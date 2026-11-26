# ADR-0008: `timeout=` is one budget for the whole run; `57014` and the deadline raise `RunTimeout`

- Status: Proposed
- Date: 2026-11-26
- Related: design sections 4.1, 4.5, 4.6 ("Options", "Execution order", "Exception handling"),
  8.3 ("Retry policy"), 10.5, 10.12; issue #61 (decided 2026-11-26), #17, #22, #64, #74;
  ADR-0005, ADR-0006; spikes 0002 (the one `57014` observed) and 0003 (C4: none at 2 s)

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- Design 4.6 wrote `timeout="2s"` as `SET LOCAL statement_timeout = '2s'` at `BEGIN` of each of up
  to 4 attempts, and did not say what a `57014` (`query_canceled`) does. The maintainer decided
  #61 on 2026-11-26: `57014` is not retried, it becomes a named error (working name `RunTimeout`),
  `timeout=` is a budget for the whole run, and there is no `lock_timeout` option. Three questions
  were left for this ADR: how the clock-free core gets the remaining budget, how the client-side
  deadline relates to the server's `57014`, and whether the server-side budget applies to the
  commit batch.
- Facts established for this ADR (pg-researcher, PostgreSQL 18.6, psycopg 3.3.9 / libpq 18.0.6,
  one run each in throwaway databases, summarised in the
  #61 decision comment, not reproduced by a
  second agent; the synchronous-replication case ran in a separate `postgres:18` container,
  because `synchronous_standby_names` is server-wide):
  - **`statement_timeout` limits each statement, also inside a pipeline.** "In extended query
    protocol, the timeout starts running when any query-related message (Parse, Bind, Execute,
    Describe) arrives, and it is canceled by completion of an Execute or Sync message" (PostgreSQL
    18, `runtime-config-client`). The per-Execute behaviour dates from PostgreSQL 11 (release
    notes: "make statement_timeout apply to each Execute message separately, not to all commands
    before Sync"), and `finish_xact_command` disabling the timer before the commit work is older
    still; the observations are from 18.6 only, and the PostgreSQL 14-18 integration matrix of
    #17 pins them. psycopg sends no Sync between
    pipelined statements (`_pipeline_base.py`, `_enqueue_sync`). Observed: three
    `pg_sleep(0.6)` in one pipeline under `SET LOCAL statement_timeout = '1s'` completed in 1.81 s
    without error; one `pg_sleep(1.2)` got `57014` at 1.00 s.
  - **A `57014` before `COMMIT` in the commit batch is a definite rollback**: the pipeline skips
    the rest, including `COMMIT`; `pg_xact_status` was `aborted`.
  - **`COMMIT` itself is not limited by `statement_timeout`.** `finish_xact_command` disables the
    timer before `CommitTransactionCommand()` (`postgres.c`), so deferred triggers and constraint
    checks, the SSI pre-commit check, the WAL flush and a synchronous-replication wait run
    unbounded. Observed: a 1 s deferred trigger under a 500 ms timeout committed.
  - **A cancel during a synchronous-replication wait does not roll back**: the client gets
    `COMMIT` plus `WARNING: canceling wait for synchronous replication due to user request ... The
    transaction has already committed locally` (`syncrep.c`, `SyncRepWaitForLSN`); a terminated
    backend loses the connection with the transaction committed. Neither `statement_timeout` nor
    `transaction_timeout` fired during that wait.
  - **Statements after `COMMIT` run under the session's `statement_timeout`** (`SET LOCAL` ends
    with the transaction): a `57014` on the post-commit `pg_current_wal_insert_lsn()` query came
    after a committed transaction, and psycopg raises it at pipeline exit like any other error -
    only the per-statement results show that `COMMIT` succeeded. From the source only (not
    observed): a timeout that fires in a narrow window at the end of `COMMIT`'s Execute can
    surface on the next statement after the commit.
  - `transaction_timeout` (PostgreSQL 17+) spans the transaction but terminates the session
    (observed: connection lost, no SQLSTATE), so it is not a statement-level budget.

