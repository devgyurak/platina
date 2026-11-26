# AGENTS.md

Instructions for every coding agent working in this repository (Claude Code, Codex, Pi).
Claude Code loads this file through `CLAUDE.md`.

## Project
Platina (`platina`) is an ORM for Python 3.14+ and PostgreSQL whose domain code never touches the
database: use cases declare what they load, run as pure functions over immutable snapshots and
return changes as data; one place (`app.run` / `app.query`) does all I/O, SERIALIZABLE with
automatic retry by default. Internally a sans-I/O engine yields commands that thin sync/async
runners execute on psycopg 3.3+. Status: design settled; implementation has started with the core
exception hierarchy (`platina.core.errors`) - the remaining experiments of design section 9 come
before the rest of the prototype.

Read before non-trivial work: `docs/design/design.md` (philosophy, syntax, decision record,
experiments, internal architecture, test strategy), `docs/architecture.md` (what exists now),
`docs/adr/` (decisions taken after the design document), `docs/spikes/` (experiment results).

## Commands
| Task | Command |
|---|---|
| Install | `uv sync` |
| Database | `make db-up` (fast, 26432) / `make db-up-durable` (measurements, 26433) / `make db-down` / `make db-psql` (docker compose, PostgreSQL 18) |
| Git hooks | `make hooks-install` (pre-commit checks + pre-push refusal for `main` / `develop`) |
| Fast gate | `make check` (ruff format check, ruff lint, pyright + mypy, import-linter, guards, agents-check, unit tests, type tests) |
| Format | `make fmt` (ruff format + ruff check --fix) |
| Free-threaded | `make test-unit-ft` (unit tests on CPython 3.14t in `.venv-ft`, each on 8 threads; fails if the GIL is on) |
| Type tests | `make test-types` (`tests/typing/pass_*` / `fail_*` under pyright **and** mypy) |
| Integration | `make test-int` (needs `make db-up`) |
| Everything | `make check-all` (`check` + `test-unit-ft` + `test-int`) |
| Agent config | `make agents-sync` after editing `.agents/` |

Always use `uv run ...` for Python tools; never `pip install`. Never add dependencies without
saying why (prefer the stack the design names; otherwise justify in the PR).

## Non-negotiables
1. **The core does no I/O.** `platina.core` and `platina.sql` import no driver, event loop,
   thread, clock, randomness or environment module and contain no `async`; the engine yields
   Commands and the runners execute them (`make guard`: A101/A105/A106).
2. **Layering** is enforced (import-linter + guards). Only `platina.drivers` imports psycopg,
   only `platina.migrate` imports SQLAlchemy/Alembic, the shell writes against anyio.
3. **Design invariants hold** (`design-invariants` rule): declared reads, pure use cases, changes
   as data, no implicit I/O, one way per operation, no option that changes meaning, remove rather
   than detect, internal append-only tables never read inside SERIALIZABLE. Bending one needs an
   ADR the maintainer accepted.
4. **Correctness > explicitness > incremental convenience > performance** decides trade-offs.
5. **Facts before code.** A design assumption about typing or PostgreSQL behaviour is checked by
   a spike or an experiment (`run-spike`), not settled by argument.
6. **Tests:** Given/When/Then markers and **zero control flow** in test modules; logic goes to
   `tests/support/`. The core is tested without a database; database semantics only against real
   PostgreSQL (no in-memory fake); public typing under pyright **and** mypy.
7. **English** for code, comments, docs, commits. Selected human docs have `-KO` translations
   that must stay in sync (`docs/i18n.toml`).
8. **Fix code, not guards.** There are no suppression comments for project guards.
9. **Generated agent files** (`.claude/agents|rules|skills`, `.codex/agents`, `.pi/agents`) are
   never edited directly - edit `.agents/` and run `make agents-sync`.
10. **Docs move with the code.** Every change updates the documents that describe it in the same
    change (design document + translation, architecture, ADRs, CHANGELOG, skills/rules) - see the
    `docs-sync` rule.

## Workflow
Every change follows the `feature-loop` skill: frame -> open facts (spike) -> design check -> red
tests -> implement -> refactor -> `review-change` (parallel sub-agent review) -> close. Details:
`docs/workflow.md`.

Definition of done: `make check-all` green, review has no open BLOCKER/MAJOR, every document
listed by the `docs-sync` rule updated, the GitHub issue closed by the PR.

ADRs are lightweight: one is needed only for an expensive-to-reverse decision the design document
does not settle, and it is accepted when the maintainer reads it and is convinced (`write-adr`).

