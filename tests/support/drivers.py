"""Both psycopg drivers behind one sync-looking facade, so each integration test is written once.

``open_drivers("sync")`` opens ``SyncPsycopgDriver`` as it is: it already is a ``SessionSource``.
``open_drivers("async")`` drives ``AsyncPsycopgDriver`` through one ``asyncio.Runner`` (one event
loop: psycopg's async objects are bound to theirs) and presents it as a ``SessionSource`` too.

Each async context manager (the driver, a session) is entered and left inside one task of its
own that the runner keeps alive in between (``_hosted``), so nothing task-bound inside the driver
(a cancel scope, a timeout) is entered in one task and left in another. The statements run in
tasks of their own, as a runner's would after acquiring a session. An exception raised in the
``with`` block of a session is thrown into that task, so the async context manager sees exactly
what the sync one sees.

After the drivers are closed, ``gc.collect()`` runs, so whatever the driver left unclosed (a
non-pooled connection, a socket, an asyncio transport or task) is finalised - and its
``ResourceWarning`` raised as an error (pytest ``filterwarnings = error``) - while the test that
left it is still the current one. A pooled connection never warns (psycopg skips the warning
when the connection belongs to a pool); a connection lent and not given back is caught by the
default pool of one instead: the next session would get a new backend, or none.
"""

from __future__ import annotations

import asyncio
import gc
import logging
from collections.abc import Iterator, Sequence
from contextlib import AbstractAsyncContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any, Final, Literal, LiteralString, Protocol

import psycopg
from psycopg.abc import AdaptContext, Buffer
from psycopg.adapt import AdaptersMap, Dumper, Loader

from platina.drivers.interface import (
    AsyncSession,
    AsyncSessionSource,
    Reply,
    Session,
    SessionSource,
    Statement,
)
from platina.drivers.psycopg import AsyncPsycopgDriver, SyncPsycopgDriver
from tests.support.database import fetch_plain, terminate_backend
from tests.support.statements import BACKEND_PID, first_value

type Variant = Literal["sync", "async"]


class Drivers(Protocol):
    """Opens a driver of the fixture's variant; it is closed when the test ends."""

    def open(
        self,
        conninfo: str,
        *,
        min_size: int = 1,
        max_size: int | None = None,
        adapters: AdaptersMap | None = None,
        timeout: float = 30.0,
    ) -> SessionSource: ...


@contextmanager
def open_drivers(variant: Variant) -> Iterator[Drivers]:
    """A ``Drivers`` of ``variant``; every driver it opened is closed on exit."""
    with ExitStack() as stack:
        if variant == "sync":
            yield _SyncDrivers(stack)
        else:
            runner = stack.enter_context(asyncio.Runner())
            yield _AsyncDrivers(runner, stack)
    gc.collect()


@dataclass(frozen=True, slots=True)
class _SyncDrivers:
    stack: ExitStack

    def open(
        self,
        conninfo: str,
        *,
        min_size: int = 1,
        max_size: int | None = None,
        adapters: AdaptersMap | None = None,
        timeout: float = 30.0,
    ) -> SessionSource:
        driver = SyncPsycopgDriver(
            conninfo, min_size=min_size, max_size=max_size, adapters=adapters, timeout=timeout
        )
        return self.stack.enter_context(driver)


@dataclass(frozen=True, slots=True)
class _AsyncDrivers:
    runner: asyncio.Runner
    stack: ExitStack

    def open(
        self,
        conninfo: str,
        *,
        min_size: int = 1,
        max_size: int | None = None,
        adapters: AdaptersMap | None = None,
        timeout: float = 30.0,
    ) -> SessionSource:
        driver = AsyncPsycopgDriver(
            conninfo, min_size=min_size, max_size=max_size, adapters=adapters, timeout=timeout
        )
        source: AsyncSessionSource = self.stack.enter_context(_hosted(self.runner, driver))
        return _AsyncSource(self.runner, source)


@dataclass(frozen=True, slots=True)
class _AsyncSource:
    runner: asyncio.Runner
    source: AsyncSessionSource

    @contextmanager
    def session(self) -> Iterator[Session]:
        with _hosted(self.runner, self.source.session()) as session:
            yield _AsyncSessionFacade(self.runner, session)


@dataclass(frozen=True, slots=True)
class _AsyncSessionFacade:
    runner: asyncio.Runner
    session: AsyncSession

    def pipeline(self, statements: Sequence[Statement], /) -> Reply:
        return self.runner.run(self.session.pipeline(statements))

    def copy_in(self, statement: Statement, rows: Sequence[Sequence[object]], /) -> Reply:
        return self.runner.run(self.session.copy_in(statement, rows))


