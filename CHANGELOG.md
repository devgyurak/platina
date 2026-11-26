# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Design document (`docs/design/design.md`, Korean original `design-KO.md`).
- Phase 0 agentic workflow (Claude Code / Codex / Pi): rules, sub-agents and skills under
  `.agents/`, edit hooks, guards (sans-I/O core and library zones, test style, language),
  pyright + mypy type-test runner, package skeleton with layer contracts, CI.
- Pre-Phase-0 review fixes: type tests pin the expected error code per checker
  (`# expect-error[<pyright rule>, <mypy code>]`) and `tests/typing` left out of pyright's project
  scope; spikes type-check strict; a `spike` dependency group (psycopg, SQLAlchemy, Alembic); a
  durable PostgreSQL profile for measurements; independent reproduction before a spike verdict
  counts; the core's imports are an allowlist and clock/ID calls are caught through aliases;
  translations are pinned in both directions; a pre-push hook refusing `main` / `develop`;
  an exhaustive layer contract with a provisional `app` layer; ADR-0001 and ADR-0002 (Proposed);
  `LICENSE` (Apache-2.0) and the MIT notice of the vendored Pi extension.
- Second review: the edit hook scans every string except file-content keys (patches in argv
  lists, heredocs and other keys are found again); A106 also catches clock and ID functions that
  are referenced without a call (`default_factory=uuid.uuid7`); L204 distinguishes meaning from
  wording edits; pre-commit hooks default to the commit stage; ADR-0001/0002 revised.
- ADR-0001 (assembly package and seal) and ADR-0002 (injected ID source) accepted; design
  sections 4.2, 4.10, 10.3 and 10.9 updated accordingly; the free-threading counter check of
  ADR-0002 is a unit test.
- Spike 0001 (design 9.1, type surface under pyright and mypy): write-up
  `docs/spikes/0001-type-surface.md`, independently reproduced in two rounds; design 9.1 ticked.
  Open decisions from the spike are issues #48-#52; #9 and #12 now describe the decided surface.
- Spike 0002 (design 9.4, ten real use cases on paper, rules taken from rocket-rides-atomic,
  eShop, pretix, saleor, Solidus, django-hordak and TigerBeetle): write-up
  `docs/spikes/0002-use-cases-on-paper.md`, reviewed by the architect sub-agent and reproduced by
  type-reviewer (type checks) and pg-researcher (database observations); design 9.4 table gains a
  result column. Partly holds; open decisions for the maintainer (delete of a root,
  idempotency-key reuse, set loads, `insert_all` in the commit batch: #57-#60, and #61 for a
  lock-wait timeout) and ADR-0005 (accepted: `lock="for_update"` is not an escape hatch from
  serialization failures; design 3.1, 4.3, 4.4, 4.6, 7.3 and 8.3 distinguish the same-row and the
  read/write-dependency `40001`).
- Spike 0004 (design 9.3, entity registry -> `MetaData` -> Alembic round trip, Alembic 1.20.1,
  SQLAlchemy 2.1.9, PostgreSQL 18): write-up `docs/spikes/0004-alembic-round-trip.md`,
  independently reproduced by pg-researcher; design 9.3 ticked and the 8.5 risk paragraph states
  the result. Partly holds: column renames need a rewrite that builds its own downgrade, CHECK and
  partial-index changes are seen only with expression-derived names, the `version` trigger works
  with Alembic's own extension points, and partitions created outside migrations do not round-trip.
  No decision changed; the remaining choices are input for #25 and #63 (the internal tables'
  schema path).
