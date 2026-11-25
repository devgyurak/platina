"""Section D of spike 0003: SERIALIZABLE vs REPEATABLE READ + version (durable profile).

  uv run python spikes/0003-ssi-internal-tables/bench.py --port 26433

Raw per-run records go to results/bench.jsonl; a line per run is printed.
"""

from __future__ import annotations

import argparse
import random
import time
from datetime import UTC, datetime
from typing import Any

import common
import harness
import psycopg
from harness import Stmt

N_ORDERS = 100_000
N_USERS = 10_000  # users = wallets = pocket owners
N_ACCOUNTS = 10_000
N_PRODUCTS = 1_000
START_BALANCE = 1_000_000
POCKET_START = 100
ZIPF_S = 1.1
LEVELS = ("SERIALIZABLE", "REPEATABLE READ")
MIX = (("pay", 0.30), ("create", 0.25), ("transfer", 0.20), ("pocket", 0.20), ("reprice", 0.05))


class Picker:
    """Uniform, or Zipf over a fixed random permutation (hot rows are spread over the key space;
    the same permutation in every worker)."""

    def __init__(self, n: int, dist: str, rng: random.Random) -> None:
        self.n = n
        self.rng = rng
        self.zipf = common.Zipf(n, ZIPF_S, rng) if dist == "zipf" else None
        perm = list(range(n))
        random.Random(42 + n).shuffle(perm)
        self.perm = perm

    def pick(self) -> int:
        if self.zipf is None:
            return self.rng.randrange(self.n)
        return self.perm[self.zipf.sample()]


def load_data(port: int) -> None:
    common.reset(port, fillfactor=100)  # default fill factor: realistic HOT behaviour
    with common.connect(port) as conn:
        common.load_orders(conn, "orders", N_ORDERS, users=N_USERS)
        conn.execute(
            "INSERT INTO wallets SELECT g, %s, 1 FROM generate_series(1, %s) g",
            (START_BALANCE, N_USERS),
        )
        conn.execute(
            "INSERT INTO accounts SELECT g, %s, 1 FROM generate_series(1, %s) g",
            (START_BALANCE, N_ACCOUNTS),
        )
        conn.execute(
            "INSERT INTO products SELECT g, 1 + g %% 50 FROM generate_series(1, %s) g",
            (N_PRODUCTS,),
        )
        conn.execute(
            "INSERT INTO pockets SELECT u, k, %s FROM generate_series(1, %s) u, "
            "generate_series(0, 1) k",
            (POCKET_START, N_USERS),
        )
        conn.execute("VACUUM ANALYZE")
        conn.execute("CHECKPOINT")


TAIL: list[Stmt] = [
    ("INSERT INTO outbox_log(payload) VALUES ('{\"e\": 1}')", ()),
    ("SELECT pg_current_xact_id()::text", ()),
    ("COMMIT", ()),
    ("SELECT pg_current_wal_insert_lsn()::text", ()),
]


