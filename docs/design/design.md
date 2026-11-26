# Platina design document
Translations: [Korean](design-KO.md)

> **Platina**: the old Spanish name for platinum. Just as platinum does not dissolve in acid and does not react, domain code does not react with the DB.
> A document written from the perspective of a backend developer coming from Spring + JPA. It starts from the pain points of existing Python ORMs, sets out a design philosophy, researches the open questions, and reaches decisions.
>
> Written: 2026-11-24 · Status: design finalized (pre-prototype) · Revisions: added composition semantics, internal architecture, test strategy → incorporated 5 external reviews (call and write syntax, dependent loads, identity model, run ID, internal table rule, job pipeline, schema tooling hybrid)

---

## Decision summary

| Area | Decision |
|---|---|
| Form | **Standalone ORM** (query compiler and execution engine implemented in-house). Only DDL, reflection and migrations use SQLAlchemy Core + Alembic, as the optional extra `platina[migrate]` |
| Name | **Platina** (package `platina`, CLI `platina`). Free on PyPI, no library of the same name on GitHub |
| License | **Apache-2.0** |
| Python | **3.14 or later** |
| DB | **PostgreSQL first**. MySQL and MariaDB support is planned, timing undecided (some features in reduced mode) |
| Driver | **psycopg 3.3 or later**, the only driver (sync, async, pipeline, COPY, t-string) |
| Load declaration | `Annotated[Order, Load(...)]` + `type` aliases. Dependent loads are also declared (`Load.when` expression / `Load.after` function). No generators → the number of round-trip stages is fixed at seal |
| Validation time | Not at import time but at **seal time** (`app.seal()` at app startup) + CLI `platina check` |
| Default isolation level | Command: **SERIALIZABLE + automatic retry** (escape hatch from SSI's read/write-dependency failures is REPEATABLE READ + version). Query: READ COMMITTED |
| External IO | Forbidden inside use cases. External IO happens only in **process handlers** |
| Composition | Steps only via **`with chain(a, b) as (c, a, b)`**. Rebinding the same names to latest-state views; aliases blocked by move marks. `+` only within a single step |
| Call and write | `app.run(uc.bind(...), options)`. A ref is a placeholder that is an entity at the type level (JPA `getReference`, `.set` not allowed). Entities inherit `Entity`; fields are `Col[T]`, read on the class as `Column[Owner, T]`. Creation via the keyword constructor `Order(...)`; a loaded row is modified with `.set(Order.status.to(...))` and deleted with `.delete()`, a new row is written with `insert(order, *children)`; owned rows only through their root ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed); embedded paths `Order.total.path(Money.amount)` |
| Commit order | Topological sort of the FK and unique key dependency graph + batching |
| Round trips | 1 load batch + 1 commit batch (including writes, COMMIT and the LSN query) |
| Run ID | Every `app.run` has a run ID (caller idempotency key or automatic uuid7). Claimed by INSERT without a lookup → idempotency and commit-outcome resolution (rerun) unified |
| Internal table rule | Internal append-only tables (run ID, outbox, jobs, completion records) are not read inside SERIALIZABLE. INSERT only |
| Projections | **inline** by default. Declare `into` and `key`; the body is field operations only. Inline keys are entity IDs only (date or constant keys need async or an opt-in with a reason); retry-rate metric |
| Identity | Committed? = **run ID**, consumer progress = **xid**, replication = **LSN**, order = **version**. Token = (xid, LSN) |
| Outbox and consumption | **Append-only event log** (xid watermark). Projections are serial consumers (checkpoint and effect in one transaction); `then` and `@process` use a two-tier job pipeline (short lease, unique INSERT fencing, per-aggregate ordering, dead-letter). `@process` returns a description |
| Migrations | Entity registry → SQLAlchemy `MetaData` → Alembic autogenerate (optional extra). Fidelity: partly ([spike 0004](../spikes/0004-alembic-round-trip.md)); Platina adds a rename rewrite (#70) and trigger operations, open choices in #25 and #70 |
| Codegen | Type inference against a temporary DB; **generated output is committed** (no DB needed in CI or deployment) |
| Async | Written against the anyio API; backend is asyncio (+uvloop). trio not supported |
| free-threaded | Core is a CI target on 3.14t; official driver support after psycopg ships wheels |
| Codebase | sans-IO core (an engine that yields commands) + thin sync/async runners; boundaries enforced by import-linter |
| Testing | Core without a DB (property-based, exhaustive error injection); DB semantics against real PostgreSQL. No in-memory fake DB |

---

## 0. Background: why build a new one

### Common problems of existing Python ORMs
- **No standard**: there is no spec like JPA, so semantics differ from ORM to ORM (a mix of ORMs with a persistence context and ORMs without one)
- **No transaction or DI integration**: no declarative boundary like `@Transactional`, no propagation attributes
- **Thin surrounding ecosystem** compared to Java: caching, observability, connection pooling, auditing, multi-tenancy
- **Fragmented async ecosystem**: SQLAlchemy (greenlet bridge), Django (delegation to a thread pool), Tortoise (shallow features)
- **Maintenance risk**: many depend on a single core maintainer

### Assessment of SQLAlchemy
The engine (unit of work, identity map, loading strategies) is on par with Hibernate. However:
- Dangerous defaults (`lazy="select"`, `expire_on_commit=True`, autoflush)
- A wide API surface (Core/ORM, 1.x/2.0 coexisting)
- Session and transaction boundaries are pushed onto the user
- async is a sync core + greenlet wrapping
- Type support is half-done; relationship configuration uses many strings
- No batteries for Repository, pagination, auditing, soft delete, etc.
- Error messages are far from where the cause is

### The common root of the problems
N+1, `MissingGreenlet`, expire accidents, blurry layer boundaries, and domain logic that is hard to test without a DB all come down to one thing.

> **Domain code does IO through objects, at unpredictable times.**

---

## 1. Philosophy

> **Domain code must not know that a DB exists.**
> **An ORM does not manage objects. It manages boundaries.**

- Where JPA and SQLAlchemy focused on making IO "transparent", Platina **gathers the places where IO can happen into one place.**
- The goal is not "an ORM where mistakes are hard to make" but **"an ORM where there is no place to make mistakes"**.
- As a result it becomes **an ORM whose default structure is CQRS**. Reads and writes are separate paths from the start, and ChangeSets and events connect them.
- The philosophy is not compromised, but we build a **stairway to the philosophy**.

### Priorities
**Correctness > Explicitness > Progressive convenience > Performance**

These priorities are used in real decisions. Example: making SERIALIZABLE the default isolation level (§8.3) is the result of putting correctness ahead of performance.

---

## 2. Principles

### Three pillars
1. **Declared reads**: a use case declares the data it needs in its signature, and the ORM loads all of it before entering the function. The load plan is fixed and validated at seal time.
2. **Pure domain**: entities are immutable snapshots. Domain functions take snapshots and return a record of changes. Inside the function there is no session and no `await`.
3. **Changes are data**: instead of dirty checking, the ChangeSet is a first-class value. It can be inspected, merged and serialized.

### Detailed principles
- **No implicit IO**: attribute access never hits the DB. Accessing an unloaded relation is an immediate error.
- **Safe defaults**: `lazy="raise"`, no expire, no autoflush, SERIALIZABLE. Anything dangerous is opt-in.
- **The library owns the boundaries**: no session passed around as an argument. Use case = transaction.
- **Only two kinds exist, pure and impure**: use cases (pure) and process handlers (external IO allowed). Nothing in between.
- **Configuration does not change meaning**: no feature where the same code behaves differently depending on an option. If the meaning differs, the name (syntax) differs.
- **Only one way to do it**: per operation - a loaded row is modified with `.set(...)` and deleted with `.delete()`, a new row is written with `insert(...)` ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed), step composition is `chain`, execution is `app.run`/`app.query`. No second syntax for the same thing.
- **Removal over detection**: rather than adding mechanisms that detect mistakes after the fact, remove the structures where mistakes can happen or turn them into type errors.
- **SQL is a first-class citizen**: the ORM does not hide SQL; it makes SQL convenient to write.
- **References instead of strings, codegen instead of runtime**.
- **Built-in observability**: query counts, N+1 suspicion and OpenTelemetry spans by default.
- **Errors point to where the cause is**.
- **Small core, batteries as official plugins**.
- **Progressive adoption**: each step delivers value on its own.
- **Distinguish row changes from domain events**: audit logs from diffs, read models from domain events.

### What we take from other ORMs / what we do not

| Source | Taken | Cautionary example |
|---|---|---|
| JPA / Hibernate | Declarative transactions, `@Version`, value objects, DTO projections, Statistics, schema validation at startup, `getReference` (placeholder ref) | Implicit lazy proxies, OSIV, detached/merge state machine, method-name-based queries |
| EF Core | `AsNoTracking` (read-only mode), Owned types | |
| Prisma | No lazy loading, TypedSQL, shadow DB drift detection | Sidecar query engine, mandatory DB connection during generation |
| TypeORM | Active Record / Data Mapper side by side | String-based relations and QueryBuilder |
| Ecto | Schema is pure data / DB access only through Repo, Changeset, `Ecto.Multi` | |
| jOOQ / Drizzle / sqlc | SQL-friendly DSL, `.sql` → typed function codegen | |
| Rust | Move: an original reference passed to `chain` can no longer be used | |
| SQLAlchemy | `Mapped[T]`-style descriptor annotations (`Col[T]`), Core's DDL and reflection and Alembic (optional extra) | Defaults, session boundaries |
| Spring Modulith | Module boundary verification, inter-module events | |

---

## 3. Features

### 3.1 Command (write) path
- `@usecase`: begin transaction → execute load plan → pure function → commit ChangeSet. From load to commit is one transaction, and there is no external IO in between, so the transaction is short.
- **Load plan**: based on `Annotated` signature declarations, fixed and validated at seal time. Warning for relations that are declared but not used
- **Dependent loads**: `Load.when` (column expression, folded into a subquery, no extra round trip) / `Load.after` (typed pure function, adds one load stage). If the function returns a list of refs, they are batch-loaded at once. No generators; the number of round-trip stages is fixed at seal
- **Call**: `app.run(uc.bind(...))`. `bind` has the same signature as the use case, so it is type-checked with ParamSpec alone
- **Recursive loads**: `Load.recursive(...)` → `WITH RECURSIVE` (depth limit required, cycle detection)
- **ChangeSet**: row-level changes / condition-based changes / chunk streams are all the same type
- **Concurrency control**: SERIALIZABLE by default + automatic retry. `version` is used for optimistic locking across requests (`expected_version`), event ordering, overlap detection within a use case, and coexistence with other ORMs. Changes to owned children bump the root version
- **Run ID**: every run gets an ID, claimed by INSERT without a lookup. A repeated request with the same key gets the stored result; connection loss or failover during COMMIT is handled by rerunning with the same ID
- **2 round trips**: 1 load batch + 1 commit batch (an extra load stage only when there is a `Load.after`)
- **Pessimistic locking**: `Load(..., lock=FOR_UPDATE)` takes the row lock at the load stage. On a hot row it does not avoid the same-row 40001 under SERIALIZABLE; it makes the conflict surface early ("fail early"); spike 0003 (§9.2) measured that it does not reduce the failures, it only moves them to the load statement. Whether `lock=` stays is decided in #64 ([ADR-0005](../adr/0005-hot-rows-under-serializable.md))
- **outbox**: domain events passed to `emit()` are INSERTed in the same transaction. An event only declares `@event(aggregate=...)`; the engine fills in the sequence numbers
- **Retry**: because it is a pure function, rerunning everything is safe. Events are recorded only at commit, so there is no duplicate publishing

### 3.2 Bulk writes

| Kind | Load | Domain rules | Compiled result |
|---|---|---|---|
| Bulk insert | None | Validation at creation | `COPY` / multi-row `INSERT`, automatic FK ordering, chunk streaming |
| Set-based update | None | SQL condition expression | `UPDATE … RETURNING` + outbox CTE, `version` increment |
| Chunked update | Per chunk | Python pure function | `unnest`-based `UPDATE`, per-chunk commit, identification of conflicting rows |

- `COPY` cannot be used in pipeline mode, so the bulk insert path runs outside the pipeline.
- If a set-based update touches a field protected by `@invariant`, it is rejected at seal time (§8.2).

### 3.3 Query (read) path
- TypedSQL: `.sql` file → codegen → typed function
- Ad hoc t-string queries: `t"SELECT … WHERE id = {x}"` → DTO mapping (columns validated at runtime)
- Read-only mode without tracking, READ COMMITTED (replica routing possible)
- Results are read-only Rows / DTOs. A `Snapshot` that supports `.set()` can only be obtained through a use case load → **CQRS enforced by types**

### 3.4 CQRS / projections
- `@projection(on=Event, into=Target, key=Event.field, mode="inline" | "async")`, **default inline**. The body only returns field operations on the target row
- The key of an inline projection must be an entity ID field of the event. Derived keys such as dates or constants create hot rows, so run them async or state it explicitly with `allow_hot_key="reason"`. Entity IDs can also be hot, so a per-projection retry rate is always emitted as a metric
- **Consistency token**: the commit result returns an opaque token (WAL insert position right after commit + transaction xid). If the read side passes it as `after=token`, a replica is used only if it has caught up to that position; otherwise the primary is used. When reading an async projection, the decision is whether that consumer's watermark has passed the xid
- **Idempotency of async projections**: the consumer checkpoint is written in the same REPEATABLE READ transaction as the projection change, so even non-idempotent updates such as `total = total + amount` are applied exactly once. A poison message is not skipped; the consumer stops and alerts
- Start with logical CQRS reading the same tables, and add separate read models only for the screens that need them

### 3.5 process handlers (the boundary with the outside world)
- `@process(on=PaymentRequested)`: the only place where external IO is allowed. Depending on the result, it **returns the description** of the use case to run, and the dispatcher commits it in one transaction with the job completion record. External calls use an event-based idempotency key provided by the framework
- `then` and `@process` are handled by a two-tier job pipeline: short lease, unique INSERT fencing, per-aggregate ordering, handling by failure kind, and dead-letter (§4.10)
- Flows where "an external result decides the write", such as payment approval, are expressed as `usecase → event → process → usecase`
- Timeout and compensating transaction helpers go into an official plugin (`platina-saga`)

### 3.6 Modular monolith support
- Per-package `Module("billing", exposes=[...])` declaration
- **Entities of other modules cannot be put into load declarations** (validated at seal time)
- `platina contracts` generates import-linter independence contract configuration, enforcing boundaries at the import level too
- Communication between modules only through events or public query paths

### 3.7 Operations and development tools
- Query and round-trip counts measured per unit of work; repeated queries of the same shape give a warning in development / an exception in tests
- OpenTelemetry spans and metrics provided by default
- Development mode: records where entities were loaded and where the unit of work ended
- CLI: `platina check` / `platina gen` / `platina migrate` / `platina pull` / `platina contracts`

### 3.8 Official plugins (outside the core)
soft delete, auditing, multi-tenancy, pagination, Pydantic DTO generation, saga helpers

---

## 4. Syntax

> The code below is a design proposal. Names and signatures may change in the prototype. The type surface of §4.2-§4.6 and the misuse list of §11.8 were confirmed under pyright and mypy by the type stub spike ([spike 0001](../spikes/0001-type-surface.md), ADR-0003, ADR-0004), and the parent key of owned children and the comparison operands of §4.2 and §4.7 by [spike 0006](../spikes/0006-parent-fk-and-column-operands.md); the other sections are not yet checked by a type spike.
> Example domain: the `billing` module of an online store (orders, order items, wallets).

### 4.0 Concepts at a glance

| Concept | What it is | Who executes it |
|---|---|---|
| Entity snapshot | Immutable object holding a row at one point in time | — |
| ref (`Order.ref(id)`, `orders.by_number(n)`) | A **placeholder** that looks like an entity at the type level. Means "please load this" (corresponds to JPA `getReference`) | The runner loads it and turns it into a snapshot |
| `Changes` | Description of changes (a value) | The runner commits it |
| `@usecase` | Pure function that takes snapshots and returns `Changes` + load declarations | `app.run(uc.bind(...))` |
| `@step` | Composition-only pure function without load declarations | Only inside `chain` |
| Repository | Holds only **descriptions**: how to find, load profiles, queries, set changes | `app` executes |
| Run ID | ID attached to every `app.run`. The idempotency key given by the caller, or an automatic uuid7 if none | Used by the runner for idempotency and commit-outcome resolution |
| Job | Unit of processing obtained by splitting an event per `then` / `@process` handler | Worker + dispatcher |

Everything is a "description", and execution happens in only one place, `app`. Even `@process` handlers do not run use cases directly; they return a description (§4.10).

### 4.1 App configuration

```python
# shop/app.py
from platina import App, Pool, TxDefaults, Retry, SERIALIZABLE

app = App(
    dsn="postgresql://app@primary/shop",
    replicas=["postgresql://app@replica-1/shop"],   # Query path + consistency token routing
    pool=Pool(min_size=2, max_size=20),
    modules=["shop.billing", "shop.catalog"],       # collect entities, Repositories and usecases per module
    defaults=TxDefaults(
        isolation=SERIALIZABLE,
        retry=Retry(max_attempts=4, base_ms=10, cap_ms=200),
        timeout="5s",                                 # budget for the whole run (ADR-0008)
    ),
)

app.seal()   # validates load plans, module boundaries, invariants, projection keys, DTO mappings and aggregate declarations. Startup aborts on failure
```

- `App` is only configuration and a registry; connections are acquired only inside `run`/`query` calls.
- The same `App` provides both the async (`await app.run(...)`) and sync (`app.run_sync(...)`) APIs. They are separate runners driving the same engine.

### 4.2 Entities, value objects, events

```python
# shop/billing/entities.py
from decimal import Decimal
from datetime import datetime
from platina import (
    Entity, value, event, Col, Id, Rel, Owned, pk, column, embedded, fk, parent_fk,
    many_to_one, owns_many, version_column, invariant, Check, Index, server_now,
)

@value
class Money:
    amount: Col[Decimal]
    currency: Col[str] = column(default="KRW")

class Order(Entity, table="orders", aggregate_root=True):
    id: Col[Id[Order]] = pk(generated="uuid7")          # default: client-side UUIDv7
    number: Col[str] = column(unique=True, length=20)
    status: Col[OrderStatus] = column(default=OrderStatus.PENDING, enum_as="text")
    paid_with: Col[PaymentMethod | None] = column(default=None)
    paid_at: Col[datetime | None] = column(default=None)
    total: Col[Money] = embedded(prefix="total_")        # total_amount, total_currency columns
    user_id: Col[Id[User]] = fk(lambda: User)
    user: Rel[User] = many_to_one(via=lambda: Order.user_id)
    items: Owned[list[Item]] = owns_many(lambda: Item.order_id,       # owned children (ADR-0010)
                                         order_by=lambda: Item.position)
    version: Col[int] = version_column()
    created_at: Col[datetime] = column(server_default=server_now())

    class Meta:
        indexes = (Index(lambda: (Order.user_id, Order.created_at.desc())),)
        checks = (Check(lambda: Order.total.path(Money.amount) >= Decimal(0)),)   # generated as a DB CHECK constraint

    @invariant(fields=lambda: (Order.status, Order.total))  # invariant checked only in Python
    def paid_requires_total(self) -> bool:
        return self.status is not OrderStatus.PAID or self.total.amount > 0

class Item(Entity, table="items"):                         # an owned child of Order
    id: Col[Id[Item]] = pk(generated="uuid7")
    order_id: Col[Id[Order]] = parent_fk(lambda: Order)   # set by Order.items.add(...), not a constructor parameter
    sku: Col[str] = column(length=40)
    price: Col[Money] = embedded(prefix="price_")
    position: Col[int] = column()

@event(aggregate=lambda: OrderPaid.order_id)               # declares only which aggregate the event belongs to
class OrderPaid:
    order_id: Col[Id[Order]]
    user_id: Col[Id[User]]
    total: Col[Money]
    paid_at: Col[datetime]
    # Sequence numbers (aggregate version, position within the transaction) are filled in by the engine at commit. Never written by hand.
```

