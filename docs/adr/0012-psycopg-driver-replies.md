# ADR-0012: The psycopg driver returns per-statement replies from autocommit sessions

- Status: Proposed
- Date: 2026-11-26
- Related: design sections 4.6 ("Execution order", "Exception handling"), 5, 8.6, 10.2, 10.3,
  10.5, 10.6, 10.12, 11.5; issue #18, and the scope notes it left on #9, #16, #17, #19, #20
  (2026-11-26); ADR-0001, ADR-0006 (amended by decision 6), ADR-0008, ADR-0010 (decision 7,
  carried out by decision 6)

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- Design 10.5 has the runner catch `psycopg.Error` and map it (`map_sqlstate(e)`), and design 5
  acquires connections with `pool.connection()`. Since then: only `platina.drivers` may import
  psycopg (guard A102), so the runners cannot catch its exceptions; exception fields are read-only
  (ADR-0006), so the mapping needs the use case when it builds the exception; and ADR-0008 decides
  the commit outcome by position - an error before or at `COMMIT` is a rollback, a `COMMIT` result
  means committed, no result after a lost connection means unknown. The driver must report
  positions, not just raise.
- Agreed with the maintainer while planning #18 (2026-11-26): the SQLSTATE mapping lives in
  `platina.drivers` and its caller passes `usecase`; the driver classifies nothing (retry,
  `AlreadyClaimed`, commit-unknown, `57014` / `53200` stay #17's); runtime dependency
  `psycopg[pool]>=3.3` with the binary for development only; hand-written thin sync and async
  variants until #19's generator; adapters per pool, none custom in #18.
- Facts (pg-researcher, psycopg 3.3.9 binary / libpq 18.0.6 / psycopg_pool 3.3.3, PostgreSQL 18.6,
  CPython 3.14.7; experiments in a throwaway database, sync and async alike; protocol messages
  counted through a TCP proxy because libpq tracing is Linux-only in the binary build). Pinned by
  the integration tests of #18 except where marked:
  - F1 With `autocommit=False` psycopg sends its own `BEGIN` and a Sync before the pipeline (one
    more round trip, notice `25001` on our `BEGIN`). With `autocommit=True` the wire carries
    exactly our statements and one Sync (proxy count, not pinned by a test). psycopg sends a Flush
    after the Sync; after such a round trip the server does not apply
    `idle_in_transaction_session_timeout` (independent review: `25P03` after 1 s without a
    pipeline, the session still alive after a pipeline), so the server will not reap the open
    transaction of a runner that stalls between round trips.
  - F2 One cursor per statement inside `conn.pipeline()`, read after the block: one round trip;
    fetching after the block sends nothing. `executemany(returning=True)` adds a round trip.
  - F3 The first error's own class is raised, at block exit or from a later `execute()`. If an
    exception escapes the block, psycopg logs and drops any error the exit then finds (#18
    review: a server error at statement j followed by a client-side error at k > j surfaced as
    k's error); caught inside the block, the exit raises the earlier server error, or
    `PipelineAborted` when the in-block error was already the server's (observed). A statement that
    failed or was not run holds no result (`pgresult is None`), nor does any later one; the
    earlier ones keep theirs. A statement whose result could not be set up - a caller's loader
    raising in its constructor, a psycopg error or not - holds a `pgresult` without a command tag:
    it ran (second independent review: `Failed` at it while the server had committed). A
    deferred constraint failing at `COMMIT` is reported on the `COMMIT` statement and leaves the connection idle; an error after a successful `COMMIT`
    leaves the data committed and the `COMMIT` cursor showing `COMMIT`. A client-side error (a
    value psycopg cannot adapt) leaves the transaction open, not aborted: a later `COMMIT`
    commits the statements before it. Loading a returned value can fail too (`'infinity'::date`
    raises `DataError` in `fetchall()`), after the statement - and a `COMMIT` after it - ran. A
    loader whose constructor raises fails while results are still arriving: the block ends with
    `cannot exit pipeline mode while busy`, the connection stays active in pipeline mode, and the
    server may already have committed (independent review, reproduced).
  - F4 A connection lost inside a pipeline (server-side terminate or client-side loss) raises
    `OperationalError` with `sqlstate=None`, although the server sent `FATAL 57P01`; outside a
    pipeline the same kill is `AdminShutdown` (`57P01`). The reliable signal is `conn.broken`. On
    a client-side loss no cursor has a result even when the server committed (proxy, not pinned).
  - F5 `copy()` inside a pipeline raises `NotSupportedError` before sending. COPY between a
    pipelined `BEGIN` and a later pipelined `COMMIT` works; a failing COPY is `23505` with
    diagnostics and leaves the transaction aborted.
  - F6 `pool.connection()` wraps `with conn:`, whose clean exit **commits** an open transaction.
    Returning a connection in a transaction makes the pool roll back (a `logging` warning);
    a broken one is discarded. The sync pool warns (`DeprecationWarning`) when `open=` is not
    given, the async pool when opened in its constructor (`RuntimeWarning`). A per-pool
    `AdaptersMap` passed as `context` is copied by each connection when it connects; later
    changes to it are not seen.
  - F7 psycopg-binary has no free-threaded (`cp314t`) wheel; with it in the default `dev` group,
    `uv sync --locked --python 3.14t` fails. Pure-Python psycopg installs on 3.14t but cannot be
    imported without a system libpq.
  - F8 psycopg prepares a query on its sixth execution on a connection (`prepare_threshold=5`).
    When that execution sits after a failed statement in the same pipeline, the server skips the
    `Parse` while psycopg records the statement as prepared; every later use of it on that
    connection fails with `26000` (`prepared statement "_pg3_1" does not exist`), also for the
    next borrower of the pooled connection. With `prepare_threshold=None` the same sequence
    completes (independent review, reproduced; 726 mismatches in 1500 fuzzed rounds).
- architect reviewed the draft (approve with changes): it asked for the closed reply union, the
  `COMMIT` tag rule, the acquisition error, the release rules, narrowing A102, dropping the server
  `DETAIL` line and a per-test database; all are in the decision below. The implementation review
  (code-reviewer, test-reviewer) added unreadable rows, the in-block error rule, COPY's `%%`
  and the release's `finally`; an independent review (another session, all four reviewers) added
  F8 and the unclean-connection rule (two BLOCKERs), the open of an interrupted pool, the
  internal exception's place and the notes for #16, #17 and #19.

## Decision
1. **A contract without psycopg.** `platina.drivers.interface` holds capability-split Protocols
   (design 10.2): `PipelineExecutor`, `CopyExecutor`, `Session` (both), `SessionSource`, and their
   async twins. `platina.drivers.errors` holds the mapping. Only `platina.drivers.psycopg` imports
   psycopg / psycopg_pool (and asyncio): guards A102 and A104 are narrowed to that package. The
   contract is not re-exported from `platina` (ADR-0001). `SessionSource` lends a full `Session`;
   a driver without COPY would satisfy only the executor Protocols, and the source Protocol is
   made generic when one exists.
2. **Statements.** A driver accepts any object with `sql: str` and `params: Sequence[object]`.
   Placeholders are `%s`, a literal `%` is always written `%%`, and the parameters are always
   passed (an empty sequence too), so one escaping rule holds for every statement. This fixes the
   compiler's placeholder style for #16 (psycopg's client-side `%s` conversion); #16's
   `CompiledSQL` satisfies this shape, or the Protocol is replaced by it.
3. **Replies, never exceptions, for statement errors.** `pipeline(statements)` sends them in one
   round trip and returns one of:
   - `Completed(results)` - one `StatementResult(status, rowcount, rows)` per statement, and only
     when every statement has one;
   - `Failed(results, fault)` - statement `at` (a property, `len(results)`) failed, `results` are
     those of `0 .. at - 1`, the ones after it did not run, the connection is usable. After a
     server error the transaction is aborted; after a client-side one in a pipeline it is still
     open and must be rolled back (a client-side error in a COPY aborts it). An error at the end
     of the round trip after every statement returned a result (the commit of an implicit
     transaction, statements sent without `BEGIN`) leaves the connection unclean: that is `Lost`;
   - `Lost(results, fault)` - the connection was lost, or is unclean: a round trip still active,
     pipeline mode still on, a state libpq does not know (F3's loader case). The driver closes
     it; a present result proves its statement ran, a missing one proves nothing, and the session
     is unusable afterwards (a new `session()` gets a fresh connection).

   One rule decides every reply, from the cursors' state rather than from the kind of
   exception (`_common.verdict`; the same class of misreport surfaced on three paths before it).
   Any exception - psycopg's or not - is caught both from each `execute()` (sending stops, the
   block closes normally) and from the block's exit. Then:
   - `Lost`, connection closed, when the connection is unclean, when the statement the received
     prefix stops at holds a `pgresult` (it ran; F3), or when the exit raised a non-psycopg
     exception (psycopg's result queue may be out of step even on a connection that looks
     clean);
   - a non-psycopg exception from an `execute()` (a dumper, invalid parameters) is re-raised in
     the shape of a programming error raised before sending - no exit error, every earlier
     statement has its result, only the one being sent lacks it; when the exit reported a server
     error of an earlier statement, the reply is `Failed` there with that error (it belongs to the
     first failed position); otherwise `Lost`;
   - otherwise `Completed` when every statement has a result, `Failed` at the first missing one
     with the first error (an earlier server error wins over a later client-side one, F3), and
     `Lost` when results are missing without an error.

   A statement that ran but whose rows cannot be loaded after the round trip keeps its result
   with `rows=UnreadableRows(fault)`, psycopg's error or not: its status, and a later
   `COMMIT`'s, stay known.

   The reader checks the `COMMIT` result's tag, not only its position: `COMMIT` in a transaction
   aborted by an earlier round trip answers `ROLLBACK` without an error. `DatabaseFault` carries
   the SQLSTATE (`None` for errors without one: a lost connection, an unadaptable value, a pool
   timeout - never read `None` as "lost"), the message, the constraint, table and schema names,
   and the psycopg exception. Cancellation (`BaseException`) is never caught. A programming error
   that propagates (parameters that are not a sequence, a dumper raising `ValueError`, a string
   that cannot be encoded) was raised before its statement was sent; the release rolls back what
   ran before it in an open transaction - but a `COMMIT` sent earlier in the same pipeline has
   committed. A statement is never empty or only a comment: a result without a command tag is
   not counted as received, and such a pipeline is `Lost`.
4. **Autocommit connections; the engine owns the transaction.** Every pooled connection has
   `autocommit=True` and the engine's statements include `BEGIN ISOLATION LEVEL ...` and `COMMIT`
   (F1). Connections are lent with `getconn` / `putconn`, never `pool.connection()` (F6), and go
   back by state: idle as is; in a transaction (open or aborted) after a `ROLLBACK`, closed if that
   fails; anything unclean (broken, closed, a round trip still active, pipeline mode on) closed
   without a `ROLLBACK`, so the pool replaces it. Connections have `prepare_threshold=None` (F8):
   no server-side prepared statements, so the wire carries exactly the engine's statements and
   no pipeline failure can desynchronise psycopg's statement cache. An interrupted pool open
   closes the pool. The connection is handed back in a `finally` on every path, also when the
   `ROLLBACK` is interrupted (then it is closed first). Shielding the release from cancellation is
   #19's.
5. **COPY** runs outside any pipeline on the same session, from a compiled
   `COPY ... FROM STDIN` statement (the driver writes no SQL) and a sequence of rows (a retried
   attempt sends them again). Its reply is the same union with one `COPY n` result. psycopg's
   `copy()` converts `%%` only when parameters are given; a COPY has none, so the driver turns
   `%%` into `%` itself and decision 2's escaping rule holds for COPY too. This fixes #17's `Copy`
   command shape (a compiled statement and a sequence of rows); text format only; `COPY ... TO`
   is not supported. `Copy` is a bounded command like `Pipeline` (design 10.5); refreshing the
   run budget before a COPY round trip, which has no statement head for ADR-0008's `set_config`,
   is #17's.
6. **The mapping.** The runner calls `database_error(fault, usecase=...)`: `23505` builds
   `UniqueViolation`, `23514` `CheckViolation`, `23503` / `23001` `ForeignKeyViolation` (decided
   by ADR-0010, handed to #18) with a hint to delete or re-point the referencing rows, anything
   else `DatabaseError` with the SQLSTATE;
   the psycopg exception is the `__cause__`; the constraint and table names become `Constraint:`
   / `Table:` detail lines. The server's `DETAIL` text is not copied: for `23505` it holds the key
   values, which would reach every log line of `str(exc)`; it stays on `__cause__`. This amends
   ADR-0006 on the two points it left to #18: `UniqueViolation` and `CheckViolation` fix their
   SQLSTATE (their constructors take no `sqlstate`), and `DatabaseError.sqlstate` stays
   `str | None` (F4). `ForeignKeyViolation` has two SQLSTATEs, so it takes `sqlstate` typed
   `Literal["23503", "23001"]` - no other value type-checks. Naming the referencing entity and
   field (ADR-0010) needs the registry and #25's constraint names; until then the `Table:` line
   names the table. No new typed field; #17 may add one if the engine needs it - recognising the
   `run_claim` conflict needs only the position of the claim statement and `23505`.
7. **Adapters per pool, fixed at construction.** The driver takes an optional `AdaptersMap` in its
   constructor and gives the pool a child of it (or of psycopg's global map); nothing is ever
   registered globally and there is no way to register after the pool opened (F6).
8. **Dependencies.** Runtime: `psycopg[pool]>=3.3`, no libpq bundled - an application installs
   `psycopg[binary]` or a system libpq. Development and CI: a `binary` dependency group, in
   `default-groups`, outside `dev`; the free-threaded unit-test job installs with
   `--no-group binary` (F7). Unit tests import only the psycopg-free contract and mapping, so that
   job needs no libpq. When `platina.app` wires the driver and `import platina` starts importing
   psycopg, that change installs a system libpq in the free-threaded job instead of importing the
   driver lazily; the sync runner on 3.14t stays unsupported (design 8.6). Pipeline mode needs
   client libpq 14+ (design 6).
9. **One internal exception outside the hierarchy.** Failing to get a connection at all (pool
   closed or timed out, connection refused) raises `SessionUnavailable(fault)` from `session()` and
   from opening the driver. It is not a `PlatinaError` and never reaches users: whoever opens the
   driver or a session - the runner, `App` when it opens the pool - maps its fault with
   `database_error`. Design 10.12 and the architecture rule name it as the one exception.

## Consequences
- Design 10.5's runner loop changes: `execute` returns a reply, the runner turns a fault into
  `database_error(fault, usecase=...)` (the use case's registry name comes from the bound use case
  it drives) and hands the engine positions. Design 5 no longer shows `pool.connection()`.
- The engine cannot import `platina.drivers`, so #17 defines its own reply in the core and the
  runner translates. To keep ADR-0008's commit-by-position rule readable, the core reply keeps,
  per round trip: the three outcomes (completed, failed at a position, lost); every received
  statement's status tag and row count; rows or the unreadable marker; the fault's SQLSTATE and
  constraint / table names; and, under lost, that a missing result proves nothing. Engine replay
  tests build these as plain data.
- The sync variant is a hand-kept mirror of the async one until #19; review keeps them in step.
- For #17: `Failed` before `COMMIT` is a rollback the engine must send (a client-side fault leaves
  the transaction open); a result whose `rows` is `UnreadableRows` is an error at that position,
  but the commit outcome still reads off the statuses. `SessionUnavailable` is not a
  `PlatinaError`: the runner maps it (`database_error(e.fault, ...)`) and 4.6's table gains a row
  then. The pool does not check connections on acquisition (a round trip per run): a connection
  that died while idle shows as `Lost` on the first round trip, before any write. ADR-0008's
  budget includes pool acquisition and its sync watchdog needs `cancel_safe()`; both extend this
  contract (a timeout on `session()`, a cancel capability on `Session`) when #17 needs them. After
  `Lost` the engine needs a new session for its rerun. A string that cannot be encoded (a lone
  surrogate) propagates as `UnicodeEncodeError` with the transaction open; whether the runner turns
  such data errors into a fault is #17's.
- A dumper error on a statement after `COMMIT` in the same pipeline propagates with the data
  committed. The engine's commit batch has no parameters after `COMMIT`, so it cannot reach this
  today; a statement with parameters placed after `COMMIT` would need #17 to treat that
  exception as commit-unknown.
- Opening a driver on an address that drops packets and cancelling the open: psycopg_pool takes
  about 5 s to close the pool (its connection attempt runs to its own timeout).
- For #17 and #19: the server does not reap the transaction of a runner stalled between round
  trips (F1), so the runner's own deadline and cancellation are the only bounds.
- For #19: on `CancelledError` psycopg itself sends a server-side cancel and waits up to 5 s, so a
  cancellation inside `pipeline()` can cancel the statements before `COMMIT` and returns no reply;
  the shield must cover the whole commit-batch call, not only the release.
- A COPY's rows are materialised before the call: design 3.2's chunk streaming sends each chunk
  with its own `copy_in`. Streaming within one COPY, if a measurement asks for it, changes this
  signature.
- No server-side prepared statements (decision 4): each statement is parsed every time. The cost is
  unmeasured; turning them back on needs a design that keeps psycopg's cache in step with
  pipeline failures (or one prepared statement per compiled SQL, managed by the driver).
- The pool's size defaults to `min_size` (1); a permanent connection error (wrong password) waits
  the whole `timeout` and loses its SQLSTATE in psycopg_pool's `PoolTimeout`.
- Integration tests create a database per test (design 11.5 shape without the template, which
  stays #20's).
- Not pinned by a test: the single Sync per pipeline (F1, F2), the Flush and idle timeout (F1),
  and a client-side loss after the server committed (F4) - they need a TCP proxy or timing; the
  unit tests cover only the reply shape (`settle`). Also not pinned: a caller's loader exception
  surfacing at the block's exit rather than from a later `execute()` (the `Lost` for a non-psycopg
  exit error). Whether it surfaces there depends on when psycopg polls the socket; the reviewer
  forced it 12 of 12 times only by replacing psycopg's `waiting.wait` with a loop that sleeps
  before each poll, and without that the exit raises psycopg's own `cannot exit pipeline mode
  while busy` (natural rate: 6 in 4456 pipelines). A database test would have to reimplement
  psycopg internals and bet on server latency. The rule itself is pinned by a truth table over
  `verdict`, a pure function, one row per branch - including that one, the dumper-shape count
  guard and "results missing without an error", which no database run reaches on its own with
  psycopg 3.3 (they are the conservative defaults for a future psycopg).

## Alternatives considered
- **Raise from `pipeline()` (an exception carrying the index)**: the runners could not catch it by
  type without importing psycopg's classes or a driver exception hierarchy, and every caller would
  rebuild the same union from it.
- **`autocommit=False` with psycopg's transaction handling**: an extra round trip per run, a notice
  per `BEGIN`, and SERIALIZABLE that depends on psycopg's `BEGIN` not having taken a snapshot.
- **`pool.connection()`**: commits an open transaction on a clean exit (F6).
- **`psycopg[binary]` in the `dev` group**: breaks the free-threaded job (F7); there is no PEP 508
  marker for free-threaded builds.
- **`RawCursor` with server-side `$1` placeholders** (no `%%` rule) or **t-strings**: `$n` would
  suit a compiler that numbers parameters, but psycopg's raw cursors give up its client-side
  conversion that the rest of the stack (adapters, `executemany`) is built around; t-strings
  bind values at the call site, while compiled SQL is built once and cached. #16 may revisit
  this with the compiler; decision 2 changes with it.
- **A `platina[binary]` extra** instead of telling users to install `psycopg[binary]`: possible
  later, but an extra that only re-exports another package's extra adds a name without a choice.
- **Keeping psycopg's automatic prepared statements** and resetting its cache after a failure: the
  cache is psycopg's internal state.
- **A `dict` from SQLSTATE to class**: a call through `type[DatabaseError]` with `sqlstate=` type
  checks and fails at run time on the two classes that fix it.

## History
- 2026-11-26 - created (as 0010; renumbered 0012 at the rebase, after 0010 and 0011 were taken on
  `develop`).
- 2026-11-26 - implementation review: `Failed.at` derived from `results`; `UnreadableRows`;
  in-block errors caught so the earliest server error wins; COPY `%%`; release in `finally`;
  notes for #17 and #19. Re-review: any loader exception becomes `UnreadableRows`; a
  `PipelineAborted` without an in-block error is reported, never read as success.
- 2026-11-26 - independent review: `prepare_threshold=None` (F8); unclean connections are `Lost`
  and closed (F3's loader case), `Completed` only with every result; interrupted pool open
  closes the pool; A104 narrowed with A102; `SessionUnavailable` as decision 9; what #17's core
  reply keeps; F1's Flush and idle timeout; alternatives for placeholders and the binary extra.
  Round 3: a loader error surfacing from a later `execute()` is `Lost` too (it escaped before).
- 2026-11-26 - second independent review: one rule from the cursors' state (`verdict`) replaces
  the per-path handling - a result that was set up half way is `Lost` (it was `Failed` while the
  server had committed), a non-psycopg exception at the block's exit is `Lost` (it escaped after
  `COMMIT`), an earlier server error wins over a later dumper error (it was `Lost` without its
  SQLSTATE).
- 2026-11-26 - rebased onto `develop`: `ForeignKeyViolation` for `23503` / `23001` added to the
  mapping (ADR-0010 decision 7 hands it to #18); design 10.5's runner sketch follows ADR-0008's
  deadline and `StatementFailed`.
