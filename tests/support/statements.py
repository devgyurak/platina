"""Statements and replies of the driver contract (``platina.drivers.interface``), without psycopg.

``SQL`` satisfies the ``Statement`` protocol. The ``*_RESULT`` constants are the results PostgreSQL
reports for transaction control and a one-row insert (``rowcount`` is -1 where the server
reports none). The reply helpers narrow a ``Reply`` for an assertion and fail with the reply
itself when it is another kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from platina.drivers.interface import (
    Completed,
    DatabaseFault,
    Failed,
    Lost,
    Reply,
    StatementResult,
    UnreadableRows,
)


@dataclass(frozen=True, slots=True)
class SQL:
    """One statement: ``%s`` placeholders, ``%%`` for a literal ``%``."""

    sql: str
    params: tuple[object, ...] = ()


BEGIN: Final = SQL("BEGIN ISOLATION LEVEL SERIALIZABLE")
COMMIT: Final = SQL("COMMIT")
ROLLBACK: Final = SQL("ROLLBACK")
DIVIDE_BY_ZERO: Final = SQL("SELECT 1/0")
TERMINATE_OWN_BACKEND: Final = SQL("SELECT pg_terminate_backend(pg_backend_pid())")
BACKEND_PID: Final = SQL("SELECT pg_backend_pid()")

ADD_ONE: Final = SQL("SELECT %s::int + 1", (1,))
SELECT_ONE: Final = SQL("SELECT 1")

# psycopg prepares a query on its sixth execution on a connection (``prepare_threshold``, default
# 5). These round trips put that sixth execution of ``ADD_ONE`` after a failed statement in the
# same pipeline, where the server skips its Parse - each in its own round trip.
SIXTH_EXECUTION_AFTER_A_FAILURE: Final = (
    [BEGIN, DIVIDE_BY_ZERO],
    [ROLLBACK],
    [BEGIN, ADD_ONE, COMMIT],
    [BEGIN, ADD_ONE, COMMIT],
    [BEGIN, ADD_ONE, COMMIT],
    [BEGIN, ADD_ONE, COMMIT],
    [BEGIN, ADD_ONE, COMMIT],
    [BEGIN, DIVIDE_BY_ZERO, ADD_ONE, COMMIT],
    [ROLLBACK],
)

BEGIN_RESULT: Final = StatementResult("BEGIN", -1, ())
INSERT_RESULT: Final = StatementResult("INSERT 0 1", 1, ())
COMMIT_RESULT: Final = StatementResult("COMMIT", -1, ())
ROLLBACK_RESULT: Final = StatementResult("ROLLBACK", -1, ())


def insert_item(item_id: int, qty: object = 1) -> SQL:
    """``INSERT`` one row into ``items`` (``tests.support.database.create_items``)."""
    return SQL("INSERT INTO items (id, qty) VALUES (%s, %s)", (item_id, qty))


def insert_key(key: int) -> SQL:
    """``INSERT`` one row into ``keys`` (``tests.support.database.create_deferred_keys``)."""
    return SQL("INSERT INTO keys (id) VALUES (%s)", (key,))


def fault_of(reply: Reply) -> DatabaseFault:
    """The fault of a ``Failed`` or ``Lost`` reply."""
    assert isinstance(reply, Failed | Lost), f"expected a failure, got {reply!r}"
    return reply.fault


def unreadable_fault(reply: Reply, index: int) -> DatabaseFault:
    """The fault of result ``index`` whose rows could not be loaded."""
    rows = reply.results[index].rows
    assert isinstance(rows, UnreadableRows), f"expected UnreadableRows, got {rows!r}"
    return rows.fault


def statuses(reply: Reply) -> list[str]:
    """The command tags of the results that arrived, in order."""
    return [result.status for result in reply.results]


def first_value(reply: Reply) -> object:
    """The first column of the first row of the last result of a ``Completed`` reply."""
    assert isinstance(reply, Completed), f"expected Completed, got {reply!r}"
    rows = reply.results[-1].rows
    assert not isinstance(rows, UnreadableRows), f"unreadable rows: {rows!r}"
    return rows[0][0]


def commit_status(reply: Reply) -> str | None:
    """The status of a ``COMMIT`` result in ``reply`` ("COMMIT" or "ROLLBACK"), ``None`` when no
    result tells the transaction's outcome.
    """
    found = [r.status for r in reply.results if r.status in {"COMMIT", "ROLLBACK"}]
    return found[-1] if found else None
