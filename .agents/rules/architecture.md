---
description: Sans-I/O core vs shell, package layers and which external libraries each zone may import
paths:
  - "src/**"
---
# Architecture rules

Read `docs/architecture.md` once per session before touching `src/`, and the matching sections of
`docs/design/design.md` (section 10 for the internal architecture).

## Core principle
**Functional core, imperative shell** (design section 10.1). The library obeys the rule it imposes
on its users: the code that decides has no I/O, the code that does I/O decides nothing.

## Zones and layers (imports point downwards only - import-linter + `tools/guards`)
```
cli | integrations | testing          shell: entry points, framework glue, user test kit
app                                   shell: App, seal() orchestration, run/query (ADR-0001)
runners | outbox | migrate | codegen  shell: drive the engine, consume the log, schema tooling
drivers                               shell: the only psycopg importer
sql                                   sans-I/O: compiler, dialects (PostgreSQL first)
core                                  sans-I/O: schema, expr, snapshot, changes, plan, planner, engine
```
- **Sans-I/O core** (`platina.core`, `platina.sql`): imports only the standard-library modules
  on the allowlist `CORE_ALLOWED` in `tools/guards/archlint.py` plus `platina` itself (A101) -
  no driver, event loop, thread, clock, randomness, logging, environment, file or network module;
  no `async`/`await` (A105); no `.now()` / `.today()` / `uuid4()` / `uuid7()` ..., `open()`,
  `print()`, `eval()` even through aliases (A106). Time arrives as the `Now` parameter, waiting
  is a `Sleep` command, the jitter's randomness is an engine argument, and new IDs come from an
  injected ID source (ADR-0002). Widening the allowlist is the maintainer's call.
- **Every package has a layer.** The import-linter layers contract is `exhaustive`: a new direct
  child of `platina` breaks it until it is placed (and documented here).
- **Drivers**: only `platina.drivers` imports `psycopg` / `psycopg_pool` (A102). Everything above
  talks to a small Protocol, split by capability (design section 10.2, the Ecto lesson).
- **Schema tooling**: only `platina.migrate` imports `sqlalchemy` / `alembic` (A103); the runtime
  never needs the `platina[migrate]` extra (design section 8.5).
- **Async runtime**: the shell writes against **anyio**; `asyncio` / `trio` / `uvloop` are not
  imported outside `platina.drivers` (A104). trio is unsupported (design section 8.6).

## Engine and runners (design section 10.5)
- The engine is a generator that yields frozen Command values and receives Replies. A runner is
  a loop that turns Commands into I/O and nothing else - no retry logic, no decisions.
- `runners/async_.py` is the source; the sync runner is **generated** from it (AST transform,
  checked in CI) and never edited by hand. Sync and async must be semantically identical.
- Commit batches and rollbacks run under a cancellation shield in the runner; the engine yields
  only where cancellation is acceptable.

## Data and metadata
- AST nodes, snapshots, Commands, plans: `frozen=True, slots=True`. Structural equality and hash
  are what make the AST a cache key (design section 10.6).
- The registry is mutable during import and becomes an immutable `SealedRegistry` at `seal()`;
  registering after seal is an error. No module-level mutable state that changes after seal
  (free-threaded safety, design section 10.9). The one exception is ADR-0002's fallback ID
  sequence: an `itertools.count()` used only through `__next__` (never `n += 1`; the core has no
  locks).
- Dialect differences are strategies chosen from `DialectCapabilities`, never
  `if dialect == "mysql"` scattered through the core.
- Extension is only through explicitly registered plugins (`ChangesTransformer`,
  `QueryTransformer`, `Observer`); no global signals (design section 10.10).

## Errors
Every Platina exception derives from `PlatinaError` (`platina.core.errors`, re-exported from
`platina`), sits in the hierarchy of design section 10.12 and carries structured fields
(`usecase`, `entity`, `field`, `location`, `hint`, `details`) besides the message - typed,
keyword-only and read-only (ADR-0006). A subclass may add fields and take its own constructor
shape, but the message stays the only item of `args`; pickle and copy go through
`PlatinaError.__reduce__` only, so no subclass defines its own. `errors.py` imports nothing
from `platina`. Lines that restate a subclass's own typed field are built by the class, not
passed in `details`. User domain exceptions propagate unwrapped.

## Decisions
The design document's decision record (section 8) and accepted ADRs in `docs/adr/` are binding.
Deviating from either needs an ADR (`write-adr` skill), and the design document is updated in the
same change. A new or changed public name or signature needs at least an entry in
`CHANGELOG.md` and an update of the design document's syntax section.
