---
description: Every change must update the documents that describe it, in the same change
paths:
  - "**/*"
---
# Docs sync rules

A change is **not done** until every document that describes the changed thing is true again.
Update them **in the same commit/PR** as the change - never "docs later", never a TODO.

## Before you finish (and in every review)
1. List the files you changed (`git status --short`).
2. Walk the table below for each of them and update every target that applies.
3. When unsure whether something else mentions it, search:
   `grep -rn "<identifier, command, port, path>" README*.md AGENTS.md CLAUDE.md docs .agents .github`
4. If an English document you touched has translations, update them too (language rule).

## What to update

| If you change | Also update |
|---|---|
| Public API (names exported from `platina`, signatures, error classes) | `docs/design/design.md` syntax section (section 4) and error table, `docs/architecture.md`, `CHANGELOG.md` (Unreleased), type tests in `tests/typing/`; an ADR if it departs from the design |
| A package/layer in `src/` (new, moved, renamed) | `docs/architecture.md`, `[tool.importlinter]` in `pyproject.toml`, `.agents/rules/architecture.md`, zones in `tools/guards/archlint.py` |
| A design decision or a deviation from the design document | an ADR in `docs/adr/`, `docs/design/design.md` (+ `design-KO.md`) |
| A finished experiment (design section 9) | `docs/spikes/NNNN-*.md`, the section 9 checkbox in `design.md` (+ KO), an ADR or a design edit if the result changes a decision |
| Progress on a roadmap item | the design document checklist; PR body `Closes #N`; the GitHub milestone |
| Guard codes in `tools/guards` or `tools/typetests.py` | the module docstring, the matching `.agents/rules/*.md`, `architecture-guard` skill, `docs/workflow.md` enforcement table |
| Hooks (`tools/hooks`, `.claude/settings.json`, `.codex/hooks.json`, `.pi/extensions/`, `.pre-commit-config.yaml`) | `docs/workflow.md` section 1, `CLAUDE.md`, agent notes in `AGENTS.md` |
| `.agents/` rules, skills or sub-agents | `make agents-sync`; the tables in `docs/workflow.md` when one is added, removed or renamed |
| `Makefile` targets or day-to-day commands | `AGENTS.md` commands table, `README.md` development section (+ KO), skills that quote the command |
| `docker-compose.yml` (image, port, credentials, profiles) | `test-db` skill, `spikes` rule, `AGENTS.md`, `README.md` (+ KO) |
| Dependencies or Python/PostgreSQL versions | `README.md` (+ KO), `pyproject.toml` classifiers, CI matrix, design section 6 if support changes |
| `.github/workflows/`, the branch flow or the GitHub setup state | `docs/workflow.md` (+ KO) sections 2 and 8, `commit` skill, `AGENTS.md` |
| An English document that has `-XX` translations | the translation + `uv run python -m tools.guards i18n-stamp <file>` |

## Reviewers
`arch-guardian` reports missing doc updates as **MAJOR** findings (docs drift), with the
document and the stale statement.
