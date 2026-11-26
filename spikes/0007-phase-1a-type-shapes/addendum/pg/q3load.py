"""F3/Q3 load: 40001 rate of 'create an order with 3 items' vs 'delete an empty order', with the
zero-row child DELETE ('with'), without it ('without'), or with a SELECT 1 in its place ('pad',
same number of round trips). 8 workers (4 creators, 4 deleters), SERIALIZABLE, one statement per
round trip (not pipelined). 10k orders x 3 items + 30k empty orders, VACUUM ANALYZE, per run.
The fast profile shortens commits and so understates rates: compare variants, not absolute rates.
Usage: q3load.py [RUNS] [SECONDS] [KEYS] [VARIANTS]   (default 3 6 uuid4,uuid7 with,without,pad)
"""

import collections
import sys
import threading
import time
import uuid

import common
import psycopg
from common import admin, schema, temp_database

WORKERS = 8


def run(a, variant, keygen, seconds):
    schema(a, alloc=False, orders=10000, items_per=3, analyze=False, keygen=keygen)
    empties = [keygen() for _ in range(30000)]
    with a.cursor() as cur, cur.copy("COPY orders(id, version) FROM STDIN") as cp:
        for o in empties:
            cp.write_row((o, 1))
    a.execute("VACUUM ANALYZE orders")
    a.execute("VACUUM ANALYZE items")
    pools = [empties[i :: WORKERS // 2] for i in range(WORKERS // 2)]
    stats: collections.Counter[str] = collections.Counter()
    lock = threading.Lock()
    stop = threading.Event()

    def worker(role, pool):
        c = psycopg.connect(common.DSN)
        c.isolation_level = psycopg.IsolationLevel.SERIALIZABLE
        local: collections.Counter[str] = collections.Counter()
        while not stop.is_set():
            if role == "delete" and not pool:
                local["delete_pool_exhausted"] += 1
                break
            try:
                if role == "create":
                    o = keygen()
                    c.execute("INSERT INTO orders VALUES (%s, 1)", (o,))
                    for _ in range(3):
                        c.execute("INSERT INTO items VALUES (%s, %s, 1)", (keygen(), o))
                else:
                    o = pool[-1]
                    if variant == "with":
                        c.execute("DELETE FROM items WHERE order_id = %s", (o,))
                    elif variant == "pad":
                        c.execute("SELECT 1")
                    cur = c.execute("DELETE FROM orders WHERE id = %s AND version = 1", (o,))
                    if cur.rowcount != 1:
                        raise RuntimeError(f"expected 1 deleted order, got {cur.rowcount}")
                c.commit()
                local[f"{role}_ok"] += 1
                if role == "delete":
                    pool.pop()
            except psycopg.errors.SerializationFailure:
                c.rollback()
                local[f"{role}_40001"] += 1
            except psycopg.Error as e:
                c.rollback()
                local[f"{role}_other_{e.sqlstate}"] += 1
        c.close()
        with lock:
            stats.update(local)

    threads = [
        threading.Thread(
            target=worker,
            args=("create", None) if i % 2 == 0 else ("delete", pools[i // 2]),
        )
        for i in range(WORKERS)
    ]
    for t in threads:
        t.start()
    time.sleep(seconds)
    stop.set()
    for t in threads:
        t.join()
    return stats


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
    keys = (sys.argv[3] if len(sys.argv) > 3 else "uuid4,uuid7").split(",")
    variants = (sys.argv[4] if len(sys.argv) > 4 else "with,without,pad").split(",")
    agg = collections.defaultdict(list)
    with temp_database("q3load"):
        a = admin()
        for n in range(runs):
            for key in keys:
                for variant in variants:
                    s = run(a, variant, getattr(uuid, key), seconds)
                    agg[(key, variant)].append(s)
                    print(f"run {n + 1} {key} {variant:7} {dict(s)}", flush=True)
        a.close()
    print("\n## summary: 40001 / attempts (attempts = ok + failures), per run and total")
    for (key, variant), rs in agg.items():
        for role in ("create", "delete"):
            per = []
            for s in rs:
                att = sum(v for k, v in s.items() if k.startswith(role) and "exhausted" not in k)
                per.append(f"{s[f'{role}_40001']}/{att}")
            tot_att = sum(
                v for s in rs for k, v in s.items() if k.startswith(role) and "exhausted" not in k
            )
            tot_f = sum(s[f"{role}_40001"] for s in rs)
            other = sum(v for s in rs for k, v in s.items() if k.startswith(f"{role}_other"))
            print(
                f"{key} {variant:7} {role}: runs {' '.join(per)} | total {tot_f}/{tot_att} = "
                f"{100 * tot_f / max(tot_att, 1):.3f}% | other errors {other}"
            )


if __name__ == "__main__":
    main()
