"""F3/Q3 pinned: does the zero-row child DELETE (or the root DELETE's FK check) make unrelated
commands fail? uuid4 keys; B is the existing order whose items follow A's key in items_order_id,
C is a new order key adjacent to B in orders_pkey (leaf pages checked with pageinspect).

S1 (two sessions): T1 deletes empty order A; T2 adds an item to order B; commit T2, T1.
S2 (three sessions): T1 deletes A [with child DELETE | root DELETE only | absent];
T2 adds an item to B; T3 inserts order C; commit T3, T2, T1.
Usage: q3pin.py [REPEAT]   (default 3)
"""

import sys
import uuid

from common import Sess, Tally, admin, new_order, schema, sireadlocks, temp_database

BEGIN = "BEGIN ISOLATION LEVEL SERIALIZABLE"


def leaf_of(a, index, key):
    """Leaf page numbers of `index` that contain uuid `key`."""
    n = a.execute("SELECT relpages FROM pg_class WHERE relname = %s", (index,)).fetchone()[0]
    hexkey = " ".join(f"{b:02x}" for b in key.bytes)
    pages = []
    for p in range(1, n):
        if a.execute("SELECT type FROM bt_page_stats(%s, %s)", (index, p)).fetchone()[0] != "l":
            continue
        hit = a.execute(
            "SELECT 1 FROM bt_page_items(%s, %s) WHERE data = %s LIMIT 1", (index, p, hexkey)
        ).fetchone()
        if hit:
            pages.append(p)
    return pages


def fresh(a):
    """A new empty order A with an existing order B after it in items_order_id."""
    while True:
        x, _ = new_order(a, 0)
        row = a.execute(
            "SELECT order_id FROM items WHERE order_id > %s ORDER BY order_id LIMIT 1", (x,)
        ).fetchone()
        if row:
            b = row[0]
            return x, b, uuid.UUID(int=b.int + 1)


def t1_delete(t1, x, child):
    if child:
        t1.go("DELETE FROM items WHERE order_id = %s", (x,))
    t1.go("DELETE FROM orders WHERE id = %s AND version = 1", (x,))


def two_sessions(a, tally, cfg):
    x, b, _ = fresh(a)
    label = f"{cfg} S1 two sessions"
    print(f"--- {label}: A={x} B={b} leaf(items_order_id, B)={leaf_of(a, 'items_order_id', b)}")
    t1, t2 = Sess("T1"), Sess("T2")
    t1.go(BEGIN)
    t2.go(BEGIN)
    t1_delete(t1, x, True)
    t2.go("INSERT INTO items VALUES (%s, %s, 1)", (uuid.uuid4(), b))
    print(f"    T1 SIRead {sireadlocks(t1.pid)}; T2 SIRead {sireadlocks(t2.pid)}")
    t2.go("COMMIT")
    t1.go("COMMIT")
    t1.close()
    t2.close()
    tally.add(label, t1, t2)


def three_sessions(a, tally, cfg, t1_mode):
    x, b, c = fresh(a)
    label = f"{cfg} S2 three sessions, T1 {t1_mode}"
    print(f"--- {label}: A={x} B={b} C={c}")
    t2, t3 = Sess("T2"), Sess("T3")
    t1 = Sess("T1") if t1_mode != "absent" else None
    if t1:
        t1.go(BEGIN)
    t2.go(BEGIN)
    t3.go(BEGIN)
    if t1:
        t1_delete(t1, x, t1_mode == "with child DELETE")
    t2.go("INSERT INTO items VALUES (%s, %s, 1)", (uuid.uuid4(), b))
    t3.go("INSERT INTO orders VALUES (%s, 1)", (c,))
    print(
        f"    leaf(orders_pkey, B)={leaf_of(a, 'orders_pkey', b)} "
        f"leaf(orders_pkey, C)={leaf_of(a, 'orders_pkey', c)} T2 SIRead {sireadlocks(t2.pid)}"
    )
    t3.go("COMMIT")
    t2.go("COMMIT")
    sessions = [t2, t3]
    if t1:
        t1.go("COMMIT")
        sessions.insert(0, t1)
    for s in sessions:
        s.close()
    a.execute("DELETE FROM orders WHERE id = %s", (c,))
    tally.add(label, *sessions)


def main():
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    tally = Tally()
    with temp_database("q3pin"):
        a = admin()
        a.execute("CREATE EXTENSION IF NOT EXISTS pageinspect")
        for cfg, kw in [
            ("10k orders analyzed", {"orders": 10000, "items_per": 3}),
            ("30 orders analyzed", {"orders": 30, "items_per": 3}),
        ]:
            print(f"===== {cfg} x3 items, index, uuid4")
            schema(a, alloc=False, **kw)
            for n in range(repeat):
                print(f"  run {n + 1}")
                two_sessions(a, tally, cfg)
                for mode in ("with child DELETE", "root DELETE only", "absent"):
                    three_sessions(a, tally, cfg, mode)
        a.close()
    tally.print()


if __name__ == "__main__":
    main()
