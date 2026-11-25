"""Load harness of spike 0003.

  exist  (section B, fast profile)    uv run python spikes/0003-ssi-internal-tables/load.py exist --port 26432
  rates  (section C, durable profile) uv run python spikes/0003-ssi-internal-tables/load.py rates --port 26433

Raw per-run records go to results/load_<mode>.jsonl; a summary table is printed.
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import common
import harness
import psycopg
from harness import Stmt

ISO = "BEGIN ISOLATION LEVEL SERIALIZABLE"
CLAIM = "INSERT INTO run_claim(id) VALUES (%s)"
OUTBOX = "INSERT INTO outbox_log(payload) VALUES ('{\"e\": 1}')"


# ----------------------------------------------------------------------------- B: existence


PAD: Stmt = ("SELECT 1", ())


def internal_stmts(variant: str, rid: uuid.UUID) -> tuple[list[Stmt], list[Stmt]]:
    """(statements before the business part, statements after it)."""
    claim: Stmt = (CLAIM, (rid,))
    if variant == "none":
        return [], []
    if variant.startswith("pad"):  # baseline padded to the same number of round trips
        return [PAD] * int(variant[3:]), []
    if variant in ("claim", "claim_retry"):
        return [claim], []
    if variant == "full":
        return [claim], [
            (OUTBOX, ()),
            ("INSERT INTO run_result(run_id, result) VALUES (%s, '{}')", (rid,)),
            ("SELECT pg_current_xact_id()::text", ()),
        ]
    if variant == "read_insert":
        return [("SELECT 1 FROM run_claim WHERE id = %s", (rid,)), claim], []
    if variant == "insert_update":
        return [("INSERT INTO run_claim_u(id) VALUES (%s)", (rid,))], [
            ("UPDATE run_claim_u SET result = '{}' WHERE id = %s", (rid,))
        ]
    raise ValueError(variant)


def own_orders(conn: psycopg.Connection[Any], w: int, n: int) -> list[uuid.UUID]:
    ids = [r[0] for r in conn.execute("SELECT id FROM orders ORDER BY id").fetchall()]
    return ids[w::n]


def iso_check(conn: psycopg.Connection[Any], iso: str = "SERIALIZABLE") -> str:
    conn.execute(f"BEGIN ISOLATION LEVEL {iso}")  # type: ignore[arg-type]
    row = conn.execute("SELECT current_setting('transaction_isolation')").fetchone()
    conn.execute("ROLLBACK")
    return str(row and row[0])


def exist_worker(
    cfg: dict[str, Any], w: int, n: int, barrier: Any, warmup: float, duration: float
) -> dict[str, Any]:
    conn = common.connect(cfg["port"])
    rng = random.Random(1000 + w + 7919 * cfg["rep"])
    mine = own_orders(conn, w, n) if cfg["business"] == "disjoint" else []
    stats = harness.Stats()
    stats.extra["iso=" + iso_check(conn)] += 1

    def attempt(c: psycopg.Connection[Any], _a: int) -> None:
        rid = common.uuid7()
        if cfg["internal"] == "claim_retry":
            # a rolled-back first attempt leaves a dead index entry with the same key
            harness.sequential(c, [(ISO, ()), (CLAIM, (rid,)), ("ROLLBACK", ())])
        pre, post = internal_stmts(cfg["internal"], rid)
        business: list[Stmt] = []
        if mine:
            o = rng.choice(mine)
            business = [
                ("SELECT * FROM orders WHERE id = %s", (o,)),
                ("UPDATE orders SET total = total + 1, version = version + 1 WHERE id = %s", (o,)),
            ]
        harness.sequential(c, [(ISO, ()), *pre, *business, *post, ("COMMIT", ())])

    barrier.wait()
    measure_from = time.perf_counter() + warmup
    deadline = measure_from + duration
    while (now := time.perf_counter()) < deadline:
        harness.run_command(conn, attempt, stats, rng, max_attempts=1, record=now >= measure_from)
    conn.close()
    d = stats.to_dict()
    d.pop("latencies")
    return d


EXIST_VARIANTS: list[tuple[str, str, int]] = [
    # (internal, business, fillfactor)
    *((i, "none", 70) for i in ("claim", "claim_retry", "full", "read_insert", "insert_update")),
    *(
        (i, "disjoint", 70)
        for i in (
            "none",
            "pad1",
            "pad2",
            "pad4",
            "claim",
            "claim_retry",
            "full",
            "read_insert",
            "insert_update",
        )
    ),
    # side observation: the same business baseline at the default fill factor
    ("pad1", "disjoint", 100),
    ("claim", "disjoint", 100),
]


def exist(port: int, workers: int, duration: float, warmup: float, reps: int) -> None:
    for rep in range(1, reps + 1):
        for internal, business, ff in EXIST_VARIANTS:
            common.reset(port, fillfactor=ff)
            with common.connect(port) as conn:
                common.load_orders(conn, "orders", 100_000)
                conn.execute("VACUUM ANALYZE")
            cfg = {"port": port, "rep": rep, "internal": internal, "business": business}
            parts = harness.run_workers(
                exist_worker, cfg, workers, warmup=warmup, duration=duration
            )
            m = harness.merge(parts)
            m.pop("latencies")
            time.sleep(1.0)  # let the backends' statistics reach the shared stats
            with common.connect(port) as conn:
                hot = common.hot_stats(conn)
            rec = {
                "mode": "exist",
                "rep": rep,
                "internal": internal,
                "business": business,
                "fillfactor": ff,
                "workers": workers,
                "duration_s": duration,
                "hot": hot,
                **m,
            }
            common.write_jsonl("load_exist.jsonl", [rec])
            print(
                f"rep={rep} internal={internal:<13} business={business:<8} ff={ff} "
                f"attempts={m['attempts']} commits={m['commits']} errors={m['errors']} "
                f"hot={hot} detail={m['error_detail']} extra={m['extra']}",
                flush=True,
            )


# ----------------------------------------------------------------------------- C: rates


def rates_worker(
    cfg: dict[str, Any], w: int, n: int, barrier: Any, warmup: float, duration: float
) -> dict[str, Any]:
    port = cfg["port"]
    kind = cfg["kind"]
    conn = common.connect(port)
    rng = random.Random(2000 + w + 7919 * cfg.get("rep", 0))
    stats = harness.Stats()
    mine: list[uuid.UUID] = []
    hot: list[uuid.UUID] = []
    old: list[uuid.UUID] = []
    my_keys: list[int] = []
    zipf: common.Zipf | None = None
    helper: psycopg.Connection[Any] | None = None
    recent: list[uuid.UUID] = []
    stats.extra["iso=" + iso_check(conn)] += 1
    # aging: the lower half of the workers is a constant "nowait" background load, only the
    # upper half (the probes) runs the variant, so every variant sees the same write load
    role = "background" if kind == "aging" and w < n // 2 else "probe"

    if kind == "proj":
        mine = own_orders(conn, w, n)
        my_keys = list(range(1 + w, 100_001, n))
        zipf = common.Zipf(1000, 1.1, rng)
    elif kind == "aging":
        hot = [r[0] for r in conn.execute("SELECT id FROM orders ORDER BY id LIMIT 1000")]
        zipf = common.Zipf(1000, 1.1, rng)
        helper = common.connect(port)
    elif kind == "locality":
        old = [r[0] for r in conn.execute("SELECT id FROM orders").fetchall()]
        new_key = uuid.uuid4 if cfg["key"] == "uuid4" else common.uuid7
        first = new_key()
        conn.execute("INSERT INTO orders VALUES (%s, 1, 1, 'PENDING', 10, 1)", (first,))
        recent.append(first)

    def proj_attempt(c: psycopg.Connection[Any], _a: int) -> None:
        rid = cur_rid[0]
        o = rng.choice(mine)
        rt1: list[Stmt] = [
            (ISO, ()),
            ("SET LOCAL statement_timeout = '2s'", ()),
            (CLAIM, (rid,)),
            ("SELECT * FROM orders WHERE id = %s", (o,)),
        ]
        harness.round_trip(c, rt1)
        proj: list[Stmt] = []
        form, dist = cfg["form"], cfg["dist"]
        if form != "none":
            assert zipf is not None
            if form == "upsert_new":
                table, col, key = "proj_new", "id", common.uuid7()
            elif dist == "disjoint":
                table, col, key = "user_spending", "user_id", rng.choice(my_keys)
            elif dist == "zipf":
                table, col, key = "store_revenue", "store_id", zipf.sample()
            else:
                table, col, key = "store_revenue", "store_id", 0
            if form == "update":
                proj = [(f"UPDATE {table} SET total = total + 1 WHERE {col} = %s", (key,))]
            else:
                proj = [
                    (
                        f"INSERT INTO {table}({col}, total) VALUES (%s, 1) ON CONFLICT ({col}) "
                        f"DO UPDATE SET total = {table}.total + 1",
                        (key,),
                    )
                ]
        rt2: list[Stmt] = [
            ("UPDATE orders SET total = total + 1, version = version + 1 WHERE id = %s", (o,)),
            *proj,
            (OUTBOX, ()),
            ("SELECT pg_current_xact_id()::text", ()),
            ("COMMIT", ()),
            ("SELECT pg_current_wal_insert_lsn()::text", ()),
        ]
        harness.round_trip(c, rt2)

    def aging_attempt(c: psycopg.Connection[Any], a: int) -> None:
        assert zipf is not None
        assert helper is not None
        rid = cur_rid[0]
        o = hot[zipf.sample()]
        variant = cfg["variant"] if role == "probe" else "nowait"
        begin: list[Stmt] = [(ISO, ()), ("SET LOCAL statement_timeout = '2s'", ())]
        if a == 1 and variant == "wait":
            helper.execute("BEGIN")
            helper.execute(CLAIM, (rid,))
            timer = threading.Timer(cfg["wait_s"], lambda: helper.execute("ROLLBACK"))
            timer.start()
            t0 = time.perf_counter()
            try:
                harness.round_trip(
                    c, [*begin, (CLAIM, (rid,)), ("SELECT * FROM orders WHERE id = %s", (o,))]
                )
            finally:
                timer.join()
            stats.extra["waited_ms_total"] += round((time.perf_counter() - t0) * 1000)
        elif a == 1 and variant == "sleep":
            harness.round_trip(c, [*begin, ("SELECT 1", ())])
            time.sleep(cfg["wait_s"])
            harness.round_trip(c, [(CLAIM, (rid,)), ("SELECT * FROM orders WHERE id = %s", (o,))])
        else:
            harness.round_trip(
                c, [*begin, (CLAIM, (rid,)), ("SELECT * FROM orders WHERE id = %s", (o,))]
            )
        harness.round_trip(
            c,
            [
                ("UPDATE orders SET total = total + 1, version = version + 1 WHERE id = %s", (o,)),
                (OUTBOX, ()),
                ("SELECT pg_current_xact_id()::text", ()),
                ("COMMIT", ()),
                ("SELECT pg_current_wal_insert_lsn()::text", ()),
            ],
        )

    def hot_attempt(c: psycopg.Connection[Any], _a: int) -> None:
        rid = cur_rid[0]
        load: list[Stmt] = {
            "blind": [],
            "read": [("SELECT bal FROM hot WHERE id = 1", ())],
            "for_update": [("SELECT bal FROM hot WHERE id = 1 FOR UPDATE", ())],
        }[cfg["mode"]]
        harness.round_trip(
            c, [(ISO, ()), ("SET LOCAL statement_timeout = '2s'", ()), (CLAIM, (rid,)), *load]
        )
        harness.round_trip(
            c,
            [
                ("UPDATE hot SET bal = bal + 1 WHERE id = 1", ()),
                (OUTBOX, ()),
                ("SELECT pg_current_xact_id()::text", ()),
                ("COMMIT", ()),
                ("SELECT pg_current_wal_insert_lsn()::text", ()),
            ],
        )

    def locality_attempt(c: psycopg.Connection[Any], _a: int) -> None:
        rid = cur_rid[0]
        read = recent[-1] if cfg["read"] == "recent" else rng.choice(old)
        new_id = uuid.uuid4() if cfg["key"] == "uuid4" else common.uuid7()
        harness.round_trip(
            c,
            [
                (ISO, ()),
                ("SET LOCAL statement_timeout = '2s'", ()),
                (CLAIM, (rid,)),
                ("SELECT * FROM orders WHERE id = %s", (read,)),
            ],
        )
        harness.round_trip(
            c,
            [
                ("INSERT INTO orders VALUES (%s, 1, 1, 'PENDING', 10, 1)", (new_id,)),
                (OUTBOX, ()),
                ("SELECT pg_current_xact_id()::text", ()),
                ("COMMIT", ()),
                ("SELECT pg_current_wal_insert_lsn()::text", ()),
            ],
        )
        pending_recent[0] = new_id

    attempt_fn = {
        "proj": proj_attempt,
        "aging": aging_attempt,
        "locality": locality_attempt,
        "hot": hot_attempt,
    }[kind]
    cur_rid: list[uuid.UUID] = [common.uuid7()]
    pending_recent: list[uuid.UUID | None] = [None]

    barrier.wait()
    start = time.perf_counter()
    measure_from = start + warmup
    deadline = measure_from + duration
    while True:
        now = time.perf_counter()
        if now >= deadline:
            break
        cur_rid[0] = common.uuid7()  # one run ID per command, reused by its retries
        pending_recent[0] = None
        if harness.run_command(
            conn, attempt_fn, stats, rng, max_attempts=4, record=now >= measure_from
        ):
            stats.extra["all_commits"] += 1  # warm-up included, for the hot-row total check
        # set only after a successful COMMIT round trip (an error raises before the assignment)
        if pending_recent[0] is not None:
            recent.append(pending_recent[0])
    conn.close()
    if helper is not None:
        helper.close()
    d = stats.to_dict()
    d.pop("latencies")
    d["role"] = role
    return d


RATE_VARIANTS: list[dict[str, Any]] = [
    {"kind": "proj", "form": "none", "dist": "-"},
    *(
        {"kind": "proj", "form": f, "dist": d}
        for f in ("update", "upsert_existing")
        for d in ("disjoint", "zipf", "global")
    ),
    {"kind": "proj", "form": "upsert_new", "dist": "-"},
    *({"kind": "aging", "variant": v, "wait_s": 0.05} for v in ("nowait", "wait", "sleep")),
    *(
        {"kind": "locality", "key": k, "read": r}
        for k in ("uuid7", "uuid4")
        for r in ("recent", "old")
    ),
    # C4 (carried over from spike 0002 / ADR-0005): one hot row, by load form and worker count
    *(
        {"kind": "hot", "mode": m, "workers": w}
        for w in (8, 32, 64)
        for m in ("blind", "read", "for_update")
    ),
]


def prepare_rates(port: int, v: dict[str, Any]) -> None:
    common.reset(port)
    with common.connect(port) as conn:
        if v["kind"] == "locality" and v["key"] == "uuid4":
            common.copy_rows(
                conn,
                "orders",
                "id, user_id, store_id, status, total, version",
                ((uuid.uuid4(), 1, 1, "PENDING", 10, 1) for _ in range(100_000)),
            )
        else:
            common.load_orders(conn, "orders", 100_000)
        conn.execute("INSERT INTO user_spending SELECT g, 0 FROM generate_series(1, 100000) g")
        conn.execute("INSERT INTO store_revenue SELECT g, 0 FROM generate_series(0, 999) g")
        conn.execute("INSERT INTO hot VALUES (1, 0)")
        conn.execute("VACUUM ANALYZE")
        conn.execute("CHECKPOINT")


def label(v: dict[str, Any]) -> str:
    return " ".join(f"{k}={val}" for k, val in v.items() if k != "wait_s")


def done_rates() -> set[tuple[int, str]]:
    path = common.RESULTS / "load_rates.jsonl"
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text().splitlines():
        r = json.loads(line)
        v = {
            k: r[k]
            for k in ("kind", "form", "dist", "variant", "wait_s", "key", "read", "mode", "workers")
            if k in r and k in VARIANT_KEYS.get(r["kind"], ())
        }
        done.add((r["rep"], label(v)))
    return done


VARIANT_KEYS = {
    "proj": ("kind", "form", "dist"),
    "aging": ("kind", "variant", "wait_s"),
    "locality": ("kind", "key", "read"),
    "hot": ("kind", "mode", "workers"),
}


def rates(
    port: int, workers: int, duration: float, warmup: float, reps: int, only: str, resume: bool
) -> None:
    done = done_rates() if resume else set()
    for rep in range(1, reps + 1):
        for v in RATE_VARIANTS:
            if only and v["kind"] != only:
                continue
            if (rep, label(v)) in done:
                continue
            for run_try in range(1, 6):
                before = harness.wait_quiet()
                prepare_rates(port, v)
                cfg = {"port": port, "rep": rep, **v}
                with harness.HostMonitor() as mon:
                    parts = harness.run_workers(
                        rates_worker,
                        cfg,
                        v.get("workers", workers),
                        warmup=warmup,
                        duration=duration,
                    )
                during = mon.summary()
                if during["quiet"]:
                    break
                common.write_jsonl(
                    "load_rates_discarded.jsonl",
                    [{"rep": rep, **v, "run_try": run_try, "before": before, "during": during}],
                )
                print(f"# discarded (host not quiet during the run): {during}", flush=True)
            else:
                raise RuntimeError(f"no quiet run for {v} in 5 tries")
            m = harness.merge([p for p in parts if p["role"] == "probe"])
            m.pop("latencies")
            bg = [p for p in parts if p["role"] == "background"]
            background = harness.merge(bg) if bg else None
            if background is not None:
                background.pop("latencies")
            time.sleep(1.0)  # let the backends' statistics reach the shared stats
            with common.connect(port) as conn:
                hot = common.hot_stats(conn)
                hot_total = (
                    conn.execute("SELECT bal FROM hot WHERE id = 1").fetchone()
                    if v["kind"] == "hot"
                    else None
                )
            all_commits = sum(p["extra"].get("all_commits", 0) for p in parts)
            e40001 = m["errors"].get(common.SERIALIZATION_FAILURE, 0)
            rec = {
                "mode": "rates",
                "rep": rep,
                **v,
                "hot": hot,
                "background": background,
                "host": {"before": before, "during": during, "run_try": run_try},
                # hot row: the final value must equal the number of committed increments
                "hot_total_ok": None if hot_total is None else int(hot_total[0]) == all_commits,
                "workers": v.get("workers", workers),
                "duration_s": duration,
                "rate_40001_per_attempt": e40001 / m["attempts"] if m["attempts"] else None,
                "attempts_per_commit": m["attempts"] / m["commits"] if m["commits"] else None,
                **m,
            }
            common.write_jsonl("load_rates.jsonl", [rec])
            print(
                f"rep={rep} {label(v):<52} attempts={m['attempts']} commits={m['commits']} "
                f"40001/att={rec['rate_40001_per_attempt']:.4f} errors={m['errors']} "
                f"exhausted={m['exhausted']} extra={m['extra']} hot={hot} "
                f"detail={m['error_detail']}",
                flush=True,
            )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["exist", "rates"])
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--workers", type=int)
    ap.add_argument("--reps", type=int)
    ap.add_argument("--duration", type=float, help="seconds measured (exist 10, rates 15)")
    ap.add_argument("--warmup", type=float, default=2)
    ap.add_argument("--only", default="", help="rates: run only one kind (proj/aging/locality/hot)")
    ap.add_argument("--resume", action="store_true", help="rates: skip runs already recorded")
    a = ap.parse_args()
    print(f"# load.py {a.mode} {datetime.now(UTC).isoformat()} {vars(a)}", flush=True)
    if a.mode == "exist":
        exist(a.port, a.workers or 16, a.duration or 10, a.warmup, a.reps or 5)
    else:
        rates(a.port, a.workers or 32, a.duration or 15, a.warmup, a.reps or 5, a.only, a.resume)


if __name__ == "__main__":
    main()
