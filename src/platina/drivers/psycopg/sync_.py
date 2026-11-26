"""Sync psycopg driver: a pool of autocommit connections, one pipeline per round trip, COPY.

Hand-written mirror of ``async_.py`` until #19 generates it from there; change both together.
ADR-0012.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from types import TracebackType
from typing import Self

import psycopg
from psycopg import Connection, Cursor
from psycopg.adapt import AdaptersMap
from psycopg.rows import TupleRow
from psycopg_pool import ConnectionPool

from platina.drivers.interface import (
    Completed,
    Lost,
    Reply,
    Session,
    SessionUnavailable,
    Statement,
    StatementResult,
    UnreadableRows,
    settle,
)
from platina.drivers.psycopg._common import (
    IN_TRANSACTION,
    Abandon,
    Propagate,
    any_fault_of,
    connection_kwargs,
    copy_query_of,
    fault_of,
    query_of,
    unclean,
    verdict,
)


class SyncPsycopgDriver:
    """A pool of autocommit connections; ``session()`` lends one out.

    Use as ``with SyncPsycopgDriver(dsn) as driver:``, which opens the pool (waiting for
    ``min_size`` connections, at most ``timeout`` seconds) and closes it on exit. ``timeout`` also
    bounds each ``session()``'s wait for a connection; ``max_size`` defaults to ``min_size``. ``adapters`` is copied when the driver is
    built: what is registered on it later is not seen.
    """

    def __init__(
        self,
        conninfo: str,
        *,
        min_size: int = 1,
        max_size: int | None = None,
        adapters: AdaptersMap | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._timeout = timeout
        self._pool: ConnectionPool[Connection[TupleRow]] = ConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            kwargs=connection_kwargs(adapters),
            timeout=timeout,
            open=False,
        )

    def __enter__(self) -> Self:
        try:
            self._pool.open(wait=True, timeout=self._timeout)
        except BaseException as e:
            self._pool.close()  # an interrupted open would leave the pool connecting
            if isinstance(e, psycopg.Error):
                raise SessionUnavailable(fault_of(e)) from e
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._pool.close()

    @contextmanager
    def session(self) -> Generator[Session]:
        """Lend a connection for one run; it goes back clean on every path (ADR-0012)."""
        try:
            conn = self._pool.getconn()
        except psycopg.Error as e:
            raise SessionUnavailable(fault_of(e)) from e
        try:
            yield _SyncPsycopgSession(conn)
        finally:
            _release(self._pool, conn)


class _SyncPsycopgSession:
    def __init__(self, conn: Connection[TupleRow]) -> None:
        self._conn = conn

    def pipeline(self, statements: Sequence[Statement], /) -> Reply:
        conn = self._conn
        cursors: list[Cursor[TupleRow]] = []
        in_block: Exception | None = None
        at_exit: Exception | None = None
        try:
            with conn.pipeline():
                for statement in statements:
                    cursor = conn.cursor()
                    cursors.append(cursor)
                    try:
                        cursor.execute(query_of(statement), statement.params)
                    except Exception as e:
                        # Stop sending and let the block close normally: an error escaping it
                        # would make psycopg drop a server error of an earlier statement. Not
                        # only psycopg's: a caller's loader raising while results arrive too.
                        in_block = e
                        break
        except Exception as e:  # psycopg's, or a caller's loader raising at the exit
            at_exit = e
        received = _received(cursors)
        stopped = cursors[len(received)] if len(received) < len(cursors) else None
        match verdict(
            unclean=unclean(conn),
            statements=len(statements),
            sent=len(cursors),
            received=received,
            stopped_ran=stopped is not None and stopped.pgresult is not None,
            in_block=in_block,
            at_exit=at_exit,
        ):
            case Propagate(error):
                raise error  # a programming error (ADR-0012 decision 3)
            case Abandon(fault):
                conn.close()  # nothing more can be known or run on it
                return Lost(received, fault)
            case reply:
                return reply

    def copy_in(self, statement: Statement, rows: Sequence[Sequence[object]], /) -> Reply:
        conn = self._conn
        try:
            cursor = conn.cursor()
            with cursor.copy(copy_query_of(statement), statement.params or None) as copy:
                for row in rows:
                    copy.write_row(row)
        except psycopg.Error as e:
            if unclean(conn):
                conn.close()
                return Lost((), fault_of(e))
            return settle((), fault_of(e), lost=False)
        return Completed((StatementResult(cursor.statusmessage or "", cursor.rowcount, ()),))


def _received(cursors: Sequence[Cursor[TupleRow]]) -> tuple[StatementResult, ...]:
    """The results that arrived: the cursors up to the first one without a complete result.

    psycopg stores no result on a statement that failed or was not run, nor on the statements
    after it; a cursor whose result could not be set up (a caller's loader raising in its
    constructor) holds a ``pgresult`` without a command tag - its statement ran, and ``verdict``
    reports that as ``Lost``. After a lost connection results that the server sent may be
    missing too (ADR-0012). Rows that cannot be loaded later are reported on their statement,
    which keeps its status.
    """
    results: list[StatementResult] = []
    for cursor in cursors:
        # No result, or one whose setup failed half way (no command tag: F3's loader case, always
        # under Lost): neither proves anything, so the received prefix ends there. psycopg gives
        # no command tag without a result either; the first test is defensive.
        if cursor.pgresult is None or not cursor.statusmessage:
            break
        rows = _rows(cursor)
        results.append(StatementResult(cursor.statusmessage, cursor.rowcount, rows))
    return tuple(results)


def _rows(cursor: Cursor[TupleRow]) -> tuple[tuple[object, ...], ...] | UnreadableRows:
    if cursor.description is None:
        return ()
    try:
        return tuple(cursor.fetchall())
    except Exception as e:  # a loader runs after the statement ran: report, never raise
        return UnreadableRows(any_fault_of(e))


def _release(pool: ConnectionPool[Connection[TupleRow]], conn: Connection[TupleRow]) -> None:
    """Return ``conn`` idle, or closed so that the pool replaces it - on every path.

    Idle: returned as is. In a transaction (open or aborted): rolled back, closed if that fails or
    is interrupted. Anything else (broken, a round trip still active, unknown): closed without a
    ``ROLLBACK``, which could block on a connection in that state. Never ``pool.connection()``:
    its clean exit commits an open transaction. Shielding this from cancellation is #19's.
    """
    try:
        if unclean(conn):
            conn.close()
        elif conn.info.transaction_status in IN_TRANSACTION:
            try:
                conn.rollback()
            except psycopg.Error:
                conn.close()
            except BaseException:
                conn.close()
                raise
    finally:
        pool.putconn(conn)
