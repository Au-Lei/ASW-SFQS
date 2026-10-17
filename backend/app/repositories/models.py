"""SQLAlchemy entities, canonical names from T02; SQLite is the V1 backend.

JSON values are replaced as complete values (no implicit in-place dirty tracking).
Relationships use explicit IDs to keep writes and transaction ordering visible.
"""
from uuid import uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, ForeignKey, ForeignKeyConstraint,
    Index, Integer, JSON, MetaData, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, declared_attr

from backend.app.domain.contracts import (
    ApplicationState, ChangeAction, DateBasis, DestinationKind, ExportMode,
    JobState, MatchState, PlanState, ReviewState,
)
from .types import Money, UTCDateTime, utc_now


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


def key():
    return Column(String(36), primary_key=True, default=lambda: str(uuid4()))


def ref(table, *, nullable=False, **kwargs):
    return Column(String(36), ForeignKey(table + ".id", ondelete="RESTRICT"), nullable=nullable, **kwargs)


def json_value(factory=dict, *, nullable=False):
    return Column(JSON(none_as_null=True), nullable=nullable, default=factory)


def state(enum, default, name):
    values = [v.value for v in enum] if not isinstance(enum, tuple) else enum
    return Column(String(40), CheckConstraint(
        name + " IN (" + ",".join("'" + v + "'" for v in values) + ")", name=name + "_values"
    ), nullable=False, default=default)


class Versioned:
    version = Column(Integer, nullable=False, default=1)

    @declared_attr.directive
    def __mapper_args__(cls):
        return {"version_id_col": cls.version}


class CountryRegion(Base):
    __tablename__ = "country_region"
    id = key()
    internal_code = Column(String(100), nullable=False, unique=True)
    iso_country_code = Column(String(2))
    name_en = Column(Text, nullable=False)
    name_zh = Column(Text, nullable=False)
    parent_country_id = ref("country_region", nullable=True)
    active = Column(Boolean, nullable=False, default=True)


class Region(Base):
    __tablename__ = "region"
    id = key()
    code = Column(String(100), nullable=False, unique=True)
    sheet_name = Column(String(31), nullable=False, unique=True)
    sort_order = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False, default=True)


class RouteGroup(Base):
    __tablename__ = "route_group"
    id = key()
    region_id = ref("region")
    code = Column(String(100), nullable=False, unique=True)
    name = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False, default=True)


class Destination(Versioned, Base):
    __tablename__ = "destination"
    id = key()
    country_region_id = ref("country_region")
    kind = state(DestinationKind, "UNKNOWN", "kind")
    parent_destination_id = ref("destination", nullable=True)
    terminal_key = Column(String(160))
    canonical_key = Column(String(200), nullable=False, unique=True)
    display_name_en = Column(Text, nullable=False)
    display_name_zh = Column(Text, nullable=False)
    unlocode = Column(String(5))
    route_group_id = ref("route_group")
    sort_order = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    __table_args__ = (
        UniqueConstraint("parent_destination_id", "terminal_key", name="uq_destination_parent_terminal"),
        CheckConstraint("parent_destination_id IS NULL OR parent_destination_id != id", name="not_self_parent"),
        CheckConstraint("kind != 'TERMINAL' OR (parent_destination_id IS NOT NULL AND terminal_key IS NOT NULL AND length(trim(terminal_key)) > 0)", name="terminal_identity"),
        Index("ix_destination_route_active_sort", "route_group_id", "active", "sort_order"),
    )


class Carrier(Base):
    __tablename__ = "carrier"
    id = key()
    code = Column(String(32), nullable=False, unique=True)
    name_en = Column(Text)
    name_zh = Column(Text)
    active = Column(Boolean, nullable=False, default=True)


class CarrierAlias(Base):
    __tablename__ = "carrier_alias"
    id = key()
    carrier_id = ref("carrier")
    alias_raw = Column(Text, nullable=False)
    alias_normalized = Column(Text, nullable=False, index=True)


