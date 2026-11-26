"""F3/Q3 (+N3): SIRead locks of a cascade DELETE that matches zero rows, and of the root DELETE's
own NO ACTION check, per table size / ANALYZE state / index. Plans via auto_explain (nested).

Variants for a root with no children (all SERIALIZABLE, rolled back after inspection):
  separate: DELETE FROM items WHERE order_id = $1; DELETE FROM orders WHERE id = $1 AND version = 1
  root-only: DELETE FROM orders WHERE id = $1 AND version = 1
  cte (N3): WITH c1 AS (DELETE FROM items WHERE order_id = ANY($1))
            DELETE FROM orders WHERE id = ANY($1)
"""

from common import Sess, admin, new_order, schema, sireadlocks, temp_database

CONFIGS = [
    ("10k orders x3 items, analyzed, index", {"orders": 10000, "items_per": 3}),
    ("10k orders x3 items, analyzed, NO index", {"orders": 10000, "items_per": 3, "index": False}),
    ("30 orders x3 items, analyzed, index", {"orders": 30, "items_per": 3}),
    ("30 orders x3 items, never analyzed, index", {"orders": 30, "items_per": 3, "analyze": False}),
    ("0 items (10k orders), analyzed, index", {"orders": 10000, "items_per": 0}),
]
CTE = (
    "WITH c1 AS (DELETE FROM items WHERE order_id = ANY(%s)) DELETE FROM orders WHERE id = ANY(%s)"
)


def stats(a):
    return a.execute(
        "SELECT relname, relpages, reltuples FROM pg_class WHERE relname IN "
        "('orders', 'items', 'items_order_id', 'orders_pkey') ORDER BY 1"
    ).fetchall()


def on_notice(d):
    lines = [ln.strip() for ln in (d.message_primary or "").splitlines()]
    print("    [auto_explain] " + " / ".join(ln for ln in lines if ln and "Query Text" not in ln))


def run(variant, x):
    t = Sess("T1")
    t.conn.add_notice_handler(on_notice)
    for s in (
        "LOAD 'auto_explain'",
        "SET auto_explain.log_min_duration = 0",
        "SET auto_explain.log_nested_statements = on",
        "SET client_min_messages = log",
        "BEGIN ISOLATION LEVEL SERIALIZABLE",
    ):
        t.go(s)
    if variant == "cte":
        t.go(CTE, ([x], [x]))
    else:
        if variant == "separate":
            t.go("DELETE FROM items WHERE order_id = %s", (x,))
            print(f"    SIRead after child DELETE: {sireadlocks(t.pid)}")
        t.go("DELETE FROM orders WHERE id = %s AND version = 1", (x,))
    locks = sireadlocks(t.pid)
    print(f"    SIRead at end ({variant}): {locks}")
    t.go("ROLLBACK")
    t.close()
    return locks


def main():
    summary = []
    with temp_database("q3locks"):
        a = admin()
        for name, kw in CONFIGS:
            schema(a, alloc=False, **kw)
            x, _ = new_order(a, 0)
            print(f"=== {name}; pg_class (relname, relpages, reltuples): {stats(a)}")
            # relation/page numbers differ per variant only if the plan differs; compare the
            # lock *shape* (locktype, relation) as well as the exact set
            for variant in ("separate", "root-only", "cte"):
                print(f"  -- {variant}")
                locks = run(variant, x)
                summary.append((name, variant, locks))
        a.close()
    print("\n## summary: config | variant | SIRead locks held before COMMIT")
    for name, variant, locks in summary:
        print(f"{name} | {variant} | {locks}")


if __name__ == "__main__":
    main()
