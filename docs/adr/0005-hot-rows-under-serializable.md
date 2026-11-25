# ADR-0005: `lock="for_update"` is not an escape hatch from serialization failures

- Status: Proposed
- Date: 2026-11-25
- Related: design sections 3.1, 4.3, 4.4, 4.6 (Spring/JPA mapping), 7.3, 8.3 ("Default isolation
  level", "Retry policy", "The roles of version"), 8.4, 9.2, 9.4; issue #5; spike 0002
  (`docs/spikes/0002-use-cases-on-paper.md`, X8)

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- The design names two ways out for hot rows under the SERIALIZABLE default: "For hot rows you
  have to step down to `lock="for_update"` or `isolation=REPEATABLE_READ` + `version`" (7.3), and
  "Escape hatch: `@usecase(isolation=REPEATABLE_READ)` + `version`, or a `lock="for_update"`
  profile" (8.3). 4.4 offers `.add(n)` as a DB-side increment that "does not read the current
  value", and 9.4 tests "commutative increments" (use case 8).
- 8.3 already records that under REPEATABLE READ, "modifying a row that was updated concurrently
  makes PostgreSQL raise 40001 first" (the `StaleSnapshot` correction). It does not draw the
  consequence for the lock profile or for increments.
- Spike 0002 checked it on PostgreSQL 18.6 with two sessions and a pinned worst-case interleaving
  (T2's snapshot taken first, as a use case's load stage is; T2 then waits on T1's row lock; T1
  commits): under REPEATABLE READ and SERIALIZABLE, both a blind `UPDATE ... SET bal = bal + 1` and
  `SELECT ... FOR UPDATE` followed by the update end in T2 with `40001 could not serialize access
  due to concurrent update`; under READ COMMITTED both succeed
  (`spikes/0002-use-cases-on-paper/db_increment_conflicts.py`). The pg-researcher sub-agent
  reproduced all six results independently, with the lock wait observed in `pg_locks`, and ran
  design 4.6's statement order (`INSERT INTO run_claim` first, then `SELECT ... FOR UPDATE`, then
  the update) under both levels (spike 0002, Reproduction, `results/repro-db/`). Its conditions:
  - the waiter fails with `40001` only when the holder **commits an actual update** of the row; a
    holder that only locked the row, or rolled back, lets the waiter commit;
  - a transaction that begins after the holder's commit does not fail;
  - the `run_claim` insert fixes the waiter's snapshot (a holder that commits between the waiter's
    insert and its lock request still makes it fail);
  - two waiters behind one holder both fail;
  - a waiter whose `statement_timeout` expires first gets `57014`, not `40001`.

  One run per scenario on the fast profile: it shows that it happens, not how often. It matches
  PostgreSQL's documented rule for these levels
  ([13.2.2 Repeatable Read Isolation Level](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-REPEATABLE-READ):
  a transaction that tries to modify or lock a row changed by a transaction that committed after
  its snapshot is rolled back with a serialization failure;
  [13.2.3](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-SERIALIZABLE) applies the
  same to SERIALIZABLE).
- So under the isolation levels commands may use, a hot row is resolved by a wait and a retry
  whatever the syntax: `for_update` moves the failure from the commit batch to the load stage, and
  `.add(n)` avoids reading the old value but not the conflict. Every waiter whose snapshot predates
  a committed update of the row fails once and retries. With `max_attempts=4` (8.3 "Retry policy")
  sustained contention on one row may end in `RetryExhausted` for some callers; that is a rate
  claim, not measured here, and goes to 9.2. A waiter that hits `statement_timeout` first ends
  with `57014`, which 4.6's retry rule (`40001` / `40P01`) does not retry. READ COMMITTED, where `FOR UPDATE` serialises writers
  without failures, is forbidden for commands (8.3), and that rule is right: the load plan needs
  one snapshot.

