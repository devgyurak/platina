"""Spike 0004 reproduction: scenario declarations, written independently of `scenarios.py`."""

from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from registry import (
    VERSION_BODY_V1,
    VERSION_BODY_V2,
    Check,
    Col,
    Entity,
    Id,
    Index,
    Json,
    Unique,
    Xid8,
    column,
    embedded,
    fk,
    fn,
    pk,
    to_metadata,
    value,
    version_column,
)
from repro_harness import Scenario, State

UUID = "gen_random_uuid()"


# --------------------------------------------------------------------------- item 1
def customer(
    new_col: bool,
    extra: bool = False,
    table: str = "customers",
    old: str | None = None,
    opt: bool = False,
):
    def md(naming: str) -> sa.MetaData:
        class C(Entity, table=table, renamed_from=old):
            id: Col[Id[C]] = pk()
            if new_col and opt:
                full_name: Col[str | None] = column(length=100, renamed_from="name")
            elif new_col:
                full_name: Col[str] = column(length=100, renamed_from="name")
            elif opt:
                name: Col[str | None] = column(length=100)
            else:
                name: Col[str] = column(length=100)
            if extra:
                email: Col[str | None]

        return to_metadata(C, naming=naming)

    return md


def product(renamed: bool, opt: bool = False):
    def md(naming: str) -> sa.MetaData:
        class P(Entity, table="products"):
            id: Col[Id[P]] = pk()
            if renamed and opt:
                sku: Col[str | None] = column(length=40, renamed_from="code")
            elif renamed:
                sku: Col[str] = column(length=40, renamed_from="code")
            elif opt:
                code: Col[str | None] = column(length=10)
            else:
                code: Col[str] = column(length=10)

        return to_metadata(P, naming=naming)

    return md


def orders_fk(renamed: bool, opt: bool = False):
    def md(naming: str) -> sa.MetaData:
        class Customer(Entity, table="customers"):
            id: Col[Id[Customer]] = pk()
            name: Col[str] = column(length=100)

        if renamed:

            class Order(Entity, table="orders"):
                id: Col[Id[Order]] = pk()
                if opt:
                    buyer_id: Col[Id[Customer] | None] = fk(
                        lambda: Customer, renamed_from="customer_id"
                    )
                    quantity: Col[int | None] = column(renamed_from="qty")
                    reference: Col[str | None] = column(length=20, renamed_from="ref")
                else:
                    buyer_id: Col[Id[Customer]] = fk(lambda: Customer, renamed_from="customer_id")
                    quantity: Col[int] = column(renamed_from="qty")
                    reference: Col[str] = column(length=20, renamed_from="ref")

                class Meta:
                    checks = (Check(lambda: Order.quantity > 0),)
                    indexes = (Index(lambda: (Order.reference,)),)
        else:

            class Order(Entity, table="orders"):  # type: ignore[no-redef]
                id: Col[Id[Order]] = pk()
                if opt:
                    customer_id: Col[Id[Customer] | None] = fk(lambda: Customer)
                    qty: Col[int | None]
                    ref: Col[str | None] = column(length=20)
                else:
                    customer_id: Col[Id[Customer]] = fk(lambda: Customer)
                    qty: Col[int]
                    ref: Col[str] = column(length=20)

                class Meta:
                    checks = (Check(lambda: Order.qty > 0),)
                    indexes = (Index(lambda: (Order.ref,)),)

        return to_metadata(Customer, Order, naming=naming)

    return md


