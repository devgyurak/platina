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