class Source(Base):
    __tablename__ = "source"
    id = key()
    name = Column(Text, nullable=False)
    kind = state(("CARRIER", "AGENT", "OTHER", "UNKNOWN"), "UNKNOWN", "kind")
    public_code = Column(String(100), unique=True)
    active = Column(Boolean, nullable=False, default=True)


class OriginPort(Base):
    __tablename__ = "origin_port"
    id = key()
    display_en = Column(Text, nullable=False)
    display_zh = Column(Text, nullable=False)
    standard_code = Column(String(5))
    active = Column(Boolean, nullable=False, default=True)


class DestinationAlias(Base):
    __tablename__ = "destination_alias"
    id = key()
    destination_id = ref("destination")
    alias_raw = Column(Text, nullable=False)
    alias_normalized = Column(Text, nullable=False)
    alias_kind = Column(String(50), nullable=False)
    source_scope_id = ref("source", nullable=True)
    country_scope_id = ref("country_region", nullable=True)
    verified_at = Column(UTCDateTime)
    verified_by = Column(String(100))
    __table_args__ = (Index("ix_alias_scoped_lookup", "alias_normalized", "source_scope_id", "country_scope_id"),)


class ImportBatch(Versioned, Base):
    __tablename__ = "import_batch"
    id = key()
    origin_port_id = ref("origin_port")
    title = Column(Text, nullable=False)
    source_id = ref("source", nullable=True)
    created_by = Column(String(100))
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)


