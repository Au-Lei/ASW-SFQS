"""Synthetic SQLite integration tests; no private quotations or seed import."""
from datetime import date, datetime, timezone
from contextlib import closing
from decimal import Decimal, localcontext
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.app.core.settings import ROOT, Settings
from backend.app.main import create_app
from backend.app.repositories.database import database_path, make_engine, schema_status, unit_of_work
from backend.app.repositories.migration import check, upgrade
from backend.app.repositories.datasets import DatasetVersionConflict, advance_dataset
from backend.app.repositories.models import (
    Application, AuditEvent, Base, ChangePlan, CountryRegion, DatasetSnapshot,
    DatasetVersion, Destination, DestinationAlias, Evidence, ExtractionCandidate,
    ExtractionRun, ImportBatch, LocationCodeMapping, OriginPort, Quotation,
    QuotationRevision, Region, RouteGroup, SourceFile, SourceGroup, SourceGroupFile,
    TemplateConfig,
)


HASH = "a" * 64


class DatabaseTests(unittest.TestCase):
    def test_money_round_trip_ignores_external_decimal_precision(self):
        with localcontext() as context:
            context.prec = 3
            self.populated(price_20gp="12345678901234.5678")
            with Session(self.engine) as session:
                self.assertEqual(session.get(QuotationRevision, "revision").price_20gp, Decimal("12345678901234.5678"))

    def setUp(self):
        root = ROOT / "data/test-tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="t05-", dir=root)
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.url = "sqlite:///" + self.path.as_posix()
        upgrade(self.url, backup=False)
        self.engine = make_engine(self.url)

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def count(self, cls):
        with Session(self.engine) as session:
            return session.scalar(select(func.count()).select_from(cls))

    def seed(self):
        with unit_of_work(self.engine, immediate=True) as session:
            session.add(OriginPort(id="origin", display_en="SYNTHETIC", display_zh="测试起运港"))
            session.add(CountryRegion(id="country", internal_code="TEST", name_en="SYNTHETIC", name_zh="测试地区"))
            session.add(Region(id="region", code="TEST", sheet_name="测试区域", sort_order=1))
            session.flush()
            session.add(RouteGroup(id="route", region_id="region", code="TEST", name="测试航线", sort_order=1))
            session.flush()
            session.add(Destination(id="dest", country_region_id="country", canonical_key="test:port", display_name_en="TEST PORT", display_name_zh="测试港", route_group_id="route", sort_order=1))

    def plan(self, session, *, key="plan"):
        session.add(ChangePlan(id=key, origin_port_id="origin", base_dataset_version=1, content_hash=HASH))
        session.flush()

    def application(self, session, *, key="app", plan="plan", snapshot=True, idem="request"):
        if snapshot:
            session.add(DatasetSnapshot(id="snapshot", origin_port_id="origin", dataset_version=2, payload_json={"historical_names": ["TEST PORT"]}, payload_sha256=HASH))
        session.add(Application(id=key, origin_port_id="origin", plan_id=plan, idempotency_key=idem, request_hash=HASH, before_version=1, after_version=2))
        session.flush()

    def quote(self, session, *, key="quote", rev="revision", **fields):
        session.add(Quotation(id=key, origin_port_id="origin", destination_id="dest", current_revision_id=rev))
        session.flush()
        values = dict(price_20gp="123.4567", valid_from=date(2026, 12, 25), valid_to=date(2027, 1, 5))
        values.update(fields)
        session.add(QuotationRevision(id=rev, quotation_id=key, revision_no=1, application_id="app", canonical_payload_hash=HASH, identity_snapshot={"destination_name": "TEST PORT"}, **values))
        session.flush()

    def populated(self, **fields):
        self.seed()
        with unit_of_work(self.engine, immediate=True) as session:
            self.plan(session)
            self.application(session)
            self.quote(session, **fields)

    def test_fresh_schema_is_empty_and_complete(self):
        self.assertEqual(schema_status(self.url), "READY")
        self.assertEqual(len(Base.metadata.tables), 34)
        self.assertEqual(set(inspect(self.engine).get_table_names()), set(Base.metadata.tables) | {"alembic_version"})
        self.assertEqual(self.count(Quotation), 0)
        self.assertEqual(self.count(Destination), 0)

    def test_schema_metadata_no_drift(self):
        check(self.url)

    def test_all_migrated_checks_match_metadata(self):
        inspector = inspect(self.engine)
        for table in Base.metadata.tables.values():
            with self.subTest(table=table.name):
                expected = {str(c.name) for c in table.constraints if isinstance(c, CheckConstraint)}
                actual = {c["name"] for c in inspector.get_check_constraints(table.name)}
                self.assertEqual(actual, expected)

    def test_upgrade_again_keeps_rows(self):
        self.seed()
        self.assertIsNone(upgrade(self.url))
        self.assertEqual(self.count(Destination), 1)

    def test_old_revision_upgrade_backs_up_and_preserves_data(self):
        old = "sqlite:///" + (Path(self.temp.name) / "old.sqlite3").as_posix()
        upgrade(old, "0001_core", backup=False)
        engine = make_engine(old)
        with unit_of_work(engine) as session:
            session.add(OriginPort(id="kept", display_en="KEPT", display_zh="保留"))
        engine.dispose()
        self.assertEqual(schema_status(old), "OUTDATED")
        saved = upgrade(old)
        self.assertTrue(saved.is_file())
        with closing(sqlite3.connect(saved)) as connection:
            self.assertEqual(connection.execute("SELECT version_num FROM alembic_version").fetchone()[0], "0001_core")
            self.assertEqual(connection.execute("SELECT display_en FROM origin_port").fetchone()[0], "KEPT")
        engine = make_engine(old)
        with engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT count(*) FROM origin_port").scalar(), 1)
            self.assertEqual(connection.exec_driver_sql("SELECT count(*) FROM sqlite_master WHERE type='trigger'").scalar(), 26)
        engine.dispose()

    def test_backward_upgrade_refused(self):
        with self.assertRaises(ValueError):
            upgrade(self.url, "0001_core")
        self.assertEqual(schema_status(self.url), "READY")

    def test_unversioned_populated_database_refused(self):
        path = Path(self.temp.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE important(value TEXT)")
            connection.execute("INSERT INTO important VALUES ('kept')")
            connection.commit()
        with self.assertRaises(ValueError):
            upgrade("sqlite:///" + path.as_posix())
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM important").fetchone()[0], "kept")

    def test_foreign_keys_and_wal_on_every_connection(self):
        for _ in range(2):
            with self.engine.connect() as connection:
                self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)
                self.assertEqual(connection.exec_driver_sql("PRAGMA journal_mode").scalar(), "wal")
            self.engine.dispose()
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(RouteGroup(region_id="missing", code="BAD", name="bad", sort_order=1))

    def test_same_port_multiple_quotations_allowed(self):
        self.populated()
        with unit_of_work(self.engine) as session:
            self.quote(session, key="quote2", rev="revision2", price_20gp="234.5678")
        self.assertEqual(self.count(Quotation), 2)
        self.assertEqual(self.count(QuotationRevision), 2)

    def test_destination_identity_cannot_duplicate(self):
        self.seed()
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(Destination(country_region_id="country", canonical_key="test:port", display_name_en="RENAMED", display_name_zh="改名", route_group_id="route", sort_order=2))
        self.assertNotIn("destination_route_group", Base.metadata.tables)

    def test_terminal_parent_key_uniqueness(self):
        self.seed()
        with unit_of_work(self.engine) as session:
            session.add(Destination(id="terminal", country_region_id="country", canonical_key="terminal:a", kind="TERMINAL", parent_destination_id="dest", terminal_key="a", display_name_en="A", display_name_zh="A", route_group_id="route", sort_order=2))
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(Destination(country_region_id="country", canonical_key="terminal:a2", kind="TERMINAL", parent_destination_id="dest", terminal_key="a", display_name_en="RENAMED", display_name_zh="A", route_group_id="route", sort_order=3))

    def test_money_exact_null_zero_and_cross_year(self):
        self.populated(price_40gp="0", price_40hq=None)
        with Session(self.engine) as session:
            row = session.get(QuotationRevision, "revision")
            self.assertEqual(row.price_20gp, Decimal("123.4567"))
            self.assertEqual(row.price_40gp, Decimal("0"))
            self.assertIsNone(row.price_40hq)
            self.assertEqual(row.valid_to, date(2027, 1, 5))
            self.assertIsNone(row.currency)
            self.assertEqual(row.created_at.tzinfo, timezone.utc)
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT price_20gp, typeof(price_20gp) FROM quotation_revision").one(), (1234567, "integer"))

    def test_money_rejects_float_negative_and_excess_precision(self):
        self.seed()
        for value in (1.1, -1, "-1", "0.00001", "100000000000000", Decimal("NaN")):
            with self.subTest(value=str(value)), self.assertRaises(StatementError), unit_of_work(self.engine) as session:
                self.plan(session)
                self.application(session)
                self.quote(session, price_20gp=value)
        self.assertEqual(self.count(Quotation), 0)

    def test_database_rejects_raw_noninteger_money(self):
        self.seed()
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            self.plan(session)
            self.application(session)
            session.add(Quotation(id="quote", origin_port_id="origin", destination_id="dest", current_revision_id="revision"))
            session.flush()
            session.execute(text("INSERT INTO quotation_revision(id,quotation_id,revision_no,price_20gp,sailing_weekdays,transit,routing,validity_basis,conditions,quality_flags,application_id,created_at,canonical_payload_hash,identity_snapshot) VALUES ('revision','quote',1,1.25,'[]','{}','[]','UNSPECIFIED','[]','[]','app','2026-10-17 00:00:00',:hash,'{}')"), {"hash": HASH})

    def test_missing_all_prices_and_reverse_dates_refused(self):
        self.seed()
        for fields in ({"price_20gp": None}, {"valid_from": date(2027, 1, 6)}, {"currency": "usd"}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
                self.plan(session)
                self.application(session)
                self.quote(session, **fields)

    def test_raw_invalid_calendar_date_refused(self):
        self.seed()
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.execute(text("INSERT INTO location_code_mapping(id,namespace,code_raw,code_normalized,origin_port_id,review_state,valid_from,evidence_ids,version) VALUES ('m','TEST','X','X','origin','PENDING_REVIEW','2026-02-30','[]',1)"))

    def test_revision_cannot_point_to_another_quote(self):
        self.populated()
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(Quotation(id="other", origin_port_id="origin", destination_id="dest", current_revision_id="revision"))
        self.assertEqual(self.count(Quotation), 1)

    def test_immutable_revision_snapshot_audit_template(self):
        self.populated()
        with unit_of_work(self.engine) as session:
            session.add(AuditEvent(id="audit", entity_type="test", entity_id="quote", action="CREATE", actor_label="test", request_id="test"))
            session.add(TemplateConfig(version="test", schema_version="1", checksum=HASH))
        for table in ("quotation_revision", "dataset_snapshot", "audit_event", "template_config", "application"):
            for action in ("UPDATE", "DELETE"):
                sql = f"UPDATE {table} SET " + ("checksum=checksum" if table == "template_config" else "id=id") if action == "UPDATE" else f"DELETE FROM {table}"
                with self.subTest(table=table, action=action), self.assertRaises(IntegrityError), self.engine.begin() as connection:
                    connection.exec_driver_sql(sql)

    def test_application_without_same_transaction_snapshot_rolls_back(self):
        self.seed()
        with self.assertRaises(IntegrityError), unit_of_work(self.engine, immediate=True) as session:
            self.plan(session)
            self.application(session, snapshot=False)
        self.assertEqual(self.count(Application), 0)
        self.assertEqual(self.count(ChangePlan), 0)

    def test_full_transaction_rollback(self):
        self.seed()
        with self.assertRaisesRegex(RuntimeError, "synthetic"), unit_of_work(self.engine, immediate=True) as session:
            self.plan(session)
            self.application(session)
            self.quote(session)
            raise RuntimeError("synthetic failure")
        for cls in (Application, ChangePlan, Quotation, QuotationRevision, DatasetSnapshot):
            self.assertEqual(self.count(cls), 0)

    def test_failed_migration_rolls_back_ddl_and_keeps_backup(self):
        old = "sqlite:///" + (Path(self.temp.name) / "fail.sqlite3").as_posix()
        upgrade(old, "0001_core", backup=False)
        def fail(cfg, target):
            cfg.attributes["connection"].exec_driver_sql("CREATE TABLE interrupted_migration (id TEXT)")
            raise RuntimeError("synthetic migration failure")
        with patch("backend.app.repositories.migration.command.upgrade", side_effect=fail):
            with self.assertRaises(RuntimeError):
                upgrade(old)
        self.assertEqual(schema_status(old), "OUTDATED")
        engine = make_engine(old)
        self.assertNotIn("interrupted_migration", inspect(engine).get_table_names())
        engine.dispose()
        self.assertEqual(len(list((Path(self.temp.name) / "backups").glob("fail-*.sqlite3"))), 1)

    def test_new_revision_preserves_old_period_and_price(self):
        self.populated()
        with unit_of_work(self.engine) as session:
            session.add(QuotationRevision(id="revision-correction", quotation_id="quote", revision_no=2,
                application_id="app", canonical_payload_hash=HASH, price_20gp="124.4567",
                valid_from=date(2026, 12, 25), valid_to=date(2027, 1, 5), identity_snapshot={"destination_name": "TEST PORT"}))
            session.get(Quotation, "quote").current_revision_id = "revision-correction"
        with Session(self.engine) as session:
            self.assertEqual(session.get(QuotationRevision, "revision").price_20gp, Decimal("123.4567"))
            self.assertEqual(session.get(Quotation, "quote").current_revision_id, "revision-correction")
            self.assertEqual(session.get(Quotation, "quote").version, 2)

    def test_formal_quotation_requires_current_revision(self):
        self.seed()
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(Quotation(origin_port_id="origin", destination_id="dest"))

    def test_dataset_advance_cas_hash_and_rollback(self):
        self.seed()
        with unit_of_work(self.engine) as session:
            session.add(DatasetVersion(origin_port_id="origin", dataset_version=1))
        payload = {"destinations": [{"name": "TEST PORT", "price_20gp": "1.2345"}]}
        with unit_of_work(self.engine, immediate=True) as session:
            snapshot = advance_dataset(session, origin_port_id="origin", expected_version=1, payload=payload)
            saved_hash = snapshot.payload_sha256
        payload["destinations"][0]["name"] = "CHANGED"
        with Session(self.engine) as session:
            row = session.get(DatasetSnapshot, snapshot.id)
            self.assertEqual(row.payload_json["destinations"][0]["name"], "TEST PORT")
            self.assertEqual(row.payload_sha256, saved_hash)
            self.assertEqual(session.get(DatasetVersion, "origin").dataset_version, 2)
        with self.assertRaises(DatasetVersionConflict), unit_of_work(self.engine, immediate=True) as session:
            advance_dataset(session, origin_port_id="origin", expected_version=1, payload={})
        with self.assertRaises(RuntimeError), unit_of_work(self.engine, immediate=True) as session:
            advance_dataset(session, origin_port_id="origin", expected_version=2, payload={})
            raise RuntimeError("synthetic later step failure")
        with Session(self.engine) as session:
            self.assertEqual(session.get(DatasetVersion, "origin").dataset_version, 2)
        self.assertEqual(self.count(DatasetSnapshot), 1)

    def test_snapshot_rejects_binary_float_before_advancing(self):
        self.seed()
        with unit_of_work(self.engine) as session:
            session.add(DatasetVersion(origin_port_id="origin"))
        for payload in ({"price": 1.25}, {"nested": (1.25,)}, {1: "bad-key"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError), unit_of_work(self.engine) as session:
                advance_dataset(session, origin_port_id="origin", expected_version=1, payload=payload)
        with Session(self.engine) as session:
            self.assertEqual(session.get(DatasetVersion, "origin").dataset_version, 1)

    def test_idempotency_key_and_snapshot_version_unique(self):
        self.populated()
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            self.application(session, key="again", snapshot=False)
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(DatasetSnapshot(origin_port_id="origin", dataset_version=2, payload_sha256=HASH))

    def test_optimistic_lock_stale_destination_rejected(self):
        self.seed()
        with Session(self.engine) as stale:
            row = stale.get(Destination, "dest")
            stale.rollback()  # End reader snapshot but keep stale object for CAS test.
            # rollback expires objects; detach the observed version explicitly.
            row = stale.get(Destination, "dest")
            stale.expunge(row)
            stale.rollback()
            with unit_of_work(self.engine) as session:
                session.get(Destination, "dest").display_name_en = "NEW NAME"
            stale.add(row)
            row.display_name_en = "STALE NAME"
            with self.assertRaises(StaleDataError):
                stale.commit()

    def test_json_round_trip_requires_explicit_replacement(self):
        self.seed()
        with unit_of_work(self.engine) as session:
            self.plan(session)
        with unit_of_work(self.engine) as session:
            plan = session.get(ChangePlan, "plan")
            plan.items = [{"candidate_id": "synthetic", "price": "9.0001"}]
        with Session(self.engine) as session:
            self.assertEqual(session.get(ChangePlan, "plan").items[0]["price"], "9.0001")

    def imports(self):
        self.seed()
        with unit_of_work(self.engine) as session:
            for suffix in ("1", "2"):
                session.add(ImportBatch(id="batch" + suffix, origin_port_id="origin", title="test"))
            session.flush()
            for suffix in ("1", "2"):
                session.add(SourceFile(id="file" + suffix, batch_id="batch" + suffix, original_name="test.xlsx", storage_key="synthetic/file" + suffix, mime_type="application/octet-stream", byte_size=1, sha256=HASH))
            session.add(ExtractionRun(id="run", batch_id="batch1", prompt_version="test", parser_version="test"))
            session.add(SourceGroup(id="group", batch_id="batch1"))

    def test_duplicate_file_hash_allowed_across_batches(self):
        self.imports()
        self.assertEqual(self.count(SourceFile), 2)

    def test_candidate_state_defaults_and_cross_batch_rejected(self):
        self.imports()
        with unit_of_work(self.engine) as session:
            session.add(ExtractionCandidate(id="candidate", batch_id="batch1", run_id="run"))
        with Session(self.engine) as session:
            row = session.get(ExtractionCandidate, "candidate")
            self.assertEqual((row.review_state, row.match_state, row.application_state), ("PENDING_REVIEW", "UNMATCHED", "NOT_APPLIED"))
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(ExtractionCandidate(batch_id="batch2", run_id="run"))
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(SourceGroupFile(source_group_id="group", source_file_id="file2"))
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(Evidence(candidate_id="candidate", file_id="file2", original_text="test", evidence_type="EXCEL"))

    def test_invalid_state_and_unreviewed_approval_refused(self):
        self.imports()
        for fields in ({"review_state": "APPROVED"}, {"match_state": "MADE_UP"}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
                session.add(ExtractionCandidate(batch_id="batch1", run_id="run", **fields))

    def test_scoped_code_mapping_overlap_and_adjacent_periods(self):
        self.seed()
        def mapping(key, start, end, status="APPROVED"):
            return LocationCodeMapping(id=key, namespace="SOURCE_PRIVATE", code_raw="X", code_normalized="X", destination_id="dest", review_state=status, valid_from=start, valid_to=end)
        with unit_of_work(self.engine) as session:
            session.add(mapping("a", date(2026, 1, 1), date(2026, 1, 31)))
            session.add(mapping("b", date(2026, 2, 1), date(2026, 2, 28)))
            session.add(mapping("pending", None, None, "PENDING_REVIEW"))
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(mapping("bad", date(2026, 1, 31), date(2026, 2, 1)))
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.get(LocationCodeMapping, "pending").review_state = "APPROVED"

    def test_ambiguous_name_alias_allowed(self):
        self.seed()
        with unit_of_work(self.engine) as session:
            for _ in range(2):
                session.add(DestinationAlias(destination_id="dest", alias_raw="PORT", alias_normalized="PORT", alias_kind="OLD_NAME"))
        self.assertEqual(self.count(DestinationAlias), 2)

    def test_readonly_health_probe_and_actual_api(self):
        missing = "sqlite:///" + (Path(self.temp.name) / "missing.sqlite3").as_posix()
        self.assertEqual(schema_status(missing), "NOT_INITIALIZED")
        self.assertFalse(database_path(missing).exists())
        with TestClient(create_app(Settings(_env_file=None, database_url=self.url)), base_url="http://127.0.0.1:8000") as client:
            health = client.get("/api/v1/health").json()
            self.assertEqual(health["database_status"], "READY")
            self.assertEqual(health["stage"], "T07")
            self.assertEqual(client.get("/api/v1/bootstrap").json()["quotation_status"], "NOT_INITIALIZED")

    def test_path_is_cwd_independent_and_rejects_uris_network(self):
        self.assertEqual(database_path("sqlite:///./data/app.sqlite3"), ROOT / "data/app.sqlite3")
        for value in ("sqlite:///:memory:", "sqlite:///file:test?mode=ro", "sqlite://///server/share/x.db", "postgresql://user:secret@host/db"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                database_path(value)

    def test_naive_timestamps_refused(self):
        self.seed()
        with self.assertRaises(StatementError), unit_of_work(self.engine) as session:
            session.add(ImportBatch(origin_port_id="origin", title="test", created_at=datetime(2026, 1, 1)))

    def test_ddl_rollback_is_transactional(self):
        with self.assertRaises(RuntimeError), self.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE synthetic_rollback (id TEXT)")
            raise RuntimeError("synthetic failure")
        self.assertNotIn("synthetic_rollback", inspect(self.engine).get_table_names())

    def test_immediate_writer_transaction_is_explicit(self):
        statements = []
        with self.engine.connect() as connection:
            connection.connection.driver_connection.set_trace_callback(statements.append)
            with connection.execution_options(sqlite_transaction_mode="IMMEDIATE").begin():
                connection.exec_driver_sql("SELECT 1")
            connection.connection.driver_connection.set_trace_callback(None)
        self.assertIn("BEGIN IMMEDIATE", statements)

    def test_cross_origin_revision_application_refused(self):
        self.populated()
        with unit_of_work(self.engine) as session:
            session.add(OriginPort(id="other-origin", display_en="OTHER", display_zh="其他起运港"))
        with self.assertRaises(IntegrityError), unit_of_work(self.engine) as session:
            session.add(Quotation(id="other-quote", origin_port_id="other-origin", destination_id="dest", current_revision_id="other-revision"))
            session.flush()
            session.add(QuotationRevision(id="other-revision", quotation_id="other-quote", revision_no=1,
                application_id="app", price_20gp="1", canonical_payload_hash=HASH))


if __name__ == "__main__":
    unittest.main()
