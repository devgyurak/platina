# TEMPORARY (spike 0002): the reproducer's code below is kept byte-identical, so lint and
# formatting are suppressed for this file until the maintainer decides how to treat it.
# fmt: off
"""Pinned-interleaving interpreter: a scenario is a list of (session name, SQL | RESUME)."""

from harness import Pending, Sess, admin, log

RESUME = "<resume>"


def play(title: str, steps: list[tuple[str, str]], names: tuple[str, ...] = ("T1", "T2")) -> dict[str, str]:
    """Run steps in order. A blocked statement stays pending until that session's RESUME step.

    After a session's statement fails, its remaining steps are skipped and ROLLBACK is sent.
    Returns per session: 'committed', or 'FAILED at <sql>: <error>' (+ whether it had waited).
    """
    log(f"\n=== {title}")
    sess = {n: Sess(n) for n in names}
    pending: dict[str, Pending] = {}
    final: dict[str, str] = {}
    waited: dict[str, list[str]] = {n: [] for n in names}
    try:
        for name, sql in steps:
            if name == "@":  # observer query on a separate autocommit connection
                log(f"    [@] {sql}\n        -> {admin(sql)}")
                continue
            if name in final and final[name].startswith("FAILED"):
                log(f"    [{name}] (skipped, transaction already failed) {sql}")
                continue
            s = sess[name]
            if sql == RESUME:
                if name not in pending:
                    log(f"    [{name}] (resume requested, but nothing was pending)")
                    continue
                p = pending.pop(name)
                r: str | Pending = p.result()
                sql = p.sql
            else:
                if name in pending:
                    raise RuntimeError(f"{name} is blocked; cannot run {sql}")
                r = s.do(sql)
            if isinstance(r, Pending):
                pending[name] = r
                waited[name].append(sql.split(" /*")[0][:40])
                continue
            if r.startswith("ERROR"):
                final[name] = f"FAILED at [{sql}]: {r}"
                s.do("ROLLBACK")
            elif sql.strip().upper() == "COMMIT":
                final[name] = "committed"
            elif sql.strip().upper() == "ROLLBACK":
                final[name] = "rolled back (scripted)"
        if pending:
            raise RuntimeError(f"scenario ended with blocked sessions: {list(pending)}")
        for n in names:
            w = f" (after an observed lock wait at: {'; '.join(waited[n])})" if waited[n] else " (no lock wait)"
            final[n] = final.get(n, "never finished") + w
            log(f"  RESULT {n}: {final[n]}")
        return final
    finally:
        for s in sess.values():
            s.close()
