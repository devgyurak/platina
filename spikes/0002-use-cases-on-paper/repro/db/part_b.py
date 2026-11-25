# TEMPORARY (spike 0002): the reproducer's code below is kept byte-identical, so lint and
# formatting are suppressed for this file until the maintainer decides how to treat it.
# ruff: noqa: RUF005
# fmt: off
"""Part B: the design 4.6 statement order (BEGIN; SET LOCAL; INSERT run_claim; SELECT FOR UPDATE; UPDATE; COMMIT)."""

import uuid

from harness import SCHEMA, admin, banner, create_schema, drop_schema, log
from script import RESUME, play

ACC, CLAIM = f"{SCHEMA}.acc", f"{SCHEMA}.run_claim"
LOCK = f"SELECT id, bal FROM {ACC} WHERE id = 1 FOR UPDATE"
UPD = f"UPDATE {ACC} SET bal = bal + 1 WHERE id = 1"
TIMEOUT = "SET LOCAL statement_timeout = '20s'"


def claim() -> str:
    return f"INSERT INTO {CLAIM}(id) VALUES ('{uuid.uuid7()}')"


def reset() -> None:
    admin(f"DROP TABLE IF EXISTS {ACC}, {CLAIM}")
    admin(f"CREATE TABLE {ACC} (id int PRIMARY KEY, bal int NOT NULL)")
    admin(f"CREATE TABLE {CLAIM} (id uuid PRIMARY KEY)")
    admin(f"INSERT INTO {ACC} VALUES (1, 0)")


def head(iso: str, first: str) -> list[str]:
    """Statements of 'round trip 1'. first='insert': design order. first='lock': FOR UPDATE first."""
    b = f"BEGIN ISOLATION LEVEL {iso}"
    if first == "insert":
        return [b, TIMEOUT, claim(), LOCK]
    return [b, TIMEOUT, LOCK, claim()]


def summary(tag: str, res: dict[str, str]) -> None:
    bal = admin(f"SELECT bal FROM {ACC} WHERE id = 1")[0][0]
    claims = admin(f"SELECT count(*) FROM {CLAIM}")[0][0]
    log(f"  SUMMARY {tag} | T1 {res['T1']} | T2 {res['T2']} | final bal = {bal}, run_claim rows = {claims}")


def t(name: str, stmts: list[str]) -> list[tuple[str, str]]:
    return [(name, s) for s in stmts]


