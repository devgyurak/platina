# ADR-0002: New IDs come from an injected source; the core never generates them

- Status: Accepted (maintainer, 2026-11-25)
- Date: 2026-11-25
- Related: design sections 4.2 ("client-generated ID is the default"), 4.5 (`Now`), 4.12,
  8.3 (retry with jitter), 10.5, 11.4, 11.10

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- Design section 4.2: `pk(generated="uuid7")` is the default, so `Order(...)` inside a pure use
  case knows the new ID. The design does not say *who* calls `uuid.uuid7()`.
- uuid7 reads the clock and a random source. If the core calls it, the core is no longer
  deterministic: replaying the engine with the same script (design section 11.4) produces
  different IDs on every run, and the guard's allowlist would need an exception.
- Time and jitter are already settled elsewhere: `Now` is a use-case parameter (section 4.5), and
  the backoff jitter's randomness is an explicit engine argument. This ADR is only about IDs.
- Unit tests build snapshots with `Order.stub(...)` and call use cases directly
  (section 4.12), outside any runner.

## Decision
1. **The engine installs, the runner only provides.** The runner passes an ID source to the
   engine as an argument, like the jitter's random source. The engine makes it the active source
   (a `contextvars` value) around each attempt's `uc.invoke(...)` and removes it afterwards; a
   retry gets fresh IDs, like a fresh `Now`. The real source (`uuid.uuid7()`) lives in the shell,
   where the guard allows it. Engine replay passes a fixed source directly, without a runner.
2. **An active source is never replaced.** Creating an entity (`Order(...)`, ADR-0003) takes its
   ID from the active source. When a use case or step is called directly, the call wrapper installs a source **only
   if none is active**; if one is (a use case running under `app.run` calling a step directly),
   it keeps using it. So a direct call nested inside a real run always gets real uuid7 IDs.
