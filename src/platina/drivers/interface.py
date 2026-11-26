"""The driver contract the runners program against (design section 10.2, ADR-0012).

Capability-split Protocols, the statement shape a driver accepts and the replies it returns.
Nothing here imports psycopg (guard A102 allows it only in ``platina.drivers.psycopg``), so the
contract and its pure helpers are importable, and unit-tested, without libpq.

A driver runs statements and reports what happened as data; it classifies nothing. Retries,
``AlreadyClaimed`` and an unknown commit outcome are the engine's decisions (#17), made from the
position of the first failed statement and from whether ``COMMIT``'s result arrived (ADR-0008).

Database and driver errors become replies, and so does any exception raised while results are
handled (a caller's loader), since its statement may already have run. A programming error raised
before its statement is sent - parameters that are not a sequence, a COPY row that is not one, a
dumper raising ``ValueError`` - propagates as it is, unless the server reported an earlier
statement's error in the same round trip (then the reply is ``Failed`` there). Cancellation
always propagates. The session's release still returns the connection clean.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from typing import Final, Protocol


class Statement(Protocol):
    """One SQL statement and its parameters, as the compiler produces it.

    ``sql`` uses ``%s`` placeholders, and a literal ``%`` is written ``%%`` - always, because the
    parameters are always passed (an empty sequence too). A COPY statement has no parameters.
    A statement is never empty or only a comment: it has no command tag, and a result without one
    is not counted as received.
    """

    @property
    def sql(self) -> str: ...

    @property
    def params(self) -> Sequence[object]: ...


@dataclass(frozen=True, slots=True)
class StatementResult:
    """What one statement returned: its command tag, row count and rows.

    ``status`` is PostgreSQL's command tag (``"INSERT 0 1"``, ``"COMMIT"``, ``"COPY 5"``). Read it,
    not only the position: ``COMMIT`` in an aborted transaction answers ``"ROLLBACK"`` without an
    error. ``rows`` is empty for a statement without a result set, and ``UnreadableRows`` when the
    statement ran but a value could not be loaded into Python (a ``'infinity'`` date, a loader
    that raises): the status, and so the commit outcome, stays known. ``rowcount`` is ``-1`` where
    PostgreSQL reports none.
    """

    status: str
    rowcount: int
    rows: tuple[tuple[object, ...], ...] | UnreadableRows


@dataclass(frozen=True, slots=True)
class DatabaseFault:
    """A driver error as data: what the server (or the client library) reported.

    ``sqlstate`` is ``None`` for errors without one: a lost connection inside a pipeline, a value
    the driver cannot adapt, a pool timeout. Never read ``None`` as "connection lost"; that is the
    ``Lost`` reply. ``constraint``, ``table`` and ``schema`` come from the server's diagnostics.
    ``cause`` is the driver's exception; ``platina.drivers.errors.database_error`` chains it as the
    ``__cause__`` of the public error.
    """

    sqlstate: str | None
    message: str
    constraint: str | None
    table: str | None
    schema: str | None
    cause: Exception


@dataclass(frozen=True, slots=True)
class UnreadableRows:
    """The statement ran, but its rows could not be loaded; ``fault`` says why."""

    fault: DatabaseFault


@dataclass(frozen=True, slots=True)
class Completed:
    """Every statement ran; one result per statement, in order."""

    results: tuple[StatementResult, ...]


@dataclass(frozen=True, slots=True)
class Failed:
    """Statement ``at`` failed; the statements before it ran, the ones after it did not.

    ``results`` holds the results of statements ``0 .. at - 1``. The connection is usable. After a
    server error the transaction is aborted (a later ``COMMIT`` answers ``"ROLLBACK"``); after a
    client-side error in a pipeline (``sqlstate`` ``None``: a value that cannot be adapted) it is
    still open and a later ``COMMIT`` would commit the statements before ``at`` - roll it back. A
    client-side error in a COPY aborts it.
    """

    results: tuple[StatementResult, ...]
    fault: DatabaseFault

    @property
    def at(self) -> int:
        """The position of the failed statement: the number of statements that ran before it."""
        return len(self.results)


@dataclass(frozen=True, slots=True)
class Lost:
    """The connection was lost, or left in a state from which nothing more is knowable (a round
    trip still active, pipeline mode still on); it is closed. A present result proves its
    statement ran; a missing one proves nothing - the server may have run, and committed,
    statements whose results never arrived. The session is unusable afterwards: every later call
    is ``Lost`` too, and a new ``session()`` gets a fresh connection.
    """

    results: tuple[StatementResult, ...]
    fault: DatabaseFault


type Reply = Completed | Failed | Lost


def settle(
    received: tuple[StatementResult, ...], fault: DatabaseFault | None, *, lost: bool
) -> Reply:
    """Build the reply from the results that arrived (a prefix), the fault and the lost flag.

    ``lost`` is read only together with a fault: a lost connection is always reported by an
    exception.
    """
    if fault is None:
        return Completed(received)
    if lost:
        return Lost(received, fault)
    return Failed(received, fault)


class SessionUnavailable(Exception):
    """No session could be opened (pool closed or timed out, connection refused).

    Raised by ``session()``; ``pipeline()`` and ``copy_in()`` report errors as replies instead.
    """

    def __init__(self, fault: DatabaseFault) -> None:
        super().__init__(fault.message)
        self.fault: Final = fault

    def __reduce__(self) -> tuple[type[SessionUnavailable], tuple[DatabaseFault]]:
        # The default would call SessionUnavailable(message) and fail; copy and pickle need this.
        return (SessionUnavailable, (self.fault,))


class PipelineExecutor(Protocol):
    def pipeline(self, statements: Sequence[Statement], /) -> Reply:
        """Run the statements in one pipeline round trip."""
        ...


class CopyExecutor(Protocol):
    def copy_in(self, statement: Statement, rows: Sequence[Sequence[object]], /) -> Reply:
        """Run ``COPY ... FROM STDIN`` outside any pipeline; one result (``"COPY n"``) on success.

        ``rows`` is a sequence, not an iterator: a retried attempt sends it again.
        """
        ...


class Session(PipelineExecutor, CopyExecutor, Protocol):
    """One connection, held for one run (every attempt of it, until a ``Lost`` reply)."""


class SessionSource(Protocol):
    def session(self) -> AbstractContextManager[Session]:
        """Acquire a connection; on exit it goes back clean (rolled back) or is discarded."""
        ...


class AsyncPipelineExecutor(Protocol):
    async def pipeline(self, statements: Sequence[Statement], /) -> Reply:
        """Run the statements in one pipeline round trip."""
        ...


class AsyncCopyExecutor(Protocol):
    async def copy_in(self, statement: Statement, rows: Sequence[Sequence[object]], /) -> Reply:
        """Run ``COPY ... FROM STDIN`` outside any pipeline; one result (``"COPY n"``) on success."""
        ...


class AsyncSession(AsyncPipelineExecutor, AsyncCopyExecutor, Protocol):
    """One connection, held for one run (every attempt of it, until a ``Lost`` reply)."""


class AsyncSessionSource(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]:
        """Acquire a connection; on exit it goes back clean (rolled back) or is discarded."""
        ...
