# TEMPORARY (spike 0002): the reproducer's code below is kept byte-identical, so lint and
# formatting are suppressed for this file until the maintainer decides how to treat it.
# fmt: off
"""Part A: X8 with the lock wait OBSERVED (not slept), plus the no-wait variant and snapshot proof."""

from harness import SCHEMA, Pending, Sess, admin, banner, create_schema, drop_schema, log

ACC = f"{SCHEMA}.acc"
BLIND = [f"UPDATE {ACC} SET bal = bal + 1 WHERE id = 1"]
LOCKED = [f"SELECT bal FROM {ACC} WHERE id = 1 FOR UPDATE", f"UPDATE {ACC} SET bal = bal + 1 WHERE id = 1"]


def reset() -> None:
    admin(f"DROP TABLE IF EXISTS {ACC}")
    admin(f"CREATE TABLE {ACC} (id int PRIMARY KEY, bal int NOT NULL)")
    admin(f"INSERT INTO {ACC} VALUES (1, 0)")


def case(isolation: str, name: str, ops: list[str], t1_commits_before_t2_op: bool) -> None:
    reset()
    log(f"\n=== {isolation} / {name} / "
        f"{'T1 commits BEFORE T2 issues its op (no wait)' if t1_commits_before_t2_op else 'T2 op issued while T1 holds the lock'}")
    t1, t2 = Sess("T1"), Sess("T2")
    try:
        t1.do(f"BEGIN ISOLATION LEVEL {isolation}")
        t2.do(f"BEGIN ISOLATION LEVEL {isolation}")
        t2.do("SELECT 1, pg_current_snapshot()")  # T2's first query: snapshot (RR/SER)
        for s in ops:
            t1.do(s)
        t1.do("SELECT pg_current_xact_id()")
        outcome: str = "?"
        if t1_commits_before_t2_op:
            t1.do("COMMIT")
        pend: Pending | None = None
        for s in ops:
            r = t2.do(s)
            if isinstance(r, Pending):
                pend = r
                assert not t1_commits_before_t2_op
                t1.do("COMMIT")
                r = pend.result()
            if r.startswith("ERROR"):
                outcome = r
                break
        else:
            outcome = t2.do("COMMIT")  # type: ignore[assignment]
        if outcome.startswith("ERROR"):
            t2.do("ROLLBACK")
        if not t1_commits_before_t2_op and pend is None:
            log("    !!! T2 never blocked")
        bal = admin(f"SELECT bal FROM {ACC} WHERE id = 1")[0][0]
        log(f"  RESULT {isolation:16} {name:26} waited={'yes' if pend else 'no'} -> T2 {outcome}; final bal = {bal}")
    finally:
        t1.close()
        t2.close()


def main() -> None:
    banner()
    create_schema()
    try:
        for before in (False, True):
            for isolation in ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"):
                case(isolation, "blind increment", BLIND, before)
                case(isolation, "FOR UPDATE then increment", LOCKED, before)
    finally:
        drop_schema()


if __name__ == "__main__":
    main()