## Decision
1. **`timeout=` is one deadline for the run**, measured by the runner from the start of `app.run`
   (pool acquisition included) across every attempt, round trip, use case invocation and backoff.
   It is set the existing three ways (`TxDefaults`, `@usecase`, `app.run`); the default is no
   budget. `TxDefaults(statement_timeout=...)` is renamed `TxDefaults(timeout=...)`, since it no
   longer means PostgreSQL's setting.
2. **The runner reports facts, the engine decides** (the core reads no clock; a runner makes no
   decisions).
   - The engine emits `set_config('statement_timeout', $1, true)` as a compiled statement at the
     head of every round trip before `COMMIT` (not when there is no budget); the runner only binds
     the remaining milliseconds, rounded up, never below 1 (`0` would switch the timeout off). The
     arithmetic is a pure helper in the engine package that takes the runner's clock reading.
   - The runner reports its deadline as a bare fact, `DeadlineReached`, at the yield point where it
     notices it: before sending a `Pipeline` or a `CommitBatch`, or instead of a `Sleep` that would
     end past the deadline. It never checks it before `Rollback`, `ResolveClaim`, `StoredResult` or
     `FreshLsn` (Decision 6). Replies to `Pipeline` and `CommitBatch` carry the per-statement outcome (the index
     of the failing statement and its SQLSTATE, or "connection lost") and whether the deadline had
     passed when the reply arrived.
   - The engine turns `DeadlineReached`, and a `57014` that arrives with the deadline passed on a
     statement before `COMMIT`, into a rollback and **`RunTimeout`, never retried**. A `57014` with
     the deadline not passed (`pg_cancel_backend`, a role's own `statement_timeout`) stays
     `DatabaseError(57014)`. Design 10.5's `Begin` loses its `timeout` field.
   - Both runners give the same guarantee: the deadline is checked at every yield point and the
     server bounds each statement. Interrupting a round trip already in flight on the client side
     (the async runner's cancel scope; a watchdog calling psycopg's `cancel_safe()` in the sync
     runner) is decided with #17, after pg-researcher has established what psycopg leaves on the
     connection when a pipeline is interrupted. The runner's own deadline is told apart from an
     outer cancellation, which still propagates.
3. **One error for both sides.** `RunTimeout` sits directly under `PlatinaError` (a deadline is
   neither a conflict nor a database fault; the client-side deadline has no SQLSTATE). Its own
   fields (ADR-0006): `budget: timedelta`, `stage: Literal["load", "use case", "backoff",
   "commit"]` and `sqlstate: str | None` (`"57014"` when the server cancelled). In the `"backoff"`
   stage the last `40001` is its `__cause__`. It is distinct from `RetryExhausted` ("the row was
   contended" and "the deadline passed" call for different reactions).
4. **The commit batch: the budget applies up to `COMMIT`, not to it.** The statements before
   `COMMIT` carry the remaining budget server-side; a budget `57014` there is a definite rollback
   and becomes `RunTimeout`. `COMMIT` itself and what follows cannot be bounded without making the
   outcome unknown (PostgreSQL does not time out `COMMIT`; a cancelled sync-rep wait still
   commits), and the batch stays shielded from client-side cancellation (4.6).
5. **Commit outcome by position, not by SQLSTATE**, decided by the engine from the per-statement
   reply:
   - an error on a statement before `COMMIT`, or on `COMMIT` itself (a `40001` from the SSI
     pre-commit check, a deferred constraint), is a rollback, classified as usual (`40001` is
     retried);
   - a successful `COMMIT` result means committed, whatever a later statement reports (a `57014`
     on the LSN query included; the LSN is then queried fresh, as on the replay path);
   - no `COMMIT` result and no error (connection lost) is unknown: `CommitUnknown`.
6. **An unknown outcome is resolved before any deadline or retry limit ends the run.** After
   `CommitUnknown` the engine yields its own command, `ResolveClaim` (`BEGIN` and the claim
   INSERT only, no `set_config`, no load), which the runner sends without a deadline check; it may
   wait on the earlier transaction. A `23505` means the earlier attempt committed: the result is
   returned as on the replay path (`StoredResult` / `FreshLsn`, also unbounded), never an error. A
   successful claim means it did not commit: the run continues in that transaction, bounded again
   - the deadline check comes first, then the load round trip with its `set_config` - so
   `RunTimeout` or `RetryExhausted` is raised only once the outcome is known. This also closes the
   same gap for `RetryExhausted` after a `CommitUnknown` on the last attempt.
7. **No `lock_timeout` option and no retry of `55P03` in Phase 1** (#61; revisit with #64). A user
   who sets `lock_timeout` themselves gets `DatabaseError(55P03)`.

## Consequences
- "`timeout="2s"`" means what a caller expects for everything before `COMMIT`; a waiter behind a
  hot row either gets `40001` and retries inside its budget, or runs out of it and fails with
  `RunTimeout` (ADR-0005's hot-row text is unchanged).
- The server-side value is a per-statement ceiling, not the budget: within one round trip, N
  statements can each run up to the remaining time. In the shielded commit batch it is the only
  bound.
- A run can exceed its budget by its own `COMMIT` (deferred constraints, the WAL flush) - without
  limit when a synchronous standby is down, since PostgreSQL waits for it - and by the resolution
  of an unknown commit outcome.
- The engine's replay tests inject `DeadlineReached` at every yield point like any database error,
  and the per-statement `CommitBatch` reply with the error before, at and after `COMMIT`; after a
  `CommitUnknown`, no injected deadline may produce `RunTimeout` or `RetryExhausted`.
- `RunTimeout` is added to `platina.core.errors` with #17; until then 10.12 lists it as decided.
- One `set_config` per round trip inside the pipelines that already exist: no extra round trip.
- `timeout=` on `app.run` is a run option, not an async-function timeout (ruff `ASYNC109`, spike
  0001 L3): an outer `anyio.fail_after` around `app.run` is a cancellation (rollback unless the
  commit batch is running, no `RunTimeout`, no server-side limit, nothing in the sync runner).

## Alternatives considered
- **Retry `57014`** (option 2 of #61): spends more than the caller allowed and repeats the same
  wait; PostgreSQL singles out `40001` / `40P01` as retryable.
- **`SET LOCAL statement_timeout` once at `BEGIN` as the budget**: limits each statement, not the
  attempt (fact above), and resets on each attempt.
- **`transaction_timeout`**: terminates the session and is not armed during `COMMIT`.
- **The runner maps `57014` to the deadline error itself**: it would have to know which statement
  is `COMMIT` and would report a committed run as rolled back on a post-`COMMIT` `57014`.
- **Bound the commit batch client-side too** (cancel it at the deadline): a cancel that lands on
  `COMMIT`'s deferred work or the sync-rep wait makes the outcome unknown or commits anyway - the
  shield exists to avoid exactly that.
- **`lock_timeout` + retry of `55P03`**: an option whose value interacts with `statement_timeout`
  and turns a wait into more retries on the rows ADR-0005 says cannot escape them (#64).

## History
- 2026-11-26 - created (Proposed) from the maintainer's #61 decision and pg-researcher's
  `statement_timeout` / commit-batch facts.
- 2026-11-26 - amended after the architect review: the engine emits the `set_config` statement
  and classifies every outcome (the runner reports facts), the remaining time never rounds to 0,
  an error on `COMMIT` itself is a rollback, an unknown outcome is resolved before `RunTimeout` or
  `RetryExhausted`, a non-budget `57014` stays `DatabaseError`, the sync runner's guarantee, the
  field types, the version range of the facts.
- 2026-11-26 - round 2 of the architect review: the resolving claim is its own command,
  `ResolveClaim`, never stopped by the deadline, and the replay reads are unbounded.
