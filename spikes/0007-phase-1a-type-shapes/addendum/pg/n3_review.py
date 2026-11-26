"""N3: two checks from the independent review of PR #81 (ADR-0010).

(e) Two root tables that reference each other (ra.rb_id -> rb, rb.ra_id -> ra), each with an
    owned child table, deleted in one transaction: as two statements (each the WITH ... DELETE of
    one aggregate) in both orders, and as one merged statement. SERIALIZABLE, fresh data per run.
(f) A NON-OWNED insert racing a root delete. Platina's `insert(Payment(order_id=x))` does not bump
    the root's version. Writer T2: BEGIN; load the order; INSERT INTO payments; COMMIT. Deleter T1:
    BEGIN; load the order; WITH c1 AS (DELETE FROM items ...) DELETE FROM orders ...; COMMIT. Both
    SERIALIZABLE, or both REPEATABLE READ. Interleavings:
      insert-first  T2 inserts (uncommitted), T1 deletes (blocks on T2's FK lock); T2 COMMIT, T1 COMMIT
      delete-first  T1 deletes (uncommitted), T2 inserts (blocks); T1 COMMIT, T2 COMMIT
Usage: n3_review.py [REPEAT]   (default 3)
"""

import sys
import uuid

from common import Sess, Tally, admin, new_order, schema, temp_database
from n1_cte import attempt, cte

SER, RR = "SERIALIZABLE", "REPEATABLE READ"
LOAD = "SELECT version FROM orders WHERE id = %s"
DELETE = (
    "WITH c1 AS (DELETE FROM items WHERE order_id = ANY(%s)) DELETE FROM orders WHERE id = ANY(%s)"
)
INSERT = "INSERT INTO payments VALUES (%s, %s)"


def schema_mutual(a):
    a.execute("DROP TABLE IF EXISTS ra, rb, ra_child, rb_child CASCADE")
    a.execute("CREATE TABLE ra(id uuid PRIMARY KEY, rb_id uuid)")
    a.execute("CREATE TABLE rb(id uuid PRIMARY KEY, ra_id uuid REFERENCES ra(id))")
    a.execute("ALTER TABLE ra ADD CONSTRAINT ra_rb_id_fkey FOREIGN KEY (rb_id) REFERENCES rb(id)")
    a.execute("CREATE TABLE ra_child(id uuid PRIMARY KEY, ra_id uuid NOT NULL REFERENCES ra(id))")
    a.execute("CREATE TABLE rb_child(id uuid PRIMARY KEY, rb_id uuid NOT NULL REFERENCES rb(id))")
    a.execute("CREATE INDEX ON ra_child(ra_id)")
    a.execute("CREATE INDEX ON rb_child(rb_id)")


def data_mutual(a):
    ra, rb = uuid.uuid4(), uuid.uuid4()
    a.execute("INSERT INTO ra VALUES (%s, NULL)", (ra,))
    a.execute("INSERT INTO rb VALUES (%s, %s)", (rb, ra))
    a.execute("UPDATE ra SET rb_id = %s WHERE id = %s", (rb, ra))
    a.execute("INSERT INTO ra_child VALUES (%s, %s)", (uuid.uuid4(), ra))
    a.execute("INSERT INTO rb_child VALUES (%s, %s)", (uuid.uuid4(), rb))
    return ra, rb


def part_e(a, repeat, summary):
    schema_mutual(a)
    del_a = cte(
        ["DELETE FROM ra_child WHERE ra_id = ANY(%(ids)s)"],
        "DELETE FROM ra WHERE id = ANY(%(ids)s)",
    )
    del_b = cte(
        ["DELETE FROM rb_child WHERE rb_id = ANY(%(ids)s)"],
        "DELETE FROM rb WHERE id = ANY(%(ids)s)",
    )
    merged = cte(
        [
            "DELETE FROM ra_child WHERE ra_id = ANY(%(ids)s)",
            "DELETE FROM rb_child WHERE rb_id = ANY(%(ids)s)",
            "DELETE FROM ra WHERE id = ANY(%(ids)s)",
        ],
        "DELETE FROM rb WHERE id = ANY(%(ids)s)",
    )
    forms = {"two statements, ra first": [del_a, del_b], "two statements, rb first": [del_b, del_a]}
    forms["one merged statement"] = [merged]
    for form, statements in forms.items():
        for n in range(repeat):
            ra, rb = data_mutual(a)
            print(f"=== (e) {form}; run {n + 1}")
            result = attempt(statements, [ra, rb], diag=n == 0)
            left = a.execute(
                "SELECT (SELECT count(*) FROM ra WHERE id = %s) + (SELECT count(*) FROM rb WHERE id = %s)",
                (ra, rb),
            ).fetchone()
            line = f"{result} | ra+rb rows after {left[0] if left else '?'}"
            print(f"  {line}")
            summary.setdefault(form, {}).setdefault(line, 0)
            summary[form][line] += 1


def scenario_f(a, iso, inter):
    x, _ = new_order(a, 1)
    t1, t2 = Sess("T1 deleter"), Sess("T2 non-owned writer")
    begin = [(t1, f"BEGIN ISOLATION LEVEL {iso}", None), (t2, f"BEGIN ISOLATION LEVEL {iso}", None)]
    load = [(t1, LOAD, (x,)), (t2, LOAD, (x,))]
    ins, dele = [(t2, INSERT, (uuid.uuid4(), x))], [(t1, DELETE, ([x], [x]))]
    c1, c2 = [(t1, "COMMIT", None)], [(t2, "COMMIT", None)]
    if inter == "insert-first":
        steps = begin + load + ins + dele + c2 + c1
    else:
        steps = begin + load + dele + ins + c1 + c2
    for sess, stmt, params in steps:
        sess.go(stmt, params)
        for other in (t1, t2):
            if other is not sess:
                other.poll()
    t1.close()
    t2.close()
    return t1, t2


def main():
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    summary: dict[str, dict[str, int]] = {}
    tally = Tally()
    with temp_database("n3"):
        a = admin()
        part_e(a, repeat, summary)
        schema(a, alloc=False)
        a.execute(
            "CREATE TABLE payments(id uuid PRIMARY KEY, order_id uuid NOT NULL REFERENCES orders(id))"
        )
        a.execute("CREATE INDEX ON payments(order_id)")
        for iso in (SER, RR):
            for inter in ("insert-first", "delete-first"):
                label = f"(f) both {iso} | {inter}"
                for n in range(repeat):
                    print(f"=== {label}; run {n + 1}")
                    tally.add(label, *scenario_f(a, iso, inter))
        a.close()
    print("\n## summary (e): form | result x runs")
    for form, d in summary.items():
        for line, k in d.items():
            print(f"{form} | {line} x{k}")
    tally.print()


if __name__ == "__main__":
    main()
