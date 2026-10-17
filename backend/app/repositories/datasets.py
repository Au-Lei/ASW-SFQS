"""Dataset compare-and-swap plus an immutable, self-contained logical snapshot.

The caller owns an IMMEDIATE unit_of_work. T17 will compose this with quotation
changes, application rows and audit entries; this helper never commits by itself.
"""
from copy import deepcopy
import hashlib
import json

from sqlalchemy import update

from .models import DatasetSnapshot, DatasetVersion
from .types import utc_now


class DatasetVersionConflict(Exception):
    """Translate to VERSION_CONFLICT/PLAN_STALE at the future service boundary."""


def advance_dataset(session, *, origin_port_id, expected_version: int, payload: dict):
    if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
        raise ValueError("Expected dataset version must be positive")
    # Reject floats recursively, including integers represented as floats.
    def exact(value):
        if isinstance(value, float):
            raise ValueError("Snapshot numbers must not use binary floats")
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("Snapshot object keys must be strings")
            for item in value.values():
                exact(item)
        elif isinstance(value, list):
            for item in value:
                exact(item)
        elif value is not None and not isinstance(value, (str, bool, int)):
            raise ValueError("Snapshot values must use JSON types")

    if not isinstance(payload, dict):
        raise ValueError("Snapshot payload must be an object")
    exact(payload)
    frozen = deepcopy(payload)
    canonical = json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    result = session.execute(update(DatasetVersion).where(
        DatasetVersion.origin_port_id == origin_port_id,
        DatasetVersion.dataset_version == expected_version,
    ).values(dataset_version=expected_version + 1,
             version=DatasetVersion.version + 1, updated_at=utc_now()),
        execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        raise DatasetVersionConflict("Dataset version changed or origin has not been initialized")
    snapshot = DatasetSnapshot(origin_port_id=origin_port_id, dataset_version=expected_version + 1,
                               payload_json=frozen, payload_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest())
    session.add(snapshot)
    session.flush()
    return snapshot
