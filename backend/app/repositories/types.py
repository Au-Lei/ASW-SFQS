"""Exact SQLite storage; no binary floating point at the money boundary."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.types import TypeDecorator

from backend.app.domain.contracts import scaled_money
from backend.app.domain.values import MoneyAmount


class Money(TypeDecorator):
    """Decimal in Python, nonnegative integer in SQLite (one unit = .0001)."""
    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, (str, Decimal)):
            raise ValueError("Money requires a decimal string or Decimal")
        return scaled_money(format(value, "f") if isinstance(value, Decimal) else value)

    def process_result_value(self, value, dialect):
        return None if value is None else MoneyAmount.from_scaled(value).decimal


class UTCDateTime(TypeDecorator):
    """UTC ISO timestamp in SQLite; reject naive timestamps on writes."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp requires an explicit timezone")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


def utc_now():
    return datetime.now(timezone.utc)
