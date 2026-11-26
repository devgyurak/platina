---
description: Given/When/Then, zero control flow, the test layers, real PostgreSQL only, type tests under pyright and mypy
paths:
  - "tests/**"
---
# Testing rules (enforced by tools/guards: T1xx-T3xx; type tests by tools/typetests.py)

## Shape of every test (`tests/**/test_*.py`)
```python
def test_planner_orders_parent_insert_before_child_insert():
    # given
    changes = insert_order_with_items(items=2)
    # when
    plan = plan_commit(changes, SCHEMA)
    # then
    assert table_order(plan) == ["orders", "items"]
```
- Markers `# given`, `# when`, `# then` in that order, each at most once. `# given` may be
  omitted only when nothing happens before `# when`. Use `# when / then` for `pytest.raises`.
  Optional trailing text is allowed: `# given: an order without items`.
- At least one assertion after `# then` (`assert`, `pytest.raises`, or an `assert_*` helper).
- One behaviour per test. Name: `test_<subject>_<condition>_<expected>`.

## Absolutely no control flow in test modules
`for`, `async for`, `while`, `if`, conditional expressions, `match`, `try`, and all
comprehensions are forbidden anywhere in a test module - no exceptions, no suppressions.
- Variation -> `@pytest.mark.parametrize` with literal values, or Hypothesis `@given`.
- Setup logic, loops over yield points, replay drivers -> `tests/support/` (or fixtures); a helper
  that a `tools/` runner also uses lives in `tools/` instead (`tools/` never imports `tests/`, and
  `src/` imports neither).
- No `sleep` in tests: the engine's `Sleep` command makes backoff testable without time; for
  concurrency, synchronise with barriers/events from a support helper.

## Layers (design section 11.2)
| Dir | Needs | What |
|---|---|---|
| `tests/unit/` | nothing (also run on free-threaded 3.14t, each test on 8 threads: `make test-unit-ft`) | core laws (Hypothesis), compiler snapshots, engine replay with fault injection, guards and tools |
| `tests/typing/` | pyright + mypy | `pass_*.py` / `fail_*.py` for the public type surface (`make test-types`; not collected by pytest) |
| `tests/integration/` | `make db-up` | real SQL on real PostgreSQL: pipelines, SSI, migrations, outbox, codegen |
| `tests/support/` | - | the place for helper logic (or `tools/` when a tool also uses it); unit-test it when non-trivial |

## Rules that follow from the architecture
- **Every unit test runs on several threads at once** on free-threaded 3.14t (pytest-run-parallel,
  design section 11.10). No module-level mutable state; a test that cannot share its process
  with copies of itself (`monkeypatch`, `capsys`, `pytest.warns`, process-wide state) gets
  `@pytest.mark.thread_unsafe(reason="...")` - never a skip. `make test-unit-ft` fails a test
  that runs on one thread without that marker, and fails on any recorded warning. For an
  expected warning use `pytest.warns`, not a `filterwarnings("error")` marker: an error raised
  in the plugin's worker threads is swallowed. After the tests it also fails when an unsafe
  `n += 1` control counter (`tools/concurrent_draws.py`) shows no race on the machine.
- **The core is tested without a database.** If a core test needs PostgreSQL, the code is in the
  wrong layer.
- **Database semantics are tested only against real PostgreSQL.** Never write an in-memory fake
  database: isolation levels, NULL logic and constraints differ and give false confidence.
- **The engine is tested by replay.** Feed scripted Replies into the generator and inject an error
  at *every* yield point (serialization failure, deadlock, connection lost, cancellation); assert
  no partial commit, rollback-or-retry, restart from `BEGIN`, same run ID on commit-unknown
  (design section 11.4). The loops that do this live in `tests/support/`.
- **Laws over examples** for ChangeSet, `chain`, planner and load plans (design section 11.3);
  add targeted examples for edge cases Hypothesis is unlikely to hit.
- **Integration isolation**: each test gets its own database (`CREATE DATABASE`, dropped after
  the test), never transaction rollback - the runner owns transaction boundaries. Until #20 adds
  the migrated template (`CREATE DATABASE ... TEMPLATE`) the database is empty and the test
  creates its tables. Concurrency tests pin interleavings with barriers, not timing.
- **Type tests**: everything the design promises to be a type error is a line in a `fail_*.py`
  file marked `# expect-error[<pyright rule>, <mypy code>]: <why>`, and must fail under **both**
  pyright and mypy **with the named code**; the happy path is a `pass_*.py` file with
  `assert_type`. See the `type-tests` skill.
- Every documented code example eventually runs as a test (Sybil, design section 11.2).
