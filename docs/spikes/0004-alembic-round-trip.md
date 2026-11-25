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
(filled in when run)

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
uv run python spikes/0004-alembic-round-trip/run.py all > spikes/0004-alembic-round-trip/results/all.txt
uv run python spikes/0004-alembic-round-trip/run.py teardown       # drops spike0004
```

**Recording.** For every item: the generated migration bodies, the second autogenerate, the
catalog rows that show the item, the comparison with the reference schema and the downgrade
comparison, verbatim from `results/`. Where something does not round-trip, the write-up lists the
possible alternatives and their cost; it does not choose one.

## Observations
(filled in when run)

Database profile: fast (`make db-up`, port 26432).

## Verdict
(filled in when run)

## Reproduction
(filled in by pg-researcher from this write-up alone)
