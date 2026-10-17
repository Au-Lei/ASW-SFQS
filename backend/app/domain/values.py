"""Immutable exact money, container selection and date applicability values."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
import re

from pydantic import TypeAdapter

from .contracts import ContainerType, DateBasis, ISODate, Money, QuotationValues, Validity
from .errors import DomainError


@dataclass(frozen=True, init=False)
class MoneyAmount:
    scaled: int

    def __init__(self, amount: str | Decimal):
        raw = format(amount, "f") if isinstance(amount, Decimal) else amount
        validated = TypeAdapter(Money).validate_python(raw)
        integer, _, fraction = validated.partition(".")
        object.__setattr__(self, "scaled", int(integer) * 10000 + int(fraction.ljust(4, "0")))

    @classmethod
    def from_scaled(cls, value: int):
        if type(value) is not int or not 0 <= value <= 999999999999999999:
            raise DomainError("MONEY_SCALED_INVALID")
        return cls(f"{value // 10000}.{value % 10000:04d}")

    @property
    def decimal(self) -> Decimal:
        return Decimal(f"{self.scaled // 10000}.{self.scaled % 10000:04d}")

    @property
    def wire(self) -> str:
        return format(self.decimal, "f").rstrip("0").rstrip(".") if self.scaled % 10000 else str(self.scaled // 10000)


def full_date(value: str | date) -> date:
    if type(value) is date:
        return value
    return date.fromisoformat(TypeAdapter(ISODate).validate_python(value))


class DateApplicability(str, Enum):
    MATCH = "MATCH"
    OUTSIDE = "OUTSIDE"
    UNCONFIRMED = "UNCONFIRMED"


@dataclass(frozen=True)
class DateWindow:
    valid_from: date | None
    valid_to: date | None
    basis: DateBasis = DateBasis.UNSPECIFIED

    def __post_init__(self):
        if any(value is not None and type(value) is not date for value in (self.valid_from, self.valid_to)):
            raise DomainError("FULL_DATE_REQUIRED")
        object.__setattr__(self, "basis", DateBasis(self.basis))
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise DomainError("VALIDITY_REVERSED")

    @classmethod
    def from_validity(cls, validity: Validity):
        validated = Validity.model_validate(validity.model_dump(mode="json"))
        return cls(full_date(validated.valid_from) if validated.valid_from else None,
                   full_date(validated.valid_to) if validated.valid_to else None, validated.basis)

    def assess(self, requested: str | date, *, basis: DateBasis) -> DateApplicability:
        requested = full_date(requested)
        basis = DateBasis(basis)
        if basis == DateBasis.UNSPECIFIED or self.basis == DateBasis.UNSPECIFIED or self.basis != basis:
            return DateApplicability.UNCONFIRMED
        if ((self.valid_from and requested < self.valid_from) or
                (self.valid_to and requested > self.valid_to)):
            return DateApplicability.OUTSIDE
        return DateApplicability.MATCH if self.valid_from and self.valid_to else DateApplicability.UNCONFIRMED


def price_for_container(values: QuotationValues, container: ContainerType | str) -> MoneyAmount | None:
    container = ContainerType(container)  # Reject ambiguous "40FT" and unrecognized types.
    price = getattr(values, "price_" + container.value.lower())
    return None if price is None else MoneyAmount(price)


def confirmed_month_day(month_day: str, *, year: int | None) -> date:
    """Explicit confirmed context only; never infer a year from today's date."""
    if type(year) is not int or not 1 <= year <= 9999:
        raise DomainError("VALIDITY_YEAR_REQUIRED")
    if not isinstance(month_day, str) or not re.fullmatch(r"[0-9]{2}-[0-9]{2}", month_day):
        raise DomainError("MONTH_DAY_INVALID")
    return full_date(f"{year:04d}-{month_day}")
