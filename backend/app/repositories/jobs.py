"""Short IMMEDIATE transactions, durable attempts, idempotency and fencing tokens."""
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import random
import re
from uuid import uuid4

from sqlalchemy import or_, select

from backend.app.domain.errors import DomainError
from .database import unit_of_work
from .models import Job, JobAttempt, JobCheckpoint, WorkerRuntime
from .types import utc_now


ERROR_CODES = frozenset({"TRANSIENT_ERROR", "RATE_LIMITED", "TIMEOUT", "AUTH_FAILED", "FILE_MISSING",
    "FILE_TOO_LARGE", "FILE_INTEGRITY_MISMATCH", "STORAGE_ERROR", "HANDLER_NOT_AVAILABLE",
    "INVALID_PAYLOAD", "JOB_FAILED", "LEASE_EXPIRED", "WORKER_STOPPED", "CANCELLED"})
TERMINAL = frozenset({"SUCCEEDED", "PARTIAL_FAILED", "FAILED", "CANCELLED", "INTERRUPTED"})


def canonical(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(raw.encode("utf-8")) > 65536:
        raise DomainError("JOB_PAYLOAD_TOO_LARGE")
    return raw


@dataclass(frozen=True)
class Claim:
    job_id: str
    execution_id: str
    token: str
    owner: str
    kind: str
    payload_json: str


class JobQueue:
    def __init__(self, engine, *, lease_seconds=30, clock=utc_now, jitter=random.random):
        if lease_seconds < 1:
            raise ValueError("Positive lease required")
        self.engine, self.lease_seconds, self.clock, self.jitter = engine, lease_seconds, clock, jitter

    @staticmethod
    def enqueue_in(session, *, kind, payload, idempotency_key, batch_id=None, max_attempts=3):
        """The upload/business service can register work in its OWN transaction."""
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", kind):
            raise DomainError("JOB_KIND_INVALID")
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 200:
            raise DomainError("IDEMPOTENCY_KEY_REQUIRED")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10 or not isinstance(payload, dict):
            raise DomainError("JOB_PAYLOAD_INVALID")
        request = canonical({"kind":kind, "payload":payload, "batch_id":batch_id, "max_attempts":max_attempts})
        digest = hashlib.sha256(request.encode("utf-8")).hexdigest()
        dedup = hashlib.sha256(canonical([kind, batch_id, idempotency_key]).encode("utf-8")).hexdigest()
        existing = session.scalar(select(Job).where(Job.dedup_key == dedup))
        if existing is not None:
            if existing.request_hash != digest:
                raise DomainError("IDEMPOTENCY_KEY_REUSED")
            return existing
        identifier = str(uuid4())
        job = Job(id=identifier, execution_id=identifier, kind=kind, batch_id=batch_id,
                  payload=json.loads(canonical(payload)), dedup_key=dedup, request_hash=digest,
                  max_attempts=max_attempts)
        session.add(job)
        session.flush()
        return job

    def enqueue(self, **kwargs):
        with unit_of_work(self.engine, immediate=True) as session:
            return self.enqueue_in(session, **kwargs)

    def get(self, job_id):
        with unit_of_work(self.engine) as session:
            job = session.get(Job, str(job_id))
            if job is None:
                raise DomainError("JOB_NOT_FOUND")
            retry = session.scalar(select(Job.id).where(Job.retry_parent_id == job.id))
            session.expunge(job)
            return job, retry

    def acquire_worker(self, owner):
        now = self.clock()
        with unit_of_work(self.engine, immediate=True) as session:
            row = session.get(WorkerRuntime, "primary")
            if row is not None and row.owner != owner and row.lease_expires_at > now:
                raise DomainError("WORKER_BUSY")
            if row is None:
                row = WorkerRuntime(name="primary", owner=owner)
                session.add(row)
            row.owner, row.heartbeat_at = owner, now
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)

    def _runtime(self, session, owner, now):
        row = session.get(WorkerRuntime, "primary")
        if row is None or row.owner != owner or row.lease_expires_at <= now:
            raise DomainError("LEASE_LOST")
        return row

    def release_worker(self, owner):
        with unit_of_work(self.engine, immediate=True) as session:
            row = session.get(WorkerRuntime, "primary")
            if row is not None and row.owner == owner:
                row.lease_expires_at = self.clock()

    def renew(self, owner, claim=None):
        now = self.clock()
        with unit_of_work(self.engine, immediate=True) as session:
            row = self._runtime(session, owner, now)
            row.heartbeat_at, row.lease_expires_at = now, now + timedelta(seconds=self.lease_seconds)
            if claim is not None:
                job = self._leased(session, claim, now, allow_cancel=True)
                # Heartbeats don't invalidate the user's cancellation version.
                session.execute(Job.__table__.update().where(Job.id == job.id).values(
                    heartbeat_at=now, lease_expires_at=row.lease_expires_at))
                return job.cancel_requested
        return False

    def recover_expired(self, owner):
        now = self.clock()
        with unit_of_work(self.engine, immediate=True) as session:
            self._runtime(session, owner, now)
            jobs = session.scalars(select(Job).where(Job.state == "RUNNING",
                or_(Job.lease_expires_at.is_(None), Job.lease_expires_at <= now))).all()
            for job in jobs:
                attempt = session.get(JobAttempt, job.lease_owner) if job.lease_owner else None
                if attempt is not None and attempt.state == "RUNNING":
                    attempt.state, attempt.finished_at = "INTERRUPTED", now
                    attempt.error = {"code":"LEASE_EXPIRED", "retryable":False}
                job.state, job.stage, job.updated_at = "INTERRUPTED", "INTERRUPTED", now
                job.error = {"code":"LEASE_EXPIRED", "retryable":False}
                job.lease_owner, job.lease_expires_at = None, None
            return len(jobs)

    def claim(self, owner):
        now = self.clock()
        with unit_of_work(self.engine, immediate=True) as session:
            self._runtime(session, owner, now)
            job = session.scalar(select(Job).where(Job.state == "QUEUED", Job.cancel_requested.is_(False),
                Job.attempts < Job.max_attempts,
                or_(Job.available_at.is_(None), Job.available_at <= now)).order_by(Job.created_at, Job.id).limit(1))
            if job is None:
                return None
            token = str(uuid4())
            job.state, job.stage, job.lease_owner = "RUNNING", "STARTING", token
            job.available_at = None
            job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            job.heartbeat_at, job.updated_at = now, now
            job.attempts += 1
            session.add(JobAttempt(id=token, job_id=job.id, attempt_no=job.attempts,
                worker_id=owner, state="RUNNING", started_at=now))
            return Claim(job.id, job.execution_id or job.id, token, owner, job.kind, canonical(job.payload))

    def _leased(self, session, claim, now, *, allow_cancel=False):
        self._runtime(session, claim.owner, now)
        job = session.get(Job, claim.job_id)
        if (job is None or job.state != "RUNNING" or job.lease_owner != claim.token or
                job.lease_expires_at is None or job.lease_expires_at <= now):
            raise DomainError("LEASE_LOST")
        if job.cancel_requested and not allow_cancel:
            raise DomainError("JOB_CANCELLED")
        return job

    def check(self, claim):
        with unit_of_work(self.engine) as session:
            self._leased(session, claim, self.clock())

    def progress(self, claim, *, stage, total):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", stage) or type(total) is not int or total < 0:
            raise DomainError("JOB_PROGRESS_INVALID")
        with unit_of_work(self.engine, immediate=True) as session:
            job = self._leased(session, claim, self.clock())
            if total < job.progress_done:
                raise DomainError("JOB_PROGRESS_INVALID")
            job.stage, job.progress_total, job.updated_at = stage, total, self.clock()

    def cached(self, claim, item_key):
        with unit_of_work(self.engine) as session:
            self._leased(session, claim, self.clock())
            row = session.scalar(select(JobCheckpoint).where(JobCheckpoint.execution_id == claim.execution_id,
                                                            JobCheckpoint.item_key == item_key))
            return None if row is None else json.loads(canonical(row.result_ref))

    def checkpoint(self, claim, item_key, result):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", item_key):
            raise DomainError("CHECKPOINT_KEY_INVALID")
        raw = canonical(result)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with unit_of_work(self.engine, immediate=True) as session:
            job = self._leased(session, claim, self.clock())
            previous = session.scalar(select(JobCheckpoint).where(JobCheckpoint.execution_id == claim.execution_id,
                                                                  JobCheckpoint.item_key == item_key))
            if previous is not None:
                if previous.payload_sha256 != digest:
                    raise DomainError("CHECKPOINT_CONFLICT")
                return
            if job.progress_total is None or job.progress_done >= job.progress_total:
                raise DomainError("JOB_PROGRESS_INVALID")
            session.add(JobCheckpoint(execution_id=claim.execution_id, attempt_id=claim.token,
                item_key=item_key, result_ref=json.loads(raw), payload_sha256=digest))
            job.progress_done += 1
            job.updated_at = self.clock()

    def finish(self, claim, *, result=None, error_code=None, retryable=False, retry_after=None, cancelled=False, interrupted=False):
        if error_code is not None and error_code not in ERROR_CODES:
            raise DomainError("JOB_ERROR_CODE_INVALID")
        now = self.clock()
        raw = canonical(result) if result is not None else None
        with unit_of_work(self.engine, immediate=True) as session:
            job = self._leased(session, claim, now, allow_cancel=True)
            attempt = session.get(JobAttempt, claim.token)
            if job.cancel_requested or cancelled:
                state, error_code, retryable = "CANCELLED", "CANCELLED", False
            elif interrupted:
                state, error_code, retryable = "INTERRUPTED", "WORKER_STOPPED", False
            elif error_code is None:
                if job.progress_total is None or job.progress_done != job.progress_total or result is None:
                    state, error_code, retryable = "FAILED", "JOB_FAILED", False
                else:
                    state = "SUCCEEDED"
            else:
                state = "PARTIAL_FAILED" if job.progress_done else "FAILED"
            attempt.state, attempt.finished_at = state, now
            attempt.error = None if error_code is None else {"code":error_code, "retryable":retryable}
            job.error = attempt.error
            job.result_ref = json.loads(raw) if raw is not None else None
            if error_code and retryable and state != "CANCELLED" and job.attempts < job.max_attempts:
                delay = min(300, 2 ** job.attempts) + self.jitter()
                if retry_after is not None:
                    delay = max(delay, retry_after)
                job.available_at = now + timedelta(seconds=delay)
                state = "QUEUED"
            job.state, job.stage, job.updated_at = state, state, now
            job.lease_owner, job.lease_expires_at = None, None

    def cancel(self, job_id, expected_version):
        if type(expected_version) is not int or expected_version < 1:
            raise DomainError("VERSION_CONFLICT")
        with unit_of_work(self.engine, immediate=True) as session:
            job = session.get(Job, str(job_id))
            if job is None:
                raise DomainError("JOB_NOT_FOUND")
            if job.cancel_requested:
                return job
            if job.version != expected_version:
                raise DomainError("VERSION_CONFLICT")
            if job.state not in ("QUEUED", "RUNNING"):
                raise DomainError("ACTION_BLOCKED")
            job.cancel_requested, job.updated_at = True, self.clock()
            if job.state == "QUEUED":
                job.state, job.stage = "CANCELLED", "CANCELLED"
            session.flush()
            return job

    def retry(self, job_id, expected_version):
        if type(expected_version) is not int or expected_version < 1:
            raise DomainError("VERSION_CONFLICT")
        with unit_of_work(self.engine, immediate=True) as session:
            old = session.get(Job, str(job_id))
            if old is None:
                raise DomainError("JOB_NOT_FOUND")
            if old.version != expected_version:
                raise DomainError("VERSION_CONFLICT")
            if old.state not in ("FAILED", "PARTIAL_FAILED", "INTERRUPTED", "CANCELLED"):
                raise DomainError("ACTION_BLOCKED")
            existing = session.scalar(select(Job).where(Job.retry_parent_id == old.id))
            if existing is not None:
                return existing
            job = Job(id=str(uuid4()), kind=old.kind, batch_id=old.batch_id,
                execution_id=old.execution_id or old.id, retry_parent_id=old.id,
                payload=json.loads(canonical(old.payload)), request_hash=old.request_hash,
                max_attempts=old.max_attempts, progress_done=old.progress_done, progress_total=old.progress_total)
            session.add(job)
            session.flush()
            return job
