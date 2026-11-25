# TEMPORARY (spike 0002): the reproducer's code below is kept byte-identical, so lint and
# formatting are suppressed for this file until the maintainer decides how to treat it.
# ruff: noqa: RUF005
# fmt: off
"""Part C: R3.7 - coupon redemption race under SERIALIZABLE. 40001 or 23505, and at which statement?

Each transaction: (1) read the coupon row, (2) read the user's redemption rows, (3) UPDATE coupon
used = used + 1, (4) INSERT redemption under UNIQUE (coupon_id, user_id), (5) COMMIT.
Both transactions read before either writes. T1 always reads first; `first` names the first writer.
"""

import sys

from harness import SCHEMA, Sess, admin, banner, create_schema, drop_schema, log
from script import RESUME, play

CP, RD, US = f"{SCHEMA}.coupon", f"{SCHEMA}.redemption", f"{SCHEMA}.users"
ISO = "SERIALIZABLE"
R1 = f"SELECT id, usage_limit, used, active FROM {CP} WHERE id = 1"
U = f"UPDATE {CP} SET used = used + 1 WHERE id = 1"
SUMMARY: list[str] = []
COMBOS = (("seq", "user"), ("seq", "key"), ("idx", "user"), ("uq", "key"))  # (data variant, step-2 read)


def r2(read: str, user: int) -> str:
    if read == "user":  # what the spike wrote: Load(User.redemptions), checked in Python
        return f"SELECT id, coupon_id FROM {RD} WHERE user_id = {user}"
    return f"SELECT id FROM {RD} WHERE coupon_id = 1 AND user_id = {user}"  # by the unique key


def ins(user: int) -> str:
    return f"INSERT INTO {RD}(coupon_id, user_id) VALUES (1, {user})"


def reset(data: str, idx_order: str) -> None:
    """Data variants.

    seq: 201 coupons, empty redemption, no user_id index (sequential scans, relation-level SIREAD).
    idx: 20000 coupons, 20000 redemptions, index on redemption(user_id), ANALYZE.
    uq:  20000 coupons, 20000 redemptions, NO user_id index, ANALYZE (a read by the key uses the unique index).
    """
    big = data in ("idx", "uq")
    admin(f"DROP TABLE IF EXISTS {RD}, {CP}, {US}")
    admin(f"CREATE TABLE {US} (id int PRIMARY KEY)")
    admin(f"CREATE TABLE {CP} (id int PRIMARY KEY, usage_limit int, used int NOT NULL DEFAULT 0, "
          f"active boolean NOT NULL DEFAULT true)")
    admin(f"INSERT INTO {US} SELECT g FROM generate_series(1, 2000) g")
    admin(f"INSERT INTO {CP}(id, usage_limit) SELECT g, 1 FROM generate_series(1, {20000 if big else 201}) g")
    uq = "CONSTRAINT redemption_coupon_user_key UNIQUE (coupon_id, user_id)"
    cols = (f"id uuid PRIMARY KEY DEFAULT uuidv7(), coupon_id int NOT NULL REFERENCES {CP}, "
            f"user_id int NOT NULL REFERENCES {US}")
    if data == "idx" and idx_order == "user-then-unique":
        admin(f"CREATE TABLE {RD} ({cols})")
        admin(f"CREATE INDEX redemption_user_idx ON {RD}(user_id)")
        admin(f"ALTER TABLE {RD} ADD {uq}")
    else:
        admin(f"CREATE TABLE {RD} ({cols}, {uq})")
        if data == "idx":
            admin(f"CREATE INDEX redemption_user_idx ON {RD}(user_id)")
    if big:
        admin(f"INSERT INTO {RD}(coupon_id, user_id) SELECT c, u FROM generate_series(2, 201) c, "
              f"generate_series(1001, 1100) u")
    admin(f"ANALYZE {US}")
    admin(f"ANALYZE {CP}")
    admin(f"ANALYZE {RD}")


def siread() -> str:
    return ("SELECT a.application_name, l.relation::regclass::text, l.locktype, l.page, l.tuple FROM pg_locks l "
            "JOIN pg_stat_activity a USING (pid) WHERE l.mode = 'SIReadLock' "
            f"AND l.relation::regclass::text LIKE '{SCHEMA}.%' ORDER BY 1, 2, 3, 4, 5")


