# Architecture (current state)

This document describes what exists **now**. The target architecture is
[`design/design.md`](design/design.md) section 10; this file catches up with it package by
package as code lands. Decisions taken after the design document: [`adr/`](adr/).

## Status

The first runtime code is the exception hierarchy, `platina.core.errors` (design section 10.12,
ADR-0006). Everything else is still the package skeleton below, with one docstring per package
that states its contract, so the layer contracts and guards are enforced from the first line of
code.

## Zones and layers

```
cli | integrations | testing          shell   entry points, FastAPI glue, user test kit
app                                   shell   App, seal() orchestration, run/query (ADR-0001)
runners | outbox | migrate | codegen  shell   drive the engine; event log consumers; schema tooling (extra); TypedSQL
drivers                               shell   psycopg 3.3+ (pool, pipeline, COPY, SQLSTATE mapping)
sql                                   sans-I/O  compiler, dialects (PostgreSQL)
core                                  sans-I/O  schema, expr, snapshot, changes, plan, planner, engine
```

Imports point downwards only (`|` separates independent siblings). The contract is exhaustive:
every direct child of `platina` must appear in it. Public re-exports live in
`platina/__init__.py`, which belongs to no layer and re-exports only from `core`, `sql` and
`app` (ADR-0001). It re-exports so far the exception hierarchy and `SourceLocation` from
`platina.core.errors` (`__all__`).

| Package | Zone | Contract |
|---|---|---|
| `platina.core.*` | sans-I/O | Pure and immutable: imports only the standard-library allowlist; no I/O, event loop, clock, randomness or `async`. The engine yields Commands. Time arrives as the `Now` parameter, the jitter's randomness as an engine argument, new IDs from an injected ID source (ADR-0002). |
| `platina.core.errors` | sans-I/O | The exception hierarchy of design section 10.12 (`PlatinaError` and its subclasses, `ModuleBoundaryError` under `SealError`) and `SourceLocation`. The bottom of the core: imports nothing from `platina`. Keyword-only read-only fields, one rendering layout for `str(exc)`, pickle/copy through one `__reduce__` (ADR-0006). Raise sites and SQLSTATE mapping come with later issues. |
| `platina.sql.*` | sans-I/O | Renders SQL from the immutable AST; never connects. |
| `platina.app` | shell | App (configuration, registry), seal orchestration (core checks, then load-plan compilation via `sql`), `run` / `query` (ADR-0001). |
| `platina.drivers` | shell | The only importer of psycopg / psycopg_pool. |
| `platina.runners` | shell | Executes engine Commands. Async runner (anyio) is the source; the sync runner is generated from it. |
| `platina.outbox` | shell | Event log readers, job workers and dispatchers, projection consumers. |
| `platina.migrate` | shell, extra | The only importer of SQLAlchemy / Alembic (`platina[migrate]`). |
| `platina.codegen` | shell | TypedSQL inference, `platina pull`, contract generation. |
| `platina.testing` | shell | User test kit and the dialect compliance suite. |
| `platina.integrations` | shell | Web framework integrations. |
| `platina.cli` | shell | The `platina` command. |

## Enforcement

