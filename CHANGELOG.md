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

### Changed
- Entity syntax (ADR-0003, accepted): entities inherit `Entity` with table options as class
  keywords instead of an `@entity` decorator, are created with the keyword constructor
  `Order(...)` instead of `Entity.new(...)`, are frozen at the type level (hashable in both
  checkers). The runtime rule - value equality with a type-plus-primary-key hash - is a
  provisional working rule until spike 9.4 (#5) settles it (#54).
- Field surface (ADR-0004, accepted): class access is `Column[Owner, T]` with fixed variance;
  value-object fields are declared `Col[...]`; embedded paths are `Order.total.path(Money.amount)`
  and value-object increments go through them; owner checks apply by type where the receiver
  fixes the owner (including `SetChange.emit_each`); queries are checked when their description
  is built, profiles, loads, indexes, checks and invariant field lists by seal.
- Design sections 4, 8.2, 10.3, 10.8, 10.12 and 11.8 (with the observed error codes), ADR-0002,
  README, the `design-invariants` rule, the `type-reviewer` agent and the `type-tests` skill
  follow these decisions.
