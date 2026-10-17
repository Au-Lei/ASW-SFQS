"""One fenced worker with a heartbeat thread and cooperative cancellation."""
from dataclasses import dataclass
import io
import json
import math
from threading import Event, Lock, Thread
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.domain.errors import DomainError
from backend.app.repositories.jobs import ERROR_CODES
from backend.app.storage import StorageError


class JobFailure(Exception):
    def __init__(self, code="JOB_FAILED", *, retryable=False, retry_after=None):
        if code not in ERROR_CODES or (retry_after is not None and (
                not isinstance(retry_after, (int, float)) or not math.isfinite(retry_after) or not 0 <= retry_after <= 86400)):
            raise ValueError("Invalid job failure")
        self.code, self.retryable, self.retry_after = code, retryable, retry_after
        super().__init__(code)


@dataclass
class JobContext:
    queue: object
    storage: object
    claim: object
    stopping: Event
    lost: Event

    def check(self):
        if self.lost.is_set():
            raise DomainError("LEASE_LOST")
        if self.stopping.is_set():
            raise DomainError("WORKER_STOPPING")
        self.queue.check(self.claim)

    def progress(self, stage, total):
        self.check()
        self.queue.progress(self.claim, stage=stage, total=total)

    def cached(self, key):
        self.check()
        return self.queue.cached(self.claim, key)

    def checkpoint(self, key, result):
        self.check()
        self.queue.checkpoint(self.claim, key, result)


class VerifyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    storage_key: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def verify_file(context, payload):
    payload = VerifyPayload.model_validate(payload)
    context.progress("VERIFY_FILE", 1)
    context.check()
    # Even when resuming a successful checkpoint, detect altered source bytes.
    stored = context.storage.verify(payload.storage_key, payload.sha256)
    context.check()
    result = {"verified":True, "sha256":stored.sha256, "byte_size":stored.byte_size}
    context.checkpoint("verify_file", result)
    raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    artifact = context.storage.put(io.BytesIO(raw), namespace="job_results",
        object_id=uuid5(UUID(context.claim.execution_id), "verify-file-result-v1"), reuse_identical=True)
    context.check()
    return {"storage_key":artifact.key, "sha256":artifact.sha256, "byte_size":artifact.byte_size}


class Worker:
    def __init__(self, queue, storage, *, handlers=None, heartbeat_seconds=5):
        if heartbeat_seconds <= 0 or heartbeat_seconds >= queue.lease_seconds / 2:
            raise ValueError("Heartbeat must be less than half the lease")
        self.queue, self.storage = queue, storage
        self.handlers = {"VERIFY_FILE":verify_file} if handlers is None else handlers
        self.heartbeat_seconds = heartbeat_seconds
        self.owner = str(uuid4())
        self.stop_event, self.heartbeat_stop, self.lost = Event(), Event(), Event()
        self.lock = Lock()
        self.active = None
        self.thread = None

    def __enter__(self):
        self.queue.acquire_worker(self.owner)
        try:
            self.queue.recover_expired(self.owner)
            self.thread = Thread(target=self._heartbeat, name="asw-worker-heartbeat", daemon=True)
            self.thread.start()
        except Exception:
            self.queue.release_worker(self.owner)
            raise
        return self

    def _heartbeat(self):
        while not self.heartbeat_stop.wait(self.heartbeat_seconds):
            try:
                # Serialize active claim handoff against renewal, avoiding a
                # false lease loss when a finished job has just been cleared.
                with self.lock:
                    self.queue.renew(self.owner, self.active)
            except Exception:
                self.lost.set()
                self.stop_event.set()
                return

    def run_once(self):
        if self.stop_event.is_set() or self.lost.is_set():
            return False
        with self.lock:
            self.queue.renew(self.owner)
            self.queue.recover_expired(self.owner)
            claim = self.queue.claim(self.owner)
            self.active = claim
        if claim is None:
            return False
        context = JobContext(self.queue, self.storage, claim, self.stop_event, self.lost)
        result, failure, cancelled, interrupted = None, None, False, False
        try:
            handler = self.handlers.get(claim.kind)
            if handler is None:
                raise JobFailure("HANDLER_NOT_AVAILABLE")
            result = handler(context, json.loads(claim.payload_json))
            context.check()
        except JobFailure as error:
            failure = error
        except ValidationError:
            failure = JobFailure("INVALID_PAYLOAD")
        except StorageError as error:
            failure = JobFailure(error.code if error.code in ERROR_CODES else "STORAGE_ERROR")
        except DomainError as error:
            cancelled = error.code == "JOB_CANCELLED"
            interrupted = error.code in ("LEASE_LOST", "WORKER_STOPPING")
            if not cancelled and not interrupted:
                failure = JobFailure()
        except (KeyboardInterrupt, SystemExit):
            interrupted = True
            self.stop_event.set()
            raise
        except Exception:
            failure = JobFailure()  # Never store raw exception text, keys or paths.
        finally:
            with self.lock:
                try:
                    if not self.lost.is_set():
                        self.queue.finish(claim, result=result, cancelled=cancelled,
                            interrupted=interrupted,
                            error_code=failure.code if failure else None,
                            retryable=failure.retryable if failure else False,
                            retry_after=failure.retry_after if failure else None)
                except DomainError as error:
                    if error.code != "LEASE_LOST":
                        raise
                    self.lost.set()
                    self.stop_event.set()
                finally:
                    self.active = None
        return True

    def run(self, *, poll_seconds=2):
        while not self.stop_event.is_set():
            if not self.run_once():
                self.stop_event.wait(poll_seconds)

    def __exit__(self, *_):
        self.stop_event.set()
        self.heartbeat_stop.set()
        if self.thread is not None:
            self.thread.join(timeout=self.heartbeat_seconds + 2)
        try:
            # Graceful stop fences its unfinished work immediately; a killed
            # process leaves leases to expire naturally, never marks success.
            self.queue.release_worker(self.owner)
        except Exception:
            pass
