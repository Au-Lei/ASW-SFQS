"""python -m backend.workers run [--once] | enqueue-verify FILE --key KEY"""
import argparse
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from backend.app.core.settings import Settings
from backend.app.repositories.database import make_engine, schema_status
from backend.app.repositories.jobs import JobQueue
from backend.app.storage import LocalStorage
from .runner import Worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--once", action="store_true")
    verify = commands.add_parser("enqueue-verify")
    verify.add_argument("file", type=Path)
    verify.add_argument("--key", required=True)
    args = parser.parse_args()
    settings = Settings()
    if schema_status(settings.database_url) != "READY":
        raise SystemExit("Database schema is not ready. Run the explicit database upgrade first.")
    engine = make_engine(settings.database_url)
    queue = JobQueue(engine, lease_seconds=settings.worker_lease_seconds)
    storage = LocalStorage(settings.storage_root, max_bytes=settings.storage_max_file_bytes)
    try:
        if args.command == "enqueue-verify":
            with args.file.open("rb") as stream:
                stored = storage.put(stream, namespace="sources", reuse_identical=True,
                    object_id=uuid5(NAMESPACE_URL, "ASW-SFQS/diagnostic-upload/" + args.key))
            # CLI upload is a local diagnostic, not the T18 upload endpoint.
            job = queue.enqueue(kind="VERIFY_FILE", payload={"storage_key":stored.key, "sha256":stored.sha256},
                                idempotency_key=args.key)
            print(json.dumps({"job_id":job.id, "state":job.state}))
        else:
            with Worker(queue, storage, heartbeat_seconds=settings.worker_heartbeat_seconds) as worker:
                print("ASW worker ready; persistent queue, one active worker.", flush=True)
                if args.once:
                    worker.run_once()
                else:
                    worker.run(poll_seconds=settings.worker_poll_seconds)
    except KeyboardInterrupt:
        print("Worker stopped; incomplete work is not successful.")
    except Exception as error:
        print("Worker operation failed (" + type(error).__name__ + "); no private exception text was logged.")
        raise SystemExit(1) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