Tracking: every roadmap item is a GitHub issue (#1-#74 so far; #47, #53, #56, #62, #66, #67, #68 and #69 are pull requests) in a milestone (`Phase 0 - Experiments`, `Phase 1a - Core execution path`, `Phase 1b - Events, queries and tooling`, `Phase 2 - Event pipeline`, `Later`;
the phases follow design section 9.6, decided in #6), with its design sections,
scope checklist and dependencies, labelled by type (`feature`, `spike`, `test`, `ci`,
`documentation`) and area (`area:*`). `needs-decision` marks issues waiting on the maintainer,
`blocked` issues whose dependencies are open. Reference the issue in the PR (`Closes #N`).

Commits and branches: one prefix per change - `ADD:` `FIX:` `REF:` `DEL:` `DOCS:` `UPT:` - with an
English summary and a body explaining why. Work branches `<prefix>/<kebab-summary>` are cut from
`develop` and PR'd into `develop`; `main` only receives release merges from `develop`. Details:
the `commit` skill. Do not commit or push unless asked.

Branch protection (GitHub rulesets): `develop` changes only via PR with the code owner's
(@devgyurak) approval - the maintainer may bypass-merge; `main` accepts no direct pushes from
anyone, only PRs from `develop`. Releases are `vX.Y.Z` git tags on `main`. Agents never push to
`main`/`develop`, approve, merge or tag.

`develop` is the default branch and both rulesets are active (`docs/workflow.md` section 8); the
local pre-push hook (`make hooks-install`) is a second line. Do not change GitHub settings,
milestones or labels unless the maintainer asks.

## Agent-specific notes
- **Claude Code**: rules auto-load from `.claude/rules/` by path; sub-agents in `.claude/agents/`;
  hooks in `.claude/settings.json` run the guards after each edit.
- **Codex**: skills load from `.agents/skills/`; agent roles from `.codex/agents/*.toml`;
  hooks in `.codex/hooks.json`. Read the matching rule file below before editing.
- **Pi**: skills load from `.agents/skills/`; `.pi/extensions/` provides the edit guard and the
  `subagent` tool (`agentScope: "project"`) over `.pi/agents/`. Read the matching rule file below
  before editing.

## Index
<!-- agentsync:begin -->
<!-- Generated by tools/agentsync.py. Edit .agents/ and run `make agents-sync`. -->

### Rules (read the matching rule before editing files under its paths)

| Rule | Applies to | Summary |
|---|---|---|
| [`architecture`](.agents/rules/architecture.md) | `src/**` | Sans-I/O core vs shell, package layers and which external libraries each zone may import |
| [`design-invariants`](.agents/rules/design-invariants.md) | `src/**`, `tests/typing/**`, `docs/design/**` | The design principles every change must keep - no implicit I/O, immutability, one way, remove rather than detect |
| [`docs-and-adr`](.agents/rules/docs-and-adr.md) | `docs/**` | The design document, architecture doc, spikes and lightweight ADRs (accepted when the maintainer is convinced) |
| [`docs-sync`](.agents/rules/docs-sync.md) | `**/*` | Every change must update the documents that describe it, in the same change |
| [`engine-and-concurrency`](.agents/rules/engine-and-concurrency.md) | `src/platina/core/engine/**`, `src/platina/runners/**`, `src/platina/drivers/**`, `src/platina/outbox/**` | Engine state machine, retries, run IDs, cancellation, pipelines and PostgreSQL concurrency rules |
| [`language-and-i18n`](.agents/rules/language-and-i18n.md) | `**/*.py`, `**/*.md`, `**/*.toml`, `**/*.yml` | English-only code comments and docs; -XX suffixed translations for selected docs |
| [`spikes`](.agents/rules/spikes.md) | `spikes/**`, `docs/spikes/**` | Experiments that answer the design's open questions - throwaway code, durable write-ups |
| [`testing`](.agents/rules/testing.md) | `tests/**` | Given/When/Then, zero control flow, the test layers, real PostgreSQL only, type tests under pyright and mypy |

### Sub-agents

| Agent | Access | Use it for |
|---|---|---|
| [`arch-guardian`](.agents/agents/arch-guardian.md) | review | Architecture review of a diff - sans-I/O core, layer and zone boundaries, design invariants, decision-record and ADR compliance, docs drift. Use in every review-change pass. |
| [`architect`](.agents/agents/architect.md) | read-only | Reviews a design, plan, spike result or ADR draft against the design document and the architecture before any code is written. Use before starting a roadmap item, when a change crosses layers, or when a spike result may change a decision. |
| [`code-reviewer`](.agents/agents/code-reviewer.md) | review | Correctness review of a diff with a transactions/PostgreSQL lens - engine state machine, retries, run IDs, cancellation, pipelines, commit ordering, snapshot immutability and edge cases. Use in every review-change pass that touches src/. |
| [`pg-researcher`](.agents/agents/pg-researcher.md) | review | Establishes PostgreSQL and psycopg facts - SSI predicate locking, isolation behaviour, pipeline mode, COPY, SQLSTATEs, WAL/LSN and xid functions - from the documentation, the installed psycopg source and experiments against the test database. Use before relying on database behaviour and when a spike needs a precise question answered. |
| [`test-reviewer`](.agents/agents/test-reviewer.md) | review | Reviews tests in a diff for rule compliance (GWT, no control flow) and adequacy (laws, fault injection at every yield point, type tests under both checkers, real PostgreSQL, flakiness). Use in every review-change pass that touches tests or behaviour. |
| [`test-writer`](.agents/agents/test-writer.md) | write | Writes the failing tests for a change first (TDD red phase) - core laws, engine replay, compiler snapshots, type tests, integration - strictly following the GWT / no-control-flow rules. Use at the start of every feature-loop iteration. |
| [`translator`](.agents/agents/translator.md) | write | Updates -XX translations (README-KO.md, docs/workflow-KO.md, docs/design/design-KO.md) after their English source changed, then re-stamps the i18n header. Use when the guard reports L202/L203 (and L204 once the direct edit has been carried into the English source). |
| [`type-reviewer`](.agents/agents/type-reviewer.md) | review | Reviews the public type surface - Col[T] descriptors, ParamSpec bind, TypeVarTuple chain, constructors, Finders - under both pyright and mypy, and the pass/fail type tests that pin it. Use when a change touches public signatures, stubs or tests/typing, and for the type-surface spike. |

### Skills

| Skill | When |
|---|---|
| [`architecture-guard`](.agents/skills/architecture-guard/SKILL.md) | Run, interpret and extend the mechanical guards (import-linter layers, tools/guards A1xx/T/L codes, tools/typetests). Use when a guard fails, when adding a package or zone, or when a new invariant should be enforced mechanically. |
| [`commit`](.agents/skills/commit/SKILL.md) | Commit message, PR title and branch name conventions (ADD/FIX/REF/DEL/DOCS/UPT prefixes) and the main/develop branch flow. Use right before committing or opening a PR, or when asked "commit this", "open a PR", "which prefix?". |
| [`core-testing`](.agents/skills/core-testing/SKILL.md) | Testing the sans-I/O core without a database - Hypothesis laws for ChangeSet/chain/planner/load plans, engine replay with fault injection at every yield point, compiler snapshots. Use when adding or changing anything under src/platina/core or src/platina/sql. |
| [`feature-loop`](.agents/skills/feature-loop/SKILL.md) | End-to-end loop for one roadmap item or bug (frame -> spike if a fact is open -> design check -> failing tests -> implementation -> guards -> multi-agent review -> close). Use whenever starting work on a feature, design-section item or bug fix in src/. |
| [`review-change`](.agents/skills/review-change/SKILL.md) | Multi-agent code review workflow for the current change - mechanical gates, then arch-guardian, code-reviewer, test-reviewer (and type-reviewer for public typing) in parallel, consolidated into one verdict. Use before every commit/PR on src/ or tests/, and when asked to review. |
| [`run-spike`](.agents/skills/run-spike/SKILL.md) | Run an experiment that answers one of the design's open questions (design section 9 - type surface, SSI false conflicts, Alembic round trip, use cases on paper, measurements) and record the verdict. Use when a design assumption needs checking before implementation, or when asked to "run the spike for 9.x". |
| [`test-db`](.agents/skills/test-db/SKILL.md) | Start, stop, reset and troubleshoot the docker-compose PostgreSQL used by integration tests and spikes. Use when tests or spikes cannot connect, or a clean database is needed. |
| [`translate-docs`](.agents/skills/translate-docs/SKILL.md) | Keep -XX translations (README-KO.md, docs/workflow-KO.md, docs/design/design-KO.md) in sync with their English sources and stamp the i18n header. Use when guards report L201/L202/L203 or after editing a translated English document. |
| [`type-tests`](.agents/skills/type-tests/SKILL.md) | Pin the public type surface with tests/typing/pass_*.py and fail_*.py files checked by BOTH pyright and mypy (tools/typetests.py) - assert_type for inference, `# expect-error[<pyright rule>, <mypy code>]` for misuse. Use when adding or changing public syntax, descriptors, stubs, bind/chain/Finder signatures, or for the type-surface spike. |
| [`write-adr`](.agents/skills/write-adr/SKILL.md) | Write a lightweight Architecture Decision Record for an expensive-to-reverse decision that the design document does not already settle (public API shape, versions, dependencies, guards, a change to a section 8 decision). The bar is that the maintainer reads it and is convinced. Use when architect says an ADR is needed or a change deviates from the design. |
| [`write-tests`](.agents/skills/write-tests/SKILL.md) | How to write tests in this repo - Given/When/Then markers, zero control flow, which layer proves what (unit, laws, engine replay, type tests, integration), parametrize/Hypothesis instead of loops. Use whenever creating or editing files under tests/. |
<!-- agentsync:end -->
