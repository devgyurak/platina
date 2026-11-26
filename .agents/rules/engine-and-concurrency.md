---
description: Engine state machine, retries, run IDs, cancellation, pipelines and PostgreSQL concurrency rules
paths:
  - "src/platina/core/engine/**"
  - "src/platina/runners/**"
  - "src/platina/drivers/**"
  - "src/platina/outbox/**"
---
# Engine and concurrency rules

Source of truth: `docs/design/design.md` sections 4.6, 4.10, 8.3, 8.4 and 10.5. Read them before
changing anything here; SSI interactions are where reviewers and the designer have repeatedly
been wrong on paper (design section 9), so prefer a measurement over an argument.

1. **Retry is the engine's job, from the top.** On 40001/40P01 the engine yields `Rollback`, then
   `Sleep(backoff)` (exponential, full jitter, injected randomness), and restarts from `BEGIN` and
   the first load stage. Injected values (`Now`, ...) are fresh per attempt. A domain exception
   rolls back and propagates; it is never retried by the engine. `57014` is never retried:
   `timeout=` is one budget for the whole run (ADR-0008) - the runner reports a passed deadline
   (`DeadlineReached`, also instead of a `Sleep` that would cross it), the engine emits the
   `set_config('statement_timeout', $1, true)` statement and turns the deadline or a budget
   `57014` before `COMMIT` into `RunTimeout`.
2. **Run IDs decide "did it commit?"** Every run claims its ID with `INSERT INTO run_claim` as the
   first table statement (after `BEGIN` and the budget), without a read. Unknown commit outcome (connection lost during the commit
   batch, failover) is resolved by re-running with the **same** run ID - never by
   `pg_xact_status`. Caller keys store the result in `run_result` (INSERT, never UPDATE of
   `run_claim`) with the call's fingerprint, compared only on the `23505` replay path
   (`IdempotencyKeyReuse`, #58); replayed tokens fetch a fresh LSN. An unknown outcome is
   resolved first by `ResolveClaim` (a claim of the same run ID; not an attempt, not bounded by
   the deadline): `23505` -> the replay path; success -> `Rollback`, then a normal attempt from
   `BEGIN` and the claim (ADR-0008 Decision 6). Only then may a deadline or the retry limit end
   the run.
3. **Inside SERIALIZABLE, internal tables are INSERT only** (`run_claim`, `run_result`, outbox
   log, job tables, checkpoints): no read, no UPDATE - B-tree leaf-page predicate locks on
   ever-growing keys turn unrelated commands into serialization failures. Reads go to a separate
   READ COMMITTED transaction. Outside SERIALIZABLE, consumer checkpoints (REPEATABLE READ) and job
   leases (READ COMMITTED) are updated as design section 8.4 describes; `run_claim`, `run_result`
   and the outbox log are never updated.
4. **Cancellation.** The commit batch and rollback run under `anyio.CancelScope(shield=True)` in
   the runner. Cancellation during load or computation rolls back. Never swallow the cancellation
   exception; every acquired connection is released on every path.
5. **Pipeline semantics.** A load stage is one pipeline round trip; the commit batch (writes,
   inline projections, outbox, run result, `pg_current_xact_id()`, `COMMIT`,
   `pg_current_wal_insert_lsn()`) is one round trip. A failing statement aborts the rest of the
   pipeline - rely on that, and test it against real PostgreSQL. `COPY` never runs in a pipeline.
   The commit outcome is read by **position**, never by SQLSTATE alone: an error before or on
   `COMMIT` is a rollback, a successful `COMMIT` result is committed whatever follows, no reply is
   unknown (ADR-0008).
6. **Commit order** is the planner's dependency graph (FK + unique keys, freeing a value before
   taking it), batched; cycles are reported (`CommitCycle`), not guessed.
7. **Workers and dispatchers** (`then`, `@process`): leases are taken in short READ COMMITTED
   transactions with `SKIP LOCKED`; external I/O never runs while a transaction (and its xid) is
   open; completion and fencing are the job-ID-as-run-ID `run_claim` INSERT; at most one in-flight
   job per aggregate key; a dead-lettered head blocks its key.
8. **Async projection consumers** commit effect + checkpoint in one REPEATABLE READ transaction
   and stop on a poison message; they never skip.
9. **Consistency token** = (xid, insert LSN). Use `pg_current_wal_insert_lsn()`, not
   `pg_current_wal_lsn()`.
10. **Errors** map SQLSTATE to the hierarchy of design section 10.12 in `platina.drivers`, keeping
    the SQLSTATE and the original exception. Replies report per-statement facts (which statement
    failed, whether the deadline had passed); what they mean for the run - rollback, committed,
    `RunTimeout`, the hinted error for `42P01` / `42703` / `42501` on an internal table
    (ADR-0009) - is decided by the engine, which built the statements.
