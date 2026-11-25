"""Does a blind increment, or `SELECT ... FOR UPDATE`, avoid serialization failures on a hot row?

Use cases 4 and 8 rest on two assumptions of the design: "commutative increments" (`.add(n)`, 4.4)
let concurrent writers of one row coexist, and a `lock="for_update"` profile is the escape hatch
for hot rows under the SERIALIZABLE default (8.3). Two sessions, pinned interleaving:

    T1: BEGIN; <op on row 1>
    T2: BEGIN; <op on row 1>      -- blocks on T1's row lock (run in a thread)
    T1: COMMIT
    T2: -> ? (committed / SQLSTATE)

Runs against the fast database (`make db-up`, port 26432): the question is whether it happens at
all. Uses its own schema and drops it.

    uv run python spikes/0002-use-cases-on-paper/db_increment_conflicts.py
"""

import os
import threading
import time
from collections.abc import Callable

import psycopg

DSN = os.environ.get("PLATINA_TEST_DSN", "postgresql://platina:platina@localhost:26432/platina")
SCHEMA = f"spike0002_{os.getpid()}"

type Op = Callable[[psycopg.Connection[tuple[object, ...]]], None]


def blind_increment(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    conn.execute(f"UPDATE {SCHEMA}.acc SET bal = bal + 1 WHERE id = 1")


def lock_then_increment(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    conn.execute(f"SELECT bal FROM {SCHEMA}.acc WHERE id = 1 FOR UPDATE")
    conn.execute(f"UPDATE {SCHEMA}.acc SET bal = bal + 1 WHERE id = 1")


def run(isolation: str, op: Op) -> str:
    with psycopg.connect(DSN, autocommit=True) as setup:
        setup.execute(f"DROP TABLE IF EXISTS {SCHEMA}.acc")
        setup.execute(f"CREATE TABLE {SCHEMA}.acc (id int PRIMARY KEY, bal int NOT NULL)")
        setup.execute(f"INSERT INTO {SCHEMA}.acc VALUES (1, 0)")
    t1 = psycopg.connect(DSN)
    t2 = psycopg.connect(DSN)
    outcome: list[str] = []
    try:
        t1.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
        t2.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
        t2.execute("SELECT 1")  # T2's snapshot is taken before T1 commits
        op(t1)

        def second() -> None:
            try:
                op(t2)
                t2.commit()
                outcome.append("committed")
            except psycopg.Error as e:
                outcome.append(f"{e.sqlstate} {type(e).__name__}: {str(e).splitlines()[0]}")
                t2.rollback()

        th = threading.Thread(target=second)
        th.start()
        time.sleep(0.5)  # T2 is now waiting on T1's row lock
        t1.commit()
        th.join()
        with psycopg.connect(DSN) as check:
            row = check.execute(f"SELECT bal FROM {SCHEMA}.acc WHERE id = 1").fetchone()
        return f"T2 {outcome[0]}; final bal = {row[0] if row else None}"
    finally:
        t1.close()
        t2.close()


def main() -> None:
    with psycopg.connect(DSN, autocommit=True) as c:
        version = c.execute("SELECT version()").fetchone()
        print(version[0] if version else "?")
        c.execute(f"CREATE SCHEMA {SCHEMA}")
    try:
        for isolation in ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"):
            for name, op in (
                ("blind increment", blind_increment),
                ("FOR UPDATE then increment", lock_then_increment),
            ):
                print(f"{isolation:16} {name:26} -> {run(isolation, op)}")
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {SCHEMA} CASCADE")


if __name__ == "__main__":
    main()
