"""F1/Q1: a concurrent child INSERT racing the engine's cascade delete (pinned interleavings).

T1 = deleter: BEGIN; [load]; DELETE FROM items WHERE order_id = X; DELETE FROM orders WHERE id = X
AND version = 1; COMMIT. T2 = plain child INSERT (no root bump). Both at the same isolation level.
Usage: q1.py [REPEAT] [ISOLATION ...]   (default: 3 SERIALIZABLE "REPEATABLE READ")
"""

import sys
import uuid

from common import Sess, Tally, admin, new_order, schema, temp_database

DEL_ITEMS = "DELETE FROM items WHERE order_id = %s"
DEL_ORDER = "DELETE FROM orders WHERE id = %s AND version = 1"
INS_ITEM = "INSERT INTO items VALUES (%s, %s, 1)"
LOAD_O = "SELECT version FROM orders WHERE id = %s"
LOAD_I = "SELECT count(*) FROM items WHERE order_id = %s"


def final(a, x):
    o = a.execute("SELECT count(*) FROM orders WHERE id = %s", (x,)).fetchone()[0]
    i = a.execute("SELECT count(*) FROM items WHERE order_id = %s", (x,)).fetchone()[0]
    print(f"  final: orders(X)={o} items(X)={i}")


def case_a(a, begin, tally, label):
    """T1 deletes first (uncommitted); T2 then inserts a child of X."""
    x, _ = new_order(a, 2)
    t1, t2 = Sess("T1"), Sess("T2")
    t1.go(begin)
    t2.go(begin)
    t1.go(LOAD_O, (x,))
    t1.go(LOAD_I, (x,))
    t2.go("SELECT 1")
    t1.go(DEL_ITEMS, (x,))
    t1.go(DEL_ORDER, (x,))
    t2.go(INS_ITEM, (uuid.uuid4(), x))
    t1.go("COMMIT")
    t2.go("COMMIT")
    final(a, x)
    t1.close()
    t2.close()
    tally.add(label, t1, t2)


def case_b(a, begin, tally, label, load):
    """T2 inserts first (uncommitted); T1 [loads and] deletes; T2 commits."""
    x, _ = new_order(a, 2)
    t1, t2 = Sess("T1"), Sess("T2")
    t1.go(begin)
    t2.go(begin)
    if load:
        t1.go(LOAD_O, (x,))
        t1.go(LOAD_I, (x,))
    t2.go(INS_ITEM, (uuid.uuid4(), x))
    t1.go(DEL_ITEMS, (x,))
    t1.go(DEL_ORDER, (x,))
    t2.go("COMMIT")
    t1.go("COMMIT")
    final(a, x)
    t1.close()
    t2.close()
    tally.add(label, t1, t2)


def case_c(a, begin, tally, label, load):
    """T1 takes its snapshot; T2 inserts and commits; then T1 deletes."""
    x, _ = new_order(a, 2)
    t1, t2 = Sess("T1"), Sess("T2")
    t1.go(begin)
    if load:
        t1.go(LOAD_O, (x,))
        t1.go(LOAD_I, (x,))
    else:
        t1.go("SELECT 1")
    t2.go(begin)
    t2.go(INS_ITEM, (uuid.uuid4(), x))
    t2.go("COMMIT")
    t1.go(DEL_ITEMS, (x,))
    t1.go(DEL_ORDER, (x,))
    t1.go("COMMIT")
    final(a, x)
    t1.close()
    t2.close()
    tally.add(label, t1, t2)


def main():
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    levels = sys.argv[2:] or ["SERIALIZABLE", "REPEATABLE READ"]
    tally = Tally()
    with temp_database("q1"):
        a = admin()
        schema(a, orders=1000, items_per=3)
        for iso in levels:
            begin = f"BEGIN ISOLATION LEVEL {iso}"
            for n in range(repeat):
                cases = [
                    ("(a) T1 deletes first, T2 inserts", case_a, ()),
                    ("(b) T2 inserts first, T1 loaded", case_b, (True,)),
                    ("(b') T2 inserts first, T1 no load", case_b, (False,)),
                    ("(c) T1 loads, T2 insert+commit", case_c, (True,)),
                    ("(c') T1 SELECT 1, T2 insert+commit", case_c, (False,)),
                ]
                for name, fn, extra in cases:
                    label = f"{iso} {name}"
                    print(f"=== {label}; run {n + 1}")
                    fn(a, begin, tally, label, *extra)
        a.close()
    tally.print()


if __name__ == "__main__":
    main()
