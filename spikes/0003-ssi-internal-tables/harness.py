"""Worker-process harness shared by load.py and bench.py (throwaway)."""

from __future__ import annotations

import contextlib
import multiprocessing as mp
import os
import random
import re
import subprocess
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import common
import psycopg

Stmt = tuple[str, tuple[Any, ...]]

RETRYABLE = {common.SERIALIZATION_FAILURE, common.DEADLOCK}


@dataclass
class Stats:
    attempts: int = 0
    commits: int = 0
    commands: int = 0
    errors: Counter[str] = field(default_factory=Counter)
    exhausted: int = 0
    dropped: Counter[str] = field(default_factory=Counter)
    latencies: list[float] = field(default_factory=list)
    attempts_hist: Counter[int] = field(default_factory=Counter)
    extra: Counter[str] = field(default_factory=Counter)
    error_detail: Counter[str] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_detail": dict(self.error_detail),
            "attempts": self.attempts,
            "commits": self.commits,
            "commands": self.commands,
            "errors": dict(self.errors),
            "exhausted": self.exhausted,
            "dropped": dict(self.dropped),
            "latencies": self.latencies,
            "attempts_hist": {str(k): v for k, v in self.attempts_hist.items()},
            "extra": dict(self.extra),
        }


def merge(parts: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "attempts": 0,
        "commits": 0,
        "commands": 0,
        "exhausted": 0,
        "errors": Counter(),
        "dropped": Counter(),
        "latencies": [],
        "attempts_hist": Counter(),
        "extra": Counter(),
        "error_detail": Counter(),
    }
    for p in parts:
        for k in ("attempts", "commits", "commands", "exhausted"):
            out[k] += p[k]
        for k in ("errors", "dropped", "attempts_hist", "extra", "error_detail"):
            out[k].update(p[k])
        out["latencies"].extend(p.get("latencies", []))
    for k in ("errors", "dropped", "attempts_hist", "extra", "error_detail"):
        out[k] = dict(out[k])
    return out


class StmtError(Exception):
    """A database error with the statement of the batch that raised it."""

    def __init__(self, exc: psycopg.Error, stmt: str) -> None:
        super().__init__(str(exc))
        self.exc = exc
        self.stmt = stmt


def stmt_label(sql: str) -> str:
    s = re.sub(r"\s+", " ", sql.strip())
    s = re.split(r" VALUES| WHERE| SET (?!LOCAL)| ON CONFLICT|\(", s, maxsplit=1)[0]
    return s[:48]


def _failed_stmt(curs: list[psycopg.Cursor[Any]], stmts: list[Stmt]) -> str:
    """The failing statement is the first one without a result (psycopg sets no result on the
    cursor that raised, and the server skips the statements after it)."""
    for c, (sql, _) in zip(curs, stmts, strict=False):
        if c.pgresult is None:
            return stmt_label(sql)
    return "?"


def round_trip(conn: psycopg.Connection[Any], stmts: list[Stmt]) -> list[Any]:
    """Sends all statements followed by exactly one Sync (the pipeline block's exit) and returns
    each one's rows or rowcount. On error raises StmtError naming the failing statement; the
    server skips the rest of the batch."""
    curs: list[psycopg.Cursor[Any]] = []
    try:
        with conn.pipeline():
            for sql, params in stmts:
                curs.append(conn.execute(sql, params))  # type: ignore[arg-type]
    except psycopg.Error as exc:
        raise StmtError(exc, _failed_stmt(curs, stmts)) from exc
    return [c.fetchall() if c.description else c.rowcount for c in curs]


def sequential(conn: psycopg.Connection[Any], stmts: list[Stmt]) -> list[Any]:
    """One round trip per statement."""
    out: list[Any] = []
    for sql, params in stmts:
        try:
            cur = conn.execute(sql, params)  # type: ignore[arg-type]
        except psycopg.Error as exc:
            raise StmtError(exc, stmt_label(sql)) from exc
        out.append(cur.fetchall() if cur.description else cur.rowcount)
    return out


def error_key(err: StmtError) -> str:
    """statement | SQLSTATE | message | detail, digits normalised (xids, pids)."""
    d = err.exc.diag
    text = re.sub(r"\d+", "N", f"{d.message_primary} | {d.message_detail}")
    return f"{err.stmt} | {d.sqlstate} | {text}"


