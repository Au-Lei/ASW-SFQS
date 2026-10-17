"""Action-specific validation. No database access, mutation or inferred defaults."""
from dataclasses import dataclass, field
import json
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from .contracts import (
    ApplicationState, Candidate, ContainerType, Evidence, Issue, IssueAction,
    MatchState, ProvenanceOrigin, QuotationValues, ReviewState,
)
from .errors import DomainError
from .values import price_for_container


# These facts are recomputed from the current content. An old stored warning
# must not survive its repair, or erase a newly detected failure by resolution.
RECOMPUTED_CODES = frozenset({
    "PROVENANCE_FIELD_UNKNOWN", "PROVENANCE_VALUE_MISMATCH", "PROVENANCE_UNCONFIRMED",
    "PROVENANCE_MISSING", "EVIDENCE_CONTEXT_REQUIRED", "EVIDENCE_NOT_FOUND",
    "EVIDENCE_OUTSIDE_BATCH", "DERIVATION_RULE_UNKNOWN", "TWO_PRICE_DERIVATION_STALE",
    "CONDITION_CONTEXT_REQUIRED", "CONDITION_NOT_FOUND", "ORIGIN_NOT_CONFIRMED_QINGDAO",
    "DESTINATION_NOT_CONFIRMED", "DESTINATION_OUT_OF_SCOPE", "REVIEW_REQUIRED",
    "CANDIDATE_NOT_AVAILABLE", "FORMAL_EXPORT_REQUIRES_SNAPSHOT", "NO_LITERAL_PRICE",
    "CONTAINER_PRICE_MISSING", "CURRENCY_UNKNOWN", "PRICE_SCOPE_UNKNOWN",
    "VALIDITY_INCOMPLETE", "VALIDITY_BASIS_UNSPECIFIED", "CARRIER_UNKNOWN",
    "SOURCE_CODE_UNASSIGNED",
})


@dataclass(frozen=True)
class EvidenceContext:
    """Trusted service input: available evidence and files in this candidate's batch.

    A model or client must not supply this registry as proof of its own output.
    File existence and sheet/image bounds are checked by the future storage/parser.
    """
    evidence: Mapping[UUID, Evidence] = field(default_factory=dict)
    allowed_file_ids: frozenset[UUID] = frozenset()
    condition_keys: frozenset[str] = frozenset()

    def __post_init__(self):
        copies = {}
        for key, value in self.evidence.items():
            if not isinstance(key, UUID) or value.id != key:
                raise DomainError("EVIDENCE_REGISTRY_INVALID")
            copies[key] = Evidence.model_validate(value.model_dump(mode="json"))
        if any(not isinstance(key, UUID) for key in self.allowed_file_ids):
            raise DomainError("EVIDENCE_REGISTRY_INVALID")
        object.__setattr__(self, "evidence", MappingProxyType(copies))
        object.__setattr__(self, "allowed_file_ids", frozenset(self.allowed_file_ids))
        object.__setattr__(self, "condition_keys", frozenset(self.condition_keys))


def validated_candidate(candidate: Candidate) -> Candidate:
    # Pydantic model_copy(update=...) and in-place changes skip normal validation.
    return Candidate.model_validate(candidate.model_dump(mode="json"))


def issue(code, paths, actions, *, severity="ERROR", message=None):
    return Issue(code=code, field_paths=paths, affected_actions=actions,
                 severity=severity, message=message or code)


def resolve_field(values: QuotationValues, path: str):
    node = values.model_dump(mode="json")
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise DomainError("PROVENANCE_FIELD_UNKNOWN", field_paths=(path,))
        node = node[part]
    return node


def same_value(left, right):
    # Python equality treats True==1 and 1.0==1; provenance must preserve types.
    try:
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return False


