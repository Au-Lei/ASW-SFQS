"""Pure candidate commands with explicit human identity and audit intentions.

These functions do not apply quotations or write a database. T12/T14 services
must atomically persist the returned candidate and event using optimistic locks.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID

from .contracts import (
    ApplicationState, Candidate, Destination, Issue, MatchState, PatchRequest,
    Provenance, ReviewRequest, ReviewState, patch_proposal, payload_hash,
)
from .errors import DomainError
from .transitions import require_transition
from .validation import EvidenceContext, candidate_issues, resolve_field, same_value, validated_candidate


@dataclass(frozen=True)
class CandidateEvent:
    action: str
    candidate_id: UUID
    actor_id: UUID
    occurred_at: str
    before_json: str
    after_json: str
    before_hash: str
    after_hash: str
    changed_fields: tuple[str, ...]


@dataclass(frozen=True)
class CandidateChange:
    candidate: Candidate
    event: CandidateEvent | None


def _identity(actor_id: UUID, at: datetime | None):
    if not isinstance(actor_id, UUID):
        raise DomainError("HUMAN_ACTOR_REQUIRED")
    at = at if at is not None else datetime.now(timezone.utc)
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise DomainError("TIMEZONE_REQUIRED")
    return actor_id, at.astimezone(timezone.utc).isoformat()


def _editable(candidate: Candidate, expected_version: int):
    candidate = validated_candidate(candidate)
    if type(expected_version) is not int or expected_version != candidate.version:
        raise DomainError("VERSION_CONFLICT")
    if candidate.application_state != ApplicationState.NOT_APPLIED:
        raise DomainError("APPLIED_CANDIDATE_IMMUTABLE")
    return candidate


def _invalidate(payload):
    payload.update(review_state="PENDING_REVIEW", review_version=None,
                   reviewed_payload_hash=None, reviewed_by=None, reviewed_at=None)
    # Known missing values stay visible. Previously acknowledged/resolved doubts
    # must be evaluated again after content, proof, or matching changes.
    for item in payload["issues"]:
        item.update(resolution="OPEN", acknowledged_by=None, acknowledged_at=None)


def _finish(before, payload, action, actor_id, timestamp, changed_fields):
    payload["version"] = before.version + 1
    after = Candidate.model_validate(payload)
    def canonical(value):
        return json.dumps(value.model_dump(mode="json"), ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"), allow_nan=False)
    previous, current = canonical(before), canonical(after)
    event = CandidateEvent(action=action, candidate_id=before.id, actor_id=actor_id,
        occurred_at=timestamp, before_json=previous, after_json=current,
        before_hash=hashlib.sha256(previous.encode("utf-8")).hexdigest(),
        after_hash=hashlib.sha256(current.encode("utf-8")).hexdigest(),
        changed_fields=tuple(sorted(changed_fields)))
    return CandidateChange(after, event)


def _manual_proof(payload, path, value, actor, timestamp, *, old_value):
    old = payload["field_provenance"].get(path)
    raw = old["raw_value"] if old is not None else old_value
    # A whole structured PATCH replaces the object, including its proof leaves.
    for existing in list(payload["field_provenance"]):
        if existing == path or existing.startswith(path + ".") or path.startswith(existing + "."):
            del payload["field_provenance"][existing]
    payload["field_provenance"][path] = Provenance(
        raw_value=raw, normalized_value=value, origin="MANUAL", recorded_by=actor,
        recorded_at=timestamp,
    ).model_dump(mode="json")


def edit_candidate(candidate: Candidate, request: PatchRequest, *, actor_id: UUID,
                   at: datetime | None = None) -> CandidateChange:
    candidate = _editable(candidate, request.expected_version)
    actor, timestamp = _identity(actor_id, at)
    proposed = patch_proposal(candidate.normalized_payload, request.changes)
    previous = candidate.normalized_payload.model_dump(mode="json")
    current = proposed.model_dump(mode="json")
    changed = {path for path in current if current[path] != previous[path]}
    if not changed:
        return CandidateChange(candidate, None)
    payload = candidate.model_dump(mode="json")
    payload["normalized_payload"] = current
    for path in changed:
        _manual_proof(payload, path, current[path], actor, timestamp, old_value=previous[path])
    _invalidate(payload)
    if changed & {"origin_port_id", "destination_id", "source_id"}:
        payload["match_state"] = "UNMATCHED"
    return _finish(candidate, payload, "EDIT_CANDIDATE", actor, timestamp, changed)


def confirm_fields(candidate: Candidate, fields: set[str], *, expected_version: int,
                   actor_id: UUID, at: datetime | None = None) -> CandidateChange:
    """Explicit human confirmation of displayed values, including deliberate nulls."""
    candidate = _editable(candidate, expected_version)
    actor, timestamp = _identity(actor_id, at)
    if not fields:
        return CandidateChange(candidate, None)
    # Prevent an object-level confirmation from accidentally erasing a second
    # supplied proof below it (ambiguous mixed parent/child requests).
    if any(a != b and b.startswith(a + ".") for a in fields for b in fields):
        raise DomainError("PROVENANCE_OVERLAPPING_FIELDS")
    payload = candidate.model_dump(mode="json")
    for path in sorted(fields):
        value = resolve_field(candidate.normalized_payload, path)
        _manual_proof(payload, path, value, actor, timestamp, old_value=value)
    _invalidate(payload)
    return _finish(candidate, payload, "CONFIRM_FIELDS", actor, timestamp,
                   ("field_provenance." + path for path in fields))


def replace_provenance(candidate: Candidate, fields: dict[str, Provenance], *, expected_version: int,
                       actor_id: UUID, context: EvidenceContext, at: datetime | None = None) -> CandidateChange:
    """Trusted parser/evidence correction command; cannot be a free-form public PATCH."""
    candidate = _editable(candidate, expected_version)
    actor, timestamp = _identity(actor_id, at)
    payload = candidate.model_dump(mode="json")
    changed = set()
    for path, proof in fields.items():
        proof = Provenance.model_validate(proof.model_dump(mode="json"))
        actual = resolve_field(candidate.normalized_payload, path)
        if not same_value(proof.model_dump(mode="json")["normalized_value"], actual):
            raise DomainError("PROVENANCE_VALUE_MISMATCH", field_paths=(path,))
        if proof.origin == "MANUAL" and (proof.recorded_by != actor or proof.recorded_at != timestamp):
            raise DomainError("MANUAL_ACTOR_MISMATCH", field_paths=(path,))
        for key in proof.evidence_ids:
            if key not in context.evidence:
                raise DomainError("EVIDENCE_NOT_FOUND", field_paths=(path,))
            if context.evidence[key].file_id not in context.allowed_file_ids:
                raise DomainError("EVIDENCE_OUTSIDE_BATCH", field_paths=(path,))
        value = proof.model_dump(mode="json")
        if payload["field_provenance"].get(path) != value:
            payload["field_provenance"][path] = value
            changed.add("field_provenance." + path)
    if not changed:
        return CandidateChange(candidate, None)
    _invalidate(payload)
    return _finish(candidate, payload, "REPLACE_PROVENANCE", actor, timestamp, changed)


def match_candidate(candidate: Candidate, state: MatchState | str, *, expected_version: int,
                    actor_id: UUID, destination: Destination | None = None,
                    at: datetime | None = None) -> CandidateChange:
    candidate = _editable(candidate, expected_version)
    actor, timestamp = _identity(actor_id, at)
    state = MatchState(state)
    require_transition(MatchState, candidate.match_state, state)
    payload = candidate.model_dump(mode="json")
    if state == MatchState.CONFIRMED:
        if destination is None:
            raise DomainError("CONFIRMED_DESTINATION_REQUIRED")
        destination = Destination.model_validate(destination.model_dump(mode="json"))
        if not destination.active:
            raise DomainError("DESTINATION_INACTIVE")
        target = str(destination.id)
        if state == candidate.match_state and target == payload["normalized_payload"]["destination_id"]:
            return CandidateChange(candidate, None)
        old = payload["normalized_payload"]["destination_id"]
        payload["normalized_payload"]["destination_id"] = target
        _manual_proof(payload, "destination_id", target, actor, timestamp, old_value=old)
    elif state == candidate.match_state:
        return CandidateChange(candidate, None)
    payload["match_state"] = state.value
    _invalidate(payload)
    return _finish(candidate, payload, "MATCH_CANDIDATE", actor, timestamp, ("match_state", "destination_id"))


def review_candidate(candidate: Candidate, request: ReviewRequest, *, actor_id: UUID,
                     qingdao_origin_id: UUID, context: EvidenceContext | None = None,
                     at: datetime | None = None) -> CandidateChange:
    candidate = _editable(candidate, request.expected_version)
    actor, timestamp = _identity(actor_id, at)
    if request.payload_hash != payload_hash(candidate.normalized_payload):
        raise DomainError("REVIEW_PAYLOAD_CHANGED")
    require_transition(ReviewState, candidate.review_state, request.decision)
    if request.decision == candidate.review_state:
        if request.acknowledged_issue_codes:
            raise DomainError("REVIEW_NOOP_CANNOT_ACKNOWLEDGE")
        return CandidateChange(candidate, None)
    payload = candidate.model_dump(mode="json")
    _invalidate(payload)
    if request.decision == ReviewState.APPROVED:
        issues = candidate_issues(candidate, qingdao_origin_id=qingdao_origin_id, context=context)
        blocked = [item for item in issues if "REVIEW" in item.affected_actions and item.resolution != "RESOLVED"]
        if blocked:
            raise DomainError("ACTION_BLOCKED", issue_codes=sorted({item.code for item in blocked}))
        # REVIEW_REQUIRED is the operation being performed. Other limits can be
        # acknowledged without pretending they have become valid for APPLY/COMPARE.
        relevant = [item for item in issues if item.code not in ("REVIEW_REQUIRED", "CANDIDATE_NOT_AVAILABLE")]
        ack = set(request.acknowledged_issue_codes)
        known = {item.code for item in relevant if item.resolution != "RESOLVED"}
        if not ack <= known:
            raise DomainError("ACKNOWLEDGMENT_UNKNOWN", issue_codes=sorted(ack - known))
        required = {item.code for item in relevant if item.severity != "INFO" and item.resolution == "OPEN"}
        if not required <= ack:
            raise DomainError("ACKNOWLEDGMENT_REQUIRED", issue_codes=sorted(required - ack))
        reviewed = []
        for item in relevant:
            data = item.model_dump(mode="json")
            if item.code in ack and item.resolution != "RESOLVED":
                data.update(resolution="ACKNOWLEDGED", acknowledged_by=str(actor), acknowledged_at=timestamp)
            reviewed.append(Issue.model_validate(data).model_dump(mode="json"))
        payload.update(issues=reviewed, review_version=candidate.version + 1,
            reviewed_payload_hash=payload_hash(candidate.normalized_payload),
            reviewed_by=str(actor), reviewed_at=timestamp)
    elif request.acknowledged_issue_codes:
        raise DomainError("ACKNOWLEDGMENT_REQUIRES_APPROVAL")
    payload["review_state"] = request.decision.value
    return _finish(candidate, payload, "REVIEW_CANDIDATE", actor, timestamp, ("review_state", "issues"))
