"""Shared helpers for spike 0003 (throwaway; never imported by src/ or tests/)."""

from __future__ import annotations

import bisect
import itertools
import json
import random
import uuid
from pathlib import Path
from typing import Any

import psycopg

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

SERIALIZATION_FAILURE = "40001"
DEADLOCK = "40P01"
UNIQUE_VIOLATION = "23505"


def dsn(port: int) -> str:
    return f"host=localhost port={port} user=platina password=platina dbname=platina"


def connect(port: int, *, autocommit: bool = True) -> psycopg.Connection[Any]:
    # prepare_threshold=None: no server-side prepared statements, so no switch to generic plans
    return psycopg.connect(dsn(port), autocommit=autocommit, prepare_threshold=None)


def uuid7() -> uuid.UUID:
    return uuid.uuid7()


def reset_schema(port: int) -> None:
    with connect(port) as conn:
        conn.execute((HERE / "schema.sql").read_text())  # type: ignore[arg-type]


FILLFACTOR_TABLES = (
    "orders",
    "small_orders",
    "wallets",
    "accounts",
    "products",
    "pockets",
    "user_spending",
    "store_revenue",
    "proj_new",
    "hot",
)


def set_fillfactor(conn: psycopg.Connection[Any], ff: int) -> None:
    for t in FILLFACTOR_TABLES:
        conn.execute(f"ALTER TABLE {t} SET (fillfactor = {ff})")  # type: ignore[arg-type]


def reset(port: int, *, fillfactor: int = 70) -> None:
    """Recreate the schema and set the fill factor of the business/projection tables."""
    reset_schema(port)
    with connect(port) as conn:
        set_fillfactor(conn, fillfactor)


def hot_stats(conn: psycopg.Connection[Any]) -> dict[str, tuple[int, int]]:
    """(n_tup_upd, n_tup_hot_upd) per business table with updates."""
    rows = conn.execute(
        "SELECT relname, n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE n_tup_upd > 0"
    ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def copy_rows(conn: psycopg.Connection[Any], table: str, cols: str, rows: Any) -> None:
    with conn.cursor() as cur, cur.copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(row)


def load_uuid7_claims(conn: psycopg.Connection[Any], table: str, n: int) -> None:
    """Preload n client-generated uuid7 keys (same generator as the run IDs, so later IDs sort
    after them regardless of any clock difference between the client and the Docker VM)."""
    copy_rows(conn, table, "id", ((uuid7(),) for _ in range(n)))


def load_orders(
    conn: psycopg.Connection[Any],
    table: str,
    n: int,
    *,
    stores: int = 1000,
    zipf_s: float = 1.1,
    seed: int = 1,
    users: int = 100_000,
) -> list[uuid.UUID]:
    rng = random.Random(seed)
    store = Zipf(stores, zipf_s, rng)
    ids = [uuid7() for _ in range(n)]
    copy_rows(
        conn,
        table,
        "id, user_id, store_id, status, total, version",
        ((i, 1 + rng.randrange(users), store.sample(), "PENDING", 10, 1) for i in ids),
    )
    return ids


class Zipf:
    """Ranks 0..n-1, P(rank k) proportional to 1 / (k+1)^s. Rank 0 is the most popular."""

    def __init__(self, n: int, s: float, rng: random.Random) -> None:
        weights = [1.0 / (k + 1) ** s for k in range(n)]
        self.cdf = list(itertools.accumulate(weights))
        self.total = self.cdf[-1]
        self.rng = rng
        self.top1_share = weights[0] / self.total

    def sample(self) -> int:
        return bisect.bisect_left(self.cdf, self.rng.random() * self.total)


def sqlstate(exc: BaseException) -> str | None:
    return getattr(exc, "sqlstate", None)


def write_jsonl(name: str, records: list[dict[str, Any]]) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / name
    with path.open("a") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")
    return path


def median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))
    return s[k]
