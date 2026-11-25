"""Prints the markdown tables of the write-up from results/*.jsonl (throwaway).

uv run python spikes/0003-ssi-internal-tables/summarize.py rates|bench
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Any

import common


def load(name: str) -> list[dict[str, Any]]:
    with (common.RESULTS / name).open() as f:
        return [json.loads(line) for line in f if line.strip()]


def mr(xs: list[float], fmt: str = "{:.4f}") -> str:
    """median (min-max)"""
    if not xs:
        return "-"
    return f"{fmt.format(common.median(xs))} ({fmt.format(min(xs))}-{fmt.format(max(xs))})"


def rates(name: str = "load_rates.jsonl") -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in load(name):
        keys = [k for k in ("kind", "form", "dist", "variant", "key", "read") if k in r]
        groups[" ".join(f"{k}={r[k]}" for k in keys)].append(r)
    print(
        "| Variant | Runs | Attempts/run | 40001 / attempt | Attempts / commit | Exhausted / run | Background 40001 / attempt |"
    )
    print("|---|---|---|---|---|---|---|")
    for label, rs in groups.items():
        att = [float(r["attempts"]) for r in rs]
        rate = [100 * r["errors"].get("40001", 0) / r["attempts"] for r in rs]
        apc = [r["attempts"] / r["commits"] for r in rs]
        exh = [float(r["exhausted"]) for r in rs]
        bg = [
            100 * r["background"]["errors"].get("40001", 0) / r["background"]["attempts"]
            for r in rs
            if r.get("background")
        ]
        print(
            f"| {label} | {len(rs)} | {mr(att, '{:.0f}')} | {mr(rate, '{:.3f}%')} | "
            f"{mr(apc, '{:.3f}')} | {mr(exh, '{:.0f}')} | {mr(bg, '{:.3f}%')} |"
        )
    print()
    for label, rs in groups.items():
        detail: dict[str, int] = defaultdict(int)
        for r in rs:
            for k, v in r["error_detail"].items():
                detail[k] += v
        for k, v in sorted(detail.items(), key=lambda kv: -kv[1]):
            print(f"- {label}: {v} x `{k}`")


def bench(name: str = "bench.jsonl") -> None:
    groups: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in load(name):
        groups[(r["workers"], r["dist"], r["iso"])].append(r)
    print(
        "| Workers | Dist | Isolation | Runs | TPS | Attempts / commit | 40001 / attempt | 40P01 / run | Exhausted % of commands | p50 ms | p99 ms | Transfer inv. | Pocket users < 0 / run |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for (w, d, iso), rs in sorted(groups.items()):
        tps = [r["tps"] for r in rs]
        apc = [r["attempts_per_commit"] for r in rs]
        rate = [100 * r["rate_40001_per_attempt"] for r in rs]
        dl = [float(r["errors"].get("40P01", 0)) for r in rs]
        exh = [100 * r["exhausted"] / r["commands"] for r in rs]
        p50 = [r["p50_ms"] for r in rs]
        p99 = [r["p99_ms"] for r in rs]
        inv = "ok" if all(r["transfer_invariant_ok"] for r in rs) else "BROKEN"
        neg = ", ".join(str(r["pocket_users_negative"]) for r in rs)
        print(
            f"| {w} | {d} | {iso} | {len(rs)} | {mr(tps, '{:.0f}')} | {mr(apc, '{:.3f}')} | "
            f"{mr(rate, '{:.2f}%')} | {mr(dl, '{:.0f}')} | {mr(exh, '{:.3f}')} | "
            f"{mr(p50, '{:.1f}')} | {mr(p99, '{:.1f}')} | {inv} | {neg} |"
        )
    print()
    print(
        "| Workers | Dist | SER/RR median TPS | SER/RR TPS per run (paired by run) | SER - RR attempts/commit (medians) |"
    )
    print("|---|---|---|---|---|")
    for w in sorted({k[0] for k in groups}):
        for d in ("uniform", "zipf"):
            ser = sorted(groups.get((w, d, "SERIALIZABLE"), []), key=lambda r: r["rep"])
            rr = sorted(groups.get((w, d, "REPEATABLE READ"), []), key=lambda r: r["rep"])
            if not ser or not rr:
                continue
            ratio = common.median([r["tps"] for r in ser]) / common.median([r["tps"] for r in rr])
            paired = ", ".join(f"{a['tps'] / b['tps']:.2f}" for a, b in zip(ser, rr, strict=False))
            dapc = common.median([r["attempts_per_commit"] for r in ser]) - common.median(
                [r["attempts_per_commit"] for r in rr]
            )
            print(f"| {w} | {d} | {ratio:.3f} | {paired} | {dapc:+.4f} |")
    print()
    print("Per command type, 40001 / attempt, median over runs:")
    print()
    types = ("pay", "create", "transfer", "pocket", "reprice")
    print("| Workers | Dist | Isolation | " + " | ".join(types) + " |")
    print("|---|---|---|" + "---|" * len(types))
    for (w, d, iso), rs in sorted(groups.items()):
        cells = []
        for t in types:
            v = [100 * (r["by_type"][t]["rate_40001_per_attempt"] or 0) for r in rs]
            cells.append(f"{common.median(v):.2f}%")
        print(f"| {w} | {d} | {iso} | " + " | ".join(cells) + " |")
    print()
    detail: dict[tuple[str, str], int] = defaultdict(int)
    for (_, _, iso), rs in groups.items():
        for r in rs:
            for k, v in r["error_detail"].items():
                detail[(iso, k)] += v
    for (iso, k), v in sorted(detail.items(), key=lambda kv: -kv[1])[:20]:
        print(f"- {iso}: {v} x `{k}`")


if __name__ == "__main__":
    {"rates": rates, "bench": bench}[sys.argv[1]](*sys.argv[2:])
