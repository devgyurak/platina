# TEMPORARY (spike 0002): the reproducer's code below is kept byte-identical, so lint and
# formatting are suppressed for this file until the maintainer decides how to treat it.
# fmt: off
"""Extra: a for_update waiter whose statement_timeout expires before the holder commits."""

import uuid

from harness import SCHEMA, admin, banner, create_schema, drop_schema
from script import RESUME, play

ACC, CLAIM = f"{SCHEMA}.acc", f"{SCHEMA}.run_claim"
LOCK = f"SELECT id, bal FROM {ACC} WHERE id = 1 FOR UPDATE"
UPD = f"UPDATE {ACC} SET bal = bal + 1 WHERE id = 1"


def main() -> None:
    banner()
    create_schema()
    try:
        admin(f"CREATE TABLE {ACC} (id int PRIMARY KEY, bal int NOT NULL)")
        admin(f"CREATE TABLE {CLAIM} (id uuid PRIMARY KEY)")
        admin(f"INSERT INTO {ACC} VALUES (1, 0)")
        b = "BEGIN ISOLATION LEVEL SERIALIZABLE"
        steps = [("T1", b), ("T1", "SET LOCAL statement_timeout = '20s'"),
                 ("T1", f"INSERT INTO {CLAIM}(id) VALUES ('{uuid.uuid7()}')"), ("T1", LOCK),
                 ("T2", b), ("T2", "SET LOCAL statement_timeout = '2s'"),
                 ("T2", f"INSERT INTO {CLAIM}(id) VALUES ('{uuid.uuid7()}')"), ("T2", LOCK),
                 ("T2", RESUME),  # T1 has NOT committed: T2 can only come back through its timeout
                 ("T1", UPD), ("T1", "COMMIT")]
        play("T2 waits on T1's FOR UPDATE lock longer than T2's statement_timeout (2s)", steps)
    finally:
        drop_schema()


if __name__ == "__main__":
    main()