def main() -> None:
    banner()
    create_schema()
    try:
        for iso in ("SERIALIZABLE", "REPEATABLE READ"):
            for first in ("insert", "lock"):
                tag = f"{iso} / T2 first data statement = {'INSERT run_claim (design 4.6 order)' if first == 'insert' else 'SELECT ... FOR UPDATE'}"

                # B1a: T1 has loaded FOR UPDATE (not yet updated) when T2 begins.
                reset()
                h1, h2 = head(iso, "insert"), head(iso, first)
                i = h2.index(LOCK)
                steps = t("T1", h1) + t("T2", h2[: i + 1]) + t("T1", [UPD, "COMMIT"]) \
                    + [("T2", RESUME)] + t("T2", h2[i + 1:] + [UPD, "COMMIT"])
                summary(f"B1a {tag}", play(f"B1a (T1 holds the FOR UPDATE lock, not yet updated, when T2 begins) {tag}", steps))

                # B1b: T1 has loaded and updated (not committed) when T2 begins.
                reset()
                h1, h2 = head(iso, "insert"), head(iso, first)
                steps = t("T1", h1 + [UPD]) + t("T2", h2[: i + 1]) + t("T1", ["COMMIT"]) \
                    + [("T2", RESUME)] + t("T2", h2[i + 1:] + [UPD, "COMMIT"])
                summary(f"B1b {tag}", play(f"B1b (T1 has locked and updated, uncommitted, when T2 begins) {tag}", steps))

                # B1c (extra): T1 only locks, commits without changing the row.
                reset()
                h1, h2 = head(iso, "insert"), head(iso, first)
                steps = t("T1", h1) + t("T2", h2[: i + 1]) + t("T1", ["COMMIT"]) \
                    + [("T2", RESUME)] + t("T2", h2[i + 1:] + [UPD, "COMMIT"])
                summary(f"B1c {tag}", play(f"B1c extra (T1 locks FOR UPDATE, commits WITHOUT updating the row) {tag}", steps))

                # B1d (extra): T1 locks, updates, rolls back.
                reset()
                h1, h2 = head(iso, "insert"), head(iso, first)
                steps = t("T1", h1 + [UPD]) + t("T2", h2[: i + 1]) + t("T1", ["ROLLBACK"]) \
                    + [("T2", RESUME)] + t("T2", h2[i + 1:] + [UPD, "COMMIT"])
                summary(f"B1d {tag}", play(f"B1d extra (T1 locks, updates, ROLLBACK) {tag}", steps))

                # B2: T2 begins only after T1 committed.
                reset()
                h1, h2 = head(iso, "insert"), head(iso, first)
                steps = t("T1", h1 + [UPD, "COMMIT"]) + t("T2", h2 + [UPD, "COMMIT"])
                summary(f"B2 {tag}", play(f"B2 (T2 begins after T1 committed) {tag}", steps))

            # B3 discriminators: which statement freezes the snapshot.
            # B3-gap: T2 has run BEGIN; SET LOCAL; INSERT run_claim. Then T1 runs completely. Then T2 locks.
            reset()
            h1, h2 = head(iso, "insert"), head(iso, "insert")
            steps = t("T2", h2[:3]) + t("T1", h1 + [UPD, "COMMIT"]) + t("T2", h2[3:] + [UPD, "COMMIT"])
            summary(f"B3-gap {iso}", play(f"B3-gap {iso}: T2 BEGIN+SET LOCAL+INSERT run_claim; T1 whole transaction; T2 SELECT FOR UPDATE", steps))

            # B3-setlocal: T2 has run only BEGIN; SET LOCAL. Then T1 runs completely. Then T2 INSERT + lock.
            reset()
            h1, h2 = head(iso, "insert"), head(iso, "insert")
            steps = t("T2", h2[:2]) + t("T1", h1 + [UPD, "COMMIT"]) + t("T2", h2[2:] + [UPD, "COMMIT"])
            summary(f"B3-setlocal {iso}", play(f"B3-setlocal {iso}: T2 BEGIN+SET LOCAL only; T1 whole transaction; T2 INSERT run_claim, SELECT FOR UPDATE", steps))

            # B3-select1: the spike script's snapshot statement, plain SELECT 1.
            reset()
            h1 = head(iso, "insert")
            steps = t("T2", [f"BEGIN ISOLATION LEVEL {iso}", "SELECT 1"]) + t("T1", h1 + [UPD, "COMMIT"]) \
                + t("T2", [f"SELECT bal FROM {ACC} WHERE id = 1", LOCK, UPD, "COMMIT"])
            summary(f"B3-select1 {iso}", play(f"B3-select1 {iso}: T2 BEGIN+SELECT 1; T1 whole transaction; T2 plain read, then FOR UPDATE", steps))

            # Extra X1: table lock BEFORE the snapshot (ADR-0005 alternative), then design order.
            reset()
            tl = f"LOCK TABLE {ACC} IN SHARE ROW EXCLUSIVE MODE"
            b = f"BEGIN ISOLATION LEVEL {iso}"
            steps = t("T1", [b, TIMEOUT, tl, claim(), LOCK, UPD]) + t("T2", [b, TIMEOUT, tl]) + t("T1", ["COMMIT"]) \
                + [("T2", RESUME)] + t("T2", [claim(), LOCK, UPD, "COMMIT"])
            summary(f"X1 {iso}", play(f"X1 extra {iso}: LOCK TABLE before the first query in both", steps))

            # Extra X1': the same table lock AFTER the run_claim INSERT (the design's first statement).
            reset()
            steps = t("T1", [b, TIMEOUT, claim(), tl, LOCK, UPD]) + t("T2", [b, TIMEOUT, claim(), tl]) + t("T1", ["COMMIT"]) \
                + [("T2", RESUME)] + t("T2", [LOCK, UPD, "COMMIT"])
            summary(f"X1' {iso}", play(f"X1' extra {iso}: LOCK TABLE after INSERT run_claim in both", steps))

            # Extra X2: advisory lock via SELECT as the first statement.
            reset()
            al = "SELECT pg_advisory_xact_lock(424242, 1)"
            steps = t("T1", [b, TIMEOUT, al, claim(), LOCK, UPD]) + t("T2", [b, TIMEOUT, al]) + t("T1", ["COMMIT"]) \
                + [("T2", RESUME)] + t("T2", [claim(), LOCK, UPD, "COMMIT"])
            summary(f"X2 {iso}", play(f"X2 extra {iso}: SELECT pg_advisory_xact_lock(...) as the first statement in both", steps))
    finally:
        drop_schema()


if __name__ == "__main__":
    main()
