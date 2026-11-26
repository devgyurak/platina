---
name: architecture-guard
description: Run, interpret and extend the mechanical guards (import-linter layers, tools/guards A1xx/T/L codes, tools/typetests). Use when a guard fails, when adding a package or zone, or when a new invariant should be enforced mechanically.
---
# Architecture guard

## What enforces what
| Tool | Command | Enforces |
|---|---|---|
| import-linter | `uv run lint-imports` | layer order between `platina` packages, `exhaustive` (every package placed) (`[tool.importlinter]` in pyproject.toml) |
| tools/guards archlint | `uv run python -m tools.guards` | A101 core (`core`, `sql`) imports outside the `CORE_ALLOWED` allowlist; A102 psycopg outside `drivers.psycopg`; A103 sqlalchemy/alembic outside `migrate`; A104 asyncio/trio/uvloop in the shell outside `drivers.psycopg` (use anyio); A105 `async`/`await`/async comprehensions in the core; A106 `.now()`/`.today()`/`uuid4()`/`uuid7()`... (aliases included), `open()`, `print()`, `eval()`... in the core |
| tools/guards testlint | same | T101 control flow, T201-T206 Given/When/Then, T301 any `*.sleep()` |
| tools/guards langlint | same | L101/L102 English-only (test data files exempt), L201-L204 translations (stale in both directions) |
| tools/typetests | `uv run python -m tools.typetests` | `tests/typing/pass_*` clean and `fail_*` `# expect-error[<pyright rule>, <mypy code>]` lines rejected with the named codes, under pyright **and** mypy |
| tools/freethreaded | `make test-unit-ft` (CI: "unit tests, free-threaded (py3.14t)") | `tests/unit` on free-threaded 3.14t, each test on 8 threads: GIL off before and after the run, no test moved to one thread without `thread_unsafe(reason=...)`, no recorded warning, ADR-0002's counter test passed, an unsafe `n += 1` control counter raced (`tools/concurrent_draws.py`) |
| tools/hooks/pre_push.py | git pre-push (`make hooks-install`) | no push to `main` / `develop` |
| ruff | `uv run ruff check` | style, bugbear, async pitfalls (ASYNC), no `print` (T20) outside tools/spikes |
| pyright + mypy | `make typecheck` | types (strict on `src`) |

`make guard` runs import-linter + guards; `make check` runs everything fast. The edit hook
(`tools/hooks/agent_hook.py`) runs guards + ruff on each edited file for every agent.

## Fixing a violation
Fix the code, never the guard. Guards have no inline suppressions by design. If you believe
a rule is wrong, stop and raise it with the maintainer (an ADR if it is architectural).

## Adding a new invariant
1. Prefer configuration: a new import-linter contract, or an entry in `CORE_ALLOWED` (widening -
   the maintainer decides), `CORE_BANNED_METHODS`, `CORE_BANNED_BUILTINS` or the zone tuples in
   `tools/guards/archlint.py`.
2. Otherwise add an AST check with a new code (next free number in its family) and document it
   in the module docstring and in the relevant `.agents/rules/*.md`.
3. Add unit tests in `tests/unit/tools/` (GWT style: source string in, violation codes out),
   one passing and one failing case per code.
4. Run the full scan `uv run python -m tools.guards` - the repo must be clean.
5. Changing what a guard allows is the maintainer's call: say so in the PR.

## Adding a package
Create it with a docstring stating its contract (zone, what it may import), add it to the
`layers` contract in `pyproject.toml` (the contract is exhaustive, so lint-imports fails until
you do), to the zones in `archlint.py` if it is sans-I/O or
confines a library, and update `docs/architecture.md` and `.agents/rules/architecture.md`.
