"""N1: one statement for the cascade and the root delete (data-modifying CTEs), SERIALIZABLE.

(a) A root that references its own owned child: users.default_address_id -> addresses,
    addresses.user_id -> users; each user's default address is one of its own addresses.
(b) Sibling owned tables with an FK between them: shipment_lines.shipment_id -> shipments, both
    owned by orders (plus items and tickets); every permutation of the CTE order.
(c) (a) and (b) with ON DELETE RESTRICT on every FK ('restrict-all') and on the inner FK only
    ('restrict-inner': users.default_address_id, shipment_lines.shipment_id).
(d) A non-owned referrer still present (allocations.item_id -> items): the CTE fails with 23503.
Each attempt is one transaction on fresh data (2 roots, deleted together with = ANY($1)).
Usage: n1_cte.py [REPEAT]   (default 3)
"""

import itertools
import sys
import uuid

import common
import psycopg
from common import admin, temp_database

ACTIONS = ["no action", "restrict-all", "restrict-inner"]


def act(action, inner):
    if action == "restrict-all" or (action == "restrict-inner" and inner):
        return " ON DELETE RESTRICT"
    return ""  # NO ACTION (the default), NOT DEFERRABLE


def schema_users(a, action):
    a.execute("DROP TABLE IF EXISTS users, addresses CASCADE")
    a.execute(
        "CREATE TABLE users(id uuid PRIMARY KEY, version int NOT NULL DEFAULT 1, default_address_id uuid)"
    )
    a.execute(
        "CREATE TABLE addresses(id uuid PRIMARY KEY, "
        f"user_id uuid NOT NULL REFERENCES users(id){act(action, False)})"
    )
    a.execute("CREATE INDEX ON addresses(user_id)")
    a.execute(
        "ALTER TABLE users ADD CONSTRAINT users_default_address_fkey FOREIGN KEY "
        f"(default_address_id) REFERENCES addresses(id){act(action, True)}"
    )


def data_users(a):
    users = []
    for _ in range(2):
        u, ad1, ad2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        a.execute("INSERT INTO users(id) VALUES (%s)", (u,))
        a.execute("INSERT INTO addresses VALUES (%s, %s), (%s, %s)", (ad1, u, ad2, u))
        a.execute("UPDATE users SET default_address_id = %s WHERE id = %s", (ad1, u))
        users.append(u)
    return users


def counts_users(a, ids):
    return a.execute(
        "SELECT (SELECT count(*) FROM users WHERE id = ANY(%s)), "
        "(SELECT count(*) FROM addresses WHERE user_id = ANY(%s))",
        (ids, ids),
    ).fetchone()


ORDER_CHILDREN = {
    "items": "DELETE FROM items WHERE order_id = ANY(%(ids)s)",
    "tickets": "DELETE FROM tickets WHERE order_id = ANY(%(ids)s)",
    "shipments": "DELETE FROM shipments WHERE order_id = ANY(%(ids)s)",
    "shipment_lines": "DELETE FROM shipment_lines WHERE order_id = ANY(%(ids)s)",
}
ROOT = "DELETE FROM orders WHERE id = ANY(%(ids)s)"


def schema_orders(a, action):
    a.execute(
        "DROP TABLE IF EXISTS allocations, shipment_lines, shipments, tickets, items, orders CASCADE"
    )
    a.execute("CREATE TABLE orders(id uuid PRIMARY KEY, version int NOT NULL DEFAULT 1)")
    for t in ("items", "tickets", "shipments"):
        a.execute(
            f"CREATE TABLE {t}(id uuid PRIMARY KEY, "
            f"order_id uuid NOT NULL REFERENCES orders(id){act(action, False)})"
        )
        a.execute(f"CREATE INDEX ON {t}(order_id)")
    a.execute(
        "CREATE TABLE shipment_lines(id uuid PRIMARY KEY, "
        f"order_id uuid NOT NULL REFERENCES orders(id){act(action, False)}, "
        f"shipment_id uuid NOT NULL REFERENCES shipments(id){act(action, True)})"
    )
    a.execute("CREATE INDEX ON shipment_lines(order_id)")
    a.execute("CREATE INDEX ON shipment_lines(shipment_id)")
    a.execute(
        "CREATE TABLE allocations(id uuid PRIMARY KEY, item_id uuid NOT NULL REFERENCES items(id))"
    )


def data_orders(a, allocation=False):
    ids = []
    for _ in range(2):
        o = uuid.uuid4()
        a.execute("INSERT INTO orders(id) VALUES (%s)", (o,))
        item = uuid.uuid4()
        a.execute("INSERT INTO items VALUES (%s, %s), (%s, %s)", (item, o, uuid.uuid4(), o))
        a.execute("INSERT INTO tickets VALUES (%s, %s)", (uuid.uuid4(), o))
        for _ in range(2):
            s = uuid.uuid4()
            a.execute("INSERT INTO shipments VALUES (%s, %s)", (s, o))
            a.execute(
                "INSERT INTO shipment_lines VALUES (%s, %s, %s), (%s, %s, %s)",
                (uuid.uuid4(), o, s, uuid.uuid4(), o, s),
            )
        if allocation:
            a.execute("INSERT INTO allocations VALUES (%s, %s)", (uuid.uuid4(), item))
        ids.append(o)
    return ids