- Core exception hierarchy (#8, ADR-0006): `platina.core.errors`, re-exported from `platina`,
  with `PlatinaError` and every class of design section 10.12 plus `ModuleBoundaryError` under
  `SealError`, and `SourceLocation`. Keyword-only read-only fields (`usecase`, `entity`, `field`,
  `location`, `hint`, `details`); `str(exc)` renders the headline, `Location:`, the details and
  `Fix:`; pickle and copy keep every field; `DatabaseError` requires `sqlstate` and keeps the
  driver exception as `__cause__`. Design 4.13 uses the `Location:` line throughout and splits
  the first example's `·` line in two. The first runtime code of the package.
- Spike 0003 (design 9.2, SSI false conflicts and the internal-table rule, PostgreSQL 18.6): write-up
  `docs/spikes/0003-ssi-internal-tables.md`, independently reproduced in three rounds by
  pg-researcher (existence on the fast profile, rates on the durable profile under a quiet-host
  gate, foreign-key checks on an ever-increasing parent key); design 9.2 ticked, 8.3 states the confirmed rule (no read lock from an INSERT's unique
  check; the small-table lock comes from sequential-scan plans) and 7.3 the measured cost.
  ADR-0007 (Proposed) on ever-increasing entity keys, to be decided after the measurements of
  #65; ADR-0005's "until / after 9.2" wording now states what 9.2 measured and leaves `lock=`,
  the hot-row approach and the candidate comparison to #64.
- Free-threaded CI job (#7): "unit tests, free-threaded (py3.14t)" runs all of `tests/unit` on
  CPython 3.14t on every PR, each test on 8 threads with pytest-run-parallel (new dev dependency,
  named by design section 11.10, pinned below 0.11 because the runner reads its marker).
  `make test-unit-ft` runs it locally in its own `.venv-ft`, and `make check-all` includes it; the
  `main` ruleset requires the job.
  - `tools/freethreaded.py` fails the run when the GIL is on before or after it (also when an
    import re-enables it), when a test runs on one thread without `thread_unsafe(reason=...)`, on
    any recorded warning (the plugin's worker threads swallow warnings raised as errors, so the run
    records them with `-W always`), when ADR-0002's counter test did not pass on every case, or
    when an unsafe `n += 1` control counter drawn after the tests shows no duplicates (no race on
    that machine, so the counter test would prove nothing).
  - It refuses to start on a GIL build, with `PYTHON_GIL` / `-X gil` set, with
    `--skip-thread-unsafe`, or with a `filterwarnings` other than `["error"]`.
  - The counter helper moved from `tests/support/free_threading.py` to `tools/concurrent_draws.py`
    so the runner can use it; helpers a tool also uses live in `tools/` (`testing` rule).
  - Design 11.2 now says every PR instead of nightly; ADR-0002, the workflow document, the
    `testing` rule, the `test-writer` agent and the `core-testing`, `write-tests`,
    `review-change`, `architecture-guard` and `commit` skills follow.
- GitHub organization icon in `docs/assets/` (see its README): a hallmark-style plate with a
  "Pt" ligature, platinum `#E5E4E2` on graphite `#15171B`, as SVG master and 1024 / 500 px PNGs.
- Phase 1 scope decided (#6, maintainer, 2026-11-26): design 9.6 splits Phase 1 at the first
  working `app.run` into 1a (core execution path, #9-#22, release) and 1b (events, queries and
  tooling, #23-#29); `platina pull` and migration fidelity move to Phase 2 (#71, #70); the
  cleanup-cost measurement is split (#72, #73, #32); 53200 gets its own issue (#74). Parts that
  depend on open decision issues follow those issues.
- Spike 0006 (#49, #51; the type spike that design 9.6 puts before Phase 1a's build issues):
  write-up `docs/spikes/0006-parent-fk-and-column-operands.md`, independently reproduced by
  type-reviewer; both decisions hold under pyright and mypy.
  - The key of an owned child is declared with `parent_fk(lambda: Order)` (working name, fixed in
    #9) and set by `Order.items.add(...)`; it is not a constructor parameter, so a new child
    cannot be created with another parent's key. A non-owned child keeps `fk`, a required
    parameter.
    Design 4.2 (with an `Item` declaration), 4.4, 4.7 and 8.2 "Creation syntax", ADR-0003.
  - Comparison operands: a value is exactly `T` (no numeric widening); two columns of the same
    value type, up to nullability, compare through an overload and give `Pred[O | O2]`, which
    `Order.where(...)` still rejects. Design 4.7, 8.2 "Field type surface" and 11.8 (new misuse
    lines and the `assert` form of a rejected comparison); ADR-0004's constraint now forbids only
    a `T | Column[O, T]` union parameter.
  - Left open: reading the key before `add` (#76, new), owned children of a new root and `add` on
    a non-owned relation (#60); for #9 how `owned` and `parent_fk` stay consistent, the final
    name, moving an existing child to another parent (still type-checks), and the comparison gaps
    of design 8.2 (`==` with a wrong value type is `bool`, `== None`, ordering against `None` and
    on an enum column, comparisons on an embedded value column - a row comparison or only through
    `path(...)` -, a column in a set, a numeric cast); two-owner predicates in queries (#52).
    The `type-tests` skill names the spike's stub as the reference for these two shapes.
- Phase 1a decisions recorded (maintainer, 2026-11-26), from the recommendations on the decision
  issues gated by design 9.6:
  - #54: entity equality compares the entity type and the column values only (relations and the
    load state are not); a column without a value yet is equal only when unset on both sides; the
    hash stays type plus primary key. ADR-0003 Decision 4 and design 4.2, 4.6, 8.2, 10.8, 10.12
    are no longer provisional.
  - #48: one marker, `INJECTED`, for every parameter the runner fills (injected types and dependent
    loads); seal checks it both ways, `bind` rejects such a parameter with `UsageError`, a direct
    call must pass every parameter; these parameters come last or are keyword-only (design 4.5,
    4.7, 4.13, 8.2).
  - #58: a caller key reused with different arguments raises `IdempotencyKeyReuse` (directly under
    `PlatinaError`, added with #22); the fingerprint (registry name + canonical serialization of
    the bound arguments) is stored in `run_result` and compared only on the `23505` replay path
    (design 4.5, 4.6, 8.3, 10.5, 10.12).
  - #61: ADR-0008 (accepted) - `timeout=` is one budget for the run, held by the runner; `57014`
    before `COMMIT` and the deadline raise `RunTimeout` (directly under `PlatinaError`, added with
    #17), never retried; no `lock_timeout` option; `TxDefaults(statement_timeout=)` becomes
    `TxDefaults(timeout=)`; the runner reports the deadline, the engine emits the
    `statement_timeout` statement and reads the commit outcome by statement position; an unknown
    outcome is resolved before `RunTimeout` / `RetryExhausted` (design 4.1, 4.6, 4.10, 8.3, 10.5,
    10.12, 11.4; the `engine-and-concurrency` and `design-invariants` rules). Facts from
    pg-researcher: `statement_timeout` limits each statement also inside a pipeline, `COMMIT` is
    not timed out, and a `57014` after `COMMIT` means committed.
  - #63 (direction only, the issue stays open): ADR-0009 (accepted) - the core owns versioned SQL
    for the internal tables in a dedicated schema (Alembic's defaults compare only the default
    schema - checked; a schema that is the default schema, e.g. through `"$user"`, is compared),
    no DDL at startup, a `42P01` / `42703` / `42501` on an internal table names the command or
    grant;
    partitioning and keys wait for #72 (design 8.5, 9.6).
  - #57, #59, #60: decided as hypotheses for the Phase 1a type spike (issue comments); the design
    text changes after the spike.
  - After an independent review (rebased onto spike 0006): ADR-0008's facts reproduced and
    corrected (`transaction_timeout` also ends the session during `COMMIT`'s deferred triggers;
    `set_config` takes the snapshot, needs a text parameter and replaces a smaller default; the
    `ROLLBACK` tag); design 10.5's sketch classifies failures in the engine, marks `bounded` on
    the command, continues without a second claim after `ResolveClaim` and keeps every `yield`
    out of the `except` clauses; the equality rule points at #76 for a parent key before `add`;
    seven questions recorded as open for the maintainer in ADR-0008 / ADR-0009.
  - The maintainer answered the seven questions and accepted ADR-0008 and ADR-0009 (2026-11-26):
    after a successful `ResolveClaim` the engine rolls back and starts a normal attempt (no
    `claimed` state; design 10.5 also raises non-retryable failures instead of retrying them);
    `RunTimeout` directly under `PlatinaError` with stages `load` / `backoff` / `commit`; the
    budget replaces a smaller default `statement_timeout`; Platina's Alembic integration refuses
    to autogenerate when the internal schema is the default schema; the internal-schema downgrade
    is forward-only (expand/contract stays open in #63); #22 runs on test-only DDL and does not
    wait for #72.
- Spike 0007 (#79, design 9.6: the type shapes of #48, #57, #59 and #60 under pyright and mypy):
  write-up `docs/spikes/0007-phase-1a-type-shapes.md`, reviewed by architect (two rounds) and two
  independent review sessions, reproduced by type-reviewer (five rounds). Holds on the lines it
  wrote under three conditions: the owner of a relation operation and of a `Load.after` path must
  be invariant (both checkers otherwise accept another entity's operation in `insert(...)` and
  another entity's path in `Load.after(...)`), `relation.load(...)` takes relations only (a
  covariant `LoadPath`), and a relation operation is not a column operation. Known checker
  differences remain (mypy accepts a declared type that widens a relation's owner; inline
  `Annotated` metadata; an `owned=` flag given a literal-initialised constant). Spike 0002's use
  cases 3, 6 and 8 become expressible. The maintainer decided (2026-11-26): `owns_many(...)`
  declares an owned relation (no `owned=` flag), candidate B writes the owned children of a new
  root through `insert(root, *children)`, and `Entity.where` requires a predicate. Design 9.6
  links the write-up; §4.3 / 4.4 / 4.7 / 4.8 / 8.2 change with the two follow-up ADRs (#60 point 4,
  #59 point 2), the second of which also decides whether row sets replace partial `.where`
  loads.
- ADR-0010 (accepted by the maintainer 2026-11-26; #57, #60): writes beyond `.set`. Records the
  decisions of #57 / #60 (`insert(entity, *children)` in the commit batch, `insert_all` a separate
  bulk operation; owned rows only through their root and no write operations on other relations;
  `owns_many`; candidate B; `Entity.where` needs a predicate; `order.delete()` with engine-issued
  deletes of the owned children) and decides: ownership one level deep; seal checks of
  `owns_many` / `parent_fk` / `aggregate_root`; a `UsageError` at the call for direct writes of
  owned children (the `Part` base stays a rejected alternative) and for the misuse of new, loaded
  and ref snapshots; a `SealError` for `identity`-key roots with owned relations in Phase 1a;
  delete semantics (unloaded owned relations deleted, one `WITH ... DELETE` statement per root
  table, key-only predicate, its planner edges, operations on deleted children dropped only
  across chain steps); `ForeignKeyViolation` for `23503` / `23001`; a `Write[O]` alias (a working
  name; #13 fixes it). Facts: a spike 0007 addendum - types A1-A3 (reproduced by type-reviewer)
  and PostgreSQL 18 experiments with their scripts (one statement deletes a root that references
  its own owned row, and two root tables that reference each other; a concurrent `add` with its
  root bump is `40001` under SERIALIZABLE and REPEATABLE READ; a non-owned insert committed just
  before a delete gives the delete `23503` at either level; `23503` names the referencing table; a
  cascade that matches no row adds no predicate lock). Reviewed by architect (two rounds) and an
  independent review. Design 4.2-4.4, 4.6, 4.8, 4.12, 8.2, 8.3, 9.6, 10.7, 10.8, 10.12, 11.3,
  11.8 (EN + KO), ADR-0003 and ADR-0004 amended in place, the `design-invariants` and
  `engine-and-concurrency` rules.
- ADR-0011 (Proposed, #59): row-set loads and the shape of dependent loads. A `Load.after`
  function returns one ref, a list of refs or a row set (`Entity.where(...)`); its load arguments
  go on the result, `Load.after(fn, missing=...).load(...)` (changes #59 point 3; probed and
  reproduced as spike 0007 round 6, which also drops the invariant `Path`); partial `.where` loads
  stay, with constant predicates, and seal rejects date and date-time constants (not `time`;
  `None` allowed) in any predicate of a load declaration - a partial `.where` at any depth and
  `Load.when`'s condition and `match`; seal also checks that a `Load.after` function returns one
  entity, read from its now required return annotation, and that every load argument is owned
  by it (the reproduction's W6-W8); a `Load.after` adds one stage after its inputs (the stage
  count is the plan's depth); a row chosen by a key the caller has, whose absence is an error, is
  a ref parameter, not a `Load.after`. Numbered 0011 (`0010-writes-beyond-set.md` takes 0010).
  Reviewed by architect (two rounds). Design 3.1, 4.3 (a cross-reference), 4.7, 4.13, 8.2 and 9.6
  updated; ADR-0004 Decision 4 amended in place (load paths are receiver-fixed places);
  `docs/architecture.md` lists the ADR.
### Changed
- Entity syntax (ADR-0003, accepted): entities inherit `Entity` with table options as class
  keywords instead of an `@entity` decorator, are created with the keyword constructor
  `Order(...)` instead of `Entity.new(...)`, are frozen at the type level (hashable in both
  checkers). The runtime rule - value equality over columns with a type-plus-primary-key hash -
  was provisional until #54 decided it (see Added).
- Field surface (ADR-0004, accepted): class access is `Column[Owner, T]` with fixed variance;
  value-object fields are declared `Col[...]`; embedded paths are `Order.total.path(Money.amount)`
  and value-object increments go through them; owner checks apply by type where the receiver
  fixes the owner (including `SetChange.emit_each`); queries are checked when their description
  is built, profiles, loads, indexes, checks and invariant field lists by seal.
- Design sections 4, 8.2, 10.3, 10.8, 10.12 and 11.8 (with the observed error codes), ADR-0002,
  README, the `design-invariants` rule, the `type-reviewer` agent and the `type-tests` skill
  follow these decisions.