def scenario(label: str, users: tuple[int, int], order: str, inter: str, first: str, read: str,
             data: str, idx_order: str = "unique-then-user") -> None:
    reset(data, idx_order)
    u = {"T1": users[0], "T2": users[1]}
    f, s = (first, "T2" if first == "T1" else "T1")
    w = {t: [{"U": U, "I": ins(u[t])}[c] for c in order] for t in ("T1", "T2")}
    title = (f"{label} | users T1={u['T1']} T2={u['T2']} | write order {order} | {inter} | first writer {f} "
             f"| step-2 read by {read} | data {data} | index order {idx_order if data == 'idx' else '-'}")
    plan1 = "; ".join(str(r[0]).strip() for r in admin("EXPLAIN (COSTS OFF) " + R1))
    plan = "; ".join(str(r[0]).strip() for r in admin("EXPLAIN (COSTS OFF) " + r2(read, u["T1"])))
    log(f"\n--- plan of step 1: {plan1}\n--- plan of step 2: {plan}")
    steps: list[tuple[str, str]] = []
    for t in ("T1", "T2"):
        steps += [(t, f"BEGIN ISOLATION LEVEL {ISO}"), (t, f"SET application_name = '{t}'"), (t, R1), (t, r2(read, u[t]))]
    steps.append(("@", siread()))
    fw, sw = [(f, x) for x in w[f]], [(s, x) for x in w[s]]
    if inter == "F-committed":      # the first writer has committed when the second writes
        steps += fw + [(f, "COMMIT")] + sw + [(s, "COMMIT")]
    elif inter == "S-after-F-w1":   # the second writes after the first's first write, first uncommitted
        steps += fw[:1] + sw[:1] + fw[1:] + [(f, "COMMIT"), (s, RESUME)] + sw[1:] + [(s, "COMMIT")]
    elif inter == "S-after-F-all":  # the second writes after all of the first's writes, first uncommitted
        steps += fw + sw[:1] + [(f, "COMMIT"), (s, RESUME)] + sw[1:] + [(s, "COMMIT")]
    elif inter == "F-rollback":     # sanity: the first writer rolls back
        steps += fw + sw[:1] + [(f, "ROLLBACK"), (s, RESUME)] + sw[1:] + [(s, "COMMIT")]
    else:
        raise ValueError(inter)
    res = play(title, steps)
    state = admin(f"SELECT (SELECT used FROM {CP} WHERE id = 1), "
                  f"(SELECT coalesce(array_agg(user_id ORDER BY user_id), '{{}}') FROM {RD} WHERE coupon_id = 1)")[0]
    for t in ("T1", "T2"):
        if res[t].startswith("FAILED"):
            r = Sess(f"retry-{t}")
            try:
                r.do(f"BEGIN ISOLATION LEVEL {ISO}")
                r.do(R1)
                r.do(r2(read, u[t]))
                r.do("ROLLBACK")
            finally:
                r.close()

    def short(x: str) -> str:
        x = x.replace(f"{SCHEMA}.", "")
        if x.startswith("FAILED at ["):
            stmt, rest = x[len("FAILED at ["):].split("]: ", 1)
            return f"FAILED at {stmt.split(' ')[0]}: {rest}"
        return x

    line = (f"SUMMARY | {title} | plan1: {plan1.replace(SCHEMA + '.', '')} | plan2: {plan.replace(SCHEMA + '.', '')} | T1: {short(res['T1'])} | T2: {short(res['T2'])} "
            f"| final coupon.used={state[0]} redemptions(coupon 1) users={state[1]}")
    log("  " + line)
    SUMMARY.append(line)


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    banner()
    create_schema()
    try:
        if which in ("all", "asked"):
            # As asked: UPDATE then INSERT.
            for users, label in (((7, 7), "C-same-user"), ((7, 1500), "C-two-users-limit-1")):
                for data, read in COMBOS:
                    if True:
                        for first in ("T1", "T2"):
                            for inter in ("F-committed", "S-after-F-w1", "S-after-F-all", "F-rollback"):
                                scenario(label, users, "UI", inter, first, read, data)
        if which in ("all", "extra"):
            # Extras: INSERT before UPDATE, and INSERT only (a once-per-customer coupon without a usage limit).
            for users, label in (((7, 7), "X-same-user"), ((7, 1500), "X-two-users")):
                for order in ("IU", "I"):
                    if order == "I" and users[0] != users[1]:
                        continue
                    for data, read in COMBOS:
                        if True:
                            for first in ("T1", "T2"):
                                inters = ["F-committed", "S-after-F-w1"] + (["S-after-F-all"] if order == "IU" else [])
                                for inter in inters:
                                    scenario(label, users, order, inter, first, read, data)
                                    if data == "idx" and read == "user" and users[0] == users[1]:
                                        scenario(label, users, order, inter, first, read, data, "user-then-unique")
    finally:
        drop_schema()
        log("\n".join(["", "=========== SUMMARY"] + SUMMARY))


if __name__ == "__main__":
    main()
