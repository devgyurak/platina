---
name: core-testing
description: Testing the sans-I/O core without a database - Hypothesis laws for ChangeSet/chain/planner/load plans, engine replay with fault injection at every yield point, compiler snapshots. Use when adding or changing anything under src/platina/core or src/platina/sql.
---
# Testing the core (design sections 11.3 and 11.4)

The core has no I/O, so it is tested by laws and by replay - never against a database, never
with sleeps. Helper logic (strategies, replay drivers, reference models) lives in
`tests/support/`; test modules stay free of control flow.

## Laws (Hypothesis)
State the property, generate the inputs, assert it holds. Examples the design names:
- `chain` of steps f, g == applying f, then running g on the result.
- Reading any field through an alias made before `chain` raises `MovedSnapshotAccess`.
- The number of executed load stages equals the depth computed at seal, for every condition
  outcome.
- Replaying the planner's order against a small constraint-only reference model never violates
  an FK or unique constraint.
Strategies go in `tests/support/strategies.py` (create it with the first law): keep them small,
bounded and deterministic in shape. Re-run a failure with `--hypothesis-seed=<seed>`.

## Engine replay with fault injection
The engine is a generator `Generator[Command, Reply, RunResult]`. A replay helper in
`tests/support/` drives it with scripted Replies and returns a trace (commands seen, attempts,
run IDs, whether a commit was applied).
- Build the happy-path script once per use case under test.
- Parametrize the fault (`serialization failure`, `deadlock`, `connection lost`, `cancelled`) and
  the yield-point index; the helper injects it with `gen.throw()` at that point.
- Assert on the trace: no commit after the error, ends with rollback or retry, retries restart at
  `Begin` with the first load stage, the run ID is the same across attempts, commit-unknown is
  resolved by re-running with that ID, `Sleep` carries the backoff (no real time passes).
- Shield behaviour is a runner property: test that `CommitBatch`/`Rollback` are not interrupted
  by cancellation in the runner's own tests.

## Compiler snapshots
Compile AST nodes to SQL and compare with a stored snapshot (inline-snapshot once added as a
dependency, with a justification in the PR). Every snapshotted statement is also PREPAREd against
real PostgreSQL in an integration test, so a snapshot cannot hide a syntax error.

## Free-threaded
Core unit tests are meant to run on 3.14t with pytest-run-parallel (design section 11.10); avoid
module-level mutable state in tests as in code.
