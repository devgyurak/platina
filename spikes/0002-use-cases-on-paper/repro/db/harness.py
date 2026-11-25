# TEMPORARY (spike 0002): the reproducer's code below is kept byte-identical, so lint and
# formatting are suppressed for this file until the maintainer decides how to treat it.
# ruff: noqa: UP037
# fmt: off
"""Throwaway two-session harness for the spike 0002 reproduction (pg-researcher).

Every statement of a session runs in a thread. `Sess.do` returns either the statement's outcome
or, when the monitor connection OBSERVES the backend waiting on a heavyweight lock
(pg_stat_activity.wait_event_type = 'Lock'), a pending handle. No sleep stands in for a wait.
"""

import os
import threading
import time

import psycopg

DSN = os.environ.get("PLATINA_TEST_DSN", "postgresql://platina:platina@localhost:26432/platina")
SCHEMA = f"repro0002_{os.getpid()}"

_mon = psycopg.connect(DSN, autocommit=True)


def log(msg: str) -> None:
    print(msg, flush=True)


class Pending:
    def __init__(self, sess: "Sess", sql: str, th: threading.Thread, box: list[str]) -> None:
        self.sess, self.sql, self.th, self.box = sess, sql, th, box

    def still_waiting(self) -> bool:
        return self.th.is_alive()

    def result(self) -> str:
        self.th.join(timeout=30)
        if self.th.is_alive():
            raise RuntimeError(f"{self.sess.name} still blocked: {self.sql}")
        log(f"    [{self.sess.name}] (resumed) {self.sql}\n        -> {self.box[0]}")
        return self.box[0]


class Sess:
    def __init__(self, name: str) -> None:
        self.name = name
        self.conn = psycopg.connect(DSN, autocommit=True)  # explicit BEGIN/COMMIT only
        row = self.conn.execute("SELECT pg_backend_pid()").fetchone()
        assert row is not None
        self.pid: int = row[0]

    def close(self) -> None:
        self.conn.close()

    def _exec(self, sql: str, box: list[str]) -> None:
        try:
            cur = self.conn.execute(sql)
            if cur.description is not None:
                box.append(f"rows={cur.fetchall()}")
            else:
                box.append(f"ok ({cur.statusmessage})")
        except psycopg.Error as e:
            d = e.diag
            box.append(f"ERROR {e.sqlstate} {type(e).__name__}: {d.message_primary}"
                       + (f" | DETAIL: {d.message_detail}" if d.message_detail else ""))

    def do(self, sql: str) -> "str | Pending":
        """Run one statement; return its outcome, or Pending if observed waiting on a lock."""
        box: list[str] = []
        th = threading.Thread(target=self._exec, args=(sql, box))
        th.start()
        while True:
            th.join(timeout=0.02)
            if not th.is_alive():
                log(f"    [{self.name}] {sql}\n        -> {box[0]}")
                return box[0]
            row = _mon.execute(
                "SELECT state, wait_event_type, wait_event, pg_blocking_pids(pid) "
                "FROM pg_stat_activity WHERE pid = %s", (self.pid,)).fetchone()
            if row and row[1] == "Lock":
                locks = _mon.execute(
                    "SELECT locktype, mode, coalesce(transactionid::text, relation::regclass::text) "
                    "FROM pg_locks WHERE pid = %s AND NOT granted", (self.pid,)).fetchall()
                time.sleep(0.2)  # confirm it is still waiting, not a transient state
                if th.is_alive():
                    log(f"    [{self.name}] {sql}\n        -> BLOCKED (observed): state={row[0]} "
                        f"wait_event={row[1]}:{row[2]} blocked_by_pids={row[3]} ungranted={locks}")
                    return Pending(self, sql, th, box)


def is_err(r: "str | Pending") -> bool:
    return isinstance(r, str) and r.startswith("ERROR")


def admin(sql: str) -> list[tuple[object, ...]]:
    with psycopg.connect(DSN, autocommit=True) as c:
        cur = c.execute(sql)
        return cur.fetchall() if cur.description is not None else []


def create_schema() -> None:
    admin(f"CREATE SCHEMA {SCHEMA}")
    log(f"schema {SCHEMA} created")


def drop_schema() -> None:
    admin(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    log(f"schema {SCHEMA} dropped")


def banner() -> None:
    log(str(admin("SELECT version()")[0][0]))
    log(f"psycopg {psycopg.__version__} ({psycopg.pq.__impl__}, libpq {psycopg.pq.version()}); DSN port "
        f"{DSN.rsplit(':', 1)[1].split('/')[0]}")
    for g in ("default_transaction_isolation", "max_pred_locks_per_transaction",
              "max_pred_locks_per_relation", "max_pred_locks_per_page", "synchronous_commit",
              "fsync", "deadlock_timeout", "lock_timeout"):
        log(f"  {g} = {admin(f'SHOW {g}')[0][0]}")