class SourceFile(Base):
    __tablename__ = "source_file"
    id = key()
    batch_id = ref("import_batch", index=True)
    original_name = Column(Text, nullable=False)
    storage_key = Column(Text, nullable=False)
    mime_type = Column(String(150), nullable=False)
    byte_size = Column(Integer, CheckConstraint("byte_size >= 0", name="size_nonnegative"), nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    uploaded_at = Column(UTCDateTime, nullable=False, default=utc_now)


class SourceGroup(Versioned, Base):
    __tablename__ = "source_group"
    id = key()
    batch_id = ref("import_batch", index=True)
    source_id = ref("source", nullable=True)
    carrier_id = ref("carrier", nullable=True)
    context_defaults = json_value()


class SourceGroupFile(Base):
    __tablename__ = "source_group_file"
    source_group_id = ref("source_group", primary_key=True)
    source_file_id = ref("source_file", primary_key=True)


class ModelConfig(Base):
    __tablename__ = "model_config"
    id = key()
    provider = Column(String(100), nullable=False)
    model_identifier = Column(String(200), nullable=False)
    prompt_version = Column(String(100), nullable=False)
    schema_version = Column(String(100), nullable=False)
    secret_ref = Column(String(200))
    enabled = Column(Boolean, nullable=False, default=False)


class ExtractionRun(Base):
    __tablename__ = "extraction_run"
    id = key()
    batch_id = ref("import_batch", index=True)
    state = state(JobState, "QUEUED", "state")
    provider_config_id = ref("model_config", nullable=True)
    model_name = Column(String(200))
    prompt_version = Column(String(100), nullable=False)
    parser_version = Column(String(100), nullable=False)
    started_at = Column(UTCDateTime)
    finished_at = Column(UTCDateTime)
    error = json_value(nullable=True)


class ExtractionCandidate(Versioned, Base):
    __tablename__ = "extraction_candidate"
    id = key()
    batch_id = ref("import_batch")
    source_group_id = ref("source_group", nullable=True)
    run_id = ref("extraction_run", index=True)
    raw_payload = json_value()
    normalized_payload = json_value()
    field_provenance = json_value()
    issues = json_value(list)
    review_state = state(ReviewState, "PENDING_REVIEW", "review_state")
    review_version = Column(Integer, nullable=False, default=1)
    match_state = state(MatchState, "UNMATCHED", "match_state")
    application_state = state(ApplicationState, "NOT_APPLIED", "application_state")
    disposition = state(("INCLUDE", "DEFER", "EXCLUDE"), "INCLUDE", "disposition")
    reviewed_by = Column(String(100))
    reviewed_at = Column(UTCDateTime)
    reviewed_payload_hash = Column(String(64))
    __table_args__ = (
        Index("ix_candidate_batch_review", "batch_id", "review_state"),
        CheckConstraint("review_version >= 1", name="review_version_positive"),
        CheckConstraint("review_state != 'APPROVED' OR (reviewed_payload_hash IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)", name="approval_snapshot"),
    )


class Evidence(Base):
    __tablename__ = "evidence"
    id = key()
    candidate_id = ref("extraction_candidate", index=True)
    field_path = Column(Text)
    file_id = ref("source_file")
    sheet_name = Column(Text)
    cell_range = Column(String(100))
    page_no = Column(Integer, CheckConstraint("page_no IS NULL OR page_no >= 1", name="page_positive"))
    bbox = json_value(nullable=True)
    original_text = Column(Text, nullable=False)
    evidence_type = Column(String(50), nullable=False)


class LocationCodeMapping(Versioned, Base):
    __tablename__ = "location_code_mapping"
    id = key()
    namespace = Column(String(100), nullable=False)
    issuer_id = ref("source", nullable=True)
    code_raw = Column(Text, nullable=False)
    code_normalized = Column(Text, nullable=False)
    destination_id = ref("destination", nullable=True)
    origin_port_id = ref("origin_port", nullable=True)
    review_state = state(ReviewState, "PENDING_REVIEW", "review_state")
    valid_from = Column(Date)
    valid_to = Column(Date)
    evidence_ids = json_value(list)
    __table_args__ = (
        CheckConstraint("(destination_id IS NOT NULL) != (origin_port_id IS NOT NULL)", name="one_location"),
        CheckConstraint("valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from", name="validity_order"),
        Index("ix_mapping_scope", "namespace", "issuer_id", "code_normalized", "review_state"),
    )


class ChangePlan(Versioned, Base):
    __tablename__ = "change_plan"
    id = key()
    origin_port_id = ref("origin_port")
    base_dataset_version = Column(Integer, nullable=False)
    selected_candidate_versions = json_value()
    items = json_value(list)
    content_hash = Column(String(64), nullable=False)
    state = state(PlanState, "DRAFT", "state")
    expires_at = Column(UTCDateTime)
    __table_args__ = (UniqueConstraint("id", "origin_port_id", name="uq_plan_id_origin"),)


class DatasetVersion(Versioned, Base):
    __tablename__ = "dataset_version"
    origin_port_id = ref("origin_port", primary_key=True)
    dataset_version = Column(Integer, CheckConstraint("dataset_version >= 1", name="dataset_positive"), nullable=False, default=1)
    updated_at = Column(UTCDateTime, nullable=False, default=utc_now)


class DatasetSnapshot(Base):
    __tablename__ = "dataset_snapshot"
    id = key()
    origin_port_id = ref("origin_port")
    dataset_version = Column(Integer, CheckConstraint("dataset_version >= 1", name="dataset_positive"), nullable=False)
    payload_json = json_value()
    payload_storage_key = Column(Text)
    payload_sha256 = Column(String(64), nullable=False)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("origin_port_id", "dataset_version", name="uq_snapshot_origin_version"),
                      UniqueConstraint("id", "origin_port_id", "dataset_version", name="uq_snapshot_identity"))


