# Spike 0004: Entity registry -> SQLAlchemy MetaData -> Alembic round trip

- Design section: 9.3 "MetaData → Alembic round trip" ("Convert the entity registry to
  SQLAlchemy `MetaData` and see whether Alembic autogenerate round-trips the following without
  loss": `renamed_from` hints, `Check` declared with lambdas, `version` triggers, expression and
  partial indexes, framework internal tables)
- Issue: #4
- Date: 2026-11-25
- Code: `spikes/0004-alembic-round-trip/` (throwaway; raw output in `results/`, git-ignored)

## Question

Section 8.5 decides that "DDL generation, catalog reflection and migrations are handed to
SQLAlchemy Core and Alembic. The entity registry is converted to SQLAlchemy `MetaData` to use
Alembic autogenerate", and names the risk: "fidelity of the conversion. The weak spots of Alembic
autogenerate overlap with features of this design" - ① `renamed_from` hints ("plan to turn
drop+add into a rename with the `process_revision_directives` hook"), ② `Check` declared with
lambdas, ③ `version` triggers ("Alembic does not handle triggers → evaluate third-party PG object
support"), ④ expression and partial indexes, ⑤ framework internal tables (especially
partitions). Section 9.3 asks whether these round-trip "without loss". Item ⑥ below carries two
schema needs over from spike 0002 (X16 and a column-to-column CHECK).

The dangerous error is a false "it round-trips". An object Alembic never compares passes a
"second autogenerate is empty" test every time, whatever the database holds. So every item is
judged by **four criteria**, all four recorded:

1. **Create**: on an empty database, the first autogenerate -> `upgrade` -> a second autogenerate
   produces no operations.
