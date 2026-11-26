"""N2: a child INSERT racing the cascade delete, with the writer written the way Platina writes it.

Writer T2 ('bump'): BEGIN; load (order + items); INSERT INTO items ...; UPDATE orders SET version =
version + 1 WHERE id = X; COMMIT. ('plain': the same without the UPDATE - coexisting code.)
Deleter T1: BEGIN; load (order + items); then either
  separate: DELETE FROM items WHERE order_id = X; DELETE FROM orders WHERE id = X AND version = 1
  cte:      WITH c1 AS (DELETE FROM items WHERE order_id = ANY($1)) DELETE FROM orders WHERE id = ANY($1)
COMMIT. Interleavings (statements of one side in order; '|' separates sessions' turns):
  A   T1 deletes first (uncommitted), T2 inserts (blocks); T1 COMMIT; T2 [bumps,] COMMIT
  A2  (separate only) T1 child DELETE | T2 insert [+bump] | T1 root DELETE; T2 COMMIT, T1 COMMIT
  B   T2 inserts [+bumps] first (uncommitted), T1 deletes; T2 COMMIT, T1 COMMIT
  B2  (bump only) T2 inserts | T1 deletes | T2 bumps; T2 COMMIT, T1 COMMIT
  C   T2 inserts [+bumps] and commits after T1's load; then T1 deletes and commits
  E   T1 deletes and commits after T2's load; then T2 inserts [+bumps] and commits
Usage: n2_race.py [REPEAT]   (default 3)
"""

import sys
import uuid

from common import Sess, Tally, admin, new_order, schema, temp_database

SER, RR, RC = "SERIALIZABLE", "REPEATABLE READ", "READ COMMITTED"
# (deleter isolation, writer isolation, writer mode)
CONFIGS = [
    (SER, SER, "bump"),
    (RR, RR, "bump"),
    (SER, SER, "plain"),
    (RR, RR, "plain"),
    (SER, RC, "plain"),
    (SER, RC, "bump"),
]
LOAD_O = "SELECT version FROM orders WHERE id = %s"
LOAD_I = "SELECT count(*) FROM items WHERE order_id = %s"
DEL_ITEMS = "DELETE FROM items WHERE order_id = %s"
DEL_ORDER = "DELETE FROM orders WHERE id = %s AND version = 1"
CTE = (
    "WITH c1 AS (DELETE FROM items WHERE order_id = ANY(%s)) DELETE FROM orders WHERE id = ANY(%s)"
)
INS = "INSERT INTO items VALUES (%s, %s, 1)"
BUMP = "UPDATE orders SET version = version + 1 WHERE id = %s"


def scenario(a, cfg, form, inter):
    d_iso, w_iso, mode = cfg
    x, _ = new_order(a, 2)
    t1, t2 = Sess("T1 deleter"), Sess("T2 writer")
    d_load = [(t1, LOAD_O, (x,)), (t1, LOAD_I, (x,))]
    w_load = [(t2, LOAD_O, (x,)), (t2, LOAD_I, (x,))]
    if form == "separate":
        d_child, d_root = [(t1, DEL_ITEMS, (x,))], [(t1, DEL_ORDER, (x,))]
    else:
        d_child, d_root = [], [(t1, CTE, ([x], [x]))]
    w_ins = [(t2, INS, (uuid.uuid4(), x))]
    w_bump = [(t2, BUMP, (x,))] if mode == "bump" else []
    b1 = [(t1, f"BEGIN ISOLATION LEVEL {d_iso}", None)]
    b2 = [(t2, f"BEGIN ISOLATION LEVEL {w_iso}", None)]
    c1, c2 = [(t1, "COMMIT", None)], [(t2, "COMMIT", None)]
    steps = {
        "A": b1 + b2 + d_load + w_load + d_child + d_root + w_ins + c1 + w_bump + c2,
        "A2": b1 + b2 + d_load + w_load + d_child + w_ins + w_bump + d_root + c2 + c1,
        "B": b1 + b2 + d_load + w_load + w_ins + w_bump + d_child + d_root + c2 + c1,
        "B2": b1 + b2 + d_load + w_load + w_ins + d_child + d_root + w_bump + c2 + c1,
        "C": b1 + b2 + d_load + w_load + w_ins + w_bump + c2 + d_child + d_root + c1,
        "E": b2 + b1 + w_load + d_load + d_child + d_root + c1 + w_ins + w_bump + c2,
    }[inter]
    for sess, stmt, params in steps:
        sess.go(stmt, params)
        for other in (t1, t2):
            if other is not sess:
                other.poll()
    t1.close()
    t2.close()
    o = a.execute("SELECT version FROM orders WHERE id = %s", (x,)).fetchall()
    i = a.execute("SELECT count(*) FROM items WHERE order_id = %s", (x,)).fetchone()[0]
    print(f"  final: orders(X) {o} items(X) {i}")
    return t1, t2


def main():
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    tally = Tally()
    with temp_database("n2"):
        a = admin()
        schema(a, alloc=False, orders=1000, items_per=3)
        for cfg in CONFIGS:
            d_iso, w_iso, mode = cfg
            for form in ("separate", "cte"):
                for inter in ("A", "A2", "B", "B2", "C", "E"):
                    if inter == "A2" and form != "separate":
                        continue
                    if inter == "B2" and mode != "bump":
                        continue
                    label = f"deleter {d_iso} {form} | writer {w_iso} {mode} | {inter}"
                    for n in range(repeat):
                        print(f"=== {label}; run {n + 1}")
                        tally.add(label, *scenario(a, cfg, form, inter))
        a.close()
    tally.print()


if __name__ == "__main__":
    main()
