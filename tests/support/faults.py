"""Builders for the driver contract's data (``platina.drivers.interface``), without psycopg.

The unit tests that use them also run on free-threaded 3.14t, where psycopg cannot be imported:
nothing here imports a driver. Every call builds fresh objects (a fault carries an exception,
which is mutable), so no instance is shared between the threads that run one test.
"""

from __future__ import annotations

import pickle
from typing import Any

from platina.drivers.interface import DatabaseFault, SessionUnavailable, StatementResult


class DriverFailure(Exception):
    """Stand-in for the driver's exception that a fault carries as ``cause``."""


def fault(
    sqlstate: str | None = "23505",
    *,
    message: str = 'duplicate key value violates unique constraint "orders_number_key"',
    constraint: str | None = None,
    table: str | None = None,
    schema: str | None = None,
) -> DatabaseFault:
    """A fault whose ``cause`` is a fresh ``DriverFailure`` that also carries a ``DETAIL`` line,
    as psycopg's ``str(exc)`` does: the key values must not reach the public error's text.
    """
    cause = DriverFailure(f"{message}\nDETAIL:  Key (number)=(42) already exists.")
    return DatabaseFault(
        sqlstate=sqlstate,
        message=message,
        constraint=constraint,
        table=table,
        schema=schema,
        cause=cause,
    )


def results(count: int) -> tuple[StatementResult, ...]:
    """``count`` distinct statement results, as a prefix of a pipeline's results."""
    return tuple(StatementResult(f"INSERT 0 {n}", n, ()) for n in range(count))


def pickled[T](value: T) -> T:
    """``value`` after a pickle round trip."""
    restored: T = pickle.loads(pickle.dumps(value))
    return restored


def unavailable_state(exc: SessionUnavailable) -> tuple[Any, ...]:
    """What a faithful copy of ``exc`` keeps: class, args, the fault's fields and its cause's
    class and args (an exception compares by identity, so the cause itself cannot be compared).
    """
    f = exc.fault
    return (
        type(exc), exc.args, f.sqlstate, f.message, f.constraint, f.table, f.schema,
        type(f.cause), f.cause.args,
    )  # fmt: skip