def worker(
    cfg: dict[str, Any], w: int, _n: int, barrier: Any, warmup: float, duration: float
) -> dict[str, Any]:
    conn = common.connect(cfg["port"])
    rng = random.Random(5000 + w + 104729 * cfg["rep"])
    orders = [r[0] for r in conn.execute("SELECT id FROM orders ORDER BY id").fetchall()]
    p_order = Picker(N_ORDERS, cfg["dist"], rng)
    p_user = Picker(N_USERS, cfg["dist"], rng)
    p_account = Picker(N_ACCOUNTS, cfg["dist"], rng)
    p_product = Picker(N_PRODUCTS, cfg["dist"], rng)
    begin = f"BEGIN ISOLATION LEVEL {cfg['iso']}"
    conn.execute(begin)  # type: ignore[arg-type]
    iso_row = conn.execute("SELECT current_setting('transaction_isolation')").fetchone()
    conn.execute("ROLLBACK")
    cmd: dict[str, Any] = {}
    per_type: dict[str, harness.Stats] = {k: harness.Stats() for k, _ in MIX}
    per_type["pay"].extra["iso=" + str(iso_row and iso_row[0])] += 1

    def head(*loads: Stmt) -> list[Stmt]:
        return [
            (begin, ()),
            ("SET LOCAL statement_timeout = '2s'", ()),
            ("INSERT INTO run_claim(id) VALUES (%s)", (cmd["rid"],)),
            *loads,
        ]

    def versioned(kind: str, res: list[Any], n: int) -> None:
        # The version predicate sits in the same transaction as the read, so under both
        # levels a concurrent update raises 40001 first; a 0-row match would be committed.
        if any(rc == 0 for rc in res[:n]):
            per_type[kind].extra["version_mismatch_committed"] += 1

    def pay(c: psycopg.Connection[Any], _a: int) -> None:
        o, u = cmd["o"], cmd["u"]
        r = harness.round_trip(
            c,
            head(
                ("SELECT total, version FROM orders WHERE id = %s", (o,)),
                ("SELECT balance, version FROM wallets WHERE id = %s", (u,)),
            ),
        )
        (total, ov), (balance, wv) = r[3][0], r[4][0]
        if balance < total:
            raise harness.Dropped("insufficient_balance")
        res = harness.round_trip(
            c,
            [
                (
                    "UPDATE orders SET status = 'PAID', version = version + 1 "
                    "WHERE id = %s AND version = %s",
                    (o, ov),
                ),
                (
                    "UPDATE wallets SET balance = balance - %s, version = version + 1 "
                    "WHERE id = %s AND version = %s",
                    (total, u, wv),
                ),
                (
                    "INSERT INTO payments(id, order_id, amount) VALUES (%s, %s, %s)",
                    (common.uuid7(), o, total),
                ),
                *TAIL,
            ],
        )
        versioned("pay", res, 2)

    def create(c: psycopg.Connection[Any], _a: int) -> None:
        prods, u = cmd["p"], cmd["u"]
        r = harness.round_trip(
            c,
            head(
                ("SELECT id, price FROM products WHERE id = ANY(%s)", (prods,)),
                # range read: the user's last orders (e.g. for a loyalty rule)
                (
                    "SELECT id, total FROM orders WHERE user_id = %s ORDER BY id DESC LIMIT 5",
                    (u,),
                ),
            ),
        )
        prices = dict(r[3])
        oid = common.uuid7()
        items: list[Stmt] = [
            (
                "INSERT INTO order_items(id, order_id, product_id, qty, price) "
                "VALUES (%s, %s, %s, 1, %s)",
                (common.uuid7(), oid, pid, prices[pid]),
            )
            for pid in prods
        ]
        harness.round_trip(
            c,
            [
                (
                    "INSERT INTO orders VALUES (%s, %s, %s, 'PENDING', %s, 1)",
                    (oid, u, cmd["store"], sum(prices.values())),
                ),
                *items,
                *TAIL,
            ],
        )

    def transfer(c: psycopg.Connection[Any], _a: int) -> None:
        a, b, amount = cmd["a"], cmd["b"], cmd["amount"]
        r = harness.round_trip(
            c,
            head(("SELECT id, balance, version FROM accounts WHERE id = ANY(%s)", ([a, b],))),
        )
        acc = {i: (bal, v) for i, bal, v in r[3]}
        if acc[a][0] < amount:
            raise harness.Dropped("insufficient_balance")
        delta = {a: -amount, b: amount}
        upd: list[Stmt] = [
            (
                "UPDATE accounts SET balance = balance + %s, version = version + 1 "
                "WHERE id = %s AND version = %s",
                (delta[i], i, acc[i][1]),
            )
            for i in sorted((a, b))
        ]
        res = harness.round_trip(
            c,
            [
                *upd,
                (
                    "INSERT INTO ledger(id, from_id, to_id, amount) VALUES (%s, %s, %s, %s)",
                    (common.uuid7(), a, b, amount),
                ),
                *TAIL,
            ],
        )
        versioned("transfer", res, 2)

    def pocket(c: psycopg.Connection[Any], _a: int) -> None:
        """Withdraw from one pocket if the sum of both covers it, or deposit. The rule is over
        the read set (both rows) while only one row is written: the write-skew shape."""
        u, k, amount, withdraw = cmd["u"], cmd["k"], cmd["amount"], cmd["withdraw"]
        r = harness.round_trip(
            c, head(("SELECT kind, balance FROM pockets WHERE user_id = %s", (u,)))
        )
        total = sum(bal for _, bal in r[3])
        if withdraw and total < amount:
            raise harness.Dropped("insufficient_pockets")
        sign = -1 if withdraw else 1
        harness.round_trip(
            c,
            [
                (
                    "UPDATE pockets SET balance = balance + %s WHERE user_id = %s AND kind = %s",
                    (sign * amount, u, k),
                ),
                *TAIL,
            ],
        )

    def reprice(c: psycopg.Connection[Any], _a: int) -> None:
        p = cmd["p1"]
        harness.round_trip(c, head(("SELECT price FROM products WHERE id = %s", (p,))))
        harness.round_trip(
            c, [("UPDATE products SET price = price + 1 WHERE id = %s", (p,)), *TAIL]
        )

    fns = {"pay": pay, "create": create, "transfer": transfer, "pocket": pocket, "reprice": reprice}

    def choose() -> str:
        x = rng.random()
        for kind, weight in MIX:
            if x < weight:
                return kind
            x -= weight
        return MIX[-1][0]

    barrier.wait()
    measure_from = time.perf_counter() + warmup
    deadline = measure_from + duration
    while (now := time.perf_counter()) < deadline:
        kind = choose()
        cmd.clear()
        cmd["rid"] = common.uuid7()  # reused by every retry of this command
        if kind == "pay":
            cmd["o"] = orders[p_order.pick()]
            cmd["u"] = 1 + p_user.pick()
        elif kind == "create":
            ps: set[int] = set()
            while len(ps) < 3:
                ps.add(1 + p_product.pick())
            cmd["p"] = sorted(ps)
            cmd["u"] = 1 + p_user.pick()
            cmd["store"] = rng.randrange(1000)
        elif kind == "transfer":
            a = 1 + p_account.pick()
            b = a
            while b == a:
                b = 1 + p_account.pick()
            cmd["a"], cmd["b"], cmd["amount"] = a, b, rng.randrange(1, 101)
        elif kind == "pocket":
            cmd["u"] = 1 + p_user.pick()
            cmd["k"] = rng.randrange(2)
            cmd["withdraw"] = rng.random() < 0.6
            cmd["amount"] = rng.randrange(1, 61) if cmd["withdraw"] else rng.randrange(1, 41)
        else:
            cmd["p1"] = 1 + p_product.pick()
        harness.run_command(
            conn, fns[kind], per_type[kind], rng, max_attempts=4, record=now >= measure_from
        )
    conn.close()
    return {k: v.to_dict() for k, v in per_type.items()}