2. **Catalog**: catalog queries (`pg_constraint` + `pg_get_constraintdef`, `pg_get_indexdef`,
   `pg_trigger` + `pg_get_triggerdef`, `pg_proc.prosrc`, `pg_partitioned_table` +
   `pg_get_partkeydef`, `pg_inherits` + `pg_get_expr(relpartbound)`, `pg_attribute`) show the
   objects the declaration intends - checked against the declaration by reading, and mechanically
   against the same state created directly (`MetaData.create_all` plus the registry's own DDL)
   in a separate schema.
3. **Change** (the key criterion): change the declaration once -> autogenerate **detects** it
   (the revision contains the operations for the change) -> `upgrade` -> a second autogenerate is
   empty -> the catalog matches the new declaration.
4. **Downgrade**: `downgrade` one revision at a time returns the catalog to the snapshot taken
   after the corresponding `upgrade`.

Per item the verdict is **holds** (all four pass for every sub-case), **does not hold** (the
change criterion fails for the item's main sub-case or the catalog is wrong), or **partly**
(some sub-cases or criteria fail), with the criteria that passed listed. "Holds" is never given
on criterion 1 alone.

What would confirm 8.5's plan: items ① ② ④ ⑤ ⑥ pass all four criteria with stock Alembic plus
the `process_revision_directives` rename hook; item ③ passes with Alembic's own extension points
(custom operations, a comparator plugin, `process_revision_directives`) or needs a third-party
package. What would refute it: a change that autogenerate does not see, an applied migration that
loses data or leaves the catalog different from the declaration, or a downgrade that does not
restore the previous catalog - each a place where `platina migrate` would need its own code or a
different tool.

### Items and sub-cases (fixed before the code)

1. **`renamed_from`** (drop+add -> rename in `process_revision_directives`):
   a. column rename; b. table rename; c. rename and type change at once; d. renaming columns that
   carry an index, a foreign key and a CHECK; e. the hint left in the code after the migration was
   applied (the next autogenerate must be empty). For a and c a row is inserted before the
   rename and read after it: a rename keeps the value, a drop+add loses it.
2. **`Check` declared with a lambda**: section 4.2's embedded-path check
   (`Order.total.path(Money.amount) >= Decimal(0)`) created with the table; on an existing table a
   CHECK added, its expression changed, and removed; the constraint naming rule.
3. **`version` trigger**: function and trigger created; a change of the function body detected;
   the trigger (and the function, when unused) dropped when the entity loses its
   `version_column()`. Tried first with Alembic's own extension points; third-party PG object
   support (`alembic_utils`) is evaluated by reading its documentation and public source only -
   it is not installed or run.
4. **Expression and partial indexes**: section 4.2's index with `desc()`; a function-expression
   index (`lower(email)`); an index with `WHERE`; a change of only the expression and a change of
   only the `WHERE` condition, under the same index name.
5. **Framework internal tables**: minimal `run_claim`, `run_result`, outbox log, a job table and a
   consumer checkpoint; partitioned parents and their partitions; partitions added outside
   migrations (does autogenerate propose to drop children that are not in the metadata?); the
   relation between the primary key and the partition key.
6. **Carried over from spike 0002**: a composite unique key (X16, `Stock` unique on
   (warehouse, variant)) and a column-to-column CHECK (`Stock.allocated <= Stock.quantity`).

Alembic configuration under test ("baseline"): Alembic 1.20 defaults (`compare_type=True`,
`compare_server_default=False`, plugins `alembic.autogenerate.*`) plus the spike's rename rewrite
and trigger plugin. A second configuration adds Alembic's opt-in plugin
`alembic.ext.checkconstraint_byname` (found in the installed source while preparing this
method; it ships with Alembic, so it is not a new dependency) and every scenario is run under
both. For items 2 and 4 a second naming rule is also run (see the assumptions): names derived
from the referenced columns, and names derived from a hash of the declared expression.

### Assumed for the experiment (inputs the design does not give; not decisions)

| # | Assumption | Would another choice change the result? |
|---|---|---|
| A1 | `renamed_from` syntax: `column(renamed_from="old")` on a column, `class C(Entity, table="new", renamed_from="old")` on a table. | No for the Alembic result: the rewrite reads the hint from `Column.info` / `Table.info`, wherever the syntax puts it. |
| A2 | Partitions (maintainer-confirmed, experiment only): `run_claim` is range-partitioned on `id` (uuid7), the outbox log on its time column; expired partitions are dropped. Partitions are created outside migrations (by a maintenance job). | Yes for item 5: list/hash partitioning would not change what Alembic sees (it sees partitioned parents as plain tables either way), but creating partitions inside migrations instead of a job changes which drop proposals appear. |
| A3 | `version` trigger body (minimal form): one shared function `platina_bump_version()`, `BEFORE UPDATE ... FOR EACH ROW`, `IF NEW.version IS NOT DISTINCT FROM OLD.version THEN NEW.version := OLD.version + 1; END IF; RETURN NEW;`, one trigger `platina_version_<table>` per table with a `version_column()`. Whether this is right for optimistic locking is out of scope. | No for the round trip: Alembic sees no function or trigger at all, whatever the body. Per-table functions would only add objects to the same mechanism. |
| A4 | Index syntax: `Index(lambda: (cols or expressions...), where=lambda: <predicate>, unique=False, name=None)`; functions via a `fn` namespace (`fn.lower(User.email)`). Composite unique key (X16): `Meta.uniques = (Unique(lambda: (Stock.warehouse_id, Stock.variant_id)),)`. | No for what Alembic compares; the syntax only feeds `sqlalchemy.Index(...)` / `UniqueConstraint(...)`. |
| A5 | Constraint and index names are computed by the registry. Rule "columns": `ck_<table>_<columns>`, `ix_<table>_<columns>`, `uq_<table>_<columns>` (the columns the expression references, so the name survives an expression change). Rule "hash": `<prefix>_<table>_<8 hex of the declared expression>` (the name changes with the expression). Foreign keys and primary keys use SQLAlchemy naming conventions (`fk_<table>_<column>_<referred table>`, `pk_<table>`). | Yes: whether a CHECK or index change is detected depends on the rule (this is measured, not decided). |
| A6 | Type mapping (minimal): `Id[...]` -> `uuid`, `str` with `length` -> `varchar(n)` (without -> `text`), `Decimal` -> `numeric(12,2)`, `int` -> `integer`, `datetime` -> `timestamptz`, enums as `text`, `xid8` columns as a `UserDefinedType` rendering `xid8`. | Only for item 5's `xid8` columns (a type SQLAlchemy does not reflect) - see the observations. |
| A7 | Lambdas are evaluated once, when the registry is converted to `MetaData` (seal). | No. |

The throwaway registry mimics section 4.2's `Order` with ADR-0003/0004 syntax (`Entity` base,
`Col[...]`, `Order.total.path(Money.amount)`) and is written from scratch; it does not import
`spikes/0002-use-cases-on-paper/`.

### Hypotheses (from the main session's memory; predictions, not facts)

- H1 A rename comes out as drop+add.
- H2 A CHECK is created with a new table, but a change on an existing table is not detected.
- H3 Alembic does not see triggers at all.
- H4 Expression indexes produce false diffs because PostgreSQL normalizes the expression, or
  their comparison is skipped.
- H5 Partitions that are not in the metadata are proposed for dropping.
- H6 A unique constraint on a partitioned table must include the partition key.

Added while reading the installed Alembic 1.20.1 source for the method (to be checked, not
assumed):
- H7 `DefaultImpl.compare_check_constraint` returns `Equal` unconditionally and the PostgreSQL
  impl does not override it, so even with `checkconstraint_byname` a CHECK whose expression
  changes under the same name is not detected.
- H8 `PostgresqlImpl.compare_indexes` compares expressions (after normalizing casts, quotes and
  parentheses) and only `nulls_not_distinct` among the dialect options, so a `WHERE` change under
  the same name is not detected.
- H9 `AlterColumnOp.reverse()` does not swap `modify_name`, and `RenameTableOp` has no
  `reverse()`, so a rename rewrite must build its own downgrade.

## Setup

- Python 3.14.7 (`uv run python -V`), macOS arm64 (Darwin).
- PostgreSQL 18.6 (`SELECT version()`: "PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2) on
  aarch64-unknown-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit"), fast profile
  (`make db-up`, port 26432, `fsync=off`), database `spike0004` created for the spike.
- SQLAlchemy 2.1.9, Alembic 1.20.1, psycopg 3.3.9 (libpq 18.0.6), all from
  `uv sync --group spike`; nothing else installed. pyright 1.1.414 and mypy 2.4.1 are present but
  not used (no typing question here).
- Data size: one or two rows per table where a rename must keep a value; nothing else.

## Method

**Databases.** Fast profile only (`make db-up`, port 26432, tmpfs, `fsync=off`; already running).
A dedicated database `spike0004` is created; nothing is created in the `platina` database. Each
scenario starts with `DROP SCHEMA public CASCADE; CREATE SCHEMA public` and the same for a
reference schema `ref` inside `spike0004`. Alembic only looks at the default schema
(`include_schemas=False`), so `ref` is invisible to autogenerate. The independent reproduction
uses its own database `spike0004_repro`. Both databases are dropped at the end. Nothing here
measures a rate, a throughput or a latency.

**Harness** (`spikes/0004-alembic-round-trip/`):
- `registry.py` - the throwaway registry (`Entity`, `Col`, `column`, `pk`, `fk`, `embedded`,
  `value`, `version_column`, `Check`, `Index`, `Unique`, `fn`) and `to_metadata(entities,
  naming)`, which evaluates the lambdas and builds `MetaData` (tables, columns, `CheckConstraint`,
  `Index` with `postgresql_where`, `UniqueConstraint`, `ForeignKey`, `postgresql_partition_by`,
  hints in `info`, triggers in `MetaData.info`).
- `ext.py` - the Alembic extension: custom operations (`create/replace/drop` for the trigger
  function and the triggers) with implementations and renderers, a comparator plugin
  (`platina.version_trigger`) that reads `pg_proc` / `pg_trigger`, and the rename rewrite used in
  `process_revision_directives`, which also builds the downgrade for its rename operations.
- `alembic_env/` - `env.py` and `script.py.mako`; migrations are written to
  `results/<config>/<scenario>/versions/`.
- `scenarios.py` - each scenario is a list of states (registry snapshots); every state is a
  function that defines the entities from scratch.
- `catalog.py` - the catalog snapshot (tables with relkind and partition key/bound, columns with
  type, nullability and default, constraints with definitions, indexes with definitions, triggers
  with definitions, functions with source), taken with `search_path` set to the schema so that
  definitions are unqualified.
- `run.py <config> <scenario>|all` - for each scenario:
  1. reset both schemas;
  2. for each state in order: `alembic revision --autogenerate` (via `alembic.command`), print the
     generated `upgrade()` / `downgrade()` bodies; `alembic upgrade head`; a second autogenerate
     in dry-run mode (operations rendered and discarded) -> `EMPTY` or the operations; catalog
     snapshot of `public`; the same state created directly in `ref` -> snapshot; the two compared
     (`MATCH` or the differences); scenario-specific probes (row values for renames, catalog rows
     named in the item);
  3. then `alembic downgrade -1` repeatedly: after each step the catalog is compared with the
     snapshot recorded after that revision's upgrade (`MATCH` or the differences), and a dry-run
     autogenerate against that older state is printed.
- Configurations: `baseline` and `ckplugin` (baseline + `alembic.ext.checkconstraint_byname`);
  naming rule `columns` everywhere, plus `hash` for the CHECK and index scenarios.
- Probes outside the main loop: the partitioned-table unique rule (H6) as plain DDL, and the
  naive rename rewrite with `UpgradeOps.reverse_into` (H9).

**Commands** (from the worktree root):

```
uv sync --group spike
uv run python spikes/0004-alembic-round-trip/run.py setup          # creates spike0004
uv run python spikes/0004-alembic-round-trip/run.py all > spikes/0004-alembic-round-trip/results/all.txt 2>&1
uv run python spikes/0004-alembic-round-trip/probes.py | tee spikes/0004-alembic-round-trip/results/probes.txt
uv run python spikes/0004-alembic-round-trip/run.py teardown       # drops spike0004
```

One scenario alone: `run.py <stock|baseline|ckplugin> <scenario> [columns|hash]`. Per-scenario
output lands in `results/<config>-<naming>/<scenario>.txt`, the generated migrations in
`results/<config>-<naming>/<scenario>/versions/`, the table of all runs in `results/summary.md`.
`SPIKE_DB` selects another database (the reproduction uses `spike0004_repro`).

### Changes to the method while running (recorded, not hidden)

- **A third configuration, `stock`**, was added: Alembic defaults with neither the rename rewrite
  nor the trigger plugin. It is the direct evidence for H1 and H3. `baseline` and `ckplugin` are as
  planned.
- **A fresh `MetaData` for every Alembic call.** Reusing one `MetaData` object across calls made
  `create_all` fail with `DuplicateObject: check constraint "ck_orders_qty" already exists`
  (side finding F1). A CLI run builds `MetaData` once per process, so the harness now rebuilds it
  per call.
- **The comparison after a downgrade** uses `produce_migrations` with the same plugins and
  rewrite: `alembic revision --autogenerate` refuses a database that is not at head
  ("Target database is not up to date.").
- **`render_item` hook** in `env.py` that adds `import registry` for the spike's `XID8` type
  (side finding F2); without it every migration containing an `xid8` column failed with
  `NameError: name 'registry' is not defined`. It is active in all three configurations.
- **Rows vs DDL outside migrations.** A state's `after` statements are rows (only in `public`);
  `world` statements are DDL run outside migrations (the partitions), applied in `public` and,
  cumulatively, in every later reference schema, because a maintenance job's partitions persist.
  For states with `world` DDL the second autogenerate runs twice: before and after it.
- **Bugs fixed in the spike's own extension** before the final run (the final numbers are from
  the fixed code; the first run is kept in `results/run1-*.txt`): Alembic has no renderer for
  `RenameTableOp` (F3), and the rename rewrite first put the column renames last in the downgrade,
  which failed with `UndefinedColumn: column "user_id" referenced in foreign key constraint does
  not exist`. Both are findings about what a rename rewrite must do (item 1).
- A probe P3 was added: it checks one alternative for item 5 (a name filter), to state its cost
  from evidence; it does not choose it.

**Recording.** For every item: the generated migration bodies, the second autogenerate, the
catalog rows that show the item, the comparison with the reference schema and the downgrade
comparison, verbatim from `results/`. Where something does not round-trip, the write-up lists the
possible alternatives and their cost; it does not choose one.

## Observations

Database profile: fast (`make db-up`, port 26432). Every observation below was run; anything
inferred and not run is marked **(inferred)**.

Legend for the per-state table (from `results/summary.md`, final run): *ops* = the revision
autogenerate wrote contains operations; *2nd* = the second autogenerate after `upgrade`
(`EMPTY` / `OPS`; two values = before / after the DDL run outside migrations); *ref* = catalog
of `public` vs the same declaration created directly; *down* = catalog after `downgrade -1` vs
the snapshot taken after the previous upgrade.

### Item 1 - `renamed_from`

**Stock Alembic (H1 holds: a rename is drop+add).** Column rename, verbatim:

```
op.add_column('users', sa.Column('contact_email', sa.String(length=200), nullable=False))
op.drop_column('users', 'email')
```

With a row in the table, `upgrade` failed: `NotNullViolation: column "contact_email" of relation
"users" contains null values`; the same for 1c (`order_no`) and 1d (`customer_id`). On a nullable
column the same migration would succeed and drop the values **(inferred)**. Table rename: the
revision was `create_table('customers', ...)`, `drop_table('users')`, then the foreign-key swap,
and `upgrade` failed: `DependentObjectsStillExist: cannot drop table users because other objects
depend on it` (the drop comes before the FK swap). The hint leaks into the migration as
`info={'renamed_from': 'users'}` on `create_table`.

**With the rewrite (`baseline`; `ckplugin` differs only in 1d).**

| Sub-case | ops | 2nd | ref | down | Row kept |
|---|---|---|---|---|---|
| 1a column `email -> contact_email` | rename | EMPTY | 2 diffs (NOT NULL name) | MATCH | yes |
| 1b table `users -> customers`, referenced by `orders.user_id` | rename + FK swap | **OPS** | 12 diffs | MATCH | yes |
| 1c `number varchar(20) -> order_no varchar(40)` | rename + type | EMPTY | 2 diffs (NOT NULL name) | MATCH | yes |
| 1d `user_id` (FK + index) `-> customer_id`, `quantity` (CHECK) `-> qty` | renames + drop/create index and FK (+ CHECK with ckplugin) | EMPTY | 6 diffs (`baseline`) / 4 (`ckplugin`) | MATCH | yes |
| 1e hint left in code: next autogenerate, and a later revision adding `nickname` | - | EMPTY | as 1a | MATCH | yes |

1a, verbatim:

```
upgrade:   op.alter_column('users', 'email', existing_type=sa.VARCHAR(length=200),
                           new_column_name='contact_email', existing_nullable=False)
downgrade: op.alter_column('users', 'contact_email', existing_type=sa.VARCHAR(length=200),
                           new_column_name='email', existing_nullable=False)
probe SELECT id, contact_email, name FROM users: [(UUID('01900000-...-000000000001'), 'a@example.com', 'A')]
```

1c emitted the same `alter_column` with `type_=sa.String(length=40)` as well; the value `A-1`
survived. 1d, verbatim (`baseline`):

```
op.alter_column('orders', 'user_id', ..., new_column_name='customer_id', ...)
op.alter_column('orders', 'quantity', ..., new_column_name='qty', ...)
op.drop_index(op.f('ix_orders_user_id'), table_name='orders')
op.create_index('ix_orders_customer_id', 'orders', ['customer_id'], unique=False)
op.drop_constraint(op.f('fk_orders_user_id_users'), 'orders', type_='foreignkey')
op.create_foreign_key(op.f('fk_orders_customer_id_users'), 'orders', 'users', ['customer_id'], ['id'])
```

Under `ckplugin` the CHECK is also re-created under its new name
(`op.drop_constraint(op.f('ck_orders_quantity'), ...)`, `op.create_check_constraint('ck_orders_qty',
'orders', 'qty > 0')`); under `baseline` PostgreSQL rewrote the CHECK body to `CHECK ((qty > 0))`
but its name stays `ck_orders_quantity`. The index and the foreign key are **dropped and
re-created** (an index build and an FK validation), not renamed.

1b, verbatim:

```
upgrade:   op.rename_table('users', 'customers')
           op.drop_constraint(op.f('fk_orders_user_id_users'), 'orders', type_='foreignkey')
           op.create_foreign_key(op.f('fk_orders_user_id_customers'), 'orders', 'customers', ['user_id'], ['id'])
second autogenerate:
           op.drop_constraint(op.f('uq_users_email'), 'customers', type_='unique')
           op.create_unique_constraint(op.f('uq_customers_email'), 'customers', ['email'])
catalog vs reference: pk_users (expected pk_customers), uq_users_email (uq_customers_email),
           users_id_not_null / users_email_not_null (customers_*_not_null), and their indexes
```

Every name derived from the table name stays: the primary key (Alembic never compares primary
key names), the unique constraint (the rewrite's second pass compares under the old name, so the
naming convention resolves to the old name and the next autogenerate proposes the rename as
drop+create), and PostgreSQL 18's NOT NULL constraints.

The "2 diffs" of 1a and 1c are PostgreSQL 18 NOT NULL constraints (`contype = 'n'`), named
`<table>_<column>_not_null` at creation: `users_email_not_null` keeps its name after the column is
renamed (`'NOT NULL contact_email'`), while a fresh table would have `users_contact_email_not_null`.
Alembic does not reflect these names; the same happens with a hand-written `RENAME COLUMN`.

**What the rewrite had to do (H9 holds).** Probe P2, naive rewrite with stock operations:

```
-- column rename: upgrade [['alter_column(users.email, new_column_name=contact_email)']]
   reverse(): [['alter_column(users.email, new_column_name=None)']]
-- table rename: upgrade ['rename_table(users -> customers)', ['DropConstraintOp', 'CreateForeignKeyOp']]
   reverse(): NotImplementedError NotImplementedError()
```

`AlterColumnOp.reverse()` drops `modify_name`, so a naive downgrade would silently not rename
back; `RenameTableOp` has no `reverse()` and no autogenerate renderer (F3). The working rewrite
(`ext.py`, about 150 lines) needed: its own `RenameColumnOp` / `RenameTableOp` subclasses with a
`reverse()`, a renderer for the table rename, a second `produce_migrations` pass comparing the
database's old table with the declared table under the old name, and **renames first in both
directions** - in the downgrade too, because the stock reverse puts the rename after the
constraint operations that refer to the old column name (the first run failed there:
`UndefinedColumn: column "user_id" referenced in foreign key constraint does not exist`). A
foreign key follows a renamed table by OID, so renaming first keeps the other tables' FK swaps
valid in both directions.

### Item 2 - `Check` declared with a lambda (and item 6's column-to-column CHECK)

The lambda `Order.total.path(Money.amount) >= Decimal(0)` becomes
`sa.CheckConstraint('total_amount >= 0', name='ck_orders_total_amount')` inside `create_table`;
PostgreSQL stores `CHECK ((total_amount >= (0)::numeric))`. Creation passes criteria 1 and 2 in
every configuration.

| Config / naming | S1 add `allocated <= quantity` | S2 change `>= 0` to `> 0` | S3 remove |
|---|---|---|---|
| `stock`, `baseline` (both namings) | not detected (revision `pass`) | not detected | not detected |
| `ckplugin`, `columns` | detected, EMPTY, MATCH | **not detected**, catalog keeps `>= (0)::numeric` | detected |
| `ckplugin`, `hash` | detected, EMPTY, MATCH | detected as drop+add, EMPTY, MATCH | detected, EMPTY, MATCH |

H2 holds for Alembic's defaults. H7 holds: with `checkconstraint_byname`, a changed expression
under an unchanged name is not seen (Alembic's `compare_check_constraint` returns `Equal`). With
names derived from the declared expression, the change becomes a new name, verbatim:

```
op.drop_constraint(op.f('ck_orders_8086d863'), 'orders', type_='check')
op.create_check_constraint('ck_orders_856905de', 'orders', 'total_amount > 0')
downgrade: op.create_check_constraint(op.f('ck_orders_8086d863'), 'orders', 'total_amount >= 0::numeric')
```

The downgrade re-creates the old CHECK from the reflected text, which PostgreSQL normalized
(`>= 0::numeric`); the catalog after the downgrade matched. "down MATCH" in the `stock` and
`baseline` rows is trivially true: those revisions were empty.

### Item 3 - `version` trigger

**Stock Alembic (H3 holds).** The revision creates the `version` column and nothing else; the
catalog lacks `platina_version_orders` and `platina_bump_version`; the body change (S2) gives an
empty revision.

**Alembic's own extension points (no new dependency).** `ext.py`, about 190 lines: five custom
operations (`create/replace/drop_version_function`, `create/drop_version_trigger`) registered with
`Operations.register_operation`, implemented with `Operations.implementation_for`, rendered with
`renderers.dispatch_for`, and a comparator registered through the Alembic 1.18+ `Plugin` API
(`platina.version_trigger`) at two priorities: drops and replacements `FIRST` (before table and
column operations), creations `LAST` (after the tables exist). It reads `pg_proc.prosrc` and
`pg_trigger` (`tgname LIKE 'platina_version_%'`) in `current_schema()`.

| State | ops (verbatim) | 2nd | ref | down |
|---|---|---|---|---|
| S0 `orders` versioned | `create_table` x2, `op.create_version_function(body=...)`, `op.create_version_trigger('orders', 'platina_version_orders')` | EMPTY | MATCH | MATCH |
| S1 `users` gains `version_column()` | `op.add_column('users', ... 'version' ...)`, `op.create_version_trigger('users', 'platina_version_users')` | EMPTY | MATCH | MATCH |
| S2 body changed | `op.replace_version_function(body=<new>, old_body=<old>)` (downgrade swaps them) | EMPTY | MATCH | MATCH |
| S3 `orders` loses it | `op.drop_version_trigger('orders', ...)`, `op.drop_column('orders', 'version')` | EMPTY | MATCH | MATCH |
| S4 `users` loses it (function unused) | `drop_version_trigger`, `op.drop_version_function(body=...)`, `drop_column` | EMPTY | MATCH | MATCH |

What it does not cover (not run): a trigger whose definition changes other than by name or
function body (timing, events) is not compared; a table rename with a versioned table (the
trigger name contains the table name, and the drop runs `FIRST`, before the rename) was not
exercised.

### Item 4 - expression and partial indexes

The declarations rendered as
`op.create_index('ix_users_email', 'users', [sa.literal_column('lower(email)')], unique=True)`,
`op.create_index('ix_orders_user_id_created_at', 'orders', ['user_id', sa.literal_column('created_at DESC')], ...)`
and `op.create_index('ix_orders_created_at', 'orders', ['created_at'], ..., postgresql_where=sa.text("status = 'pending'"))`.
Criterion 1 passed in every configuration: **no false diff** from PostgreSQL's expression
normalization (H4 does not hold for Alembic 1.20.1: `PostgresqlImpl.compare_indexes` strips
casts, quotes and parentheses before comparing).

| Change (same name under `columns`) | `columns` naming | `hash` naming |
|---|---|---|
| S1 `lower(email) -> lower(btrim(email))` | detected (drop + create `ix_users_email`), EMPTY, MATCH | detected, EMPTY, MATCH |
| S2 `WHERE status = 'pending' -> 'paid'` | **not detected**; catalog keeps `WHERE (status = 'pending'::text)` | detected (new name), EMPTY, MATCH |
| S3 `created_at DESC -> created_at` | detected, EMPTY; catalog differs only by S2's stale index | detected, EMPTY, MATCH |

H8 holds: a `WHERE` change under the same name is invisible. Every downgrade matched (the
reverse re-creates from the reflected text, e.g. `lower(email::text)`). Any index change is a drop
and a create (no `CONCURRENTLY`).

### Item 5 - framework internal tables

The five tables render with `postgresql_partition_by='RANGE (id)'` / `'RANGE (created_at)'` and a
composite primary key `(created_at, xid, seq)` on the outbox log; the `xid8` columns render as
`registry.XID8()` (F2).

- **Criterion 1 holds before partitions exist**: second autogenerate EMPTY, catalog MATCH.
- **H5 holds.** After three partitions are created outside migrations (`PARTITION OF ... FOR
  VALUES FROM ... TO ...`), the same autogenerate proposes, verbatim:
  ```
  op.drop_table('platina_outbox_p20261126')
  op.drop_table('platina_run_claim_p0')
  op.drop_table('platina_outbox_p20261125')
  ```
  and the next real revision (S1: a column and an index on the outbox) **contains these drops**
  next to the intended `add_column` / `create_index`; applying it dropped the partitions (empty
  here; with data, their rows would go with them **(inferred)**). Catalog vs reference: 39
  differences, all of them the partitions' tables, columns, constraints and indexes.
- **The downgrade cannot restore them.** Alembic reflects a partition as an inheritance child and
  renders `op.create_table('platina_outbox_p20261125', ..., sa.Column('xid', sa.NullType(), ...),
  ..., postgresql_inherits=('platina_outbox',))` - no `PARTITION OF`, no bounds, and
  `sa.NullType` for `xid8`. The downgrade failed with
  `WrongObjectType: cannot inherit from partitioned table "platina_run_claim"`; in an earlier run,
  where the drops came out in another order, it failed first with
  `AttributeError: module 'sqlalchemy' has no attribute 'NullType'` (the order of these drops is
  not stable across runs).
- **Partitioning is not compared**: S2 (dry run) changed `run_claim` from `RANGE (id)` to
  `HASH (id)` and autogenerate was EMPTY.
- **`xid8` is not reflected**: every run that reflects these tables warns
  `SAWarning: Did not recognize type 'xid8' of column 'xid'`; the reflected type is `NullType`.
  That a type change of an `xid8` column would then go unnoticed is **(inferred)**, not run.
- **H6 holds** (probe P1): `PRIMARY KEY (xid, seq)` and `UNIQUE (xid, seq)` on a table partitioned
  by `created_at` both fail with `FeatureNotSupported: unique constraint on partitioned table must
  include all partitioning columns` / `DETAIL: PRIMARY KEY constraint on table "outbox" lacks
  column "created_at" which is part of the partition key.` For `run_claim` (partitioned on its key
  `id`) the primary key is the partition key and nothing conflicts.
- Probe P3 (an alternative, not chosen): an `include_name` hook that hides tables with
  `pg_class.relispartition` made the S0 autogenerate EMPTY and S1's autogenerate exactly
  `[('add_column', 'headers'), ('add_index', 'ix_platina_outbox_aggregate_id')]`. The hook needs
  a catalog query per run (SQLAlchemy's reflection does not tell partitions apart), and children
  are then never compared at all.

### Item 6 - carried over from spike 0002

- **Composite unique key (X16)** with `Meta.uniques = (Unique(lambda: (Stock.warehouse_id,
  Stock.variant_id)),)`: `op.create_unique_constraint('uq_stock_warehouse_id_variant_id', 'stock',
  ['warehouse_id', 'variant_id'])` when added to an existing table, `op.drop_constraint(...)` when
  removed; EMPTY, MATCH and MATCH in all three configurations.
- **Column-to-column CHECK** `Stock.allocated <= Stock.quantity`: rendered `'allocated <=
  quantity'`, stored `CHECK ((allocated <= quantity))`; it behaves exactly as item 2 (S1 and S3 of
  that table).

### Side findings

- **F1 - `checkconstraint_byname` mutates the declared `MetaData`.** Each time Alembic rebuilds a
  CHECK from the declared expression (`produce_migrations`, `reverse()`, rendering), SQLAlchemy
  attaches the new `CheckConstraint` to the declared table, because the expression references that
  table's columns. Counted on one `Order` table: 1 before, 2 after `produce_migrations`, 3 after
  the rewrite's second pass, 4 after rendering. A `MetaData` reused in the same process then fails
  in `create_all` with `DuplicateObject`. A `platina migrate` that builds `MetaData` once and also
  uses it for anything else in the same process would hit this.
- **F2 - user-defined types render without an import**: `sa.Column('xid', registry.XID8(), ...)`
  with no `import registry` in the migration (`NameError` at upgrade). The `render_item` hook (or
  `user_module_prefix` plus a template import) is needed for every type Platina defines.
- **F3 - no renderer for `RenameTableOp`**: Alembic's autogenerate never emits it, so a rewrite
  that does gets `no dispatch function for object: <...RenameTableOp ...>` until it registers one.
- **F4 - NOT NULL constraint names (PostgreSQL 18)** do not follow column or table renames (item
  1) and are invisible to Alembic.
- **F5 - the `checkconstraint_byname` plugin is young**: opt-in, and renamed in Alembic 1.19.2
  from `alembic.autogenerate.checkconstraint_byname` to `alembic.ext.checkconstraint_byname`
  (`runtime/plugins.py`, `_legacy_plugin_names`, "see #1859").

### Third-party PG object support: `alembic_utils` (read only, not installed or run)

Read from its README, documentation, `pyproject.toml`, `src/alembic_utils/replaceable_entity.py`,
`simulate.py`, `pg_trigger.py`, `reversible_op.py` and issues #41, #79, #166, #169 on GitHub
(`olirice/alembic_utils`, default branch `master`), on 2026-11-25. Nothing below was executed.

| | Spike extension (run) | `alembic_utils` (read only) |
|---|---|---|
| Objects | the `version` function and its triggers only | `PGFunction`, `PGTrigger`, `PGView`, `PGMaterializedView`, `PGExtension`, `PGPolicy`, `PGGrantTable` |
| Change detection | function body text (`prosrc`) and trigger names | simulation: drops and re-creates the entity in a savepoint, reads the catalog definition (`pg_get_triggerdef` for triggers), compares whitespace-normalized text, rolls back |
| Trigger on a table created in the same revision | works (S0: `create_table` then `create_version_trigger`) | does not: the simulation needs the table to exist; issue #79 (open since 2022-01-28), maintainer: two migrations |
| Objects it does not own | ignored (only `platina_version_%`) | proposed for drop in every observed schema unless filtered (`include_name` / `include_object`, `entity_types`) |
| Downgrade of a change | stores the old body (`old_body=`) | stores the live definition (`RevertOp`) |
| Alembic hook | `Plugin` API (Alembic 1.18+) | the older global `comparators.dispatch_for("schema")` registry |
| Versions | Alembic 1.20.1, SQLAlchemy 2.1.9 | declares `alembic>=1.9`, `sqlalchemy>=1.4`, no statement about Alembic 1.18+ or SQLAlchemy 2.1; last release 0.8.8 (2025-04-10); issue #166 reports an empty `__init__.py` in 0.8.8 (not verified) |
| New dependency | none | `alembic_utils` plus `flupy`, `parse`; MIT |

## Verdict

| Item | Verdict | Criteria passed (1 create / 2 catalog / 3 change / 4 downgrade) | One-line reason |
|---|---|---|---|
| ① `renamed_from` | **partly** | Columns (1a, 1c, 1d, 1e): 1 and 4 pass; 3 passes on detection, an empty second autogenerate and kept rows, but its catalog part fails on the same names as 2; 2 fails on names only - columns, types, rows, FK and index are right, but PostgreSQL 18 NOT NULL constraint names (and in 1d the CHECK name without the plugin) keep the old name. Table (1b): 1, 4 pass; 3 fails its second autogenerate (convention-named unique constraint), 2 fails on every table-derived name | The `process_revision_directives` plan works for columns but needs its own downgrade, renderer and ordering; a table rename leaves names behind |
| ② lambda `Check` | **partly** | Defaults: 1, 2 on creation only, 3 fails (add, change, remove all invisible). With `checkconstraint_byname`: add/remove pass, change fails under a stable name; with expression-derived names all four pass | Holds only with an opt-in plugin **and** names that change with the expression |
| ③ `version` trigger | **holds** (with the spike's extension; **does not hold** with Alembic alone) | All four, every sub-case, with custom operations + `Plugin` comparator; none of 2 and 3 with stock Alembic | Alembic's own extension points suffice; no third-party package needed. Drift is detected by trigger name and function body only: a same-named trigger redefined by hand (`AFTER INSERT`) is not seen (Reproduction) - §6 calls this trigger the real safeguard for coexistence |
| ④ expression / partial indexes | **partly** | 1, 2, 4 pass; 3 passes for expression and `desc()` changes, fails for a `WHERE`-only change under the same name; with expression-derived names all four pass | No false diffs; the partial-index predicate is not compared |
| ⑤ internal tables (partitions) | **does not hold** | 1 passes only before partitions exist; 3 drags partition drops into the next revision; 4 fails (downgrade re-creates partitions as inheritance children with `sa.NullType`); partitioning itself is not compared; `xid8` is not reflected | Partitions created outside migrations are proposed for drop, and Alembic cannot express or restore them |
| ⑥ X16 composite unique / column-to-column CHECK | **holds** / as ② | Unique: all four in every configuration. CHECK: as item 2 | - |

Hypotheses: H1 holds, H2 holds, H3 holds, **H4 does not hold** (no false diffs, expressions are
compared), H5 holds, H6 holds, H7 holds, H8 holds, H9 holds.

**Consequence for the design.** Section 8.5's decision to hand DDL and migrations to SQLAlchemy
Core and Alembic is not refuted - columns, tables, foreign keys, composite unique keys and
expression indexes round-trip, and Alembic's extension points carried the `version` trigger
without a new dependency. But "the registry is converted to `MetaData` to use Alembic
autogenerate" is not enough on its own for four of the five risks; `platina migrate` needs code
of its own (the rename rewrite with its downgrade; the trigger operations and comparator; a
`render_item` hook) and three choices the design does not make yet. None is decided here; each
alternative is listed with its cost:

1. **Names that depend on the table or the expression** (items 1, 2, 4).
   - a. Names derived from the declared expression for CHECKs and indexes, plus
     `checkconstraint_byname`: everything is detected; cost: opaque names (`ck_orders_856905de`),
     every expression change is a drop and a create (a full validation scan for a CHECK, an index
     build), a dependency on a plugin that is opt-in and was renamed in 1.19.2, and names that
     change whenever the hashed text changes - a column rename (the hash covers the column name;
     the Reproduction saw a stale hash-named CHECK in 1d) and, if the hash is taken over rendered
     SQL, a Platina or SQLAlchemy upgrade that renders differently would rebuild every CHECK and
     index.
   - b. Readable names, plus Platina's own comparators for CHECK bodies and index predicates;
     cost: comparing PostgreSQL's normalized text (`(0)::numeric`, `'pending'::text`) - either
     normalization rules of our own or a simulation in a savepoint as `alembic_utils` does.
   - c. Leave changes undetected and require hand-written migrations for them; cost: silent
     drift, the failure mode this spike exists to catch.
   - d. Readable names, with the expression's hash stored in `COMMENT ON CONSTRAINT` / `COMMENT ON
     INDEX` and checked by a small comparator; cost: a comparator and comment handling of our own,
     comments that hand-written DDL can lose (not run).
   - e. Across choices 1 and 3: a shadow-schema catalog diff as a completeness check - create the
     declared state in a scratch schema and compare the `pg_get_*def` output with the database,
     which is what this spike's reference comparison did and it caught everything Alembic missed.
     Alembic still generates the operations; section 8.5 already needs a temporary PostgreSQL for
     codegen. Cost: a check that reports drift but does not write the migration, and a scratch
     schema per run.
   - For table renames in addition: the rewrite emits `ALTER ... RENAME` for every name derived
     from the table (primary key, unique, indexes, NOT NULL constraints); cost: more rewrite code
     that has to know PostgreSQL 18's NOT NULL naming. Or accept stale names and keep names out of
     drift checks; cost: the catalog no longer says what the code says.
2. **Renames of indexed or referenced columns** re-create the index and the foreign key. Turning
   matching drop/create pairs into `ALTER INDEX ... RENAME` / `ALTER TABLE ... RENAME CONSTRAINT`
   in the rewrite avoids the rebuild; cost: more rewrite code. Or accept the rebuild; cost: lock
   and time on large tables.
3. **Partitioned internal tables** (item 5) - the decision is tracked in #63.
   - a. An `include_name` filter on `pg_class.relispartition` or on a partition name pattern
     (probe P3: works for the cases run); cost: partitions are never compared, and the partition
     scheme and `xid8` stay invisible - each needs its own comparator or type registration.
   - b. Internal tables outside Alembic: Platina creates and evolves them with its own DDL; cost: a
     second schema path to maintain and test.
   - c. Unpartitioned internal tables with deletion-based retention; cost: the bloat and vacuum load
     that partition drops avoid (assumption A2 is the maintainer's experiment-only choice). Which
     of 3c and partitioning is cheaper is the section 9.5 measurement "Write amplification and
     cleanup cost of the run ID and job tables".
   - d. Partitions declared in the registry with custom operations; cost: SQLAlchemy has no
     `PARTITION OF`, and time-based partitions are created by a job, not by a static declaration.
4. **`version` triggers**: the spike's extension (about 190 lines, run) or `alembic_utils`
   (read only: wider object coverage, but a trigger on a table created in the same revision needs
   two migrations, it proposes drops for objects it does not own unless filtered, it uses the
   older comparator registry and states no support for Alembic 1.18+ / SQLAlchemy 2.1).

No ADR is proposed: the spike refutes no section 8 decision (partitioning of the internal tables
was an experiment-only assumption, A2), and it chooses none of the alternatives. The architect
review agreed and flagged that choosing 3b (internal tables outside Alembic, an exception to
section 8.5; #63), a naming rule (1a or 1b/1d; #25) or `alembic_utils` (a dependency; #25) will
each need an ADR when it is picked.

### Input for #25 (migration implementation) and #63 (internal tables)
Posted as a comment on #25 (2026-11-26). In short: the rename rewrite with its own reverse and
ordering; the trigger operations and comparator; a `render_item` hook for Platina's types; a fresh
`MetaData` per autogenerate (F1); decisions 1 and 2 above. Decision 3 (the internal tables'
schema path and partitioning) is issue #63.

## Reproduction

- **Who:** the `pg-researcher` sub-agent, 2026-11-25, in this worktree, database
  `spike0004_repro` on the fast profile (created, then dropped: `pg_database` afterwards
  `['platina', 'postgres', 'spike0004', 'template0', 'template1']`).
- **What it was given:** this write-up cut before Observations (Question, A1-A7, H1-H9, Setup,
  Method without "Changes to the method") plus neutral harness facts (fresh `MetaData` per call,
  `produce_migrations` after a downgrade, the three configurations). It did not read the
  Observations, the Verdict, `results/`, the commit bodies, or the author's `run.py`,
  `scenarios.py`, `catalog.py`, `probes.py`. It imported only the subject under test
  (`registry.py`, `ext.py`, `alembic_env/`) and wrote its own driver, scenario declarations and
  catalog checks: `spikes/0004-alembic-round-trip/repro/` (`repro_harness.py`, `repro_states.py`,
  `repro_run.py`, `repro_probes.py`; raw output in `repro/out/`, git-ignored).
- **Commands:**
  ```
  uv run python spikes/0004-alembic-round-trip/repro/repro_run.py setup
  uv run python spikes/0004-alembic-round-trip/repro/repro_run.py <item> <stock|baseline|ckplugin> <columns|hash>
  uv run python spikes/0004-alembic-round-trip/repro/repro_probes.py
  uv run python spikes/0004-alembic-round-trip/repro/repro_run.py teardown
  ```
  21 runs (items 1-6 across configurations and namings, plus `1bx` for the case below) and the
  probes. Its declarations differ from the author's (other table and column names, e.g.
  `customers -> clients`, `name -> full_name`, `code -> sku`), which is intended.

**Its results per item** (C1 create, C2 catalog, C3 change, C4 downgrade):
- **Item 1.** Stock: C3 fails in every sub-case - NOT NULL columns with a row give
  `NotNullViolation`; it also ran the nullable variant: the upgrade succeeds and the value is lost
  (`SELECT full_name` -> `[(None,)]`), a table rename loses the row (`[]`), and in 1d PostgreSQL
  drops the CHECK with its column, Alembic never re-adds it, and the second autogenerate is still
  `EMPTY`. With the rewrite: 1a, 1c, 1e pass C1/C3/C4 with rows kept
  (`op.alter_column('customers', 'name', ..., new_column_name='full_name')`, `[('Ada',)]`); C2 is
  partial on PostgreSQL 18 NOT NULL names. 1d: C3 and C4 pass (index and FK dropped and
  re-created under new names); C2 fails under `baseline` (the CHECK keeps a stale name - with
  `hash` naming too, as the hash covers the column name) and is partial under `ckplugin` (the
  CHECK is re-created). 1b: first run with no unique column passed C3; at the author's request it
  ran `1bx` (a `unique=True` column and an incoming FK): **the second autogenerate is not empty**
  (`op.drop_constraint(op.f('uq_customers_email'), 'clients', type_='unique')`,
  `op.create_unique_constraint(op.f('uq_clients_email'), 'clients', ['email'])`), identical under
  `baseline` and `ckplugin`; C2 fails on `pk_customers`, `uq_customers_email` and the NOT NULL
  names; the FK is right (`FOREIGN KEY (customer_id) REFERENCES clients(id)`), the row is kept,
  C4 MATCH; applying the leftover in a third revision settles everything except the PK and NOT NULL
  names. It changed its own 1b row from pass to partial.
- **Item 2.** `baseline` (both namings): add, change and remove all generate `pass`.
  `ckplugin`/`columns`: add and remove detected, change under the same name not.
  `ckplugin`/`hash`: all four pass (`drop_constraint('ck_orders_0ccbe12f')` +
  `create_check_constraint('ck_orders_9e486203', 'orders', 'quantity >= 0')`).
- **Item 3.** Stock: no trigger or function; an `UPDATE ... RETURNING version` gives `[(1,)]`.
  With the extension: all four pass in every state; the bump works (`[(2,)]`), V2 raises
  `version went backwards on orders`, and the function's md5 returns to V1 after the downgrade.
  A same-named trigger redefined by hand as `AFTER INSERT` is not detected (`EMPTY`).
- **Item 4.** No false diff (`lower((email)::text)` in the catalog, second autogenerate `EMPTY`);
  expression and `desc` changes detected; a `WHERE`-only change under the same name generates
  `pass`; with `hash` naming all four pass.
- **Item 5.** Before partitions all four pass. After partitions created outside migrations, the
  next revision prepends `drop_table` for each partition (and `drop_index` for their indexes).
  With an index on the parent the upgrade fails (`cannot drop index outbox_log_2026_11_topic_idx
  because index ix_outbox_log_topic requires it`); without one it succeeds and **drops the
  partitions with their rows** (`count(*)` 1 -> 0). The downgrade fails (`baseline`:
  `AttributeError: module 'sqlalchemy' has no attribute 'NullType'`; `stock`: `cannot inherit
  from partitioned table "run_claim"`). `RANGE (id) -> HASH (id)`: `EMPTY`. A primary key or
  unique constraint without the partition key is generated without warning and fails at upgrade
  (`unique constraint on partitioned table must include all partitioning columns`).
- **Item 6.** The composite unique key and `allocated <= quantity`: all four pass (the CHECK
  change itself is covered by item 2).
- **Hypotheses:** H1, H2, H3, H5, H6, H7, H8, H9 hold; H4 does not hold. H7, H8 and H9 were also
  checked against the installed source objects (`"compare_check_constraint" in
  vars(PostgresqlImpl)` is `False`; `_dialect_options` of a partial index returns `()`;
  `AlterColumnOp(..., modify_name='new').reverse()` has `modify_name` `None`).
- **Not run by it:** `ckplugin` for items 3-5, `stock` for items 2 and 6, `hash` for items 3 and 5;
  `alembic_utils` and the `include_name` filter (outside the subject).

**Agreement:** agree. Every item verdict and every hypothesis matches. It ran two things the
author only inferred (nullable renames losing values; partition rows dropped) and found two the
author did not run (the silent CHECK loss under stock 1d; the hand-redefined trigger going
undetected); none changes a verdict. The one difference in its first report (1b's second
autogenerate) came from a table without a unique column; on the author's shape it reproduced the
author's result.
