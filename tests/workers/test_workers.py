"""T07 isolated storage, queue, worker and HTTP fault/concurrency tests."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Event
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.settings import ROOT, Settings
from backend.app.domain.errors import DomainError
from backend.app.main import create_app
from backend.app.repositories.database import make_engine, schema_status, unit_of_work
from backend.app.repositories.jobs import JobQueue
from backend.app.repositories.migration import check, upgrade
from backend.app.repositories.models import Job, JobAttempt, JobCheckpoint, Quotation, WorkerRuntime
from backend.app.storage import LocalStorage, StorageError
from backend.workers.runner import JobFailure, Worker


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 17, tzinfo=timezone.utc)
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class Foundation(unittest.TestCase):
    def setUp(self):
        root = ROOT / "data/test-tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="t07-", dir=root)
        self.root = Path(self.temp.name)
        self.url = "sqlite:///" + (self.root / "queue.sqlite3").as_posix()
        upgrade(self.url, backup=False)
        self.engine = make_engine(self.url)
        self.clock = Clock()
        self.queue = JobQueue(self.engine, lease_seconds=10, clock=self.clock, jitter=lambda:0)
        self.storage = LocalStorage(self.root / "storage")

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def enqueue(self, kind="TEST", payload=None, key="test", **kwargs):
        return self.queue.enqueue(kind=kind, payload={} if payload is None else payload, idempotency_key=key, **kwargs)

    def claim(self):
        owner = str(uuid4())
        self.queue.acquire_worker(owner)
        return self.queue.claim(owner)

    def row(self, job):
        return self.queue.get(job.id)[0]

    def count(self, model):
        with Session(self.engine) as session:
            return session.scalar(select(func.count()).select_from(model))


class StorageTests(Foundation):
    def test_private_storage_cannot_be_configured_under_served_frontend(self):
        from pydantic import ValidationError
        for folder in (ROOT / "frontend/dist/assets/private", ROOT / "contracts/generated/private"):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None, storage_root=folder)

    def test_stream_hash_and_private_generated_key(self):
        payload = b"synthetic quotation bytes"
        stored = self.storage.put(io.BytesIO(payload), namespace="sources")
        self.assertEqual(stored.sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(stored.byte_size, len(payload))
        self.assertRegex(stored.key, r"^sources/[0-9a-f]{32}/original$")
        with self.storage.open(stored.key) as stream:
            self.assertEqual(stream.read(), payload)

    def test_existing_original_is_never_overwritten(self):
        identifier = uuid4()
        old = self.storage.put(io.BytesIO(b"old"), namespace="sources", object_id=identifier)
        with self.assertRaises(StorageError):
            self.storage.put(io.BytesIO(b"new"), namespace="sources", object_id=identifier)
        with self.storage.open(old.key) as stream:
            self.assertEqual(stream.read(), b"old")
        reused = self.storage.put(io.BytesIO(b"old"), namespace="sources", object_id=identifier, reuse_identical=True)
        self.assertEqual(reused, old)

    def test_bad_validator_cannot_publish_or_overwrite_exports(self):
        old = self.storage.put(io.BytesIO(b"old export"), namespace="exports")
        def fail(path):
            raise ValueError("invalid synthetic workbook")
        with self.assertRaises(ValueError):
            self.storage.put(io.BytesIO(b"broken export"), namespace="exports", validate=fail)
        self.assertEqual(list((self.storage.root / "exports").glob("*/artifact.xlsx")), [self.storage.root / old.key])
        self.assertEqual(list((self.storage.root / "temporary").glob("*")), [])

    def test_validator_cannot_change_the_hashed_bytes(self):
        def change(path):
            path.write_bytes(b"changed")
        with self.assertRaisesRegex(StorageError, "VALIDATOR_CHANGED_CONTENT"):
            self.storage.put(io.BytesIO(b"original"), namespace="exports", validate=change)

    def test_size_limit_streaming_and_cleanup(self):
        storage = LocalStorage(self.storage.root, max_bytes=3)
        with self.assertRaisesRegex(StorageError, "FILE_TOO_LARGE"):
            storage.put(io.BytesIO(b"four"), namespace="sources")
        self.assertEqual(list((storage.root / "temporary").glob("*")), [])
        self.assertFalse((storage.root / "sources").exists())

    def test_incomplete_stream_never_becomes_published(self):
        class Failing:
            def read(self, count):
                raise OSError("synthetic disk/network failure")
        with self.assertRaises(OSError):
            self.storage.put(Failing(), namespace="sources")
        self.assertEqual(list((self.storage.root / "temporary").glob("*")), [])

    def test_filename_traversal_encoded_paths_and_drive_names_rejected(self):
        for key in ("../secret", "sources/../../.env", "C:/secret", "\\\\server\\share", "/etc/passwd", "sources/%2e%2e/original", "sources/"+uuid4().hex+"/artifact.xlsx"):
            with self.subTest(key=key), self.assertRaises(StorageError):
                with self.storage.open(key):
                    pass

    def test_changed_original_is_detected(self):
        stored = self.storage.put(io.BytesIO(b"original"), namespace="sources")
        (self.storage.root / stored.key).write_bytes(b"tampered")
        with self.assertRaisesRegex(StorageError, "FILE_INTEGRITY_MISMATCH"):
            self.storage.verify(stored.key, stored.sha256)

    def test_symlink_or_junction_cannot_escape_storage(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.storage.root.mkdir()
        link = self.storage.root / "sources"
        if os.name == "nt":
            command = ["cmd", "/c", "mklink", "/J", str(link), str(outside)]
            made = subprocess.run(command, capture_output=True)
            if made.returncode:
                self.skipTest("Cannot create a Windows junction in this environment")
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaisesRegex(StorageError, "STORAGE_LINK_FORBIDDEN"):
                self.storage.put(io.BytesIO(b"data"), namespace="sources")
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            # Remove only the tested link, never the target directory.
            if os.name == "nt":
                link.rmdir()
            else:
                link.unlink()


class QueueTests(Foundation):
    def test_same_request_is_idempotent_but_changed_request_is_refused(self):
        a = self.enqueue(payload={"value":"a"})
        b = self.enqueue(payload={"value":"a"})
        self.assertEqual(a.id, b.id)
        with self.assertRaisesRegex(DomainError, "IDEMPOTENCY_KEY_REUSED"):
            self.enqueue(payload={"value":"b"})
        self.assertEqual(self.count(Job), 1)

    def test_business_and_enqueue_share_one_transaction(self):
        with self.assertRaises(RuntimeError), unit_of_work(self.engine, immediate=True) as session:
            JobQueue.enqueue_in(session, kind="TEST", payload={}, idempotency_key="transaction")
            raise RuntimeError("synthetic business rollback")
        self.assertEqual(self.count(Job), 0)

    def test_concurrent_duplicate_enqueue_and_claim_only_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: self.enqueue().id, range(4)))
        self.assertEqual(len(set(ids)), 1)
        owner = str(uuid4())
        self.queue.acquire_worker(owner)
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: self.queue.claim(owner), range(4)))
        self.assertEqual(sum(c is not None for c in claims), 1)
        self.assertEqual(self.count(JobAttempt), 1)

    def test_only_one_active_worker_and_live_work_not_interrupted(self):
        self.enqueue()
        claim = self.claim()
        with self.assertRaisesRegex(DomainError, "WORKER_BUSY"):
            self.queue.acquire_worker(str(uuid4()))
        self.assertEqual(self.queue.recover_expired(claim.owner), 0)
        self.assertEqual(self.queue.get(claim.job_id)[0].state, "RUNNING")

    def test_expired_work_interrupted_old_token_cannot_write(self):
        job = self.enqueue()
        old = self.claim()
        self.clock.advance(11)
        owner = str(uuid4())
        self.queue.acquire_worker(owner)
        self.assertEqual(self.queue.recover_expired(owner), 1)
        self.assertEqual(self.row(job).state, "INTERRUPTED")
        for operation in (lambda:self.queue.progress(old, stage="LATE", total=1),
                          lambda:self.queue.checkpoint(old,"late",{}),
                          lambda:self.queue.finish(old,result={"late":True})):
            with self.assertRaisesRegex(DomainError, "LEASE_LOST"):
                operation()
        self.assertEqual(self.count(Quotation), 0)

    def test_heartbeat_keeps_work_live_without_changing_cancel_version(self):
        job = self.enqueue()
        claim = self.claim()
        version = self.row(job).version
        self.clock.advance(6)
        self.queue.renew(claim.owner, claim)
        self.clock.advance(6)
        self.queue.check(claim)
        self.assertEqual(self.row(job).version, version)

    def test_cancel_queued_is_immediate_and_repeat_safe(self):
        job = self.enqueue()
        self.queue.cancel(job.id, job.version)
        self.queue.cancel(job.id, job.version)
        self.assertEqual(self.row(job).state, "CANCELLED")
        self.assertIsNone(self.claim())

    def test_cancel_running_prevents_checkpoint_and_success(self):
        job = self.enqueue()
        claim = self.claim()
        self.queue.progress(claim, stage="TEST", total=1)
        self.queue.cancel(job.id, self.row(job).version)
        with self.assertRaisesRegex(DomainError, "JOB_CANCELLED"):
            self.queue.checkpoint(claim, "late", {})
        self.queue.finish(claim, result={"should_not_apply":True})
        self.assertEqual(self.row(job).state, "CANCELLED")
        self.assertEqual(self.count(JobCheckpoint), 0)

    def test_transient_retry_respects_backoff_and_retry_after(self):
        job = self.enqueue()
        claim = self.claim()
        self.queue.finish(claim, error_code="RATE_LIMITED", retryable=True, retry_after=20)
        self.assertEqual(self.row(job).state, "QUEUED")
        self.assertIsNone(self.queue.claim(claim.owner))
        self.clock.advance(20)
        self.queue.acquire_worker(claim.owner)
        claim2 = self.queue.claim(claim.owner)
        self.assertIsNotNone(claim2)
        self.assertNotEqual(claim.token, claim2.token)
        self.assertEqual(self.count(JobAttempt), 2)

    def test_permanent_failure_does_not_retry(self):
        job = self.enqueue()
        claim = self.claim()
        self.queue.finish(claim, error_code="AUTH_FAILED")
        self.assertEqual(self.row(job).state, "FAILED")
        self.assertIsNone(self.queue.claim(claim.owner))

    def test_maximum_attempts_is_enforced(self):
        job = self.enqueue(max_attempts=2)
        claim = self.claim()
        self.queue.finish(claim, error_code="TIMEOUT", retryable=True)
        self.clock.advance(3)
        second = self.queue.claim(claim.owner)
        self.queue.finish(second, error_code="TIMEOUT", retryable=True)
        self.assertEqual(self.row(job).state, "FAILED")
        self.assertEqual(self.row(job).attempts, 2)
        self.assertIsNone(self.queue.claim(claim.owner))

    def test_explicit_retry_is_new_job_and_successful_unit_is_reused(self):
        job = self.enqueue()
        claim = self.claim()
        self.queue.progress(claim, stage="FILES", total=2)
        self.queue.checkpoint(claim, "file_a", {"done":True})
        self.queue.finish(claim, error_code="JOB_FAILED")
        old = self.row(job)
        self.assertEqual(old.state, "PARTIAL_FAILED")
        retry = self.queue.retry(job.id, old.version)
        self.assertNotEqual(retry.id, job.id)
        self.assertEqual(self.queue.retry(job.id, old.version).id, retry.id)
        resumed = self.queue.claim(claim.owner)
        self.assertEqual(self.queue.cached(resumed, "file_a"), {"done":True})
        self.queue.checkpoint(resumed, "file_a", {"done":True})
        self.queue.checkpoint(resumed, "file_b", {"done":True})
        self.queue.finish(resumed, result={"done":2})
        self.assertEqual(self.row(retry).state, "SUCCEEDED")
        self.assertEqual(self.row(job).state, "PARTIAL_FAILED")
        self.assertEqual(self.count(JobCheckpoint), 2)

    def test_checkpoint_conflict_and_history_mutation_are_rejected(self):
        self.enqueue()
        claim = self.claim()
        self.queue.progress(claim, stage="TEST", total=1)
        self.queue.checkpoint(claim, "unit", {"value":"old"})
        with self.assertRaisesRegex(DomainError, "CHECKPOINT_CONFLICT"):
            self.queue.checkpoint(claim, "unit", {"value":"new"})
        self.queue.finish(claim, result={"done":True})
        for sql in ("DELETE FROM job_checkpoint", "UPDATE job_checkpoint SET item_key='changed'", "UPDATE job_attempt SET state='RUNNING'", "DELETE FROM job_attempt"):
            with self.subTest(sql=sql), self.assertRaises(IntegrityError), self.engine.begin() as connection:
                connection.exec_driver_sql(sql)

    def test_success_is_not_assumed_for_an_incomplete_handler(self):
        job = self.enqueue()
        claim = self.claim()
        self.queue.finish(claim, result={"claimed_success":True})
        self.assertEqual(self.row(job).state, "FAILED")

    def test_expected_version_rejects_stale_controls_and_boolean(self):
        job = self.enqueue()
        for value in (job.version + 1, True):
            with self.assertRaisesRegex(DomainError, "VERSION_CONFLICT"):
                self.queue.cancel(job.id, value)


class WorkerTests(Foundation):
    def test_independent_cli_process_runs_a_real_persistent_job(self):
        source = self.root / "synthetic-source.txt"
        source.write_bytes(b"synthetic independent worker source")
        env = {**os.environ, "DATABASE_URL":self.url, "STORAGE_ROOT":str(self.storage.root),
               "PYTHONUTF8":"1", "WORKER_LEASE_SECONDS":"5", "WORKER_HEARTBEAT_SECONDS":".2"}
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        command = [sys.executable, "-m", "backend.workers", "enqueue-verify", str(source), "--key", "independent"]
        first = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20, creationflags=flags)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20, creationflags=flags)
        self.assertEqual(second.returncode, 0, second.stderr)
        identifier = json.loads(first.stdout)["job_id"]
        self.assertEqual(identifier, json.loads(second.stdout)["job_id"])
        result = subprocess.run([sys.executable, "-m", "backend.workers", "run", "--once"], cwd=ROOT, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=20, creationflags=flags)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.queue.get(identifier)[0].state, "SUCCEEDED")
        self.assertEqual(self.count(Job), 1)

    def test_killed_process_recovers_as_interrupted_not_success(self):
        queue = JobQueue(self.engine, lease_seconds=2)
        job = queue.enqueue(kind="WAIT", payload={}, idempotency_key="crash")
        code = '''
import os, time
from pathlib import Path
from backend.app.repositories.database import make_engine
from backend.app.repositories.jobs import JobQueue
from backend.app.storage import LocalStorage
from backend.workers.runner import Worker
engine=make_engine(os.environ["DATABASE_URL"])
queue=JobQueue(engine,lease_seconds=2)
def waiting(context,payload):
    context.progress("WAITING",1)
    while True: time.sleep(.1)
with Worker(queue,LocalStorage(Path(os.environ["STORAGE_ROOT"])),handlers={"WAIT":waiting},heartbeat_seconds=.2) as worker:
    worker.run()
'''
        env = {**os.environ, "DATABASE_URL":self.url, "STORAGE_ROOT":str(self.storage.root), "PYTHONUTF8":"1"}
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with subprocess.Popen([sys.executable,"-c",code], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, creationflags=flags) as child:
            try:
                deadline = time.monotonic()+10
                while queue.get(job.id)[0].state != "RUNNING":
                    if child.poll() is not None:
                        self.fail("Owned child worker exited before claiming")
                    if time.monotonic()>deadline:
                        self.fail("Owned child worker did not claim before deadline")
                    time.sleep(.05)
            finally:
                child.kill()
                child.wait(timeout=5)
        self.assertEqual(queue.get(job.id)[0].state, "RUNNING")
        time.sleep(2.3)
        owner=str(uuid4())
        queue.acquire_worker(owner)
        self.assertEqual(queue.recover_expired(owner), 1)
        self.assertEqual(queue.get(job.id)[0].state, "INTERRUPTED")
        self.assertEqual(self.count(Quotation), 0)

    def test_real_verify_file_worker_and_idempotent_result(self):
        stored = self.storage.put(io.BytesIO(b"synthetic source"), namespace="sources")
        job = self.enqueue("VERIFY_FILE", {"storage_key":stored.key, "sha256":stored.sha256})
        with Worker(self.queue, self.storage, heartbeat_seconds=1) as worker:
            self.assertTrue(worker.run_once())
            self.assertFalse(worker.run_once())
        current = self.row(job)
        self.assertEqual(current.state, "SUCCEEDED")
        self.assertEqual((current.progress_done, current.progress_total), (1, 1))
        self.storage.verify(current.result_ref["storage_key"], current.result_ref["sha256"])
        self.assertEqual(self.count(JobAttempt), 1)
        self.assertEqual(self.count(Quotation), 0)

    def test_unsupported_handler_and_invalid_payload_do_not_fake_success(self):
        for kind, payload in (("OCR_NOT_INSTALLED", {}), ("VERIFY_FILE", {})):
            job = self.enqueue(kind, payload, key=kind)
            with Worker(self.queue, self.storage, heartbeat_seconds=1) as worker:
                worker.run_once()
            self.assertEqual(self.row(job).state, "FAILED")

    def test_raw_private_exception_is_not_saved(self):
        job = self.enqueue()
        def fail(context, payload):
            raise RuntimeError("synthetic-private-key-and-path")
        with Worker(self.queue, self.storage, handlers={"TEST":fail}, heartbeat_seconds=1) as worker:
            worker.run_once()
        self.assertNotIn("synthetic-private", json.dumps(self.row(job).error))
        self.assertEqual(self.row(job).error["code"], "JOB_FAILED")

    def test_worker_auto_retry_skips_completed_units(self):
        job = self.enqueue()
        calls = []
        def handler(context, payload):
            context.progress("FILES", 2)
            if context.cached("a") is None:
                calls.append("a")
                context.checkpoint("a", {"done":True})
                raise JobFailure("TIMEOUT", retryable=True)
            calls.append("b")
            context.checkpoint("b", {"done":True})
            return {"done":2}
        with Worker(self.queue, self.storage, handlers={"TEST":handler}, heartbeat_seconds=1) as worker:
            worker.run_once()
            self.clock.advance(3)
            worker.run_once()
        self.assertEqual(calls, ["a", "b"])
        self.assertEqual(self.row(job).state, "SUCCEEDED")

    def test_cancel_during_handler_blocks_later_results(self):
        job = self.enqueue()
        def handler(context, payload):
            context.progress("MODEL_CALL", 1)
            self.queue.cancel(job.id, self.row(job).version)
            return {"provider_returned_after_cancel":True}
        with Worker(self.queue, self.storage, handlers={"TEST":handler}, heartbeat_seconds=1) as worker:
            worker.run_once()
        self.assertEqual(self.row(job).state, "CANCELLED")
        self.assertEqual(self.count(JobCheckpoint), 0)

    def test_keyboard_interrupt_never_becomes_success(self):
        job = self.enqueue()
        def handler(context, payload):
            context.progress("TEST", 1)
            context.checkpoint("done", {})
            raise KeyboardInterrupt
        with Worker(self.queue, self.storage, handlers={"TEST":handler}, heartbeat_seconds=1) as worker:
            with self.assertRaises(KeyboardInterrupt):
                worker.run_once()
        self.assertEqual(self.row(job).state, "INTERRUPTED")

    def test_heartbeat_continues_while_handler_is_blocked(self):
        queue = JobQueue(self.engine, lease_seconds=2)
        job = queue.enqueue(kind="TEST", payload={}, idempotency_key="real-heartbeat")
        def handler(context, payload):
            context.progress("BLOCKED_IO", 1)
            time.sleep(2.5)
            context.check()
            context.checkpoint("finished", {})
            return {"done":True}
        with Worker(queue, self.storage, handlers={"TEST":handler}, heartbeat_seconds=.2) as worker:
            worker.run_once()
        self.assertEqual(queue.get(job.id)[0].state, "SUCCEEDED")


class HTTPAndMigrationTests(Foundation):
    def client(self):
        return TestClient(create_app(Settings(_env_file=None, database_url=self.url)), base_url="http://127.0.0.1:8000")

    @staticmethod
    def headers(client):
        token = client.get("/api/v1/bootstrap").json()["csrf_token"]
        return {"Origin":"http://127.0.0.1:5173", "X-CSRF-Token":token}

    def test_job_status_requires_a_valid_session_and_never_exposes_payload(self):
        job = self.enqueue(payload={"private":"synthetic-secret-path"})
        with self.client() as client:
            self.assertEqual(client.get("/api/v1/jobs/"+job.id).status_code, 403)
            self.headers(client)
            response = client.get("/api/v1/jobs/"+job.id)
            self.assertEqual(response.status_code, 200)
            for forbidden in ("synthetic-secret", "payload", "lease_owner", "result_ref", "storage_key"):
                self.assertNotIn(forbidden, response.text)

    def test_cancel_csrf_version_and_not_found(self):
        job = self.enqueue()
        with self.client() as client:
            headers = self.headers(client)
            path = "/api/v1/jobs/"+job.id+"/cancel"
            self.assertEqual(client.post(path, json={"expected_version":1}).status_code, 403)
            self.assertEqual(client.post(path, json={"expected_version":2}, headers=headers).status_code, 409)
            self.assertEqual(client.post(path, json={"expected_version":True}, headers=headers).status_code, 422)
            self.assertEqual(client.post(path, json={"expected_version":1}, headers=headers).json()["state"], "CANCELLED")
            self.assertEqual(client.get("/api/v1/jobs/"+str(uuid4())).status_code, 404)

    def test_runtime_job_controls_declare_session_and_csrf(self):
        with self.client() as client:
            paths = client.get("/api/v1/openapi.json").json()["paths"]
            for action in ("cancel", "retry"):
                operation = paths["/api/v1/jobs/{id}/"+action]["post"]
                self.assertEqual(operation["security"], [{"LocalSessionCookie":[]}])
                self.assertEqual({p["name"] for p in operation["parameters"]}, {"id", "Origin", "X-CSRF-Token"})

    def test_http_retry_returns_one_new_job_and_old_result_stays(self):
        job = self.enqueue()
        claim = self.claim()
        self.queue.finish(claim, error_code="JOB_FAILED")
        old = self.row(job)
        with self.client() as client:
            headers = self.headers(client)
            path = "/api/v1/jobs/"+job.id+"/retry"
            first = client.post(path, json={"expected_version":old.version}, headers=headers)
            second = client.post(path, json={"expected_version":old.version}, headers=headers)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["id"], second.json()["id"])
            self.assertNotEqual(first.json()["id"], job.id)
            self.assertEqual(client.get("/api/v1/jobs/"+job.id).json()["state"], "FAILED")

    def test_missing_database_returns_503_without_creating_it(self):
        path = self.root / "missing.sqlite3"
        settings = Settings(_env_file=None, database_url="sqlite:///"+path.as_posix())
        with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
            self.headers(client)
            response = client.get("/api/v1/jobs/"+str(uuid4()))
            self.assertEqual(response.status_code, 503)
        self.assertFalse(path.exists())

    def test_t05_database_upgrade_keeps_existing_job(self):
        path = self.root / "old.sqlite3"
        url = "sqlite:///"+path.as_posix()
        upgrade(url, "0002_history_guards", backup=False)
        identifier = str(uuid4())
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("INSERT INTO job(id,kind,state,attempts,max_attempts,cancel_requested,payload,created_at,updated_at,version) VALUES (?,'TEST','RUNNING',1,3,0,'{}','2026-10-17 00:00:00','2026-10-17 00:00:00',1)", (identifier,))
            connection.commit()
        backup = upgrade(url)
        self.assertTrue(backup.is_file())
        engine = make_engine(url)
        queue = JobQueue(engine, clock=self.clock)
        owner = str(uuid4())
        queue.acquire_worker(owner)
        self.assertEqual(queue.recover_expired(owner), 1)
        self.assertEqual(queue.get(identifier)[0].state, "INTERRUPTED")
        self.assertEqual(schema_status(url), "READY")
        check(url)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
