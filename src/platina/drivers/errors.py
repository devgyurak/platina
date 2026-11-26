"""SQLSTATE -> exception mapping (engine rule 10, ADR-0012).

The runner calls ``database_error`` with the use case it is running, so the public exception is
built complete (its fields are read-only, ADR-0006). The driver's exception becomes its
``__cause__``. This module classifies nothing beyond the exception class: retry, ``AlreadyClaimed``
and an unknown commit outcome are the engine's (#17).
"""

from __future__ import annotations

from platina.core.errors import CheckViolation, DatabaseError, ForeignKeyViolation, UniqueViolation
from platina.drivers.interface import DatabaseFault

FOREIGN_KEY_HINT = (
    "delete or re-point the rows that still reference it first, in the same use case, "
    "or reference a row that exists"
)


def database_error(fault: DatabaseFault, *, usecase: str | None) -> DatabaseError:
    """The public exception for ``fault``: ``UniqueViolation`` (23505), ``CheckViolation`` (23514),
    ``ForeignKeyViolation`` (23503 / 23001, with a hint) or ``DatabaseError``, with
    ``Constraint:`` / ``Table:`` detail lines when the server named them. Naming the referencing
    entity and field needs the registry (#25's naming rule); the table line stands in until then.

    The server's ``DETAIL`` text is left out on purpose: for 23505 it holds the key values, which
    would land in every log line of ``str(exc)``. It stays readable on ``__cause__``.
    """
    details = _details(fault)
    error: DatabaseError
    # One constructor call per class, not a table of classes: UniqueViolation and CheckViolation
    # fix their SQLSTATE and take no `sqlstate`, which a call through `type[DatabaseError]` would
    # still pass type checking with.
    match fault.sqlstate:
        case "23505":
            error = UniqueViolation(fault.message, usecase=usecase, details=details)
        case "23514":
            error = CheckViolation(fault.message, usecase=usecase, details=details)
        case "23503" | "23001" as sqlstate:
            error = ForeignKeyViolation(
                fault.message,
                sqlstate=sqlstate,
                usecase=usecase,
                details=details,
                hint=FOREIGN_KEY_HINT,
            )
        case sqlstate:
            error = DatabaseError(
                fault.message, sqlstate=sqlstate, usecase=usecase, details=details
            )
    error.__cause__ = fault.cause  # what `raise error from fault.cause` sets
    error.__suppress_context__ = True
    return error


def _details(fault: DatabaseFault) -> tuple[tuple[str, str], ...]:
    lines: list[tuple[str, str]] = []
    if fault.constraint is not None:
        lines.append(("Constraint", fault.constraint))
    if fault.table is not None:
        table = fault.table if fault.schema is None else f"{fault.schema}.{fault.table}"
        lines.append(("Table", table))
    return tuple(lines)
