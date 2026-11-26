# Agentic development workflow

Translations: [Korean](workflow-KO.md)

This repository is built to be developed by coding agents (Claude Code, Codex and Pi, all
supported equally) with a human maintainer approving decisions. This document explains how the
pieces fit together.

## 1. One source, three agents

```
.agents/                      canonical, tool-neutral (edit here)
├── rules/*.md                path-scoped rules
├── agents/*.md               sub-agent definitions
└── skills/*/SKILL.md         workflows (Agent Skills standard)
        │
        │  make agents-sync  (tools/agentsync.py; CI fails on drift)
        ▼
.claude/rules, .claude/agents, .claude/skills      Claude Code
.codex/agents/*.toml                               Codex   (skills read from .agents/skills)
.pi/agents/*.md                                    Pi      (skills read from .agents/skills)
AGENTS.md index block                              Codex, Pi (and Claude via CLAUDE.md)
```

| Capability | Claude Code | Codex | Pi |
|---|---|---|---|
| Project instructions | `CLAUDE.md` -> `@AGENTS.md` | `AGENTS.md` | `AGENTS.md` |
| Rules | `.claude/rules/` (auto, path-scoped) | rules index in `AGENTS.md` | rules index in `AGENTS.md` |
| Skills | `.claude/skills/` | `.agents/skills/` | `.agents/skills/` |
| Sub-agents | `.claude/agents/` (Agent tool) | `.codex/agents/*.toml` (agent roles) | `.pi/agents/` via `.pi/extensions/subagent` (`agentScope: "project"`) |
| Edit hook | `.claude/settings.json` | `.codex/hooks.json` | `.pi/extensions/platina-guard.ts` |

All three edit hooks call the same script, `tools/hooks/agent_hook.py`:
- **pre**: blocks edits to generated files (edit `.agents/` instead);
- **post**: runs `tools/guards` and `ruff check` on the edited files and feeds violations back
  to the agent immediately.

## 2. The feature loop

Every change follows the `feature-loop` skill:

```
 frame ──► open facts ──► design check ──► red tests ──► implement ──► refactor
 (issue,    (run-spike,     (architect;      (test-writer)  (hook feedback
  design     pg-researcher,  ADR if needed)                  on every edit)
  section)   type-reviewer)                                         │
                                                                    │
   close ◄──────────────── review-change ◄──────────────────────────┘
 (docs-sync: design + KO,  (arch-guardian + code-reviewer + test-reviewer
  architecture, CHANGELOG)  + type-reviewer, in parallel)
```

Gates: guards clean -> tests red for the right reason -> `make check` (+ `make test-int` when the
database is involved) green -> no open BLOCKER/MAJOR review findings -> `make check-all`.

**Facts before code.** The design leaves open questions that only experiments answer (design
section 9: the type surface under pyright and mypy, SSI false conflicts, the Alembic round trip,
ten use cases on paper). The `run-spike` skill turns each into throwaway code under `spikes/` and
a durable write-up under `docs/spikes/`, then ticks the design checklist and, if the verdict
changes a decision, edits the design or writes an ADR.

Docs move with the code: the `docs-sync` rule maps every kind of change to the documents that
must be updated in the same change, and `arch-guardian` reports misses as MAJOR findings.

