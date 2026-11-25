---
name: commit
description: Commit message, PR title and branch name conventions (ADD/FIX/REF/DEL/DOCS/UPT prefixes) and the main/develop branch flow. Use right before committing or opening a PR, or when asked "commit this", "open a PR", "which prefix?".
---
# Commits, PRs and branch names

> Commit **only when the user asks**. This skill is about *how* to write it, not *when*.

The commit summary, the PR title and the branch name share **one prefix**. One PR carries one
kind of change, so one prefix is always enough.

```
<PREFIX>: <summary>

<body - explain WHY>
```

## 1. Look at what actually changed

Pick the prefix from the diff, never from memory.

```bash
git status --short
git diff --stat
git diff            # unstaged
git diff --staged   # staged
```

## 2. Pick exactly one prefix

| Prefix | Use when | Example |
|---|---|---|
| `ADD:` | Something new in code: feature, API, test, workflow, guard, harness, new dependency | `ADD: commit planner orders FK parents first` |
| `FIX:` | Behaviour was wrong and now matches the intent | `FIX: shield rollback after a cancelled load stage` |
| `REF:` | Structure changes, **observable behaviour is identical** | `REF: split load-stage compilation from materialization` |
| `DEL:` | Removing a feature, file, API, dependency or dead code | `DEL: unused Copy command field` |
| `DOCS:` | **Docs only**: README, docs/, ADRs, translations, docstrings, agent configuration | `DOCS: spike 0001 type surface write-up` |
| `UPT:` | **Version updates** of existing dependencies, `uv.lock` refreshes, pinned images/tools | `UPT: psycopg 3.3.10` |

Upper case, colon, one space: `ADD: ...`, never `Add:` or `ADD :`.

### When the boundary is unclear, decide in this order

1. **Did observable behaviour change?** No -> `REF:`. New behaviour -> `ADD:`. Wrong
   behaviour corrected -> `FIX:`. A `REF:` with a user-visible effect has the wrong prefix.
2. **A spike's throwaway code plus its write-up** -> `DOCS:` (spike code is never shipped);
   promoting spike code into `src/` is a normal `ADD:`.
3. **Dependencies:** new package in `pyproject.toml` -> `ADD:`; version bump of an existing
   package or `uv.lock` only -> `UPT:`; removed package -> `DEL:`. A bump that forces code
   changes (e.g. a psycopg behaviour change) is still `UPT:`; explain the code changes in the body.
4. **Code + the docs that describe it** -> the code's prefix (`ADD:`/`FIX:`/`REF:`). `DOCS:` is
   for commits that change **only** documentation.
5. **Docs are always `DOCS:`**, whether a document is added, edited or removed - `ADD:`/`DEL:`
   are for code and dependencies. That includes ADRs, spike write-ups, `-XX` translations, docstring-only edits
   and agent configuration (`.agents/`, generated `.claude/`, `.codex/`, `.pi/` agent files,
   `AGENTS.md`, `CLAUDE.md`): it instructs agents and has no runtime effect. A new skill is `DOCS:`.
6. **But `.github/workflows/`, hooks and guards are code** - they run and change outcomes
   (`tools/guards`, `tools/hooks`, `.pi/extensions/*.ts`, `.claude/settings.json`,
   `.codex/hooks.json`, `.pre-commit-config.yaml`). New -> `ADD:`, behaviour corrected ->
   `FIX:`, tidy-up -> `REF:`, removal -> `DEL:`. Inside `.github/`, only the issue/PR templates
   are docs.
7. **Tests only:** new tests -> `ADD:`; restructuring existing tests -> `REF:`.
8. **Two prefixes both fit?** Split the commit. "Add a feature and refactor on the way" is two
   commits.

## 3. Summary line

- **English**, imperative or noun phrase, no trailing period (see the language rule).
- About 50-72 characters including the prefix.
- Describe the **change**, not the files.

```
good:  FIX: shield rollback after a cancelled load stage
bad:   FIX: update run.py
bad:   FIX: bug fix
```

`DOCS:` summaries describe the document change: `DOCS: explain engine replay in testing rule`.

## 4. Body - the why

The diff already says *what*. The body says **why**: the failing scenario, the design section,
ADR or spike that justified the change, the measurement for a perf change.

This project has deliberately unusual code (a sans-I/O engine, INSERT-only internal tables,
SERIALIZABLE by default, descriptor typing tricks). If the reason is not written down, the next
agent will "clean it up" and silently regress it. The body is **required** when the commit:
- touches the engine, runners, transactions, run IDs, cancellation or the outbox;
- changes the public type surface (say what pyright and mypy now infer);
- changes a guard, rule or a design decision (name the ADR or design section).

Agents append the attribution trailer their harness requires.

## 5. Branches and flow

```
main      released / releasable history. Receives PRs from develop only (merge commit).
develop   integration branch. All work PRs target develop (squash merge).
<prefix>/<kebab-summary>   work branches cut from develop
v<X.Y.Z>  tags on main mark releases
```

These rules are enforced by GitHub rulesets - agents cannot work around them. The local pre-push
hook (`make hooks-install`) refuses pushes to `main` / `develop` before they leave the machine:

| Branch | Rule |
|---|---|
| `develop` | Changes only through PRs. Merging needs an approval from the code owner (@devgyurak, `.github/CODEOWNERS`). The maintainer may bypass-merge their own PR. Squash for work PRs, merge commit allowed for back-merges. No force pushes, no deletion. |
| `main` | **No direct pushes for anyone, no bypass.** Only PRs whose head is `develop` (required check "main accepts PRs from develop only", `.github/workflows/branch-policy.yml`) with the CI `check` jobs green (py3.14, py3.15), merged with a merge commit. No force pushes, no deletion. Renaming a required CI job means updating the ruleset. |

Consequences for agents: never push to `main` or `develop`; push a work branch and open a PR
(`gh pr create --base develop`) - and only when the user asks. Never approve or merge PRs - that
is the maintainer's call.

## Releases and versions

Versions are **git tags** (`vX.Y.Z`) created on `main` after a `develop` -> `main` merge. Pushing
a tag triggers the release CI (not built yet). Do not bump `version` in
`pyproject.toml` by hand; the release pipeline derives it from the tag. Tags are created by the
maintainer only.

Branch name: lower-case prefix + kebab summary.

```
add/commit-planner-fk-order
fix/shield-cancelled-rollback
ref/load-stage-compile
upt/psycopg-3-3-10
del/unused-copy-field
docs/spike-0001-type-surface
```

## 6. PR title

Same as the commit: `ADD: commit planner orders FK parents first`. With squash merges on
`develop` the PR title becomes the history line, so it must follow the same rules. Fill in
`.github/pull_request_template.md` (verification checklist + review table).

## 7. Before you commit

- [ ] Prefix matches the diff (no `REF:` with behaviour change).
- [ ] One kind of change per commit.
- [ ] Summary describes the change; body explains why (required cases above).
- [ ] `make check` green; `make test-int` when `src/` or `tests/integration` changed.
- [ ] `review-change` done for changes in `src/` or `tests/`.
- [ ] No secrets, no `spikes/**/results/`, no `.claude/settings.local.json`.
- [ ] Every document required by the `docs-sync` rule is updated in this same commit.
- [ ] Translations re-stamped if an English source with translations changed.
- [ ] PR body references the issue (`Closes #N`) when it completes a roadmap item.
- [ ] `DOCS:` only if no code, hook, guard or workflow changed.