- **Entities inherit `Entity`** and pass their table options as class keywords (ADR-0003). A class decorator can make a type checker synthesise a constructor but cannot add members, so `Order.ref`, `Order.where`, `Order.stub`, `order.set` and `order.delete` need the base class (spike 0001).
- **Every field is declared as `Col[T]`.** With a plain annotation (`status: OrderStatus = column(...)`), the type checker also sees class access (`Order.status`) as `OrderStatus`. For it to appear as `Column[Order, OrderStatus]` on the class (the column knows the class that declares it) and `OrderStatus` on the instance, the annotation itself must be a descriptor type. This is the same reason SQLAlchemy 2.0 uses `Mapped[T]`. Event fields and value-object fields are the same (`OrderPaid.user_id` in projection keys, `Money.amount` in embedded paths, ADR-0004).
- **Snapshots are immutable.** `order.status = PAID` is an error; writes happen only through `.set(...)`, `insert(...)` and `.delete()` (§4.4). Collection fields are a read-only `Sequence[Item]` on the instance.
- **Creation is the keyword constructor**: `Order(number="A-1", total=..., user_id=...)`, the same as events and values. A missing required field is a type error in both checkers; generated keys, `version_column()`, server defaults, relations and the parent key of an owned child are not parameters (§8.2 "Creation syntax", ADR-0003).
- **The parent sets the key of an owned child.** The child declares it with `parent_fk(lambda: Order)` (working name; the final name is fixed in #9), so `Item(sku=..., price=..., position=...)` takes no `order_id` and `Order.items.add(item)` fills it; passing it is a type error in both checkers, so a new child cannot be created with another parent's key. A child of a relation that is not owned declares its key with `fk` and passes it to the constructor like any other column (#49, [spike 0006](../spikes/0006-parent-fk-and-column-operands.md)). Owned children of a new root are added in `insert(t, Transfer.legs.add(...))`, and a relation that is not owned has no `add` (§4.4, [ADR-0010](../adr/0010-writes-beyond-set.md)). Seal checks `owns_many`, `parent_fk` and `aggregate_root=True` against each other ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed; the final names are #9's): both declarations stay, because the child's constructor needs its own field specifier and the root's operations need the `Owned[...]` annotation. Open: reading the key of a child that has not been added yet (#76); moving an existing child to another parent, which still type-checks (`Item.order_id.to(...)` in a child update or a set change; spike 0006 O9) (#9) - `add` of a loaded child is a `UsageError` ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed).
- **Equality** (#54): two snapshots are equal when they are of the same entity type and all their column values are equal (embedded values included); relations and what is loaded are not compared. A column that has no value yet (a server default or an `identity` key of a new entity) is equal only when it has no value on both sides. The hash is the entity type plus the primary key. `==` and `hash()` on a ref raise `UnloadedReference` (ADR-0003 Decision 4). The parent key of an owned child that has not been added yet (`parent_fk`, before `add`) has no value either; how equality and the hash treat it is decided in #76.
- **`owns_many(...)`** (annotation `Owned[list[Item]]`) declares children that belong to the aggregate. When a child changes, the root's `version` is bumped as well (JPA `OPTIMISTIC_FORCE_INCREMENT`). So when an edit screen handles an order and its items together, a change to only the items is still caught by the optimistic lock across requests (§4.6). The rows of an owned relation are written only through the root, and deleting the root deletes them (§4.4). Ordinary FK children (e.g. comments on a post) are declared `Rel[list[...]]` with `one_to_many(...)`: they do not touch the root, have no write operations on the relation and are written directly (`insert(Comment(post_id=...))`). There is no `owned=` flag: the behaviour differs, so the name differs ([ADR-0010](../adr/0010-writes-beyond-set.md)). Proposed in [ADR-0010](../adr/0010-writes-beyond-set.md): ownership is one level deep - only an `aggregate_root=True` class declares `owns_many`, so an owned child owns nothing itself.
- **Client-generated IDs are the default.** Thanks to Python 3.14's `uuid.uuid7()`, the ID of a new entity is known inside the pure function. `generated="identity"` is also supported, but in that case the ID is only available from the commit result (`result.created(Order)`). The core never calls `uuid7()` itself: `Order(...)` takes the ID from the source the engine installs for the invocation; direct calls in tests and `Order.stub()` use a deterministic fallback sequence, and `Order(...)` outside any use case or step is a `UsageError` (ADR-0002). Under SERIALIZABLE an ever-increasing key (uuid7, identity) makes commands that read recent rows of a table (including a child's foreign-key check of a new parent) and insert into it conflict; [ADR-0007](../adr/0007-ever-increasing-entity-keys.md) (Proposed) proposes a random default.
- Places that refer to other classes are evaluated late with a `lambda`. String references are not used.
- Instances for tests: `Order.stub(...)`.

### 4.3 Repository: how to find, load profiles, queries, set changes

**A Repository does not do IO either.** It only describes queries and changes; `app` executes them.

```python
# shop/billing/repos.py
from platina import Repository, Profile, Finder, query, dto, select, Select, count, Changes

@dto
class OrderSummary:
    id: Id[Order]
    number: str
    total: Decimal
    item_count: int

class OrderRepo(Repository[Order]):
    # 1) How to find: calling it returns a typed ref (placeholder)
    by_number = Finder(Order.number)            # orders.by_number("A-1") -> Order (Finder[Order, str])

    # 2) Load profiles: named EntityGraphs
    payable = Profile(Order.items, Order.user)
    with_item_count = Profile(Order.items.count())
    for_update = Profile(Order.items, lock="for_update")   # row lock at the load stage: fails early, does not avoid 40001 (ADR-0005)

    # 3) Queries: Query path only, results are DTOs (read-only)
    @query
    def summaries(self, user_id: Id[User], limit: int = 20) -> Select[OrderSummary]:
        return (
            select(OrderSummary,
                   id=Order.id, number=Order.number,
                   total=Order.total.path(Money.amount), item_count=count(Item.id))
            .join(Order.items, outer=True)
            .where(Order.user_id == user_id)
            .group_by(Order.id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )

    # 4) Set change factory: a pure function that only returns Changes
    def expire_older_than(self, cutoff: datetime) -> Changes:
        return (
            Order.where(Order.status == OrderStatus.PENDING, Order.created_at < cutoff)
                 .set(Order.status.to(OrderStatus.EXPIRED))
                 .emit_each(OrderExpired, order_id=Order.id)   # event sequence numbers filled via RETURNING
        )

class WalletRepo(Repository[Wallet]):
    by_user = Finder(Wallet.user_id)            # wallets.by_user(uid) -> Wallet

orders, wallets = OrderRepo(), WalletRepo()
```

- **A ref is a placeholder.** `Order.ref(id)` and `orders.by_number("A-1")` are `Order` at the type level, but in reality they are a mark meaning "please load this row". Reading a field of a ref on the calling side, or **calling `.set` or `.delete()` on a ref**, is an immediate `UnloadedReference` error. `.set` is blocked because it would be a write that skips the load and the `@invariant` checks. To write without loading, state it explicitly as a set change `Order.where(Order.id == x).set(...)` (it gets invariant checks at seal).
- **`Order.where(pred, *preds)` is a `RowSet[Order]`**: the rows of `Order` that match, with `.set(...)` (a set change) and `.delete()`; it is not a `Changes`, so it cannot be returned or added with `+` by itself. At least one predicate is required: `Order.where()` is a type error in both checkers, and an unpacked list that turns out empty at run time (`Order.where(*preds)`) is a `UsageError` (spike 0007; [ADR-0010](../adr/0010-writes-beyond-set.md)). Only `Entity.where` changes; a relation's `.where(...)` (partial loads, §4.7) and a query's `where` do not. Whether a row set is also a load is decided with #59.
- **Optimistic locking across requests**: if you pass `Order.ref(id, expected_version=v)`, a different loaded version raises `VersionMismatch`. This is the pattern of sending the version received when opening an edit screen along with the save request (HTTP `If-Match`).
- Finder arguments are checked against the column type. There are no keyword strings. A Finder of `Repository[Order]` must be built on a column of `Order`; another entity's column is a type error (ADR-0004).
- **A query may reference only the entities it selects from or joins.** A column of any other entity is rejected when the query description is built. This is not checked by types: in a call that receives columns of several entities, pyright and mypy infer the owner differently (ADR-0004); whether seal can also catch it is open (#52).
- **Repository is optional.** Start by writing `Load(...)` directly in the use case signature, and move it to a `Profile` once the same load repeats.
- **Module boundary**: a Repository handles only the entities of its own module. Only queries published with `Module("billing", exposes=[orders.summaries])` can be used from other modules.

### 4.4 Write syntax: `.set`, `insert` and `.delete()`

> Decided by the maintainer on #57 and #60 (2026-11-26) and written up in [ADR-0010](../adr/0010-writes-beyond-set.md); the rules marked *(Proposed)* are that ADR's proposals and wait for the maintainer to accept it.

| Operation | Meaning | Generated SQL |
|---|---|---|
| `Order.status.to(v)` | Assign a value (`v` checked against `T` of `Column[Order, T]`) | `SET status = $1` |
| `Wallet.balance.path(Money.amount).add(n)` | DB-side increment/decrement of a part of an embedded value (does not read the current value; concurrent writers of the same row still conflict with 40001, ADR-0005) | `SET balance_amount = balance_amount + $1` |
| `Order.items.add(item)` | Add a new child to an owned relation; the parent sets the child's `parent_fk` key (§4.2) | `INSERT` + root version increment |
| `Order.items.remove(item)` | Delete a loaded child of an owned relation | `DELETE` + root version increment |
| `Order.items.update(item, Item.price.to(p))` | Update a loaded child of an owned relation; column operations only *(Proposed: ownership is one level deep)* | `UPDATE` + root version increment |
| `insert(payment)` | Insert one new row; its column values come from the constructor | `INSERT` |
| `insert(t, Transfer.legs.add(leg), ...)` | Insert a new root with its owned children (only `add`) | `INSERT` of the root, then of the children |
| `order.delete()` | Delete a loaded row; for a root also every row of its owned relations (*Proposed:* loaded or not) | engine-issued `DELETE`s of the owned relations by the root key and of the root (*Proposed:* §10.7) |

```python
order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now))   # a loaded row
Order.where(...).set(Order.status.to(OrderStatus.EXPIRED))             # set change, same operations
insert(Payment(order_id=order.id, amount=order.total))                 # a new row that is not owned
t = Transfer(amount=amount)
insert(t, Transfer.legs.add(Leg(account_id=src.id, side=LegSide.CREDIT, amount=amount)),
          Transfer.legs.add(Leg(account_id=dst.id, side=LegSide.DEBIT, amount=amount)))
src.delete()                                                           # the order, its items and its tickets
```

- **One verb per operation.** `.set` modifies a loaded snapshot (column operations, and the relation operations of its owned relations); `insert` writes a new row; `.delete()` deletes a loaded row. Creating, modifying and deleting are different operations (ADR-0003). `insert_all` is the bulk path, a different operation (§4.8).
- **Owned rows only through their root.** The rows of an `owns_many` relation are written with `Order.items.add / update / remove`, which bump the root's `version`. Every other row is written directly: `insert(Payment(...))`, `payment.set(...)`, `payment.delete()`. A relation that is not owned has no write operations; `Order.payments.add(...)` is a type error in both checkers (spike 0007). *(Proposed)* A direct write of an owned child - `item.set(...)`, `item.delete()`, `insert(Item(...))` - is a `UsageError` at that call, naming the root operation to use.
- **New, loaded and ref** share one type, so their misuse is a runtime rule, checked at the call. Decided: `.set` on a new entity is a `UsageError` (its values go in the constructor, its owned children in `insert`); `.set` and `.delete()` on a ref raise `UnloadedReference`; an entity created in a step and never inserted is a `UsageError` when the step returns. *(Proposed)* `.delete()` on a new entity, `insert` of a loaded snapshot or a stub, `add` of a loaded snapshot, `update` / `remove` of a new entity or of a child of another root, and reading the `identity` key of a new entity before commit are `UsageError`s; `insert`, `add`, `update` or `remove` of a ref raises `UnloadedReference`; an empty `.set()` or an `update(item)` without operations changes nothing and bumps no `version`. Owned children of a root with an `identity` key are rejected in Phase 1a, since a new root's children would need its key from `RETURNING` (*Proposed:* a `SealError` for an `identity`-key class that declares `owns_many`). The full table is ADR-0010's.
- **Delete.** `order.delete()` deletes the root and every row of its owned relations (*Proposed:* whether the use case loaded them or not); rows that are not owned are not touched, so one that still references a deleted row fails the commit with `ForeignKeyViolation` (§10.12) - delete or re-point it first in the same use case. The engine issues the DELETEs (no `ON DELETE CASCADE`). *(Proposed)* One statement per deleted-root table deletes every owned relation and the root, `WITH c1 AS (DELETE FROM items WHERE order_id = ANY($1)), ... DELETE FROM orders WHERE id = ANY($1)`, so a root's FK into its own owned table (`User.default_address_id`) and FKs between owned tables need no order (NO ACTION FKs are checked after the whole statement; PostgreSQL 18), and it runs after every change that removes a reference into the aggregate (§10.7). `expected_version` is checked at the load, as for every write; the DELETE, like the UPDATE, is by primary key. A concurrent `add` to the deleted root is a retried `40001` under SERIALIZABLE and REPEATABLE READ alike (the `add` bumps the root's `version`); only writers outside Platina that skip the bump or run READ COMMITTED can turn that race into a `ForeignKeyViolation`. A delete and a `.set` of one snapshot in one step are `ConflictingWrites`; in `chain`, a `.set` in an earlier step and a `.delete()` in a later one leave a delete. The set-level `Order.where(...).delete()` never skips the aggregate rule silently; how it keeps it is #33's. Events of a deleted aggregate are #23's.
- **Collecting operations.** A relation operation (`RelOp[Order]`) is not a column operation (`Op[Order]`), so a set change rejects it by type. A list that collects both for one `.set` is `list[Op[Order] | RelOp[Order]]` - *(Proposed)* `list[Write[Order]]` with a public alias.
- Field names are attribute references, so a typo is a type error, and value types are checked too. An operation also carries the entity it belongs to: `order.set(Wallet.balance.to(m))`, an operation of another entity inside `Order.where(...)` or `Order.items.update(item, ...)`, and a child of the wrong type are type errors (ADR-0004).
- Within a single step, changes are collected with `+`: `order.set(...) + wallet.set(...) + emit(...)`. A function sees only one snapshot, so there is no room to read stale values. Writing the same field twice is `ConflictingWrites`.
- **Embedded paths** are written `Order.total.path(Money.amount)` (`Column[Order, Decimal]`); a field of another class is a type error. A part of a value object is incremented through its path, `Wallet.balance.path(Money.amount).add(n)`; the whole value is written with `Order.total.to(Money(...))`. `Order.total.amount` cannot be typed by a generic column, and a second increment syntax on the value object was rejected (ADR-0004).

### 4.5 Use cases: signature and call

```python
# shop/billing/usecases.py
from typing import Annotated
from platina import usecase, step, Load, Now, INJECTED, Changes, emit

type PayableOrder = Annotated[Order, orders.payable]          # reuse a Repository profile
type ChargeableWallet = Annotated[Wallet, Load()]             # load only the root

@usecase
def pay(order: PayableOrder, wallet: ChargeableWallet, now: Now = INJECTED) -> Changes:
    if order.status is not OrderStatus.PENDING:
        raise AlreadyPaid(order.id)
    if wallet.balance < order.total:
        raise InsufficientBalance(wallet.id)
    return (
        order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now))
        + wallet.set(Wallet.balance.path(Money.amount).add(-order.total.amount))
        + emit(OrderPaid(order_id=order.id, user_id=order.user_id, total=order.total, paid_at=now))
    )
```

**Call: separate description (`bind`) from execution (`app.run`)**

```python
result = await app.run(
    pay.bind(order=Order.ref(order_id), wallet=wallets.by_user(user.id)),
    idempotency_key=request_id,        # run options go to run, not bind. Automatic uuid7 if absent
)
result.run_id           # run ID
result.token            # consistency token (xid, LSN)
result.created(Order)   # generated ID for an identity PK
result.events           # committed domain events
result.value            # value returned via Changes.returning(v)
```

- **Type checking works with ParamSpec alone.** `bind(*args: P.args, **kwargs: P.kwargs)` of `Usecase[P]` has the same signature as `pay`. A ref is an entity at the type level, and parameters injected by the runner (`Now`, `Actor`, `RequestId`) have the default `INJECTED`, so they are left out of `bind` (and may not be passed to it).
- **One marker for every parameter the runner fills** (#48): an injected type (`Now`, `Actor`, `RequestId`) or a dependent load (`Load.when`, `Load.after`, §4.7). Seal checks the default against the declaration both ways: such a parameter without `= INJECTED`, and `= INJECTED` on any other parameter, are `SealError`s that show the fix. `bind` rejects a runner-filled parameter passed explicitly with a `UsageError`: the runner supplies it fresh on every attempt, and a bound value would silently be the same on every retry (tests fix the clock with the test kit, §11.11). A direct call (§4.12) passes every parameter; one that leaves a runner-filled parameter out fails at once with a `UsageError` naming it, instead of handing the `INJECTED` sentinel to the function body. Because these parameters have a default, Python requires them to come after the parameters the caller binds, or to be keyword-only. A default is the only way to make a parameter omittable in `bind` under both checkers: `ParamSpec` cannot drop a parameter (PEP 612).
- Run options (`idempotency_key`, `after`, `timeout`) are keywords of `app.run`, so they do not mix with the signature of `bind`.
- Injected values are supplied fresh for each attempt. On retry, `Now` is refreshed too.
- In a run where the caller provided an idempotency key, the value of `Changes.returning(v)` is stored, so it must be serializable, and the bound arguments are fingerprinted (§4.6), so each must have a canonical serialization: `app.run` with a caller key and an argument that has none raises `UsageError`. Runs with an automatic ID do not store the value or a fingerprint, so they have no such requirement.

### 4.6 Transaction management

**Principle: one `app.run()` = one transaction.** There is no transaction API inside a use case.

#### Options

```python
@usecase(
    isolation=SERIALIZABLE,          # default. Escape hatch is REPEATABLE_READ (see below)
    retry=Retry(max_attempts=4, on_unique=False),
    timeout="2s",                    # one budget for the whole run: every attempt, round trip and backoff (ADR-0008)
)
def pay(order: PayableOrder, wallet: ChargeableWallet, now: Now = INJECTED) -> Changes: ...
```

- **The escape hatch is REPEATABLE READ + `version`, not READ COMMITTED** - an escape from SSI's read/write-dependency failures only, not from the same-row 40001 on a hot row ([ADR-0005](../adr/0005-hot-rows-under-serializable.md)). Under READ COMMITTED each statement of the load plan has a different snapshot, which breaks the premise that "the loaded snapshots show a single point in time". REPEATABLE READ guarantees a single snapshot but **does not prevent write skew.**

#### Execution order: 2 round trips

```
attempt 1..N:
  [round trip 1] BEGIN ISOLATION LEVEL SERIALIZABLE; set_config('statement_timeout', <remaining budget>, true)
           INSERT INTO run_claim(id) VALUES ($run_id)      ← claim the run ID. INSERT without a lookup
           load plan stage 1
  (if there is a Load.after: [round trip 1+k] load stage k — number of stages fixed at seal)
  execute usecase (pure function)        ← domain exception → ROLLBACK, propagated as is
  [round trip 2] set_config('statement_timeout', <remaining>, true) → row changes (in FK/unique dependency order) → inline projections → outbox
           → INSERT INTO run_result(...)                   ← only for caller keys (result + fingerprint)
           → SELECT pg_current_xact_id() → COMMIT → SELECT pg_current_wal_insert_lsn()
           ← 40001/40P01 → ROLLBACK, back off, then next attempt
```

- Writes, COMMIT and the LSN query are sent in one batch. In a pipeline, if an earlier statement fails, later statements are not executed, so this is safe. The cost is a wider window in which the commit outcome is unknown; the run ID covers it (below).
- The shield that blocks cancellation covers the whole of round trip 2.
- **`timeout=` is one budget for the run** ([ADR-0008](../adr/0008-run-timeout-budget.md); #61), from the start of `app.run` across every attempt and backoff. The runner holds the deadline and reports facts; the engine decides. The engine puts `set_config('statement_timeout', $1, true)` at the head of each round trip before `COMMIT` and the runner binds the remaining time (PostgreSQL applies it to each statement, also inside a pipeline; the local value replaces a smaller session, role or database default `statement_timeout` for those statements); the runner reports a passed deadline at a yield point, including instead of a backoff that would end past it, and the engine turns that, or a budget 57014 before `COMMIT`, into `RunTimeout`, which is not retried. The budget covers the statements before `COMMIT`; `COMMIT` itself is not timed out by PostgreSQL and the commit batch is shielded, so a run can exceed its budget by the duration of its `COMMIT`. Whether the batch committed is decided by which statement failed, not by the SQLSTATE: an error before or on `COMMIT` is a rollback; once `COMMIT` has returned, the run is committed, whatever the LSN query after it reports; no reply at all is unknown, and that is resolved first by a claim of the same run ID (`ResolveClaim`, not counted as an attempt and not bounded by the deadline): a 23505 means it committed (the replay path); a successful claim means it did not, and the engine rolls back and starts a normal attempt from `BEGIN` and the claim. A deadline or the retry limit ends the run only after that.
- "The first statement" (the run ID claim, everywhere in this document) means the first statement on a table, after `BEGIN` and the budget's `set_config`.

#### Run ID: idempotency and commit-outcome resolution unified

Every `app.run` has a run ID (the caller's `idempotency_key`, or an automatic uuid7 if none). The first statement INSERTs into `run_claim`, and for a caller key the result is INSERTed into `run_result`.

| Situation | Handling |
|---|---|
| Called again with the same key and the same arguments (repeated request, double click) | `run_claim` INSERT gets 23505 → rollback → read `run_result` in a separate READ COMMITTED transaction, compare the fingerprint, and return the stored result |
| Called again with the same key and **different arguments** (a client reusing a key by mistake) | The same path, but the fingerprint differs → `IdempotencyKeyReuse`, not retried |
| The same key is running right now | `run_claim` INSERT waits on the unique key → once the other side is decided, one of the two cases above |
| Connection lost during COMMIT, failover | **Rerun with the same run ID**. If it already committed, 23505 (stored result for a caller key; for an automatic ID the runner returns the result from memory); if it was rolled back or lost, it simply runs |

- There are two reasons for doing **the INSERT first, without a lookup**. ① The duplicate check for a caller key must come before the business logic. If the second request of a double click ran the use case first, it would see an order that is already PAID and raise `AlreadyPaid`. ② "Look up, and INSERT if absent" creates false conflicts under SERIALIZABLE (see the internal table rule below).
- The result is not written by UPDATEing `run_claim` but by **INSERTing into a separate append-only table `run_result`**. An UPDATE reads the index to find the row and recreates the same false conflict.
- **Fingerprint** (#58): for a caller key, `run_result` also stores a fingerprint of the call - the use case's registry name plus a canonical serialization of the bound arguments (refs by entity type and key, including `expected_version`; a Finder ref by its Finder and argument, since it has no key before loading; plain values). Runner-filled parameters are not bound, so they are not part of it; neither is the use case's code version. It is written with the result and compared only on the 23505 replay path, which already reads `run_result` outside the SERIALIZABLE transaction, so the internal table rule holds and `run_claim` does not change. A key reused with other arguments is an error rather than the stored result: returning another request's result would let the client believe its own request happened (Stripe, AWS `IdempotentParameterMismatch` and the IETF idempotency-key draft do the same). There is no option to turn it off.
- The LSN of a token obtained through replay is queried fresh. The stored value was taken before commit, so it is too low.
- The `then` and `@process` dispatchers use **the job ID as the run ID**. So the job completion record and fencing are also handled by `run_claim` alone (§4.10).
- Both tables are cleaned up after a retention period (longer than the maximum period in which a rerun can happen).

> **Internal append-only table rule**: `run_claim`, `run_result`, the outbox log and the job tables are **not read inside SERIALIZABLE transactions.** (The internal schema's version table is touched only by the command that applies the schema, never by a run; ADR-0009.) SERIALIZABLE takes read locks per B-tree leaf page, and with ever-increasing keys like uuid7 every INSERT lands on the rightmost page. Transactions that read that page form cycles in which each invalidates the others' reads, and unrelated commands get retried on serialization failures. Inside a SERIALIZABLE transaction the only operation on these tables is INSERT; reads happen in a separate READ COMMITTED transaction. (Consumer checkpoints and job leases are updated, but only in their own non-SERIALIZABLE transactions, §8.4.)

#### Composition: steps only via `chain` (corresponds to JPA `REQUIRED`)

```python
@step
def apply_coupon(order: Order, coupon: Coupon) -> Changes:
    return order.set(Order.total.to(coupon.apply(order.total))) + coupon.set(Coupon.used.to(True))

@usecase
def checkout(order: PayableOrder, coupon: Annotated[Coupon, Load()],
             wallet: ChargeableWallet, now: Now = INJECTED) -> Changes:
    with chain(order, wallet) as (c, order, wallet):    # rebound to the same names
        c.run(apply_coupon, order, coupon)
        c.run(pay, order, wallet, now)                  # order: latest state with the coupon applied
    return c.changes
```

- **Positional arguments + rebinding the same names.** `chain(*snapshots)` is typed with TypeVarTuple, so the returned `order` and `wallet` appear as `Order` and `Wallet` respectively. Because the original names are overwritten, most cases of "accidentally reading the original" disappear structurally.
- The returned values are **always views pointing to the latest state of the chain**. If they were plain snapshots, they would still hold the old value on the line after `c.run`, and rebinding would be meaningless. When passed to `c.run`, they are converted to the immutable snapshot of that moment.
- **Move marks** remain as a defense against aliases. Reading a field through an alias created before the chain, such as `o = order`, is `MovedSnapshotAccess`. If you need the value before the change, use `c.original(order)`.
- **After leaving the block**: views are frozen at the final state; **reads are allowed** (`Changes.returning(order.total)` etc.), **`.set` and `.delete()` are errors**. A write outside the block would not go into `c.changes` and would silently disappear.
- `c.changes` is merged into the final difference relative to the original snapshots. All events are kept, in the order they occurred.
- **Inserts and deletes in a chain** ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed): a `.set` in an earlier step and a `.delete()` of the same row in a later one leave a delete, and the earlier step's operations on that root's owned children are dropped (the cascade covers them); a write to a row an earlier step deleted is a `UsageError`, while reading its view stays allowed. A new entity is not a chain view: `.set` and `.delete()` on it are `UsageError`s in every step, so the step that creates it inserts it with all its owned children.
- **`+` between steps is a type error.** A step call result (`StepResult`) has no `+`. `+` between undecorated helpers is caught by a lint (`PRL001`).

#### Separate transaction after commit (corresponds to JPA `REQUIRES_NEW`, `AFTER_COMMIT`)

```python
@usecase
def pay(order: PayableOrder, wallet: ChargeableWallet, now: Now = INJECTED) -> Changes:
    return (
        order.set(Order.status.to(OrderStatus.PAID))
        + then(issue_receipt.bind(order=Order.ref(order.id)))   # separate transaction after a successful commit
    )
```

`then` is recorded in the outbox log as a command, and the job pipeline (§4.10) runs it in a new transaction after the commit. If the outer transaction rolls back, it is not recorded.

#### Optimistic locking across requests

```python
@api.put("/orders/{order_id}")
async def edit_order(order_id: UUID, body: EditOrder, if_match: int = Header()):
    await app.run(edit.bind(order=Order.ref(order_id, expected_version=if_match), patch=body))
```

There is no transaction spanning the two requests, so `version` prevents the lost update that the DB cannot detect. Changes to owned children (`owns_many`) also bump the root version, so a change to only the items is caught too.

#### Query transactions

```python
rows = await app.query(orders.summaries(user_id=uid))                # build a description
rows = await app.query(orders.summaries(user_id=uid), after=token)   # run options are separate

async with app.read(consistency="snapshot") as r:                    # REPEATABLE READ READ ONLY
    summary = await r.query(orders.summaries(user_id=uid))
    stats   = await r.query(sql.order_stats(since=day))
```

- A single query is READ COMMITTED (replica possible); to bind several queries to one point in time, use `app.read(consistency="snapshot")`.
- `app.read(consistency="serializable")` runs as `SERIALIZABLE READ ONLY DEFERRABLE`.

#### Exception handling

| Situation | Behavior |
|---|---|
| Domain exception (raised by the usecase) | Rollback, propagated as is, no retry (handling in the job runner: §4.10) |
| 40001 serialization failure / 40P01 deadlock | Rollback, then retry from the beginning. `RetryExhausted` when the limit is exceeded |
| The run's `timeout=` budget runs out: the deadline passes, a backoff would cross it, or a statement before `COMMIT` gets 57014 | Rollback, `RunTimeout`, no retry (ADR-0008) |
| 23505 (run ID table) | Idempotent path: return the stored result |
| 23505 (other) | Retried only when `retry.on_unique=True`, otherwise `UniqueViolation` |
| Row of the root ref or of a required dependent load is missing | `NotFound` |
| `expected_version` mismatch | `VersionMismatch`, no retry (the user must be told about the conflict) |
| Caller key reused with different arguments (fingerprint mismatch on the replay path) | `IdempotencyKeyReuse`, no retry (#58) |
| Caller key with an argument that has no canonical serialization | `UsageError` from `app.run`, before anything runs (#58) |
| Connection lost during COMMIT | Rerun with the same run ID (see above) |
| Reading a field of a ref / `.set` or `.delete()` on a ref / `==` or `hash()` on a ref (*Proposed:* `insert`, `add`, `update` or `remove` of a ref) | `UnloadedReference` |
| Reading a field through a moved original (alias), including `==` and `hash()` | `MovedSnapshotAccess` |
| `hash()` of a new entity with an `identity` key before commit | `UsageError` (ADR-0003) |
| `.set` or `.delete()` on a view outside the chain block | `ChainClosed` |
| Writing the same field twice within a single step; a `.delete()` and a `.set` (or two `.delete()`) of one snapshot in one step; *(Proposed)* one new entity inserted twice | `ConflictingWrites` |
| `.set` on a new entity; a new entity never inserted (when the step returns); an empty unpacked predicate list in `Entity.where(*preds)`; *(Proposed, [ADR-0010](../adr/0010-writes-beyond-set.md))* `.delete()` on a new entity, `insert` of a loaded snapshot, `add` of a loaded snapshot, `update` / `remove` of a child of another root, a direct write of an owned child (`item.set`, `item.delete()`, `insert(Item(...))`), reading a new entity's `identity` key, a write to a row an earlier step of the chain deleted | `UsageError` at the call, not retried |
| 23503 / 23001 foreign-key violation (a row still references a deleted one, or a hand-passed key points at no row) | `ForeignKeyViolation`, a `DatabaseError`, not retried ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed) |
| Overlap between a set change and a row change in the same use case (not the cascade of a delete, which the planner resolves, [ADR-0010](../adr/0010-writes-beyond-set.md)) | `IntraUsecaseConflict` |
| Cancellation (client disconnect, an outer cancel scope) | Rollback if loading or computing. The commit batch is shielded and runs to completion |

#### Spring/JPA mapping

| Spring / JPA | Platina |
|---|---|
| `@Transactional` (REQUIRED) | One `app.run(uc.bind(...))`. Internal composition via `chain` |
| `propagation = REQUIRES_NEW` | `then(uc.bind(...))` |
| `@TransactionalEventListener(AFTER_COMMIT)` | async projection / `@process` |
| `propagation = NESTED` (savepoint) | Not supported |
| `readOnly = true` | `app.query` / `app.read` |
| `isolation`, `timeout` | `@usecase(isolation=..., timeout=...)` |
| `rollbackFor` | Domain exceptions always roll back |
| `@Retryable` | Built in (40001/40P01) |
| `@Version` + merging detached entities | `Order.ref(id, expected_version=v)` |
| `LockModeType.OPTIMISTIC_FORCE_INCREMENT` | `owns_many(...)` |
| `EntityManager.persist()` | `insert(entity)` (with `insert(root, Root.children.add(...))` for owned children) |
| `EntityManager.remove()` with `cascade = REMOVE` | `order.delete()`: the owned relations go with the root, nothing else ([ADR-0010](../adr/0010-writes-beyond-set.md)) |
| `@Lock(PESSIMISTIC_WRITE)` | `Profile(..., lock="for_update")`: under SERIALIZABLE a waiter still fails with 40001 once the holder has updated and committed the row, and is retried - not an escape hatch (ADR-0005) |
| `EntityManager.getReference()` | `Order.ref(id)`, `orders.by_number(n)` |
| Persistence context flush | None. The ChangeSet is applied at once in the commit batch |

### 4.7 Partial loads and dependent loads

There are no generators. Additional data you need is also **declared**. The number of load stages is fixed at seal time.

```python
# Partial load: does not read the whole collection
type OrderWithCount = Annotated[Order, orders.with_item_count]

@usecase
def add_item(order: OrderWithCount, sku: str) -> Changes:
    if order.items.count >= 100:
        raise TooManyItems(order.id)
    # Item takes no order_id: the parent sets its parent_fk key on add (§4.2, #49)
    return order.set(Order.items.add(Item(sku=sku, price=..., position=order.items.count)))

# Expression form: if the condition and the match are column expressions, they fold into a subquery with no extra round trip
type PointWallet = Annotated[Wallet | None,
    Load.when(Order.paid_with == PaymentMethod.POINT, match=Wallet.user_id == Order.user_id)]
    # match compares two columns of the same value type: a predicate over Wallet | Order (§8.2 "Field type surface", #51).
    # Inside Annotated metadata only pyright type-checks it (mypy checks nothing there, spike 0002 X1); seal validates the declaration

# Function form (Load.after): when it is hard to express as an expression. Argument names bind to use case parameters
def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.paid_with is PaymentMethod.POINT else None

type PointWalletAfter = Annotated[Wallet | None, Load.after(point_wallet)]   # adds one load stage

@usecase
def refund(order: Annotated[Order, Load(Order.items)], wallet: PointWallet = INJECTED) -> Changes:
    changes = order.set(Order.status.to(OrderStatus.REFUNDED))
    if wallet is not None:
        changes += wallet.set(Wallet.balance.path(Money.amount).add(order.total.amount))
    return changes

# Recursive load
type RoleTree = Annotated[list[Role], Load.recursive(start=User.roles, via=Role.parent, max_depth=10)]
```

- The **expression form** is allowed only when there is exactly one parameter of the same entity type. With two or more, seal raises an error and points to `Load.after`.
- In the **function form**, argument names bind to use case parameters (checked at seal), and a typed function is recommended (lambda arguments are inferred as `Any`). The function must be pure and returns a ref or `None`.
- **`None` and `NotFound` are distinguished.** If the condition is false or the function returns `None`, the result is `None`; if the condition is true but the row is missing, it is `NotFound`. If absence is acceptable, use `Load.after(fn, missing="none")`.
- Logic that "follows data without end" and cannot be expressed even this way cannot fit into a single use case (§7.1).

### 4.8 Bulk writes

```python
@usecase
def import_products(rows: list[ProductRow]) -> Changes:
    return insert_all(Product(sku=r.sku, price=r.price) for r in rows)   # COPY, chunk streaming

@usecase
def expire_orders(now: Now = INJECTED) -> Changes:
    return orders.expire_older_than(now - timedelta(days=30))   # set change factory of the Repository

@batch_usecase(chunk=5_000, cursor=Account.id, job="apply-interest-2026-11")
def apply_interest(accounts: Chunk[Annotated[Account, Load(Account.product)]]) -> Changes:
    return changes(a.set(Account.balance.add(calc_interest(a))) for a in accounts)   # balance: Col[Decimal]

await app.run_batch(apply_interest)   # commit per chunk, checkpoint written in the same transaction, resumes on restart
```

`emit_each` on a set change fills in the event sequence numbers from the result of `UPDATE … RETURNING id, version` and passes them to the outbox INSERT (a CTE in one statement).

- **`insert_all` is not `insert` with more rows** ([ADR-0010](../adr/0010-writes-beyond-set.md)). `insert(entity)` writes one row in the pipelined commit batch, planned like any row change (§4.4); `insert_all(...)` streams many rows with COPY or chunks, outside the pipeline, with no per-row planning (#33, Phase 2). Different behaviour, different name. `insert_all` takes no owned children: it has no way to add them, and an owned child passed to it is a `UsageError` (*Proposed*).

### 4.9 TypedSQL and t-strings

```sql
-- shop/billing/queries/order_stats.sql
-- name: order_stats
SELECT date_trunc('day', created_at) AS day, count(*) AS orders, sum(total_amount) AS revenue
FROM orders
WHERE created_at >= :since
GROUP BY 1
ORDER BY 1;
```

```python
from shop.billing.generated import sql          # output of platina gen (committed to the repository)

stats: list[sql.OrderStatsRow] = await app.query(sql.order_stats(since=date(2026, 11, 1)))

# Ad hoc query: t-string + DTO, columns validated at runtime
rows = await app.query(raw(OrderSummary, t"SELECT id, number, total_amount AS total, 0 AS item_count FROM orders WHERE user_id = {uid}"))
```

### 4.10 Event consumption: projections, then, process

#### Projections: declare the target and the key; the body is field operations only

```python
@projection(on=OrderPaid, into=UserSpending, key=OrderPaid.user_id)    # inline by default: same transaction
def user_spending(e: OrderPaid) -> Ops[UserSpending]:
    return (UserSpending.total.add(e.total.amount),)

@projection(on=OrderPaid, into=DailyRevenue, key=lambda e: e.paid_at.date(), mode="async")
def daily_revenue(e: OrderPaid) -> Ops[DailyRevenue]:                  # date-keyed aggregates go async
    return (DailyRevenue.total.add(e.total.amount),)

@projection(on=OrderPaid, into=DailyRevenue, key=lambda e: e.paid_at.date(),
            allow_hot_key="low traffic, and strong consistency of daily totals is required")   # explicit opt-in
def daily_revenue_strict(e: OrderPaid) -> Ops[DailyRevenue]: ...
```

- **The target (`into`) and the key (`key`) are in the declaration; the body is only field operations on that row.** Workarounds such as the body upserting with a different key are impossible, so seal can check the hot row rule precisely. If several rows must be updated, split the projection.
- **Inline key rule**: only entity ID fields of the event are allowed. Derived keys such as dates or constants are rejected at seal (async or `allow_hot_key`). Entity IDs can be hot too, so a **per-projection retry rate metric** is always emitted.
- The **async projection consumer** is a serial path. It reads the log in a separate READ COMMITTED transaction and commits the effect and the checkpoint together in a **REPEATABLE READ** transaction (the field operations are commutative and there is one consumer per checkpoint, so SERIALIZABLE is not needed). When a poison message arrives, it is not skipped; the consumer **stops and alerts.** Skipping would corrupt the read model.

#### then and process: the two-tier job pipeline

```python
@process(on=PaymentRequested)                       # the only place where external IO is allowed
async def approve_payment(e: PaymentRequested, ctx: ProcessContext, pg: PgClient) -> Bound | None:
    res = await pg.approve(e.payment_key, e.amount, idempotency_key=ctx.idempotency_key)
    if res.ok:
        return confirm_payment.bind(order=Order.ref(e.order_id), approval=res.id)
    return cancel_order.bind(order=Order.ref(e.order_id), reason=res.code)
    # Does not call app.run. The dispatcher commits the returned description in one transaction with the completion record.

class InsufficientBalance(DomainError, retry_later=RetryLater(max_attempts=5, within="1h")): ...
```

```
outbox log ─[log reader: xid watermark, READ COMMITTED]→ INSERT into per-handler job table (+ reader checkpoint, same transaction)
job table ─[worker: acquire lease in a short READ COMMITTED transaction, SKIP LOCKED]→ run handler (external IO outside the transaction)
           ─[dispatcher: run the returned use case with the job ID as the run ID. run_claim is the completion record]→ done
```

- **process returns a description.** The dispatcher commits that use case and the completion record in one transaction, so once committed there is no redelivery at all. In the common shape (IO followed by one use case), no key design is needed. If there are several use cases, chain them with `then`. The dispatcher does not import a runner: `app` hands it the function that executes a bound use case under a run ID (ADR-0001).
- **External idempotency is needed separately.** If the external IO has finished but the dispatcher dies before committing, the job is redelivered and the external call is repeated. So the framework provides an event-based `ctx.idempotency_key`, and the rule is to use this key for external calls. For external APIs that do not accept an idempotency key, write the handler to "query the state first, then decide".
- **Leases outside the transaction.** If a transaction holds a row lock while waiting for external IO, it stays open holding an xid, and the log reader's entire xid watermark stalls. Acquiring the lease and writing the completion record are each a short transaction.
- **Completion record and fencing with `run_claim` alone.** The dispatcher uses the job ID as the run ID, so the `run_claim` INSERT, the first statement of the use case transaction, is itself the completion record. If a lease expires and two workers finish the same job, the later one gets 23505 and does nothing (if the earlier one is still in progress, it waits on the unique key until that is decided). Even when the handler returns `None`, the dispatcher commits a transaction containing only `run_claim` to record completion. It does not read a lease token, so the internal table rule holds.
- **Ordering within an aggregate**: for each aggregate key, only the earliest job can be in progress (e.g. a `PaymentCancelled` for an order does not overtake its `PaymentRequested`).
- **Distinguishing failure kinds**:
  - Transient errors (connection, `RunTimeout`, 40001 limit exceeded): retry with backoff.
  - Domain exceptions: immediate dead-letter by default. They are retried later only when the exception type declares `retry_later=RetryLater(max_attempts, within)`. This setting only has meaning in the job runner; in an `app.run` called from HTTP, the exception propagates immediately. Beyond the limit: dead-letter.
  - When the head job goes to dead-letter, **later jobs with that key are blocked too.** The damage is isolated to one aggregate. A "blocked keys" metric and operational tooling to resend or skip while leaving an audit record are provided together.
- `then` use cases run under SERIALIZABLE with use case semantics unchanged.
- External dependencies such as `pg: PgClient` are registered with `app.provide(PgClient, factory)` and injected. Use cases have no such injection.

### 4.11 Web framework integration (FastAPI example)

```python
from fastapi import FastAPI, Header
from platina.integrations.fastapi import lifespan, ConsistencyTokenMiddleware

api = FastAPI(lifespan=lifespan(app))           # app.seal() at startup, pool cleanup at shutdown
api.add_middleware(ConsistencyTokenMiddleware)  # X-Consistency-Token header ↔ contextvar

@api.post("/orders/{order_id}/pay")
async def pay_order(order_id: UUID, idem: str = Header(alias="Idempotency-Key")):
    await app.run(pay.bind(order=Order.ref(order_id), wallet=wallets.by_user(current_user().id)),
                  idempotency_key=idem)
    return {"ok": True}                         # the middleware puts result.token in the response header

@api.get("/orders")
async def list_orders():
    return await app.query(orders.summaries(user_id=current_user().id))   # token from the request header applied automatically
```

### 4.12 Testing

```python
# Unit tests: no DB. Calling use cases and steps directly returns a StepResult
def test_pay_moves_balance():
    order = Order.stub(status=PENDING, total=Money(Decimal("1000")))
    wallet = Wallet.stub(balance=Money(Decimal("5000")))
    r = pay(order, wallet, now=datetime(2026, 11, 24))
    assert r.updated(order) == {Order.status: PAID, Order.paid_at: datetime(2026, 11, 24)}
    assert r.updated(wallet) == {Wallet.balance: Add(Decimal("-1000"))}
    assert r.events == [OrderPaid(order_id=order.id, user_id=order.user_id,
                                  total=order.total, paid_at=datetime(2026, 11, 24))]

def test_checkout_charges_discounted_total():
    order, coupon = Order.stub(total=Money(Decimal("1000"))), Coupon.stub(rate=Decimal("0.1"))
    wallet = Wallet.stub(balance=Money(Decimal("5000")))
    r = checkout(order, coupon, wallet, now=NOW)
    assert r.updated(wallet) == {Wallet.balance: Add(Decimal("-900"))}   # thanks to chain, the discounted amount is charged

def test_merge_deletes_the_source():                       # spike 0002 use case 6 (ADR-0010)
    src, dst = Order.stub(status=PENDING, items=[Item.stub()]), Order.stub(status=PENDING)
    r = merge(src, dst, None)
    assert r.removed(src)       # its owned items and tickets go with it, recorded as "every owned
                                # child of src", not as rows (Proposed, ADR-0010: r.removed(item) is
                                # true for a loaded child of src; the unloaded ones are not listed)

def test_transfer_inserts_the_root_and_its_legs():         # spike 0002 use case 8
    r = transfer(Account.stub(balance=Money(Decimal("100"))), Account.stub(), Money(Decimal("30")))
    assert len(r.inserted(Transfer)) == 1
    assert len(r.inserted(Leg)) == 2

def test_alias_of_moved_snapshot_is_rejected():
    @usecase
    def bad(order: PayableOrder, wallet: ChargeableWallet) -> Changes:
        alias = order
        with chain(order, wallet) as (c, order, wallet):
            c.run(charge, wallet, alias.total)            # alias created before the chain
        return c.changes
    with pytest.raises(MovedSnapshotAccess):
        bad(Order.stub(), Wallet.stub())

# Repository tests: snapshot of the generated SQL (no DB)
def test_summaries_sql(snapshot):
    assert orders.summaries(user_id=uid).compile() == snapshot

# Integration tests: real PostgreSQL + round-trip budget
async def test_pay_roundtrips(app_with_db):
    with app_with_db.expect_roundtrips(max=2):          # 1 load + 1 commit batch
        await app_with_db.run(pay.bind(order=..., wallet=...))
```

### 4.13 Error message examples

```
RelationNotLoaded: Order.items is not loaded.
  Location: shop/billing/usecases.py:12  (pay)
  Actual load declaration: Load()
  Example of the needed declaration: orders.payable = Profile(Order.items, Order.user)
  Fix: use Annotated[Order, orders.payable] or add Load(Order.items)

MovedSnapshotAccess: alias is an alias of order, which was moved by chain. Order.total was read.
  Location: shop/billing/usecases.py:31  (checkout)
  Fix: use the order returned by chain, or c.original(order) if you need the value before the change

UnloadedReference: .set was called on Order.ref(...). A ref is only a load request.
  Fix: take it as a use case parameter so it is loaded, or state it explicitly with Order.where(Order.id == x).set(...)

SealError: the key of inline projection daily_revenue is not an entity ID (date).
  Fix: mode="async" or allow_hot_key="reason"

SealError: a set change modifies a field protected by an invariant.
  Location: shop/billing/repos.py:41  (OrderRepo.expire_older_than)
  Field: Order.status  ← @invariant paid_requires_total (entities.py:29)
  Fix: move the invariant to Check(...) or state .set(..., unsafe_bypass="reason") explicitly

SealError: refund's parameter wallet is filled by a dependent load (Load.when) but has no default.
  Location: shop/billing/usecases.py:58  (refund)
  Fix: write wallet: PointWallet = INJECTED (the runner fills it; bind and app.run never take it)

SealError: the Load.when expression is ambiguous. refund_merge has two parameters of type Order (src, dst).
  Fix: use Load.after(function) to state which parameter is meant

ModuleBoundaryError: shop.catalog.usecases.restock loads the entity Order of the billing module.
  Fix: use a query published by billing (orders.summaries) or communicate through events
```

Every message has the same layout ([ADR-0006](../adr/0006-exception-fields-and-rendering.md)): the headline, then one line per present item, each indented two spaces - `Location: <file>:<line>  (<function>)`, the `details` lines in order, `Fix: <hint>` last. The `ClassName:` prefix shown above is printed by the traceback (module-qualified there, `platina.core.errors.RelationNotLoaded:`); it is not part of `str(exc)`.

---

## 5. Async

### Choice per layer

| Layer | Choice |
|---|---|
| Core (load plan, ChangeSet, SQL compilation) | **sans-IO**, no dependency on an async library |
| async runner | Written against the **anyio** API (cancellation semantics, structured concurrency) |
| Backend | **asyncio only**, uvloop at the user's choice |
| sync runner | Uses psycopg sync connections directly, a first-class path |
| Driver | **psycopg 3.3+** only |

### Why anyio
- **Cancellation semantics**: protect the commit and rollback sections with `CancelScope(shield=True)`
- **Structured concurrency**: run independent loads in parallel with a task group, clean cancellation on failure

```python
async def run(bound: Bound[P], *, idempotency_key: str | None = None) -> RunResult:
    run_id = RunId.caller(idempotency_key) if idempotency_key else RunId.auto()
    async with pool.connection() as conn:
        return await drive_async(run_usecase(bound, run_id, policy, PG), conn)
    # the engine (§10.5) issues commands, and drive_async shields the commit batch and rollback sections
```

### Resolving the function color problem
Domain functions have no IO and are not generators (dependent loads are declarative). So they take on no color, sync/async or otherwise, and use cases and steps are plain functions that compose freely in `chain`.

### Pipeline
Because the load plan is fixed before execution, psycopg pipeline mode sends each stage of the plan in one round trip. Expression-form dependent loads (`Load.when`) fold into the same stage as subqueries; only `Load.after` adds a stage. At commit, INSERT, UPDATE and outbox statements are also bundled into a pipeline. However, `COPY` is not supported in a pipeline, so bulk insert takes a separate path.

---

## 6. Supported targets

### Runtime
- **Python 3.14+**: t-strings (PEP 750), deferred evaluation of annotations (PEP 649/749), official free-threaded support
- **PostgreSQL 14+**: pipeline mode requires client libpq 14 or later. The server is also 14+ for `WITH RECURSIVE … CYCLE` and similar

### Coexistence with existing ORMs (as a standalone ORM)
- No adapters are built. Instead, only **coexistence on the same DB** is supported
  - `platina pull`: reads the DB catalog and generates entity definitions (works the same for DBs managed by Django or SQLAlchemy)
  - Generates a **DB trigger** that increments `version`: makes writes by other ORMs subject to optimistic locking too
  - Caution: SERIALIZABLE guarantees hold only between SERIALIZABLE transactions, so on tables written by other ORMs the `version` trigger is the real safeguard
- Keep CRUD and admin on the existing ORM, and move only the core use cases to Platina

### Step-by-step adoption (the stairway)

| Step | What is adopted | What you get |
|---|---|---|
| 0 | `platina pull` + query path (TypedSQL) only | Typed SQL, query instrumentation |
| 1 | Load declarations + 1 use case | Structural elimination of N+1, pipeline |
| 2 | More use cases + `chain` | Tests without a DB, automatic retry |
| 3 | inline projections and outbox | Auditing, read models |
| 4 | async projections, process, module boundaries | Preparation for splitting into services |

> Because we chose a standalone ORM, "step 0: putting a plugin on top of an existing ORM" is gone. Instead, entering through the query path is the lowest entry point.

### Target users
- **Primary target**: teams that want "a monolith for speed now, and no pain when splitting it off later"
- **Well-suited domains**: orders, ledgers, reservations, settlement, payments
- **Goal**: "use this for the 20% where money and consistency are at stake"
- **Areas we do not compete in**: simple CRUD and admin

---

## 7. Limitations

### 7.1 Domains that decide by following data
Because dependent loads are allowed only as declarations (expression, function, recursive), the number of round-trip stages of every use case is fixed at seal time. The cost is that logic which follows data to a depth that cannot be known in advance (traversal that cannot be expressed even as a recursive CTE) cannot fit into a single use case.

Splitting the use case in two here is not just an inconvenience; **it loses atomicity.** Values read in the first transaction do not protect the writes of the second. So such logic must either be computed inside the DB with recursive CTEs or TypedSQL, or be designed so that the second use case reloads and revalidates its premises.

### 7.2 Interaction with the outside world
Flows where an external result decides the write are split into a process handler and several use cases. The cost of a single JPA method becoming an event flow remains.

### 7.3 The cost of the SERIALIZABLE default
On highly contended tables, serialization failures and retries increase. Two kinds of 40001 differ here. SSI's read/write-dependency failures (the write-skew case) can be escaped with `isolation=REPEATABLE_READ` + `version`, which then does not prevent write skew. The same-row write conflict ("could not serialize access due to concurrent update") on a hot row cannot be escaped: under REPEATABLE READ and SERIALIZABLE, neither `lock="for_update"` nor a blind increment (`.add(n)`) avoids it once a concurrent command has updated and committed the row after the transaction's snapshot; each such writer waits, fails once and is retried (spike 0002, reproduced; [ADR-0005](../adr/0005-hot-rows-under-serializable.md)). Spike 0003 (§9.2) measured it on one hot row: `lock="for_update"` fails as often as a blind increment (about 31-41 / 75-78 / 90 % of attempts at 8 / 32 / 64 workers) and only moves the failure to the load statement, so it counts as "fail early", not as an escape hatch. Whether `lock=` stays, and which approach the design takes for genuinely hot rows (the candidates are listed in ADR-0005), are decided in #64. Hot rows created by inline projections are mostly prevented by the key rule (§4.10), but entity ID keys can be hot too. Measured in [spike 0003](../spikes/0003-ssi-internal-tables.md) (§9.2): on uniform access SERIALIZABLE stays within about 10 % of REPEATABLE READ's throughput with at most 1.007 attempts per commit; under skewed access the retries are mostly same-row conflicts both levels share, and SERIALIZABLE ranged from about 7 % faster to 17 % slower. The two main sources of false conflicts found: a read the planner turns into a sequential scan takes a relation-level lock (small tables), and ever-increasing keys put reads of recent rows - including the foreign-key check of a new child, which reads its parent's primary-key index - and new inserts on the same index page ([ADR-0007](../adr/0007-ever-increasing-entity-keys.md), Proposed).

### 7.4 Remaining problems with bulk writes
- Set-based updates are allowed only on fields without an `@invariant`
- Chunked commits are handled with checkpoints and idempotency, but it amounts to operating a small Spring Batch yourself

### 7.5 The decisive limitation: an architecture, not an ORM
"No implicit IO" and "immutable entities" cannot be adopted gradually, and they do not fit ecosystems that assume mutable models (Django admin, DRF, factory_boy). Because we chose a standalone ORM, the only way to seep into an existing codebase is "coexistence on the same DB".

### 7.6 Limitations from the restricted scope
- Initially PostgreSQL only (MySQL timing undecided), psycopg only, asyncio only
- A codegen step is added to the build, and codegen needs a temporary DB (the output is committed)

### 7.7 The cost of the infrastructure tables
- Every command INSERTs a run ID row (with a caller key, 2 rows including the result row). Rows past the retention period need a cleanup job.
- `then` and `@process` events are copied once more into per-handler job tables. This causes write amplification and cleanup cost.
- A single long-open write transaction holding back the xid watermark delays every consumer by that much.
- These costs are the price of "removal over detection". In exchange for handling idempotency and commit resolution with a single run ID, and isolating poison messages with job tables, writes increase. The actual size is measured by the experiments in §9.

---

## 8. Decision record

### 8.1 Identity

**Form: standalone ORM (runtime), schema tooling via SQLAlchemy Core + Alembic (optional extra)**
- Decision: the query compiler and the execution engine are built in-house without depending on SQLAlchemy. The compiler has a dialect layer, but the first implementation starts with a single PostgreSQL dialect. DDL, reflection and migrations use SQLAlchemy Core and Alembic in the `platina[migrate]` extra (§8.5).
- Rationale: the execution engine is a sans-IO state machine that issues commands per pipeline, so it does not fit SQLAlchemy's execution layer (DBAPI cursors, greenlet-based async). The query AST is a limited PostgreSQL-only set, and as immutable objects it is directly both the load plan and the cache key, so building it ourselves is cheap. On the other hand, DDL, catalog reflection and migrations are the most expensive parts to build ourselves, so we use Core and Alembic.
- Correction: the earlier rationale ("conflicts with SQLAlchemy's Session and identity map") was wrong. Session belongs to the ORM layer; Core has none. A review pointed this out, so the rationale was rebuilt, and in the process the decision changed to the hybrid that hands schema tooling to Core.

**Name: Platina**
- Decision: package and import name `platina`, CLI also `platina`. The optional extra is `platina[migrate]`; official plugins are `platina-pydantic` and `platina-saga`.
- Rationale: platina is the Spanish name ("little silver") under which platinum first became known in Europe. Three properties of platinum overlap with the design.
  - **A noble metal that does not react**: it barely dissolves in acid and does not rust. Domain code does not react with the DB (pure functions).
  - **Catalyst**: it causes a reaction but is itself neither consumed nor changed. The ORM runs transactions, and the domain stays as it is.
  - **The prototype of a standard**: the former International Prototype of the Kilogram was a platinum-iridium alloy. This ties into the story of a project that started from "Python ORMs have no standard like JPA".
- Verification: as of 2026-11-25, `platina` does not exist on PyPI. On GitHub there is no library with the same name; there are only kernel repositories that use it as a Xiaomi device codename.
- Candidates considered:
  - `purelational` (Pure + Relational, the first name), `teduri` (border = boundary): replaced after deciding to look for another name.
  - `munjigi` (gatekeeper), `maedeup` (knot), `purrm` (pure + ORM): available, but platina explains the first principle, "the domain is pure", through a property, so it hits the core more directly.
  - `platinorm`, `baekgeum` (platinum): available, but respectively the suffix is too literal, and the romanization is hard for users abroad.
  - `platinum`, `iridium`, `rhodium`, `osmium`, `palladium`, `dojang`, `airlock`, `sluice`: already on PyPI. `platine`: German for "circuit board", confusing. `edgewise`: already used by an ORM for EdgeDB. `docket`: a Python job library with the same name exists.
- Follow-up: register the name on PyPI with a minimal working version (0.0.1) to secure it. Squatting the name with an empty package can be subject to reclamation under PEP 541.

**License: Apache-2.0**
- Rationale: it has a patent clause, which favors enterprise adoption. Hibernate also moved from LGPL to Apache 2.0 starting with ORM 7.0, citing broader acceptance in the Apache/Jakarta ecosystems among others as the reason.
- Dependency check: psycopg (LGPL-3.0-only) is a dynamic import dependency, so it is no problem for Apache-2.0 distribution. anyio (MIT), import-linter (BSD-2), and SQLAlchemy and Alembic (MIT) in the optional extra are compatible.

### 8.2 Core design

**Load declaration syntax: `Annotated[Entity, Load(...)]`**
- Decision: declare with `Annotated` metadata instead of call expressions in annotations. Reuse through PEP 695 `type` aliases.
- Rationale: both mypy and pyright reject call expressions in annotation positions as invalid types. `Annotated` is a pattern already familiar from FastAPI `Depends`.
- Implementation: decorators read annotations in the `FORWARDREF` format of `annotationlib`, and actual resolution happens at seal time. From Python 3.14, deferred evaluation of annotations is the default, so circular references between entities can be written without strings.

**Validation time: import time → seal time**
- Decision: the initial idea that "import time is Python's compile time" is discarded; validation happens in `app.seal()` (app startup) and `platina check` (CI).
- Rationale: Python 3.15 added explicit lazy imports (PEP 810), and there is also a global lazy mode flag. When this flag is on, module execution is delayed, so validation that relies on import side effects cannot be trusted. PEP 649's deferred annotations point in the same direction.

**Field type surface: the `Col[T]` wrapper and owner-typed columns**
- Decision: every column field of entities, events and value objects is declared as `Col[T]` (`status: Col[OrderStatus] = column(...)`, `amount: Col[Decimal]` in `Money`). Relations are `Rel[...]` (`many_to_one`, `one_to_many`), and owned collections `Owned[list[...]]` (`owns_many`): on the class `Relation[Owner, E]` (read and load only) and `OwnedRelation[Owner, E]` (adds `add` / `remove` / `update`), on the instance `Sequence[E]`. A relation operation is a `RelOp[Owner]` (`add` an `AddOp[Owner]`), invariant in its owner and not an `Op`, so a set change rejects it by type and `insert` takes `add` only (spike 0007; [ADR-0010](../adr/0010-writes-beyond-set.md)). Class access is `Column[Owner, T]`, where the owner is the class that declares the field (`Order.status`: `Column[Order, OrderStatus]`); instance access is `T`. Paths into embedded values are `Order.total.path(Money.amount)` (`Column[Order, Decimal]`). `Column`'s owner parameter is covariant and its value parameter invariant, pinned by type tests (ADR-0004).
- Rationale: with a plain annotation, the type checker also sees class access (`Order.status`) as `T`. For it to appear as a column on the class and `T` on the instance, the annotation itself must be a descriptor type with an overloaded `__get__`. SQLAlchemy 2.0's `Mapped[T]` exists for the same reason. `.to()`, Finders and projection keys all stand on top of this. The owner comes from the `owner` argument of `__get__`, so operations (`Op[Owner]`), predicates and relations carry the entity they belong to. Spike 0001 confirmed all of it under pyright and mypy.
- **Where the owner is checked**: by types only where the receiver fixes the owner - `order.set(...)`, `Entity.where(...)`, `RowSet.set(...)`, `SetChange.set(...)`, `SetChange.emit_each(...)`, relation operations, the Finders of `Repository[E]`, and `path` - and in `insert(entity, *children)`, where the owner is solved from several arguments but `RelOp`'s invariance leaves the entity as the only solution (under mypy a declared type written on a relation's class access can still widen it, ADR-0004). Where the owner would have to be inferred from several arguments of one call it is not checked by types: queries (`select`/`join`/`where`) are validated when their description is built (whether seal can also catch them is #52), and `Profile`, `Load`, `Index`, `Check` and `@invariant(fields=...)` are validated by seal. Reason (spike 0001, P-A): given columns of two entities in one call, pyright infers the owner as the union `Order | Item` and mypy as the common base `Entity`, so the same misuse would be an error under one checker only.
- **Comparison operands** (#51, [spike 0006](../spikes/0006-parent-fk-and-column-operands.md)): a value compared with a column is exactly `T`, with no numeric widening - `Order.total.path(Money.amount) >= 0` is a type error and §4.2 writes `>= Decimal(0)` (the typing spec's `int` to `float` promotion still applies to a `float` column). Two columns compare directly, through overloads of `Column`'s comparison operators, when they have the same value type; a difference in nullability only (`T` against `T | None`) is allowed. The result is a predicate over both owners: `Column[O, T] == Column[O2, T]` is `Pred[O | O2]`, so a place where the receiver fixes the owner (`Order.where(...)`) still rejects a predicate that mentions another entity's column. Where two entities are in scope the owner is checked by the query description or by seal (ADR-0004 Decision 4); the parameter type that accepts a predicate over two owners there is open (queries #52; `Load.when`'s `match` takes `Pred[object]` in the spike's stub). That rejection rests on `Pred` being covariant in its owner: like `Column`'s, its variance is declared and pinned by a type test when it is written (spike 0006 O1). The value and the column forms are separate overloads; no parameter takes `T | Column[O, T]`, the shape on which the checkers split (spike 0001).
- Comparison gaps (open, decided in #9; spike 0006):
  - `==` and `!=` with a value of the wrong type are `bool` to both checkers, which fall back to the value's reflected `__eq__` (typeshed: `(object) -> bool`); the mistake is reported only where a predicate is required (`Order.where`, `Check`, `Load.when`, `select(...).where`). That is the checkers' view: at run time `Column.__eq__` is called first, and what it does with a value that is not a `T` must not end in a silent `bool`.
  - `== None` on a non-null column is the same case. On a nullable column `== None` is a `Pred` whose SQL meaning (compiled to `IS NULL`, or replaced by an explicit `is_null()`) is open, and ordering against `None` (`Order.guest_id >= None`) is accepted by both checkers although it can never be true in SQL.
  - Ordering on an enum column is accepted (`Order.paid_with >= PaymentMethod.POINT`), although Python's plain `Enum` has no order and the SQL order depends on `enum_as` (`IntEnum` and `StrEnum` are ordered, and a `StrEnum`'s order by value can differ from a native PostgreSQL enum's declaration order).
  - Comparisons on an embedded value column are accepted (`Order.total >= Money(...)`, `Order.total == Money(...)`). The value class is ordered (`@value` orders its fields, so `wallet.balance < order.total` in §4.5 is a plain `bool`), but the column spans several SQL columns: whether such a comparison compiles to a row comparison or is allowed only through `path(...)` is open.
  - A column in a set (`{Order.amount}`) is rejected by pyright and accepted by mypy (`Column` defines `__eq__` without `__hash__`, which also makes it unhashable at run time).
  - Comparing columns of different numeric types (`Decimal` against `int`) needs an explicit cast that is not designed yet; until then it is a type error.
- Cost: annotations get longer, `Column` has two type parameters wherever it is named, value objects declare `Col[...]` fields, and an increment of a part of a value object goes through its path (`Wallet.balance.path(Money.amount).add(n)`). `Order.total.amount` cannot be typed by a generic column.

**Creation syntax and constructor types**
- Decision: entities inherit the `Entity` base class, and creation is its keyword constructor (`Order(number=..., total=...)`), like events and values; there is no `new`. Modification of a loaded row is `.set`, insertion of a new row `insert(...)`, deletion of a loaded row `.delete()` ([ADR-0010](../adr/0010-writes-beyond-set.md)). "Only one way" applies per operation. Creation and modification are different operations (ADR-0003).
- Rationale: a missing required field is the most common mistake when creating an entity, so under "correctness first" it must be caught statically. The alternative of unifying creation into the operation syntax as well, `Order(Order.sku.to(...), …)`, was rejected because it pushes this check down to runtime. A separate classmethod `new` can only be typed by copying the constructor's signature, so the plain constructor would type-check next to it; dropping `new` removes the second way instead of detecting it.
- Order of attempts to get the types: step 1 holds (spike 0001), so steps 2 and 3 are not needed.
  1. **Chosen.** The descriptor's `__set__(self, instance: Never, value: T)`: the constructor synthesised through `dataclass_transform(kw_only_default=True, frozen_default=True, ...)` on `Entity` takes each parameter type from the value of `__set__`, and assignment is blocked (pyright `reportAttributeAccessIssue`, mypy `misc` and `arg-type`). Field specifiers declare `init: Literal[False]` for generated keys, `version_column()`, server defaults, relations and the parent key of an owned child (`parent_fk`), so they are not parameters.
  2. Typed creation functions in a generated **real Python module**.
  3. Runtime checks only (last resort).
- Generating `.pyi` stubs was rejected. A stub cannot overlay just the constructor; it replaces the types of the whole module, so until you add a field and regenerate, the editor shows the old shape.
- Entities are hashable at the type level (`frozen_default=True`; without it pyright and mypy disagree on `{order}`). The runtime rule (decided in #54 from spike 9.4's data, ADR-0003 Decision 4): equality compares the entity type and the column values only (embedded values included; relations and the load state are not compared, so a stub and a loaded snapshot holding the same values are equal, as are two snapshots of one row loaded through two paths); a column without a value yet (a server default or an `identity` key of a new entity) is equal only when it has no value on both sides; the hash is the entity type plus the primary key (the parent key of an owned child before `add` has no value yet: #76); refs raise `UnloadedReference`, a new entity with an `identity` key has no hash before commit (`UsageError`), a chain view compares its latest state, and a moved alias raises `MovedSnapshotAccess`. `version` is a column and a change to an owned child bumps the root's version, so two snapshots of a row before and after a commit differ. Identity equality (type and key, Django and Rails) was rejected: `assert before == after` would pass after a change. `==` does not compare children; comparing a whole aggregate is a test-kit helper (#27). Remaining cost: a new `identity` entity cannot be a set member or dict key before commit, and two new entities with equal values compare equal, so the engine and the planner identify new rows by object identity, never by `==`.
- **The key of an owned child is set by the parent** (#49): the child declares it with its own field specifier `parent_fk(lambda: Order)` (working name, fixed in #9), it is not a constructor parameter, and `Order.items.add(Item(...))` fills it. A child of a relation that is not owned keeps `fk(lambda: Order)`, an ordinary required parameter. A flag on `fk` (`fk(..., parent=True)`) was rejected: it would make one specifier mean two things, so the name differs ("configuration never changes meaning"). Rationale: in spike 0002 every owned child passed its parent's key by hand, and a child added to one parent with another parent's key was accepted by both checkers; without the parameter a new child cannot be created with another parent's key ("remove rather than detect"). Confirmed under both checkers by [spike 0006](../spikes/0006-parent-fk-and-column-operands.md).
- Owned children of a new root are written `insert(t, Transfer.legs.add(...), ...)`, and a relation that is not owned has no `add` (decided on #60, [ADR-0010](../adr/0010-writes-beyond-set.md)); seal checks `owns_many`, `parent_fk` and `aggregate_root=True` against each other ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed).
- Open: `Order.stub(...)` keywords are not type-checked (#50); reading the parent key of an owned child before it is added (#76); the final names of `parent_fk` and `owns_many`, and moving an existing child to another parent, which still type-checks (spike 0006 O9) (#9).

**Dependent loads: declarative only, no generators**
- Decision: additional data needed is declared with `Load.when` (column expression) or `Load.after` (typed pure function). There is no way to request data with `yield` inside a use case.
- Rationale: generator use cases were a new function color. They could not simply be put into `chain`, the caller also had to become a generator, and since there is only one send type, the type of `wallet = yield ...` could not be inferred. Switching to declarations removes the color, makes parameter types (`Wallet | None`) precise, and fixes the number of round-trip stages of every use case at seal time.
- The expression form is allowed only when there is exactly one parameter of the same entity type (with two, seal error → points to `Load.after`). The condition and the match are column expressions, so they fold into a subquery with no extra round trip.
- In the function form, argument names bind to use case parameters (checked at seal), and typed functions are recommended over lambdas (lambda arguments are inferred as `Any`).
- `None` and `NotFound` are distinguished. If the condition is false, `None`; if the condition is true but the row is missing, `NotFound`. When absence is acceptable, state it explicitly with `missing="none"`.
- Cost: traversal of unknown depth cannot be expressed (§7.1).

**Recursive loads**
- Decision: `Load.recursive(...)` → `WITH RECURSIVE`. `max_depth` is required; cycle detection with the `CYCLE` clause of PostgreSQL 14.

**Scope of external effects**
- Decision: no effects of any kind are allowed inside use cases. External IO is possible only in `@process` handlers, and even handlers do not run use cases directly; they **return a description** (§8.4 job processing).
- Rationale: the moment effect requests (`Call(...)`) are allowed, the runner becomes an effect interpreter, and the anti-pattern of waiting for external IO inside a transaction opens up. Fixing two kinds, "pure (usecase) / impure (process)", fits the philosophy.

**Call syntax: `bind` + placeholder refs**
- Decision: a use case call builds a description with `uc.bind(...)` and executes it with `app.run(description, options)`. A ref (`Order.ref(id)`, `orders.by_number(n)`) is a placeholder that is an entity at the type level, and parameters injected by the runner have the default `INJECTED`.
- One marker (#48): every parameter the runner fills - an injected type or a dependent load - defaults to `INJECTED`, and no other parameter does (a `SealError` either way). `bind` given such a parameter raises `UsageError` (it is filled fresh on every attempt); a direct call must pass every parameter (`UsageError` naming the one left out). These parameters come last or are keyword-only, since they have a default. A second marker for dependent loads (`LOADED`) was rejected: for the caller both mean "do not pass this", and seal tells them apart from the annotation. The marker cannot live in the annotation alone (FastAPI's `Annotated[..., Depends(...)]` form): without a default the parameter stays required in `bind`, because `ParamSpec` cannot drop parameters (PEP 612; spike 0002 X5).
- Rationale: the previous proposal (`app.run(pay, order=Order.ref(id))`) had to change the parameter type from `Order` to `Ref[Order]` and drop `Now`, but ParamSpec cannot express such transformations, nor can run option keywords sit next to `**kwargs: P.kwargs` (PEP 612). If a ref is an entity at the type level, the signature of `bind` equals that of the use case and it is checked with ParamSpec alone. It is the same idea as JPA `EntityManager.getReference()`.
- A Finder is callable (`orders.by_number("A-1")`), so its argument is checked against the column type.
- `.set` and `.delete()` on a ref are also blocked with `UnloadedReference`. It is a write that reads no fields, so if left alone it would be a write that skips the load and the `@invariant` checks. A write without loading is stated explicitly as a set change `Order.where(Order.id == x).set(...)`.
- Cost: reading a field of a ref on the calling side is an error only at runtime (immediately and deterministically).

**Write syntax: `.set` for loaded rows, `insert` for new rows, `.delete()`** ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed)
- Decision: one way per write operation. A loaded row is modified by passing field operations, as in `order.set(Order.status.to(PAID), Order.paid_at.to(now))`, and the owned children of a root through its relation operations `Order.items.add/remove/update` inside the same `.set`. A new row is written with `insert(entity)`, a new root with its owned children with `insert(t, Transfer.legs.add(...), ...)`. A loaded row is deleted with `.delete()`, a root with its owned relations. The rows of an owned relation are written only through the root; every other row is written directly, and a relation that is not owned has no write operations. Set changes take the same field operations (`Order.where(...).set(...)`).
- Rationale: thanks to the `Col[T]` descriptor, names and types are checked through `Column[Owner, T].to(v: T)` without codegen, and snapshots remain immutable at the type level too. Inserting and deleting are operations of their own, as creating and modifying are (ADR-0003): a new entity has no row to `.set`, and a delete has no field to pass. Writing owned rows only through the root keeps the root's `version` bump on every change of the aggregate; writing other rows directly removes the second way to insert them (`add` on any relation of a loaded parent, spike 0002 X3) and the second way to write a child (X11).
- Runtime rules where the types cannot reach (a new entity, a loaded snapshot and a ref have one type): `.set` on a new entity and a created entity never inserted are `UsageError`s; *(Proposed)* so are `.delete()` on a new entity, `insert` of a loaded snapshot and a direct write of an owned child, each at its call (ADR-0010's table); an `identity`-key root that declares `owns_many` is a `SealError` in Phase 1a.
- Alternatives considered and rejected:
  - Keyword style `.set(status=PAID)`: the type checker cannot catch typos in field names.
  - Assignment via `with order.edit() as o:` (returning Self): to allow assignment, collection field types must be `list`, so even `order.items.append()` on a snapshot passes type checking.
  - Immer-style `draft()`: there would be two ways to write, and type-level immutability breaks for the same reason as above.
  - `.set` on a new entity for its owned children (`insert(t) + t.set(Transfer.legs.add(...))`, #60 candidate A): needs a second runtime rule (`.set` on a new entity takes relation operations only); candidate B makes `insert` reject column and non-`add` operations by type (spike 0007).
  - The bulk `insert_all` for one root (spike 0002 use case 8): COPY runs outside the pipeline, so it cannot share the commit batch (§4.8).
- History: until ADR-0010 the write syntax was "a single `.set(Column operation)`", with `add` allowed on any relation and no insert of a root or delete of a root outside the bulk path.
- Cost: longer than assignment syntax, three verbs instead of one, and a list that collects column and relation operations for one `.set` is `list[Op[O] | RelOp[O]]` (*Proposed:* the alias `Write[O]`). We chose "only one way" per operation and type safety over familiarity.

**Aggregate boundaries: `aggregate_root` and `owns_many`**
- Decision: aggregate boundaries are declared with `class Order(Entity, table="orders", aggregate_root=True)` and `items: Owned[list[Item]] = owns_many(...)` (no `owned=` flag; decided on #60). One declaration is used in five places: ① changes to owned children bump the root `version`, ② sequence numbers of `@event(aggregate=...)`, ③ module boundary checks, ④ which write operations exist (owned rows only through the root), ⑤ what `.delete()` of the root deletes. The child side of an owned relation declares its key with `parent_fk` (§4.2).
- Proposed in [ADR-0010](../adr/0010-writes-beyond-set.md): ownership is one level deep (an owned child declares no `owns_many`, so a child update takes column operations only and a delete cascades one level); seal checks the declarations against each other - an `owns_many` over a plain `fk`, a `parent_fk` that no `owns_many` names, that two name or that targets another class, `owns_many` on a class without `aggregate_root=True`, and a class with a `parent_fk` that is an aggregate root, owns children or has a second `parent_fk` are `SealError`s; a `many_to_one` over a `parent_fk` (the child reading its root) is allowed (final names: #9).
- Rationale: when an edit screen handles an order and its items together, a change to only the items must still be caught by the optimistic lock across requests (JPA `OPTIMISTIC_FORCE_INCREMENT`). But applying this to every FK child would mean that merely adding a comment to a post updates the post row, which quickly becomes a hot row under the SERIALIZABLE default. So it is limited to children that belong to the aggregate.

**Partial loads of large aggregates**
- Decision: provide partial loads such as `Load(Order.items.count())`, `.exists()`, `.where(...)`. Writes do not require loading the whole collection: `add` needs no loaded child, `update` / `remove` need the child they name, and a root's `.delete()` removes its owned relations unloaded ([ADR-0010](../adr/0010-writes-beyond-set.md)); iteration and lookup require loading.

**Marking Python-only invariants**
- Decision: protected fields are stated with `@invariant(fields=lambda: (Order.status, ...))` (references instead of strings). If a set-based update touches such a field, it is an error at seal time. Rules expressible in SQL are declared with `Check(...)` and pushed down to a DB `CHECK` constraint; set updates are allowed on such fields.
- Escape hatch: `.set(..., unsafe_bypass="reason")`. The reason is kept in the ChangeSet and the audit log.

**Module boundary declaration**
- Decision: `Module("billing", exposes=[...])` in the package's `__init__.py`. An entity belongs to the module of the package where it is defined. Module boundaries of load declarations are verified at seal; the import level is verified by import-linter independence contracts generated by `platina contracts`.
- Rationale: import-linter already does import graph analysis well. There is no reason to build it ourselves.

### 8.3 Consistency and transactions

**Default isolation level: SERIALIZABLE for Commands**
- Decision: use cases run under SERIALIZABLE by default and are retried automatically on serialization failure. The Query path is READ COMMITTED.
- Rationale: PostgreSQL states that applications using SERIALIZABLE must be ready to retry serialization failures (SQLSTATE 40001), and also states that the DB does not provide automatic retry because it cannot guarantee correctness. In most ORMs this retry is dangerous (side effects inside the transaction are repeated), but Platina's use cases are pure functions, so rerunning everything is safe.
- Effect: no separate feature such as "read-set version validation" is needed. SSI prevents write skew.
- Escape hatch: `@usecase(isolation=REPEATABLE_READ)` + `version` escapes SSI's read/write-dependency failures (write skew). There is no escape hatch from the same-row 40001 ("concurrent update") on a row that concurrent commands update: neither REPEATABLE READ nor a `lock="for_update"` profile avoids it; the profile only makes the conflict surface at the load stage ([ADR-0005](../adr/0005-hot-rows-under-serializable.md), from spike 0002; spike 0003 measured that the profile does not reduce the failures; whether `lock=` stays is decided in #64). **READ COMMITTED is not allowed for Commands.** Each statement of the load plan would have a different snapshot, breaking the premise that "the loaded snapshots show a single point in time". REPEATABLE READ does not prevent write skew, so if there are rules based on the read set, the use case must stay on SERIALIZABLE.

**Retry policy**
- Decision: 40001 and 40P01 are always retried. 23505 only for use cases that explicitly set `on_unique=True` (23505 on the run ID tables is handled separately as the idempotent path). At most 4 attempts, exponential backoff + full jitter (base 10ms, cap 200ms), each retry starting again from the load.
- Rationale: the PostgreSQL documentation advises that serialization failures can always be retried, but other codes such as unique violations may be permanent errors and need more care.
- 57014 (`statement_timeout`) is not retried: `timeout=` is the caller's limit for the whole run, so a retry after it expired would spend more than the caller allowed. The deadline and a 57014 before `COMMIT` both raise `RunTimeout` ([ADR-0008](../adr/0008-run-timeout-budget.md); #61). No `lock_timeout` option and no retry of 55P03 for now (revisit with #64); a user who sets `lock_timeout` gets `DatabaseError(55P03)`.
- This retry loop and the job runner's domain exception retry (`retry_later`, §8.4) are separate.

**Commit order within a single use case**
- Decision: ① set-based changes (in declaration order) → ② row-level changes in the order of a **topological sort of the FK and unique key dependency graph** → ③ inline projections → ④ outbox → ⑤ run result record. Statements with the same table, operation and column set are batched together (§10.7).
- Rationale: Hibernate's ActionQueue executes SQL in a fixed order, which applies batching automatically, but the fixed order has a trap: when emptying a collection and inserting new rows, the INSERT runs before the DELETE and causes a unique violation. So a change that frees a unique key value runs before a change that takes that value.
- Cycles (e.g. two rows swapping unique values) are reported as an error, pointing to `DEFERRABLE INITIALLY DEFERRED` constraints.
- A root's `.delete()` (one statement deleting its owned relations by the root key and the root) is set-level SQL but is planned in ②, as a node of the row-level graph: it must follow every change that removes a reference into the aggregate's tables, which ① would run too early ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed; edges in §10.7).
- Overlap handling: set updates bump `version`, so if one overlaps with an entity update of the same row, it is reported as `IntraUsecaseConflict` (a programming error), which is not retried. The delete of an aggregate is not a set change in this sense: an operation on an owned child of a root the same use case deletes is dropped from the plan when it comes from an earlier chain step, and is `ConflictingWrites` or a `UsageError` within one step ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed).

**Composition: steps only via `chain`**
- Decision: there is one way to connect steps: `with chain(order, wallet) as (c, order, wallet):`. The returned values are views pointing to the latest state of the chain, rebound to the same names to hide the originals. `+` is used only within a single step; step call results (`StepResult`) have no `+`, so `+` between steps is a type error. Aliases created before the chain are blocked by move marks (`MovedSnapshotAccess`). Views that have left the block allow only reads; `.set` and `.delete()` are `ChainClosed`.
- History:
  1. Merge with `+` and connect manually with `order.apply(changes)`: forget it and you silently read the previous value. Rejected.
  2. Automatic connection as an option: the same code would mean different things depending on configuration. Rejected.
  3. `+` (conflict detection by read tracking) + `chain`: when a value is passed as an argument, as in `charge(wallet, order.total)`, the read happens in the outer scope and is not tracked. Detection cannot block it completely. Rejected.
  4. `chain(order=order)` keyword + `c.order`: turning keyword names into attributes cannot be expressed in types, so `c.order` becomes `Any`. Rejected.
  5. **Current proposal**: positional arguments typed with TypeVarTuple, and rebinding the same names structurally hides references to the originals. The remaining alias mistakes are caught precisely by move marks.
- Why writes outside the block are blocked: such a change does not go into `c.changes` and silently disappears. Reads are harmless, so they are allowed.

**2 round trips**
- Decision: 1 load batch (BEGIN, run ID claim, load stage 1) + 1 commit batch (writes, projections, outbox, result record, xid query, COMMIT, LSN query). Load stages increase only when there is a `Load.after`. `insert(...)` and `.delete()` are row changes of the commit batch; only the bulk `insert_all` (COPY) runs outside it (§4.8).
- Rationale: a libpq pipeline does not execute later statements if an earlier one fails, so putting COMMIT in the same batch is safe. The wider window of unknown outcome is covered by the run ID. The shield covers the whole commit batch.

**Run ID: idempotency and commit-outcome resolution unified**
- Decision: every `app.run` gets a run ID (the caller's idempotency key, or an automatic uuid7 if none). The first statement **INSERTs into `run_claim` without a lookup**, and for a caller key the commit batch INSERTs the result into `run_result`. If the outcome is unknown, rerun with the same run ID: if it committed, 23505 → the stored result (caller key) or the result in the runner's memory (automatic ID); if it is in progress, wait on the unique key; if it was rolled back or lost, it runs as is.
- History:
  1. Obtain the xid before commit, and on disconnect resolve with `pg_xact_status(xid)`: on failover, an xid that was not replicated can be reused by another transaction on the new primary, risking reading someone else's commit as our own success. The workaround of also checking the timeline ID was unclear to mean the same thing on managed services (Aurora, etc.).
  2. **Current proposal**: idempotency and commit resolution are handled by a single run ID. It reuses the already designed "concurrent requests with the same key" path, so there is no new mechanism, and xid resolution and failover concerns disappear.
- Why INSERT without a lookup: ① if the second request of a double click ran the business logic first, it would see an order that is already PAID and raise `AlreadyPaid`. The duplicate check must come before the business logic. ② "Look up, and INSERT if absent" runs into the internal table rule below.
- Why the result is INSERTed into a separate table instead of UPDATEing `run_claim`: an UPDATE reads the index to find the row and recreates the same false conflict (observed in [spike 0003](../spikes/0003-ssi-internal-tables.md), though far less often than look-up-then-INSERT).
- Fingerprint (#58): for a caller key, `run_result` also stores a fingerprint of the call (the use case's registry name and a canonical serialization of the bound arguments; not the code version) and the 23505 replay path compares it: the same key with other arguments raises `IdempotencyKeyReuse` instead of returning another request's result. It is never read inside the claiming transaction - spike 0003 measured that reading `run_claim` there fails 72-78 % of attempts and turns the waiting duplicate's 23505 into a 40001. A duplicate that arrives while the first run is in progress waits on the claim as before and is compared after it.
- Cost: one INSERT row per command (two with a caller key) and periodic cleanup. The `returning` value and the bound arguments of a caller-key run must be serializable (an argument that is not is a `UsageError` from `app.run`). The LSN of a token obtained through replay is queried fresh.

**Internal append-only table rule**
- Decision: internal tables such as `run_claim`, `run_result`, the outbox log, the job tables and consumer checkpoints are **not read inside SERIALIZABLE transactions.** The only thing a SERIALIZABLE transaction does with these tables is INSERT; reads happen in a separate READ COMMITTED transaction. Updates happen only outside SERIALIZABLE: consumer checkpoints (REPEATABLE READ) and job leases (short READ COMMITTED transactions). `run_claim`, `run_result` and the outbox log are never updated. The internal schema's version table is updated only by the command that applies the schema, never by a run ([ADR-0009](../adr/0009-internal-tables-owned-by-the-core.md)).
- Rationale: PostgreSQL's SERIALIZABLE takes read locks per B-tree leaf page. With ever-increasing keys like uuid7 or sequences, every INSERT lands on the rightmost leaf page. Transactions that read that page form cycles in which each invalidates the others' reads, and SSI breaks them with serialization failures. As a result, unrelated commands fail and are retried (72-78 % of attempts when the claim table is read, spike 0003). A read that the planner turns into a sequential scan (a small or empty, analyzed table) takes a relation-level lock instead, which conflicts with every write to the table ([spike 0003](../spikes/0003-ssi-internal-tables.md)).
- Application: the run result record (INSERT instead of UPDATE), job completion record and fencing (`run_claim` INSERT with the job ID as the run ID), and consumer log reads (separate transaction) all follow from this rule.
- Confirmed ([spike 0003](../spikes/0003-ssi-internal-tables.md), independently reproduced): the unique check of an INSERT takes no such read lock - also for a key that was inserted and rolled back before, or that a concurrent claimant holds - and INSERT-only claims caused no serialization failure under load, while reading the table inside the transaction failed 72-78 % of attempts. The fencing outcome (wait, then 23505 or proceed) also depends on the table not being read: when two claimants both read the ID first, the waiting one gets 40001 instead of 23505.

**The roles of version**
- Decision: the `version` column is used for the following four things.
  1. Optimistic locking across requests: `Order.ref(id, expected_version=v)` → `VersionMismatch`. There is no transaction spanning the two requests, so it prevents the lost update that the DB cannot detect.
  2. Event ordering: the sequence number of events within the same aggregate.
  3. Overlap detection within a use case: when a set change and a row change touch the same row.
  4. Coexistence with other ORMs: bumped by a DB trigger so that writes by the other ORM are also subject to optimistic locking.
- Correction: the earlier `StaleSnapshot` ("version mismatch in REPEATABLE READ mode") was dead code. Under REPEATABLE READ, modifying a row that was updated concurrently makes PostgreSQL raise 40001 first. Its place is taken by `VersionMismatch` of the cross-request lock.

**Identity of a run: each question has its own answer**

| Question | Basis | Where used |
|---|---|---|
| Did it commit? | Run ID | Idempotency, rerun after connection loss during COMMIT or failover |
| How far has the consumer got? | xid | outbox watermark, read-your-writes for async projection queries |
| Has it been replicated? | WAL LSN | Replica routing (replay LSN is monotonically increasing, so the app caches and compares it) |
| What came first? | version | Event ordering within the same aggregate |

- The consistency token is the pair (xid, LSN). The xid is queried inside the commit batch. When the result was obtained through replay, the LSN is queried fresh, and if the xid was lost in an automatic-ID replay, `pg_current_xact_id()` at that moment is used as a conservative upper bound.

### 8.4 CQRS and events

**Projections: inline by default, target and key declared, body is field operations only**
- Decision: `@projection(on=E, into=Target, key=E.field)`. The body only returns field operations on that target row. For inline, the key may only be an entity ID field of the event; derived keys such as dates or constants are rejected at seal (run async or `allow_hot_key="reason"`).
- Rationale: the primary target is small teams that start without a broker, so strong consistency is the default. But combined with the SERIALIZABLE default, every payment converges on global aggregate rows such as daily revenue. If only the key were declared and the body could upsert with any key, this rule could be bypassed, so the target and the key were moved into the declaration.
- This rule filters only the obvious cases. Entity IDs can also be hot, such as `store_id` or the ID of a popular product, so a per-projection retry rate metric is always present.

**Aggregates and ordering of events**
- Decision: `@event(aggregate=lambda: E.order_id)` declares only which aggregate an event belongs to, and the engine fills in the sequence numbers (aggregate version, position within the transaction) at commit. For `emit_each` on set changes, they are filled from the result of `UPDATE … RETURNING id, version`.
- Rationale: the earlier proposal of writing `order_version=order.version + 1` by hand on the event was a place to make mistakes. When two steps in a chain each emit an event, the numbers diverge (there is only one UPDATE, so the DB does +1), and emitting an event without modifying the aggregate row sends out a wrong number.
- When only an event is emitted without modifying the aggregate row, **bumping the version is the default**. To guarantee ordering, that aggregate row must become the serialization point. In this case the aggregate must be an entity of the event's own module (rows of other modules cannot be written). Notification-style events that do not need ordering, or events that use an ID from another module as the aggregate, are declared with `ordered=False`.

**Consistency token API**
- Decision: `result.token` is the (xid, LSN) pair as an opaque string. The LSN is obtained with `pg_current_wal_insert_lsn()` right after commit. `query(..., after=token)` uses the replica if its replay LSN is greater than or equal to the token LSN, otherwise the primary. async projection queries decide by whether the consumer watermark has passed the token xid. By default there is no waiting and it falls back to the primary; waiting is possible with the `wait_ms` option.
- The WAL position used is the **insert position**, not the write position (`pg_current_wal_lsn()`). With `synchronous_commit=off`, the write position can lag behind the commit record.

**outbox log and consumer checkpoints**
- Decision: the outbox is an **append-only event log**, and processing state lives on the consumer side. Each row records an xid and a sequence, and consumers read only rows with `xid < pg_snapshot_xmin(pg_current_snapshot())`, i.e. only events of transactions that have definitely finished. Log reads happen in a separate READ COMMITTED transaction (internal table rule).
- `(xid, seq)` is only the processing order, not the semantic order. If order within the same aggregate matters, use the events' sequence numbers.
- Correction: the earlier proposal claimed to be "INSERT only" yet UPDATEd lease columns, and the sequence watermark skipped lower numbers that committed late. The xid watermark does not move past a transaction until that in-progress transaction finishes.
- Trade-off: a single long-open write transaction holding back xmin delays every consumer by that much. This delay is exposed as a metric.
- Because the log is truly append-only, it can follow the column conventions of the Debezium Outbox Event Router, and switch to CDC when throughput grows. The general recommendation is to introduce CDC when polling latency or DB load has become a measured problem.

**async projection consumer**
- Decision: one serial consumer per projection. The effect and the checkpoint are committed together in a **REPEATABLE READ** transaction, applied exactly once. A poison message is not skipped; the consumer stops and alerts.
- Rationale: projection effects are commutative field operations such as `.add`, and there is one consumer per checkpoint, so SERIALIZABLE is not needed. Running under SERIALIZABLE would cause false conflicts between consumers on the checkpoint table. Skipping would corrupt the read model.

**Job processing: the two-tier pipeline for then and @process**
- Decision:
  - **Log reader**: reads without gaps using the xid watermark, INSERTs into the per-handler job tables, and writes the reader checkpoint in the same transaction.
  - **Worker**: takes a lease with `SKIP LOCKED` in a short READ COMMITTED transaction, and does external IO outside the transaction.
  - **Dispatcher**: runs the use case returned by the handler with the job ID as the run ID. The first statement, the `run_claim` INSERT, is both the completion record and the fencing. If a lease expires and two workers finish the same job, the later one gets 23505 and does nothing. If the handler returns `None`, only `run_claim` is committed.
  - **Ordering**: for each aggregate key, only the earliest job can be in progress.
  - **Failures**: transient errors are retried with backoff. Domain exceptions go to dead-letter immediately by default, and are retried later only when the exception type declares `retry_later=RetryLater(max_attempts, within)` (beyond the limit: dead-letter). When the head job goes to dead-letter, later jobs with that key are blocked too. A "blocked keys" metric and resend/skip tooling that leaves an audit record are provided.
  - **@process returns a description.** It does not call `app.run`. External calls use the `ctx.idempotency_key` provided by the framework. For external APIs that do not accept an idempotency key, write the handler to query the state first, then decide.
- History:
  1. One worker per consumer + ordered checkpoints applied to every consumer: slow external IO capped throughput at the number of partitions, and a single poison message blocked everything behind it.
  2. Handlers call `app.run`, with the idempotency key built from (event, handler, use case): if, after the approval use case committed on the first delivery, the external API returned an "already approved" error on redelivery, a cancellation use case with a different key would run. That was a hole. The workaround of putting a call sequence number into the key broke with deployments or branch changes.
  3. **Current proposal**: the handler returns a description, and the dispatcher commits it in one transaction with the completion record. After commit there is no redelivery, so no DB-side key design is needed. The remaining window (failure after external IO, before commit) is covered by the external idempotency key.
- Rationale: if a lease is held while waiting for external IO, the transaction stays open holding an xid and the entire log reader stalls. If the completion record were written as an UPDATE `WHERE lease_token = $n`, the job table would be read inside the SERIALIZABLE use case transaction, violating the internal table rule. So fencing is done with a unique INSERT. At first there was a separate `job_done` table, but when the dispatcher uses the job ID as the run ID, there would be two unique INSERTs doing the same job as `run_claim`, so they were merged into one.
- `then` use cases run under SERIALIZABLE with use case semantics unchanged.

**Batch checkpoint storage**
- Decision: a batch-checkpoint table in the same DB, in the internal schema ([ADR-0009](../adr/0009-internal-tables-owned-by-the-core.md)). The cursor is updated in the same transaction as each chunk commit, so on restart processing resumes exactly from the next chunk.

### 8.5 Tooling and ecosystem

**Schema source for codegen**
- Decision: for entity tables, the Python entity definitions are the source of truth. TypedSQL type inference is performed with prepared statement describe against a temporary PostgreSQL with migrations applied. **Generated code is committed to the repository**, and CI only checks that it is up to date with `platina gen --check`.
- Rationale: Prisma TypedSQL needs a connection to a running DB when generating types, and requests that this constraint is inconvenient in stateless CI come up repeatedly. sqlc also added DB-based analysis because static analysis alone has limits in inferring types of complex queries.

**Schema tooling: SQLAlchemy Core + Alembic hybrid (optional extra)**
- Decision: the query compiler and the execution engine stay independent, and **DDL generation, catalog reflection and migrations are handed to SQLAlchemy Core and Alembic.** The entity registry is converted to SQLAlchemy `MetaData` to use Alembic autogenerate. This is needed only for `platina migrate`, `pull` and drift checks, so it lives in the optional extra `platina[migrate]`, and the runtime core does not depend on SQLAlchemy.
- History: at first we decided to implement our own migration tool, reasoning that "Alembic is tied to SQLAlchemy metadata and does not fit a standalone ORM". But the rationale for not using Core (§8.1) was wrong, and it became clear that the work Core actually saves is not query compilation but DDL, reflection and migrations, so the decision was reversed. When MySQL is added, we also get this work for free.
- Risk: fidelity of the conversion. The weak spots of Alembic autogenerate overlap with features of this design. ① `renamed_from` hints (autogenerate does not detect renames → plan to turn drop+add into a rename with the `process_revision_directives` hook), ② `Check` declared with lambdas, ③ `version` triggers (Alembic does not handle triggers → evaluate third-party PG object support), ④ expression and partial indexes, ⑤ framework internal tables (especially partitions). Whether these five round-trip is a spike item (§9). Result ([spike 0004](../spikes/0004-alembic-round-trip.md), §9.3): columns, tables, foreign keys, composite unique keys and expression indexes round-trip. ① works for columns only with a rewrite that also builds the downgrade (Alembic's reverse of a rename loses it) and orders renames first; a table rename leaves names derived from the table behind, and any rename leaves PostgreSQL 18's NOT NULL constraint names behind. ② and ④: a CHECK or partial-index change is detected only when its name changes with the expression (for a CHECK also only with Alembic's opt-in `checkconstraint_byname` plugin); expression indexes give no false diffs. ③ works with Alembic's own extension points (custom operations and a comparator plugin), without a third-party package; drift is detected by trigger name and function body only. ⑤ does not round-trip: partitions created outside migrations (partitioning was assumed for the experiment, not decided) are proposed for drop and the downgrade cannot re-create them; the partition scheme and `xid8` columns are not compared. The same reflection gaps (`xid8`, CHECK bodies, partial-index predicates, NOT NULL names) also limit `platina pull` and the drift comparison, not only `migrate`. Of the choices this leaves, the naming rule is open for #25, and renames of indexed columns with the other fidelity gaps for #70 (Phase 2, §9.6).
- **Internal tables are the exception** ([ADR-0009](../adr/0009-internal-tables-owned-by-the-core.md); direction decided in #63, which stays open for the details): the core ships their DDL as versioned SQL in a dedicated schema, which Alembic autogenerate does not compare with its defaults (it compares only the connection's default schema) - unless that schema *is* the connection's default schema, through `search_path` or a role of the same name (`"$user"`), and then it is compared and proposed for drop; Platina's Alembic integration therefore refuses to autogenerate in that case, with an error that says how to fix it, and `platina check` reports it too. Nothing runs DDL at startup: a `platina` command applies it, and `platina[migrate]` users call it as an Alembic operation from their own history. There is no separate startup check: a `42P01` / `42703` / `42501` from any internal-table statement (the claim INSERT is the first) becomes a `DatabaseError` whose hint names the command or the grant, and `platina check` compares the versions. Partitioning and the key shapes wait for #72; no internal-table DDL ships before it, and until then integration tests (#22) run against test-only DDL in `tests/support`. The downgrade is forward-only.
- Rationale (for reference): Atlas has an Apache 2.0 core but is open core, and in October 2025 with v0.38 it moved migration linting to a paid tier. sqldef manages the schema with a single SQL file, but it is a Go binary, which breaks the experience of finishing with a single `pip install`.

**Pydantic integration**
- Decision: the core does not depend on Pydantic. Entities and DTOs are our own immutable classes (slots) and frozen dataclasses. The `platina-pydantic` plugin generates Pydantic models for API responses from projection and TypedSQL results.

**Django adapter: not built**
- Decision: no adapter that compiles load plans into Django QuerySets is built. Coexistence is solved with `platina pull` (DB catalog → entities) + `version` triggers, with no distinction between Django and SQLAlchemy.

### 8.6 Async and runtime

**Minimum Python: 3.14**
- Rationale: psycopg 3.3 supports writing safe queries using Python 3.14's t-strings. From 3.14, deferred evaluation of annotations is the default. The free-threaded build dropped its "experimental" label in 3.14 with the acceptance of PEP 779. Since 3.15 was released on October 9, 2026, it is reasonable for a new library coming out in 2027 to require 3.14+.

**Driver: psycopg 3.3+ only**
- Rationale: it provides both sync and async interfaces (required to keep the sync runner first-class) and supports pipeline mode, COPY and t-strings. asyncpg is fast but async-only, so a sync runner cannot be built on it.

**MySQL: support planned, timing undecided**
- Decision: we plan to add a MySQL (and MariaDB) dialect on top of the compiler's dialect layer. The timing will be decided after the PostgreSQL implementation stabilizes.
- Practical constraints: MySQL still does not support `RETURNING`, and the feature request bug is open against 8.x and 9.x. It also has no data-modifying CTEs. MariaDB, on the other hand, has supported `INSERT … RETURNING` since 10.5 and added `UPDATE … RETURNING` in 13.0 GA.
- So MySQL is supported in a **reduced-feature mode**.

| Feature | PostgreSQL | Replacement in MySQL |
|---|---|---|
| Set change + outbox in one statement | Data-modifying CTE | Obtain target IDs with `SELECT … FOR UPDATE` → `UPDATE` → outbox `INSERT` (3 round trips) |
| Identifying conflicting rows in chunked updates | `UPDATE … RETURNING` | Preceding `SELECT … FOR UPDATE`, then compare |
| Sending the load plan at once | libpq pipeline | Sequential execution (or multi-statement, depending on the driver) |
| Consistency token | WAL LSN | GTID |
| SERIALIZABLE by default | SSI (optimistic, 40001 retry) | InnoDB is lock-based and behaves differently → MySQL default decided separately |
| Recursive loads | `WITH RECURSIVE … CYCLE` | `WITH RECURSIVE` (8.0+), cycle detection done manually with a path column |

- Not yet decided: the MySQL driver (both sync and async are needed), the default isolation level on MySQL, and whether MariaDB is grouped into the same dialect as MySQL or kept separate.

**trio: not supported; own wire protocol: not done**
- Rationale: the official psycopg documentation covers the asyncio interface and gevent support. A PR for anyio support was once proposed, but the maintainer has stated that Trio support work will not be done without sponsorship. The trio-specific drivers are roughly triopg (unmaintained notice) and pgtrio, a pure Python implementation, which are hard to build on.
- Why we still write against the anyio API: for the cancellation semantics of cancel scopes and shields. The backend is fixed to asyncio.

**free-threaded Python**
- Decision: the core (sans-IO, immutable snapshots) includes 3.14t as a CI target. Official support for the sync runner + threads combination is deferred until psycopg-binary ships free-threaded wheels.
- Rationale: as checked on PyPI on 2026-11-24, psycopg-binary 3.3.9 has only cp310 to cp315 wheels and no free-threaded (`cp3xxt`) wheels. asyncpg 0.32.0 provides cp314t wheels.

---

## 9. Experiment plan (to confirm before the prototype)

Over five rounds of review, the comments moved steadily down into implementation details. The remaining questions cannot be answered by documents; only experiments can answer them. In particular, with SSI interactions, both reviewers and the designer repeated the same kind of mistake on paper. So the following four experiments come before implementation.

### 9.1 Type stub spike (top priority)
The whole syntax of §4 depends on this. Without an implementation, run the pass and fail files of §11.8 through pyright and mypy with stubs alone. Result: [spike 0001](../spikes/0001-type-surface.md) (independently reproduced in three rounds; the probes added after round 3 are recorded as not reproduced), ADR-0003, ADR-0004. Follow-up: [spike 0006](../spikes/0006-parent-fk-and-column-operands.md) (independently reproduced) confirms the parent-set key of owned children (#49) and the comparison operands (#51).
- [x] `Col[T]`: class access `Column[T]`, instance access `T` - holds; class access is now `Column[Owner, T]` (ADR-0004)
- [x] Constructor: does `__set__(self, instance: Never, value: T)` give constructor parameter types while blocking assignment? If not, typed creation functions in a generated module - holds at step 1, on an `Entity` base class; creation is `Order(...)` (ADR-0003)
- [x] `with chain(a, b) as (c, a, b)`: does TypeVarTuple preserve the type of each name? - holds
- [x] `bind`: name and type checking with ParamSpec, omission of `INJECTED` defaults - holds (the seal rule for `INJECTED` defaults is decided in #48, §4.5)
- [x] Embedded paths (`Order.total.amount`) and value object operations (`Wallet.balance.add(Decimal)`) - not as written; `Order.total.path(Money.amount)` with owner-typed columns holds, increments go through the path (ADR-0004)
- [x] Is `+` between `StepResult`s an error; Finder argument types - holds

### 9.2 SSI concurrency experiment
Measure the rate of false conflicts (serialization failures) under concurrent execution on real PostgreSQL. Result: [spike 0003](../spikes/0003-ssi-internal-tables.md) (independently reproduced in three rounds); ever-increasing entity keys: [ADR-0007](../adr/0007-ever-increasing-entity-keys.md) (Proposed).
- [x] Does the run ID `run_claim` INSERT (uuid7) alone produce no false conflicts? (assumption: the unique check of an INSERT does not create read locks) - holds: no read lock on the internal tables (also for a reused or contended key), no serialization failure under load
- [x] Control group: do conflicts actually occur with the "look up then INSERT" and "INSERT then UPDATE" approaches? (confirming the rationale of the rule) - partly: look-up-then-INSERT fails on 72-78 % of attempts; INSERT-then-UPDATE conflicts by the same mechanism but on about 0.1 % of attempts or less
- [x] `run_claim` fencing with the job ID as the run ID (waiting and 23505 behavior on concurrent completion), retry rate of inline projections - holds: the second claim waits, gets 23505 after a commit and proceeds after a rollback (while `run_claim` is not read); disjoint projection keys add no retries, a popular key does (about 27 % of attempts under Zipf, 80 % for one key)
- [x] Behavior in the early state when tables are small (table-level locks) - partly: relation-level locks come from sequential-scan plans (small or empty analyzed tables), not from size; the internal tables are not affected
- [x] Throughput and retry rate of the SERIALIZABLE default on representative workloads (compared with REPEATABLE READ + version) - holds: uniform access within about 10 % of REPEATABLE READ's throughput and at most 1.007 attempts per commit; under skew the retries are mostly same-row conflicts both levels share; REPEATABLE READ broke a write-skew invariant
- [x] One hot row ([ADR-0005](../adr/0005-hot-rows-under-serializable.md)): retry rate, `RetryExhausted` rate and `57014` rate with and without `lock="for_update"`, on the durable profile - measured: about 31-41 / 75-78 / 90 % of attempts fail at 8 / 32 / 64 workers and 7-10 / 35-41 / 64-69 % of commands end in `RetryExhausted`, the same with and without `lock="for_update"`; no `57014` at a 2 s timeout. The comparison of ADR-0005's candidates for genuinely hot rows is not part of 9.2: it is #64, which uses this measurement as its baseline

### 9.3 MetaData → Alembic round trip
Convert the entity registry to SQLAlchemy `MetaData` and see whether Alembic autogenerate round-trips the following without loss. Result: [spike 0004](../spikes/0004-alembic-round-trip.md) (independently reproduced by pg-researcher) - partly; no decision is changed by it, and the choices it leaves are open for #25 and #70 (§8.5, §9.6).
- [x] `renamed_from` hints (drop+add → rename conversion via `process_revision_directives`) - partly: column renames round-trip once the rewrite builds its own downgrade and puts renames first; a table rename leaves the names derived from the table behind (primary key, convention-named unique constraints, PostgreSQL 18 NOT NULL constraints)
- [x] `Check` declared with lambdas - partly: created with the table; a change on an existing table is detected only with Alembic's opt-in `checkconstraint_byname` and names that change with the expression
- [x] `version` triggers - holds with Alembic's own extension points; Alembic alone sees no trigger or function; `alembic_utils` was read, not needed
- [x] Expression and partial indexes - partly: no false diffs and expression changes are detected; a `WHERE`-only change under the same name is not
- [x] Framework internal tables (especially partitions) - does not hold: partitions created outside migrations are proposed for drop and the downgrade cannot re-create them; the partition scheme and `xid8` are not compared

### 9.4 Port 10 real use cases to this syntax
Each was chosen to test a different part of the design. If something does not translate onto paper, fix the syntax. Result: [spike 0002](../spikes/0002-use-cases-on-paper.md) - partly; no syntax is changed by it. Three use cases need a decision (delete of a root, reuse of an idempotency key with other arguments), the others carry workarounds (set loads, loads on `Load.after` results, nested load paths, the `bind` rule for dependent loads, `insert_all` in the commit batch), and the hot-row escape hatch does not hold on PostgreSQL (ADR-0005, accepted). Verdicts are the spike's, reviewed by the architect sub-agent (agreed after two rounds); its type checks were reproduced by type-reviewer and its database observations by pg-researcher, which changed no verdict (one type finding was corrected, and the database facts gained conditions; see the write-up's Reproduction).

| # | Use case | What it tests | Result (spike 0002) |
|---|---|---|---|
| 1 | Payment | Idempotency key, run ID | Not expressible: a key reused with other arguments gets the stored result |
| 2 | Refund | Dependent loads (`Load.when`/`after`) | Expressed, awkward: `Load.when` with a column-to-column `match` is a type error (#51; allowed since spike 0006); dependent-load parameters must be passed to `bind` unless given a default |
| 3 | Payment after applying a coupon | `chain` | Expressed, awkward: `chain` as written; "used by this customer?" over-reads a relation |
| 4 | Stock reservation | Hot rows, pessimistic lock profile | Expressed, awkward: the stock rows cannot be declared (the caller pre-reads); `lock="for_update"` still ends in 40001 (ADR-0005) |
| 5 | Seat reservation | write skew, SERIALIZABLE | Expressed, awkward: SERIALIZABLE covers the write skew; availability reads over-read whole relations |
| 6 | Order merge | Two parameters of the same type, `Load.after` | Not expressible: no delete for a root row |
| 7 | Bulk expiry of unpaid orders | Set change, `emit_each` sequence numbers | Expressed, awkward as one use case per order; a set change does not express it |
| 8 | Account transfer | Ledger, commutative increments | Not expressible: key reuse as in 1; increments into one row still conflict (ADR-0005) |
| 9 | Profile edit | `expected_version`, `owned` children | Expressed |
| 10 | Payment approval notification | `@process`, job pipeline, external idempotency key | Expressed, awkward: the notice is a second `@process`, not `then`; the transient-error rule is unstated |

### 9.5 Other measurements
- [ ] Pipeline effect: latency of sending load stages in one round trip compared with sequential execution (local / cross-region)
- [ ] Overhead of immutable snapshots + `.set` operations, move marks and read tracking
- [ ] How often `Load.after` is actually needed and by how many stages it increases round trips
- [ ] Whether the verbosity of `.set(Column.to(...))` is acceptable in real use
- [ ] Write amplification and cleanup cost of the run ID and job tables (split by #6: run-ID tables #72, outbox log #73, job tables #32)
- [ ] Seal time (at the scale of hundreds of use cases)
- [ ] Entity key generators ([ADR-0007](../adr/0007-ever-increasing-entity-keys.md), before it is decided; #65): uuid4 vs uuid7 insert rate and WAL bytes per insert with the primary-key index at about 1x and 10x `shared_buffers`; the false-conflict window of an ever-increasing key (spike 0003 C3 with the row read aged by N inserts); the 40001 and `RetryExhausted` rates of a "create a parent and its children" load with a real foreign key (spike 0003 A7 under concurrency), uuid7 vs uuid4

### 9.6 First-phase scope (decided, #6)
Started as a proposal reflecting the comment that the scope is too broad; decided by the maintainer on 2026-11-26 in #6, from the verdicts of §9.1-9.4 and the recommendations on the decision issues they produced. Phase 1 is cut in two at the first working `app.run`. Where a part depends on a decision issue that is still open, it follows the decision of that issue.
- **Phase 1a - Core execution path**: pure use cases and the execution engine, PostgreSQL dialect, run ID (#9-#22), then the release pipeline and a working 0.0.1 (#44, #30).
  - Exit: use cases 6 (order merge, delete of a root), 8 (transfer, insert of a new root) and 9 (profile edit) of [spike 0002](../spikes/0002-use-cases-on-paper.md) pass as integration tests on PostgreSQL in one load batch and one commit batch, SERIALIZABLE with retry and a run ID.
  - Before the build issues they gate: the type spike for #49 and #51 (done: [spike 0006](../spikes/0006-parent-fk-and-column-operands.md)); the decisions #48, #54, #57, #58, #59, #60, #61 and #63, with a separate type spike for the shapes of #48, #57, #59 and #60 (done: [spike 0007](../spikes/0007-phase-1a-type-shapes.md); the maintainer decided `owns_many`, candidate B for owned children of a new root and a required predicate in `Entity.where` on 2026-11-26; the first follow-up ADR, [ADR-0010](../adr/0010-writes-beyond-set.md) (Proposed, writes beyond `.set`, #57 and #60), changes §4.2-4.4 / 4.6 / 4.8 / 4.12 / 8.2 / 8.3 / 10.7 / 10.12 and gates the exit's use cases 6, 8 and 9; the second (#59) changes §4.7 and 8.2 "Dependent loads" and decides whether row sets replace partial `.where` loads), and the ADRs they call for (one of them for #61's run budget); ADR-0007 after #65; the cleanup cost of the run-ID tables (#72) before #63 fixes their schema. What these decisions add to the build issues follows the decision of each.
  - `expected_version`, `VersionMismatch` and the root `version` bump on changes of owned children are part of #11, #13, #15 and #17. Until the outbox lands (#23), a use case that emits events is rejected, never silently dropped; whether at seal or at run time is decided in #21.
- **Phase 1b - Events, queries and tooling**: inline projections and the outbox log (#23), Query path (TypedSQL, #24), schema tooling (optional extra, #25, CLI #26), the test kit (#27), the §9.5 measurements (#28) and documentation examples as tests (#29). Exit: adoption step 3 (§6).
  - Also in 1b: the set-load implementation (following #59), the cleanup cost of the outbox log (#73) before #23, and the classification of `53200` under SSI load (#74; it gates nothing - until then it is not retried and surfaces as `DatabaseError`).
  - Schema tooling in Phase 1 ([spike 0004](../spikes/0004-alembic-round-trip.md)): Alembic generates what round-trips (create, add or drop a column, a type change, `version` triggers); the constraint and index naming rule is decided in 1b, before the first name is created; a shadow-schema catalog diff reports what Alembic cannot see. `platina check` runs it in CI in projects that use `platina migrate`, and it can also check the declared tables of a database Platina does not migrate. A rename, or a changed CHECK or partial index, is a hand-written migration that the drift report catches. The internal tables follow #63 ([ADR-0009](../adr/0009-internal-tables-owned-by-the-core.md): versioned SQL in a dedicated schema, shipped only after #72).
  - `platina gen` accepts an existing database as its schema source (#24).
- **Phase 2**: async projections, `then` and `@process` with the job pipeline, batch use cases and set changes (#33; the set-level delete and `insert_all` follow [ADR-0010](../adr/0010-writes-beyond-set.md)), migration fidelity (renames, derived names, CHECK and partial-index changes, #70) and `platina pull` (#71). Phase 1 has no boundary with the outside world: the `@process` handlers that four of spike 0002's use cases need arrive here.
- **Later**: MySQL and MariaDB dialects, saga helpers, official free-threaded support
- Until `platina pull` lands, adoption step 0 (§6) is the query path alone, and a hand-written entity is checked against an existing schema by the drift check; §6 describes the end state.

### 9.7 Other
- [x] Name decided: Platina (§8.1)

---

## 10. Internal architecture (codebase design)

### 10.1 Principle: the ORM itself follows the philosophy

The rules we require of users apply equally to Platina's own codebase.

> **A core without IO (functional core) and a thin shell that does only IO (imperative shell).**

- **Core**: schema registry, expression AST, load plan, ChangeSet, commit planner, SQL compiler, execution engine. It does not import sockets, drivers or event loops.
- **Shell**: sync/async runners, psycopg driver adapter, CLI, framework integrations.
- This boundary is **enforced in CI by import-linter contracts**, not by review (§10.4). We use the tool we recommend to users first.

### 10.2 Internal structures referenced

| Source | Internal structure | What we take | What we avoid |
|---|---|---|---|
| psycopg 3 | Network code is written as generators that yield when they must wait, and the sync/async difference lives only in `wait()` functions. The sync code of the upper API is generated automatically from the AST of the async code, and CI checks for drift | The execution engine as a **generator-based state machine**. The thin public API layer generated async→sync automatically | |
| SQLAlchemy | Since 1.4, SQL compilation results are cached by cache key. Components that cannot produce a cache key raise a warning and performance drops sharply | Compilation cache | A structure where cache participation must be opted into per component. Our AST is **immutable, so a structural hash exists by default** |
| SQLAlchemy | A "dialect compliance suite" for third-party dialects, and a `Requirements` class marking support per dialect | Dialect **capability flags** + compatibility test suite (a mandatory gate when adding the MySQL dialect) | |
| Hibernate | ActionQueue collects write-behind DML and executes it in a fixed order at flush, which applies batching automatically | The commit planner collects changes and executes them **sorted + batched** | Fixed order (unique violation when replacing a collection). We use a dependency graph |
| Ecto | The Adapter behaviour defines the minimal API of an adapter, and queries etc. are split into separate behaviours such as `Ecto.Adapter.Queryable` | Driver and dialect interfaces split into **small Protocols per capability** | |
| Prisma | (design notes §2) sidecar query engine → moved to pure TS | | A separate engine process. Everything of ours is in-process |
| Django | Model methods hit the DB directly, and signals are wired as global side effects | | Global signals. Extension only through explicitly registered plugins |

### 10.3 Package structure

```
platina/
├── core/                    # ── no IO (enforced by import-linter) ──
│   ├── schema/              # Entity / @value metadata, type mapping, registry, seal validation
│   ├── expr/                # immutable expression AST (frozen dataclass + slots), structural hash
│   ├── snapshot/            # immutable snapshots, ref placeholders, move marks, field descriptors (Column[Owner, T] / T)
│   ├── changes/             # field operations (.to/.add/items.add…), + within a step, chain, final diff computation
│   ├── plan/                # load plan (Load/Profile/when/after/recursive), load stage DAG
│   ├── planner/             # commit planner: dependency graph → topological sort → batching
│   ├── engine/              # execution engine: state machine that yields Commands (including retry and backoff)
│   └── errors.py            # exception hierarchy (with structured fields)
├── sql/                     # ── no IO ──
│   ├── compiler/            # shared AST → SQL parts, compilation cache
│   └── dialects/
│       ├── base.py          # DialectCapabilities, strategy selection
│       └── postgresql/      # PG dialect (MySQL later goes here as a sibling)
├── app/                     # ── shell ── App, seal orchestration, run/query (ADR-0001)
├── runners/                 # ── shell ──
│   ├── async_.py            # anyio + psycopg AsyncConnection (source)
│   └── sync_.py             # generated automatically from async_.py (do not edit by hand)
├── drivers/psycopg/         # connection pool, pipeline, COPY, type adapters, SQLSTATE → exception mapping
├── outbox/                  # event log, consumer checkpoints (xid watermark), projection/process/then dispatchers
├── migrate/                 # [extra] registry → SQLAlchemy MetaData conversion, Alembic integration, drift checks
├── codegen/                 # TypedSQL type inference, platina pull, import-linter contract generation
├── testing/                 # test kit for users + dialect compatibility suite
├── integrations/fastapi/
└── cli/                     # platina check / gen / migrate / pull / contracts
```

### 10.4 Layer rules

```toml
# pyproject.toml — contracts of the Platina repository itself
[[tool.importlinter.contracts]]
name = "platina layers: shell -> core only"
type = "layers"
containers = ["platina"]
exhaustive = true            # every direct child of platina must be placed
layers = [
    "cli | integrations | testing",
    "app",                   # App, seal orchestration (ADR-0001)
    "runners | outbox | migrate | codegen",
    "drivers",
    "sql",
    "core",
]
```

- import-linter checks the layering between our own packages. Which *external* modules each zone may use is enforced by `tools/guards/archlint.py`: the core (`core`, `sql`) imports only an allowlist of standard-library modules (so no psycopg, anyio, asyncio, socket, threading, time, random, os, logging, sqlalchemy, alembic, ...), contains no `async`, and calls no clock or random-ID function; psycopg is imported only in `drivers`, SQLAlchemy and Alembic only in `migrate` (the optional extra).
- Why even `time` is forbidden: the core does not even wait for backoff itself; it requests it with a `Sleep` command. Thanks to this, engine tests do not use real time. Nothing time- or chance-dependent is produced inside the core: the clock arrives as the `Now` parameter (§4.5), the jitter's randomness as an engine argument, and new IDs from an injected ID source (ADR-0002).

### 10.5 Execution engine: a sans-IO state machine

The engine is a generator that **yields a Command** whenever it needs IO and proceeds when it receives the result (Reply). A runner is just a loop that turns commands into real IO.

```python
# core/engine/commands.py   (`bounded`: whether the run's deadline applies before the command; ADR-0008)
@dataclass(frozen=True, slots=True)
class Begin:    isolation: Isolation                     # with a budget, followed by set_config('statement_timeout', $1::text, true); the runner binds the remaining ms
class Pipeline: statements: tuple[CompiledSQL, ...]; bounded = True     # statements sent in one round trip
class Copy:     table: str; columns: tuple[str, ...]; rows: Iterable[tuple]
class CommitBatch: statements: tuple[CompiledSQL, ...]; bounded = True  # writes, projections, outbox, result record, COMMIT, LSN query (one round trip)
class StoredResult: run_id: RunId; bounded = False       # read run_result (result + fingerprint) in a separate READ COMMITTED transaction
class FreshLsn: bounded = False                          # query pg_current_wal_insert_lsn()
class Rollback: bounded = False
class ResolveClaim: run_id: RunId; bounded = False       # after CommitUnknown: BEGIN + claim only; not an attempt (ADR-0008 Decision 6)
class Sleep:    seconds: float; bounded = True           # retry backoff; bounded by its end, now + seconds

# core/engine/run.py  (no IO)
def run_usecase(uc: Usecase, args: Bound, policy: RetryPolicy, d: Dialect
               ) -> Generator[Command, Reply, RunResult]:
    pending: RunResult | None = None                        # result computed before commit (kept across attempts)
    fp = fingerprint(uc, args) if run_id.kind == "caller" else None   # once, before anything runs (UsageError if not serializable, #58)
    for attempt in policy.attempts():
        stage_kind = "load"                                 # RunTimeout's stage: "load", "commit" (or "backoff", below)
        try:
            snapshots = {}
            for i, stage in enumerate(uc.plan.stages):        # number of stages fixed at seal
                head = (begin(uc.isolation), budget(), claim(run_id)) if i == 0 else (budget(),)
                rows = yield Pipeline(head + stage.compile(d, args, snapshots))   # round trip 1: BEGIN + budget + run ID claim + load
                snapshots |= stage.materialize(rows)          # Load.after functions also run here (pure)
            changes = uc.invoke(snapshots)                    # user use case (pure); a deadline passed here is reported at the commit batch
            pending = RunResult.from_changes(changes)
            stage_kind = "commit"
            reply = yield CommitBatch(commit_plan(changes, d, run_id, fp))   # round trip 2: budget, writes … COMMIT, LSN
            return pending.committed(reply)                   # COMMIT's tag is COMMIT; an error after it still means committed
        except StatementFailed as f:                        # a fact from the runner: which statement failed, its SQLSTATE
            fault = classify(f, stage_kind)                   # (typed by drivers), whether the deadline had passed - the engine
        except DeadlineReached as e:                        # decides: claimed / retry / deadline / unknown / committed / fatal
            fault = Deadline(e)
        # Every yield below is outside the except clauses, so a DeadlineReached the runner reports at
        # one of them (only Sleep is bounded) reaches this code instead of escaping the generator.
        match fault:
            case Committed():                               # an error on a statement after COMMIT (ADR-0008 Decision 5)
                return pending.committed_with((yield FreshLsn()))
            case AlreadyClaimed():                          # run_claim 23505: the same run ID already committed
                yield Rollback()
                return (yield from replay(run_id, fp, pending))
            case Deadline():                                # the runner's deadline, or a budget 57014 before COMMIT
                yield Rollback()
                raise RunTimeout(stage=stage_kind, ...) from fault.cause   # never retried
            case Retryable():                               # 40001 / 40P01
                yield Rollback()
                try:
                    yield Sleep(policy.backoff(attempt, fault))
                except DeadlineReached:                     # the backoff would end past the deadline
                    raise RunTimeout(stage="backoff", ...) from fault.error   # the last 40001 is the cause
            case CommitUnknown():                           # connection lost during the commit batch
                if not (yield ResolveClaim(run_id)):        # 23505: the earlier attempt committed
                    yield Rollback()
                    return (yield from replay(run_id, fp, pending))
                yield Rollback()                            # claimed: it did not commit (the claim waited for it to end);
                                                            # release and start a normal attempt, from BEGIN and the claim
            case Fatal():                                   # not retryable: 23503, 23505 on a user table (without on_unique), 22xxx, ...
                yield Rollback()
                raise fault.error                           # the DatabaseError the driver typed, SQLSTATE kept
    raise RetryExhausted(...)                               # every attempt's outcome is known by now

def replay(run_id, fp, pending):                            # the replay path; never stopped by the deadline
    match run_id.kind:
        case "caller":                                      # caller key: stored result
            stored = yield StoredResult(run_id)             # the runner returns the row; the engine compares
            if stored.fingerprint != fp:
                raise IdempotencyKeyReuse(...)
            return stored.result
        case "auto":                                        # automatic ID: this runner's previous attempt committed
            return pending.committed_with((yield FreshLsn()))   # result in memory + fresh LSN
        case "job":                                         # job ID: another worker already completed it
            return RunResult.already_done(run_id)
```

```python
# runners/async_.py  (shell: the loop that turns commands into IO; it reports facts, it decides nothing)
async def drive_async(gen, conn, deadline):
    reply = None
    while True:
        try:
            cmd = gen.send(reply) if not isinstance(reply, BaseException) else gen.throw(reply)
        except StopIteration as stop:
            return stop.value
        if cmd.bounded and deadline.reached(by=cmd_end(cmd)):  # the Command says whether; Sleep ends at now + seconds
            reply = DeadlineReached()
            continue
        try:
            if isinstance(cmd, (CommitBatch, Rollback)):
                with anyio.CancelScope(shield=True):          # commit batch and rollback cannot be cut off by cancellation
                    reply = await execute(conn, cmd, deadline.remaining_ms())   # binds the set_config slot
            elif isinstance(cmd, Sleep):
                reply = await anyio.sleep(cmd.seconds)
            else:
                reply = await execute(conn, cmd, deadline.remaining_ms())
        except psycopg.Error as e:
            reply = StatementFailed(index=failed_statement(cmd, e), error=map_sqlstate(e),   # facts only; the
                                    deadline_passed=deadline.passed())                       # engine classifies them
```

- **sync/async semantics are 100% the same.** Both drive the same engine generator. The only differences are the loop's `await` and the shield.
- **Cancellation points are explicit.** Only the places where the engine yields can be cancelled.
- **The engine can be tested without a DB.** Just `send` prepared replies (§11.4).
- The runner code itself, in the same way as psycopg, keeps `async_.py` as the source and generates `sync_.py` by AST transformation. Humans do not maintain two copies.

### 10.6 SQL compiler: immutable AST + dialect capabilities

- **AST nodes are `frozen=True, slots=True` dataclasses.** Structural equality and hashing come by default, so the AST itself, minus bind values, becomes the compilation cache key. User-defined expressions also participate in the cache automatically as long as they follow the node rules.
- **Compilation is per-dialect `match` dispatch.** `PostgresCompiler` inherits the shared `Compiler` and overrides only the nodes that differ.
- **Dialect differences are strategies, not if statements.**

```python
@dataclass(frozen=True)
class DialectCapabilities:
    update_returning: bool          # PG ✓, MySQL ✗, MariaDB 13+ ✓
    data_modifying_cte: bool        # PG ✓, MySQL ✗
    pipeline: bool                  # PG(libpq 14+) ✓
    copy: bool
    recursive_cycle_clause: bool    # PG 14+ ✓
    ssi: bool                       # optimistic SERIALIZABLE

# the planner picks a strategy by looking at the capabilities
set_update_strategy = CteWithOutbox if caps.data_modifying_cte else LockSelectUpdateInsert
```

MySQL support then becomes a matter of adding a few of these strategies and a dialect compiler. `if dialect == "mysql"` does not spread throughout the core.

### 10.7 Commit planner (corresponds to the Hibernate ActionQueue)

```
ChangeSet
  → list of RowOps (Insert / Update / Delete / AggregateDelete / LinkAdd / LinkRemove)
  → dependency graph
       · FK: parent INSERT → child INSERT,  child DELETE → parent DELETE
       · unique key: operation that frees a value (DELETE, value change) → operation that takes the same value
       · AggregateDelete(root table, root keys) - ADR-0010, Proposed: one statement deleting every
           owned relation by the root keys and the roots (WITH ... DELETE);
           a DELETE of a row with an FK into the aggregate's tables, an UPDATE that changes or
           clears such an FK → AggregateDelete;
           AggregateDelete → INSERT into an owned table, UPDATE of its unique columns, only for
           unique constraints without the parent_fk column (it frees values the planner cannot
           see: the children are not loaded);
           AggregateDelete(X) → AggregateDelete(Y) when a table of X has an FK into a table of Y
           (from the registry; the rows are not loaded); aggregates that reference each other are
           merged into one statement (not verified on PostgreSQL)
  → topological sort (ties sorted so that table, operation and column set group together)
  → batching: multi-row INSERT / unnest UPDATE / DELETE … WHERE id = ANY($1)
  → Pipeline command (COPY is a separate command)
```

- If a cycle occurs, a `CommitCycle` error reports which rows and constraints caused it and points to `DEFERRABLE INITIALLY DEFERRED` constraints.
- `insert(root, *children)` is an Insert of the root and one per child, ordered by the FK edge. `root.delete()` is one `AggregateDelete` per root table, batched over the deleted roots (`WITH c1 AS (DELETE FROM items WHERE order_id = ANY($1)), c2 AS (DELETE FROM tickets WHERE order_id = ANY($1)) DELETE FROM orders WHERE id = ANY($1)`); a root's FK into its own owned table and FKs between owned tables need no order inside it, because NO ACTION FKs are checked after the whole statement. RowOps on owned children of a deleted root that come from earlier chain steps (an Update, a Delete from `remove`, an Insert from `add`) are dropped: the statement covers them (an operation that changes a child's `parent_fk` is a `UsageError` instead until #9 decides moves); within one step such a pair is an error, never dropped ([ADR-0010](../adr/0010-writes-beyond-set.md), Proposed).
- The planner is a pure function, so it is the main target of property-based tests (§11.3).

### 10.8 Snapshots, refs, move marks

- An entity snapshot is a **slots class** generated per entity at seal time (internal values are a tuple). Entities inherit `Entity` (ADR-0003), and `__init_subclass__` cannot add `__slots__`, so the slots class is made by the `Entity` metaclass or as a separate snapshot class. Field access goes through a descriptor, which returns `Column[Owner, T]` when accessed on the class and `T` when accessed on an instance.
- A **ref** is an "unloaded" instance of the same class. It holds only identifying information (PK or Finder key), and reading a field raises `UnloadedReference`. The runner collects refs when building the load plan.
- **chain views**: the values returned by `chain(order, wallet)` are view objects pointing to the latest state of the chain (the original entity at the type level). When passed to `c.run` they become the immutable snapshot of that moment; after leaving the block they are frozen at the final state, and `.set` and `.delete()` raise `ChainClosed`.
- **Move marks**: `chain(order, ...)` leaves "this snapshot object has been moved" in the current step's `contextvars` record. Rebinding the same names structurally removes most references to originals, and this mark blocks aliases created before the chain. When the descriptor reads a field, and when `__eq__` / `__hash__` run, they check this mark and raise `MovedSnapshotAccess`. The mark is per step scope, so it does not affect other coroutines or threads using the same snapshot.
- **Read tracking** has been removed from correctness responsibilities. It is turned on only in development and test modes, for the "declared but unused relation" warning and for showing the cause in `RelationNotLoaded`.
- Snapshots stay immutable to the end, so sharing them across threads is safe. Every write is expressed as a field operation value, so no proxies are needed.

### 10.9 Registry and seal

- During import, entities, Repositories and usecases are registered in a mutable registry.
- When all validations pass, `seal()` creates an **immutable `SealedRegistry`**, and any registration attempt after that is an error. Even in a free-threaded environment, the metadata shared at runtime needs no locks.
- Seal validation stages: ① resolve entities, relations and constraints (evaluate deferred annotations) → ② resolve and compile load plans → ③ module boundaries → ④ conflicts between invariants and set changes → ⑤ DTO and `@query` mappings → ⑥ (optional) drift comparison against the DB catalog.
- Where the stages live (ADR-0001): the pure checks (①, ③, ④ and the parts of ⑤ that need no SQL) are in `core/schema`; `app` orchestrates seal and runs the SQL-dependent stages (② through `platina.sql`, ⑥ in the shell) before building the `SealedRegistry`. Public names are re-exported by `platina/__init__.py` from `core`, `sql` and `app` only.

### 10.10 Extension points: explicit plugins

There are no global signals. Plugins are registered explicitly with `App(plugins=[...])`, and there are only three kinds of interface.

| Protocol | What it does | Examples |
|---|---|---|
| `ChangesTransformer` | Transforms the ChangeSet into another ChangeSet right before commit (pure) | soft delete (DELETE → `deleted_at` UPDATE), adding audit rows |
| `QueryTransformer` | Adds conditions to load and query ASTs (pure) | soft delete filter, tenant filter |
| `Observer` | Observes run results (read-only, side effects allowed) | Metrics, logs, tracing |

Transformation plugins are pure functions too, so they are applied deterministically in registration order and can be unit-tested.

### 10.11 Performance optimization path

- v1 is pure Python. Row decoding is already handled by psycopg's C implementation.
- Hot paths (snapshot creation, planner, compilation cache lookup) are kept behind small interfaces. If needed, they are replaced later with a Rust (PyO3) extension.
- mypyc is not used. mypyc does not yet support free-threaded builds. PyO3, on the other hand, supports building extensions for free-threaded Python.

### 10.12 Exception hierarchy

```
PlatinaError
├── SealError                 # validation failure at startup (module boundaries, invariants, mappings)
│   └── ModuleBoundaryError   # a module uses an entity another module owns
├── UsageError                # programming error, not retried
│   ├── RelationNotLoaded
│   ├── UnloadedReference     # reading a field of a ref, .set, .delete(), == or hash() on a ref
│   ├── ChainClosed           # .set or .delete() on a view outside the chain block
│   ├── MovedSnapshotAccess   # reading (also == / hash()) an original moved by chain
│   ├── ConflictingWrites     # writing the same field twice in one step; .delete() and .set of one snapshot
│   ├── IntraUsecaseConflict
│   └── CommitCycle
├── NotFound                  # row of the root ref or of a required dependent load is missing
├── IdempotencyKeyReuse       # caller key reused with different arguments (#58; not retried, a client's mistake)
├── RunTimeout                # the run's timeout= budget ran out: deadline or 57014 before COMMIT (ADR-0008; not retried;
│                             #   fields budget, stage "load" / "backoff" / "commit", sqlstate)
├── ConcurrencyError
│   ├── RetryExhausted        # 40001/40P01 retry limit exceeded
│   └── VersionMismatch       # expected_version mismatch (optimistic lock across requests)
└── DatabaseError             # other DB errors, SQLSTATE and the original exception preserved
    └── UniqueViolation, CheckViolation, ForeignKeyViolation (23503 / 23001, ADR-0010), ...
(user domain exceptions are not wrapped; they propagate as is)
```

`IdempotencyKeyReuse` (#58) and `RunTimeout` (#61) are decided; they are added to `platina.core.errors` with #22 and #17. `ForeignKeyViolation` (23503, and 23001 from a RESTRICT foreign key) is proposed by [ADR-0010](../adr/0010-writes-beyond-set.md): a `DatabaseError` the driver types from the SQLSTATE like `UniqueViolation` and `CheckViolation`, not retried - it depends on rows the use case did not read. It is common once rows that are not owned are written directly with hand-passed keys and a delete leaves them to the use case. PostgreSQL's diagnostics name the referencing table and constraint; the error names the referencing entity and field where the constraint name follows #25's naming rule (otherwise the table) and hints to delete or re-point those rows first. The engine attributes it by statement position, not by the psycopg call that raised it (a later call in the pipeline can raise it). It is added with #18. The `UsageError`s of writes (a `.set` or `.delete()` on a new entity, `insert` of a loaded snapshot, a direct write of an owned child, a created entity never inserted) are plain `UsageError`s with a `hint` (ADR-0010).

Besides the message, every exception has structured fields (`usecase`, `entity`, `field`, `location`, `hint`, and `details` for extra lines). No string parsing is needed for CLI or IDE integration or for test assertions. Their types, the constructor and the rendering are fixed by [ADR-0006](../adr/0006-exception-fields-and-rendering.md):

- The message is the only positional argument; the fields are keyword-only and read-only: `usecase: str | None` (the use case's registry name), `entity: type[object] | None` (the entity class), `field: str | None` (attribute path relative to `entity`, `"address.city"`), `location: SourceLocation | None` (`file`, `line`, `function`; `file` is the path from the top-level package, never absolute), `hint: str | None` (rendered as `Fix:`), and `details: tuple[tuple[str, str], ...]` for ordered lines the five fields cannot hold.
- `DatabaseError` adds a required `sqlstate: str | None`; the original driver exception is its `__cause__`, not a field.
- Every exception survives `pickle`, `copy` and `deepcopy` with all its fields (one `__reduce__` on `PlatinaError`).

---

## 11. Test strategy

### 11.1 Principles

- **The core is tested without a DB.** This is the biggest reason the architecture is sans-IO.
- **DB semantics are tested against real PostgreSQL.** No in-memory fake DB is built. Semantics such as isolation levels, NULL handling and constraints differ, so it gives false reassurance.
- **Examples in the documentation are tests that run.**

### 11.2 Test layers

| Layer | Target | DB | Tools | When run |
|---|---|---|---|---|
| Core unit + property-based | Field operations, chain views and move marks, planner, load stage planning | ✗ | pytest, Hypothesis | Every PR |
| Compiler snapshots | AST → SQL string | ✗ | inline-snapshot | Every PR |
| Engine state machine | Retry, rollback, cancellation, error injection | ✗ | Prepared reply scripts | Every PR |
| Architecture | Layer and no-IO contracts, sync/async generated output in sync | ✗ | import-linter, generation script `--check` | Every PR |
| Types | Type inference of the public API, whether misuse is a type error | ✗ | pyright + mypy, `assert_type` | Every PR |
| Integration | Real SQL execution, migrations, outbox, codegen | ✓ | docker compose, pytest-xdist | Every PR (latest PG), nightly (PG 14 to 18) |
| Documentation | Every code block in the documentation | ✓ | Sybil | Every PR |
| Concurrency | write skew, retry, deadlock, stress invariants | ✓ | Ordering controlled with anyio events | nightly |
| Differential testing | Semantic correctness of the compiler | ✓ | Hypothesis + reference evaluator | nightly (phase 2) |
| Compatibility suite | Shared capability-based tests per dialect | ✓ | `platina.testing.suite` | Per-dialect CI |
| free-threaded | Thread safety of the core | ✗ | 3.14t + pytest-run-parallel | Every PR |
| Performance | §9 benchmark scenarios, regression detection | ✓ | pytest-benchmark | nightly |
| Mutation testing | Effectiveness of planner and ChangeSet tests | ✗ | mutmut | Once a week |

### 11.3 Core: property-based tests

ChangeSets and the planner are tested by "laws". Rather than a few examples, we check that properties hold over thousands of inputs generated by Hypothesis.

```python
from hypothesis import given, strategies as st
from platina.testing.strategies import snapshots, steps, changesets, fk_schemas, load_plans
from tests.support.laws import (
    apply_sequentially, executed_stage_counts, read_through_moved_alias,
    replay_on_reference, run_chain,
)

@given(snapshots(Order), steps(Order), steps(Order))
def test_chain_equals_sequential_apply(order, f, g):
    """chain of f, g == running g on the snapshot that f produced."""
    # when
    chained = run_chain(order, f, g)                    # helper: with chain(order) ... c.changes
    # then
    assert order.applied(chained) == apply_sequentially(order, f, g)

@given(snapshots(Order), steps(Order), st.sampled_from(Order.fields()))
def test_alias_of_moved_snapshot_is_always_rejected(order, f, field):
    """Reading any field through an alias made before chain is always MovedSnapshotAccess."""
    # when
    error = read_through_moved_alias(order, f, field)   # helper: alias before chain, read inside it
    # then
    assert isinstance(error, MovedSnapshotAccess)

@given(load_plans())
def test_stage_count_is_fixed_at_seal(plan):
    """The number of load stages does not depend on data: for every condition outcome it equals the depth computed at seal."""
    # when
    counts = executed_stage_counts(plan)                # helper: simulate every condition outcome
    # then
    assert counts == {plan.sealed_depth}

@given(fk_schemas().flatmap(lambda s: st.tuples(st.just(s), changesets(s))))
def test_planner_never_violates_constraints(schema_and_changes):
    """Replaying the planner's execution order on a reference model never breaks an FK or unique constraint."""
    # given
    schema, changes = schema_and_changes
    # when
    violations = replay_on_reference(plan_commit(changes, schema), schema)   # small constraint-only Python model
    # then
    assert violations == []
```

With ADR-0010 the generated schemas and change sets also cover deletes of roots whose owned children are not loaded (the reference model holds rows the change set never names), FKs between owned tables of one root, a root's FK into its own owned table, unique keys of a child table with and without the parent key, and rows outside the aggregate that reference owned children; a `CommitCycle` is reported exactly when no valid order exists, and `chain` of a `.set` and a `.delete()` equals the delete.

The tests follow the repository's test style: Given/When/Then markers and no control flow in test modules. Loops (over condition outcomes, over row operations) live in helpers under `tests/support/`.

### 11.4 Engine: exhaustive error injection

Because the engine is sans-IO, **tests that inject an error at every yield point** can be run deterministically.

```python
FAULTS = [SerializationFailure(), Deadlock(), ConnectionLost(), Cancelled(), DeadlineReached()]
RETRYABLE = [SerializationFailure(), Deadlock()]
POINTS = yield_points(pay_usecase)                   # helper: every yield index of the happy path

@pytest.mark.parametrize("fault", FAULTS)
@pytest.mark.parametrize("point", POINTS)
def test_fault_at_any_yield_point_never_commits_partial_state(point, fault):
    # given
    script = happy_path_script(pay_usecase)          # (command, reply) list of the normal flow
    # when
    trace = replay(run_usecase(pay_usecase, ARGS, POLICY, PG), script, inject=(point, fault))
    # then
    assert trace.commits_after_error() == 0
    assert trace.ends_with_rollback_or_retry()

@pytest.mark.parametrize("fault", RETRYABLE)
@pytest.mark.parametrize("point", POINTS)
def test_retryable_fault_restarts_from_begin(point, fault):
    # when
    trace = replay(run_usecase(pay_usecase, ARGS, POLICY, PG),
                   happy_path_script(pay_usecase), inject=(point, fault))
    # then
    assert trace.restarted_from_begin()              # a retry always starts again from the load
```

```python
@pytest.mark.parametrize("committed", [True, False], ids=["committed", "rolled-back"])
def test_commit_unknown_is_resolved_by_rerun_with_same_run_id(committed):
    """If the connection drops during the commit batch, a claim with the same run ID decides whether it committed."""
    # when
    trace = replay(run_usecase(pay_usecase, ARGS, POLICY, PG),
                   happy_path_script(pay_usecase), inject=("CommitBatch", ConnectionLost()),
                   server_state={"committed": committed})
    # then
    assert trace.second_attempt_run_id == trace.first_attempt_run_id
    assert trace.applied_once()                      # committed: 23505, the replay path; otherwise rollback, then a normal attempt
```

- In the same way, we check that when cancellation is injected, it is not delivered in the middle of `CommitBatch`/`Rollback` commands (shield).
- Thanks to the `Sleep` command, backoff tests take no real time.

### 11.5 Integration tests: real PostgreSQL

- Start PostgreSQL with docker compose (`make db-up`; measurements on the durable profile, `make db-up-durable`) and create a **template DB** with the test schema applied, once. Each test gets a DB cloned with `CREATE DATABASE … TEMPLATE`. Isolation by transaction rollback is not used, because our runner owns the transaction boundaries itself.
- Each pytest-xdist worker has its own template, for parallel execution.
- Every SQL statement stored in the compiler snapshots is actually `PREPARE`d in the integration stage to double-check that there are no syntax errors.
- Matrix: one latest PostgreSQL on PRs, all of PG 14 to 18 nightly.

### 11.6 Concurrency tests

Ordering is not left to luck; events pin down the points where two transactions interleave.

```python
async def test_write_skew_is_prevented(app_with_db):
    """Rule: at least one doctor must stay on call. Two doctors try to go off call at the same time."""
    # given
    both_loaded = Barrier(2)

    async def go_off(doctor_id):
        async with app_with_db.pause_after_load(barrier=both_loaded):   # wait point after loading
            return await app_with_db.run(go_off_call.bind(doctor=Doctor.ref(doctor_id), shift=SHIFT))

    # when
    await gather_settled(go_off(1), go_off(2))
    # then
    on_call = await app_with_db.query(doctors.on_call(shift=SHIFT))
    assert len(on_call) >= 1                                   # invariant holds
    assert app_with_db.stats.retries(go_off_call) >= 1         # SSI made one side retry
```

```python
async def test_unrelated_commands_do_not_conflict_on_internal_tables(app_with_db):
    """Running hundreds of commands on different orders concurrently must cause zero serialization
    failures from run ID and outbox INSERTs (verifies the internal append-only table rule)."""
    # given
    calls = pay_calls_on_disjoint_orders(500)       # helper: pay.bind(...) on distinct orders and wallets
    # when
    await run_concurrently(app_with_db, calls)      # helper: gather over app.run
    # then
    assert app_with_db.stats.serialization_failures() == 0
```

- **Stress invariant test**: after N workers run thousands of random account transfers, check that the total balance is unchanged. The retry rate is also recorded and used as evidence for "the cost of the SERIALIZABLE default" in §9.
- Tests that check *whether* something happens can use the fast test database. Anything that reports a *rate* (retry rate, throughput) runs against the durable profile (`make db-up-durable`): with fsync off on tmpfs, commits are shorter, transactions overlap less, and conflicts would be understated.

### 11.7 Differential testing (phase 2)

Hypothesis generates random query ASTs over a fixed schema and data, and the results of executing them on PostgreSQL are compared with the results of a small Python reference evaluator. The goal is to catch bugs where the compiler changes semantics in NULLs and three-valued logic, joins and grouping. The reference evaluator is expensive to implement, so it is introduced after the compiler stabilizes.

### 11.8 Type tests

```python
# tests/typing/pass_composition.py — must pass both pyright and mypy
result = await app.run(pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid)))
assert_type(result.token, ConsistencyToken)
rows = await app.query(orders.summaries(user_id=uid))
assert_type(rows, list[OrderSummary])
assert_type(Order.status, Column[Order, OrderStatus])
assert_type(order.status, OrderStatus)
with chain(order, wallet) as (c, o2, w2):
    assert_type(o2, Order)
    assert_type(w2, Wallet)
new = Order(number="A-1", total=money, user_id=uid)              # required-field check
item = Item(sku="A", price=money, position=1)                    # no order_id: the parent sets it
assert_type(order.set(Order.items.add(item)), Changes)
assert_type(insert(Transfer(amount=money), Transfer.legs.add(leg)), Changes)   # ADR-0010
assert_type(order.delete(), Changes)
assert_type(Wallet.user_id == Order.user_id, Pred[Wallet | Order])  # a predicate over both owners

# tests/typing/fail_misuse.py — every line must be a type error with the named codes [pyright rule, mypy code]
# fmt: off
pay.bind(order=oid, wallet=w)                 # expect-error[reportArgumentType, arg-type]: UUID is not Order
pay.bind(ordr=Order.ref(oid), wallet=w)       # expect-error[reportCallIssue, call-arg]: parameter name typo
order.set(Order.status.to(123))               # expect-error[reportArgumentType, arg-type]: int is not OrderStatus
order.status = OrderStatus.PAID               # expect-error[reportAttributeAccessIssue, misc, arg-type]: snapshots are immutable
order.items.append(item)                      # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: Sequence has no append
apply_coupon(o, c) + pay(o, w)                # expect-error[reportOperatorIssue, reportUnusedExpression, operator]: + not allowed between StepResults
orders.by_number(42)                          # expect-error[reportArgumentType, arg-type]: Finder[Order, str]
Order(number="A-1")                           # expect-error[reportCallIssue, call-arg]: required fields total, user_id missing
Item(order_id=order.id, sku="A", price=money, position=1)  # expect-error[reportCallIssue, call-arg]: the parent sets an owned child's key
assert Order.total.path(Money.amount) >= 0    # expect-error[reportOperatorIssue, operator]: a value is exactly T, no widening
Order.where(Order.user_id == Wallet.user_id)  # expect-error[reportArgumentType, arg-type]: a predicate over Order | Wallet
rows = Order.where()                          # expect-error[reportCallIssue, reportUnknownVariableType, call-arg]: a row set needs a predicate
order.set(Order.payments.add(payment))        # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType, attr-defined]: not owned, no write operations
insert(transfer, Transfer.amount.to(money))   # expect-error[reportArgumentType, arg-type]: insert takes owned-child add only
# fmt: on
```

- `tools/typetests.py` runs both checkers and checks every marked line: each checker must report an error there, and every error it reports on that line must carry one of the listed codes (pyright rules start with `report`, the others are mypy codes). Without the codes, a line that fails for an unrelated reason (a misspelled name) would pass.
- The codes above are the ones spike 0001 observed (§9.1), spike 0006 for the parent-key and comparison lines, and spike 0007 for the write lines (`insert`, `delete`, `where`, relation operations; ADR-0010). Some lines carry more than one code per checker: mypy reports both `misc` (frozen) and `arg-type` (the `Never` instance of `__set__`) on the immutability line, and pyright strict adds `reportUnknownMemberType` to the `append` line and `reportUnusedExpression` to the bare `+` expression (as `_ = ...` it would be `reportUnknownVariableType` instead).
- A marker makes the line long; `ruff format` would wrap the statement and move the marker off the line that errors, so fail files fence their misuse block with `# fmt: off` / `# fmt: on`.
- A rejected comparison stands in an `assert` statement. pyright strict adds another code to every other use of an expression that failed to type (`reportUnusedExpression` on a bare expression, `reportUnknownVariableType` on an assignment, `reportUnknownArgumentType` on a call argument); in an `assert` both checkers report the operator code alone, and an accepted comparison reports nothing, so the line fails (spike 0006).

### 11.9 Compatibility suite

Following SQLAlchemy's approach, dialect-independent shared tests are published as `platina.testing.suite`, and dialects declare what they support through `DialectCapabilities`. Tests for unsupported features are not skipped; **they turn into tests of the reduced-mode strategy.** The PostgreSQL dialect is the first user of this suite, and passing this suite is a release condition for the MySQL dialect.

### 11.10 free-threaded verification

The unit tests, core first, are run on 3.14t with pytest-run-parallel. This plugin does not run the whole test suite in parallel; it runs the same test concurrently on several threads to find thread safety problems. This is where we confirm that the immutable snapshot and `SealedRegistry` designs are actually safe without locks. It runs on every PR, and the run also fails when the GIL is on: a dependency whose extension module re-enables it would turn the run into an ordinary GIL run.

### 11.11 Test kit for users (`platina.testing`)

| Provided | Purpose |
|---|---|
| `Entity.stub(...)` | Snapshots for use case unit tests without a DB |
| `Entity.ref(...)`, Finder calls | Placeholders to pass as `bind` arguments (integration tests) |
| `changes.updated()`, `.inserted()`, `.events` | ChangeSet assertions |
| `freeze_now(...)` | Pin the `Now` injected value |
| pytest plugin: `pg_database`, `app_with_db` | Integration test fixtures based on template DB cloning |
| `app.expect_roundtrips(max=N)` | Round-trip budget assertions (prevent N+1 regressions) |
| `app.pause_after_load(...)` | Reproduce concurrency scenarios |
| `strategies` (Hypothesis) | Snapshot and ChangeSet generators for user entities |

We give users the same test tools we use. No in-memory fake DB is provided. Pure use cases do not need a DB, and for tests that do need a DB, real PostgreSQL is the right choice.

---

## Sources

- Hibernate ORM 7.0 Apache 2.0 relicensing: https://in.relation.to/2025/03/14/orm-asl/ , https://docs.hibernate.org/orm/7.0/migration-guide/
- psycopg pipeline mode: https://psycopg.org/psycopg3/docs/advanced/pipeline.html
- psycopg 3.3 t-string support: https://www.postgresql.org/about/news/psycopg-33-released-3187/
- psycopg async (asyncio, gevent): https://psycopg.org/psycopg3/docs/advanced/async.html
- psycopg Trio support discussion: https://github.com/psycopg/psycopg/issues/29
- PostgreSQL serialization failure handling: https://www.postgresql.org/docs/16/mvcc-serialization-failure-handling.html
- PEP 779 (free-threaded supported status): https://discuss.python.org/t/pep-779-criteria-for-supported-status-for-free-threaded-python/84319/123
- PEP 649/749, annotationlib: https://docs.python.org/3/library/annotationlib.html
- PEP 810 (explicit lazy imports): https://peps.python.org/pep-0810/
- Python 3.15 release: https://docs.python.org/3.15/whatsnew/3.15.html
- MySQL RETURNING request: https://bugs.mysql.com/bug.php?id=117915
- MariaDB INSERT…RETURNING: https://mariadb.com/kb/en/insertreturning/ , MariaDB 13.0 UPDATE…RETURNING: https://mariadb.com/resources/blog/announcing-mariadb-community-server-13-0-ga.md
- triopg / pgtrio: https://awesome.ecosyste.ms/projects/github.com%2Fpython-trio%2Ftriopg , https://pypi.org/project/pgtrio/0.5.1/
- Atlas license and v0.38 change: https://atlasgo.io/features , https://dev.to/mickelsamuel/atlas-paywalled-their-migration-linter-here-are-your-free-alternatives-4god
- sqldef: https://github.com/sqldef/sqldef
- Prisma TypedSQL DB connection requirement: https://www.prisma.io/docs/orm/v6/prisma-client/using-raw-sql/typedsql
- sqlc DB-based analysis: https://docs.sqlc.dev/en/latest/howto/generate.html
- outbox polling and CDC: https://encore.dev/articles/transactional-outbox-pattern , https://oneuptime.com/blog/post/2026-07-22-transactional-outbox-duplicate-events/view
- import-linter contracts: https://import-linter.readthedocs.io/en/v2.0/contract_types.html
- PyPI name and wheel check: https://pypi.org (checked directly on 2026-11-24)
- psycopg internal design (generators and wait, automatic async→sync conversion): https://psycopg.org/articles/tag/psycopg3 , https://www.postgresql.org/message-id/CA%2Bmi_8YaYErxx0L56Z1HdXkMmdMd-TSYZ%3DUDjQZAOSQ4zUTKPQ%40mail.gmail.com
- SQLAlchemy compilation cache: https://docs.sqlalchemy.org/en/21/faq/performance.html
- SQLAlchemy dialect compliance suite: https://sources.debian.org/src/sqlalchemy/2.0.45%2Bds1-1/README.dialects.rst
- Hibernate ActionQueue: https://vladmihalcea.com/hibernate-facts-knowing-flush-operations-order-matters/ , https://docs.hibernate.org/orm/7.2/javadocs/org/hibernate/engine/spi/ActionQueue.html , https://forum.hibernate.org/viewtopic.php?p=2431155
- Ecto Adapter behaviour: https://hexdocs.pm/ecto/3.7.0/Ecto.Adapter.Queryable.html
- free-threaded extension tooling support (mypyc, PyO3): https://py-free-threading.github.io/dependencies , https://docs.rs/crate/pyo3/0.28.0/source/guide/src/free-threading.md
- pytest-run-parallel: https://pypi.org/project/pytest-run-parallel
- Python 3.14 uuid7: https://docs.python.org/3.14/library/uuid.html
- SSI read locks per B-tree leaf page: https://postgresql.org/message-id/CAHXaXTy%3DaJROA0pXXifb%3DjkvP%2B2_62s9%2BictzqkmfhOJVjHWxg%40mail.gmail.com , https://www.interdb.jp/pg/pgsql05/09.html
- Discussion of descriptor fields and dataclass_transform constructor types (2026-10): https://discuss.python.org/t/plain-annotations-for-descriptor-backed-fields-orms-dataclass-transform/109427
- txid_status for checking commit outcome (rationale of the earlier proposal): https://www.enterprisedb.com/blog/traceable-commit-postgresql-10