Work is tracked on GitHub: one milestone per phase (`Phase 0 - Experiments`, `Phase 1a - Core execution path`, `Phase 1b - Events, queries and tooling`, `Phase 2 - Event pipeline`, `Later`; the
phases are those of design section 9.6, decided in issue #6), one issue per roadmap item with its
design sections, scope checklist and dependencies, labels for type (`feature`, `spike`, `test`,
`ci`, `documentation`), area (`area:*`) and process (`needs-decision`, `blocked`). PRs close
their issue with `Closes #N`.

Humans decide: accepting ADRs, changing guards/rules, the phase scope (design section 9.6),
releases.

**ADRs are lightweight.** One is written only for an expensive-to-reverse decision the design
document does not already settle. It is short (context, decision, consequences, alternatives) and
it is accepted when the maintainer reads it and is convinced - no mandatory reviewer verdict, no
amendment ceremony. Agents write `Proposed`; only the maintainer's word makes it `Accepted`.
Details: the `docs-and-adr` rule and the `write-adr` skill.

Branches: work happens on `<prefix>/<kebab-summary>` branches cut from `develop` and is PR'd
into `develop`; `main` only receives release merges. GitHub rulesets enforce it: merging into
`develop` needs the code owner's (@devgyurak) approval, which the maintainer may bypass from the
PR; nobody can push to `main`, which only accepts PRs from `develop` (`branch-policy.yml`) with
the CI `check` and free-threaded jobs green. Releases
are `vX.Y.Z` tags on `main`. CI (`ci.yml`) runs on every pull request and on pushes to `develop`
and `main`: `make check` on 3.14 and 3.15, the unit tests on free-threaded 3.14t
(`make test-unit-ft`), and the integration tests. Commit/PR titles use one prefix: `ADD:` `FIX:` `REF:` `DEL:` `DOCS:` `UPT:` (the
`commit` skill).

## 3. Sub-agents

| Agent | Access | Role in the loop |
|---|---|---|
| `architect` | read-only | design check, spike verdicts, ADR drafts |
| `pg-researcher` | review | PostgreSQL / psycopg facts, by documentation and experiment |
| `test-writer` | write | red phase: failing tests from the spec |
| `arch-guardian` | review | architecture and invariant review of the diff, docs drift |
| `code-reviewer` | review | correctness review (engine, transactions, SSI, cancellation) |
| `test-reviewer` | review | test rules and adequacy |
| `type-reviewer` | review | public type surface under pyright and mypy |
| `translator` | write | keeps `-XX` translations in sync |

`review` agents may run commands (tests, type checkers, database experiments) but never edit
repository files.

## 4. Mechanical enforcement

| Layer | Tool | When |
|---|---|---|
| Format, lint | ruff | edit hook, `make lint`, pre-commit, CI |
| Types | pyright (strict on `src`) + mypy `--strict` | `make typecheck`, CI |
| Public type surface | `tools/typetests.py` (`tests/typing/pass_*`, `fail_*` with `# expect-error[<pyright rule>, <mypy code>]`, under both checkers) | `make test-types`, CI |
| Layers | import-linter (`exhaustive`: every package placed) | `make guard`, pre-commit, CI |
| Zones (A101-A106: `core`/`sql` import only an allowlist of standard-library modules, no `async`, no clock or random-ID calls even through aliases; psycopg only in `drivers`; SQLAlchemy/Alembic only in `migrate`; anyio, not asyncio, in the shell) | `tools/guards` | edit hook, `make guard`, pre-commit, CI |
| Test rules: GWT, zero control flow (T1xx-T3xx) | `tools/guards` | same |
| Language: English + translations, stale in either direction (L1xx/L2xx) | `tools/guards` | same |
| No push to `main` / `develop` | `tools/hooks/pre_push.py` (git pre-push, `make hooks-install`) | every push from a clone with the hooks installed |
| Agent config drift | `tools/agentsync.py --check` | `make agents-check`, pre-commit, CI |
| Database semantics | pytest on real PostgreSQL | `make test-int`, CI |
| Thread safety on free-threaded CPython: unit tests on 3.14t, each on 8 threads (pytest-run-parallel), failing when the GIL is on before or after the run, a test ran on one thread without `thread_unsafe(reason=...)`, a warning was recorded, ADR-0002's counter test did not pass, or an unsafe `n += 1` control counter showed no race | `tools/freethreaded.py` | `make test-unit-ft`, CI |
| Branch flow | GitHub rulesets + `branch-policy.yml` + `CODEOWNERS` | every push / PR to `develop` and `main` |

Guards have no inline suppressions. Fix code, not guards; changing a guard needs the maintainer.

## 5. Test rules in one paragraph

Every test has `# given` / `# when` / `# then` markers and contains no `for`, `while`, `if`,
`try`, `match`, comprehensions or conditional expressions. Variation comes from
`pytest.mark.parametrize` or Hypothesis, and helper logic lives in `tests/support/` (or in `tools/`
when a tool also uses it; `tools/` never imports `tests/`). The core is
tested without a database (laws, engine replay with a fault at every yield point, compiler
snapshots); database semantics only against real PostgreSQL, never an in-memory fake; the public
type surface under both pyright and mypy.

## 6. Languages

English is the source language for code, comments, docs and agent files. Human-facing documents
listed in `docs/i18n.toml` ship translations named `<stem>-<LANG>.md` (e.g. `README-KO.md`,
`docs/design/design-KO.md`). Each translation pins the English revision it came from, so the
guard flags it as stale when the English text changes.

## 7. Day-to-day commands

```bash
make hooks-install                # once per clone: pre-commit checks + pre-push guard
make check                        # start of a session (no database needed)
make db-up && make test-int       # when PostgreSQL is involved
make db-up-durable                # spikes that measure rates, throughput or latency
make test-types                   # after touching public signatures
make test-unit-ft                 # unit tests on free-threaded 3.14t (own .venv-ft)
make agents-sync                  # after editing .agents/
uv run python -m tools.guards --changed
```

## 8. GitHub setup (maintainer, one-time)

**Current state (2026-11-26):** done. `develop` is the default branch, both rulesets are active,
and the milestones, labels and roadmap issues (#1-#80; #47, #53, #56, #62, #66, #67, #68, #69, #75, #77, #78 and #80 are pull requests) exist. The local pre-push hook
(`make hooks-install`) stays as a second line of defence. Agents change GitHub settings,
milestones and labels only when the maintainer asks.

- [x] First commit on `main`, then create `develop` from it; make `develop` the default branch.
- [x] Ruleset `develop`: pull request required, 1 approval from the code owner
      (`.github/CODEOWNERS`), stale approvals dismissed, squash or merge commit, repository
      admins may bypass through the PR, no force push, no deletion.
- [x] Ruleset `main`: pull request required, merge commit only, no bypass, required status checks
      "main accepts PRs from develop only" (`.github/workflows/branch-policy.yml`) and
      "lint, types, guards, unit, type tests (py3.14)" / "(py3.15)" and "unit tests, free-threaded (py3.14t)" (`ci.yml`), no force push,
      no deletion. A renamed CI job must be renamed in the ruleset too.
- [x] Milestones: `Phase 0 - Experiments`, `Phase 1a - Core execution path`, `Phase 1b - Events, queries and tooling`, `Phase 2 - Event pipeline`, `Later` (Phase 1 split by #6 on 2026-11-26).
- [x] Labels: `feature`, `spike`, `test`, `ci`, `documentation`, `needs-decision`, `blocked`,
      `area:core`, `area:sql`, `area:app`, `area:runners`, `area:drivers`, `area:outbox`,
      `area:migrate`, `area:codegen`, `area:testing`, `area:integrations`, `area:cli`,
      `area:tooling`.
- [x] Roadmap issues #1-#80: the design section 9 experiments, then every package and feature of
      design sections 3-11 with dependencies (#1 tracks this setup; #48-#52, #54 and #55 come from
      spike 0001, #57-#61 from spike 0002, #63 from spike 0004, #64-#65 from spike 0003, #70-#74 from the
      Phase 1 scope decision #6, #76 from spike 0006, #79 tracks spike 0007; #47, #53, #56, #62, #66,
      #67, #68, #69, #75, #77, #78 and #80 are pull requests).
- [x] Decide ADR-0001 (assembly package and seal) and ADR-0002 (new IDs from an injected
      source) before the first implementation - both accepted.

When an item is done, update this section (and the KO translation) in the same change.