@dataclass(frozen=True, slots=True)
class _Host[T]:
    value: T
    task: asyncio.Task[None]
    leaving: asyncio.Future[BaseException | None]

    async def leave(self, error: BaseException | None) -> None:
        """Let the hosting task leave the context manager (raising ``error`` inside it)."""
        self.leaving.set_result(error)
        await self.task


async def _hold[T](
    manager: AbstractAsyncContextManager[T],
    entered: asyncio.Future[T],
    leaving: asyncio.Future[BaseException | None],
) -> None:
    async with manager as value:
        entered.set_result(value)
        error = await leaving
        if error is not None:
            raise error


async def _enter[T](manager: AbstractAsyncContextManager[T]) -> _Host[T]:
    loop = asyncio.get_running_loop()
    entered: asyncio.Future[T] = loop.create_future()
    leaving: asyncio.Future[BaseException | None] = loop.create_future()
    task = asyncio.create_task(_hold(manager, entered, leaving))
    await asyncio.wait([entered, task], return_when=asyncio.FIRST_COMPLETED)
    if not entered.done():
        task.result()  # raises what ``__aenter__`` raised
    return _Host(entered.result(), task, leaving)


@contextmanager
def _hosted[T](runner: asyncio.Runner, manager: AbstractAsyncContextManager[T]) -> Iterator[T]:
    """Enter ``manager`` in a task of its own; leave it there, with the block's exception."""
    host = runner.run(_enter(manager))
    try:
        yield host.value
    except BaseException as error:
        # Raises ``error`` again unless the async context manager suppressed it; returning
        # here suppresses it in turn.
        runner.run(host.leave(error))
    else:
        runner.run(host.leave(None))


class Interrupted(Exception):
    """An exception a test raises inside a session block."""


def fail_inside_session(
    driver: SessionSource, statements: Sequence[Statement], error: Exception
) -> None:
    """Open a session, run ``statements`` in one pipeline, then raise ``error`` in the block."""
    with driver.session() as session:
        session.pipeline(statements)
        raise error


def run_in_session(driver: SessionSource, statements: Sequence[Statement]) -> Reply:
    """Open a session, run ``statements`` in one pipeline, leave the session."""
    with driver.session() as session:
        return session.pipeline(statements)


@dataclass(frozen=True, slots=True)
class _BareStringParams:
    """A statement whose parameters are a ``str``: the type allows it (``str`` is a
    ``Sequence``), psycopg rejects it in ``execute()`` before sending - a programming error."""

    sql: str
    params: str


def with_string_params(sql: str, params: str) -> Statement:
    return _BareStringParams(sql, params)


def raised_by_pipeline(driver: SessionSource, statements: Sequence[Statement]) -> BaseException:
    """The exception ``run_in_session`` propagates (the test fails if there is none)."""
    try:
        run_in_session(driver, statements)
    except Exception as e:
        return e
    raise AssertionError("pipeline() returned a reply instead of propagating the exception")


def run_round_trips(session: Session, *round_trips: Sequence[Statement]) -> list[Reply]:
    """Run each round trip as one pipeline on ``session``; their replies in order."""
    return [session.pipeline(statements) for statements in round_trips]


def rows_seen_while_held(
    driver: SessionSource, dsn: str, query: LiteralString, *round_trips: Sequence[Statement]
) -> list[tuple[Any, ...]]:
    """Run each round trip as one pipeline in a session and, before leaving it, read ``query``
    on a separate plain connection: what is committed while the session still holds its
    connection (and whatever transaction is open on it), so the release's ``ROLLBACK`` cannot
    account for the result.
    """
    with driver.session() as session:
        for statements in round_trips:
            session.pipeline(statements)
        return fetch_plain(dsn, query)


def backend_pid(session: Session) -> int:
    """The PostgreSQL backend process id of the session's connection."""
    pid = first_value(session.pipeline([BACKEND_PID]))
    assert isinstance(pid, int)
    return pid


def leave_after_the_backend_died(
    driver: SessionSource, dsn: str, statements: Sequence[Statement]
) -> int:
    """Run ``statements`` in a session, terminate its backend from a separate connection, then
    leave the session - its release finds a dead connection. Returns the terminated pid.
    """
    with driver.session() as session:
        session.pipeline(statements)
        pid = backend_pid(session)
        terminate_backend(dsn, pid)
    return pid


def session_pid(driver: SessionSource) -> int:
    """The backend pid of the connection a new session gets."""
    with driver.session() as session:
        return backend_pid(session)


def pool_warnings(records: Sequence[logging.LogRecord]) -> list[str]:
    """The WARNING (or worse) messages of psycopg_pool's logger among captured ``records``.

    psycopg_pool warns "rolling back returned connection" / "closing returned connection" when
    it has to clean up a connection that came back in a transaction or mid round trip: the
    driver's release must have done that already.
    """
    return [
        record.getMessage()
        for record in records
        if record.name == "psycopg.pool" and record.levelno >= logging.WARNING
    ]


