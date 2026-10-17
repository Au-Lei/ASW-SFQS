"""Allowed transitions only; execution, persistence and transactions are separate."""
from .contracts import ApplicationState, MatchState, PlanState, ReviewState
from .errors import DomainError


TRANSITIONS = {
    ReviewState: {
        "PENDING_REVIEW": {"APPROVED", "NEEDS_INFO", "REJECTED"},
        "APPROVED": {"PENDING_REVIEW"},
        "NEEDS_INFO": {"PENDING_REVIEW"},
        "REJECTED": {"PENDING_REVIEW"},
    },
    MatchState: {
        "UNMATCHED": {"SUGGESTED", "CONFIRMED", "OUT_OF_SCOPE"},
        "SUGGESTED": {"UNMATCHED", "CONFIRMED", "OUT_OF_SCOPE"},
        "CONFIRMED": {"UNMATCHED", "SUGGESTED", "OUT_OF_SCOPE"},
        "OUT_OF_SCOPE": {"UNMATCHED", "SUGGESTED", "CONFIRMED"},
    },
    ApplicationState: {
        "NOT_APPLIED": {"APPLIED", "NO_CHANGE", "EXCLUDED"},
        "APPLIED": set(), "NO_CHANGE": set(), "EXCLUDED": set(),
    },
    PlanState: {
        "DRAFT": {"READY", "STALE", "CANCELLED"},
        "READY": {"APPLIED", "STALE", "CANCELLED"},
        "APPLIED": set(), "STALE": set(), "CANCELLED": set(),
    },
}


def require_transition(enum, before, after):
    if enum not in TRANSITIONS:
        raise DomainError("STATE_MACHINE_UNSUPPORTED")
    before, after = enum(before), enum(after)
    if before == after:
        return  # Identity operation has no event or version increment.
    if after not in TRANSITIONS[enum][before]:
        raise DomainError("STATE_TRANSITION_FORBIDDEN")
