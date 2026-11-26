"""Misuse of exception constructors and fields is a type error under pyright and mypy (ADR-0006)."""

from platina import (
    CheckViolation,
    DatabaseError,
    ForeignKeyViolation,
    PlatinaError,
    RelationNotLoaded,
    SourceLocation,
    UniqueViolation,
)


class Order:
    pass


exc = RelationNotLoaded("Order.items is not loaded.", entity=Order)
location = SourceLocation("shop/billing/usecases.py", 12, "pay")
db = DatabaseError("connection lost", sqlstate=None)

# fmt: off
PlatinaError("m", "pay")  # expect-error[reportCallIssue, call-arg]: fields are keyword-only
PlatinaError(message="m")  # expect-error[reportCallIssue, call-arg]: the message is positional-only
RelationNotLoaded("m", entity="Order")  # expect-error[reportArgumentType, arg-type]: entity is the class, not its name
RelationNotLoaded("m", location=("a.py", 1))  # expect-error[reportArgumentType, arg-type]: location is a SourceLocation
RelationNotLoaded("m", details=[("Label", "value")])  # expect-error[reportArgumentType, arg-type]: details is a tuple
exc.usecase = "pay"  # expect-error[reportAttributeAccessIssue, misc]: fields are read-only
exc.entity = Order  # expect-error[reportAttributeAccessIssue, misc]: fields are read-only
location.line = 13  # expect-error[reportAttributeAccessIssue, misc]: SourceLocation is frozen
DatabaseError("connection lost")  # expect-error[reportCallIssue, call-arg]: sqlstate is required
UniqueViolation("x", sqlstate="23505")  # expect-error[reportCallIssue, call-arg]: the subclass fixes its SQLSTATE
CheckViolation("x", sqlstate="23514")  # expect-error[reportCallIssue, call-arg]: the subclass fixes its SQLSTATE
ForeignKeyViolation("x", sqlstate="23505")  # expect-error[reportArgumentType, arg-type]: only 23503 or 23001
ForeignKeyViolation("x")  # expect-error[reportCallIssue, call-arg]: sqlstate is required
UniqueViolation(message="m")  # expect-error[reportCallIssue, call-arg]: the message is positional-only
DatabaseError("duplicate key value", "23505")  # expect-error[reportCallIssue, call-arg]: sqlstate is keyword-only
DatabaseError(message="m", sqlstate=None)  # expect-error[reportCallIssue, call-arg]: the message is positional-only here too
db.sqlstate = "40001"  # expect-error[reportAttributeAccessIssue, misc]: sqlstate is read-only
exc.details = ()  # expect-error[reportAttributeAccessIssue, misc]: fields are read-only
SourceLocation("a.py", "12")  # expect-error[reportArgumentType, arg-type]: line is an int


class NarrowedUsecase(PlatinaError):
    usecase: str  # expect-error[reportGeneralTypeIssues, misc]: fields are Final, a subclass cannot narrow them
# fmt: on
