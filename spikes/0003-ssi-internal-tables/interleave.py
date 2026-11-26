"""Fixed interleavings A1-A5 of spike 0003 (fast profile).

Usage: uv run python spikes/0003-ssi-internal-tables/interleave.py --port 26432 [A1 A2 ...]
Appends to results/interleave.txt and prints the same lines.
"""

from __future__ import annotations

import argparse
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import common
import psycopg

LOG: list[str] = []
Stmt = tuple[str, tuple[Any, ...]]
Stages = list[list[Stmt]]


def log(line: str = "") -> None:
    print(line, flush=True)
    LOG.append(line)


def _short(p: Any) -> str:
    return "…" + str(p)[-6:] if isinstance(p, uuid.UUID) else repr(p)


def _show(sql: str, params: tuple[Any, ...]) -> str:
    parts = sql.split("%s")
    vals = [_short(p) for p in params] + [""]
    return "".join(part + vals[i] for i, part in enumerate(parts)) if params else sql


class Session:
    """One connection in autocommit mode; transactions are opened with an explicit BEGIN, so
    the snapshot is taken by the first statement that needs one, as the engine would do it."""

    def __init__(self, name: str, port: int) -> None:
        self.name = name
        self.conn = common.connect(port)
        self.pid: int = self.conn.info.backend_pid
        self._thread: threading.Thread | None = None
        self._result = ""

    def run(self, sql: str, params: tuple[Any, ...] = ()) -> str:
        try:
            cur = self.conn.execute(sql, params)  # type: ignore[arg-type]
            rows = cur.fetchall() if cur.description else None
            out = f"ok {rows}" if rows is not None else f"ok rowcount={cur.rowcount}"
        except psycopg.Error as exc:
            out = _err(exc)
        log(f"  {self.name}: {_show(sql, params)} -> {out}")
        return out

    def start(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        """Send a statement that may block; its result is read with finish()."""

        def target() -> None:
            try:
                cur = self.conn.execute(sql, params)  # type: ignore[arg-type]
                self._result = f"ok rowcount={cur.rowcount}"
            except psycopg.Error as exc:
                self._result = _err(exc)

        self._result = ""
        self._thread = threading.Thread(target=target)
        self._thread.start()
        log(f"  {self.name}: {_show(sql, params)} (sent)")

    def done(self) -> bool:
        return self._thread is not None and not self._thread.is_alive()

    def finish(self) -> str:
        assert self._thread is not None
        self._thread.join(timeout=10)
        res = self._result if not self._thread.is_alive() else "STILL BLOCKED after 10 s"
        log(f"  {self.name}: (completed) -> {res}")
        return res

    def close(self) -> None:
        self.conn.close()


def _err(exc: psycopg.Error) -> str:
    d = exc.diag
    return f"ERROR {d.sqlstate}: {d.message_primary} | detail: {d.message_detail}"


class Observer(Session):
    def waiting(self, s: Session, timeout: float = 3.0) -> bool:
        """Polls until s waits on a heavyweight lock; stops early if s's statement finished."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if s.done():
                log(f"  O: {s.name}'s statement finished without waiting: {s._result}")
                return False
            row = self.conn.execute(
                "SELECT wait_event_type, wait_event FROM pg_stat_activity WHERE pid = %s",
                (s.pid,),
            ).fetchone()
            if row and row[0] == "Lock":
                lk = self.conn.execute(
                    "SELECT locktype, mode FROM pg_locks WHERE pid = %s AND NOT granted", (s.pid,)
                ).fetchall()
                log(f"  O: {s.name} waits: wait_event={row[0]}/{row[1]} ungranted={lk}")
                return True
            time.sleep(0.02)
        log(f"  O: {s.name} NOT waiting after {timeout} s")
        return False

    def xmin(self, s: Session, when: str) -> None:
        row = self.conn.execute(
            "SELECT backend_xid::text, backend_xmin::text FROM pg_stat_activity WHERE pid = %s",
            (s.pid,),
        ).fetchone()
        log(f"  O: {s.name} {when}: backend_xid={row and row[0]} backend_xmin={row and row[1]}")

    def siread(self, ss: list[Session]) -> list[tuple[Any, ...]]:
        names = {s.pid: s.name for s in ss}
        rows = self.conn.execute(
            """SELECT l.pid, l.locktype, c.relname, l.page, l.tuple
               FROM pg_locks l LEFT JOIN pg_class c ON c.oid = l.relation
               WHERE l.mode = 'SIReadLock' AND l.pid = ANY(%s)
               ORDER BY l.pid, c.relname, l.locktype, l.page, l.tuple""",
            ([s.pid for s in ss],),
        ).fetchall()
        log(f"  O: SIReadLock rows ({len(rows)}):")
        for r in rows:
            log(f"       {names[r[0]]} {r[1]:<8} {r[2]} page={r[3]} tuple={r[4]}")
        return rows


def open_sessions(port: int, n: int) -> tuple[list[Session], Observer]:
    return [Session(f"S{i + 1}", port) for i in range(n)], Observer("O", port)


def close_all(ss: list[Session], obs: Session) -> None:
    for s in [*ss, obs]:
        s.close()


ISO_CHECK: Stmt = ("SELECT current_setting('transaction_isolation')", ())


def multi_session_round(
    port: int,
    label: str,
    stages: Callable[[int], Stages],
    order: str,
    *,
    n: int = 3,
    pre: Callable[[Session, int], None] | None = None,
) -> None:
    """order = "sequential": S1 runs all its stages, then S2, then S3.
    order = "phased": stage 1 of S1, S2, S3, then stage 2 of S1, S2, S3, ...
    Then: observe SIRead locks, check the isolation level, COMMIT S3, S2, S1 (reverse order, so
    the last writer commits first - the shape of a dangerous structure S1 -> S2 -> S3)."""
    log(f"-- {label} [order={order}]")
    ss, obs = open_sessions(port, n)
    try:
        if pre is not None:
            for i, s in enumerate(ss):
                pre(s, i)
        for s in ss:
            s.run("BEGIN ISOLATION LEVEL SERIALIZABLE")
        plan = [stages(i) for i in range(n)]
        if order == "sequential":
            for i, s in enumerate(ss):
                for stage in plan[i]:
                    for sql, params in stage:
                        s.run(sql, params)
        else:
            for k in range(max(len(p) for p in plan)):
                for i, s in enumerate(ss):
                    for sql, params in plan[i][k] if k < len(plan[i]) else []:
                        s.run(sql, params)
        obs.siread(ss)
        for s in ss:
            s.run(*ISO_CHECK)
        for s in reversed(ss):
            s.run("COMMIT")
    finally:
        close_all(ss, obs)


# ----------------------------------------------------------------------------- A1


def a1_stages(variant: str, rid: uuid.UUID) -> Stages:
    claim: Stmt = ("INSERT INTO run_claim(id) VALUES (%s)", (rid,))
    return {
        "claim": [[claim]],
        "claim_retry": [[claim]],  # the ID was inserted and rolled back first (pre step)
        "full": [
            [claim],
            [
                ("INSERT INTO outbox_log(payload) VALUES ('{\"e\": 1}')", ()),
                ("INSERT INTO run_result(run_id, result) VALUES (%s, '{}')", (rid,)),
                ("SELECT pg_current_xact_id()::text", ()),
            ],
        ],
        "read_insert": [[("SELECT 1 FROM run_claim WHERE id = %s", (rid,))], [claim]],
        "insert_update": [
            [("INSERT INTO run_claim_u(id) VALUES (%s)", (rid,))],
            [("UPDATE run_claim_u SET result = '{}' WHERE id = %s", (rid,))],
        ],
    }[variant]


def prepare_internal(port: int, state: str) -> None:
    common.reset(port)
    if state == "1M":
        with common.connect(port) as conn:
            common.load_uuid7_claims(conn, "run_claim", 1_000_000)
            common.load_uuid7_claims(conn, "run_claim_u", 1_000_000)
            conn.execute(
                "INSERT INTO outbox_log(payload) "
                "SELECT '{}'::jsonb FROM generate_series(1, 1000000)"
            )
            common.copy_rows(
                conn,
                "run_result",
                "run_id, result",
                ((common.uuid7(), "{}") for _ in range(1_000_000)),
            )
    with common.connect(port) as conn:
        conn.execute("VACUUM ANALYZE")


def a1(port: int) -> None:
    log("== A1: internal-table variants, three sessions, empty vs 1M rows")
    for state in ("empty", "1M"):
        prepare_internal(port, state)
        for variant in ("claim", "claim_retry", "full", "read_insert", "insert_update"):
            for order in ("sequential", "phased"):
                rids = [common.uuid7() for _ in range(3)]

                def pre(s: Session, i: int, r: list[uuid.UUID] = rids) -> None:
                    s.run("BEGIN ISOLATION LEVEL SERIALIZABLE")
                    s.run("INSERT INTO run_claim(id) VALUES (%s)", (r[i],))
                    s.run("ROLLBACK")

                multi_session_round(
                    port,
                    f"A1 state={state} variant={variant}",
                    lambda i, v=variant, r=rids: a1_stages(v, r[i]),
                    order,
                    pre=pre if variant == "claim_retry" else None,
                )


# ----------------------------------------------------------------------------- A2

INS = "INSERT INTO run_claim(id) VALUES (%s)"


def a2(port: int) -> None:
    log("== A2: fencing on the same run ID")
    for s1_iso in ("SERIALIZABLE", "READ COMMITTED"):
        common.reset(port)

        for name, s1_end in (("F1", "COMMIT"), ("F2", "ROLLBACK")):
            log(f"-- {name} (S1 {s1_iso}): S1 holds X, S2 inserts X and waits, S1 {s1_end}")
            (s1, s2), obs = open_sessions(port, 2)
            x = common.uuid7()
            s1.run(f"BEGIN ISOLATION LEVEL {s1_iso}")
            s1.run(INS, (x,))
            s2.run("BEGIN ISOLATION LEVEL SERIALIZABLE")
            s2.start(INS, (x,))
            obs.waiting(s2)
            s1.run(s1_end)
            s2.finish()
            obs.siread([s1, s2])
            s2.run(*ISO_CHECK)
            s2.run("COMMIT")
            obs.run("SELECT count(*) FROM run_claim WHERE id = %s", (x,))
            close_all([s1, s2], obs)

        log(f"-- F3 (S1 {s1_iso}): S1 inserts X and commits; then S2 BEGIN, INSERT X")
        (s1, s2), obs = open_sessions(port, 2)
        x = common.uuid7()
        s1.run(f"BEGIN ISOLATION LEVEL {s1_iso}")
        s1.run(INS, (x,))
        s1.run("COMMIT")
        s2.run("BEGIN ISOLATION LEVEL SERIALIZABLE")
        s2.run(INS, (x,))
        s2.run("ROLLBACK")
        close_all([s1, s2], obs)

        log(
            f"-- F4 (S1 {s1_iso}): S2 BEGIN, SELECT 1 (snapshot); S1 inserts X, commits; S2 INSERT X"
        )
        (s1, s2), obs = open_sessions(port, 2)
        x = common.uuid7()
        s2.run("BEGIN ISOLATION LEVEL SERIALIZABLE")
        s2.run("SELECT 1")
        obs.xmin(s2, "after SELECT 1")
        s1.run(f"BEGIN ISOLATION LEVEL {s1_iso}")
        s1.run(INS, (x,))
        s1.run("COMMIT")
        s2.run(INS, (x,))
        s2.run("ROLLBACK")
        close_all([s1, s2], obs)


# ----------------------------------------------------------------------------- A3


def a3(port: int) -> None:
    log("== A3: snapshot aging of a transaction that waited on the claim")
    for name in ("F5", "F5-read", "F5-control"):
        common.reset(port)
        o = common.uuid7()
        with common.connect(port) as conn:
            conn.execute("INSERT INTO orders VALUES (%s, 1, 1, 'PENDING', 0, 1)", (o,))
        log(f"-- {name}")
        (s1, s2, s3), obs = open_sessions(port, 3)
        x = common.uuid7()
        s1.run("BEGIN ISOLATION LEVEL SERIALIZABLE")
        s1.run(INS, (x,))
        s2.run("BEGIN ISOLATION LEVEL SERIALIZABLE")
        obs.xmin(s2, "after BEGIN")
        s2.run("SET LOCAL statement_timeout = '10s'")
        obs.xmin(s2, "after SET LOCAL")
        s2.start(INS, (x,))
        obs.waiting(s2)
        obs.xmin(s2, "while its claim waits")
        if name != "F5-control":
            s3.run("UPDATE orders SET total = 100 WHERE id = %s", (o,))
        s1.run("ROLLBACK")
        s2.finish()
        obs.xmin(s2, "after its claim completed")
        s2.run("SELECT total FROM orders WHERE id = %s", (o,))
        if name != "F5-read":
            s2.run("UPDATE orders SET total = total + 1 WHERE id = %s", (o,))
        s2.run("COMMIT")
        obs.run("SELECT total FROM orders WHERE id = %s", (o,))
        close_all([s1, s2, s3], obs)


# ----------------------------------------------------------------------------- A4


def upsert(table: str, col: str, key: Any) -> Stmt:
    return (
        f"INSERT INTO {table}({col}, total) VALUES (%s, 1) "
        f"ON CONFLICT ({col}) DO UPDATE SET total = {table}.total + 1",
        (key,),
    )


def a4(port: int) -> None:
    log("== A4: projection write forms - SIRead locks and three-session outcome")
    common.reset(port)
    with common.connect(port) as conn:
        conn.execute("INSERT INTO user_spending SELECT g, 0 FROM generate_series(1, 100000) g")
        conn.execute("VACUUM ANALYZE user_spending")
    keys = [50001, 50002, 50003]
    forms: dict[str, Callable[[int], Stages]] = {
        "update_existing": lambda i: [
            [("UPDATE user_spending SET total = total + 1 WHERE user_id = %s", (keys[i],))]
        ],
        "upsert_existing": lambda i: [[upsert("user_spending", "user_id", keys[i])]],
    }
    for form, fn in forms.items():
        multi_session_round(port, f"A4 {form} (adjacent keys)", fn, "sequential")
    for state in ("empty", "100k"):
        common.reset(port)
        if state == "100k":
            with common.connect(port) as conn:
                common.copy_rows(
                    conn, "proj_new", "id, total", ((common.uuid7(), 0) for _ in range(100_000))
                )
                conn.execute("VACUUM ANALYZE proj_new")
        new = [common.uuid7() for _ in range(3)]
        multi_session_round(
            port,
            f"A4 upsert_new uuid7 key (proj_new {state})",
            lambda i, n=new: [[upsert("proj_new", "id", n[i])]],
            "sequential",
        )


# ----------------------------------------------------------------------------- A5


def a5(port: int) -> None:
    log("== A5: small vs large business table, never analyzed vs analyzed")
    for table, n in (("small_orders", 30), ("orders", 100_000)):
        for analyzed in (False, True):
            common.reset(port)
            with common.connect(port) as conn:
                conn.execute(f"ALTER TABLE {table} SET (autovacuum_enabled = false)")  # type: ignore[arg-type]
                ids = common.load_orders(conn, table, n)
                if analyzed:
                    conn.execute(f"ANALYZE {table}")  # type: ignore[arg-type]
                st = conn.execute(
                    "SELECT relpages, reltuples FROM pg_class WHERE relname = %s", (table,)
                ).fetchone()
            rows = [ids[5], ids[15], ids[25]]
            multi_session_round(
                port,
                f"A5 {table} rows={n} analyzed={analyzed} pg_class(relpages, reltuples)={st}",
                lambda i, r=rows, t=table: [
                    [
                        (
                            f"EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF, SUMMARY OFF) SELECT * FROM {t} WHERE id = %s",
                            (r[i],),
                        )
                    ],
                    [
                        (
                            f"EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF, SUMMARY OFF) UPDATE {t} SET total = total + 1 WHERE id = %s",
                            (r[i],),
                        )
                    ],
                ],
                "phased",
            )


# ----------------------------------------------------------------------------- A6


def a6(port: int) -> None:
    """uuid7 locality of a user table: "read a recent row by primary key + INSERT a new row" in
    two unrelated transactions (each reads only the row it committed itself just before)."""
    log("== A6: read own recent row by PK + INSERT a new row, uuid7 vs uuid4 keys")
    for key in ("uuid7", "uuid4"):
        new_key: Callable[[], uuid.UUID] = common.uuid7 if key == "uuid7" else uuid.uuid4
        for read in ("recent", "old"):
            common.reset(port)
            with common.connect(port) as conn:
                common.copy_rows(
                    conn,
                    "orders",
                    "id, user_id, store_id, status, total, version",
                    ((new_key(), 1, 1, "PENDING", 10, 1) for _ in range(100_000)),
                )
                conn.execute("VACUUM ANALYZE orders")
                old = [
                    r[0] for r in conn.execute("SELECT id FROM orders ORDER BY random() LIMIT 2")
                ]
                own = [new_key(), new_key()]
                for o in own:  # each session's own recent order, committed before the test
                    conn.execute("INSERT INTO orders VALUES (%s, 1, 1, 'PENDING', 10, 1)", (o,))
                pages = conn.execute(
                    "SELECT id, (SELECT count(*) FROM orders) FROM orders WHERE id = ANY(%s)",
                    (own,),
                ).fetchall()
            targets = own if read == "recent" else old
            fresh = [new_key(), new_key()]
            log(f"-- A6 key={key} read={read} (rows={pages[0][1] if pages else '?'})")
            for n_sessions, order in ((2, "phased"), (2, "sequential")):
                multi_session_round(
                    port,
                    f"A6 key={key} read={read} sessions={n_sessions}",
                    lambda i, t=targets, f=fresh: [
                        [("SELECT * FROM orders WHERE id = %s", (t[i],))],
                        [("INSERT INTO orders VALUES (%s, 1, 1, 'PENDING', 10, 1)", (f[i],))],
                    ],
                    order,
                    n=n_sessions,
                )
                fresh = [new_key(), new_key()]


# ----------------------------------------------------------------------------- A7


def _q(s: Session, sql: str, params: tuple[Any, ...] = ()) -> str:
    """Run one statement without logging it; "ok" or "<SQLSTATE> <message> | <detail>"."""
    try:
        s.conn.execute(sql, params)  # type: ignore[arg-type]
        return "ok"
    except psycopg.Error as exc:
        d = exc.diag
        return f"{d.sqlstate} {d.message_primary} | {d.message_detail}"


FK_DDL = (
    "DROP TABLE IF EXISTS fk_child, fk_parent",
    "CREATE TABLE fk_parent (id uuid PRIMARY KEY, v int NOT NULL DEFAULT 0)",
    "CREATE TABLE fk_child (id uuid PRIMARY KEY, "
    "parent_id uuid NOT NULL REFERENCES fk_parent (id))",
)
INS_P = "INSERT INTO fk_parent (id) VALUES (%s)"
INS_C = "INSERT INTO fk_child (id, parent_id) VALUES (%s, %s)"


def _a7_key(port: int, key: str, reps: int) -> None:
    new_key: Callable[[], uuid.UUID] = common.uuid7 if key == "uuid7" else uuid.uuid4
    with common.connect(port) as conn:
        for ddl in FK_DDL:
            conn.execute(ddl)  # type: ignore[arg-type]
        common.copy_rows(conn, "fk_parent", "id", ((new_key(),) for _ in range(100_000)))
        conn.execute("VACUUM ANALYZE fk_parent")
        old = [r[0] for r in conn.execute("SELECT id FROM fk_parent ORDER BY random() LIMIT 2")]

    # -- lock observation: which SIRead locks does a child INSERT's FK check take?
    log(f"-- A7 key={key} lock observation (one session, SERIALIZABLE)")
    (s1,), obs = open_sessions(port, 1)
    recent = new_key()
    with common.connect(port) as conn:
        conn.execute(INS_P, (recent,))  # a parent committed just before
    for case, stmts in (
        ("child of its own new parent (same transaction)", "own"),
        ("child of a parent committed just before", "recent"),
        ("child of an old parent", "old"),
    ):
        s1.run("BEGIN ISOLATION LEVEL SERIALIZABLE")
        if stmts == "own":
            p = new_key()
            s1.run(INS_P, (p,))
        else:
            p = recent if stmts == "recent" else old[0]
        s1.run(INS_C, (new_key(), p))
        log(f"  [{case}]")
        obs.siread([s1])
        s1.run("COMMIT")
    close_all([s1], obs)

    # -- three orders, each repeated
    def run_case(name: str, n: int, plan: Callable[[list[Session]], None]) -> None:
        fails = 0
        for rep in range(1, reps + 1):
            ss, obs = open_sessions(port, n)
            for s in ss:
                _q(s, "BEGIN ISOLATION LEVEL SERIALIZABLE")
            errs: list[str] = []
            try:
                plan(ss)
            finally:
                outcomes = []
                for s in reversed(ss):
                    r = _q(s, "COMMIT")
                    outcomes.append(f"{s.name} COMMIT: {r}")
                    if r != "ok":
                        errs.append(r)
                close_all(ss, obs)
            failed = any(o.split(": ", 1)[1] != "ok" for o in outcomes)
            fails += failed
            log(f"  rep {rep}: " + "; ".join(outcomes))
        log(f"  => {name}: {fails}/{reps} reps with a failed commit")

    def p1(ss: list[Session]) -> None:  # each: parent + its child; commit S3, S2, S1
        for s in ss:
            pid = new_key()
            for sql, prm in ((INS_P, (pid,)), (INS_C, (new_key(), pid))):
                r = _q(s, sql, prm)
                if r != "ok":
                    log(f"    {s.name}: {sql.split(' (')[0]} -> {r}")

    def p2(ss: list[Session]) -> None:  # child of own recent parent, then new parent (phased)
        recents = [new_key() for _ in ss]
        with common.connect(port) as conn:
            for rp in recents:
                conn.execute(INS_P, (rp,))
        for s, rp in zip(ss, recents, strict=True):
            r = _q(s, INS_C, (new_key(), rp))
            if r != "ok":
                log(f"    {s.name}: child -> {r}")
        for s in ss:
            r = _q(s, INS_P, (new_key(),))
            if r != "ok":
                log(f"    {s.name}: parent -> {r}")

    def p3(ss: list[Session]) -> None:  # both parents first, then both children
        pids = [new_key() for _ in ss]
        for s, pid in zip(ss, pids, strict=True):
            r = _q(s, INS_P, (pid,))
            if r != "ok":
                log(f"    {s.name}: parent -> {r}")
        for s, pid in zip(ss, pids, strict=True):
            r = _q(s, INS_C, (new_key(), pid))
            if r != "ok":
                log(f"    {s.name}: child -> {r}")

    log(
        f"-- A7 key={key} P1: three sessions, each parent INSERT + its child INSERT in turn; COMMIT S3, S2, S1"
    )
    run_case(f"key={key} P1", 3, p1)
    log(
        f"-- A7 key={key} P2: two sessions, each child of its own just-committed parent, then a new parent (children first, then parents); COMMIT S2, S1"
    )
    run_case(f"key={key} P2", 2, p2)
    log(
        f"-- A7 key={key} P3: two sessions, each parent + its child (both parents first, then both children); COMMIT S2, S1"
    )
    run_case(f"key={key} P3", 2, p3)


def a7(port: int, reps: int = 10) -> None:
    """FK checks against a parent with an ever-increasing key (added after the morning report,
    see the change record). Parent 100,000 rows; parent and child keys from the same generator."""
    log("== A7: FK checks on an ever-increasing parent key (uuid7 vs uuid4), fast profile")
    for key in ("uuid7", "uuid4"):
        _a7_key(port, key, reps)
    with common.connect(port) as conn:
        conn.execute("DROP TABLE IF EXISTS fk_child, fk_parent")


SCENARIOS: dict[str, Callable[[int], None]] = {
    "A1": a1,
    "A2": a2,
    "A3": a3,
    "A4": a4,
    "A5": a5,
    "A6": a6,
    "A7": a7,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=26432)
    ap.add_argument("only", nargs="*", default=[k for k in SCENARIOS if k not in ("A6", "A7")])
    args = ap.parse_args()
    with common.connect(args.port) as conn:
        version = conn.execute("SELECT version()").fetchone()
    log(f"# interleave.py {datetime.now(UTC).isoformat()} port={args.port} {version}")
    for name in args.only:
        SCENARIOS[name](args.port)
    common.RESULTS.mkdir(exist_ok=True)
    with (common.RESULTS / "interleave.txt").open("a") as f:
        f.write("\n".join(LOG) + "\n")


if __name__ == "__main__":
    main()