def counts_orders(a, ids):
    return a.execute(
        "SELECT (SELECT count(*) FROM orders WHERE id = ANY(%(i)s)), "
        "(SELECT count(*) FROM items WHERE order_id = ANY(%(i)s)), "
        "(SELECT count(*) FROM tickets WHERE order_id = ANY(%(i)s)), "
        "(SELECT count(*) FROM shipments WHERE order_id = ANY(%(i)s)), "
        "(SELECT count(*) FROM shipment_lines WHERE order_id = ANY(%(i)s))",
        {"i": ids},
    ).fetchone()


def cte(children, root):
    parts = [f"c{n} AS ({s})" for n, s in enumerate(children, 1)]
    return "WITH " + ", ".join(parts) + " " + root


def attempt(statements, ids, diag=False):
    """Run the statements in one SERIALIZABLE transaction; return a one-line result."""
    out = []
    with psycopg.connect(common.DSN, autocommit=True) as c:
        c.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
        for n, s in enumerate(statements, 1):
            try:
                cur = c.execute(s, {"ids": ids})
                out.append(f"stmt{n} {cur.statusmessage}")
            except psycopg.Error as e:
                d = e.diag
                out.append(
                    f"stmt{n} ERROR {e.sqlstate} table_name={d.table_name} "
                    f"constraint_name={d.constraint_name}"
                )
                if diag:
                    print(
                        f"      {type(e).__name__}: {d.message_primary} | DETAIL: {d.message_detail}"
                    )
                    print(
                        f"      diag: schema_name={d.schema_name!r} table_name={d.table_name!r} "
                        f"constraint_name={d.constraint_name!r} column_name={d.column_name!r} "
                        f"source_function={d.source_function!r}"
                    )
                break
        r = c.execute("COMMIT").statusmessage
        out.append(f"COMMIT -> {r}")
    return "; ".join(out)


def main():
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    summary: dict[tuple[str, str, str], dict[str, int]] = {}

    def record(case, action, form, result, rows):
        d = summary.setdefault((case, action, form), {})
        key = f"{result} | rows after {rows}"
        d[key] = d.get(key, 0) + 1

    with temp_database("n1"):
        a = admin()
        for action in ACTIONS:
            schema_users(a, action)
            addr = "DELETE FROM addresses WHERE user_id = ANY(%(ids)s)"
            usr = "DELETE FROM users WHERE id = ANY(%(ids)s)"
            forms = {
                "separate: addresses; users": [addr, usr],
                "separate: users; addresses": [usr, addr],
                "CTE: WITH addresses DELETE users": [cte([addr], usr)],
                "CTE: WITH users DELETE addresses": [cte([usr], addr)],
            }
            for form, stmts in forms.items():
                for _ in range(repeat):
                    ids = data_users(a)
                    res = attempt(stmts, ids)
                    record("(a) users <-> addresses", action, form, res, counts_users(a, ids))
            schema_orders(a, action)
            sep = {
                "separate: shipments; shipment_lines; items; tickets; orders": [
                    ORDER_CHILDREN[t] for t in ("shipments", "shipment_lines", "items", "tickets")
                ]
                + [ROOT],
                "separate: shipment_lines; shipments; items; tickets; orders": [
                    ORDER_CHILDREN[t] for t in ("shipment_lines", "shipments", "items", "tickets")
                ]
                + [ROOT],
            }
            for form, stmts in sep.items():
                for _ in range(repeat):
                    ids = data_orders(a)
                    record(
                        "(b) shipments/lines",
                        action,
                        form,
                        attempt(stmts, ids),
                        counts_orders(a, ids),
                    )
            for perm in itertools.permutations(ORDER_CHILDREN):
                form = "CTE: WITH " + ", ".join(perm) + " DELETE orders"
                stmt = cte([ORDER_CHILDREN[t] for t in perm], ROOT)
                for _ in range(repeat):
                    ids = data_orders(a)
                    record(
                        "(b) shipments/lines",
                        action,
                        form,
                        attempt([stmt], ids),
                        counts_orders(a, ids),
                    )
        print("=== (d) allocations row references an owned item (NO ACTION everywhere)")
        schema_orders(a, "no action")
        stmt = cte([ORDER_CHILDREN[t] for t in ORDER_CHILDREN], ROOT)
        print(f"    statement: {stmt}")
        for _ in range(repeat):
            ids = data_orders(a, allocation=True)
            res = attempt([stmt], ids, diag=True)
            record(
                "(d) allocations referrer",
                "no action",
                "CTE (all children + root)",
                res,
                counts_orders(a, ids),
            )
        a.close()
    print("\n## summary: case | FK actions | form | result | (rows of the roots after) x runs")
    print(
        "## (a) rows = (users, addresses); (b)/(d) rows = (orders, items, tickets, shipments, lines)"
    )
    for (case, action, form), d in summary.items():
        for k, n in d.items():
            print(f"{case} | {action} | {form} | {k} x{n}")


if __name__ == "__main__":
    main()
