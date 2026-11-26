"""The psycopg drivers and a frozen dataclass satisfy the driver protocols, ``Reply`` is a closed
union and ``StatementResult.rows`` narrows, under pyright and mypy.

These pin the internal driver contract of ADR-0012 (what the runners program against), not
public API.
"""

from dataclasses import dataclass
from typing import assert_never, assert_type

from platina.drivers.interface import (
    AsyncSessionSource,
    Completed,
    Failed,
    Lost,
    Reply,
    SessionSource,
    Statement,
    StatementResult,
    UnreadableRows,
)
from platina.drivers.psycopg import AsyncPsycopgDriver, SyncPsycopgDriver


@dataclass(frozen=True, slots=True)
class CompiledStatement:
    sql: str
    params: tuple[object, ...] = ()


sync_source: SessionSource = SyncPsycopgDriver("")
async_source: AsyncSessionSource = AsyncPsycopgDriver("")
statement: Statement = CompiledStatement("SELECT %s::int", (5,))


def outcome(reply: Reply) -> str:
    """Exhaustive over the three replies: a fourth would reach ``assert_never``."""
    match reply:
        case Completed():
            return "completed"
        case Failed():
            assert_type(reply.at, int)
            return "failed"
        case Lost():
            return "lost"
        case _:
            assert_never(reply)


def rows_of(result: StatementResult) -> tuple[tuple[object, ...], ...]:
    rows = result.rows
    if isinstance(rows, UnreadableRows):
        assert_type(rows, UnreadableRows)
        return ()
    assert_type(rows, tuple[tuple[object, ...], ...])
    return rows