class _UpperTextLoader(Loader):
    """Loads ``text`` (text format, UTF-8) upper-cased: proof that a per-driver loader was used."""

    def load(self, data: Buffer) -> str:
        return bytes(data).decode().upper()


class _FailingIntLoader(Loader):
    """Loads ``int4`` by raising ``ValueError``: a caller's loader that is not psycopg's."""

    def load(self, data: Buffer) -> int:
        raise ValueError("failing int4 loader")


def failing_int_adapters() -> AdaptersMap:
    """A child of ``psycopg.adapters`` whose ``int4`` loader (text format) raises ``ValueError``."""
    adapters = child_adapters()
    adapters.register_loader("int4", _FailingIntLoader)
    return adapters


def child_adapters() -> AdaptersMap:
    """A fresh child of ``psycopg.adapters``, as a caller would pass it."""
    return AdaptersMap(psycopg.adapters)


def register_upper_text(adapters: AdaptersMap) -> None:
    """Register the upper-casing ``text`` loader (text format) on ``adapters``."""
    adapters.register_loader("text", _UpperTextLoader)


def upper_text_adapters() -> AdaptersMap:
    """A child of ``psycopg.adapters`` whose ``text`` loader upper-cases (text format)."""
    adapters = child_adapters()
    register_upper_text(adapters)
    return adapters


class _RaisingLoader(Loader):
    """A loader whose constructor raises: psycopg fails while setting up the result itself."""

    def __init__(self, oid: int, context: AdaptContext | None = None) -> None:
        raise ValueError("loader constructor failed")

    def load(self, data: Buffer) -> object:
        return bytes(data)


def raising_uuid_loader_adapters() -> AdaptersMap:
    """A child of ``psycopg.adapters`` whose ``uuid`` loader cannot even be built."""
    adapters = child_adapters()
    adapters.register_loader("uuid", _RaisingLoader)
    return adapters


class _InitValueError(Loader):
    def __init__(self, oid: int, context: AdaptContext | None = None) -> None:
        raise ValueError("loader constructor failed")

    def load(self, data: Buffer) -> object:
        return bytes(data)


class _InitDataError(Loader):
    def __init__(self, oid: int, context: AdaptContext | None = None) -> None:
        raise psycopg.DataError("loader constructor failed")

    def load(self, data: Buffer) -> object:
        return bytes(data)


class _LoadValueError(Loader):
    def load(self, data: Buffer) -> object:
        raise ValueError("loader failed")


class _LoadDataError(Loader):
    def load(self, data: Buffer) -> object:
        raise psycopg.DataError("loader failed")


type LoaderFailure = Literal["init", "load"]
type LoaderError = Literal["ValueError", "DataError"]

_FAILING_LOADERS: Final[dict[tuple[LoaderFailure, LoaderError], type[Loader]]] = {
    ("init", "ValueError"): _InitValueError,
    ("init", "DataError"): _InitDataError,
    ("load", "ValueError"): _LoadValueError,
    ("load", "DataError"): _LoadDataError,
}


def failing_uuid_adapters(where: LoaderFailure, error: LoaderError) -> AdaptersMap:
    """A child of ``psycopg.adapters`` whose ``uuid`` loader raises ``error`` in its constructor
    (``"init"``: psycopg fails while setting up the result) or in ``load()``.
    """
    adapters = child_adapters()
    adapters.register_loader("uuid", _FAILING_LOADERS[where, error])
    return adapters


class Unsendable:
    """A value whose dumper (``unsendable_dumper_adapters``) raises ``ValueError``."""


class _UnsendableDumper(Dumper):
    def dump(self, obj: object) -> Buffer | None:
        raise ValueError("dumper failed")


def unsendable_dumper_adapters() -> AdaptersMap:
    """A child of ``psycopg.adapters`` with a dumper for ``Unsendable`` that raises ``ValueError``."""
    adapters = child_adapters()
    adapters.register_dumper(Unsendable, _UnsendableDumper)
    return adapters


def run_capturing(driver: SessionSource, statements: Sequence[Statement]) -> Reply | Exception:
    """``run_in_session``, with an exception the pipeline raised returned instead."""
    try:
        return run_in_session(driver, statements)
    except Exception as error:
        return error


def pipeline_capturing(session: Session, statements: Sequence[Statement]) -> Reply | Exception:
    """``session.pipeline(statements)``, with an exception it raised returned instead."""
    try:
        return session.pipeline(statements)
    except Exception as error:
        return error
