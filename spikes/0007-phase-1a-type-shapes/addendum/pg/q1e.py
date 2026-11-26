"""F1/Q1 (e): the child INSERT after the cascade delete committed - writer snapshot before/after.

Usage: q1e.py [REPEAT] [ISOLATION ...]   (default: 3 SERIALIZABLE "REPEATABLE READ")
"""

import sys
import uuid

from common import Sess, Tally, admin, new_order, schema, temp_database


def case(a, begin, tally, label, t2_first):
    x, _ = new_order(a, 2)
    t1, t2 = Sess("T1"), Sess("T2")
    t2.go(begin)
    if t2_first == "load":
        t2.go("SELECT version FROM orders WHERE id = %s", (x,))
    elif t2_first == "select1":
        t2.go("SELECT 1")
    t1.go(begin)
    t1.go("DELETE FROM items WHERE order_id = %s", (x,))
    t1.go("DELETE FROM orders WHERE id = %s AND version = 1", (x,))
    t1.go("COMMIT")
    t2.go("INSERT INTO items VALUES (%s, %s, 1)", (uuid.uuid4(), x))
    t2.go("COMMIT")
    t1.close()
    t2.close()
    tally.add(label, t1, t2)


def main():
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    levels = sys.argv[2:] or ["SERIALIZABLE", "REPEATABLE READ"]
    tally = Tally()
    with temp_database("q1e"):
        a = admin()
        schema(a, orders=1000, items_per=3)
        for iso in levels:
            begin = f"BEGIN ISOLATION LEVEL {iso}"
            for n in range(repeat):
                for first, name in [
                    ("load", "(e) T2 loaded X, T1 delete+commit, T2 inserts"),
                    ("select1", "(e') T2 SELECT 1, T1 delete+commit, T2 inserts"),
                    ("none", "(e'') T2's first statement is the INSERT after T1's commit"),
                ]:
                    label = f"{iso} {name}"
                    print(f"=== {label}; run {n + 1}")
                    case(a, begin, tally, label, first)
        a.close()
    tally.print()


if __name__ == "__main__":
    main()
