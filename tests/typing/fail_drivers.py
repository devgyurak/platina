"""Mixing the sync and async driver contracts, a statement whose parameters can be missing, or
rebinding a ``SessionUnavailable``'s fault is a type error under pyright and mypy.

These pin the internal driver contract of ADR-0012 (what the runners program against), not
public API.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from platina.drivers.interface import (
    AsyncSessionSource,
    DatabaseFault,
    SessionSource,
    SessionUnavailable,
    Statement,
)
from platina.drivers.psycopg import AsyncPsycopgDriver, SyncPsycopgDriver


@dataclass(frozen=True, slots=True)
class OptionalParams:
    sql: str
    params: Sequence[object] | None = None


fault = DatabaseFault(None, "pool timeout", None, None, None, Exception("pool timeout"))
unavailable = SessionUnavailable(fault)

# fmt: off
sync_source: SessionSource = AsyncPsycopgDriver("")  # expect-error[reportAssignmentType, assignment]: an async driver is no sync SessionSource
async_source: AsyncSessionSource = SyncPsycopgDriver("")  # expect-error[reportAssignmentType, assignment]: a sync driver is no AsyncSessionSource
statement: Statement = OptionalParams("SELECT 1")  # expect-error[reportAssignmentType, assignment]: params is always a sequence, never None
unavailable.fault = fault  # expect-error[reportAttributeAccessIssue, misc]: the fault is Final
# fmt: on
