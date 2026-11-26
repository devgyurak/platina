"""Helpers shared by the sync and async psycopg variants (ADR-0012)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, LiteralString

import psycopg
from psycopg import errors, pq
from psycopg.adapt import AdaptersMap

from platina.drivers.interface import (
    Completed,
    DatabaseFault,
    Failed,
    Reply,
    Statement,
    StatementResult,
)

IN_TRANSACTION = frozenset({pq.TransactionStatus.INTRANS, pq.TransactionStatus.INERROR})
_SETTLED = IN_TRANSACTION | {pq.TransactionStatus.IDLE}


def unclean(conn: psycopg.Connection[Any] | psycopg.AsyncConnection[Any]) -> bool:
    """Whether ``conn`` cannot run another statement: broken, closed, a round trip still
    active, pipeline mode still on, or a state libpq does not know.

    Such a connection is reported as ``Lost`` and closed, so that its session fails fast and the
    pool replaces it: what ran on it is no longer knowable from the client.
    """
    return (
        conn.broken
        or conn.closed
        or conn.info.transaction_status not in _SETTLED
        or conn.pgconn.pipeline_status != pq.PipelineStatus.OFF
    )


def unclean_fault() -> DatabaseFault:
    """The fault of a pipeline that ended unclean without a psycopg error of its own."""
    error = psycopg.OperationalError("the connection was left in an unknown state")
    return fault_of(error)


def query_of(statement: Statement) -> LiteralString:
    """The statement's text as psycopg's query type.

    psycopg types queries as ``LiteralString`` to keep user input out of SQL text. Compiled SQL is
    built by ``platina.sql`` from the registry, never from values (those are parameters), so
    waiving that one check states a fact rather than hides one. It is the only checker waiver in
    ``src``.
    """
    # mypy reads LiteralString as str; pyright alone sees the gap, and only this rule is waived.
    return statement.sql  # pyright: ignore[reportReturnType]


def copy_query_of(statement: Statement) -> LiteralString:
    """The text of a COPY statement, with ``%%`` turned into ``%`` when there are no parameters.

    psycopg converts placeholders and ``%%`` in ``execute`` always (the parameters are always
    passed, ADR-0012), but in ``copy`` only when there are parameters. A COPY has none, so the
    driver applies the same conversion to keep one escaping rule for every compiled statement.
    """
    query = query_of(statement)
    return query if statement.params else query.replace("%%", "%")


def first_error(in_block: Exception | None, at_exit: Exception | None) -> Exception | None:
    """The error that belongs to the first failed statement of a pipeline.

    ``in_block`` was raised by an ``execute()`` inside the block, ``at_exit`` when the block
    closed. An ``execute()`` raises either its own client-side error (a value it cannot adapt) or
    a server error of an earlier statement that arrived meanwhile. In the first case a server
    error of an earlier statement can still arrive at exit, and it wins; in the second the exit
    only reports ``PipelineAborted`` for the statements skipped after it, which is no error of
    its own. A ``PipelineAborted`` without an in-block error is kept: it is the only report that
    statements were skipped, and a reply must never call skipped statements completed.
    """
    if at_exit is not None and (
        in_block is None or not isinstance(at_exit, errors.PipelineAborted)
    ):
        return at_exit
    return in_block


def fault_of(error: psycopg.Error) -> DatabaseFault:
    diag = error.diag
    return DatabaseFault(
        sqlstate=error.sqlstate,
        message=diag.message_primary or str(error),
        constraint=diag.constraint_name,
        table=diag.table_name,
        schema=diag.schema_name,
        cause=error.with_traceback(
            None
        ),  # the traceback would keep the connection and cursors alive
    )


def any_fault_of(error: Exception) -> DatabaseFault:
    """The fault of any exception: psycopg's with its diagnostics, others without a SQLSTATE.

    Used where an exception is reported rather than raised although it may not be psycopg's: a
    loader from the caller's adapters map raising ``ValueError`` after its statement ran.
    """
    if isinstance(error, psycopg.Error):
        return fault_of(error)
    return DatabaseFault(
        sqlstate=None,
        message=str(error),
        constraint=None,
        table=None,
        schema=None,
        cause=error.with_traceback(None),
    )


def connection_kwargs(adapters: AdaptersMap | None) -> dict[str, Any]:
    """Connection arguments of every pooled connection.

    ``autocommit=True``: the engine sends its own ``BEGIN ISOLATION LEVEL ...`` and ``COMMIT``
    inside its pipelines; without autocommit psycopg would add a ``BEGIN`` and a round trip of its
    own. ``context``: one adapters map per pool, a child of the caller's map (or of psycopg's
    global one), so nothing is ever registered globally. Each connection copies it when it
    connects, so it is complete before the pool opens and never changed afterwards.
    ``prepare_threshold=None``: psycopg would prepare a query on its sixth execution, and when that
    execution sits after a failed statement in the same pipeline the server skips the ``Parse``
    while psycopg records the statement as prepared - every later use of it on that pooled
    connection then fails with ``26000`` (#18 review). Without it the wire carries exactly the
    engine's statements.
    """
    return {
        "autocommit": True,
        "prepare_threshold": None,
        "context": AdaptersMap(adapters if adapters is not None else psycopg.adapters),
    }


@dataclass(frozen=True, slots=True)
class Abandon:
    """Close the connection and reply ``Lost`` with ``fault``."""

    fault: DatabaseFault


@dataclass(frozen=True, slots=True)
class Propagate:
    """Raise ``error``: a programming error, raised before its statement was sent."""

    error: Exception


def verdict(
    *,
    unclean: bool,
    statements: int,
    sent: int,
    received: tuple[StatementResult, ...],
    stopped_ran: bool,
    in_block: Exception | None,
    at_exit: Exception | None,
) -> Reply | Abandon | Propagate:
    """What one pipeline round trip reports (ADR-0012 decision 3) - one rule for every path.

    A pure function of what the pipeline observed, so every branch is pinned by a table test.
    ``unclean`` is ``unclean(conn)`` after the block. ``sent`` cursors were created (the last one may have raised before sending); ``received`` is
    the prefix with a result; ``stopped_ran`` says the cursor the prefix stops at has a ``pgresult``
    after all - its statement ran, and setting up its result failed (a caller's loader raising in
    its constructor, a psycopg error or not). ``in_block`` was raised by an ``execute()``,
    ``at_exit`` when the block closed; either may be any exception.

    - Lost, connection closed: the connection is unclean, the stopping statement ran, or the
      block's exit raised something that is not psycopg's - psycopg's result queue may then be out
      of step with the statements even on a connection that looks clean.
    - A non-psycopg error raised by an ``execute()`` (a dumper, invalid parameters): propagated
      when it has a dumper error's shape - nothing else failed, every earlier statement has its
      result, only the one being sent lacks it; ``Failed`` at the earlier position when the exit
      reported a server error (that error belongs to the first failed statement); ``Lost``
      otherwise.
    - Otherwise psycopg errors only: ``Completed`` when every statement has a result, ``Failed``
      at the first missing result with the first error (``first_error``), ``Lost`` when results
      are missing without an error.
    """
    first = first_error(in_block, at_exit)
    if unclean or stopped_ran or not _is_psycopg(at_exit):
        return Abandon(unclean_fault() if first is None else any_fault_of(first))
    if in_block is not None and not isinstance(in_block, psycopg.Error):
        if at_exit is None and len(received) == sent - 1:
            return Propagate(in_block)
        if isinstance(at_exit, psycopg.Error) and at_exit.sqlstate is not None:
            return Failed(received, fault_of(at_exit))
        return Abandon(any_fault_of(in_block))
    if first is None:
        return Completed(received) if len(received) == statements else Abandon(unclean_fault())
    return Failed(received, any_fault_of(first))


def _is_psycopg(error: Exception | None) -> bool:
    """``None`` or a psycopg error: anything else came from code psycopg called (a loader, a
    dumper) or from invalid arguments."""
    return error is None or isinstance(error, psycopg.Error)
