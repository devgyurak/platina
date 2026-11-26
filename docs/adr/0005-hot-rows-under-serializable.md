# ADR-0005: `lock="for_update"` is not an escape hatch from serialization failures

- Status: Accepted (maintainer, 2026-11-25)
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
- `40001` covers two different conflicts, and spike 0002 saw both messages:
  - **a write conflict on the same row** - `could not serialize access due to concurrent update`:
    the transaction modifies or locks a row that another transaction updated and committed after
    the first one's snapshot. It happens under REPEATABLE READ and SERIALIZABLE alike (observed
    under both in the reproduction's parts A and B; PostgreSQL 18 documentation 13.2.2, 13.2.3);
  - **an SSI read/write-dependency conflict** - `could not serialize access due to read/write
    dependencies among transactions` (observed with `Reason code: Canceled on identification as a
    pivot, during write` in part C, which ran under SERIALIZABLE only): reads and writes of
    different transactions form a cycle - the write-skew case. Only SERIALIZABLE raises it; that
    REPEATABLE READ does not is PostgreSQL's documentation (13.2.2, 13.2.3), not an observation of
    this spike.

  REPEATABLE READ + `version` is a real escape hatch from the second kind (8.3: at the price of not
  preventing write skew). This ADR is about the first kind, the hot row.