INS_CUST = f"INSERT INTO customers (id, name) VALUES ({UUID}, 'Ada')"
ITEM1 = [
    Scenario(
        "1a-column-rename",
        [
            State("create", customer(False)),
            State(
                "rename name->full_name",
                customer(True),
                before=[INS_CUST],
                probe=["SELECT full_name FROM customers"],
            ),
            State(
                "1e hint left + add email",
                customer(True, extra=True),
                probe=["SELECT full_name, email FROM customers"],
            ),
        ],
        probe_down=["SELECT * FROM customers"],
    ),
    Scenario(
        "1b-table-rename",
        [
            State("create", customer(False)),
            State(
                "rename customers->clients",
                customer(False, table="clients", old="customers"),
                before=[INS_CUST],
                probe=["SELECT name FROM clients"],
            ),
            State(
                "1e hint left + add email",
                customer(False, extra=True, table="clients", old="customers"),
                probe=["SELECT name, email FROM clients"],
            ),
        ],
        probe_down=[
            "SELECT relname FROM pg_class WHERE relname IN ('customers','clients') AND relnamespace = 'public'::regnamespace"
        ],
    ),
    Scenario(
        "1c-rename-and-type",
        [
            State("create", product(False)),
            State(
                "rename code varchar(10) -> sku varchar(40)",
                product(True),
                before=[f"INSERT INTO products (id, code) VALUES ({UUID}, 'AB-1')"],
                probe=["SELECT sku FROM products"],
                show=("column",),
            ),
        ],
        probe_down=["SELECT * FROM products"],
    ),
    Scenario(
        "1d-rename-fk-ck-ix",
        [
            State("create", orders_fk(False)),
            State(
                "rename customer_id/qty/ref",
                orders_fk(True),
                before=[
                    INS_CUST,
                    "INSERT INTO orders (id, customer_id, qty, ref) SELECT "
                    f"{UUID}, id, 3, 'R-1' FROM customers",
                ],
                probe=["SELECT buyer_id IS NOT NULL, quantity, reference FROM orders"],
            ),
        ],
        probe_down=["SELECT * FROM orders"],
    ),
]


ITEM1 += [
    Scenario(
        "1a-nullable-column-rename",
        [
            State("create (nullable)", customer(False, opt=True)),
            State(
                "rename name->full_name",
                customer(True, opt=True),
                before=[INS_CUST],
                probe=["SELECT full_name FROM customers"],
            ),
        ],
        probe_down=["SELECT * FROM customers"],
    ),
    Scenario(
        "1c-nullable-rename-and-type",
        [
            State("create (nullable)", product(False, opt=True)),
            State(
                "rename code varchar(10) -> sku varchar(40)",
                product(True, opt=True),
                before=[f"INSERT INTO products (id, code) VALUES ({UUID}, 'AB-1')"],
                probe=["SELECT sku FROM products"],
            ),
        ],
        probe_down=["SELECT * FROM products"],
    ),
    Scenario(
        "1d-nullable-rename-fk-ck-ix",
        [
            State("create (nullable)", orders_fk(False, opt=True)),
            State(
                "rename customer_id/qty/ref",
                orders_fk(True, opt=True),
                before=[
                    INS_CUST,
                    "INSERT INTO orders (id, customer_id, qty, ref) SELECT "
                    f"{UUID}, id, 3, 'R-1' FROM customers",
                ],
                probe=["SELECT buyer_id, quantity, reference FROM orders"],
            ),
        ],
        probe_down=["SELECT * FROM orders"],
    ),
]


# --------------------------------------------------------------------------- item 2
def money_order(qty_check: str | None):
    def md(naming: str) -> sa.MetaData:
        @value
        class Money:
            amount: Col[Decimal]
            currency: Col[str] = column(length=3)

        extra = {
            None: (),
            "gt0": (Check(lambda: Order.quantity > 0),),
            "ge0": (Check(lambda: Order.quantity >= 0),),
        }[qty_check]

        class Order(Entity, table="orders"):
            id: Col[Id[Order]] = pk()
            total: Col[Money] = embedded(prefix="total_")
            quantity: Col[int]

            class Meta:
                checks = (Check(lambda: Order.total.path(Money.amount) >= Decimal(0)), *extra)

        return to_metadata(Order, naming=naming)

    return md


ITEM2 = [
    Scenario(
        "2-check",
        [
            State("create with path check", money_order(None), show=("constraint",)),
            State("add quantity > 0", money_order("gt0"), show=("constraint",)),
            State("change to quantity >= 0", money_order("ge0"), show=("constraint",)),
            State("remove quantity check", money_order(None), show=("constraint",)),
        ],
    )
]


