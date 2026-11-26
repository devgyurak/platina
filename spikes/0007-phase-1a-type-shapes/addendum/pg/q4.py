"""F4/Q4: a versioned root DELETE that matches zero rows; a concurrent committed UPDATE of the root.

All SERIALIZABLE; T1 = cascade DELETE (items, then orders ... AND version = 1).
(i) stale version, no concurrency; (ii) T1 loads v1, T2 bumps and commits, T1 deletes;
(iii) T2 bumps uncommitted, T1 loads and deletes (blocks), T2 commits;
(iv) T2 bumps and commits before T1's first statement, T1 deletes with version 1 (no load).
Usage: q4.py [REPEAT]   (default 3)
"""

import sys

from common import Sess, Tally, admin, new_order, schema, temp_database

BEGIN = "BEGIN ISOLATION LEVEL SERIALIZABLE"
DEL_ITEMS = "DELETE FROM items WHERE order_id = %s"
DEL = "DELETE FROM orders WHERE id = %s AND version = %s"
UPD = "UPDATE orders SET version = version + 1 WHERE id = %s"
LOAD = "SELECT version FROM orders WHERE id = %s"


def final(a, x):
    v = a.execute("SELECT version FROM orders WHERE id = %s", (x,)).fetchall()
    i = a.execute("SELECT count(*) FROM items WHERE order_id = %s", (x,)).fetchone()[0]
    print(f"  final: orders(X) version {v}, items(X) {i}")


def main():
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    tally = Tally()
    with temp_database("q4"):
        a = admin()
        schema(a, alloc=False, orders=1000, items_per=3)
        for n in range(repeat):
            label = "(i) stale version, no concurrency"
            print(f"=== {label}; run {n + 1}")
            x, _ = new_order(a, 2)
            a.execute(UPD, (x,))
            t1 = Sess("T1")
            for s, p in [(BEGIN, None), (DEL_ITEMS, (x,)), (DEL, (x, 1)), ("COMMIT", None)]:
                t1.go(s, p)
            t1.close()
            final(a, x)
            tally.add(label, t1)

            label = "(ii) T1 loads v1, T2 bump+commit, T1 deletes"
            print(f"=== {label}; run {n + 1}")
            x, _ = new_order(a, 2)
            t1, t2 = Sess("T1"), Sess("T2")
            t1.go(BEGIN)
            t1.go(LOAD, (x,))
            t2.go(BEGIN)
            t2.go(UPD, (x,))
            t2.go("COMMIT")
            t1.go(DEL_ITEMS, (x,))
            t1.go(DEL, (x, 1))
            t1.go("COMMIT")
            t1.close()
            t2.close()
            final(a, x)
            tally.add(label, t1, t2)

            label = "(iii) T2 bump uncommitted, T1 loads+deletes, T2 commits"
            print(f"=== {label}; run {n + 1}")
            x, _ = new_order(a, 2)
            t1, t2 = Sess("T1"), Sess("T2")
            t1.go(BEGIN)
            t1.go(LOAD, (x,))
            t2.go(BEGIN)
            t2.go(UPD, (x,))
            t1.go(DEL_ITEMS, (x,))
            t1.go(DEL, (x, 1))
            t2.go("COMMIT")
            t1.go("COMMIT")
            t1.close()
            t2.close()
            final(a, x)
            tally.add(label, t1, t2)

            label = "(iv) T2 bump+commit before T1's first statement, T1 deletes v1"
            print(f"=== {label}; run {n + 1}")
            x, _ = new_order(a, 2)
            t1, t2 = Sess("T1"), Sess("T2")
            t1.go(BEGIN)
            t2.go(BEGIN)
            t2.go(UPD, (x,))
            t2.go("COMMIT")
            t1.go(DEL_ITEMS, (x,))
            t1.go(DEL, (x, 1))
            t1.go("COMMIT")
            t1.close()
            t2.close()
            final(a, x)
            tally.add(label, t1, t2)
        a.close()
    tally.print()


if __name__ == "__main__":
    main()
