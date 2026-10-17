"""Explicit migrations, coherent SQLite backup, and metadata drift checking."""
from contextlib import closing
from datetime import datetime, timezone
import sqlite3
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.core.settings import ROOT
from .database import database_path, make_engine


def config():
    value = Config(str(ROOT / "backend/alembic.ini"))
    value.set_main_option("script_location", str(ROOT / "backend/migrations"))
    return value


def upgrade(database_url: str, revision="head", *, backup=True):
    """Returns backup path, if upgrading a nonempty existing database.

    Refuse unknown/unversioned populated databases and backwards targets.
    All pending revisions run inside a single explicit IMMEDIATE transaction.
    """
    path = database_path(database_url)
    cfg = config()
    scripts = ScriptDirectory.from_config(cfg)
    target = scripts.get_revision(revision)
    if target is None:
        raise ValueError("An upgrade target revision is required")
    backup_path = None
    engine = make_engine(database_url, create=True)
    try:
        with engine.connect() as connection:
            connection = connection.execution_options(sqlite_transaction_mode="IMMEDIATE")
            with connection.begin():
                tables = set(connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").scalars())
                current = list(connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalars()) if "alembic_version" in tables else []
                if len(current) > 1:
                    raise ValueError("Multiple migration heads are not supported")
                if tables - {"alembic_version"} and not current:
                    raise ValueError("Refusing an unversioned populated database; controlled import is required")
                if current:
                    if current[0] == target.revision:
                        return None
                    allowed = {r.revision for r in scripts.iterate_revisions(target.revision, "base")}
                    if current[0] not in allowed:
                        raise ValueError("Target is not a forward upgrade from the current revision")
                if backup and tables:
                    directory = path.parent / "backups"
                    directory.mkdir(exist_ok=True)
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    backup_path = directory / (path.stem + "-" + stamp + "-" + uuid4().hex + ".sqlite3")
                    # Writer lock is already held; use a separate read connection
                    # so backup never deadlocks against this transaction's write lock.
                    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
                        with closing(sqlite3.connect(backup_path)) as destination:
                            source.backup(destination)
                cfg.attributes["connection"] = connection
                command.upgrade(cfg, target.revision)
    finally:
        engine.dispose()
    return backup_path


def check(database_url: str):
    engine = make_engine(database_url)
    try:
        with engine.connect() as connection:
            cfg = config()
            cfg.attributes["connection"] = connection
            command.check(cfg)
    finally:
        engine.dispose()
