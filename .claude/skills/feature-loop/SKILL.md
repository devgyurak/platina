---
name: feature-loop
description: End-to-end loop for one roadmap item or bug (frame -> spike if a fact is open -> design check -> failing tests -> implementation -> guards -> multi-agent review -> close). Use whenever starting work on a feature, design-section item or bug fix in src/.
---
# Feature loop

One iteration = one roadmap item (or one bug). Keep iterations small enough to review in one
sitting. Each step names its gate; do not move on until the gate passes.

## 0. Frame
- Pick the GitHub issue from the current milestone (`gh issue list --milestone "<milestone>"`)
  and read it with its dependencies; skip issues labelled `blocked` or `needs-decision`.
  While the repository has no milestones or issues yet (`docs/workflow.md` section 8), work from
  the maintainer's request or the design section 9 checklist and say which item you took; do not
  create GitHub issues or milestones unless asked.
- Locate the item in `docs/design/design.md` (the syntax in section 4, the decision in section 8,
  the architecture in section 10, the experiment in section 9). Write a 3-5 line spec: public API,
  behaviour, error cases, out of scope.
- Gate: spec exists (in the PR description draft or the conversation).

## 1. Open facts first (only when the change rests on unverified behaviour)
- Typing behaviour of a construct, PostgreSQL/SSI behaviour, Alembic fidelity: do not argue,
  measure. Run the `run-spike` skill, or ask **pg-researcher** / **type-reviewer** a precise
  question.
- Gate: every fact the design depends on is either documented in the design/a spike write-up or
  verified now.

## 2. Design check
- Small, single-package change: self-check against `.agents/rules/architecture.md` and
  `.agents/rules/design-invariants.md`.
- Cross-layer change, new public API, anything in the engine, runners, drivers or outbox, or a
  deviation from the design: ask **architect**. If it says an ADR is needed, write it
  (`write-adr` skill) and get the maintainer's acceptance before merging.
- Gate: zone and layer placement are clear; no invariant is bent without an ADR.

## 3. Red - tests first
- Delegate to **test-writer** (or follow `write-tests` yourself): core laws and unit tests,
  engine replay with fault injection, `fail_*`/`pass_*` type tests for public syntax, integration
  tests only for real database semantics.
- Gate: `uv run python -m tools.guards --changed` clean; new tests fail for the right reason.

## 4. Green - implement
- Smallest change that passes. Keep the core pure; put I/O in the shell.
- The edit hook runs guards + ruff on every file you touch; fix what it reports immediately.
- Gate: `make check` passes (lint, pyright + mypy, guards, unit and type tests); `make test-int`
  passes when anything that talks to PostgreSQL changed.

## 5. Refactor
- Remove duplication, keep frozen/slotted values frozen, update docstrings (English).

## 6. Review
- Run the `review-change` skill (arch-guardian + code-reviewer + test-reviewer, plus
  type-reviewer for public typing, in parallel).
- Gate: zero BLOCKER/MAJOR findings left open (fixed, or rebutted with evidence).

## 7. Close
- Walk the `docs-sync` rule table for every changed file and update each listed document
  (design document + KO translation, `docs/architecture.md`, `CHANGELOG.md`, skills).
- The PR body says `Closes #N`.
- Commit following the `commit` skill on a `<prefix>/<kebab-summary>` branch cut from `develop`;
  PR into `develop`. Do not commit or push unless the user asks.
- Gate: `make check-all` green.
