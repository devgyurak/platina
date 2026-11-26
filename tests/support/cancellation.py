"""Cancelling async driver work while it is under way, without timing.

``cancel_driver_open`` cancels ``AsyncPsycopgDriver.__aenter__`` while the pool's first
connection attempt is in flight: the "server" is a local socket that accepts and never answers,
so its ``accept()`` returning is the observable proof that the pool has started connecting.

``cancel_pipeline_waiting_on_lock`` makes the server block deterministically: a plain connection
holds ``pg_advisory_lock(1)`` and the session's pipeline asks for the same lock. The helper
waits until ``pg_locks`` shows the session's backend waiting - polling over a second async
connection, each poll an await on the event loop - and only then cancels the task. Every wait is
bounded (``asyncio.timeout``), so a driver that swallows the cancellation or hangs while
releasing makes the scenario report a ``TimeoutError`` instead of hanging the test run.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from typing import Final

import psycopg
from psycopg.rows import TupleRow

from platina.drivers.interface import AsyncSession, Reply, SessionUnavailable
from platina.drivers.psycopg import AsyncPsycopgDriver
from tests.support.statements import BACKEND_PID, SQL, first_value

_BOUND: Final = 10.0  # seconds; a bound against hanging, never a timing assertion
_TAKE_LOCK: Final = SQL("SELECT pg_advisory_lock(1)")
_WAITING: Final = (
    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted AND pid = %s"
)


@dataclass(frozen=True, slots=True)
class CancelledPipeline:
    """What happened: the cancelled task's ``outcome`` (its exception, or the reply it returned
    instead), the backend pids of the cancelled session and of the next session, and the reply
    to ``SELECT 1`` in the next session.
    """

    outcome: BaseException | Reply
    cancelled_pid: int
    next_pid: int
    next_reply: Reply


def cancel_pipeline_waiting_on_lock(dsn: str) -> CancelledPipeline:
    """Cancel a pipeline blocked on an advisory lock; then open the next session."""
    with psycopg.connect(dsn, autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(1)")
        return asyncio.run(_scenario(dsn))


async def _scenario(dsn: str) -> CancelledPipeline:
    async with (
        AsyncPsycopgDriver(dsn, max_size=1, timeout=_BOUND) as driver,
        await psycopg.AsyncConnection.connect(dsn, autocommit=True) as observer,
    ):
        started: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(_take_lock(driver, started))
        async with asyncio.timeout(_BOUND):
            cancelled_pid = await started
            await _until_waiting(observer, cancelled_pid)
        task.cancel()
        outcome = await _outcome(task)
        async with asyncio.timeout(_BOUND), driver.session() as session:
            next_pid = await _pid(session)
            next_reply = await session.pipeline([SQL("SELECT 1")])
    return CancelledPipeline(outcome, cancelled_pid, next_pid, next_reply)


async def _take_lock(driver: AsyncPsycopgDriver, started: asyncio.Future[int]) -> Reply:
    async with driver.session() as session:
        started.set_result(await _pid(session))
        return await session.pipeline([_TAKE_LOCK])


async def _until_waiting(observer: psycopg.AsyncConnection[TupleRow], pid: int) -> None:
    while True:
        cursor = await observer.execute(_WAITING, (pid,))
        row = await cursor.fetchone()
        if row is not None and row[0] > 0:
            return


async def _outcome(task: asyncio.Task[Reply]) -> BaseException | Reply:
    try:
        async with asyncio.timeout(_BOUND):
            return await task
    except (asyncio.CancelledError, TimeoutError) as error:
        return error


async def _pid(session: AsyncSession) -> int:
    pid = first_value(await session.pipeline([BACKEND_PID]))
    assert isinstance(pid, int)
    return pid


@dataclass(frozen=True, slots=True)
class CancelledOpen:
    """What awaiting the cancelled ``__aenter__`` raised (``None``: it returned) and what a
    ``session()`` on the same driver raised afterwards (``None``: it gave a session).
    """

    outcome: BaseException | None
    session_error: BaseException | None

    def session_error_cause(self) -> Exception | None:
        """The driver exception behind a ``SessionUnavailable`` from ``session()``."""
        assert isinstance(self.session_error, SessionUnavailable), repr(self.session_error)
        return self.session_error.fault.cause


def cancel_driver_open() -> CancelledOpen:
    """Cancel opening a driver (``min_size=1``) while its pool is connecting; try a session."""
    with socket.create_server(("127.0.0.1", 0)) as listener:
        listener.setblocking(False)
        port: int = listener.getsockname()[1]
        conninfo = f"postgresql://platina:platina@127.0.0.1:{port}/platina?connect_timeout=5"
        return asyncio.run(_open_scenario(listener, conninfo))


async def _open_scenario(listener: socket.socket, conninfo: str) -> CancelledOpen:
    driver = AsyncPsycopgDriver(conninfo, min_size=1, timeout=_BOUND)
    task = asyncio.create_task(_open(driver))
    async with asyncio.timeout(_BOUND):
        accepted, _ = await asyncio.get_running_loop().sock_accept(listener)
    with accepted:  # a pool worker is connecting now
        task.cancel()
    # The peer is closed, so the attempt in flight fails at once and the pool can stop.
    try:
        outcome = await _open_outcome(task)
        return CancelledOpen(outcome, await _session_error(driver))
    finally:
        # A driver that left its pool open would leave pool tasks that never finish, and
        # asyncio.run would wait for them forever. Closing a closed pool does nothing.
        async with asyncio.timeout(_BOUND):
            await driver.__aexit__(None, None, None)


async def _open(driver: AsyncPsycopgDriver) -> None:
    await driver.__aenter__()


async def _open_outcome(task: asyncio.Task[None]) -> BaseException | None:
    try:
        async with asyncio.timeout(_BOUND):
            await task
    except (asyncio.CancelledError, TimeoutError, psycopg.Error, SessionUnavailable) as error:
        return error
    return None


async def _session_error(driver: AsyncPsycopgDriver) -> BaseException | None:
    try:
        async with asyncio.timeout(_BOUND), driver.session():
            return None
    except (TimeoutError, SessionUnavailable) as error:
        return error
