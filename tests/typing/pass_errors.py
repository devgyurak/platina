"""Exception fields and constructors infer as ADR-0006 says, under pyright and mypy."""

from typing import Final, assert_type

from platina import (
    CheckViolation,
    DatabaseError,
    ModuleBoundaryError,
    PlatinaError,
    RelationNotLoaded,
    RetryExhausted,
    SealError,
    SourceLocation,
    UniqueViolation,
    UsageError,
)


class Order:
    pass


location = SourceLocation("shop/billing/usecases.py", 12, "pay")
assert_type(location.file, str)
assert_type(location.line, int)
assert_type(location.function, str | None)
assert_type(SourceLocation("shop/billing/entities.py", 29).function, str | None)

exc = RelationNotLoaded(
    "Order.items is not loaded.",
    usecase="pay",
    entity=Order,
    field="items",
    location=location,
    hint="add Load(Order.items)",
    details=(("Actual load declaration", "Load()"),),
)
assert_type(exc.usecase, str | None)
assert_type(exc.entity, type[object] | None)
assert_type(exc.field, str | None)
assert_type(exc.location, SourceLocation | None)
assert_type(exc.hint, str | None)
assert_type(exc.details, tuple[tuple[str, str], ...])

bare = PlatinaError("m")
assert_type(bare.location, SourceLocation | None)

usage: UsageError = RelationNotLoaded("m")
seal: SealError = ModuleBoundaryError("m", usecase="restock", entity=Order)

db = DatabaseError("connection lost", sqlstate=None)
assert_type(db.sqlstate, str | None)
unique = UniqueViolation("duplicate key value", sqlstate="23505")
assert_type(unique, UniqueViolation)
assert_type(unique.sqlstate, str | None)
check: DatabaseError = CheckViolation("check constraint", sqlstate="23514", entity=Order)

# The entity class is an object type, not Any: what it builds is an object.
assert exc.entity is not None
assert_type(exc.entity(), object)


class AttemptsExhausted(RetryExhausted):
    """A later issue's subclass: its own typed field and constructor (ADR-0006, decision 2)."""

    def __init__(self, *, attempts: int) -> None:
        super().__init__(f"gave up after {attempts} attempts")
        self.attempts: Final = attempts


assert_type(AttemptsExhausted(attempts=4).attempts, int)
assert_type(AttemptsExhausted(attempts=4).usecase, str | None)
