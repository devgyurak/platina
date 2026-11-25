# ADR-0001: An `app` layer assembles App, seal and the public re-exports

- Status: Accepted (maintainer, 2026-11-25)
- Date: 2026-11-25
- Related: design sections 4.1, 4.10, 10.3, 10.4, 10.9

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- The package list of design section 10.3 has no place for `App`, `seal()` or the names users
  import from `platina` (section 4 imports `App`, `usecase`, `Load`, ... from the top package).
- Section 10.9 puts seal validation in `core/schema`, but one of its steps - "resolve and compile
  load plans" - needs `platina.sql`, and the layer contract of section 10.4 forbids `core` from
  importing `sql`.
- `App.run` / `App.query` hand engine generators to the runners, so `App` must sit above
  `runners`; the FastAPI integration, the CLI and the user test kit (`app_with_db`) use `App`, so
  it must sit below them.
- The `then` / `@process` dispatcher in `outbox` must *execute* use cases (job ID as run ID,
  section 4.10), but `outbox` and `runners` are independent siblings and cannot import each other
  (verified: the contract breaks).

## Decision
- Add a shell package **`platina.app`** with its own layer between
  `cli | integrations | testing` and `runners | outbox | migrate | codegen`. It holds `App`, the
  `seal()` orchestration and `run` / `query` / `read`.
- **Seal is split by purity:** `core/schema` keeps the pure checks that need no SQL (entities,
  relations, constraints, module boundaries, invariant-vs-set-change conflicts, projection keys)
  and builds the registry; `app` orchestrates seal: core checks -> load-plan compilation through
  `platina.sql` -> optional catalog drift check (shell) -> the immutable `SealedRegistry`.
- **`outbox` receives the executor; it never imports `runners`.** `outbox` declares a small
  Protocol for "execute this bound use case under this run ID and return the result"; `app`
  builds the workers and passes them its own run function. `outbox` stays a sibling of `runners`
  and can be tested with a recording executor.
- **Public re-exports** live in `platina/__init__.py` and come **only from `core`, `sql` and
  `app`**. `migrate`, `testing`, `integrations` and `cli` are never imported by the root module:
  users import them explicitly (`platina.testing`, `platina.integrations.fastapi`, ...), so
  `import platina` needs neither SQLAlchemy, pytest nor FastAPI. The root module belongs to no
  layer; nothing inside `platina` imports from it (verified: a core module importing the root
  breaks the contract).
- The layers contract is `containers = ["platina"]` with `exhaustive = true`, so any new direct
  child of `platina` fails lint-imports until it is placed. (Wired in `pyproject.toml`; the
  empty `platina.app` package exists.)

## Consequences
- `core` stays free of `sql`; seal's SQL-dependent step is visible as shell orchestration.
- The dispatcher's dependency on execution is an explicit argument, so the job pipeline is
  testable without a runner and cannot grow its own transaction logic.
- `import platina` loads `core`, `sql`, `app` and what `app` needs (`runners`, `drivers`, hence
  psycopg and anyio); optional pieces stay opt-in.
- One more layer to explain; design sections 10.3, 10.4 and 10.9 describe it, and section 4.10
  notes how the dispatcher gets its executor.

## Alternatives considered
- `App` in `runners`: mixes the registry and seal orchestration into the I/O loop package, and
  `outbox` (a sibling) also needs `App`'s registry.
- Let `core/schema` import `sql`: breaks the core/sql ordering that keeps the AST and plans free
  of dialect code.
- Seal entirely in `sql`: `sql` would then own module boundaries and invariants, which are not SQL
  concerns.
- Move `outbox` above `runners`: works, but couples the dispatcher to one runner implementation
  and makes its tests need a runner; injection keeps the layer flat.

## History
- 2026-11-25 - created (raised by the pre-Phase-0 review).
- 2026-11-25 - review: added how `outbox` executes use cases (injected executor) and limited the
  root re-exports to `core`, `sql` and `app`.
- 2026-11-25 - accepted by the maintainer; design sections 4.10, 10.3, 10.4 and 10.9 updated.