## Decision
1. Keep SERIALIZABLE + automatic retry and the ban on READ COMMITTED for commands.
2. Correct the text: `lock="for_update"` and REPEATABLE READ are not escape hatches from
   serialization failures on a row that concurrent commands update. A hot row costs a wait and a
   retry per conflicting writer (and, if 9.2 shows it, `RetryExhausted` under sustained contention;
   a wait longer than the timeout ends in `57014`). 7.3 and 8.3 say
   so, 4.6's mapping of `@Lock(PESSIMISTIC_WRITE)` says what the profile does here, and 4.4 says
   `.add(n)` avoids the read, not the conflict.
3. Until 9.2 measures it, the profile is documented as "fail early" (the conflict surfaces at the
   load stage, before the use case runs), not as an escape hatch. Keeping or removing `lock=`, and
   the 3.1 / 4.3 notation (spike 0002 X12), are separate decisions for the maintainer after 9.2.
4. 7.3 names modelling as the direction for genuinely hot rows and lists the candidates to measure
   in 9.2, without claiming any of them as the answer: append-only rows with a total computed on
   read (a ledger of legs - which helps only writers that do not read the total; an overdraft check
   that sums an account's legs under SERIALIZABLE conflicts with concurrent inserts of legs for
   that account), an async projection of the total, or a counter kept outside the SERIALIZABLE
   transaction. An inline projection is not a candidate: it updates its target row inside the same
   SERIALIZABLE transaction and meets the same `40001` (which is why 8.4 restricts inline keys).

## Consequences
- The design stops promising something PostgreSQL does not do; users with a hot row learn early
  that the fix is the model, not a flag.
- 9.2 gets one more item: the retry rate, the `RetryExhausted` rate and the `57014` rate on one
  hot row with and without `for_update`, on the durable profile, and the candidates of point 4.
- Use cases with a hot row and a rule that reads it (stock allocation, an overdraft check) stay on
  retries until a modelling decision is made.

## Alternatives considered
- Allow READ COMMITTED + `for_update` for named hot-row use cases: removes the failures but breaks
  the single-snapshot premise of the load plan (8.3) and a design invariant; it would need its own
  ADR and a rule for which loads may see different snapshots.
- Lock before the snapshot is taken. [13.4.2](https://www.postgresql.org/docs/18/applevel-consistency.html)
  advises obtaining locks before the first query, but its sentence names Repeatable Read only; the
  reproduction observed a `LOCK TABLE` before the first query avoiding the failure under both
  levels. It locks the whole table, and the run-ID insert into `run_claim` must be the first
  statement (8.3); after that insert the same `LOCK TABLE` fails with `40001` (observed), and so
  does `pg_advisory_xact_lock` as the first statement. Rejected.
- Keep `for_update` with a retry policy tuned for lock waiters (retry at once, no backoff, after a
  wait-then-`40001`): reduces latency but not the number of failures; a candidate for 9.2.
- A hot counter updated in a short separate non-SERIALIZABLE transaction or table, like the
  internal-table rule (8.3): fast, but the counter is no longer part of the use case's atomic
  change; listed under point 4 as a candidate, not decided here.
- Remove `lock=` now: possibly right, but that is a decision on public syntax for the maintainer,
  and 9.2 can first show whether failing early pays for itself.
- Leave the text and let 9.2 find it: the current text is wrong today, and 9.4 already depends on
  it (use cases 4 and 8).

## History
- 2026-11-25 - created (Proposed) from spike 0002.
- 2026-11-25 - revised after the architect review: one unreproduced run stated, PostgreSQL
  reference and the retry limit added; point 3 no longer pre-decides removing `lock=`; point 4
  drops the inline projection and states the candidates as candidates; three alternatives added.
- 2026-11-25 - after the pg-researcher reproduction: the observation is reproduced, with its
  conditions (only a committed update of the row makes a waiter fail; `run_claim` fixes the
  snapshot; `57014` on timeout); "every waiter fails once" narrowed to that condition; the
  `RetryExhausted` statement marked as an unmeasured rate claim for 9.2; the `LOCK TABLE`
  alternative restated from the observation; documentation links pinned to `/docs/18/`. The
  direction is unchanged.
