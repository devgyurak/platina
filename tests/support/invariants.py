"""What a pipeline reply may claim about the commit, judged against facts read elsewhere.

A reply must never misreport a committed run (ADR-0012): ``violated_invariant`` compares the
outcome of a pipeline (its reply, or the exception it raised) with whether its row is committed,
read on a separate connection, and names the first invariant it breaks. It checks soundness, not
precision: it fails a reply the database contradicts, but accepts one that claims less than it
could (``Lost`` where ``Completed`` was possible, an exception when nothing was committed). The
exact replies are pinned by the other driver tests.

The scenarios put a ``SELECT gen_random_uuid()`` - whose result a failing ``uuid`` loader cannot
load - at a chosen position around the ``COMMIT`` of a transaction that inserts ``items`` row 2,
optionally followed by many statements, so that the loader's error surfaces in an ``execute()``
or at the block's exit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from platina.drivers.interface import Completed, Failed, Reply, Statement
from tests.support.database import fetch_plain
from tests.support.statements import BEGIN, COMMIT, SELECT_ONE, SQL, insert_item

type Position = Literal["only", "before-commit", "after-commit", "last"]

UUID: Final = SQL("SELECT gen_random_uuid()")


@dataclass(frozen=True, slots=True)
class Scenario:
    statements: tuple[Statement, ...]
    commit_at: int | None  # the COMMIT's index; None without a transaction


def uuid_scenario(position: Position, trailing: int) -> Scenario:
    """The uuid statement at ``position``, then ``trailing`` times ``SELECT 1``."""
    head: dict[Position, tuple[tuple[Statement, ...], int | None]] = {
        "only": ((UUID,), None),
        "before-commit": ((BEGIN, insert_item(2), UUID, COMMIT), 3),
        "after-commit": ((BEGIN, insert_item(2), COMMIT, UUID, SELECT_ONE), 2),
        "last": ((BEGIN, insert_item(2), COMMIT, SELECT_ONE, UUID), 2),
    }
    statements, commit_at = head[position]
    return Scenario(statements + (SELECT_ONE,) * trailing, commit_at)


def item_committed(dsn: str) -> bool:
    """Whether ``items`` row 2 is committed, read on a separate plain connection."""
    return fetch_plain(dsn, "SELECT id FROM items WHERE id = 2") != []


def violated_invariant(
    outcome: Reply | Exception, scenario: Scenario, *, committed: bool
) -> str | None:
    """The first invariant ``outcome`` breaks given ``committed``, or ``None``.

    1. An exception propagated, or ``Failed`` at or before the COMMIT => nothing committed.
    2. ``Completed`` => one result per statement, and the COMMIT's result says "COMMIT".
    3. A result with status "COMMIT" in the reply => committed.
    """
    commit_at = scenario.commit_at
    if isinstance(outcome, Exception):
        return f"raised {outcome!r}, yet committed" if committed else None
    failed_by_commit = isinstance(outcome, Failed) and commit_at is not None
    if failed_by_commit and committed and len(outcome.results) <= (commit_at or 0):
        return f"Failed at or before the COMMIT at {commit_at}, yet committed: {outcome!r}"
    if isinstance(outcome, Completed):
        if len(outcome.results) != len(scenario.statements):
            return f"Completed with {len(outcome.results)} results: {outcome!r}"
        if commit_at is not None and outcome.results[commit_at].status != "COMMIT":
            return f"Completed without the COMMIT status: {outcome!r}"
    if any(result.status == "COMMIT" for result in outcome.results) and not committed:
        return f"a COMMIT result, yet nothing committed: {outcome!r}"
    return None