def provenance_issues(candidate: Candidate, *, context: EvidenceContext | None = None) -> list[Issue]:
    """Check nondefault business values, explicit null proofs and evidence references."""
    values = candidate.normalized_payload
    result = []
    actions = [IssueAction.REVIEW, IssueAction.APPLY, IssueAction.COMPARE]
    defaults = QuotationValues().model_dump(mode="json")
    supplied = values.model_dump(mode="json")
    valid_paths = set()
    for path, provenance in candidate.field_provenance.items():
        try:
            actual = resolve_field(values, path)
        except DomainError:
            result.append(issue("PROVENANCE_FIELD_UNKNOWN", [path], actions))
            continue
        if not same_value(actual, provenance.model_dump(mode="json")["normalized_value"]):
            result.append(issue("PROVENANCE_VALUE_MISMATCH", [path], actions))
            continue
        if provenance.origin == ProvenanceOrigin.UNKNOWN:
            if actual is None or actual in ([], "UNKNOWN", "UNSPECIFIED"):
                continue  # A known missing value can be acknowledged as missing.
            result.append(issue("PROVENANCE_UNCONFIRMED", [path], actions))
            continue
        if provenance.origin == ProvenanceOrigin.RULE_DERIVED:
            if provenance.rule_id != "TWO_PRICE_20GP_40FT_V1":
                result.append(issue("DERIVATION_RULE_UNKNOWN", [path], actions))
                continue
            if (path != "price_40hq" or values.price_20gp is None or values.price_40gp is None
                    or values.price_40hq != values.price_40gp
                    or provenance.raw_value != values.price_40gp):
                result.append(issue("TWO_PRICE_DERIVATION_STALE", [path], actions))
                continue
        if provenance.evidence_ids:
            if context is None:
                result.append(issue("EVIDENCE_CONTEXT_REQUIRED", [path], actions))
                continue
            missing = [key for key in provenance.evidence_ids if key not in context.evidence]
            outside = [key for key in provenance.evidence_ids if key in context.evidence and
                       context.evidence[key].file_id not in context.allowed_file_ids]
            if missing:
                result.append(issue("EVIDENCE_NOT_FOUND", [path], actions))
                continue
            if outside:
                result.append(issue("EVIDENCE_OUTSIDE_BATCH", [path], actions))
                continue
        valid_paths.add(path)

    def covered(path, value):
        # An explicit object-level proof covers all leaves; otherwise each
        # meaningful leaf requires proof. Empty defaults need no fabricated source.
        if path in valid_paths:
            return True
        if isinstance(value, dict):
            return all(covered(path + "." + k, v) for k, v in value.items()
                       if v not in (None, [], "UNKNOWN", "UNSPECIFIED"))
        return False

    for path, value in supplied.items():
        if value != defaults[path] and not covered(path, value):
            result.append(issue("PROVENANCE_MISSING", [path], actions))
    year_ids = values.validity.year_evidence_ids
    if year_ids:
        if context is None:
            result.append(issue("EVIDENCE_CONTEXT_REQUIRED", ["validity.year_evidence_ids"], actions))
        elif any(key not in context.evidence for key in year_ids):
            result.append(issue("EVIDENCE_NOT_FOUND", ["validity.year_evidence_ids"], actions))
        elif any(context.evidence[key].file_id not in context.allowed_file_ids for key in year_ids):
            result.append(issue("EVIDENCE_OUTSIDE_BATCH", ["validity.year_evidence_ids"], actions))
    if values.condition_keys:
        if context is None:
            result.append(issue("CONDITION_CONTEXT_REQUIRED", ["condition_keys"], actions))
        elif not set(values.condition_keys) <= context.condition_keys:
            result.append(issue("CONDITION_NOT_FOUND", ["condition_keys"], actions))
    return result


