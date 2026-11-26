"""Shared harness for the ADR-0010 PostgreSQL experiments (spike 0007 addendum, throwaway).

Every script runs inside its own temporary database (`temp_database`), created from the
maintenance DSN in `SPIKE_PG_DSN` (default: the fast profile on 26432) and dropped afterwards.
Two-session interleavings are pinned: each `Sess` runs its statements on its own thread, a
statement that has not returned after `BLOCK_WAIT` seconds is reported as BLOCKED together with
`pg_blocking_pids`, and its result is reported when it resumes.
"""

import os
import re
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ADMIN_DSN = os.environ.get("SPIKE_PG_DSN", "postgresql://platina:platina@localhost:26432/platina")
DURABLE_PORT = "26433"  # measurement profile: never used by these experiments
BLOCK_WAIT = 0.4
DSN = ""  # the temporary database, set by temp_database()

_monitor: psycopg.Connection[Any] | None = None


@contextmanager
def temp_database(tag: str) -> Iterator[str]:
    """Create `spike0007_pg_<tag>_<pid>`, point DSN at it, drop it (WITH FORCE) afterwards."""
    global DSN, _monitor
    if str(conninfo_to_dict(ADMIN_DSN).get("port")) == DURABLE_PORT:
        raise SystemExit(f"refusing to run against the durable profile ({DURABLE_PORT})")
    name = f"spike0007_pg_{tag}_{os.getpid()}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    DSN = make_conninfo(ADMIN_DSN, dbname=name)
    try:
        with psycopg.connect(DSN, autocommit=True) as c:
            server = c.execute("SELECT version()").fetchone()
            print(f"# server: {server[0] if server else '?'}")
            print(
                f"# psycopg {psycopg.__version__} ({psycopg.pq.__impl__}), libpq {psycopg.pq.version()}"
            )
            for g in (
                "default_transaction_isolation",
                "max_pred_locks_per_transaction",
                "max_pred_locks_per_relation",
                "max_pred_locks_per_page",
                "synchronous_commit",
            ):
                row = c.execute(sql.SQL("SHOW {}").format(sql.Identifier(g))).fetchone()
                print(f"# {g} = {row[0] if row else '?'}")
            print(f"# database: {name}", flush=True)
        yield DSN
    finally:
        if _monitor is not None:
            _monitor.close()
            _monitor = None
        with psycopg.connect(ADMIN_DSN, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def admin() -> psycopg.Connection[Any]:
    return psycopg.connect(DSN, autocommit=True)


def schema(
    conn: psycopg.Connection[Any],
    *,
    index: bool = True,
    deferred: bool = False,
    alloc: bool = True,
    orders: int = 0,
    items_per: int = 0,
    analyze: bool = True,
    keygen: Callable[[], uuid.UUID] = uuid.uuid4,
) -> None:
    """orders(id, version) <- items(order_id) [<- allocations(item_id)], plain NO ACTION FKs."""
    conn.execute("DROP TABLE IF EXISTS allocations, items, orders CASCADE")
    conn.execute("CREATE TABLE orders(id uuid PRIMARY KEY, version int NOT NULL)")
    conn.execute(
        "CREATE TABLE items(id uuid PRIMARY KEY, order_id uuid NOT NULL REFERENCES orders(id), qty int)"
    )
    if index:
        conn.execute("CREATE INDEX items_order_id ON items(order_id)")
    if alloc:
        d = " DEFERRABLE INITIALLY DEFERRED" if deferred else ""
        conn.execute(
            "CREATE TABLE allocations(id uuid PRIMARY KEY, "
            f"item_id uuid NOT NULL REFERENCES items(id){d})"
        )
    if orders:
        oids = [keygen() for _ in range(orders)]
        with conn.cursor() as cur:
            with cur.copy("COPY orders(id, version) FROM STDIN") as cp:
                for o in oids:
                    cp.write_row((o, 1))
            with cur.copy("COPY items(id, order_id, qty) FROM STDIN") as cp:
                for o in oids:
                    for _ in range(items_per):
                        cp.write_row((keygen(), o, 1))
    if analyze:
        conn.execute("VACUUM ANALYZE orders")
        conn.execute("VACUUM ANALYZE items")


def new_order(
    conn: psycopg.Connection[Any], n_items: int = 0, keygen: Callable[[], uuid.UUID] = uuid.uuid4
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    o = keygen()
    conn.execute("INSERT INTO orders VALUES (%s, 1)", (o,))
    items = []
    for _ in range(n_items):
        i = keygen()
        conn.execute("INSERT INTO items VALUES (%s, %s, 1)", (i, o))
        items.append(i)
    return o, items


def fmt_err(e: psycopg.Error) -> str:
    d = e.diag
    return (
        f"ERROR {e.sqlstate} {type(e).__name__}: {d.message_primary}"
        + (f" | DETAIL: {d.message_detail}" if d.message_detail else "")
        + (f" | HINT: {d.message_hint}" if d.message_hint else "")
    )


class Sess:
    """One session on its own thread; autocommit=True so BEGIN/COMMIT are explicit SQL."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.conn = psycopg.connect(DSN, autocommit=True)
        self.pid = self.conn.info.backend_pid
        self.ex = ThreadPoolExecutor(1)
        self.fut: Future[str] | None = None
        self.sql = ""
        self.log: list[tuple[str, str]] = []  # (statement, result) in completion order

    def _run(self, stmt: str, params: Any) -> str:
        try:
            cur = self.conn.execute(stmt, params)
            rows = cur.fetchall() if cur.description else None
            return f"{cur.statusmessage}" + (f" rows={rows}" if rows is not None else "")
        except psycopg.Error as e:
            return fmt_err(e)

    def go(self, stmt: str, params: Any = None, wait: float = BLOCK_WAIT) -> str:
        if self.fut is not None and self.check(15.0) == "BLOCKED":
            raise RuntimeError(f"{self.name}: {self.sql!r} still blocked; interleaving is wrong")
        self.sql = stmt
        self.fut = self.ex.submit(self._run, stmt, params)
        return self.check(wait, first=True)

    def check(self, wait: float = BLOCK_WAIT, first: bool = False) -> str:
        assert self.fut is not None
        try:
            r = self.fut.result(timeout=wait)
        except FutureTimeout:
            if first:
                print(f"  {self.name}: {self.sql!r:72} -> BLOCKED{blocked_on(self.pid)}")
            return "BLOCKED"
        self.fut = None
        self.log.append((self.sql, r))
        print(f"  {self.name}: {self.sql!r:72} -> {'' if first else '(resumed) '}{r}", flush=True)
        return r

    def poll(self) -> None:
        if self.fut is not None and self.fut.done():
            self.check(0)

    def close(self) -> None:
        if self.fut is not None:
            self.check(15.0)
        self.conn.close()
        self.ex.shutdown()

    def outcome(self) -> str:
        """First error (statement and SQLSTATE + reason) or the COMMIT result."""
        for stmt, r in self.log:
            if r.startswith("ERROR"):
                code = r.split()[1]
                reason = ""
                if "Reason code:" in r:
                    reason = " [" + r.split("Reason code: ")[1].split(".")[0] + "]"
                    reason = re.sub(r"pivot \d+", "pivot <xid>", reason)
                elif code == "40001":
                    reason = " [" + r.split(": ", 1)[1].split(" |")[0] + "]"
                return f"{code}{reason} at {short(stmt)}"
        for stmt, r in reversed(self.log):
            if stmt == "COMMIT":
                return f"COMMIT -> {r}"
        return "no COMMIT"


def short(stmt: str) -> str:
    s = " ".join(stmt.split())
    return s if len(s) <= 48 else s[:45] + "..."


def _mon() -> psycopg.Connection[Any]:
    global _monitor
    if _monitor is None:
        _monitor = admin()
    return _monitor


def blocked_on(pid: int) -> str:
    r = (
        _mon()
        .execute(
            "SELECT wait_event_type, wait_event, pg_blocking_pids(pid) FROM pg_stat_activity "
            "WHERE pid = %s",
            (pid,),
        )
        .fetchone()
    )
    return f" (wait {r[0]}/{r[1]}, blocked by pids {r[2]})" if r else ""


def sireadlocks(pid: int) -> list[tuple[Any, ...]]:
    return (
        _mon()
        .execute(
            "SELECT locktype, relation::regclass::text, page, tuple FROM pg_locks "
            "WHERE mode = 'SIReadLock' AND pid = %s ORDER BY 1, 2, 3, 4",
            (pid,),
        )
        .fetchall()
    )


class Tally:
    """Counts per-case outcomes across repetitions and prints them at the end."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, int]] = {}

    def add(self, case: str, *sessions: Sess) -> None:
        for s in sessions:
            d = self.rows.setdefault((case, s.name), {})
            o = s.outcome()
            d[o] = d.get(o, 0) + 1

    def print(self) -> None:
        print("\n## summary: case | session | outcome x runs")
        for (case, name), d in self.rows.items():
            for o, n in d.items():
                print(f"{case} | {name} | {o} x{n}")