# --------------------------------------------------------------------------- item 3
def versioned(order: bool, customer: bool, body: str):
    def md(naming: str) -> sa.MetaData:
        if customer:

            class Customer(Entity, table="customers"):
                id: Col[Id[Customer]] = pk()
                name: Col[str | None]
                version: Col[int] = version_column()
        else:

            class Customer(Entity, table="customers"):  # type: ignore[no-redef]
                id: Col[Id[Customer]] = pk()
                name: Col[str | None]

        if order:

            class Order(Entity, table="orders"):
                id: Col[Id[Order]] = pk()
                note: Col[str | None]
                version: Col[int] = version_column()
        else:

            class Order(Entity, table="orders"):  # type: ignore[no-redef]
                id: Col[Id[Order]] = pk()
                note: Col[str | None]

        return to_metadata(Customer, Order, naming=naming, version_body=body)

    return md


BUMP = "UPDATE orders SET note = note || 'x' RETURNING version"
TRIG = ("trigger", "function")
ITEM3 = [
    Scenario(
        "3-version-trigger",
        [
            State(
                "create orders with version",
                versioned(True, False, VERSION_BODY_V1),
                before=[],
                show=TRIG,
                probe=[f"INSERT INTO orders (id, note) VALUES ({UUID}, 'a')", BUMP],
            ),
            State(
                "body V2",
                versioned(True, False, VERSION_BODY_V2),
                show=TRIG,
                probe=["UPDATE orders SET version = 0 RETURNING version"],
            ),
            State("add version to customers", versioned(True, True, VERSION_BODY_V2), show=TRIG),
            State("remove from customers", versioned(True, False, VERSION_BODY_V2), show=TRIG),
            State("remove last (orders)", versioned(False, False, VERSION_BODY_V2), show=TRIG),
        ],
        probe_down=[
            "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT tgisinternal AND c.relnamespace = 'public'::regnamespace ORDER BY 1",
            "SELECT md5(prosrc) FROM pg_proc WHERE proname = 'platina_bump_version' "
            "AND pronamespace = 'public'::regnamespace",
        ],
    )
]


# --------------------------------------------------------------------------- item 4
def users(desc: bool, expr: str | None, where: str | None):
    def md(naming: str) -> sa.MetaData:
        class User(Entity, table="users"):
            id: Col[Id[User]] = pk()
            email: Col[str] = column(length=200)
            name: Col[str] = column(length=100)
            status: Col[str] = column(length=20)
            created_at: Col[datetime]

            class Meta:
                indexes = (
                    Index(lambda: (User.created_at.desc() if desc else User.created_at,)),
                    *(
                        (Index(lambda: (getattr(fn, expr)(User.email),), unique=True),)
                        if expr
                        else ()
                    ),
                    *(
                        (Index(lambda: (User.name,), where=lambda: User.status == where),)
                        if where
                        else ()
                    ),
                )

        return to_metadata(User, naming=naming)

    return md


ITEM4 = [
    Scenario(
        "4-indexes",
        [
            State("create with desc index", users(True, None, None), show=("index",)),
            State("add unique lower(email)", users(True, "lower", None), show=("index",)),
            State(
                "add partial name WHERE status='active'",
                users(True, "lower", "active"),
                show=("index",),
            ),
            State("expression only lower->upper", users(True, "upper", "active"), show=("index",)),
            State("WHERE only active->pending", users(True, "upper", "pending"), show=("index",)),
            State("desc only desc->asc", users(False, "upper", "pending"), show=("index",)),
        ],
    )
]


