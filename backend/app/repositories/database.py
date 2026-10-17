"""Local SQLite engine and transaction boundaries. No implicit schema creation."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.core.settings import ROOT


def database_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.drivername != "sqlite" or url.host or url.username or url.password or url.port or url.query or not url.database or url.database == ":memory:":
        raise ValueError("V1 requires a local file SQLite URL without URI parameters")
    raw = url.database
    if raw.startswith(("//", "\\\\", "file:")):
        raise ValueError("Network and SQLite URI paths are not supported")
    path = Path(raw)
    if path.drive and not path.is_absolute():
        raise ValueError("Drive-relative database paths are not supported")
    result = (path if path.is_absolute() else ROOT / path).resolve()
    if str(result).startswith(("//", "\\\\")):
        raise ValueError("Network paths are not supported")
    return result


def make_engine(database_url: str, *, create=False):
    path = database_path(database_url)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.is_file():
        raise FileNotFoundError("Database is not initialized; run the explicit upgrade command")
    engine = create_engine("sqlite:///" + path.as_posix(), connect_args={"timeout": 10})

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        # Own BEGIN explicitly, including DDL and SAVEPOINTs on Python sqlite3.
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.close()

    @event.listens_for(engine, "begin")
    def begin(connection):
        mode = connection.get_execution_options().get("sqlite_transaction_mode", "DEFERRED")
        if mode not in ("DEFERRED", "IMMEDIATE"):
            raise ValueError("Unsupported SQLite transaction mode")
        connection.exec_driver_sql("BEGIN " + mode)

    return engine


@contextmanager
def unit_of_work(engine, *, immediate=False):
    """One commit or full rollback; application writers use immediate=True."""
    with engine.connect() as connection:
        if immediate:
            connection = connection.execution_options(sqlite_transaction_mode="IMMEDIATE")
        with connection.begin():
            with Session(bind=connection, expire_on_commit=False) as session:
                yield session
                session.flush()


def schema_status(database_url: str) -> str:
    """Read-only probe: health requests never create, upgrade, or change journal mode."""
    path = database_path(database_url)
    if not path.is_file():
        return "NOT_INITIALIZED"
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as connection:
            rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
            return "READY" if rows == [("0003_jobs",)] else "OUTDATED"
    except sqlite3.DatabaseError:
        return "UNAVAILABLE"
