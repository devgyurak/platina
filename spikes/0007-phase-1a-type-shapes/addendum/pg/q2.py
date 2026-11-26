"""F2/Q2: 23503 from a non-owned referrer (allocations -> items): when, diag fields, pipelines.

T1 alone, SERIALIZABLE: DELETE FROM items WHERE order_id = X; DELETE FROM orders WHERE id = X
AND version = 1; COMMIT, while an allocations row references one of X's items.
Part 1: plain statements, FK NOT DEFERRABLE and DEFERRABLE INITIALLY DEFERRED.
Part 2: psycopg pipeline mode, non-autocommit (conn.commit()) and autocommit with explicit
BEGIN/COMMIT, with and without a 0.2 s pause between calls (which call raises is timing-dependent).
Usage: q2.py [REPEAT]   (default 5)
"""

import sys
import time
import uuid

import common
import psycopg
from common import admin, new_order, schema, temp_database

DIAG = [
    "severity_nonlocalized",
    "message_primary",
    "message_detail",
    "message_hint",
    "schema_name",
    "table_name",
    "column_name",
    "datatype_name",
    "constraint_name",
    "source_file",
    "source_function",
]


def setup(a, deferred):
    schema(a, deferred=deferred, orders=1000, items_per=3)
    x, items = new_order(a, 2)
    a.execute("INSERT INTO allocations VALUES (%s, %s)", (uuid.uuid4(), items[0]))
    return x


def counts(a, x):
    return a.execute(
        "SELECT (SELECT count(*) FROM orders WHERE id = %s), "
        "(SELECT count(*) FROM items WHERE order_id = %s)",
        (x, x),
    ).fetchone()


def show(e):
    print(f"    class {type(e).__module__}.{type(e).__qualname__}")
    print(f"    mro {[c.__name__ for c in type(e).__mro__]}")
    print(f"    e.sqlstate={e.sqlstate!r}")
    for f in DIAG:
        print(f"    diag.{f}={getattr(e.diag, f)!r}")


def plain(a, deferred):
    x = setup(a, deferred)
    kind = "DEFERRABLE INITIALLY DEFERRED" if deferred else "NOT DEFERRABLE"
    print(f"=== plain statements, allocations FK {kind}")
    with psycopg.connect(common.DSN, autocommit=True) as c:
        for stmt, p in [
            ("BEGIN ISOLATION LEVEL SERIALIZABLE", None),
            ("DELETE FROM items WHERE order_id = %s", (x,)),
            ("DELETE FROM orders WHERE id = %s AND version = 1", (x,)),
            ("COMMIT", None),
        ]:
            try:
                cur = c.execute(stmt, p)
                print(f"  {stmt!r:55} -> {cur.statusmessage}")
            except psycopg.Error as e:
                status = c.info.transaction_status.name
                print(f"  {stmt!r:55} -> ERROR {e.sqlstate} (transaction status after: {status})")
                show(e)
        print(
            f"  final transaction status {c.info.transaction_status.name}; "
            f"(orders, items) rows of X: {counts(a, x)}"
        )


def step(label, fn, log):
    try:
        r = fn()
        log.append(f"{label}: ok" + ("" if r is None else f" {r}"))
    except psycopg.Error as e:
        log.append(f"{label}: RAISED {type(e).__name__} sqlstate={e.sqlstate}")


def pipeline(a, deferred, mode, delay):
    """mode 'txn': autocommit=False, isolation_level=SERIALIZABLE, conn.commit() in the pipeline.
    mode 'sql': autocommit=True, explicit BEGIN/COMMIT statements queued, then pipeline.sync()."""
    x = setup(a, deferred)
    log: list[str] = []
    c = psycopg.connect(common.DSN, autocommit=(mode == "sql"))
    if mode == "txn":
        c.isolation_level = psycopg.IsolationLevel.SERIALIZABLE
    curs: dict[str, psycopg.Cursor] = {}

    def execute(key, stmt, params=None):
        curs[key] = c.execute(stmt, params)

    try:
        with c.pipeline() as p:
            if mode == "sql":
                step(
                    "execute BEGIN", lambda: execute("b", "BEGIN ISOLATION LEVEL SERIALIZABLE"), log
                )
            step(
                "execute DELETE items",
                lambda: execute("items", "DELETE FROM items WHERE order_id = %s", (x,)),
                log,
            )
            time.sleep(delay)
            step(
                "execute DELETE orders",
                lambda: execute("orders", "DELETE FROM orders WHERE id = %s AND version = 1", (x,)),
                log,
            )
            time.sleep(delay)
            if mode == "sql":
                step("execute COMMIT", lambda: execute("c", "COMMIT"), log)
                step("pipeline.sync()", p.sync, log)
            else:
                step("conn.commit()", c.commit, log)
            status = psycopg.pq.TransactionStatus(c.pgconn.transaction_status).name
            log.append(f"(inside the block: transaction status {status})")
        log.append("pipeline block exit: ok")
    except psycopg.Error as e:
        log.append(f"pipeline block exit: RAISED {type(e).__name__} sqlstate={e.sqlstate}")
    for k in ("items", "orders"):
        if k in curs:
            log.append(
                f"cursor {k}: statusmessage={curs[k].statusmessage!r} rowcount={curs[k].rowcount}"
            )
        else:
            log.append(f"cursor {k}: never returned (its execute() raised)")
    log.append(
        f"after: transaction status {c.info.transaction_status.name}; "
        f"(orders, items) rows of X = {counts(a, x)}"
    )
    c.rollback()
    log.append(f"after conn.rollback(): transaction status {c.info.transaction_status.name}")
    c.close()
    return tuple(log)


def main():
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    with temp_database("q2"):
        a = admin()
        plain(a, False)
        plain(a, True)
        for deferred in (False, True):
            for mode in ("txn", "sql"):
                for delay in (0.0, 0.2):
                    seen: dict[tuple[str, ...], int] = {}
                    for _ in range(repeat):
                        lg = pipeline(a, deferred, mode, delay)
                        seen[lg] = seen.get(lg, 0) + 1
                    print(f"=== pipeline mode={mode} deferred={deferred} pause={delay}s")
                    for lg, n in seen.items():
                        print(f"  outcome x{n} of {repeat}:")
                        for line in lg:
                            print(f"    {line}")
        a.close()


if __name__ == "__main__":
    main()
