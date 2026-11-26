"""F4/Q4 in pipeline mode: the versioned root DELETE matches 0 rows and COMMIT is queued in the
same pipeline - the child DELETEs commit and the root stays.
Usage: q4pipe.py [REPEAT]   (default 3)
"""

import sys

import common
import psycopg
from common import admin, new_order, schema, temp_database


def main():
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    with temp_database("q4pipe"):
        a = admin()
        schema(a, alloc=False, orders=1000, items_per=3)
        for n in range(repeat):
            x, _ = new_order(a, 2)
            a.execute("UPDATE orders SET version = 2 WHERE id = %s", (x,))
            c = psycopg.connect(common.DSN)
            c.isolation_level = psycopg.IsolationLevel.SERIALIZABLE
            with c.pipeline():
                ci = c.execute("DELETE FROM items WHERE order_id = %s", (x,))
                co = c.execute("DELETE FROM orders WHERE id = %s AND version = 1", (x,))
                c.commit()
            o = a.execute("SELECT count(*) FROM orders WHERE id = %s", (x,)).fetchone()[0]
            i = a.execute("SELECT count(*) FROM items WHERE order_id = %s", (x,)).fetchone()[0]
            print(
                f"run {n + 1}: items cursor rowcount={ci.rowcount} ({ci.statusmessage!r}); "
                f"orders cursor rowcount={co.rowcount} ({co.statusmessage!r}); transaction "
                f"{c.info.transaction_status.name}; committed: orders(X)={o} items(X)={i}"
            )
            c.close()
        a.close()


if __name__ == "__main__":
    main()