| What | Where |
|---|---|
| Layer order between packages | import-linter, `[tool.importlinter]` in `pyproject.toml` |
| External modules and calls per zone (A101-A106; the core imports only `CORE_ALLOWED`) | `tools/guards/archlint.py` |
| Public type surface under pyright and mypy | `tools/typetests.py` over `tests/typing/` |
| Unit tests on free-threaded CPython with the GIL off, each test on several threads (ADR-0002's counter included, with an unsafe control counter that must race; no silent single-thread fallback, no warnings) | `tools/freethreaded.py` (`make test-unit-ft`, CI) |
| Everything else in the design invariants | review (`arch-guardian`, `code-reviewer`, `type-reviewer`) |

## ADRs

| ADR | Status | Shapes |
|---|---|---|
| [0001](adr/0001-assembly-package-and-seal.md) assembly package and seal | Accepted | `platina.app`, the layer contract, where seal's steps live, the executor `outbox` receives, root re-exports (`core`, `sql`, `app` only) |
| [0002](adr/0002-injected-id-source.md) new IDs from an injected source | Accepted | the ID source of entity creation (`Order(...)`) (installed by the engine, never replaced by a nested direct call), the version-8 fallback sequence for direct calls and stubs, guard A106 |
| [0003](adr/0003-entity-base-class.md) entities declared with an `Entity` base class and created with `Order(...)` | Accepted | entity declaration (`class Order(Entity, table=...)`), creation by the keyword constructor (no `new`), `frozen_default=True` (type level); runtime value equality over columns only with a type-plus-primary-key hash (#54); the parent key of an owned child (`parent_fk`) is not a constructor parameter (#49) |
| [0004](adr/0004-owner-typed-columns-and-embedded-paths.md) columns carry their owner; embedded paths are `Order.total.path(Money.amount)` | Accepted | `Column[Owner, T]` with fixed variance, owner checks by type where the receiver fixes the owner (queries when built, the rest at seal), value-object fields declared `Col[...]`, increments through paths; comparison operands (a value of exactly `T`, a column of the same value type through a separate overload, `Pred[O | O2]`; no `T | Column[O, T]` parameter, #51) |
| [0005](adr/0005-hot-rows-under-serializable.md) `lock="for_update"` is not an escape hatch from serialization failures | Accepted | the hot-row text of the design (two kinds of `40001`; REPEATABLE READ + `version` escapes only the read/write-dependency kind; `lock=` counts as "fail early"; 9.2 measured that it does not reduce the failures; `lock=` and the hot-row approach are decided in #64) |
| [0006](adr/0006-exception-fields-and-rendering.md) exception fields are typed keyword-only values; `str(exc)` renders them in a fixed layout | Accepted | `platina.core.errors`: field types (`entity: type[object]`, `usecase`/`field: str`, `SourceLocation`), `details` for extra lines, the rendering order (`Location:`, details, `Fix:`), the pickle/copy guarantee, required `DatabaseError.sqlstate` with the driver exception as `__cause__` |
| [0007](adr/0007-ever-increasing-entity-keys.md) ever-increasing entity keys and SSI false conflicts | Proposed | the default entity key (`pk(generated=...)`, design 4.2) - proposes a random UUID default, to be decided after the measurements of #65, because uuid7 / sequence keys make reads of recent rows and inserts into the same index conflict under SERIALIZABLE (spike 0003) |
| [0008](adr/0008-run-timeout-budget.md) `timeout=` is one budget for the run; `57014` and the deadline raise `RunTimeout` | Accepted | the engine and the runners (#17, #22): the runner holds the deadline and sends the remaining time as `statement_timeout` per round trip before `COMMIT`; the engine turns an expired deadline or a pre-`COMMIT` `57014` into `RunTimeout` (never retried); `Begin` has no timeout; the commit outcome is decided by the failing statement's position; `RunTimeout` directly under `PlatinaError` (#61) |
| [0009](adr/0009-internal-tables-owned-by-the-core.md) the core owns the versioned SQL of the internal tables, in a dedicated schema | Accepted | where the DDL of `run_claim`, `run_result`, the outbox and job tables lives (sans-I/O core, not `platina.migrate`), no DDL at startup, the Alembic operation for `platina[migrate]`, `42P01` / `42703` / `42501` on any internal-table statement mapped to a `DatabaseError` naming the command or the grant; versioned steps as string constants in `platina.sql.dialects.postgresql`; partitioning and keys wait for #72 (#63) |
| [0010](adr/0010-writes-beyond-set.md) writes beyond `.set`: `insert`, `delete`, and owned rows only through their root | Proposed | the write verbs of `platina.core` (#13): `insert(entity, *children)` in the commit batch, `entity.delete()` with engine-issued cascade DELETEs of owned relations, `owns_many` / `Owned[...]` with no `owned=` flag, no write operations on relations that are not owned, the runtime rules for new / loaded / ref snapshots and for direct writes of owned children; seal's ownership checks and one-level ownership (#9); the cascade node and its edges in the planner (#15); `ForeignKeyViolation` (#18) |