def summarize(m: dict[str, Any], dur: float) -> dict[str, Any]:
    lat = m["latencies"]
    e40001 = m["errors"].get(common.SERIALIZATION_FAILURE, 0)
    return {
        "tps": m["commits"] / dur,
        "commits": m["commits"],
        "commands": m["commands"],
        "attempts_per_commit": m["attempts"] / m["commits"] if m["commits"] else None,
        "rate_40001_per_attempt": e40001 / m["attempts"] if m["attempts"] else None,
        "p50_ms": common.percentile(lat, 50) * 1000,
        "p99_ms": common.percentile(lat, 99) * 1000,
        "errors": m["errors"],
        "exhausted": m["exhausted"],
        "dropped": m["dropped"],
        "extra": m["extra"],
    }


def run_one(
    port: int, rep: int, workers: int, dist: str, iso: str, warmup: float, dur: float
) -> dict[str, Any]:
    load_data(port)
    cfg = {"port": port, "rep": rep, "dist": dist, "iso": iso}
    parts = harness.run_workers(worker, cfg, workers, warmup=warmup, duration=dur)
    by_type = {k: harness.merge([p[k] for p in parts]) for k, _ in MIX}
    total = harness.merge([p[k] for p in parts for k, _ in MIX])
    time.sleep(1.0)  # let the backends' statistics reach the shared stats
    with common.connect(port) as conn:
        acc = conn.execute("SELECT sum(balance) FROM accounts").fetchone()
        pk = conn.execute(
            "SELECT count(*) FILTER (WHERE s < 0), min(s) "
            "FROM (SELECT sum(balance) s FROM pockets GROUP BY user_id) t"
        ).fetchone()
        hot = common.hot_stats(conn)
    assert acc is not None
    assert pk is not None
    rec = {
        "rep": rep,
        "workers": workers,
        "dist": dist,
        "iso": iso,
        "duration_s": dur,
        **summarize(total, dur),
        "transfer_invariant_ok": acc[0] == START_BALANCE * N_ACCOUNTS,
        "pocket_users_negative": pk[0],
        "pocket_min_sum": str(pk[1]),
        "hot": hot,
        "error_detail": total["error_detail"],
        "attempts_hist": total["attempts_hist"],
        "by_type": {k: summarize(v, dur) for k, v in by_type.items()},
    }
    return rec


