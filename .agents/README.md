# .agents - canonical, tool-neutral agent configuration

This directory is the single source of truth for every coding agent we support
(Claude Code, Codex, Pi). Edit files here, then run `make agents-sync`.

| Path | Format | Consumed by |
|---|---|---|
| `skills/<name>/SKILL.md` | Agent Skills standard | Codex and Pi natively; copied to `.claude/skills/` |
| `agents/<name>.md` | frontmatter `name, description, access, effort` + prompt body | generated into `.claude/agents/`, `.codex/agents/*.toml`, `.pi/agents/` |
| `rules/<name>.md` | frontmatter `description, paths` + body | generated into `.claude/rules/` (path-scoped) and the rules index in `AGENTS.md` |

`access` levels: `read-only` (reads code and docs only: no shell - Read/Grep/Glob, Codex
read-only sandbox), `review` (has a shell to run tests, type checkers and database experiments,
and never edits repository files - an instruction, not a sandbox), `write` (may edit files).

Generated files carry a "GENERATED" banner. The edit hook blocks direct edits to them, and
CI fails (`make agents-check`) if they drift from this directory.
