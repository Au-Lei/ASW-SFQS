"""Single source for API, extraction JSON Schema and generated TypeScript types.

Strings carry decimal amounts on the wire. Cross-field validators remain mandatory
on the server: JSON Schema alone cannot express every business invariant.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class ReviewState(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    NEEDS_INFO = "NEEDS_INFO"
    REJECTED = "REJECTED"


class MatchState(str, Enum):
    UNMATCHED = "UNMATCHED"
    SUGGESTED = "SUGGESTED"
    CONFIRMED = "CONFIRMED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class ApplicationState(str, Enum):
    NOT_APPLIED = "NOT_APPLIED"
    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    EXCLUDED = "EXCLUDED"


class PlanState(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    APPLIED = "APPLIED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class ChangeAction(str, Enum):
    CREATE_QUOTE = "CREATE_QUOTE"
    UPDATE_QUOTE = "UPDATE_QUOTE"
    LINK_EVIDENCE = "LINK_EVIDENCE"
    ARCHIVE_QUOTE = "ARCHIVE_QUOTE"
    NO_CHANGE = "NO_CHANGE"
    EXCLUDE = "EXCLUDE"


class DateBasis(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    ETD = "ETD"
    BOOKING_DATE = "BOOKING_DATE"
    GATE_IN_DATE = "GATE_IN_DATE"
    QUOTATION_DATE = "QUOTATION_DATE"
    OTHER = "OTHER"


class DestinationKind(str, Enum):
    SEAPORT = "SEAPORT"
    TERMINAL = "TERMINAL"
    ICD = "ICD"
    INLAND_POINT = "INLAND_POINT"
    CITY_SCOPE = "CITY_SCOPE"
    UNKNOWN = "UNKNOWN"


class ProvenanceOrigin(str, Enum):
    EXPLICIT = "EXPLICIT"
    RULE_DERIVED = "RULE_DERIVED"
    MANUAL = "MANUAL"
    UNKNOWN = "UNKNOWN"


class ExportMode(str, Enum):
    FULL = "FULL"
    FILTERED = "FILTERED"


class ContainerType(str, Enum):
    GP20 = "20GP"
    GP40 = "40GP"
    HQ40 = "40HQ"


class IssueAction(str, Enum):
    APPLY = "APPLY"
    COMPARE = "COMPARE"
    EXPORT = "EXPORT"
    REVIEW = "REVIEW"
    DATE_FILTER = "DATE_FILTER"


Money = Annotated[str, Field(strict=True, pattern=r"^(0|[1-9][0-9]{0,13})(\.[0-9]{1,4})?$",
                             description="Nonnegative decimal string, max 14 integer / 4 fraction digits; null means unknown")]
ISODate = Annotated[str, Field(strict=True, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
Version = Annotated[int, Field(strict=True, ge=1)]
def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("BLANK_VALUE")
    return value


NonEmpty = Annotated[str, Field(strict=True, min_length=1), AfterValidator(nonblank)]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$", strict=True)]
Weekday = Annotated[int, Field(strict=True, ge=1, le=7)]


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return value


Timestamp = Annotated[str, Field(strict=True, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T.+(Z|[+-][0-9]{2}:[0-9]{2})$"), AfterValidator(timestamp)]


class Validity(Contract):
    valid_from: ISODate | None = None
    valid_to: ISODate | None = None
    basis: DateBasis = DateBasis.UNSPECIFIED
    raw_text: str | None = None
    year_evidence_ids: list[UUID] = Field(default_factory=list)

    @field_validator("valid_from", "valid_to")
    @classmethod
    def real_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("VALIDITY_REVERSED")
        return self


class Provenance(Contract):
    raw_value: Any
    normalized_value: Any
    origin: ProvenanceOrigin
    evidence_ids: list[UUID] = Field(default_factory=list)
    rule_id: str | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    recorded_by: UUID | None = None
    recorded_at: Timestamp | None = None

    @model_validator(mode="after")
    def derivation(self):
        if self.origin == ProvenanceOrigin.RULE_DERIVED and not self.rule_id:
            raise ValueError("DERIVATION_RULE_REQUIRED")
        if self.origin in (ProvenanceOrigin.EXPLICIT, ProvenanceOrigin.RULE_DERIVED) and not self.evidence_ids:
            raise ValueError("EVIDENCE_REQUIRED")
        if self.origin == ProvenanceOrigin.MANUAL and (self.recorded_by is None or self.recorded_at is None):
            raise ValueError("MANUAL_ACTOR_REQUIRED")
        return self


class CellLocation(Contract):
    kind: Literal["XLSX_CELL"]
    sheet_name: NonEmpty
    cell_range: Annotated[str, Field(pattern=r"^[A-Z]+[1-9][0-9]*(:[A-Z]+[1-9][0-9]*)?$")]


class ImageLocation(Contract):
    kind: Literal["IMAGE_REGION"]
    page_no: Annotated[int, Field(strict=True, ge=1)] = 1
    bbox: tuple[float, float, float, float] = Field(description="Normalized x0,y0,x1,y1 in original image orientation")

    @model_validator(mode="after")
    def bounds(self):
        x0, y0, x1, y1 = self.bbox
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("INVALID_BBOX")
        return self


class TextLocation(Contract):
    kind: Literal["TEXT_SPAN"]
    start: Annotated[int, Field(strict=True, ge=0)]
    end: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode="after")
    def order(self):
        if self.end <= self.start:
            raise ValueError("INVALID_TEXT_SPAN")
        return self


class Evidence(Contract):
    id: UUID
    file_id: UUID
    field_path: str | None = None
    original_text: str
    location: Annotated[CellLocation | ImageLocation | TextLocation, Field(discriminator="kind")]


class ExtractedIssue(Contract):
    code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
    field_paths: list[str] = Field(default_factory=list)
    message: NonEmpty
    affected_actions: list[IssueAction]
    severity: Literal["INFO", "WARNING", "ERROR"]


class Issue(ExtractedIssue):
    resolution: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"] = "OPEN"
    acknowledged_by: UUID | None = None
    acknowledged_at: Timestamp | None = None

    @model_validator(mode="after")
    def human_resolution(self):
        if self.resolution != "OPEN" and (self.acknowledged_by is None or self.acknowledged_at is None):
            raise ValueError("ISSUE_ACTOR_REQUIRED")
        return self


class LiteralPrice(Contract):
    kind: Literal["LITERAL_COMPONENT"]
    raw_text: NonEmpty
    amount: Money
    qualifier_raw: str | None = None


class ReferencePrice(Contract):
    kind: Literal["REFERENCE_PLUS_ADDON"]
    raw_text: NonEmpty
    reference_raw: NonEmpty
    addon: Money
    amount: None = None
    # V1 does not evaluate reference expressions. A later confirmed resolution is a new candidate value.


class UnassignedPair(Contract):
    kind: Literal["PAIR_UNASSIGNED"]
    raw_text: NonEmpty
    tokens: Annotated[list[Money], Field(min_length=2)]
    amount: None = None


class MissingPrice(Contract):
    kind: Literal["MISSING"]
    raw_text: str | None = None
    amount: None = None


PriceCell = Annotated[LiteralPrice | ReferencePrice | UnassignedPair | MissingPrice, Field(discriminator="kind")]


class PriceProfile(Contract):
    profile_key: NonEmpty
    label_raw: NonEmpty
    purpose: Literal["UNSPECIFIED", "PROCUREMENT", "SELLING", "SETTLEMENT"] = "UNSPECIFIED"
    container_binding: Literal["EXPLICIT", "CONFIRMED", "UNCONFIRMED"]
    # Keys are source column identifiers, not assumed container types.
    cells: dict[str, PriceCell]
    container_map: dict[str, Literal["20GP", "40GP", "40HQ", "40GP_AND_40HQ"]] = Field(default_factory=dict)
    evidence_ids: list[UUID]

    @model_validator(mode="after")
    def binding(self):
        if not set(self.container_map).issubset(self.cells):
            raise ValueError("UNKNOWN_PRICE_COLUMN")
        if self.container_binding == "UNCONFIRMED" and self.container_map:
            raise ValueError("UNCONFIRMED_CONTAINER_MAPPING")
        return self


class Schedule(Contract):
    raw_text: str | None = None
    weekdays: list[Weekday] = Field(default_factory=list)
    service_binding: Literal["UNKNOWN", "CONFIRMED"] = "UNKNOWN"
    transit_days_raw: str | None = None
    transit_day_options: list[Annotated[int, Field(strict=True, ge=0)]] = Field(default_factory=list)
    transit_binding: Literal["UNKNOWN", "SINGLE", "ALTERNATIVES", "CONFIRMED_RANGE"] = "UNKNOWN"
    # No actual ETD inferred from periodic weekdays.

    @model_validator(mode="after")
    def normalize_and_validate(self):
        self.weekdays = sorted(set(self.weekdays))
        options = self.transit_day_options
        if self.transit_binding == "SINGLE" and len(options) != 1:
            raise ValueError("TRANSIT_SINGLE_REQUIRES_ONE_VALUE")
        if self.transit_binding == "ALTERNATIVES" and (len(options) < 2 or len(options) != len(set(options))):
            raise ValueError("TRANSIT_ALTERNATIVES_REQUIRE_DISTINCT_VALUES")
        if self.transit_binding == "CONFIRMED_RANGE" and (len(options) != 2 or options[0] > options[1]):
            raise ValueError("TRANSIT_RANGE_INVALID")
        return self


class RouteNode(Contract):
    name_en: NonEmpty
    destination_id: UUID | None = None


class Routing(Contract):
    status: Literal["UNKNOWN", "DIRECT", "TRANSSHIPMENT"] = "UNKNOWN"
    nodes: list[RouteNode] = Field(default_factory=list)
    raw_text: str | None = None

    @model_validator(mode="after")
    def route(self):
        if self.status == "DIRECT" and len(self.nodes) != 2:
            raise ValueError("DIRECT_REQUIRES_POL_POD")
        if self.status == "TRANSSHIPMENT" and len(self.nodes) < 3:
            raise ValueError("TRANSIT_NODE_REQUIRED")
        return self


class LocationCode(Contract):
    namespace: Literal["UNLOCODE", "SOURCE_SPECIFIC", "INTERNAL"]
    value: NonEmpty
    source_id: UUID | None = None

    @model_validator(mode="after")
    def scoped(self):
        if self.namespace == "SOURCE_SPECIFIC" and self.source_id is None:
            raise ValueError("SOURCE_NAMESPACE_REQUIRED")
        return self


class DestinationRef(Contract):
    raw_name: str | None = None
    country_en: str | None = None
    country_zh: str | None = None
    name_en: str | None = None
    name_zh: str | None = None
    kind: DestinationKind = DestinationKind.UNKNOWN
    terminal_name: str | None = None
    destination_id: UUID | None = None
    parent_destination_id: UUID | None = None
    route_group_id: UUID | None = None
    codes: list[LocationCode] = Field(default_factory=list)


class Destination(Contract):
    id: UUID
    canonical_key: NonEmpty
    country_region_id: UUID
    kind: DestinationKind
    parent_destination_id: UUID | None = None
    display_name_en: NonEmpty
    display_name_zh: NonEmpty
    route_group_id: UUID
    version: Version = 1
    active: bool = True

    @model_validator(mode="after")
    def terminal_parent(self):
        if self.kind == DestinationKind.TERMINAL and self.parent_destination_id is None:
            raise ValueError("TERMINAL_PARENT_REQUIRED")
        if self.parent_destination_id == self.id:
            raise ValueError("DESTINATION_SELF_PARENT")
        return self


class DestinationDirectory(Contract):
    destinations: list[Destination]

    @model_validator(mode="after")
    def unique_assignment(self):
        ids = [d.id for d in self.destinations]
        keys = [d.canonical_key for d in self.destinations]
        if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
            raise ValueError("DESTINATION_DUPLICATE_ASSIGNMENT")
        return self


class Condition(Contract):
    key: NonEmpty
    raw_text: NonEmpty
    scope: Literal["DOCUMENT", "GROUP", "RECORD", "PROFILE", "CONTAINER"]
    target_keys: list[str]
    currency: Currency | None = None
    amount: Money | None = None
    unit_raw: str | None = None
    payment_raw: str | None = None
    exception_target_keys: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID]
    # No automatic all-in summation; ambiguous thresholds remain in raw_text.


class ExtractedRecord(Contract):
    record_key: NonEmpty
    physical_row_key: NonEmpty
    origin_raw: str | None = None
    destination: DestinationRef
    carrier_raw: str | None = None
    currency: Currency | None = None
    service_raw: str | None = None
    validity: Validity = Field(default_factory=Validity)
    schedule: Schedule = Field(default_factory=Schedule)
    routing: Routing = Field(default_factory=Routing)
    price_profiles: Annotated[list[PriceProfile], Field(min_length=1)]
    condition_keys: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID]
    field_provenance: dict[str, Provenance] = Field(default_factory=dict)
    issues: list[ExtractedIssue] = Field(default_factory=list)


class DocumentContext(Contract):
    title_raw: str | None = None
    source_updated_on: ISODate | None = None
    origin_scope_raw: str | None = None
    validity: Validity = Field(default_factory=Validity)

    @field_validator("source_updated_on")
    @classmethod
    def real_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value


class ExtractionGroup(Contract):
    group_key: NonEmpty
    label_raw: NonEmpty
    record_keys: list[str]
    evidence_ids: list[UUID]


class ExtractionOutput(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_context: DocumentContext
    records: list[ExtractedRecord]
    groups: list[ExtractionGroup] = Field(default_factory=list)
    conditions: list[Condition]
    evidence: list[Evidence]
    issues: list[ExtractedIssue]

    @model_validator(mode="after")
    def references(self):
        ids = [e.id for e in self.evidence]
        keys = [c.key for c in self.conditions]
        record_keys = [r.record_key for r in self.records]
        group_keys = [g.group_key for g in self.groups]
        if (len(ids) != len(set(ids)) or len(keys) != len(set(keys)) or len(record_keys) != len(set(record_keys))
                or len(group_keys) != len(set(group_keys))):
            raise ValueError("DUPLICATE_LOCAL_KEY")
        known = set(ids)
        refs = list(self.document_context.validity.year_evidence_ids)
        for g in self.groups:
            refs.extend(g.evidence_ids)
            if not set(g.record_keys).issubset(record_keys):
                raise ValueError("DANGLING_GROUP_RECORD")
        for c in self.conditions:
            refs.extend(c.evidence_ids)
            allowed = {"DOCUMENT": {"DOCUMENT"}, "GROUP": set(group_keys), "RECORD": set(record_keys),
                       "PROFILE": {r.record_key + "/" + p.profile_key for r in self.records for p in r.price_profiles},
                       "CONTAINER": {"20GP", "40GP", "40HQ"}}[c.scope]
            if not set(c.target_keys + c.exception_target_keys).issubset(allowed):
                raise ValueError("DANGLING_CONDITION_TARGET")
        for r in self.records:
            if len({p.profile_key for p in r.price_profiles}) != len(r.price_profiles):
                raise ValueError("DUPLICATE_PRICE_PROFILE")
            if not set(r.condition_keys).issubset(keys):
                raise ValueError("DANGLING_CONDITION")
            refs.extend(r.evidence_ids + r.validity.year_evidence_ids)
            for p in r.price_profiles:
                refs.extend(p.evidence_ids)
            for provenance in r.field_provenance.values():
                if (provenance.origin == ProvenanceOrigin.MANUAL or provenance.recorded_by is not None
                        or provenance.recorded_at is not None):
                    raise ValueError("MODEL_CANNOT_CLAIM_HUMAN_PROVENANCE")
                refs.extend(provenance.evidence_ids)
        if not set(refs).issubset(known):
            raise ValueError("DANGLING_EVIDENCE")
        return self


class QuotationValues(Contract):
    origin_port_id: UUID | None = None
    destination_id: UUID | None = None
    carrier_id: UUID | None = None
    source_id: UUID | None = None
    source_code: str | None = None
    service_name: str | None = None
    price_profile_key: str | None = None
    price_20gp: Money | None = None
    price_40gp: Money | None = None
    price_40hq: Money | None = None
    currency: Currency | None = None
    validity: Validity = Field(default_factory=Validity)
    schedule: Schedule = Field(default_factory=Schedule)
    routing: Routing = Field(default_factory=Routing)
    remarks: str | None = None
    price_scope_summary: str | None = None
    condition_keys: list[str] = Field(default_factory=list)

    @field_validator("source_code", "service_name", "price_profile_key", "remarks", "price_scope_summary")
    @classmethod
    def no_empty_unknown(cls, value):
        if value is not None and not value.strip():
            raise ValueError("EMPTY_VALUE_USE_NULL")
        return value


class Candidate(Contract):
    id: UUID
    batch_id: UUID
    source_group_id: UUID | None = None
    run_id: UUID | None = None
    raw_payload: dict[str, Any]
    normalized_payload: QuotationValues
    field_provenance: dict[str, Provenance]
    issues: list[Issue]
    review_state: ReviewState = ReviewState.PENDING_REVIEW
    match_state: MatchState = MatchState.UNMATCHED
    application_state: ApplicationState = ApplicationState.NOT_APPLIED
    disposition: Literal["INCLUDE", "DEFER", "EXCLUDE"] = "INCLUDE"
    version: Version = 1
    review_version: Version | None = None
    reviewed_payload_hash: Sha256 | None = None
    reviewed_by: UUID | None = None
    reviewed_at: Timestamp | None = None

    @model_validator(mode="after")
    def approval_snapshot(self):
        if self.review_state == ReviewState.APPROVED:
            if (self.review_version != self.version or self.reviewed_payload_hash != payload_hash(self.normalized_payload)
                    or self.reviewed_by is None or not self.reviewed_at):
                raise ValueError("APPROVAL_SNAPSHOT_INVALID")
        return self


class CandidatePatch(QuotationValues):
    # Partial top-level fields; structured objects are REPLACED as a whole.
    # Explicit null only allowed where QuotationValues allows it.
    pass


class PatchRequest(Contract):
    expected_version: Version
    changes: CandidatePatch


class ReviewRequest(Contract):
    expected_version: Version
    payload_hash: Sha256
    decision: ReviewState
    acknowledged_issue_codes: list[str] = Field(default_factory=list)


class ChangePlan(Contract):
    id: UUID
    state: PlanState
    version: Version
    dataset_version: Version
    candidate_versions: dict[str, Version]
    snapshot_hash: Sha256


class ApplyRequest(Contract):
    expected_plan_version: Version
    expected_dataset_version: Version
    snapshot_hash: Sha256


class ApplyResponse(Contract):
    application_id: UUID
    dataset_version: Version
    snapshot_hash: Sha256
    applied_count: Annotated[int, Field(strict=True, ge=0)]


class ExportRequest(Contract):
    mode: ExportMode
    dataset_version: Version
    filters: dict[str, str | list[str]] = Field(default_factory=dict)


class ExportAccepted(Contract):
    job_id: UUID


class ErrorDetail(Contract):
    field_path: str | None = None
    code: NonEmpty
    message: NonEmpty


class APIError(Contract):
    code: Literal["BAD_REQUEST", "NOT_FOUND", "VERSION_CONFLICT", "PLAN_STALE", "IDEMPOTENCY_KEY_REUSED",
                  "ACTION_BLOCKED", "VALIDATION_ERROR", "PAYLOAD_TOO_LARGE", "INTERNAL_ERROR",
                  "FORBIDDEN", "METHOD_NOT_ALLOWED"]
    message: NonEmpty
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: NonEmpty


class ErrorResponse(Contract):
    error: APIError


class HealthResponse(Contract):
    status: Literal["ok"]
    version: str
    stage: Literal["T05"]
    database_status: Literal["NOT_INITIALIZED", "READY", "OUTDATED", "UNAVAILABLE"]
    model_status: Literal["NOT_CONFIGURED", "ADAPTER_NOT_IMPLEMENTED"]


class DestinationPreview(Contract):
    id: UUID
    name_en: str
    name_zh: str
    country_zh: str


class RegionSummary(Contract):
    id: UUID
    name: str
    destination_count: Annotated[int, Field(ge=0)]
    route_group_count: Annotated[int, Field(ge=0)]
    route_names: list[str]
    preview_destinations: list[DestinationPreview]


class BootstrapResponse(Contract):
    origin_name: str
    regions: list[RegionSummary]
    quotation_status: Literal["NOT_INITIALIZED"]
    model_status: Literal["NOT_CONFIGURED", "ADAPTER_NOT_IMPLEMENTED"]
    csrf_token: NonEmpty


class SessionResponse(Contract):
    status: Literal["VALID"]


def payload_hash(values: QuotationValues) -> str:
    """Canonical normalized payload, not source bytes; version tracked separately."""
    raw = json.dumps(values.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def patch_proposal(current: QuotationValues, patch: CandidatePatch) -> QuotationValues:
    """Pure proposal only: caller must invalidate review and produce a change plan."""
    return QuotationValues.model_validate({**current.model_dump(mode="json"),
                                          **patch.model_dump(mode="json", exclude_unset=True)})


def edit_candidate(candidate: Candidate, request: PatchRequest) -> Candidate:
    """Legacy T02 fixture transition only; production commands use domain.candidates.

    This helper does not record human provenance or an audit intention. Never
    persist its output as the implementation of a real candidate edit endpoint.
    """
    if request.expected_version != candidate.version:
        raise ValueError("VERSION_CONFLICT")
    if candidate.application_state != ApplicationState.NOT_APPLIED:
        raise ValueError("APPLIED_CANDIDATE_IMMUTABLE")
    proposed = patch_proposal(candidate.normalized_payload, request.changes)
    if proposed == candidate.normalized_payload:
        return candidate
    payload = candidate.model_dump(mode="json")
    payload.update(normalized_payload=proposed.model_dump(mode="json"), version=candidate.version + 1,
                   review_state="PENDING_REVIEW", review_version=None, reviewed_payload_hash=None,
                   reviewed_by=None, reviewed_at=None)
    if proposed.destination_id != candidate.normalized_payload.destination_id:
        payload["match_state"] = "UNMATCHED"
    return Candidate.model_validate(payload)


def derive_two_prices(first: Money, second: Money, *, confirmed_20gp_40ft: bool,
                      evidence_ids: list[UUID]) -> tuple[QuotationValues, Provenance]:
    if confirmed_20gp_40ft is not True or not evidence_ids:
        raise ValueError("TWO_PRICE_HEADERS_NOT_CONFIRMED")
    values = QuotationValues(price_20gp=first, price_40gp=second, price_40hq=second)
    provenance = Provenance(raw_value=second, normalized_value=second,
                            origin=ProvenanceOrigin.RULE_DERIVED, evidence_ids=evidence_ids,
                            rule_id="TWO_PRICE_20GP_40FT_V1")
    return values, provenance


def scaled_money(amount: str) -> int:
    # Independent of the ambient Decimal precision / rounding context.
    from .values import MoneyAmount
    return MoneyAmount(amount).scaled


def gate_issues(candidate: Candidate, *, qingdao_origin_id: UUID) -> list[Issue]:
    """Legacy T02 subset for fixtures; real commands use validation.action_blockers.

    This subset does not validate provenance, dates or container applicability.
    """
    result = []
    def add(code, fields, actions):
        result.append(Issue(code=code, field_paths=fields, message=code,
                            affected_actions=actions, severity="ERROR"))
    v = candidate.normalized_payload
    if v.origin_port_id != qingdao_origin_id:
        add("ORIGIN_NOT_CONFIRMED_QINGDAO", ["origin_port_id"], ["APPLY"])
    if v.destination_id is None or candidate.match_state != MatchState.CONFIRMED:
        add("DESTINATION_NOT_CONFIRMED", ["destination_id"], ["APPLY"])
    if candidate.review_state != ReviewState.APPROVED:
        add("REVIEW_REQUIRED", ["review_state"], ["APPLY"])
    if candidate.disposition != "INCLUDE" or candidate.application_state != ApplicationState.NOT_APPLIED:
        add("CANDIDATE_NOT_AVAILABLE", ["disposition", "application_state"], ["APPLY"])
    if all(getattr(v, f"price_{c}") is None for c in ("20gp", "40gp", "40hq")):
        add("NO_LITERAL_PRICE", ["price_20gp", "price_40gp", "price_40hq"], ["APPLY", "COMPARE"])
    if v.currency is None:
        add("CURRENCY_UNKNOWN", ["currency"], ["COMPARE"])
    result.extend(i for i in candidate.issues if i.resolution != "RESOLVED")
    return result


class ContractBundle(Contract):
    extraction: ExtractionOutput
    candidate: Candidate
    patch: PatchRequest
    review: ReviewRequest
    plan: ChangePlan
    apply_request: ApplyRequest
    apply_response: ApplyResponse
    export_request: ExportRequest
    export_accepted: ExportAccepted
    error: ErrorResponse
    job_state: JobState
    change_action: ChangeAction
    container_type: ContainerType
    destination: DestinationRef
    directory: DestinationDirectory
    health: HealthResponse
    bootstrap: BootstrapResponse
    session: SessionResponse
