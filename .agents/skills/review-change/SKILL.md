---
name: review-change
description: Multi-agent code review workflow for the current change - mechanical gates, then arch-guardian, code-reviewer, test-reviewer (and type-reviewer for public typing) in parallel, consolidated into one verdict. Use before every commit/PR on src/ or tests/, and when asked to review.
---
# Review a change

## 1. Scope
`git status`, `git diff --stat <base>` (base defaults to `develop`; before the first commit review
the working tree). Note which zones are touched (core, sql, drivers, runners, outbox, ...).

## 2. Mechanical gate (must pass before spending reviewer time)
```bash
make check        # ruff, pyright + mypy, lint-imports, guards, agents-check, unit + type tests
make test-int     # when anything that talks to PostgreSQL changed (needs make db-up)
```
Fix failures first.

## 3. Parallel reviews
Spawn in parallel, each with the base ref and the list of touched files:
- **arch-guardian** - always.
- **code-reviewer** - always when `src/` changed.
- **test-reviewer** - when tests or behaviour changed.
- **type-reviewer** - when a public signature, a descriptor/stub or `tests/typing/` changed.

How to spawn per tool:
| Tool | How |
|---|---|
| Claude Code | Agent tool with `subagent_type` = agent name (definitions in `.claude/agents/`) |
| Codex | ask to spawn the agent role by name (roles in `.codex/agents/*.toml`) |
| Pi | `subagent` tool with `agentScope: "project"` (agents in `.pi/agents/`, extension in `.pi/extensions/subagent/`) |
| none available | run each agent's instructions from `.agents/agents/<name>.md` sequentially yourself |

Give reviewers the code, not your conclusions - ask for an independent read.

Every reviewer also checks **docs drift** against the `docs-sync` rule table: a changed
command, port, API, layer, guard or decision whose documents were not updated is a MAJOR finding.

## 4. Consolidate
Merge findings into one table sorted by severity, de-duplicated:
`severity | file:line | finding | source agent | action`.
- BLOCKER / MAJOR: fix, or rebut with concrete evidence (test output, a design section, a
  PostgreSQL experiment, the checker's inferred type).
- MINOR: fix if cheap, otherwise list as follow-up.
Verify each fix (re-run the relevant test) and, for BLOCKERs, re-run the agent that raised it.

## 5. Verdict
Report: gates run (with pass/fail), findings and their resolution, remaining follow-ups.
Only declare "ready" when gates are green and no BLOCKER/MAJOR remains open.