def show(rec: dict[str, Any]) -> None:
    print(
        f"rep={rec['rep']} w={rec['workers']:<2} {rec['dist']:<7} {rec['iso']:<15} tps={rec['tps']:8.1f} "
        f"att/commit={rec['attempts_per_commit']:.3f} "
        f"40001/att={rec['rate_40001_per_attempt']:.4f} "
        f"p50={rec['p50_ms']:.1f}ms p99={rec['p99_ms']:.1f}ms errors={rec['errors']} "
        f"exhausted={rec['exhausted']} transfer_ok={rec['transfer_invariant_ok']} "
        f"pocket_neg={rec['pocket_users_negative']} extra={rec['extra']}",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--workers", type=int, nargs="*", default=[8, 32, 64])
    ap.add_argument("--dists", nargs="*", default=["uniform", "zipf"])
    ap.add_argument("--duration", type=float, default=20)
    ap.add_argument("--warmup", type=float, default=3)
    a = ap.parse_args()
    print(f"# bench.py {datetime.now(UTC).isoformat()} {vars(a)}", flush=True)
    block = 0
    for rep in range(1, a.reps + 1):
        for workers in a.workers:
            for dist in a.dists:
                # ABBA: consecutive blocks alternate which level runs first
                order = LEVELS if block % 2 == 0 else LEVELS[::-1]
                for pair_try in range(1, 6):
                    before = harness.wait_quiet()
                    with harness.HostMonitor() as mon:
                        recs = [
                            run_one(a.port, rep, workers, dist, iso, a.warmup, a.duration)
                            for iso in order
                        ]
                    during = mon.summary()
                    quiet = during["quiet"]
                    for rec in recs:
                        rec["host"] = {"before": before, "during": during, "quiet": quiet}
                        rec["block"], rec["pair_order"], rec["pair_try"] = block, order[0], pair_try
                        common.write_jsonl(
                            "bench.jsonl" if quiet else "bench_discarded.jsonl", [rec]
                        )
                        show(rec)
                    print(
                        f"# block={block} before={before} during={during} kept={quiet}", flush=True
                    )
                    if quiet:
                        break
                else:
                    raise RuntimeError(f"block {block}: no quiet pair in 5 tries")
                block += 1


if __name__ == "__main__":
    main()
