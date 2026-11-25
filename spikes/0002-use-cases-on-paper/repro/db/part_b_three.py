# TEMPORARY (spike 0002): the reproducer's code below is kept byte-identical, so lint and
# formatting are suppressed for this file until the maintainer decides how to treat it.
# fmt: off
"""Extra: two waiters behind one for_update holder, design 4.6 statement order."""

import uuid

from harness import SCHEMA, admin, banner, create_schema, drop_schema, log
from script import RESUME, play

ACC, CLAIM = f"{SCHEMA}.acc", f"{SCHEMA}.run_claim"
LOCK = f"SELECT id, bal FROM {ACC} WHERE id = 1 FOR UPDATE"
UPD = f"UPDATE {ACC} SET bal = bal + 1 WHERE id = 1"


def head(iso: str, t: str) -> list[tuple[str, str]]:
    return [(t, f"BEGIN ISOLATION LEVEL {iso}"), (t, "SET LOCAL statement_timeout = '20s'"),
            (t, f"INSERT INTO {CLAIM}(id) VALUES ('{uuid.uuid7()}')"), (t, LOCK)]


def main() -> None:
    banner()
    create_schema()
    try:
        for iso in ("SERIALIZABLE", "REPEATABLE READ"):
            admin(f"DROP TABLE IF EXISTS {ACC}, {CLAIM}")
            admin(f"CREATE TABLE {ACC} (id int PRIMARY KEY, bal int NOT NULL)")
            admin(f"CREATE TABLE {CLAIM} (id uuid PRIMARY KEY)")
            admin(f"INSERT INTO {ACC} VALUES (1, 0)")
            steps = head(iso, "T1") + head(iso, "T2") + head(iso, "T3") + [("T1", UPD), ("T1", "COMMIT")]
            for t in ("T2", "T3"):
                steps += [(t, RESUME), (t, UPD), (t, "COMMIT")]
            play(f"{iso}: T1 holds the lock; T2 and T3 both begin and wait; T1 updates and commits", steps,
                 names=("T1", "T2", "T3"))
            log(f"  final bal = {admin(f'SELECT bal FROM {ACC} WHERE id = 1')[0][0]}")
    finally:
        drop_schema()


if __name__ == "__main__":
    main()