- Spike 0002 checked the first kind on PostgreSQL 18.6 with two sessions and a pinned worst-case
  interleaving (T2's snapshot taken first, as a use case's load stage is; T2 then waits on T1's row
  lock; T1 commits): under REPEATABLE READ and SERIALIZABLE, both a blind
  `UPDATE ... SET bal = bal + 1` and `SELECT ... FOR UPDATE` followed by the update end in T2 with
  `40001 could not serialize access due to concurrent update`; under READ COMMITTED both succeed
  (`spikes/0002-use-cases-on-paper/db_increment_conflicts.py`). The pg-researcher sub-agent
  reproduced all six results independently, with the lock wait observed in `pg_locks`, and ran
  design 4.6's statement order (`INSERT INTO run_claim` first, then `SELECT ... FOR UPDATE`, then
  the update) under both levels (spike 0002, Reproduction; scripts in
  `spikes/0002-use-cases-on-paper/repro/db/`, output regenerated into the git-ignored
  `results/repro-db/`). Its conditions:
  - the waiter fails with `40001` only when the holder **commits an actual update** of the row; a
    holder that only locked the row, or rolled back, lets the waiter commit;
  - a transaction that begins after the holder's commit does not fail;
  - the `run_claim` insert fixes the waiter's snapshot (a holder that commits between the waiter's
    insert and its lock request still makes it fail);
  - two waiters behind one holder both fail;
  - a waiter whose `statement_timeout` expires first gets `57014`, not `40001` (an observation;
    how a lock wait interacts with 4.6's retry rule is left to #61).

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
  claim, not measured here, and goes to 9.2. READ COMMITTED, where `FOR UPDATE` serialises writers
  without failures, is forbidden for commands (8.3), and that rule is right: the load plan needs
  one snapshot.

## Decision
1. Keep SERIALIZABLE + automatic retry and the ban on READ COMMITTED for commands.
2. Correct the text: neither `lock="for_update"` nor REPEATABLE READ is an escape hatch from the
   same-row write conflict (`40001 ... concurrent update`) on a row that concurrent commands
   update; a hot row costs a wait and a retry per conflicting writer (and, as 9.2 showed,
   `RetryExhausted` under sustained contention). REPEATABLE READ + `version` stays the escape hatch
   from SSI's read/write-dependency conflicts (`40001 ... read/write dependencies`), as 8.3 says.
   7.3 and 8.3 say both; 4.6's mapping of `@Lock(PESSIMISTIC_WRITE)` says what the profile does
   here; 4.4 says `.add(n)` avoids the read, not the conflict.
3. 9.2 measured it (spike 0003, C4): on one hot row `for_update` fails as often as a blind
   increment and only moves the failure to the load stage. The profile is documented as "fail
   early" (the conflict surfaces at the load stage, before the use case runs), not as an escape
   hatch. Keeping or removing `lock=`, and the 3.1 / 4.3 notation (spike 0002 X12), are separate
   decisions for the maintainer in #64.
4. 7.3 lists candidates for genuinely hot rows, to be compared in #64 with spike 0003's C4 as the
   baseline; which direction the design takes - a different model, a lock taken before the
   transaction, or accepting the retries - is decided there, not here. Candidates: append-only rows
   with a total computed on read (a ledger of legs - which helps only writers that do not read the
   total; an overdraft check that sums an account's legs under SERIALIZABLE conflicts with
   concurrent inserts of legs for that account), an async projection of the total, a counter kept
   outside the SERIALIZABLE transaction, and a session-level advisory lock taken before `BEGIN`
   (Alternatives, unverified). An inline projection is not a candidate: it updates its target row
   inside the same SERIALIZABLE transaction and meets the same `40001` (which is why 8.4 restricts
   inline keys).

## Consequences
- The design stops promising something PostgreSQL does not do: users with a hot row learn early
  that neither `lock="for_update"` nor REPEATABLE READ removes the retries on that row. What to
  use instead is decided in #64.
- 9.2 (spike 0003, #3) gets one more item, on the durable profile: the retry rate, the
  `RetryExhausted` rate and the `57014` rate on one hot row with and without `for_update`. The
  comparison of the candidates of point 4, including the session-level advisory lock before
  `BEGIN`, is #64, which uses that measurement as its baseline; it is not part of 9.2.
- Use cases with a hot row and a rule that reads it (stock allocation, an overdraft check) stay on
  retries until that decision is made.

## Design text changed on acceptance
On acceptance (2026-11-25), in `docs/design/design.md` and `docs/design/design-KO.md`:
- 7.3, first paragraph (line 863): the "under review" note became the decision - two kinds of
  `40001`; REPEATABLE READ + `version` escapes the read/write-dependency kind; neither
  `lock="for_update"` nor a blind increment avoids the same-row kind on a hot row; the profile
  counts as "fail early"; whether `lock=` stays and the approach for hot rows are decided after
  9.2 (candidates here, not repeated there). Links this ADR.
- 8.3 "Default isolation level", the "Escape hatch" bullet (line 991): REPEATABLE READ + `version`
  escapes SSI's read/write-dependency failures; there is no escape hatch from the same-row `40001`;
  the profile only makes the conflict surface at the load stage. Links this ADR.
- 4.4, the `.add(n)` row of the write table (line 353): "concurrent writers of the same row still
  conflict with 40001".
- 4.6, the Spring/JPA mapping row `@Lock(PESSIMISTIC_WRITE)` (line 555): under SERIALIZABLE a
  waiter still fails with `40001` once the holder has updated and committed, and is retried - not
  an escape hatch.
- 3.1, "Pessimistic locking" (line 137): the lock is taken at the load stage and fails early; it
  does not avoid the same-row `40001`; whether `lock=` stays is decided after 9.2.
- 4.3, the `for_update` profile comment (line 311): "row lock at the load stage: fails early, does
  not avoid 40001".

The 3.1 / 4.3 notation difference (spike 0002 X12) is left as it was (Decision 3). The candidate
of a session-level advisory lock before `BEGIN` is not mentioned in the design text: it is
unverified.

## Alternatives considered
- Allow READ COMMITTED + `for_update` for named hot-row use cases: removes the failures but breaks
  the single-snapshot premise of the load plan (8.3) and a design invariant; it would need its own
  ADR and a rule for which loads may see different snapshots.
- A lock taken inside the transaction before the snapshot is fixed.
  [13.4.2](https://www.postgresql.org/docs/18/applevel-consistency.html) advises obtaining locks
  before the first query, but its sentence names Repeatable Read only; the reproduction observed a
  `LOCK TABLE` before the first query avoiding the failure under both levels. Inside the
  transaction the run-ID insert into `run_claim` must be the first statement (8.3); after that
  insert the same `LOCK TABLE` fails with `40001` (observed), and so does `pg_advisory_xact_lock`
  as the first statement (observed). `LOCK TABLE` also locks the whole table. Rejected for a lock
  inside the transaction.
- **A session-level advisory lock taken before `BEGIN`** (`pg_advisory_lock` on a key derived from
  the ref, released after `COMMIT` / `ROLLBACK`). **Unverified candidate**, for #64. Basis:
  the same principle as the observed `LOCK TABLE` before the first query - a writer that waits
  before its snapshot exists sees the holder's committed update instead of conflicting with it.
  Not resolved:
  - it serialises only writers that take the same lock; any other write of the row (a set change,
    another use case, another ORM) still conflicts;
  - the order of locks when a use case touches several hot keys (deadlocks across sessions);
  - release when the connection goes back to the pool (a session lock outlives the transaction),
    including after cancellation and errors;
  - how it fits the pipelined batches of 4.6 (it must complete before `BEGIN`, which adds a round
    trip) and the run-ID claim;
  - not tested in this spike.
- Keep `for_update` with a retry policy tuned for lock waiters (retry at once, no backoff, after a
  wait-then-`40001`): reduces latency but not the number of failures; a candidate for #64.
- A hot counter updated in a short separate non-SERIALIZABLE transaction or table, like the
  internal-table rule (8.3): fast, but the counter is no longer part of the use case's atomic
  change; listed under point 4 as a candidate, not decided here.
- Remove `lock=` now: possibly right, but that is a decision on public syntax for the maintainer,
  and #64 can first show whether failing early pays for itself.
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
- 2026-11-25 - at the maintainer's request, without changing the direction: the two kinds of
  `40001` (same-row write conflict vs SSI read/write dependency) distinguished in Context and
  Decision 2, REPEATABLE READ + `version` kept as the hatch for the second kind; `57014` moved out
  of Decision 2 into the observations; "modelling is the direction" deferred to after 9.2; the
  session-level advisory lock before `BEGIN` added as an unverified candidate and the
  in-transaction lock rejection narrowed; the design locations to change on acceptance listed;
  line wrapping fixed.
- 2026-11-25 - accepted by the maintainer. The design text listed in this ADR was changed (section
  "Design text changed on acceptance", EN + KO); the `57014` question is #61.
- 2026-11-25 - at the maintainer's decision, without changing the direction: Consequences now
  splits the 9.2 work - spike 0003 measures the single hot row (retry, `RetryExhausted` and
  `57014` rates with and without `for_update`); the comparison of point 4's candidates moves to a
  follow-up issue (#64) with that measurement as its baseline.
- 2026-11-26 - at the maintainer's decision, without changing the direction: the "until / after
  9.2" wording of Decisions 2-4, Consequences and Alternatives now states what 9.2 (spike 0003,
  C4) measured - `for_update` does not reduce the failures on a hot row, `RetryExhausted` occurs
  under sustained contention - and points the open decisions (`lock=`, the hot-row approach, the
  candidate comparison) to #64.