def rollback(conn: psycopg.Connection[Any]) -> None:
    with contextlib.suppress(psycopg.Error):
        conn.execute("ROLLBACK")


class Dropped(Exception):
    """The command ended without commit for a non-retryable, non-database reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def backoff(attempt: int, rng: random.Random, base: float = 0.010, cap: float = 0.200) -> float:
    """Full jitter, design 8.3: uniform(0, min(cap, base * 2^(attempt-1)))."""
    return rng.uniform(0, min(cap, base * 2 ** (attempt - 1)))


# An attempt function runs one whole attempt (both round trips, COMMIT included) on conn for the
# given attempt number and returns normally on commit; it raises psycopg.Error or Dropped.
Attempt = Callable[[psycopg.Connection[Any], int], None]


def run_command(
    conn: psycopg.Connection[Any],
    attempt_fn: Attempt,
    stats: Stats,
    rng: random.Random,
    *,
    max_attempts: int,
    record: bool,
) -> bool:
    """Runs one command with retries; returns True when it committed."""
    t0 = time.perf_counter()
    for attempt in range(1, max_attempts + 1):
        if record:
            stats.attempts += 1
        try:
            attempt_fn(conn, attempt)
        except (StmtError, psycopg.Error) as caught:
            err = caught if isinstance(caught, StmtError) else StmtError(caught, "?")
            st = err.exc.sqlstate or type(err.exc).__name__
            rollback(conn)
            if record:
                stats.errors[st] += 1
                stats.error_detail[error_key(err)] += 1
            if st in RETRYABLE and attempt < max_attempts:
                time.sleep(backoff(attempt, rng))
                continue
            if record:
                stats.commands += 1
                if st in RETRYABLE:
                    stats.exhausted += 1
                else:
                    stats.dropped[st] += 1
            return False
        except Dropped as d:
            rollback(conn)
            if record:
                stats.commands += 1
                stats.dropped[d.reason] += 1
            return False
        if record:
            stats.commits += 1
            stats.commands += 1
            stats.latencies.append(time.perf_counter() - t0)
            stats.attempts_hist[attempt] += 1
        return True
    return False


# ------------------------------------------------------------------------- process runner

WorkerFn = Callable[[dict[str, Any], int, int, Any, float, float], dict[str, Any]]


def _entry(
    fn: WorkerFn,
    cfg: dict[str, Any],
    w: int,
    n: int,
    barrier: Any,
    q: Any,
    warmup: float,
    duration: float,
) -> None:
    try:
        q.put((w, fn(cfg, w, n, barrier, warmup, duration)))
    except BaseException as exc:
        q.put((w, {"crash": repr(exc)}))
        raise


def run_workers(
    fn: WorkerFn, cfg: dict[str, Any], n: int, *, warmup: float, duration: float
) -> list[dict[str, Any]]:
    """Starts n spawn processes that each open their connection, wait on a shared barrier, then
    run fn. fn receives the barrier and must call barrier.wait() once its setup is done."""
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(n)
    q = ctx.Queue()
    procs = [
        ctx.Process(target=_entry, args=(fn, cfg, w, n, barrier, q, warmup, duration))
        for w in range(n)
    ]
    for p in procs:
        p.start()
    results = [q.get(timeout=600) for _ in procs]
    for p in procs:
        p.join(timeout=60)
    crashes = [r for _, r in results if "crash" in r]
    if crashes:
        raise RuntimeError(f"worker crashed: {crashes[0]}")
    return [r for _, r in sorted(results, key=lambda t: t[0])]


# ------------------------------------------------------------------------- quiet-host gate

# Fixed before any gated run completed (2026-11-25, second version; see the write-up's change
# record). "External CPU" is the CPU used by everything that is not this measurement:
#   - host processes outside this harness's process tree (the parent and its spawn workers),
#     excluding the Docker VM and Docker backend processes (they carry the spike's own
#     PostgreSQL), from `ps` %CPU (100 = one core);
#   - plus the CPU of every container whose name does not start with "platina-", from
#     `docker stats --no-stream` (100 = one core).
# A C run / D pair counts only if (a) external CPU is at most QUIET_EXTERNAL_PCT right before it
# starts and (b) the mean of samples taken every MONITOR_PERIOD_S seconds while it runs is at
# most QUIET_EXTERNAL_PCT. 500 = 5 of the 15 cores: spot checks just before the reruns, with no
# heavy job running, gave 2.5-3.9 cores of always-on load (endpoint agents, syspolicyd, desktop
# apps, other agent sessions); the earlier contamination was about 8 cores (six `yes` processes
# alone ~5.4). Every record keeps its samples, so a stricter cut can be applied afterwards.
# SPIKE_QUIET_EXTERNAL_PCT overrides it for smoke tests only; measured runs use the default.
QUIET_EXTERNAL_PCT = float(os.environ.get("SPIKE_QUIET_EXTERNAL_PCT", "500"))
MONITOR_PERIOD_S = 5.0
# then stop and report instead of waiting on; SPIKE_QUIET_MAX_WAIT_S raises it (the maintainer
# allowed waiting through the night on 2026-11-25)
QUIET_MAX_WAIT_S = int(os.environ.get("SPIKE_QUIET_MAX_WAIT_S", str(30 * 60)))


def _own_tree() -> set[int]:
    out = subprocess.run(
        ["/bin/ps", "-Ao", "pid=,ppid="], capture_output=True, text=True, check=True
    ).stdout
    children: dict[int, list[int]] = {}
    for line in out.splitlines():
        pid, ppid = (int(x) for x in line.split())
        children.setdefault(ppid, []).append(pid)
    own, todo = set(), [os.getpid()]
    while todo:
        p = todo.pop()
        if p not in own:
            own.add(p)
            todo.extend(children.get(p, []))
    return own


EXCLUDED_COMMANDS = ("com.apple.Virtualization.VirtualMachine", "com.docker.backend")


def external_cpu() -> dict[str, float]:
    """External CPU in % of one core: host processes + non-platina containers."""
    own = _own_tree()
    out = subprocess.run(
        ["/bin/ps", "-Ao", "pid=,pcpu=,comm="], capture_output=True, text=True, check=True
    ).stdout
    host = 0.0
    for line in out.splitlines():
        pid_s, cpu_s, comm = line.strip().split(None, 2)
        if int(pid_s) in own or any(x in comm for x in EXCLUDED_COMMANDS):
            continue
        host += float(cpu_s)
    stats = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    containers = 0.0
    for line in stats.splitlines():
        name, pct = line.split()
        if not name.startswith("platina-"):
            containers += float(pct.rstrip("%"))
    return {
        "external_pct": round(host + containers, 1),
        "host_pct": round(host, 1),
        "containers_pct": round(containers, 1),
        "load1": round(os.getloadavg()[0], 2),
    }


def wait_quiet(*, poll: int = 30, max_wait: int = QUIET_MAX_WAIT_S) -> dict[str, float]:
    """Blocks until external CPU is at most QUIET_EXTERNAL_PCT; raises after max_wait."""
    deadline = time.monotonic() + max_wait
    while True:
        s = external_cpu()
        if s["external_pct"] <= QUIET_EXTERNAL_PCT:
            return s
        if time.monotonic() > deadline:
            raise RuntimeError(f"host not quiet after {max_wait} s: {s}")
        print(f"# waiting for a quiet host: {s}", flush=True)
        time.sleep(poll)


class HostMonitor:
    """Samples external_cpu() every MONITOR_PERIOD_S seconds on a thread while a run executes."""

    def __init__(self) -> None:
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while True:  # one sample at once, then every MONITOR_PERIOD_S seconds
            with contextlib.suppress(Exception):
                self.samples.append(external_cpu())
            if self._stop.wait(MONITOR_PERIOD_S):
                return

    def __enter__(self) -> HostMonitor:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()

    def summary(self) -> dict[str, Any]:
        ext = [s["external_pct"] for s in self.samples]
        mean = sum(ext) / len(ext) if ext else 0.0
        return {
            "n": len(ext),
            "mean_external_pct": round(mean, 1),
            "max_external_pct": max(ext, default=0.0),
            "max_load1": max((s["load1"] for s in self.samples), default=0.0),
            "quiet": bool(ext) and mean <= QUIET_EXTERNAL_PCT,  # no samples: not quiet
        }