# --------------------------------------------------------------------------- item 5
def internal(
    later: bool,
    scheme: str = "",
    outbox_pk_ts: bool = True,
    outbox_uq: str = "",
    topic_ix: bool = True,
):
    def md(naming: str) -> sa.MetaData:
        class RunClaim(Entity, table="run_claim", partition_by=scheme or "RANGE (id)"):
            id: Col[Id[RunClaim]] = pk()
            claimed_at: Col[datetime] = column(server_default="now()")

            class Meta:
                indexes = (Index(lambda: (RunClaim.claimed_at,)),) if later else ()

        class RunResult(Entity, table="run_result"):
            run_id: Col[Id[RunClaim]] = pk()
            result: Col[Json]
            created_at: Col[datetime] = column(server_default="now()")

        class Outbox(Entity, table="outbox_log", partition_by="RANGE (created_at)"):
            id: Col[Id[Outbox]] = pk()
            created_at: Col[datetime] = column(primary_key=outbox_pk_ts, server_default="now()")
            xid: Col[Xid8]
            topic: Col[str]
            payload: Col[Json]
            if later:
                headers: Col[Json | None]

            class Meta:
                indexes = (Index(lambda: (Outbox.topic,)),) if topic_ix else ()
                uniques = {
                    "": (),
                    "topic": (Unique(lambda: (Outbox.topic,)),),
                    "topic_ts": (Unique(lambda: (Outbox.topic, Outbox.created_at)),),
                }[outbox_uq]

        class Job(Entity, table="job"):
            id: Col[Id[Job]] = pk()
            kind: Col[str]
            state: Col[str]
            run_at: Col[datetime]
            if later:
                attempts: Col[int | None]

        class Checkpoint(Entity, table="consumer_checkpoint"):
            consumer: Col[str] = column(primary_key=True)
            last_xid: Col[Xid8]
            updated_at: Col[datetime]

        ents: list[type] = [RunClaim, RunResult, Outbox, Job, Checkpoint]
        return to_metadata(*ents, naming=naming)

    return md


PARTS = [
    "CREATE TABLE run_claim_p0 PARTITION OF run_claim FOR VALUES FROM (MINVALUE) "
    "TO ('019a0000-0000-7000-8000-000000000000')",
    "CREATE TABLE outbox_log_2026_11 PARTITION OF outbox_log "
    "FOR VALUES FROM ('2026-11-01 00:00+00') TO ('2026-12-01 00:00+00')",
    "CREATE TABLE outbox_log_2026_12 PARTITION OF outbox_log "
    "FOR VALUES FROM ('2026-12-01 00:00+00') TO ('2027-01-01 00:00+00')",
]
ALL = ("table", "column", "constraint", "index")
INS_OUTBOX = (
    "INSERT INTO outbox_log (id, xid, topic, payload, created_at) VALUES "
    f"({UUID}, pg_current_xact_id(), 't', '{{}}', '2026-11-25') "
    "RETURNING tableoid::regclass::text"
)
AFTER_LATER = [
    "SELECT attrelid::regclass::text, attname FROM pg_attribute "
    "WHERE attname = 'headers' AND attrelid::regclass::text NOT LIKE 'ref.%' ORDER BY 1",
    "SELECT count(*) FROM outbox_log",
]
PARTS_NOW = [
    "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
    "AND relispartition ORDER BY 1",
    "SELECT count(*) FROM outbox_log",
]
LATER = "later change: job.attempts, outbox.headers, run_claim index"
ITEM5 = [
    Scenario(
        "5-internal-noparts",
        [
            State("create five internal tables", internal(False), show=ALL),
            State(
                "scheme change run_claim RANGE(id) -> HASH(id)",
                internal(False, scheme="HASH (id)"),
                dry_only=True,
            ),
            State(LATER, internal(True), show=("column", "index")),
        ],
    ),
    Scenario(
        "5-internal-parts",
        [
            State(
                "create five internal tables",
                internal(False),
                outside=PARTS,
                show=ALL,
                probe=[INS_OUTBOX],
            ),
            State(LATER, internal(True), probe=AFTER_LATER),
        ],
        probe_down=PARTS_NOW,
    ),
    Scenario(
        "5-internal-parts-no-parent-index",
        [
            State(
                "create five internal tables (no outbox topic index)",
                internal(False, topic_ix=False),
                outside=PARTS,
                show=("table",),
                probe=[INS_OUTBOX],
            ),
            State(LATER, internal(True, topic_ix=False), show=("table",), probe=AFTER_LATER),
        ],
        probe_down=PARTS_NOW,
    ),
    Scenario(
        "5-pk-unique-partition-key",
        [
            State("outbox pk (id) only, RANGE(created_at)", internal(False, outbox_pk_ts=False)),
            State("outbox UNIQUE(topic) without partition key", internal(False, outbox_uq="topic")),
            State(
                "outbox UNIQUE(topic, created_at)",
                internal(False, outbox_uq="topic_ts"),
                show=("constraint",),
            ),
        ],
    ),
]


