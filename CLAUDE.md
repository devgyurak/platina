@AGENTS.md

## Claude Code specifics

- Path-scoped rules in `.claude/rules/` load automatically; they are generated from
  `.agents/rules/` (do not edit them directly).
- Sub-agents (`.claude/agents/`): delegate with the Agent tool. Use `review-change` to run
  `arch-guardian`, `code-reviewer`, `test-reviewer` (and `type-reviewer` for public typing)
  **in parallel** in one message.
- Skills (`.claude/skills/`, copied from `.agents/skills/`) are available as `/feature-loop`,
  `/review-change`, `/run-spike`, `/type-tests`, ...
- Hooks (`.claude/settings.json`): `PreToolUse` blocks edits to generated agent files;
  `PostToolUse` runs `tools/guards` + ruff on every edited file and reports violations back.
  Treat hook feedback as a failing check and fix it before continuing.
- Avoid the built-in `/code-review` for repo reviews; use `/review-change`, which knows the
  project rules and sub-agents.
