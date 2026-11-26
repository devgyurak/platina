# ADR-0009: The core owns the versioned SQL of the internal tables, in a dedicated schema

- Status: Proposed
- Date: 2026-11-26
- Related: design sections 4.6 (internal append-only table rule), 7.7, 8.3, 8.5 ("Schema tooling"),
  9.3, 9.5, 9.6; issue #63 (direction decided 2026-11-26), #72 (run-ID table cleanup cost), #73,
  #32, #25; spike 0004 (`docs/spikes/0004-alembic-round-trip.md`, item 5, probe P3)

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- Every `app.run` INSERTs into `run_claim` as its first table statement (4.6), so the internal tables
  (`run_claim`, `run_result`, the outbox log, the job tables, the consumer and batch checkpoints)
  must exist before the first command, also in a core-only install without `platina[migrate]`.
- Design 8.5 hands DDL to SQLAlchemy Core and Alembic in the optional extra. Spike 0004 item 5:
  for these tables that does not round-trip - partitions created outside migrations are proposed
  for `drop_table`, the downgrade cannot re-create them, and the partition scheme and `xid8`
  columns are not compared. Whether the tables are partitioned is not known yet: it waits for the
  cleanup-cost measurements (#72 for the run-ID tables, #73 for the outbox log, #32 for the jobs).
- The maintainer chose option 3b of #63 on 2026-11-26 (direction only; the issue stays open): the
  core owns versioned SQL for these tables, there is no DDL at startup, and `platina[migrate]`
  users call it from their own Alembic history (the model of Oban's `Oban.Migrations.up(version:
  N)` and Procrastinate's SQL migrations shipped in the package).
- Fact checked for this ADR (Alembic 1.20.1, SQLAlchemy 2.1.9, PostgreSQL 18; a throwaway
  database, a schema `platina_internal` holding one table, an empty target `MetaData` for it):
  - With Alembic's defaults (`include_schemas=False`) autogenerate compares only the
    connection's default schema (`connection.dialect.default_schema_name`, PostgreSQL's
    `current_schema()`; `alembic/autogenerate/compare/schema.py`, `_produce_net_changes`). The
    table in `platina_internal` was not proposed for anything: `compare_metadata` returned `[]`.
  - With `include_schemas=True` the same table was proposed as `remove_table`; an `include_name`
    hook returning `False` for `type_ == "schema"` and that schema name made the result `[]`
    again.
  - **Condition:** when the dedicated schema *is* the default schema, it is compared even with
    the defaults, and a schema filter does not help (the default schema reaches the hook as
    `None`). This happened twice: with `search_path=platina_internal,public`, and - without
    touching `search_path` - with a schema named `platina` while connected as the role
    `platina`, because PostgreSQL's default `search_path` is `"$user", public`. Both proposed
    `remove_table` for the internal table.

## Decision
1. **The sans-I/O core ships the DDL of the internal tables as versioned SQL** (numbered,
   forward-only steps, each idempotent) plus a one-row version table, all in **one dedicated
   schema** rather than a reserved table-name prefix in the user's schema. The steps are Python
   string constants in `platina.sql.dialects.postgresql` (dialect-specific; reading `.sql` package
   files would be file I/O, which the core may not do), so no SQLAlchemy is needed to read or
   apply them. Every internal-table statement is schema-qualified. The schema name is open, with
   one constraint from the fact above: it must not be a likely role name (so not `platina`).
   - Each step and its version bump run in one transaction under an advisory lock, so two
     deploys applying at once are safe. The version table is updated only there; `app.run` never
     touches it, so it is outside the internal-table rule's SERIALIZABLE transactions.
   - Steps are expand/contract: each keeps the previous release's statements working, because
     old and new application instances share the schema during a rolling deploy.
   - The Alembic operation's downgrade does nothing to the internal schema (forward-only), and
     says so in the generated revision.
2. **Nothing runs DDL at `app.seal()` or startup.** It is applied by a command (core-only
   installs; a `platina` CLI command and the same as a function for tests - names open) or, for
   `platina[migrate]` users, by an Alembic operation the user's own revision calls ("internal
   schema to version N"), so there is one migration history. Platina's Alembic integration adds
   an `include_name` filter that excludes the dedicated schema, for projects that turn on
   `include_schemas`.
3. **No separate startup check.** The first table statement of every run, the claim INSERT,
   already touches an internal table. A `42P01` (undefined table), `42703` (undefined column) or
   `42501` (insufficient privilege, e.g. no `USAGE` on the schema) on **any** internal-table
   statement - the engine knows which statements those are, by position in the round trip - is
   mapped to a `DatabaseError` (SQLSTATE kept) whose message says the internal schema is missing,
   old or not granted, and whose `hint` names the command to run or the grant needed. The
   application role needs `USAGE` on the schema, `INSERT` on the tables a run writes and `SELECT`
   on `run_result` for the replay path; the apply command prints them. The version comparison
   (shipped version against the version table) is part of `platina check`, which accepts a
   database that is ahead by the steps of one release (a rolling deploy) and reports a dedicated schema that is the
   connection's default schema.
4. **Partitioning and the key shapes are not decided here: they wait for #72** (and #73 / #32
   for their tables). No internal-table DDL is shipped before #72 has measured the cleanup cost,
   because the partition key must be part of every unique key (PostgreSQL 18, "Partitioning";
   spike 0004 H6) and changing it later is a table rewrite.

## Consequences
- A core-only install can create and upgrade what `app.run` needs; `platina[migrate]` users keep
  one Alembic history. Unless the dedicated schema is the connection's default schema,
  autogenerate with Alembic's defaults never proposes dropping an internal table, whatever the
  partitions are, because it does not look at the schema at all.
- This is an exception to 8.5 ("DDL generation ... handed to SQLAlchemy Core and Alembic") for
  the internal tables only; entity tables are unchanged.
- The core holds SQL text for one dialect; a MySQL dialect will need its own versions.
- A missing schema is reported on the first run, not at startup - the price of keeping `seal()`
  free of database I/O. `platina check` in CI and deployment closes that gap for version skew.
- #22 (run IDs) has no table to run its integration tests against until #72 has measured and the
  first DDL step exists; #22 waits for #72.
- `platina pull` and the drift check (8.5) skip the dedicated schema by name; no prefix rule.
- Open, tracked in #63: the schema name, the command names, the version-table shape, and
  everything #72 decides (partitioning, keys, retention).

## Alternatives considered
- **3a - Alembic only, with an `include_name` filter** (spike 0004 P3): a core-only install has
  no way to create `run_claim`, and `xid8` columns and partitions stay outside what Alembic
  compares.
- **A reserved table-name prefix** (`platina_*`) in the user's schema: autogenerate sees the tables
  unless every project adds a name filter, and `pull` / drift need the same filter; a schema is
  excluded by Alembic's defaults.
- **DDL at startup** (pg-boss, Hangfire): application roles often lack DDL rights, and an implicit
  schema change is implicit I/O the design avoids.
- **3c - never partition / 3d - declare partitions in `MetaData`**: 3c decides #72 before it is
  measured; 3d needs a `PARTITION OF` construct SQLAlchemy does not have, and time partitions
  are created by a job, not a declaration.

## History
- 2026-11-26 - created (Proposed) from the maintainer's #63 direction (3b, dedicated schema
  preferred, no startup check, partitioning waits for #72) and the Alembic default-schema check.
- 2026-11-26 - amended after the architect review: steps are string constants in
  `platina.sql.dialects.postgresql`, schema-qualified; the version table, advisory lock,
  expand/contract steps and a no-op downgrade; `42P01` / `42703` / `42501` on any internal-table
  statement, with the grants the role needs; #22 waits for #72.