# --------------------------------------------------------------------------- item 6
def stock(unique: bool):
    def md(naming: str) -> sa.MetaData:
        class Warehouse(Entity, table="warehouses"):
            id: Col[Id[Warehouse]] = pk()

        class Variant(Entity, table="variants"):
            id: Col[Id[Variant]] = pk()

        class Stock(Entity, table="stock"):
            id: Col[Id[Stock]] = pk()
            warehouse_id: Col[Id[Warehouse]] = fk(lambda: Warehouse)
            variant_id: Col[Id[Variant]] = fk(lambda: Variant)
            quantity: Col[int]
            allocated: Col[int]

            class Meta:
                checks = (Check(lambda: Stock.allocated <= Stock.quantity),)
                uniques = (
                    (Unique(lambda: (Stock.warehouse_id, Stock.variant_id)),) if unique else ()
                )

        return to_metadata(Warehouse, Variant, Stock, naming=naming)

    return md


ITEM6 = [
    Scenario(
        "6-stock",
        [
            State("create with allocated <= quantity", stock(False), show=("constraint",)),
            State("add unique (warehouse_id, variant_id)", stock(True), show=("constraint",)),
            State("remove unique", stock(False), show=("constraint",)),
        ],
    )
]

ITEMS = {"1": ITEM1, "2": ITEM2, "3": ITEM3, "4": ITEM4, "5": ITEM5, "6": ITEM6}


# --------------------------------------------------------------------------- item 1b, extra case
def customer_uq_fk(renamed: bool):
    """Renamed table with a convention-named unique column, referenced by a foreign key."""

    def md(naming: str) -> sa.MetaData:
        table, old = ("clients", "customers") if renamed else ("customers", None)

        class C(Entity, table=table, renamed_from=old):
            id: Col[Id[C]] = pk()
            name: Col[str] = column(length=100)
            email: Col[str] = column(length=200, unique=True)

        class Order(Entity, table="orders"):
            id: Col[Id[Order]] = pk()
            customer_id: Col[Id[C]] = fk(lambda: C)

        return to_metadata(C, Order, naming=naming)

    return md


ITEMS["1bx"] = [
    Scenario(
        "1b-rename-unique-fk",
        [
            State("create customers(email unique) + orders(fk)", customer_uq_fk(False)),
            State(
                "rename customers->clients",
                customer_uq_fk(True),
                before=[
                    f"INSERT INTO customers (id, name, email) VALUES ({UUID}, 'Ada', 'ada@x')",
                    f"INSERT INTO orders (id, customer_id) SELECT {UUID}, id FROM customers",
                ],
                probe=[
                    "SELECT c.name, c.email, o.customer_id = c.id FROM clients c "
                    "JOIN orders o ON o.customer_id = c.id"
                ],
            ),
            State(
                "same declaration again (apply the leftover operations)",
                customer_uq_fk(True),
                probe=[
                    "SELECT c.name, c.email FROM clients c JOIN orders o ON o.customer_id = c.id"
                ],
            ),
        ],
        probe_down=[
            "SELECT c.name, c.email FROM customers c JOIN orders o ON o.customer_id = c.id"
        ],
    )
]