class Application(Base):
    __tablename__ = "application"
    id = key()
    origin_port_id = ref("origin_port")
    plan_id = Column(String(36), nullable=False)
    idempotency_key = Column(String(200), nullable=False)
    request_hash = Column(String(64), nullable=False)
    before_version = Column(Integer, nullable=False)
    after_version = Column(Integer, nullable=False)
    actor_id = Column(String(100))
    applied_at = Column(UTCDateTime, nullable=False, default=utc_now)
    status = state(("APPLIED",), "APPLIED", "status")
    __table_args__ = (
        UniqueConstraint("origin_port_id", "idempotency_key", name="uq_application_origin_key"),
        UniqueConstraint("origin_port_id", "after_version", name="uq_application_origin_version"),
        ForeignKeyConstraint(["plan_id", "origin_port_id"], ["change_plan.id", "change_plan.origin_port_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["origin_port_id", "after_version"], ["dataset_snapshot.origin_port_id", "dataset_snapshot.dataset_version"], deferrable=True, initially="DEFERRED"),
        CheckConstraint("before_version >= 1 AND after_version = before_version + 1", name="version_step"),
    )


class Quotation(Versioned, Base):
    __tablename__ = "quotation"
    id = key()
    origin_port_id = ref("origin_port")
    destination_id = ref("destination")
    carrier_id = ref("carrier", nullable=True)
    source_id = ref("source", nullable=True)
    current_revision_id = Column(String(36), nullable=False)
    related_quotation_id = ref("quotation", nullable=True)
    lifecycle_state = state(("ACTIVE", "ARCHIVED"), "ACTIVE", "lifecycle_state")
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
    created_by = Column(String(100))
    __table_args__ = (
        ForeignKeyConstraint(["current_revision_id", "id"], ["quotation_revision.id", "quotation_revision.quotation_id"], deferrable=True, initially="DEFERRED", use_alter=True),
        Index("ix_quotation_origin_destination_state", "origin_port_id", "destination_id", "lifecycle_state"),
        Index("ix_quotation_carrier_source", "carrier_id", "source_id"),
    )


class QuotationRevision(Base):
    __tablename__ = "quotation_revision"
    id = key()
    quotation_id = ref("quotation")
    revision_no = Column(Integer, CheckConstraint("revision_no >= 1", name="revision_positive"), nullable=False)
    price_20gp = Column(Money)
    price_40gp = Column(Money)
    price_40hq = Column(Money)
    currency = Column(String(3))
    sailing_weekdays = json_value(list)
    sailing_text = Column(Text)
    transit = json_value()
    routing = json_value(list)
    valid_from = Column(Date)
    valid_to = Column(Date)
    validity_basis = state(DateBasis, "UNSPECIFIED", "validity_basis")
    remarks = Column(Text)
    price_scope_summary = Column(Text)
    conditions = json_value(list)
    quality_flags = json_value(list)
    service = Column(Text)
    price_profile = Column(String(100))
    candidate_id = ref("extraction_candidate", nullable=True)
    application_id = ref("application")
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
    created_by = Column(String(100))
    canonical_payload_hash = Column(String(64), nullable=False)
    identity_snapshot = json_value()
    __table_args__ = (
        UniqueConstraint("quotation_id", "revision_no", name="uq_revision_number"),
        UniqueConstraint("id", "quotation_id", name="uq_revision_owner"),
        CheckConstraint("price_20gp IS NOT NULL OR price_40gp IS NOT NULL OR price_40hq IS NOT NULL", name="at_least_one_price"),
        CheckConstraint("valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from", name="validity_order"),
        *[CheckConstraint(f"{c} IS NULL OR (typeof({c}) = 'integer' AND {c} BETWEEN 0 AND 999999999999999999)", name=c + "_exact") for c in ("price_20gp", "price_40gp", "price_40hq")],
        CheckConstraint("currency IS NULL OR (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*')", name="currency_shape"),
        Index("ix_revision_validity_currency", "valid_from", "valid_to", "currency"),
    )


class ChargeRule(Base):
    __tablename__ = "charge_rule"
    id = key()
    quotation_revision_id = ref("quotation_revision", nullable=True)
    source_group_id = ref("source_group", nullable=True)
    type = Column(String(100), nullable=False)
    raw_text = Column(Text, nullable=False)
    normalized_payload = json_value()
    scope = json_value()
    review_state = state(ReviewState, "PENDING_REVIEW", "review_state")
    evidence_ids = json_value(list)
    __table_args__ = (CheckConstraint("quotation_revision_id IS NOT NULL OR source_group_id IS NOT NULL", name="has_owner"),)


class Issue(Versioned, Base):
    __tablename__ = "issue"
    id = key()
    candidate_id = ref("extraction_candidate", nullable=True)
    charge_rule_id = ref("charge_rule", nullable=True)
    code = Column(String(100), nullable=False)
    field_paths = json_value(list)
    affected_actions = json_value(list)
    severity = Column(String(32), nullable=False)
    message = Column(Text, nullable=False)
    resolution = json_value()
    __table_args__ = (CheckConstraint("candidate_id IS NOT NULL OR charge_rule_id IS NOT NULL", name="has_owner"),)


class ApplicationItem(Base):
    __tablename__ = "application_item"
    id = key()
    application_id = ref("application", index=True)
    action = state(ChangeAction, "NO_CHANGE", "action")
    candidate_id = ref("extraction_candidate", nullable=True)
    quotation_id = ref("quotation", nullable=True)
    before_revision_id = ref("quotation_revision", nullable=True)
    after_revision_id = ref("quotation_revision", nullable=True)
    field_diff = json_value()


class TemplateConfig(Base):
    __tablename__ = "template_config"
    version = Column(String(100), primary_key=True)
    schema_version = Column(String(100), nullable=False)
    layout_json = json_value()
    checksum = Column(String(64), nullable=False)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)


class ExportArtifact(Base):
    __tablename__ = "export_artifact"
    id = key()
    origin_port_id = ref("origin_port")
    snapshot_id = Column(String(36), nullable=False)
    dataset_version = Column(Integer, nullable=False)
    baseline_version = Column(Integer)
    export_mode = state(ExportMode, "FULL", "export_mode")
    filter_payload = json_value()
    template_version = Column(String(100), ForeignKey("template_config.version", ondelete="RESTRICT"), nullable=False)
    file_sha256 = Column(String(64))
    file_storage_key = Column(Text)
    state = state(JobState, "QUEUED", "state")
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
    error = json_value(nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["snapshot_id", "origin_port_id", "dataset_version"], ["dataset_snapshot.id", "dataset_snapshot.origin_port_id", "dataset_snapshot.dataset_version"], ondelete="RESTRICT"),
        Index("ix_export_cache", "origin_port_id", "dataset_version", "template_version", "export_mode", "baseline_version"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id = key()
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    actor_id = Column(String(100))
    actor_label = Column(Text, nullable=False)
    occurred_at = Column(UTCDateTime, nullable=False, default=utc_now)
    before_hash = Column(String(64))
    after_hash = Column(String(64))
    request_id = Column(String(100), nullable=False)
    __table_args__ = (Index("ix_audit_entity_time", "entity_type", "entity_id", "occurred_at"),)


class Job(Versioned, Base):
    __tablename__ = "job"
    id = key()
    kind = Column(String(100), nullable=False)
    state = state(JobState, "QUEUED", "state")
    stage = Column(String(100))
    batch_id = ref("import_batch", nullable=True)
    lease_owner = Column(String(100))
    lease_expires_at = Column(UTCDateTime)
    heartbeat_at = Column(UTCDateTime)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    payload = json_value()
    result_ref = json_value(nullable=True)
    error = json_value(nullable=True)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
    updated_at = Column(UTCDateTime, nullable=False, default=utc_now)
    __table_args__ = (CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="attempt_limits"),
                      Index("ix_job_claim", "state", "lease_expires_at", "created_at"))


# SQLAlchemy optimistic locking covers ORM writes; bulk SQL must explicitly CAS.
for table in Base.metadata.tables.values():
    if "version" in table.c and table.name != "template_config":
        table.append_constraint(CheckConstraint("version >= 1", name="version_positive"))
    for column in table.c:
        # Alembic's CREATE TABLE renderer serializes table-level checks.
        for constraint in list(column.constraints):
            if isinstance(constraint, CheckConstraint):
                column.constraints.remove(constraint)
                table.append_constraint(constraint)
        if isinstance(column.type, Date):
            name = column.name
            table.append_constraint(CheckConstraint(
                f"{name} IS NULL OR (length({name}) = 10 AND {name} GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date({name}, '+0 days') IS NOT NULL AND date({name}, '+0 days') = {name})",
                name=name + "_calendar",
            ))
