---
name: write-tests
description: How to write tests in this repo - Given/When/Then markers, zero control flow, which layer proves what (unit, laws, engine replay, type tests, integration), parametrize/Hypothesis instead of loops. Use whenever creating or editing files under tests/.
---
# Writing tests

The full rule set is `.agents/rules/testing.md`; `tools/guards` enforces the shape (T1xx-T3xx).

## Template
```python
import pytest

from tests.support.planner import insert_order_with_items, table_order


@pytest.mark.parametrize("items", [0, 1, 3], ids=["no-items", "one", "several"])
def test_planner_orders_parent_insert_before_child_inserts(items):
    # given
    changes = insert_order_with_items(items=items)
    # when
    plan = plan_commit(changes, SCHEMA)
    # then
    assert table_order(plan)[0] == "orders"
```
(`tests/support/planner.py` and `plan_commit` are illustrations; create the helpers you need.)

## Pick the layer
| To prove | Write |
|---|---|
| a pure function's behaviour | a unit test in `tests/unit/` |
| a property over many inputs (ChangeSet, chain, planner, load plans) | a Hypothesis law (`core-testing` skill) |
| transaction behaviour (retry, rollback, run ID, cancellation) | engine replay with fault injection (`core-testing` skill) |
| generated SQL | a compiler snapshot, later also PREPAREd in integration |
| "this misuse is a type error" / "this infers as X" | `tests/typing/fail_*.py` / `pass_*.py` (`type-tests` skill) |
| real database semantics (SSI, constraints, pipelines, COPY) | `tests/integration/` on PostgreSQL |

Unit tests also run on free-threaded 3.14t, each on 8 threads at once (`make test-unit-ft`): no
module-level mutable state, and a test that cannot run beside copies of itself gets
`@pytest.mark.thread_unsafe(reason="...")` (the `testing` rule).

## Replacing control flow
| Instead of | Use |
|---|---|
| `for x in cases:` | `@pytest.mark.parametrize` with literal values (ids for readability) |
| random/combinatorial inputs | Hypothesis `@given(strategy)`; strategies in `tests/support/` |
| looping over engine yield points | a replay helper in `tests/support/` that returns a trace; parametrize the fault |
| `try/except` to check errors | `# when / then` + `with pytest.raises(Exc):` |
| list/dict comprehensions | a builder in `tests/support/` or a literal |
| `x if cond else y` | parametrize both cases |
| waiting with sleep | the engine's `Sleep` command, or a barrier/event helper |

## Checklist before handing off
1. `uv run python -m tools.guards tests/...` clean.
2. `uv run pytest <file> -q` passes (or fails for the intended reason in the red phase);
   `uv run python -m tools.typetests <file>` for type tests.
3. Each test asserts one behaviour and its name says which.