3. **Outside any run, IDs come from one fallback sequence.** A single process-wide deterministic
   sequence serves the two places that legitimately need IDs without a runner: a use case or step
   called directly with no active source (the call wrapper activates the fallback sequence for
   that call), and `Order.stub(...)`, which draws from it directly. There is no counter per call,
   so IDs are unique within the process: two direct calls in one test, and a stub plus the
   `Order(...)` inside the call under test, never collide.
   - The sequence is an `itertools.count()` whose `__next__` is the only operation used (no
     read-modify-write such as `n += 1`). The core cannot import `threading`, so a lock is not an
     option. Observed on free-threaded CPython 3.14.7 (macOS arm64; 8 threads x 200,000
     draws, 1.6 million per run, 5 runs): `itertools.count().__next__` produced 0 duplicates, a `box[0] += 1` counter
     up to about 1.2 million. That is an observation on one build, not a documented guarantee, so
     it is pinned as a unit test (`tests/unit/test_fallback_id_counter.py`, helper
     `tools/concurrent_draws.py`). The free-threaded CI job (design section 11.10,
     `make test-unit-ft`) runs it on 3.14t with the GIL off on every PR and fails if one of its
     cases did not pass, so it is a real check, not one that passes trivially under a GIL. The same
     run draws from a `box[0] += 1` counter as a control and fails if that gives no duplicates,
     so a green run also shows that the threads raced on that machine.
   - Fallback IDs are **version-8 UUIDs** with a fixed marker prefix and the sequence number in
     the low bits. Real IDs are version 7, so the two spaces cannot overlap.
   - The commit planner rejects a fallback-space ID with `UsageError` ("a test-only ID reached a
     commit"), so a stub or a direct-call result can never be written to the database.
   - Tests that need a specific value pass it explicitly (`Order.stub(id=...)`) or read it from
     the result; they do not rely on the sequence's position.
4. **`Order(...)` outside any invocation raises `UsageError`.** At module level, in a plain
   helper, or as an argument built by the caller (`app.run(create.bind(order=Order(...)))`)
   there is no active source, and the fallback sequence is *not* used: the mistake is reported
   where it is made ("`Order(...)` needs an active ID source: call it inside a use case or step,
   or use `Order.stub()` in tests"), not later at commit time.
5. **No special case for the test kit.** `Order(...)` and `Order.stub()` behave the same whether
   or not `platina.testing` is imported.
6. The guard keeps forbidding `uuid1/4/6/7/8` (called or referenced), clock calls and `random` in
   the core (A101/A106). Generating version-8 fallback IDs needs none of them (`uuid.UUID(int=...)`
   from the sequence number).

## Consequences
- Engine replay is bit-for-bit repeatable (fixed source); core laws and unit tests are
  deterministic for a given test order, and never depend on real time or randomness.
- One way to receive each value: time by the `Now` parameter, jitter by engine argument, IDs by
  the active source.
- The fallback sequence is the one piece of module-level mutable state in the core
  (`itertools.count`, see Decision 3), and the architecture rule names it as the only exception.
- Fallback ID *values* depend on test order (unique, but not stable across orderings); a test that
  prints or snapshots an ID passes it explicitly.
- When Hypothesis replays a failing example, fewer examples ran before it, so its IDs have other
  values; their relative order is kept. Laws must therefore not depend on ID values themselves -
  the same condition as in production, where uuid7 values are random too.
- The source is set and cleared in exactly two places - the engine's invocation step and the
  direct-call wrapper of `@usecase` / `@step` - covered by replay tests (installed per attempt,
  removed on every exit path) and unit tests (nested direct call keeps the outer source).

## Alternatives considered
- Core calls `uuid.uuid7()` directly (one allowlisted module): simplest, but replay and property
  tests become non-deterministic and the "no randomness in the core" rule gets an exception.
- A fresh counter per direct call: IDs collide between two calls in one test and between a stub
  and the call under test.
- The direct-call wrapper always installs its own source: under `app.run`, a step called directly
  would swap in counter IDs that reach the database and collide on the primary key across runs.
- Put `now` and the jitter random source into the same context: a second way to receive the time
  (besides the `Now` parameter), and hidden inputs to the retry policy.
- A test-kit exception (the kit installs the deterministic source): `Order(...)` would behave
  differently depending on an import, and direct calls without the kit would fail.
- IDs assigned at commit (placeholders until then): the pure function would no longer know the
  new ID, which section 4.2 explicitly wants (events, child rows referencing it).
- Pass an ID source as a use-case parameter (`ids: Ids = INJECTED`): explicit, but every use case
  that creates anything grows a parameter, and creating an entity in a `@step` needs it threaded
  through `chain`.

## History
- 2026-11-25 - created (raised by the pre-Phase-0 review).
- 2026-11-25 - review: narrowed the context to the ID source (time stays the `Now` parameter,
  jitter randomness is an engine argument) and replaced the test-kit exception with a
  deterministic source installed on direct calls.
- 2026-11-25 - review: the engine (not the runner) installs the source; an active source is
  never replaced by a nested direct call; one process-wide version-8 fallback sequence for direct
  calls and stubs, rejected at commit; renamed the file from
  `0002-injected-clock-ids-and-randomness.md`.
- 2026-11-25 - review: the fallback sequence is `itertools.count` (with the free-threading
  observation and the CI pin); `Order.new()` outside any invocation is `UsageError` again;
  Hypothesis replay note.
- 2026-11-25 - review: corrected the measurement (8 threads x 200,000 draws per run, not 1.6 million
  each); the experiment is now a unit test in the repository.
- 2026-11-25 - accepted by the maintainer.
- 2026-11-25 - creation is now the plain constructor `Order(...)` (ADR-0003); the text says
  `Order(...)` where it said `Order.new()`. No change to the decision.
- 2026-11-26 - the 3.14t CI job exists (issue #7): the counter test now runs with the GIL off on
  every PR; its helper moved to `tools/concurrent_draws.py`, and the run adds a `box[0] += 1`
  control that must show duplicates. No change to the decision.
- 2026-11-26 - control measured on the CI runner (GitHub `ubuntu-latest`, 4 CPUs, CPython
  3.14.10 free-threaded; PR #68, 6 runs of 8 threads x 200,000 draws): the `box[0] += 1` counter
  gave 778,539 to 1,279,674 duplicates per run, `itertools.count().__next__` 0. The margin is wide,
  so a control with 0 duplicates fails the run. No change to the decision.