def candidate_issues(candidate: Candidate, *, qingdao_origin_id: UUID,
                     context: EvidenceContext | None = None,
                     container: ContainerType | str | None = None) -> list[Issue]:
    candidate = validated_candidate(candidate)
    values = candidate.normalized_payload
    generated = provenance_issues(candidate, context=context)
    if values.origin_port_id != qingdao_origin_id:
        generated.append(issue("ORIGIN_NOT_CONFIRMED_QINGDAO", ["origin_port_id"], ["APPLY", "COMPARE"]))
    if values.destination_id is None or candidate.match_state != MatchState.CONFIRMED:
        generated.append(issue("DESTINATION_NOT_CONFIRMED", ["destination_id"], ["APPLY", "COMPARE"]))
    if candidate.match_state == MatchState.OUT_OF_SCOPE:
        generated.append(issue("DESTINATION_OUT_OF_SCOPE", ["destination_id"], ["APPLY", "COMPARE"]))
    if candidate.review_state != ReviewState.APPROVED:
        generated.append(issue("REVIEW_REQUIRED", ["review_state"], ["APPLY", "COMPARE"]))
    if candidate.application_state != ApplicationState.NOT_APPLIED or candidate.disposition != "INCLUDE":
        generated.append(issue("CANDIDATE_NOT_AVAILABLE", ["application_state", "disposition"], ["APPLY", "COMPARE"]))
    generated.append(issue("FORMAL_EXPORT_REQUIRES_SNAPSHOT", [], ["EXPORT"], severity="INFO"))
    if all(getattr(values, "price_" + c.value.lower()) is None for c in ContainerType):
        generated.append(issue("NO_LITERAL_PRICE", ["price_20gp", "price_40gp", "price_40hq"], ["APPLY", "COMPARE"]))
    if container is not None and price_for_container(values, container) is None:
        generated.append(issue("CONTAINER_PRICE_MISSING", ["price_" + ContainerType(container).value.lower()], ["COMPARE"]))
    if values.currency is None:
        generated.append(issue("CURRENCY_UNKNOWN", ["currency"], ["COMPARE"], severity="WARNING"))
    if values.price_scope_summary is None:
        generated.append(issue("PRICE_SCOPE_UNKNOWN", ["price_scope_summary"], ["COMPARE"], severity="WARNING"))
    if values.validity.valid_from is None or values.validity.valid_to is None:
        generated.append(issue("VALIDITY_INCOMPLETE", ["validity.valid_from", "validity.valid_to"], ["DATE_FILTER"], severity="WARNING"))
    if values.validity.basis == "UNSPECIFIED":
        generated.append(issue("VALIDITY_BASIS_UNSPECIFIED", ["validity.basis"], ["DATE_FILTER"], severity="WARNING"))
    for path, code in (("carrier_id", "CARRIER_UNKNOWN"), ("source_code", "SOURCE_CODE_UNASSIGNED")):
        if getattr(values, path) is None:
            generated.append(issue(code, [path], [], severity="INFO"))

    # Generated invariants cannot be removed by setting a stored issue RESOLVED.
    # Reuse human acknowledgment only for an identical still-present issue.
    def key(item):
        return item.code, tuple(item.field_paths), tuple(item.affected_actions)
    existing = {key(item): item for item in candidate.issues}
    result = []
    for item in generated:
        previous = existing.pop(key(item), None)
        if previous is not None and previous.resolution == "ACKNOWLEDGED":
            item = Issue.model_validate({**item.model_dump(mode="json"),
                "resolution": "ACKNOWLEDGED", "acknowledged_by": previous.acknowledged_by,
                "acknowledged_at": previous.acknowledged_at})
        result.append(item)
    result.extend(item for item in existing.values() if item.code not in RECOMPUTED_CODES)
    return result


def action_blockers(candidate: Candidate, action: IssueAction | str, *, qingdao_origin_id: UUID,
                    context: EvidenceContext | None = None, container=None) -> list[Issue]:
    action = IssueAction(action)
    return [item for item in candidate_issues(candidate, qingdao_origin_id=qingdao_origin_id,
            context=context, container=container)
            if action in item.affected_actions and item.resolution != "RESOLVED"]


def require_action(candidate: Candidate, action: IssueAction | str, **kwargs):
    blocked = action_blockers(candidate, action, **kwargs)
    if blocked:
        raise DomainError("ACTION_BLOCKED", issue_codes=tuple(sorted({i.code for i in blocked})))
