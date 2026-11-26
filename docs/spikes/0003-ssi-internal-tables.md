# Spike 0003: SSI false conflicts and the internal-table rule

- Design section: 9.2 "SSI concurrency experiment" - "Measure the rate of false conflicts
  (serialization failures) under concurrent execution on real PostgreSQL", all five items.
- Issue: #3
- Date: 2026-11-25
- Code: `spikes/0003-ssi-internal-tables/` (throwaway; raw output in `results/`, git-ignored)
- Renumbered from 0002 on 2026-11-25 (0002 became the use-case spike, PR #56); see the change
  record under Method.

## Question

The design rests on two claims that have not been observed on a real server.

**The internal append-only table rule** (design 4.6, 8.3): "`run_claim`, `run_result`, the
outbox log and the job tables are not read inside SERIALIZABLE transactions. SERIALIZABLE takes
read locks per B-tree leaf page, and with ever-increasing keys like uuid7 every INSERT lands on
the rightmost page. Transactions that read that page form cycles [...]. Inside a SERIALIZABLE
transaction the only operation on these tables is INSERT". Design 8.3 adds: "In the early stage
when the table is small, a table-level lock is taken, which is even worse", and "Needs
confirmation: the assumption that the unique check of an INSERT does not create such read locks
is verified by concurrency tests (§9)".

**The cost of the SERIALIZABLE default** (design 7.3): "On highly contended tables,
serialization failures and retries increase. [...] How large this cost actually is must be
confirmed by benchmarks (§9)."

Every statement below about what PostgreSQL does is a hypothesis to be observed, not a fact. The
dangerous error is a false "holds", so each verdict is decided only by the observations listed
for it here, fixed before anything ran. A "false conflict" is a 40001 between transactions whose
business effects do not overlap (no common row written, no row one writes that the other reads).

**Item 1 - `run_claim` INSERT (uuid7) alone causes no false conflicts.** Holds only if all of:
- (1a) In the fixed three-session interleavings (A1), while the transactions are open after their
  INSERTs, `pg_locks` (`mode = 'SIReadLock'`) shows **no** row whose relation is `run_claim` or
  `run_claim_pkey`; the same for the whole internal set (`run_claim`, `run_result`, `outbox_log`
  and every index on them) in the combined variant. This must hold for a fresh uuid7 **and** for
  a run ID that was inserted and rolled back before (`claim_retry`: the design's retry reuses the
  run ID, which leaves a dead index entry with an equal key, so the unique check goes to the
  heap), and after the fenced INSERT of A2 (a live or just-rolled-back equal key).
- (1b) Every session of the A1 interleavings commits. (Weak on its own: an INSERT takes any lock
  and writes in one statement, so a lock it took could only ever form a structure with three
  sessions in a particular order; A1 runs that order, but 1a and 1c decide.)
- (1c) In the load harness, the internal-only variants (`claim`, `claim_retry`, `full`, no
  business statements at all) report **zero** 40001 across every run.
- (1d) With business statements on disjoint rows, the variants with internal statements show no
  more 40001 than the baseline padded to the same number of round trips (`pad1` for `claim`,
  `pad4` for `full`): median over runs at most the padded baseline's maximum. If the padded
  baseline is not zero, (1d) is **undecidable** (not passed) and the business-table conflicts are
  reported as a finding of their own.
Does not hold if any of (1a)-(1c) fails. (1d) failing alone, with (1a)-(1c) holding, is "partly"
and investigated.

**Item 2 - control: "read then INSERT" and "INSERT then UPDATE" conflict.** The rule's rationale
holds if, for each control: `pg_locks` shows an SIReadLock on `run_claim_pkey` / `run_claim_u_pkey`
(page or relation) after the read / the UPDATE; at least one A1 order (sequential or phased - for
"INSERT then UPDATE" only the three-session sequential order can form a dangerous structure,
because each session writes before it reads) ends with a session receiving 40001; and the load
harness reports 40001 counts above the padded baseline's maximum (`pad2`) in every run. Partly if
only one of the two controls conflicts; does not hold if neither does (then the rule is not
needed for that reason, and the design rationale text is wrong).

**Item 3 - job-ID-as-run-ID fencing and the inline projection retry rate.**
- Fencing. The design's table in 4.6 and the dispatcher text in 4.10 say: a second INSERT of the
  same ID while the first is in progress *waits on the unique key*; if the first commits, the
  second gets **23505**; if the first rolls back, the second proceeds; a rerun after a commit
  gets 23505. Holds if exactly those SQLSTATEs and the waiting are observed. Partly if the
  outcome is still decided correctly but by a different SQLSTATE (for example 40001 where 23505
  was expected): then the runner's classification in 4.6 (23505 -> idempotent path, 40001 ->
  retry) must be checked against what a retry then sees, and the design text corrected. Does not
  hold if a duplicate claim can commit, or a wait never resolves.
- Snapshot aging (off-checklist). Observed with `pg_stat_activity.backend_xmin`: whether the
  snapshot exists after `BEGIN`, after `SET LOCAL`, and while the claim waits; whether the
  transaction that waited sees a row committed by a third session during the wait; whether a
  later UPDATE of that row gets 40001; then, as a rate, whether a 50 ms wait raises the 40001
  rate of the following business statements compared with no wait and with a 50 ms sleep on an
  open snapshot. Reported, not judged.
- Inline projection retry rate (design 4.10 key rule, 7.3). Reported per key distribution
  (disjoint keys, Zipf-distributed `store_id`, one global key - the case the seal rule rejects,
  as an upper bound) and per write form (UPDATE of an existing row; `INSERT ... ON CONFLICT DO
  UPDATE` on a new uuid7 key; the same on an existing key), against a baseline with no
  projection. The design's assumption holds if disjoint keys add no 40001 over the baseline
  (median at most the baseline maximum) in each write form; as in (1d), a non-zero baseline makes
  this undecidable rather than passed. The upsert question (off-checklist): whether the
  arbiter-index check of `ON CONFLICT` takes an SIReadLock - decided by `pg_locks` in A4, for a
  new key and for an existing key.

**Item 4 - small tables.** Two separate questions.
- Internal tables (4a): item 1's observations (1a, 1b) are repeated with the internal tables
  **empty** and with **1,000,000** rows each. Holds if no SIReadLock appears on them in either
  state.
- The design's "table-level lock when small" (4b): for the read-based controls of item 2 on an
  empty and a large `run_claim`, and for a business table of 30 rows versus 100,000 rows (never
  analyzed and analyzed), record the plan actually executed by the read and the UPDATE (run as
  `EXPLAIN ANALYZE` inside the observed transactions), the lock granularity in `pg_locks`
  (`locktype` relation / page / tuple, and whether the relation is the heap or the index), and
  whether transactions on different rows conflict. Holds if relation-level SIRead locks are
  observed in the small state and cause a conflict between transactions on different rows;
  partly if the granularity depends on something other than size (for example only on the plan,
  or only on emptiness) - the design text is then corrected to name the actual cause.

**Item 5 - SERIALIZABLE vs REPEATABLE READ + version** (durable profile only). A mixed workload
(payment, order creation with a range read of the user's last orders, transfer, a two-pocket
spend whose rule spans both rows but writes one, product repricing), uniform and Zipf row
selection, 8 / 32 / 64 worker processes, 5 runs per configuration, two round trips per attempt as
in design 4.6, retry as in design 8.3. Reported: TPS, attempts per commit, 40001 rate, 40P01
count, retry exhaustion, p50/p99 latency per committed command - each as median and range over
the 5 runs - plus the transfer total invariant and the pocket invariant (no user's pocket sum
below 0). The design gives no threshold; this spike fixes one before running:
- holds: under uniform selection at every worker count, SERIALIZABLE's median TPS is at least
  90% of REPEATABLE READ's and its median attempts per commit at most 1.05, and both invariants
  hold under SERIALIZABLE in every run;
- partly: the uniform bound holds but Zipf shows retry exhaustion under SERIALIZABLE in more
  than 1% of commands at some worker count where REPEATABLE READ does not (the 7.3 hot-row
  caveat made concrete); other Zipf differences are reported, not judged;
- does not hold: the uniform bound fails, or an invariant breaks under SERIALIZABLE.
Invariant breaks under REPEATABLE READ are reported as the price of the escape hatch. Only ratios
between the two levels and trends across worker counts are concluded; absolute numbers are not
(client and server share one laptop).

**uuid7 locality of user tables** (off-checklist, reported with item 5). Whether "read a recent
row by primary key + INSERT a new row", run by unrelated commands, conflicts because uuid7 keys
put both on the rightmost leaf page; compared with uuid4 keys and with reads of old rows.

## Setup
- Host: Apple M5 Pro (15 cores), 24 GiB; Docker 29.8.0 (VM with 15 CPUs, 15.6 GiB). Client
  and server run on the same machine.
- Python 3.14.7 (`uuid.uuid7()` from the standard library), psycopg 3.3.9 (binary, libpq 18.0.6).
- PostgreSQL: `PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2) on aarch64-unknown-linux-gnu, compiled
  by gcc (Debian 14.2.0-19) 14.2.0, 64-bit`, image `postgres:18`, both profiles of
  `docker-compose.yml`.
- Settings (both profiles, `SHOW`): `max_pred_locks_per_transaction = 64`,
  `max_pred_locks_per_relation = -2`, `max_pred_locks_per_page = 2`, `synchronous_commit = on`,
  `default_transaction_isolation = read committed`, `shared_buffers = 256MB`,
  `max_connections = 300`, `wal_level = replica`. The predicate-lock table is sized by
  `max_pred_locks_per_transaction x max_connections`; when it fills, PostgreSQL summarises
  committed transactions' locks, which adds false positives, and there is no counter for it -
  a condition of the 64-worker runs, not something this spike measures. Fast (26432): `fsync = off`,
  `full_page_writes = off`, tmpfs. Durable (26433): `fsync = on`, `full_page_writes = on`, volume.
- Docker could not create the compose project's network on this machine ("all predefined
  address pools have been fully subnetted"; the pools are held by other projects' networks). The
  two services were started unchanged except for `network_mode: bridge`, through an override
  file outside the repository:
  ```
  # compose-bridge.yml
  services:
    postgres: {network_mode: bridge}
    postgres-durable: {network_mode: bridge}
  docker compose -f docker-compose.yml -f compose-bridge.yml --profile durable \
      up -d --wait postgres postgres-durable
  ```
  Image, command line flags, ports and storage are those of `docker-compose.yml`; where `make
  db-up` / `make db-up-durable` work, they are equivalent.

## Method

Everything runs from the repository root after `uv sync --group spike`. Connection strings:
fast `host=localhost port=26432 user=platina password=platina dbname=platina`, durable the same
with port 26433. Every connection is opened with `autocommit=True` (transactions are explicit
`BEGIN ISOLATION LEVEL ...` statements) and `prepare_threshold=None` (no server-side prepared
statements, so no switch to generic plans). Every script writes its raw output under
`spikes/0003-ssi-internal-tables/results/` and prints a summary.

The method was reviewed by pg-researcher before anything ran; its findings changed: the A1
orders and the three-session structure, the `claim_retry` variant and lock observation after the
fenced INSERT, the padded baselines, fill factor 70 and HOT statistics, per-error statement and
message recording, `backend_xmin` observation of snapshot timing, `EXPLAIN ANALYZE` inside the
A5 transactions, the D workload (reads not written, a range read, a write-skew invariant), a
Zipf criterion, and exactly one Sync per round trip.

### Schema (`schema.sql`, recreated before every scenario and every run)
- Internal tables, as the design describes them:
  `run_claim(id uuid primary key)`,
  `run_result(run_id uuid primary key, result jsonb not null)`,
  `outbox_log(id bigint generated always as identity primary key, xid xid8 not null
  default pg_current_xact_id(), payload jsonb not null)` with an index on `xid` (the log reader
  reads by xid watermark),
  and for the control "INSERT then UPDATE" a variant `run_claim_u(id uuid primary key,
  result jsonb)`. Preloaded keys are generated by the client's `uuid.uuid7()` (as the run IDs
  are), so later run IDs sort after them whatever the clock difference to the Docker VM.
- Business tables: `orders(id uuid pk, user_id bigint, store_id int, status text, total numeric,
  version int)` with an index on `(user_id, id)`, `small_orders` (same shape), `wallets(id bigint
  pk, balance, version)`, `accounts(id bigint pk, balance, version)`, `products(id int pk,
  price)`, `order_items`, `payments`, `ledger` (uuid pk), `pockets(user_id, kind, balance, pk
  (user_id, kind))`; projection targets `user_spending(user_id bigint pk, total)`,
  `store_revenue(store_id int pk, total)`, `proj_new(id uuid pk, total)`. No foreign keys (an FK
  check is a read and would confound attribution).
- Fill factor of the business and projection tables: **70** in A, B and C, so that updates of
  non-indexed columns can stay HOT (a non-HOT update inserts into the primary-key leaf page and
  conflicts with readers of that page); **100** (the default) in D. B, C and D record
  `n_tup_upd` / `n_tup_hot_upd` per run. B also runs its baseline once more at fill factor 100.
- After loading: `VACUUM ANALYZE` unless an item says "never analyzed".

### Recording errors
Every error is recorded as `statement | SQLSTATE | message | detail` (digits replaced by `N`),
where the statement is the one that raised it (in a pipeline: the first statement without a
result; the server skips the rest of the batch). This separates 40001 at a statement from 40001
at COMMIT, "read/write dependencies" from "concurrent update", and the SSI reason code
("Canceled on identification as a pivot, during ...").

### A. Fixed interleavings (`interleave.py`, fast profile)
`uv run python spikes/0003-ssi-internal-tables/interleave.py --port 26432` (or name scenarios:
`... A1 A3`). Sessions S1..S3 and an observer O each have a fresh connection per scenario.
Statements run one at a time in the listed order; a statement that may block is sent from a
thread, and O polls `pg_stat_activity.wait_event_type` (deadline 3 s, stopping early if the
statement finished) and records the ungranted `pg_locks` row. At the observation point O runs
```sql
SELECT l.pid, l.locktype, c.relname, l.page, l.tuple
FROM pg_locks l LEFT JOIN pg_class c ON c.oid = l.relation
WHERE l.mode = 'SIReadLock' AND l.pid = ANY(<session pids>)
ORDER BY l.pid, c.relname, l.locktype, l.page, l.tuple;
```
and every row is recorded verbatim; then each session runs `SELECT
current_setting('transaction_isolation')`, and the sessions COMMIT in reverse order (S3, S2, S1),
recording `ok` or the error.

- **A1 (items 1, 2, 4a).** Internal-table state `empty`, then `1M` (1,000,000 rows in each of
  `run_claim`, `run_claim_u`, `run_result`, `outbox_log`). Variants, each session with its own
  new uuid7:
  - `claim`: INSERT into `run_claim`;
  - `claim_retry`: before the transaction, the session runs `BEGIN; INSERT X; ROLLBACK`, then the
    observed transaction INSERTs the same X;
  - `full`: claim; then INSERT outbox, INSERT `run_result`, `SELECT pg_current_xact_id()`;
  - `read_insert`: `SELECT 1 FROM run_claim WHERE id = X`; then the INSERT;
  - `insert_update`: INSERT into `run_claim_u`; then `UPDATE run_claim_u SET result = '{}'
    WHERE id = X`.
  Each variant runs in two orders, three sessions, all `BEGIN ISOLATION LEVEL SERIALIZABLE`
  first: **sequential** (S1 runs all its statements, then S2, then S3) - if a statement takes an
  SIRead lock on the page a later session inserts into, this gives S1 -rw-> S2 -rw-> S3, and S3
  commits first: a dangerous structure; and **phased** (first statement group of S1, S2, S3,
  then the second group of S1, S2, S3) - for `read_insert` all reads precede all inserts, a
  direct cycle.
- **A2 (item 3, fencing; 1a for an equal key).** Same ID X in both sessions, S2 SERIALIZABLE:
  - F1: S1 INSERT X; S2 INSERT X (sent; waiting recorded); S1 COMMIT; S2's result; O observes
    SIRead locks; S2 COMMIT (or the error it gets).
  - F2: as F1 but S1 ROLLBACK; S2's INSERT result, SIRead locks, S2 COMMIT, `count(*)` of X.
  - F3: S1 INSERT X, COMMIT; then S2 BEGIN, INSERT X (no wait possible).
  - F4: S2 BEGIN, `SELECT 1` (its snapshot; `backend_xmin` recorded); S1 INSERT X, COMMIT; S2
    INSERT X - the claim is not S2's first statement and X committed after S2's snapshot.
  Each scenario with S1 SERIALIZABLE, then with S1 READ COMMITTED. The SQLSTATE and the message
  text are recorded.
- **A3 (snapshot aging).** Order O preloaded with `total = 0`.
  - F5: S1 BEGIN SERIALIZABLE, INSERT X (holds). S2 BEGIN SERIALIZABLE [`backend_xmin`], `SET
    LOCAL statement_timeout = '10s'` [`backend_xmin`], INSERT X (sent; waiting recorded)
    [`backend_xmin`]; S3 (autocommit) `UPDATE orders SET total = 100 WHERE id = O`; S1 ROLLBACK;
    S2's INSERT completes [`backend_xmin`]; S2 `SELECT total FROM orders WHERE id = O`
    (recorded: 0 or 100); S2 `UPDATE orders SET total = total + 1 WHERE id = O` (result
    recorded); S2 COMMIT; O reads `total`.
  - F5-read: as F5 but S2 only reads O and commits.
  - F5-control: as F5 without S3's update.
- **A4 (upsert locks).** Three sessions, sequential order, each with its own key:
  `UPDATE user_spending SET total = total + 1 WHERE user_id = k` and `INSERT INTO user_spending
  ... ON CONFLICT (user_id) DO UPDATE SET total = user_spending.total + 1` on existing keys
  50001, 50002, 50003 (100,000 preloaded keys; adjacent keys share a leaf page); `INSERT INTO
  proj_new ... ON CONFLICT (id) DO UPDATE ...` on new uuid7 keys, with `proj_new` empty and with
  100,000 rows.
- **A5 (item 4b).** `small_orders` with 30 rows and `orders` with 100,000 rows, each "never
  analyzed" (autovacuum disabled on the table, no ANALYZE; `pg_class.relpages/reltuples`
  recorded) and "analyzed". Three sessions, phased order: each runs `EXPLAIN (ANALYZE, COSTS OFF,
  TIMING OFF, SUMMARY OFF) SELECT * FROM <t> WHERE id = <its row>`, then each runs the same for
  `UPDATE <t> SET total = total + 1 WHERE id = <its row>` (different rows: indexes 5, 15, 25 of
  the load order); observe; commit S3, S2, S1.

### B. Load harness, existence (`load.py exist`, fast profile; items 1, 2)
`uv run python spikes/0003-ssi-internal-tables/load.py exist --port 26432`
- 16 worker processes (multiprocessing `spawn`), each connects, checks its isolation level
  (`current_setting('transaction_isolation')` inside a SERIALIZABLE transaction, recorded), and
  waits on a shared barrier. Then each runs transactions back to back for 2 s of warm-up (not
  counted) and 10 s measured. One round trip per statement (a long transaction is the harsher
  case for an existence question). No retry: a 40001 / 40P01 is rolled back and counted, and the
  worker moves on with fresh IDs.
- Business statements: `none`, or `disjoint` - `SELECT * FROM orders WHERE id = $1` then
  `UPDATE orders SET total = total + 1, version = version + 1 WHERE id = $1`, where worker `w` of
  `N` only picks orders whose position in primary-key order is `w (mod N)` (rows of different
  workers interleave on the same pages). 100,000 preloaded orders.
- Internal statements (before / after the business statements): `none`; `pad1`, `pad2`, `pad4`
  (that many `SELECT 1` - baselines with the same number of round trips as `claim`,
  `read_insert`/`insert_update`, `full`); `claim`; `claim_retry` (each transaction is preceded by
  `BEGIN; INSERT X; ROLLBACK` on the same connection, then claims the same X); `full`;
  `read_insert`; `insert_update` (statements as in A1).
- Variants: internal in {`claim`, `claim_retry`, `full`, `read_insert`, `insert_update`} with
  business `none`; internal in {`none`, `pad1`, `pad2`, `pad4`, `claim`, `claim_retry`, `full`,
  `read_insert`, `insert_update`} with business `disjoint`; and `pad1`, `claim` with `disjoint`
  at fill factor 100. Internal tables start empty. 5 runs, every variant once per run.
- Recorded per run: attempts, commits, errors by SQLSTATE and by statement/message/detail, HOT
  statistics.

### C. Projection, snapshot-aging and locality rates (`load.py rates`, durable profile)
`uv run python spikes/0003-ssi-internal-tables/load.py rates --port 26433`
- Same harness, but 32 workers, 2 s warm-up + 15 s measured, 5 runs (every variant once per run),
  the retry policy of design 8.3 (at most 4 attempts, same run ID, full-jitter backoff
  `uniform(0, min(200 ms, 10 ms * 2^(attempt-1)))`), and **two round trips per attempt** through
  psycopg pipeline mode: round trip 1 = `BEGIN ISOLATION LEVEL SERIALIZABLE; SET LOCAL
  statement_timeout = '2s'; claim; loads`, round trip 2 = `writes; outbox INSERT; SELECT
  pg_current_xact_id(); COMMIT; SELECT pg_current_wal_insert_lsn()`. Each round trip ends with
  exactly one Sync (checked by counting `_enqueue_sync` calls in a probe: one per round trip,
  including when a statement fails). Reported: 40001 per attempt and attempts per commit, median
  and range, plus errors by statement/message/detail.
- **C1 projections (item 3).** Each attempt: claim; read and update a disjoint order (as in B);
  one projection write; outbox INSERT. Projection: `none` (baseline); `update` with key
  distribution `disjoint` (`user_spending`, 100,000 preloaded keys, worker `w` uses keys
  `= w + 1 (mod N)`), `zipf` (`store_revenue`, 1,000 stores, Zipf exponent s = 1.1, rank 0 most
  popular), `global` (one row); `upsert_existing` with the same three distributions;
  `upsert_new` on a new uuid7 key into `proj_new`.
- **C2 snapshot aging (item 3, rate).** Each attempt: claim; read and update an order chosen by
  Zipf (s = 1.1) over the 1,000 oldest orders; outbox INSERT. Workers 0-15 are a constant
  background load that always runs `nowait`; workers 16-31 (the probes) run the variant, and the
  reported rates are the probes' (the background's are recorded separately). A smoke run showed
  why: when every worker waits 50 ms, the write load itself drops and the variants are not
  comparable. Variants: `nowait`; `wait` -
  before the first attempt of a command, a helper connection of the same worker INSERTs the
  command's run ID in an open transaction, the main connection's claim then blocks on it, and a
  timer rolls the helper back after 50 ms; `sleep` - the first attempt runs `BEGIN; SET LOCAL;
  SELECT 1` as an extra round trip, sleeps 50 ms, then claims and loads (an aged snapshot without
  the claim wait - separates "the wait" from "the age").
- **C3 uuid7 locality (off-checklist).** Each attempt: claim; read one order by primary key;
  INSERT one new order; outbox. The order read is either `recent` (the order this worker inserted
  in its previous committed command - no other worker touches it) or `old` (uniform over the
  100,000 preloaded orders). Keys (preloaded and new) are uuid7 or uuid4. 4 variants.
- **C4 one hot row (off-checklist, carried over from spike 0002 X8 / ADR-0005; durable
  profile, port 26433, like the rest of C).** Table
  `hot(id int pk, bal numeric)` with one row. Each attempt: round trip 1 = `BEGIN ISOLATION LEVEL
  SERIALIZABLE; SET LOCAL statement_timeout = '2s'; claim` plus the load form - `blind` (no
  load), `read` (`SELECT bal FROM hot WHERE id = 1`) or `for_update` (the same `FOR UPDATE`);
  round trip 2 = `UPDATE hot SET bal = bal + 1 WHERE id = 1`, outbox, `SELECT
  pg_current_xact_id()`, `COMMIT`, LSN. Workers 8 / 32 / 64 (the other C variants use 32).
  Reported, not judged (ADR-0005 leaves the decision to the maintainer after 9.2): 40001 per
  attempt (and at which statement), attempts per commit, `RetryExhausted` (commands that failed
  their 4th attempt) as a share of commands, and `57014` (statement timeout) per attempt. Check:
  the row's final value equals the number of committed commands, warm-up included
  (`hot_total_ok`).

### D. Isolation benchmark (`bench.py`, durable profile; item 5)
`uv run python spikes/0003-ssi-internal-tables/bench.py --port 26433`
- Data, reloaded before every run (fill factor 100): 100,000 orders (uuid7, 10,000 users,
  `store_id` Zipf over 1,000), 10,000 wallets and 10,000 accounts (balance 1,000,000 each),
  1,000 products, 10,000 users x 2 pockets (balance 100 each); then `VACUUM ANALYZE`,
  `CHECKPOINT`.
- Commands, chosen per command with weights 30 / 25 / 20 / 20 / 5, each attempt starting with
  `BEGIN ISOLATION LEVEL <level>; SET LOCAL statement_timeout = '2s'; claim` and its loads
  (round trip 1), and ending with its writes, an outbox INSERT, `SELECT pg_current_xact_id()`,
  `COMMIT`, `SELECT pg_current_wal_insert_lsn()` (round trip 2):
  - pay: load order and wallet; `UPDATE orders SET status = 'PAID', version = version + 1 WHERE
    id = $o AND version = $v`; `UPDATE wallets SET balance = balance - $t, ... AND version =
    $v`; INSERT payment;
  - create: load 3 products and the user's last 5 orders (`WHERE user_id = $u ORDER BY id DESC
    LIMIT 5`, a range read); INSERT one order (uuid7) and 3 order items;
  - transfer: load accounts `a`, `b` (`a != b`, amount 1-100); UPDATE both in id order with the
    version predicate; INSERT ledger;
  - pocket: load both pockets of a user; withdraw (p = 0.6, amount 1-60, from one pocket chosen
    at random, only if the **sum** covers it - otherwise the command ends as a domain refusal) or
    deposit (amount 1-40) - a rule over two rows that writes one (write skew under REPEATABLE
    READ);
  - reprice: load a product; `UPDATE products SET price = price + 1` (makes the products that
    `create` reads but does not write contended).
  The version predicate sits in the same transaction as the read, so it protects nothing here
  (a concurrent update raises 40001 first under both levels); a 0-row match would be counted as
  `version_mismatch_committed`.
- Row selection: `uniform`, or `zipf` (s = 1.1 over a fixed random permutation) for orders,
  users/wallets/pockets, accounts and products.
- On 40001 / 40P01: ROLLBACK, backoff as in C, retry with the same run ID, at most 4 attempts.
- Isolation `SERIALIZABLE` or `REPEATABLE READ`; workers 8 / 32 / 64 processes; 3 s warm-up
  (not counted) + 20 s measured; 5 runs; run r executes every configuration once before run
  r + 1, so drift does not favour one level.
- Latency: wall time from a command's first attempt to its successful COMMIT, including backoff;
  p50 and p99 per run.
- After each run: `sum(balance)` of accounts must equal 10,000 x 1,000,000; the number of users
  whose pocket sum is below 0 and the minimum sum are recorded.

### Changes to the method after the first runs (dated record)
The criteria fixed in the Question are unchanged. These changes were made after some results
were seen, and are recorded here instead of being folded silently into the sections above.
- **2026-11-25, C2 background/probe split** - made after a smoke run (before the measured runs):
  when every worker waits 50 ms, the write load itself drops and the variants are not
  comparable. Described in C2 above.
- **2026-11-25, A6 added (post hoc).** After the first C3 run showed 64.5 % 40001 per attempt for
  uuid7 + recent reads, a load-independent check was added to A: two sessions, 100,000 orders
  plus one order per session committed just before (its "recent" row); each session reads its
  own target row by primary key, then INSERTs a new order; uuid7 vs uuid4 keys (preloaded and
  new), recent vs old (two random preloaded rows) targets; phased (both reads, then both
  inserts) and sequential orders; SIRead locks observed before the commits (S2, then S1).
  `uv run python spikes/0003-ssi-internal-tables/interleave.py --port 26432 A6` (A6 is not in
  the default scenario list).
- **2026-11-25, host contamination: first C and D runs discarded.** During C and D other
  workloads on the same machine (another session's deliberate CPU load - six `yes`
  processes - mutation tests, other database containers) drove the load average to 52 on 15
  cores; D's TPS for one configuration fell from 6,566 to 3,041 between runs, and the
  paired SERIALIZABLE/REPEATABLE READ ratios spread from 0.48 to 3.14. Within each run D also
  always ran SERIALIZABLE before REPEATABLE READ, so a load that grows during a run biases
  against REPEATABLE READ. The raw files are kept as `results/*_run1_discarded.*` and
  summarised under Observations as discarded. For the reruns:
  - **Quiet-host gate, first version - superseded before any gated run completed** (see the
    next-but-one entry) (`harness.QUIET_IDLE_PCT = 85`): CPU idle,
    sampled with `/usr/sbin/iostat -c 2 -w 3` (the second, 3 s window), must be at least 85 %
    right before a C run / D pair starts (`wait_quiet` polls every 30 s until it is) and in a
    sample 1 s after it ends. A run / pair whose after-sample fails is written to
    `results/*_discarded.jsonl` and rerun (at most 5 tries, then stop and report). Both samples
    and the 1-minute load average are stored with every record. 85 % idle leaves at most ~2.3
    of the 15 cores to everything else (the always-on endpoint agents and desktop apps).
  - **D order:** consecutive blocks (rep, workers, distribution) alternate which level runs
    first (AB, BA, AB, ...). Item 5 is reported from paired ratios within a block (median and
    range) as well as from medians per level.
  - C and D are rerun in full; the "TPS 90 %" criterion is unchanged.
  - The reruns and any reproduction of rates are never run at the same time.

- **2026-11-25, renumbered 0002 -> 0003 and moved onto develop `c974bc1`.** Spike number 0002
  went to the use-case spike (#5, PR #56, ADR-0005). Write-up, code directory and branch were
  renamed (`docs/spike-0003-ssi-internal-tables`); every path in this write-up, including the
  output paths in Reproduction round 1, now names `0003` (the files moved with the directory). The
  reproducer's recorded branch name (`docs/spike-0002-ssi-internal-tables` at `10a8517`) and its
  schema names are kept as they were run. Nothing was rerun because of the move; the reruns of C
  and D had not completed a run yet and were stopped and restarted from the new path.
- **2026-11-25, C4 added** (one hot row; before any C4 data was seen, apart from a smoke run whose
  output was discarded). Carried over from spike 0002 / ADR-0005 (Consequences: "the retry rate,
  the `RetryExhausted` rate and the `57014` rate on one hot row with and without `for_update`").
  ADR-0005 Decision 4's candidate comparison (append-only legs, async projection, a counter
  outside the transaction, a session-level advisory lock before `BEGIN`) is **not** in this
  spike: it needs a workload per candidate and, for the advisory lock, a protocol of its own.
  The maintainer decided (2026-11-25) to keep it out of this spike and give it a follow-up issue (#64)
  that uses C4 as its baseline; ADR-0005's Consequences and design 9.2 were adjusted to say so.
- **2026-11-25, quiet-host gate, second version** (replaces the first before any gated run had
  completed; no C or D record was kept under the first). Reasons: the first gate sampled only
  before and after a run, and CPU idle cannot separate other workloads from the spike's own
  load while it runs; and the always-on load of this machine, measured with no heavy job running,
  was 2.5-3.9 cores, so 85 % idle (at most ~2.3 busy cores) was rarely reachable. The maintainer
  asked for a numeric bound before **and during** each run. The gate is now:
  - **External CPU** = `ps` %CPU of every host process outside the harness's own process tree
    (the parent and its spawn workers), excluding the Docker VM and Docker backend processes
    (they carry the spike's PostgreSQL), plus `docker stats --no-stream` CPU of every container
    whose name does not start with `platina-` (100 % = one core).
  - A C run / D pair counts only if external CPU is **at most 500 %** right before it starts
    (`wait_quiet`, polling every 30 s) **and** the mean of the samples taken while it runs (one
    at once, then every 5 s; `HostMonitor`) is at most 500 %; a run without samples does not
    count. 500 % = 5 of the 15 cores: about one core above the always-on load measured above,
    and well below the contamination seen in the first runs (about 8 cores). Failed runs / pairs
    go to `results/*_discarded.jsonl` with their samples and are rerun, at most 5 tries.
  - If the host is not quiet within 30 minutes, the run stops (`RuntimeError`) and the
    maintainer is told, instead of waiting indefinitely.
  - Every kept record stores `host.before` and `host.during` (mean, max, number of samples,
    maximum 1-minute load average), so a stricter cut can be applied afterwards.
  - `harness.QUIET_EXTERNAL_PCT` can be overridden by `SPIKE_QUIET_EXTERNAL_PCT` for smoke tests
    only; measured runs use the default.
- **2026-11-25 22:40, overnight run.** The maintainer allowed the reruns to wait through the
  night (report at 07:00). `load.py rates` and `bench.py` gained `--resume` (skip a C run - rep
  and variant - or a D block - rep, workers, distribution - already in `results/load_rates.jsonl`
  / `results/bench.jsonl`), and the 30-minute limit can be raised with `SPIKE_QUIET_MAX_WAIT_S`,
  so a run stopped by the limit continues where it stopped instead of repeating kept runs. Neither
  changes what a kept run measures.
- **2026-11-26, A7 added (post hoc).** Occasion: after the morning report, a one-off probe in the
  maintainer's session found that a child INSERT's foreign-key check takes an SIRead lock on the
  parent's primary-key leaf, so ADR-0007's "no foreign keys (not measured)" left a gap. A7 checks
  it with fixed interleavings (existence only, fast profile; rates are not measured in this
  spike): tables `fk_parent(id uuid pk)` with 100,000 rows and `fk_child(id uuid pk, parent_id
  uuid references fk_parent)`, created by the scenario itself, parent and child keys from the
  same generator (uuid7, then uuid4); `pg_locks` after a child INSERT whose parent is new in the
  same transaction, committed just before, or old; then 10 pinned repetitions each of P1 (three
  sessions, each a parent INSERT and its child INSERT, one session after the other, COMMIT S3,
  S2, S1), P2 (two sessions, each first a child of its own just-committed parent, then - after
  both children - a new parent, COMMIT S2, S1) and P3 (two sessions, both parents first, then
  both children, COMMIT S2, S1). `uv run python spikes/0003-ssi-internal-tables/interleave.py
  --port 26432 A7` (not in the default scenario list). The probe's numbers were not used as
  evidence; A7 measured them again.
- **2026-11-26, A7 failure count corrected** after reproduction round 3: a repetition now counts
  as failed when any statement or any COMMIT fails, and a COMMIT that the server answers with
  `ROLLBACK` (an earlier statement had aborted the transaction) is reported as such. Rerun: same
  outcomes (no statement had failed).

## Observations

Database profile: per section (A, B: fast; C, D: durable). Raw output:
`results/interleave.txt`, `results/load_exist.{jsonl,txt}`, `results/load_rates.{jsonl,txt}`,
`results/bench.{jsonl,txt}`. In every scripted transaction and every worker,
`current_setting('transaction_isolation')` returned the level that was asked for
(`serializable` / `repeatable read`); the only exceptions are the two A2 F1 sessions whose
transaction was already aborted by the 23505 (`25P02`).

### A. Fixed interleavings (fast)
`uv run python spikes/0003-ssi-internal-tables/interleave.py --port 26432`, one run, 677 log
lines.

**A1 - SIRead locks and outcome, three sessions** (S1..S3 each with its own new uuid7; COMMIT in
the order S3, S2, S1):

| Internal state | Variant | Order | SIReadLock rows (all sessions) | S3 / S2 / S1 COMMIT |
|---|---|---|---|---|
| empty | `claim` | seq / phased | **0** / **0** | ok ok ok / ok ok ok |
| empty | `claim_retry` | seq / phased | **0** / **0** | ok ok ok / ok ok ok |
| empty | `full` | seq / phased | **0** / **0** | ok ok ok / ok ok ok |
| empty | `read_insert` | seq / phased | 3: `relation run_claim` (the heap), one per session | ok 40001 40001 / ok 40001 40001 |
| empty | `insert_update` | seq / phased | 3: `relation run_claim_u` (the heap) | ok 40001 40001 / ok 40001 40001 |
| 1M | `claim` | seq / phased | **0** / **0** | ok ok ok / ok ok ok |
| 1M | `claim_retry` | seq / phased | **0** / **0** | ok ok ok / ok ok ok |
| 1M | `full` | seq / phased | **0** / **0** | ok ok ok / ok ok ok |
| 1M | `read_insert` | seq / phased | 3: `page run_claim_pkey page=3852` (the same rightmost leaf for all three) | ok 40001 ok / ok 40001 40001 |
| 1M | `insert_update` | seq / phased | 3: `page run_claim_u_pkey page=3852` | ok 40001 ok / ok ok ok |

Every 40001 reads `could not serialize access due to read/write dependencies among
transactions`, detail `Reason code: Canceled on identification as a pivot, during commit
attempt.` The 1M `insert_update` phased order commits everywhere, as the review predicted (each
session writes before it reads, so no structure can form). With the tables empty, the controls'
lock is a relation lock on the **heap**, not on the index - the read was a sequential scan of the
empty table (A5 shows the plan dependence).

**A2 - fencing** (identical with S1 SERIALIZABLE and S1 READ COMMITTED):

| Scenario | S2 waits? | S2's INSERT | Then |
|---|---|---|---|
| F1: S1 holds X, S1 COMMIT | yes: `wait_event=Lock/transactionid`, ungranted `('transactionid', 'ShareLock')` | `23505 duplicate key value violates unique constraint "run_claim_pkey"`, detail `Key (id)=(...) already exists.` | SIReadLock rows: 0; X exists once |
| F2: S1 holds X, S1 ROLLBACK | yes (same lock) | ok, rowcount 1 | SIReadLock rows: 0; S2 COMMIT ok; X exists once |
| F3: S1 committed X before S2 began | - | 23505 | |
| F4: S2's snapshot (`SELECT 1`, `backend_xmin` set) before S1 inserted and committed X | - | 23505 (not 40001) | |

After the 23505 in F1, S2's `COMMIT` returns without error (the server ends the aborted
transaction with a rollback); nothing was committed.

**A3 - snapshot aging** (`backend_xmin` / `backend_xid` of S2 from `pg_stat_activity`):
- After `BEGIN ISOLATION LEVEL SERIALIZABLE`: `backend_xmin=None`; after `SET LOCAL
  statement_timeout`: `backend_xmin=None`; **while its claim INSERT waits**: `backend_xid=1088
  backend_xmin=1087` (the snapshot was taken by the claim, before the wait, and the transaction
  already holds an xid while it waits); unchanged after the wait.
- F5: S3 committed `total = 100` during the wait; after S1's ROLLBACK, S2 reads `total = 0`
  (the pre-wait snapshot), and its `UPDATE ... total + 1` fails with `40001 could not serialize
  access due to concurrent update`. Final value 100.
- F5-read: S2 reads 0 and commits (a single rw-dependency, no failure).
- F5-control (no S3): S2 reads 0, updates, commits; final value 1.

**A4 - projection write forms** (three sessions, sequential, all commit in every case):

| Form | SIReadLock rows |
|---|---|
| `UPDATE user_spending ... WHERE user_id = k` (existing keys 50001-50003) | 3: `page user_spending_pkey page=138` (one per session, no tuple or heap locks) |
| `INSERT ... ON CONFLICT (user_id) DO UPDATE` on the same existing keys | **0** |
| `INSERT ... ON CONFLICT (id) DO UPDATE` on new uuid7 keys, `proj_new` empty | **0** |
| the same, `proj_new` with 100,000 rows | **0** |

**A5 - small vs large business table** (three sessions on different rows, phased; plans are the
ones actually executed, from `EXPLAIN ANALYZE` inside the transactions):

| Table | `pg_class` (relpages, reltuples) | Plan of read and UPDATE | SIReadLock rows | S3 / S2 / S1 COMMIT |
|---|---|---|---|---|
| `small_orders` 30 rows, never analyzed | (0, -1) | Index Scan using `small_orders_pkey` | 3 x `page small_orders_pkey page=1` | ok ok ok |
| `small_orders` 30 rows, analyzed | (1, 30) | **Seq Scan** on `small_orders` | 3 x **`relation small_orders`** (heap) | ok **40001 40001** (pivot, commit attempt) |
| `orders` 100,000 rows, never analyzed | (0, -1) | Index Scan using `orders_pkey` | 3 x `page orders_pkey page=1` | ok ok ok |
| `orders` 100,000 rows, analyzed | (1392, 100000) | Index Scan using `orders_pkey` | 3 x `page orders_pkey page=1` | ok ok ok |

**A6 - uuid7 locality (post hoc, see the change record)**. Each session reads one row by
primary key, then INSERTs one new order; SIRead locks observed after both inserts; COMMIT S2,
then S1.

| Keys | Rows read | Order | SIReadLock rows | S2 / S1 COMMIT |
|---|---|---|---|---|
| uuid7 | each session's own recent row | phased | S1 and S2: `page orders_pkey page=387` (the **same** leaf, the rightmost) + a heap tuple each | ok / **40001** (pivot, commit attempt) |
| uuid7 | each session's own recent row | sequential | same | ok / ok |
| uuid7 | old rows | phased / sequential | `orders_pkey` pages 233 and 24 (different leaves) | ok / ok, ok / ok |
| uuid4 | each session's own recent row | phased / sequential | `orders_pkey` pages 137 and 367 | ok / ok, ok / ok |
| uuid4 | old rows | phased / sequential | `orders_pkey` pages 427 and 324 | ok / ok, ok / ok |

**A7 - foreign-key checks on an ever-increasing parent key (post hoc, see the change record).**
SIReadLock rows after one child INSERT (one SERIALIZABLE session):

| Parent of the child | uuid7 parent keys | uuid4 parent keys |
|---|---|---|
| new, inserted in the same transaction | `page fk_parent_pkey page=387` (the rightmost leaf) | `page fk_parent_pkey page=305` |
| committed just before | `page fk_parent_pkey page=387` + `tuple fk_parent page=636 tuple=149` | `page fk_parent_pkey page=364` + a heap tuple |
| old | `page fk_parent_pkey page=4` + a heap tuple | `page fk_parent_pkey page=469` + a heap tuple |

The FK check reads the parent's primary-key index under the transaction's predicate locking, like
any other read. Outcomes, 10 pinned repetitions each:

| Order | uuid7 | uuid4 |
|---|---|---|
| P1: three sessions, each parent INSERT + its child INSERT; COMMIT S3, S2, S1 | **10/10** fail: S2 `40001 ... read/write dependencies`, "Canceled on identification as a pivot, during commit attempt" | 0/10 |
| P2: two sessions, each a child of its own just-committed parent, then a new parent; COMMIT S2, S1 | **10/10** fail: S1, same message | 0/10 |
| P3: two sessions, both parents first, then both children; COMMIT S2, S1 | 0/10 | 0/10 |

So creating a parent and its children - an aggregate root with owned children, the most common
write - is the "read the right edge and insert into it" pattern of A6/C3 through the FK check,
without any read in the use case. Rates were not measured.

**Conditions** (from reproduction round 3, which varied what A7 fixed): the table above is the
**index-scan case** - the FK check (`SELECT 1 FROM ONLY <parent> x WHERE id = $1 FOR KEY SHARE OF
x`, run with the transaction snapshot) reads the parent's primary-key index when the planner
picks an index scan, as it did for 100,000 and 1,000,000 parents and for never-analyzed parents
of any size. For a small or empty **analyzed** parent table (up to about 400 single-column rows in
the reproducer's probe) the check is a sequential scan with a relation-level SIRead lock on the
parent heap - the item 4b mechanism - and then uuid4 parent keys and the parents-first order P3
fail as well (10/10 each in the reproducer's probe). Only the parent's key generator matters
(child keys from the other generator gave the same outcomes). uuid4's 0/10 at 100,000 parents
means the sessions landed on different leaves, not that the structure cannot form. The first A7
run counted only failed COMMITs (a statement error leaves an aborted transaction whose COMMIT
returns `ROLLBACK` without an error); no statement failed in any run, and the rerun with the
corrected count (2026-11-26) gave the same table.

### B. Existence under load (fast)
`uv run python spikes/0003-ssi-internal-tables/load.py exist --port 26432` - 16 workers, 2 s
warm-up + 10 s measured, 5 runs, every variant once per run; all 80 workers per variant reported
`serializable`. In this run no error other than 40001 occurred (no 40P01, no 23505). This is
not general: the independent reproduction's B run also got 23 x `53200 not enough elements in
RWConflictPool to record a read/write conflict` (one `insert_update`/disjoint run, under heavy
host load), see Reproduction. Attempts are the
measured ones; "non-HOT" is `n_tup_upd - n_tup_hot_upd` of `orders` over the whole run
(warm-up included).

| Internal | Business | Fill factor | Attempts per run, median (range) | 40001 per run | 40001 / attempt, median (range) | non-HOT `orders` updates per run |
|---|---|---|---|---|---|---|
| `claim` | none | 70 | 93,788 (56,379-98,469) | 0, 0, 0, 0, 0 | 0 | - |
| `claim_retry` | none | 70 | 45,799 (25,015-54,536) | 0, 0, 0, 0, 0 | 0 | - |
| `full` | none | 70 | 49,907 (32,564-53,055) | 0, 0, 0, 0, 0 | 0 | - |
| `read_insert` | none | 70 | 56,368 (39,775-58,092) | 30,829, 43,855, 42,964, 45,094, 44,338 | 77.7% (77.5-77.8) | - |
| `insert_update` | none | 70 | 63,014 (51,429-75,618) | 40, 91, 23, 71, 54 | 0.078% (0.038-0.120) | - |
| `none` | disjoint | 70 | 71,960 (25,567-74,997) | 0, 0, 0, 0, 0 | 0 | 0 in every run |
| `pad1` | disjoint | 70 | 53,203 (35,963-55,624) | 0, 0, 0, 0, 0 | 0 | 0 |
| `pad2` | disjoint | 70 | 46,947 (39,916-49,772) | 0, 0, 0, 0, 0 | 0 | 0 |
| `pad4` | disjoint | 70 | 34,854 (24,623-38,114) | 0, 0, 0, 0, 0 | 0 | 0 |
| `claim` | disjoint | 70 | 47,354 (32,104-61,177) | 0, 0, 0, 0, 0 | 0 | 0 |
| `claim_retry` | disjoint | 70 | 30,787 (24,857-40,216) | 0, 0, 0, 0, 0 | 0 | 0 |
| `full` | disjoint | 70 | 33,460 (23,685-40,167) | 0, 0, 0, 0, 0 | 0 | 0 |
| `read_insert` | disjoint | 70 | 40,967 (23,867-44,174) | 20,023, 17,306, 29,474, 30,339, 31,830 | 72.1% (71.9-72.5) | 0 |
| `insert_update` | disjoint | 70 | 43,400 (30,694-50,009) | 5, **0**, 3, 3, 1 | 0.006% (0-0.012) | 0 |
| `pad1` | disjoint | **100** | 42,970 (26,166-61,888) | 6, 6, 9, 9, 4 | 0.016% (0.006-0.034) | 2,247-4,204 |
| `claim` | disjoint | **100** | 52,601 (24,198-61,167) | 6, 4, 6, 7, 13 | 0.012% (0.011-0.024) | 2,565-3,940 |

Where the 40001 were raised (all runs summed; message always `could not serialize access due
to read/write dependencies among transactions`):
- `read_insert`/none: `COMMIT` 146,217 ("Canceled on identification as a pivot, during commit
  attempt"), `INSERT INTO run_claim` 60,802 ("... as a pivot, during write"), `COMMIT` 61
  ("Canceled on commit attempt with conflict in from prepared pivot").
- `read_insert`/disjoint: `COMMIT` 73,627, `UPDATE orders` 51,207 ("during conflict out
  checking" / "during conflict in checking"), `SELECT * FROM orders` 3,825, `INSERT INTO
  run_claim` 313 - the business statements fail because the transaction is already a pivot
  through `run_claim`.
- `insert_update`/none: `COMMIT` 278, `UPDATE run_claim_u` 1; 62-162 of its updates per run
  were non-HOT. `insert_update`/disjoint: `COMMIT` 12.
- fill factor 100, `pad1` and `claim` alike: `COMMIT` 26 / 25 and `UPDATE orders` 8 / 11 - the
  business baseline itself conflicts once updates stop being HOT, with or without the claim.

### C and D, first runs - discarded (host contaminated)
Not evidence for any verdict; kept because the method requires discarded data to stay visible.
See the change record for the reason. Durable profile, 32 workers (C) / 8-64 workers (D),
5 runs each. Raw: `results/load_rates_run1_discarded.*`, `results/load_rates_c2rerun_discarded.txt`,
`results/bench_run1_discarded.*`; tables by
`uv run python spikes/0003-ssi-internal-tables/summarize.py rates|bench <file>`.

C, 40001 per attempt, median (range) over 5 runs:
- C1 projections: baseline (no projection) 0 %; `update` disjoint 0 %, Zipf 26.6 % (26.0-27.0),
  global 79.8 % (76.0-82.1); `upsert_existing` disjoint 0 %, Zipf 26.4 % (25.8-26.7), global
  79.7 % (79.1-81.8); `upsert_new` 0 %. Every Zipf/global 40001 except a few hundred was
  `could not serialize access due to concurrent update` at the projection statement.
- C3 locality: uuid7 + recent 64.5 % (62.7-67.1), 2.82 attempts per commit, ~4,845 exhausted
  commands per run, raised mostly at `INSERT INTO orders` ("Canceled on identification as a
  pivot, during write"); uuid7 + old 0 %; uuid4 + recent 0.10 %; uuid4 + old 0.11 %.
- C2 snapshot aging: first run (background stats not saved) nowait 26.6 %, wait 47.1 %, sleep
  46.5 %; rerun (with background stats) probes nowait 31.0 % / wait 41.3 % / sleep 41.6 %, the
  background workers of the same runs 30.2 % / 23.8 % / 23.6 %.

D (first run): uniform attempts per commit at most 1.008 under SERIALIZABLE at every worker
count; Zipf 1.10 / 1.35 / 1.66 (SERIALIZABLE) vs 1.09 / 1.31 / 1.53 (REPEATABLE READ) at
8 / 32 / 64 workers; transfer invariant held in every run; pocket users with a negative sum:
REPEATABLE READ 0-1 per run (at 32 and 64 workers, Zipf), SERIALIZABLE 0 in every run; under
Zipf, `create` (range read + uuid7 INSERT) had 4-29 % 40001 under SERIALIZABLE and 0 % under
REPEATABLE READ. TPS is not reported: paired ratios spread 0.48-3.14.

### C. Rates, rerun on a quiet host (durable)
`uv run python spikes/0003-ssi-internal-tables/load.py rates --port 26433` (2026-11-25,
21:44-23:19 local), quiet-host gate second version: 120 runs kept (24 variants x 5), 26 runs
discarded and rerun (mean external CPU during the run 507-829 %); the kept runs' mean external CPU
was 67-498 %. Every worker reported `serializable`. Tables: `uv run python
spikes/0003-ssi-internal-tables/summarize.py rates`. Values are median (range) over 5 runs; 32
workers unless stated; no error other than 40001 occurred (no 40P01, no 57014, no 53200).

| Variant | 40001 / attempt | Attempts / commit | Exhausted commands / run |
|---|---|---|---|
| C1 baseline (no projection) | 0 % | 1.000 | 0 |
| C1 `update` disjoint keys | 0 % | 1.000 | 0 |
| C1 `update` Zipf `store_id` | 26.8 % (26.5-27.7) | 1.366 | 336 |
| C1 `update` one global key | 82.1 % (80.5-82.6) | 5.60 | 7,068 |
| C1 `upsert_existing` disjoint keys | 0 % | 1.000 | 0 |
| C1 `upsert_existing` Zipf | 27.1 % (26.6-27.5) | 1.372 | 308 |
| C1 `upsert_existing` global | 81.2 % (78.8-86.5) | 5.32 | 7,482 |
| C1 `upsert_new` (new uuid7 key) | 0 % | 1.000 | 0 |
| C2 probes `nowait` | 26.9 % (25.9-27.2) | 1.369 | 172 |
| C2 probes `wait` (50 ms on a held claim) | 46.6 % (45.7-47.2) | 1.871 | 23 |
| C2 probes `sleep` (50 ms on an open snapshot) | 46.2 % (45.1-47.4) | 1.858 | 28 |
| C3 uuid7 keys, read own recent row | **69.2 % (65.1-72.3)** | 3.24 | 4,936 |
| C3 uuid7 keys, read an old row | 0 % | 1.000 | 0 |
| C3 uuid4 keys, read own recent row | 0.10 % (0.09-0.12) | 1.001 | 0 |
| C3 uuid4 keys, read an old row | 0.11 % (0.08-0.13) | 1.001 | 0 |

- C1: every Zipf/global 40001 except a few hundred per variant is `could not serialize access due
  to concurrent update` at the projection statement (`UPDATE store_revenue` / `INSERT INTO
  store_revenue ... ON CONFLICT`); the rest are read/write-dependency pivots (e.g. 445 at COMMIT
  for `update`/Zipf over 5 runs).
- C2: background workers (same runs, always `nowait`) 27.0 % / 18.6 % / 18.8 % for the
  `nowait` / `wait` / `sleep` runs - the probes' higher rate is not a heavier write load (the
  background saw less). Almost all failures are `concurrent update` at `UPDATE orders`.
- C3: uuid7 + recent failures are read/write-dependency pivots, mostly at `INSERT INTO orders`
  (126,628 "Canceled on identification as a pivot, during write" over 5 runs), then at the outbox
  INSERT and COMMIT.

**C4 - one hot row** (durable, 5 runs per cell, `statement_timeout = '2s'`; the final value of
the row equalled the number of committed commands in all 45 runs):

| Workers | Load form | 40001 / attempt | Attempts / commit | `RetryExhausted`, % of commands | 57014 / attempt | Failing statement |
|---|---|---|---|---|---|---|
| 8 | `blind` | 41.3 % (30.2-47.0) | 1.70 | 9.6 (6.5-11.2) | 0 | `UPDATE hot` |
| 8 | `read` | 40.2 % (31.1-46.1) | 1.67 | 9.3 (7.0-11.6) | 0 | `UPDATE hot` |
| 8 | `for_update` | 40.1 % (30.0-48.2) | 1.67 | 9.2 (6.7-12.1) | 0 | `SELECT ... FOR UPDATE` |
| 32 | `blind` | 78.1 % (73.5-81.4) | 4.57 | 39.7 (34.3-45.1) | 0 | `UPDATE hot` |
| 32 | `read` | 78.5 % (77.2-81.3) | 4.65 | 41.0 (39.1-45.0) | 0 | `UPDATE hot` |
| 32 | `for_update` | 77.2 % (72.1-79.9) | 4.39 | 39.3 (33.7-43.0) | 0 | `SELECT ... FOR UPDATE` |
| 64 | `blind` | 91.0 % (90.7-91.8) | 11.1 | 68.9 (68.0-71.1) | 0 | `UPDATE hot` |
| 64 | `read` | 91.1 % (91.0-92.8) | 11.3 | 69.3 (68.8-74.4) | 0 | `UPDATE hot` |
| 64 | `for_update` | 89.7 % (88.1-90.4) | 9.74 | 65.5 (61.5-67.2) | 0 | `SELECT ... FOR UPDATE` |

All C4 failures are `could not serialize access due to concurrent update`, except a few dozen
read/write-dependency failures at COMMIT (at most 32 per cell over 5 runs). No lock wait reached
the 2 s `statement_timeout`.

### D. SERIALIZABLE vs REPEATABLE READ, rerun on a quiet host (durable)
`uv run python spikes/0003-ssi-internal-tables/bench.py --port 26433` (2026-11-25, finished
23:34 local; resumed once with `--resume` after the gate itself crashed on a container that
`docker stats` reported as `--` - fixed, no kept record affected). 30 blocks (rep x workers x
distribution) kept, none discarded; each level ran first in 15 blocks, but **not balanced within a
configuration**: the alternation follows the global block counter and every run has 6 blocks, so
each configuration had the same order in all 5 runs (uniform: SERIALIZABLE first, Zipf:
REPEATABLE READ first) - found by the reproduction, whose order checks (3 pairs in each order for
64/uniform, 32/uniform, 64/Zipf) showed no consistent first-position effect; mean external CPU
during the kept pairs 138-368 %. Every worker reported the level asked for. No error other than
40001 (no 40P01, no 57014, no 53200); `version_mismatch_committed` 0. Tables: `uv run python
spikes/0003-ssi-internal-tables/summarize.py bench`. Median (range) over 5 runs.

| Workers | Dist | Level | TPS | Attempts / commit | 40001 / attempt | Exhausted, % of commands | p50 / p99 ms |
|---|---|---|---|---|---|---|---|
| 8 | uniform | RR | 4,337 (3,610-4,587) | 1.000 | 0.02 % | 0 | 1.7 / 3.4 |
| 8 | uniform | SER | 4,137 (4,004-4,626) | 1.001 | 0.07 % | 0 | 1.8 / 3.7 |
| 32 | uniform | RR | 6,226 (5,928-7,142) | 1.001 | 0.07 % | 0 | 4.8 / 10.7 |
| 32 | uniform | SER | 6,061 (5,183-6,447) | 1.003 | 0.31 % | 0 | 4.8 / 12.8 |
| 64 | uniform | RR | 6,620 (5,946-7,478) | 1.002 | 0.14 % | 0 | 9.0 / 20.8 |
| 64 | uniform | SER | 6,804 (6,028-6,984) | 1.007 | 0.64 % | 0.001 | 8.8 / 21.4 |
| 8 | Zipf | RR | 3,371 (3,095-3,552) | 1.086 | 4.97 % | 0.047 | 1.8 / 13.9 |
| 8 | Zipf | SER | 3,327 (3,175-3,592) | 1.096 | 5.77 % | 0.039 | 1.7 / 14.5 |
| 32 | Zipf | RR | 3,637 (3,203-4,853) | 1.284 | 19.6 % | 2.26 | 4.5 / 52.8 |
| 32 | Zipf | SER | 3,894 (3,538-4,633) | 1.325 | 21.9 % | 2.22 | 4.1 / 52.4 |
| 64 | Zipf | RR | 3,842 (3,718-4,069) | 1.502 | 31.1 % | 5.97 | 8.0 / 74.2 |
| 64 | Zipf | SER | 3,677 (3,473-3,778) | 1.594 | 35.0 % | 6.42 | 7.7 / 77.0 |

SER/RR TPS, ratio of medians (paired ratios per block): uniform 0.954 (0.89-1.14) / 0.973
(0.83-1.09) / 1.028 (0.90-1.14) at 8 / 32 / 64 workers; Zipf 0.987 (0.93-1.08) / 1.071
(0.80-1.25) / 0.957 (0.91-0.98).

- Invariants: the transfer total held in all 60 runs. Users with a negative pocket sum: **0 in
  all 30 SERIALIZABLE runs**; under REPEATABLE READ 1 user in 4 of 30 runs (8/Zipf, 32/Zipf,
  64/uniform, 64/Zipf; minimum sums -7, -3, -20, -3) - the write skew the escape hatch allows.
- Where the extra SERIALIZABLE failures come from (per command type, 40001 per attempt, 64
  workers Zipf, SER vs RR): pay 42.5 % vs 44.3 %, transfer 50.8 % vs 53.1 % (same-row
  `concurrent update` under both), **create 27.2 % vs 0 %**, pocket 12.2 % vs 5.5 %, reprice
  11.5 % vs 6.8 %. Under SERIALIZABLE 50,444 failures were `INSERT INTO orders` pivots ("during
  write") and 4,021 the range read of the user's last orders - the create command's range read
  and uuid7 INSERT (the C3 pattern) - and 8,433 `UPDATE pockets` pivots, the write skew being
  prevented; REPEATABLE READ raised only `concurrent update`.

(Independent reproduction of C and D: Reproduction, round 2.)

## Verdict

Items 1, 2, 3 (fencing), 4a and 4b rest on load-independent observations (A, B), reproduced in
round 1; A7 (foreign keys, post hoc) was reproduced in round 3 (agree for the configuration A7
fixed, partly overall: the plan condition added to A7). The rate verdicts (item 3's projection rates, item 5, and the rate halves of the
off-checklist observations) come from the C and D reruns on a quiet host, reproduced in round 2.
Both rounds agreed with every verdict.

| Item | Verdict | Deciding observations |
|---|---|---|
| 1. `run_claim` INSERT alone | **Holds** | (1a) 0 SIReadLock rows on `run_claim`, `run_result`, `outbox_log` and their indexes in every A1 variant (fresh ID, reused ID after rollback, full set), empty and 1M rows, and after the fenced INSERTs of A2; (1b) every A1 session committed; (1c) 0 x 40001 in 5/5 runs of `claim`, `claim_retry`, `full` without business statements (45,799-93,788 attempts per run); (1d) 0 x 40001 with disjoint business statements, as in the padded baselines (also 0) |
| 2. Controls conflict | **Partly** | "read then INSERT": SIReadLock on the rightmost `run_claim_pkey` leaf (or the heap relation when empty), 40001 in both A1 orders, 72-78 % of attempts in B. "INSERT then UPDATE": the same lock and a pivot 40001 in the three-session sequential order, but only 0.04-0.12 % of attempts without business statements and 0-0.012 % with them - **one of five disjoint runs had none**, so the pre-fixed "above the baseline in every run" fails for it. The mechanism the design names is real for both; the claim that the UPDATE form "recreates the same false conflict" overstates its frequency by about three orders of magnitude in this harness. |
| 3. Fencing | **Holds** | A2: the second INSERT waits on the first transaction's xid (`Lock/transactionid`, ShareLock); commit -> **23505** `duplicate key value violates unique constraint "run_claim_pkey"`; rollback -> proceeds and commits; rerun after commit -> 23505, also when the rerun's snapshot predates the commit (F4); never 40001; identical with the first transaction at READ COMMITTED. **Condition:** this holds because `run_claim` is not read; when both claimants read the ID before inserting it, the waiting one gets 40001 instead of 23505 (reproducer's probe 2(b)) - one more reason for the internal-table rule |
| 3. Inline projection retry rate | **Holds** | C1: disjoint keys 0 % 40001 per attempt in 5/5 runs for `update`, `upsert_existing` and `upsert_new`, equal to the baseline (0 %); Zipf `store_id` 26.8 % / 27.1 % (1.37 attempts per commit, ~300 exhausted commands per run); one global key 82.1 % / 81.2 % (5.3-5.6 attempts per commit, ~7,000 exhausted per run) - almost all the same-row `concurrent update`. The key rule's assumption (entity-ID keys that are disjoint add no retries) holds; a popular entity ID is as hot as its traffic (Zipf), which is what the per-projection retry metric is for. A4: `ON CONFLICT DO UPDATE` takes no SIRead lock |
| 4a. Internal tables empty / 1M | **Holds** | as 1a, in both states |
| 4b. "Table-level lock when small" | **Partly** | The relation-level SIRead lock is real and causes pivot 40001 between transactions on different rows, but its cause is the **plan**, not the size: an analyzed 30-row table is read by Seq Scan -> `relation small_orders` (heap) -> 40001; the same table never analyzed is read by Index Scan -> page lock -> no conflict; empty analyzed tables were seq-scanned too (A1 controls: `relation run_claim`) |
| 5. SERIALIZABLE vs REPEATABLE READ | **Holds** | D, uniform: SER/RR median TPS 0.954 / 0.973 / 1.028 at 8 / 32 / 64 workers (>= 0.90) and SER attempts per commit 1.001 / 1.003 / 1.007 (<= 1.05); transfer total and pocket invariant held in every SERIALIZABLE run. Zipf: SER retry exhaustion 2.2 % / 6.4 % of commands at 32 / 64 workers, but REPEATABLE READ 2.3 % / 6.0 % - not a SERIALIZABLE-only exhaustion, so the "partly" clause does not apply; the extra SERIALIZABLE failures are SSI pivots in `create` (range read + uuid7 INSERT, 27 % vs 0 %) and in `pocket` (write skew prevented). REPEATABLE READ broke the pocket invariant in 4 of 30 runs. Reproduction: uniform ratios 0.995 / 0.949 / 0.910 (narrow at 64 workers; 0.960 with alternating order), Zipf 6-17 % slower under SERIALIZABLE - same verdict. Absolute TPS is not concluded (client and server on one laptop) |

**Off-checklist observations**
- **Upsert projections:** `INSERT ... ON CONFLICT DO UPDATE` took no SIReadLock at all - neither
  for a new uuid7 key (empty or 100,000-row table) nor for an existing key - whereas a plain
  `UPDATE ... WHERE key = $k` took an index-page SIRead lock (A4). Upsert-form projections do
  not reintroduce the internal-table problem.
- **uuid7 locality of user tables:** confirmed without load (A6): two unrelated transactions
  that each read their own recent row by primary key and then INSERT a new row lock the same
  rightmost leaf page and one gets 40001; with uuid4 keys or old rows they lock different leaves
  and both commit. Rate (C3): 69.2 % (65.1-72.3) of attempts failed
  with uuid7 keys and recent reads, 3.24 attempts per commit and ~4,900 exhausted commands per
  15 s run; 0 % with uuid7 and old reads; 0.10-0.11 % with uuid4 keys (reproduction: 65.2 %, and 74 % in its own probe, against <= 0.12 % for uuid4). C3 is a worst
  case (the row read was always the newest of its worker, 32 workers inserting without pause,
  100,000 rows, no foreign keys); the conflict window as rows age was not measured. D's `create`
  command also failed only under SERIALIZABLE (27 % vs 0 % at 64 workers / Zipf), but through its
  range read on the `(user_id, id)` index - a per-user right edge plus page granularity, partly
  true conflicts - which a uuid4 primary key would not change (architect review of ADR-0007).
- **Foreign keys (A7, post hoc, reproduced in round 3):** a child INSERT's FK check takes an
  SIRead lock on the parent's primary-key leaf, so with uuid7 parents "create a parent and its
  children" by unrelated commands fails as a pivot 40001 (10/10 in two orders; 0/10 when both
  parents are inserted before both children, and 0/10 with uuid4 parents) - while the parent is
  read by an index scan. On a small or empty analyzed parent the check takes a relation lock and
  every order fails with uuid4 as well. Rates not measured (#65).
- **Snapshot aging while waiting on a claim:** the claim INSERT takes the snapshot and an xid
  **before** it waits (A3: `backend_xmin`/`backend_xid` set while waiting, none after `BEGIN` or
  `SET LOCAL`); after the wait the transaction reads pre-wait values and its UPDATE of a row
  changed meanwhile fails with `40001 ... due to concurrent update`. Rate (C2): probes that waited 50 ms on a held claim failed 46.6 % of attempts, probes that slept
  50 ms on an open snapshot 46.2 %, probes without either 26.9 % - while the background workers
  of the same runs saw less, not more (27.0 % / 18.6 % / 18.8 %). The cost is the snapshot's age,
  not the wait.
- **One hot row (C4, carried over from spike 0002 / ADR-0005; reported, not judged):** 40001 per attempt about 40 % / 78 % / 90 % at 8 / 32 / 64 workers, the same
  for a blind increment, read-then-update and `SELECT ... FOR UPDATE` (the last moves the failure
  to the load statement); `RetryExhausted` (4 attempts) 9 % / 40 % / 66-69 % of commands; no
  `57014` at a 2 s `statement_timeout`. `for_update` neither reduced the failures nor produced
  timeouts in this harness. (Reproduction: about 31 % / 75 % / 90 % and 7 % / 35-37 % / 64-69 %; its
  own one-statement-per-round-trip probe exhausted more, so the cost grows with transaction length.)
- Also seen: (i) a transaction waiting on a claim already holds an xid, so it holds back the
  outbox log's xid watermark (design 4.10, 7.7) for as long as it waits; (ii) `COMMIT` of a
  transaction already aborted by an error returns without an error (the server rolls back) -
  the runner must decide the outcome from the first error, which pipeline mode makes natural
  because later statements are skipped; (iii) at the default fill factor (100) the business
  baseline itself produced 40001 between transactions on disjoint rows (0.006-0.034 % per
  attempt), through non-HOT updates inserting into shared primary-key leaf pages; (iv) under
  SSI load PostgreSQL can raise **53200** (`not enough elements in RWConflictPool to record a
  read/write conflict`) instead of 40001 (reproducer's B run, 23 times in one run; not
  reproduced on demand, cause not isolated). The design retries only 40001/40P01.

**Relation to spike 0002 (X8, ADR-0005) and to #58**
- Agreement with spike 0002's database observations: the `run_claim` INSERT fixes the snapshot
  and `SET LOCAL` does not (A3 here, `backend_xmin` observed; X8 there); the hot-row failures seen
  here in C1 (Zipf and global projection keys) are all the same-row kind, `could not serialize
  access due to concurrent update`, at the projection statement - ADR-0005's first kind. No
  observation here contradicts X8 or ADR-0005.
- #58 (an idempotency key reused with other arguments): if a fingerprint of the bound arguments
  is compared, the comparison must not read `run_claim` (or `run_result`) inside the claiming
  SERIALIZABLE transaction. Reading `run_claim` there is this spike's "read then INSERT" control:
  72-78 % of attempts failed with 40001 in B (both runs), and when two claimants of the same ID
  both read it first, the waiting one gets 40001 instead of 23505 (reproduction probe 2(b)), so
  the idempotent path would turn into a retry. Writing the fingerprint with the claim (an INSERT,
  no read) and comparing it on the 23505 replay path, which already reads `run_result` in a
  separate READ COMMITTED transaction, stays within the rule; no observation here covers a
  fingerprint column itself.
- Carried-over rates: C4 above (retry, `RetryExhausted` and `57014` on one hot row with and
  without `for_update`); ADR-0005 Decision 4's candidates are not in this spike
  (change record).

**Consequence for the design** (applied after both reproductions agreed; items 1, 2, 3, 6 are
in design 7.3, 8.3 and 9.2, EN + KO; item 4 is a `Proposed` ADR, reviewed by the architect):
1. 8.3 internal-table rule: replace "Needs confirmation: ..." with a statement that spike 0003
   confirmed it (link), and correct "In the early stage when the table is small, a table-level
   lock is taken" to name the cause: a sequential-scan read (which the planner chooses for small
   or empty analyzed tables) takes a relation-level SIRead lock on the heap, so every write to
   that table conflicts with it. 4.6 is unchanged (it does not make the small-table claim).
2. 8.3 "Why the result is INSERTed into a separate table": keep the decision; note that the
   UPDATE form conflicts far less often than look-up-then-INSERT, but does conflict.
3. 9.2: tick items 1, 3, 4, 5 and the hot-row item, and item 2 as "partly" (4 as "partly" for
   the small-table cause), each with the link, once reproduction round 2 agrees with the rates.
4. **Decision change proposed: [ADR-0007](../adr/0007-ever-increasing-entity-keys.md)
   (Proposed, revised after the architect review).** The default `pk(generated="uuid7")` for user
   entities (4.2) makes "read a recent row by PK + INSERT into the same table" a false-conflict
   pattern under SERIALIZABLE (A6; C3 65-69 % of attempts in a worst case, against ~0.1 % for
   uuid4). The ADR proposes a uuid4 default with uuid7 / identity as explicit choices, to be
   decided after measurements added to design 9.5 and #65 (uuid4's insert / WAL cost, the
   conflict window, and the rate of the foreign-key case A7); keeping uuid7 and documenting the
   cost is its main alternative.
5. Open question for the runner (#22/#23): whether 53200 from the SSI conflict pool is
   classified as retryable, surfaced as a distinct error, or prevented by sizing
   (`max_connections` / `max_pred_locks_per_transaction`); not settled by this spike.
6. 7.3 (cost of the SERIALIZABLE default): add the two concrete false-conflict sources found
   here - plan-dependent relation locks on small tables, and right-edge locality of
   ever-increasing primary keys - with the item 5 numbers (uniform: SERIALIZABLE within about
   10 % of REPEATABLE READ's throughput - ratio of medians 0.954-1.028 here, 0.910-0.995 in the
   reproduction, paired medians within 5 % in both - and at most 1.007 attempts per commit; Zipf:
   retries dominated by same-row conflicts that REPEATABLE READ has too, SERIALIZABLE 0-17 %
   slower).
7. ADR-0005 / hot rows: the C4 numbers go to #64 as its baseline and to 7.3 if
   the maintainer wants the cost stated there; no design change follows from this spike.

## Reproduction

### Round 1: sections A and B (existence, fast profile)

- **Who:** pg-researcher, working independently. It had not run the spike before. It read Question, Setup and Method (including the change record) and the code under `spikes/0003-ssi-internal-tables/`, and wrote down its own observations before reading Observations and Verdict.
- **Date:** 2026-11-25 (20:48 to 21:12 local time).
- **Versions observed:**
  - `PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2) on aarch64-unknown-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit` (container `platina-postgres-1`, port 26432).
  - psycopg 3.3.9, binary, libpq 180006. Python 3.14.7.
  - Branch `docs/spike-0002-ssi-internal-tables` at `10a8517`, with the spike files untracked.
  - Settings from `SHOW` match Setup: `max_pred_locks_per_transaction = 64`, `max_pred_locks_per_relation = -2`, `max_pred_locks_per_page = 2`, `synchronous_commit = on`, `default_transaction_isolation = read committed`, `shared_buffers = 256MB`, `max_connections = 300`, `fsync = off`, `full_page_writes = off`, `wal_level = replica`.
- **Not reproduced in this round:** sections C and D (rates). Port 26433 was never used.
- **Host:**
  - Load averages (1/5/15 min, 15 cores) were 9.79 / 21.86 / 32.50 at the start, 21.51 when the load harness started, 35.21 / 36.94 / 34.05 when it ended, and 33.82 at the end of all runs.
  - Another client was on the same fast database at the start: schema `repro0002_28861`, sessions `T1` (active) and `T2` (`idle in transaction`). Both were gone by 21:12. [Author's note, added later: the schema name is the one `spikes/0002-use-cases-on-paper/repro/db/harness.py` (spike 0002's database reproduction) creates, `repro0002_<pid>`.]
  - Throughput numbers below therefore say nothing about speed. Only existence and pattern are compared.

**What was run**
1. The spike code copied to `spikes/0003-ssi-internal-tables/results/repro/code/` (git-ignored) and the copies run, so all output landed under the copy's `results/`:
   - `uv run python <copy>/interleave.py --port 26432` (A1-A5, 677 log lines, 21.8 s);
   - `uv run python <copy>/interleave.py --port 26432 A6`;
   - `uv run python <copy>/load.py exist --port 26432` (80 records, 19 min 23 s).
2. Its own probe, `results/repro/probe/probe.py` (psycopg; own schema `pgr0002`, dropped at the end). Interleavings pinned, one statement at a time; a blocking statement runs from a thread. It covers:
   - P1: fresh uuid7 claim, then the full internal set (claim, outbox with an `xid` index, result), with tables empty and with 1,000,000 claims and outbox rows.
   - P2: re-INSERT of a key that was inserted and rolled back, by the same session and by another session, in both states.
   - P3a/P3b: "SELECT then INSERT", lock rows plus `EXPLAIN ANALYZE`; then two sessions in phased order, 5 pinned reps per state.
   - P4: fencing with S1 at SERIALIZABLE and at READ COMMITTED: wait then commit, wait then rollback, rerun after commit, snapshot before S1's commit; extra case: S2 reads X first, then S1 inserts and commits X, then S2 inserts X.
   - P5: `ON CONFLICT DO UPDATE` on an existing bigint key, a new bigint key, a new uuid7 key and an existing uuid7 key, against a plain `UPDATE` for contrast.
   - P6: "read own recent row by PK + INSERT", uuid7 vs uuid4, recent vs old rows, two sessions phased, 20 pinned reps per cell.
3. A second probe, `results/repro/probe/probe2.py` (schema `pgr0002b`, dropped):
   - (a) the `insert_update` load (16 processes x 10 s), with and without one idle SERIALIZABLE transaction holding a snapshot, 2 reps each, to look for the cause of a 53200 seen in B;
   - (b) both sessions read X, then both INSERT X; S2 waits; S1 commits.

After the runs only `public` remains on the fast database.

**Method vs code.** The code does what the Method says. Small, harmless differences:
- A2 runs the `current_setting` check between the observation and S2's COMMIT; that check produces the `25P02` lines.
- A1 `full` runs `SELECT pg_current_xact_id()::text`, not the bare call the Method shows.
- In A6 the log label `rows=` is the table's row count.
- `load.py` writes only `load_exist.jsonl`; the `load_exist.txt` named under Observations is redirected stdout.
- B counts and moves on after *any* error, not only 40001/40P01. That is how the 53200 below became visible.

**Observations**

*A1.* Lock rows, pages and outcomes identical to the write-up's table, row for row:
- `claim`, `claim_retry` and `full`: 0 SIReadLock rows in both orders and both states; every session commits.
- `read_insert` and `insert_update` with tables empty: 3 x `relation run_claim` / `relation run_claim_u` (the heap); `ok 40001 40001` in both orders.
- 1M rows: 3 x `page run_claim_pkey page=3852` / `run_claim_u_pkey page=3852`; `read_insert` `ok 40001 ok` (sequential) and `ok 40001 40001` (phased); `insert_update` `ok 40001 ok` (sequential) and `ok ok ok` (phased).
- Every 40001: `could not serialize access due to read/write dependencies among transactions`, detail `Reason code: Canceled on identification as a pivot, during commit attempt.`

*A2.* Identical, with S1 at SERIALIZABLE and at READ COMMITTED:
- F1 and F2: S2 waits with `wait_event=Lock/transactionid`, ungranted `('transactionid', 'ShareLock')`.
- F1: `ERROR 23505: duplicate key value violates unique constraint "run_claim_pkey" | detail: Key (id)=(...) already exists.`, 0 SIRead rows, `count = 1`.
- F2: S2's INSERT `ok rowcount=1`, 0 SIRead rows, COMMIT ok, `count = 1`.
- F3 and F4: 23505, never 40001.

*A3.* Same pattern; only xid values differ (`backend_xid=5024257 backend_xmin=5024256`): `backend_xmin=None` after `BEGIN` and after `SET LOCAL`; xid and xmin set while the claim waits. F5: S2 reads `0`, its UPDATE fails with `40001: could not serialize access due to concurrent update`, final 100. F5-read commits. F5-control ends at 1.

*A4.* Identical: plain `UPDATE` 3 x `page user_spending_pkey page=138`; `ON CONFLICT DO UPDATE` on existing keys, and on new uuid7 keys with `proj_new` empty or at 100k rows: **0** rows; all sessions commit.

*A5.* Identical:

| Table | `pg_class` (relpages, reltuples) | Plan | SIRead lock | Outcome |
|---|---|---|---|---|
| 30 rows, never analyzed | `(0, -1.0)` | Index Scan | `page small_orders_pkey page=1` | all ok |
| 30 rows, analyzed | `(1, 30.0)` | **Seq Scan** | 3 x `relation small_orders` | `ok 40001 40001` |
| 100k rows, never analyzed | `(0, -1.0)` | Index Scan | `orders_pkey page=1` | all ok |
| 100k rows, analyzed | `(1392, 100000.0)` | Index Scan | `orders_pkey page=1` | all ok |

*A6.*
- uuid7, recent rows: both sessions lock `page orders_pkey page=387`, plus heap tuples `orders page=1333 tuple=26/27`. Phased: S2 ok, S1 `40001 ... pivot, during commit attempt`. Sequential: ok / ok.
- uuid7 old rows: pages 143 / 247, all ok. uuid4 recent rows: pages 499 / 498 (adjacent but distinct), all ok. uuid4 old rows: pages 266 / 300, all ok. (Page numbers for random rows differ from the write-up; same conclusion.)

*B.* All 80 records report `{'iso=serializable': 16}`; at fill factor 70 `orders` had 0 non-HOT updates in every run.

| Internal | Business | ff | 40001 per run | 40001 / attempt, median (range) |
|---|---|---|---|---|
| `claim` / `claim_retry` / `full` | none | 70 | 0,0,0,0,0 each | 0 |
| `read_insert` | none | 70 | 38,126, 26,281, 26,508, 12,572, 9,587 | 77.8 % (77.0-77.8) |
| `insert_update` | none | 70 | 40, 52, 12, 40, 16 | 0.065 % (0.036-0.142) |
| `none` / `pad1` / `pad2` / `pad4` | disjoint | 70 | 0 in every run | 0 |
| `claim` / `claim_retry` / `full` | disjoint | 70 | 0 in every run | 0 |
| `read_insert` | disjoint | 70 | 3,516, 18,430, 22,842, 18,420, 13,034 | 72.0 % (71.7-72.2) |
| `insert_update` | disjoint | 70 | 10, **0**, 1, 1, 4 | 0.0033 % (0-0.039) |
| `pad1` | disjoint | 100 | 9, 1, 2, 4, 4 | 0.013 % (non-HOT `orders` 2,048-3,315) |
| `claim` | disjoint | 100 | 6, 4, 8, 5, 6 | 0.018 % (non-HOT 1,914-3,703) |

Where the 40001 were raised: `read_insert`/none: COMMIT 78,967 (pivot, commit attempt) + 90 (prepared pivot), `INSERT INTO run_claim` 34,017 (during write). `read_insert`/disjoint: COMMIT 44,159, `UPDATE orders` 29,757, `SELECT * FROM orders` 2,157, `INSERT INTO run_claim` 169. ff 100: `COMMIT` and `UPDATE orders` for both `pad1` and `claim`.

**53200 in B, not in the write-up.** In rep 1 of `insert_update`/disjoint: **23 x `53200 not enough elements in RWConflictPool to record a read/write conflict`** (22 at `INSERT INTO run_claim_u`, 1 at `UPDATE run_claim_u`). Once only, under heavy host load, possibly while another client was still on the server. Probe 2(a) did not bring it back (16 processes x 10 s, with and without an idle SERIALIZABLE transaction holding a snapshot: only 40001, 276 / 211 / 39 / 435 per 10 s). The cause is **not isolated**; what stands is that under this SSI load PostgreSQL can return 53200 (out of memory, not retryable by the design's 40001/40P01 rule) instead of 40001.

**Own probe** (`probe_out.txt`, `probe2_out.txt`):
- P1 / P2: 0 SIReadLock rows in every case, empty and 1M: after a fresh uuid7 claim; after the full internal set (claim + outbox with an `xid` index + result + `pg_current_xact_id()`); after re-INSERT of a key rolled back by the same session or by another session.
- P3a: empty analyzed table: `Seq Scan on claim` -> `relation claim` (heap); 1M rows: `Index Only Scan using claim_pkey` -> `page claim_pkey 3852` (rightmost leaf).
- P3b: two sessions phased: 5/5 reps empty and 5/5 at 1M end with S1 `40001 ... Canceled on identification as a pivot, during commit attempt.` after S2 committed; both hold the same lock (relation when empty, page 3852 at 1M).
- P4: reproduces A2 at both S1 levels (wait `('Lock', 'transactionid')`, ungranted `('transactionid', 'ShareLock', False)`; commit -> `23505 duplicate key value violates unique constraint "claim_pkey"`; rollback -> S2 proceeds and commits, `count = 1`; rerun after commit and the F4 shape -> 23505; extra case where S2 *read* X before S1 inserted and committed it -> still 23505).
- Probe 2(b): when *both* sessions read X before inserting it, the waiting S2 gets `40001 ... Canceled on identification as a pivot, during conflict in checking.` instead of 23505.
- P5: `ON CONFLICT DO UPDATE` took 0 SIReadLock rows for an existing bigint key, a new bigint key, a new uuid7 key and an existing uuid7 key, in both states; the plain `UPDATE` took `page proj_pkey 138`.
- P6 (20 pinned phased reps per cell): uuid7 recent **20/20** end with 40001, both holding `page t_pkey 387`; uuid7 old 0/20; uuid4 recent 0/20; uuid4 old 0/20. (Its "old" sample used `TABLESAMPLE SYSTEM (1) LIMIT 2`, so both sessions read the same old leaf; they still did not conflict, because the inserts land elsewhere.)

**Differences from the write-up's Observations**
1. B "No error other than 40001 occurred" did not hold in this run: 23 x 53200 (above). (The write-up was corrected to say so.)
2. B counts and attempts differ, as expected on a loaded host; the 40001 pattern per variant is the same, including **one zero run** for `insert_update`/disjoint; the `insert_update`/none percentages overlap (0.038-0.120 % vs 0.036-0.142 %).
3. A6 leaf page numbers for old and uuid4 rows differ (random choice); same outcome.
4. A3 xid values differ; same outcome.

**Per item**

| Item | Reproducer | Reason |
|---|---|---|
| 1 | **agree: holds** | (1a) 0 SIRead rows in A1 (`claim`, `claim_retry`, `full`, empty and 1M), after A2's fenced INSERTs, and in P1/P2 (also a key rolled back by another session); (1b) all A1 sessions commit; (1c) 0 x 40001 in 5/5 runs; (1d) 0 = padded baselines at ff 70. |
| 2 | **agree: partly** | Both controls take the lock and give a pivot 40001 in A1 and in P3b (10/10). Under load `read_insert` gives ~72-78 % 40001, but `insert_update`/disjoint had 0 in one of five runs here too. With business `none` it was above zero in 5/5 runs in both runs, so the "partly" depends on reading the criterion against the disjoint/`pad2` baseline; that reading is the conservative one. |
| 3 (fencing) | **agree: holds** | Wait on `transactionid` ShareLock; commit -> 23505, rollback -> proceeds, rerun -> 23505; F4 -> 23505; same at both S1 levels; also 23505 when only S2 had read X. Condition: probe 2(b) shows **40001 instead of 23505 when both claimants read `run_claim` first** - "never 40001" holds only while the internal-table rule holds. |
| 4a | **agree: holds** | As 1a, empty and 1M. |
| 4b | **agree: partly** | The relation-level SIRead lock and the 40001 it causes between different rows are real; the cause is a Seq Scan plan (analyzed small or empty table), not size: a never-analyzed 30-row table is read by Index Scan and does not conflict. P3a shows the same for an empty analyzed `claim`. |
| A4 upsert (off-checklist) | **agree** | 0 SIRead rows for `ON CONFLICT DO UPDATE`, new and existing keys, empty and 100k; P5 adds the bigint new key and the existing uuid7 key; a plain `UPDATE` takes an index-page lock. |
| A6 uuid7 locality (off-checklist) | **agree (existence)** | Same rightmost leaf (`page=387`) and a pivot 40001 in phased order; none for uuid4 or old rows; P6 pinned 20/20 vs 0/20, 0/20, 0/20. The rate under load is not checked (section C). |

No verdict disagreed with. Two corrections requested before the verdicts are applied, both made in this write-up: (1) Observations B no longer says only 40001 can occur, and 53200 is recorded; (2) item 3 states that "23505, never 40001" depends on `run_claim` never being read inside the claiming transactions.

Output: `spikes/0003-ssi-internal-tables/results/repro/` (`interleave_stdout.txt`, `interleave_a6_stdout.txt`, `load_exist_stdout.txt`, `load_uptime.txt`, `code/results/interleave.txt`, `code/results/load_exist.jsonl`, `probe/probe.py`, `probe/probe_out.txt`, `probe/probe2.py`, `probe/probe2_out.txt`).

### Round 2: sections C and D (rates, durable profile)

- **Who:** pg-researcher, working independently. It had not run the spike or round 1. It read Question, Setup, Method (including the change record) and the code, ran C and D and its own probe, and wrote down its numbers before reading Observations and Verdict.
- **Date:** 2026-11-25/26, 23:37 to 01:15 local time: C 23:38:15-00:22:27; D 00:22:32-00:49:48; D order checks 00:50:17-01:01:22 and 01:08:49-01:14:30; own probe 01:01:37-01:07:44.
- **Versions observed:** `PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2) on aarch64-unknown-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit` (container `platina-postgres-durable-1`, port 26433); psycopg 3.3.9, binary, libpq 180006; Python 3.14.7. Branch `docs/spike-0003-ssi-internal-tables` at `fc7c9e3`; the copies were byte-identical (`cmp`) to the tracked `common.py`, `harness.py`, `load.py`, `bench.py` and `schema.sql`. Settings from `pg_settings` match Setup (`fsync = on`, `full_page_writes = on`). Port 26432 was not used.
- **Host (from the gate's records):** at 23:37 load averages 4.88 / 16.34 / 19.68 and external CPU 314 %; other workloads present throughout (another agent session's test runs in a different project, the non-platina database containers).
  - C: 120 runs kept, **0 discarded**, one gate wait (522.5 %); external CPU before a run 27-485 % (median 135), mean during a run 49-494 % (median 210), highest single sample 735 %, highest 1-min load 33.1.
  - D: 30 pairs kept, **0 discarded**, no waits; before 48-473 % (median 188), mean during 129-428 % (median 205), highest sample 684 %, highest 1-min load 35.0.
  - Order checks: 18 pairs kept, 0 discarded. The probe is not gated (external CPU 112 % before, 164 % after).

**What was run**
1. The spike code copied to `spikes/0003-ssi-internal-tables/results/repro2/code/` and run from the repository root, one after the other, gate at its default 500 %:
   - `SPIKE_QUIET_MAX_WAIT_S=7200 uv run python <copy>/load.py rates --port 26433 --resume` (no prior records): 120 records;
   - `SPIKE_QUIET_MAX_WAIT_S=7200 uv run python <copy>/bench.py --port 26433 --resume`: 60 records (30 pairs).
2. Order checks for D (separate copies `order64/`, `order32/`, `orderz64/`; only the CLI narrowed so the level order alternates *within* one configuration), each 6 pairs, 3 in each order: `bench.py --port 26433 --workers 64 --dists uniform --reps 6`, the same with `--workers 32`, and with `--workers 64 --dists zipf`.
3. Own probe, `results/repro2/probe/probe.py` (own tables `r2p_*`, dropped; threads, plain psycopg, one statement per round trip, durable, 3 reps per cell):
   - P1: 16 workers x 10 s, no retry; read own most recent committed row by PK, then INSERT a new row; uuid7 vs uuid4 (100,000 preloaded keys of the same kind), recent vs old rows.
   - P2: one hot row at 8 and 32 workers x 8 s; claim INSERT, then `blind`, `read` or `FOR UPDATE`, then `UPDATE`; at most 4 attempts with the design's full jitter, `statement_timeout = '2s'`.
   - P3: 16 workers x 10 s, no retry; read and update an own order, plus no projection, an `UPDATE` of an own disjoint key, or `ON CONFLICT DO UPDATE` on an own existing key.

**Method vs code.** The code does what C and D say (retry policy, two round trips with one Sync each, key assignment, the C2 background/probe split, C4 load forms and `hot_total_ok`). Findings:
1. **D order is confounded per configuration.** ABBA alternates over the global block counter and each rep has 6 blocks, so in every rep the same configuration gets the same order: uniform always SERIALIZABLE first, Zipf always REPEATABLE READ first, 5/5 pairs each - in this run and in the author's `results/bench.jsonl`. The order checks (step 2) show no consistent first-position effect, so the conclusions do not change; the text should say so. (Corrected in Observations D.)
2. **C runs get only 3 gate samples each** (a run is about 20 s; each `docker stats` sample takes ~2 s plus the 5 s period); D pairs get 7-8.
3. **Harmless stderr noise:** many `error ignored terminating <psycopg.Pipeline [INERROR|IDLE ...]>: pipeline aborted` lines - psycopg logs the failing exit Sync after an error was already raised inside the block (`psycopg/_pipeline.py` `__exit__`). Statement attribution stays right: `_pipeline_base.py` `_process_results` calls `_check_results` before `_set_results`, so the failing cursor and the aborted ones keep `pgresult = None`; 0 `?` labels in C.
4. **C2 per-attempt rates include retries.** Retry attempts neither wait nor sleep (only attempt 1 does), so 46-47 % understates the first-attempt effect (a reading note).

**Observations** (median (range) over 5 runs; 32 workers unless stated). No SQLSTATE other than 40001 anywhere (no 40P01, 57014, 53200); `version_mismatch_committed` 0; every worker reported the requested level.

*C1-C3*

| Variant | 40001 / attempt | Attempts / commit | Exhausted / run |
|---|---|---|---|
| C1 baseline | 0 % | 1.000 | 0 |
| C1 `update` disjoint | 0 % (5/5 zero) | 1.000 | 0 |
| C1 `update` Zipf | 26.7 % (25.7-27.0) | 1.364 | 358 |
| C1 `update` global | 80.2 % (77.3-81.1) | 5.06 | 7,284 |
| C1 `upsert_existing` disjoint | 0 % (5/5) | 1.000 | 0 |
| C1 `upsert_existing` Zipf | 26.6 % (25.6-26.8) | 1.362 | 358 |
| C1 `upsert_existing` global | 78.7 % (77.7-81.9) | 4.69 | 7,130 |
| C1 `upsert_new` | 0 % (5/5) | 1.000 | 0 |
| C2 probes `nowait` / `wait` / `sleep` | 26.4 % (26.1-26.6) / 46.6 % (46.3-47.2) / 47.1 % (46.5-47.6) | 1.358 / 1.871 / 1.890 | 179 / 26 / 27 |
| C2 background, same runs | 26.1 % / 18.4 % / 18.3 % | | |
| C3 uuid7 recent | **65.2 % (62.7-65.7)** | 2.87 | 4,883 (20.2 % of commands) |
| C3 uuid7 old | 0 % | 1.000 | 0 |
| C3 uuid4 recent / old | 0.09 % (0.08-0.10) / 0.10 % (0.09-0.12) | 1.001 | 0 |

C1 Zipf and global failures are 99.6-100 % `concurrent update` at the projection statement; C2 almost all `concurrent update` at `UPDATE orders`; C3 uuid7 recent failures are all pivots (`INSERT INTO orders` "during write" 72 %, outbox INSERT 13 %, COMMIT 13 %).

*C4, one hot row* (final value matched in 45/45 runs; no 57014; `for_update` fails 100 % at `SELECT ... FOR UPDATE`, the other forms at `UPDATE hot`; all `concurrent update` plus a handful of rw pivots at COMMIT):

| Workers | blind | read | for_update |
|---|---|---|---|
| 8: 40001 / attempt, RetryExhausted % | 31.2 % (28.3-37.0), 6.9 | 30.5 % (29.5-36.1), 6.8 | 30.8 % (29.5-37.5), 7.1 |
| 32 | 73.9 % (72.4-77.4), 34.7 | 75.9 % (73.4-77.4), 37.3 | 74.9 % (71.5-75.5), 37.1 |
| 64 | 90.3 % (89.7-91.8), 67.0 | 91.2 % (90.3-92.0), 69.4 | 89.1 % (86.9-89.9), 63.9 |

*D* (medians over 5 runs)

| | 8 workers | 32 workers | 64 workers |
|---|---|---|---|
| uniform TPS SER / RR | 4,055 / 4,075 | 5,866 / 6,182 | 6,069 / 6,669 |
| uniform ratio of medians (paired median, range) | 0.995 (0.989, 0.953-1.048) | 0.949 (1.031, 0.857-1.074) | **0.910** (0.954, 0.875-1.070) |
| uniform SER attempts / commit | 1.001 | 1.003 | 1.007 |
| Zipf ratio of medians (paired) | 0.938 (0.948) | 0.943 (0.922) | 0.834 (0.834, 0.812-0.922) |
| Zipf exhausted % SER / RR | 0.05 / 0.05 | 2.14 / 2.18 | 6.54 / 5.90 |
| Zipf 40001 / attempt SER / RR | 5.8 / 4.9 % | 21.7 / 19.5 % | 35.2 / 31.0 % |

- Order checks (3 pairs in each order per configuration): uniform 64 ratio of medians 0.960, paired 0.958 (0.852-1.073); uniform 32 1.000, paired 1.002 (0.893-1.109); Zipf 64 0.921, paired 0.917 (0.754-1.068). SER-first and RR-first pairs do not differ consistently; single pairs fall below 0.90 in both orders (pair-to-pair noise about ±10 %).
- Invariants: transfer total held in 60/60 runs and 36/36 order-check runs. Negative pocket sums: SER 0 in all 30 runs and 18 order-check runs; RR 2 of 30 runs (8/Zipf 1 user, min -21; 64/Zipf 2 users, min -6), plus 2 of the 6 Zipf order-check runs.
- Per command type, 64/Zipf, SER vs RR: pay 42.4 vs 44.5 %, create **27.8 vs 0 %**, transfer 50.7 vs 52.4 %, pocket 12.5 vs 5.9 %, reprice 11.8 vs 6.3 %; SER pivots led by `INSERT INTO orders` (30,465), then `UPDATE pockets` (5,171) and the range read (2,783).

*Own probe*
- P1 (16 workers, no retry): uuid7 recent **74.3 / 74.4 / 74.5 %** 40001 per attempt, all rw-dependency; uuid7 old 0 / 0 / 0; uuid4 recent 0 / 0.003 / 0.018 %; uuid4 old 0.007 / 0.021 / 0.014 %.
- P2 (one hot row): 8 workers blind 34-36 %, read 39-41 %, for_update 38-40 % per attempt, RetryExhausted 6.2-6.4 / 7.8-8.8 / 8.2-9.1 % of commands; 32 workers 80-82 / 86-87 / 83 %, RetryExhausted 42-45 / 55-57 / 48-49 %; all `concurrent update`, no 57014, final value = commits in 18/18 runs. With one statement per round trip (longer transactions) exhaustion is higher than in the pipelined C4; `FOR UPDATE` again does not reduce failures compared with blind.
- P3 (disjoint projection keys): 0 x 40001 in 9/9 runs (none / update / upsert_existing, 22,058-30,140 attempts each).

**Differences from the write-up's Observations**
1. C3 uuid7 + recent: 65.2 % (62.7-65.7) vs 69.2 % (65.1-72.3); attempts per commit 2.87 vs 3.24; exhausted per run about the same (4,883 vs 4,936). Same conclusion; P1 gives 74 % without the harness.
2. C4 at 8 workers: 30.5-31.2 % vs 40.1-41.3 %, RetryExhausted 6.8-7.1 % vs 9.2-9.6 % (ranges overlap at 30-37 %); at 32 workers 3-4 points lower; at 64 the same.
3. C1 global key: 78.7-80.2 % vs 81.2-82.1 %; attempts per commit 4.69-5.06 vs 5.32-5.60. Zipf matches within 0.5 points.
4. D uniform 64 workers, ratio of medians: 0.910 vs 1.028; 0.960 in the alternating-order check. The draft "Consequence 6" said "SERIALIZABLE within 5 % of REPEATABLE READ's throughput" - not supported by this run (9 % at 64 workers by ratio of medians; the paired medians are within 5 %); asked to read "within about 10 %" or cite paired medians. (Corrected.)
5. D Zipf ratios: 0.938 / 0.943 / 0.834 vs 0.987 / 1.071 / 0.957; order check at 64 gives 0.921. Not judged by the criterion, but in all its Zipf data SERIALIZABLE was 6-17 % slower, not equal.
6. D order: "each level ran first in 15 blocks (ABBA)" should add that each configuration had a fixed order (Method vs code, finding 1); the order checks remove the concern. (Corrected.)
7. RR pocket breaks: 2 of 30 runs vs 4 of 30; none under uniform here.

**Per item**

| Item | Reproducer | Reason |
|---|---|---|
| 3 (inline projection rates) | **agree: holds** | Baseline 0 in 5/5, so the criterion can be decided. Disjoint keys 0 in 5/5 for `update`, `upsert_existing`, `upsert_new`; P3 also 0 in 9/9. Zipf about 27 % and global about 79-80 %, almost all same-row `concurrent update`. |
| 5 (SER vs RR) | **agree: holds** | Uniform SER/RR ratio of medians 0.995 / 0.949 / 0.910 (>= 0.90) and SER attempts per commit 1.001 / 1.003 / 1.007 (<= 1.05); both invariants held in every SER run (30 + 18); the "partly" clause does not fire (Zipf exhaustion above 1 % under RR too: 2.18 / 5.90 % vs SER 2.14 / 6.54 %). Caveat: the 64-worker margin was narrow in its main run (0.910); the alternating-order check gave 0.960. |
| C2 snapshot aging | **agree** | Probes 26.4 / 46.6 / 47.1 % (nowait / wait / sleep); background 26.1 / 18.4 / 18.3 %. `wait` ≈ `sleep`: the cost is the snapshot's age, not the wait. |
| C3 uuid7 locality | **agree** | 65 % (harness) and 74 % (P1) for uuid7 + recent, against 0 % for uuid7 + old and <= 0.12 % for uuid4; raised as pivots at the INSERT; in D, `create` 27.8 % vs 0 % at 64/Zipf. The ADR candidate (Consequence 4) stands. |
| C4 one hot row | **agree** (8-worker rates lower) | About 31 / 75 / 90 % 40001 per attempt and 7 / 35-37 / 64-69 % RetryExhausted at 8 / 32 / 64 workers; the same for blind, read and `FOR UPDATE` (which only moves the failure to the load statement); no 57014 at 2 s. P2 agrees and shows exhaustion rises with transaction length. |

No verdict disagreed with. Two corrections requested, both made: (1) the D text on ABBA order (fixed per configuration, and checked); (2) Consequence 6's "within 5 %". Everything planned was completed.

Output: `spikes/0003-ssi-internal-tables/results/repro2/` (`load_rates.log`, `bench.log`, `code/results/load_rates.jsonl`, `code/results/bench.jsonl`, `order64.log`, `order32.log`, `orderz64.log`, `order{64,32,z64}/results/bench.jsonl`, `probe/probe.py`, `probe/probe.log`; git-ignored).


### Round 3: A7 (foreign-key checks, fast profile)

- **Who:** pg-researcher, working independently; it had not run A7 before. It read the Question, Method section A, the change record's "A7 added (post hoc)" entry and the A7 code (`a7`, `_a7_key`, `run_case`), ran the copy and its own probe, and wrote its numbers down before reading the A7 Observations, the Verdict and the Reproduction section.
- **Date:** 2026-11-26, 11:16 to 11:21 local time (KST).
- **Versions observed:** `PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2) on aarch64-unknown-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit` (container `platina-postgres-1`, port 26432); psycopg 3.3.9, libpq 180006; Python 3.14.7. Branch `docs/spike-0003-ssi-internal-tables`, started at `32a0071` with A7 uncommitted; the author committed it as `e73a513` during the round, and the copied `interleave.py` has the committed file's SHA-256. `SHOW`: `max_pred_locks_per_transaction = 64`, `max_pred_locks_per_relation = -2`, `max_pred_locks_per_page = 2`, `default_transaction_isolation = read committed`, `synchronous_commit = on`, `fsync = off`.
- **Host:** no other client on the fast database at the start or the end; load average 16.36 / 15.56 / 9.97 at 11:21 (existence only). Port 26433 not used.

**What was run**
1. The spike code copied to `spikes/0003-ssi-internal-tables/results/repro3/code/`, then `uv run python <copy>/interleave.py --port 26432 A7`.
2. Own probe `results/repro3/probe/fkprobe.py`: tables `r3_par(id uuid pk)`, `r3_chi(id uuid pk, par uuid not null references r3_par)` and a no-FK control `r3_chi_nofk`; `pageinspect` (`bt_page_stats`) to classify the locked index pages (dropped afterwards). Per configuration: the lock observation for a parent new in the same transaction, committed just before, or old - each through the FK, into the no-FK control, and as the explicit query `RI_FKey_check` builds (`SELECT 1 FROM ONLY r3_par x WHERE id = $1 FOR KEY SHARE OF x`); and the orders P1, P2, P3, implemented independently, 10 pinned repetitions each, statement and COMMIT errors recorded separately. Configurations: `main` (same generator for parent and child keys, uuid7 then uuid4, 100,000 parents, plus an order P2-old with children of old parents), `mixed` (uuid7 parents with uuid4 children and the reverse), `sizes` (0, 200 and 1,000,000 parents, each key type).
3. `probe/sizeplan.py`: the generic plan of the RI query (`EXPLAIN (GENERIC_PLAN)`) and the FK check's SIRead rows for 0 to 100,000 parents, analyzed and never analyzed.
4. `probe/commit_after_error.py`: what `COMMIT` returns in autocommit mode after a statement of the transaction failed.

**Method vs code.** The code does what the change record says, with two differences: (1) `run_case` counted a repetition as failed only if `COMMIT` raised; after a failed statement the transaction is aborted and `COMMIT` succeeds with tag `ROLLBACK` (`COMMIT raised nothing; statusmessage = ROLLBACK`), so a statement-level 40001 would have been printed but counted as "ok" - no statement raised in any run of this round, so the totals were unaffected (corrected afterwards by the author, see the change record); (2) in the lock observation the "committed just before" parent is committed once, before the "own" case, so it is not the newest parent - both lie on the same rightmost leaf, so the observation is unaffected.

**Observations: spike code (copy)**

| Parent | uuid7 | uuid4 |
|---|---|---|
| new, same transaction | `page fk_parent_pkey page=387` | `page fk_parent_pkey page=251` |
| committed just before | `page fk_parent_pkey page=387` + `tuple fk_parent page=636 tuple=149` | `page fk_parent_pkey page=172` + `tuple fk_parent page=636 tuple=149` |
| old | `page fk_parent_pkey page=312` + `tuple fk_parent page=512 tuple=147` | `page fk_parent_pkey page=495` + `tuple fk_parent page=415 tuple=40` |

| Order | uuid7 | uuid4 |
|---|---|---|
| P1 | 10/10: S2 COMMIT failed every time, S3 and S1 committed | 0/10 |
| P2 | 10/10: S1 COMMIT failed every time | 0/10 |
| P3 | 0/10 | 0/10 |

Every failure at COMMIT, verbatim: `40001 could not serialize access due to read/write dependencies among transactions | Reason code: Canceled on identification as a pivot, during commit attempt.`

**Observations: own probe**
- **The locks come from the FK check:** the FK child INSERT and the explicit `FOR KEY SHARE` query take the same SIRead rows; the no-FK control takes none. uuid7 at 100,000 rows: the index page for a new or just-committed parent is the rightmost leaf (`page=387`, `rightmost=yes`), for an old parent an inner leaf; at 1,000,000 rows the same on `page=3852`; uuid4 never the rightmost leaf. A parent inserted by the same transaction gets no heap tuple lock, only the index page (`PredicateLockTID` in `src/backend/storage/lmgr/predicate.c`, REL_18_STABLE: "If we wrote it; we already have a write lock" -> return). The check runs with the transaction snapshot (`RI_FKey_check` calls `ri_PerformCheck(..., detectNewRows = false ...)` for a non-partitioned parent, `src/backend/utils/adt/ri_triggers.c`).
- **Main, 100,000 parents:** uuid7 P1 10/10 (S2), P2 10/10 (S1), P3 0/10, P2-old 0/10 (the sessions locked different inner leaves); uuid4 0/10 in every order. Same message and reason code; all at COMMIT; no statement errors.
- **Child keys do not matter:** uuid7 parents with uuid4 children 10/10, 10/10, 0/10; uuid4 parents with uuid7 children 0/10, 0/10, 0/10; the child's own primary key takes no SIRead lock.
- **1,000,000 parents:** as at 100,000 (uuid7 10/10, 10/10, 0/10; uuid4 0/10 everywhere).
- **Small analyzed parent tables change the lock and the outcome:** with 0 or 200 parents after `VACUUM ANALYZE` the FK check takes `relation r3_par` (a relation-level SIRead lock on the parent heap) and no index page lock; then:

  | Parents | Keys | P1 | P2 | P3 |
  |---|---|---|---|---|
  | 0 | uuid7 | 10/10 (S2 and S1 fail every rep) | 10/10 (S1) | **10/10** (S1) |
  | 0 | uuid4 | 10/10 (S2 and S1) | **10/10** (S1) | **10/10** (S1) |
  | 200 | uuid7 | 10/10 (S2 and S1) | 10/10 (S1) | **10/10** (S1) |
  | 200 | uuid4 | 10/10 (S2 and S1) | **10/10** (S1) | **10/10** (S1) |

  Every failure the same pivot 40001 at COMMIT.
- **The cause is the plan, not the size** (`sizeplan.py`): analyzed, 0 / 50 / 200 / 400 parents (relpages 0-3): generic plan `LockRows -> Seq Scan on r3_par x`, SIRead `relation r3_par`; analyzed, 1,000 parents and more (relpages 6+): `Index Scan using r3_par_pkey`, index page + heap tuple; never analyzed (`reltuples = -1`), every size from 0 to 100,000: Index Scan. The switching point (between 400 and 1,000 rows here) depends on row width and cost settings.
- **Why P3 commits under an index scan (inference, consistent with the data):** the check reads only its own key's heap tuple, so it never meets the other session's earlier uncommitted insert on the same leaf; under a sequential scan it visits that tuple (`HeapCheckForSerializableConflictOut`), which records an edge both ways, and P3 fails 10/10.

**Differences from the write-up's A7 Observations**
- Locks: identical page numbers for a new or just-committed uuid7 parent (`page=387`, `tuple fk_parent page=636 tuple=149`); old-parent and uuid4 pages differ (random keys), with the same classification in every case.
- Outcomes: identical in every cell, with the same SQLSTATE, message and reason code.
- Not in the write-up (added since): the plan condition - the claim holds while the RI query uses an index scan; on an analyzed parent of a few heap pages it is a sequential scan with a relation lock, and uuid4 parents and P3 fail 10/10 too (item 4b's mechanism through the FK check). uuid4's 0/10 at 100,000 parents is the sessions landing on different leaves (508 here), not a structural absence. And the COMMIT-only count.

**Statement:** agree for the configuration A7 fixed; partly overall. Agree with every A7 observation at 100,000 parents (FK check locks the parent's primary-key leaf, the rightmost for new or recent uuid7 parents; uuid7 P1 and P2 fail 10/10 with a pivot 40001 at COMMIT; P3 and all uuid4 orders commit; child keys and 1,000,000 parents change nothing). Partly, because any conclusion that uuid4 parent keys or the parents-first order avoid the conflict needs the condition "the parent is read by an index scan". Requested: state the plan and size condition next to the A7 table and in any ADR text that leans on A7; fix or note the COMMIT-only count. (Both done: A7 Observations "Conditions", the change record, ADR-0007.)

Output: `spikes/0003-ssi-internal-tables/results/repro3/` (`a7_run1.txt`, `code/results/interleave.txt`, `probe/fkprobe.py`, `probe/out_main.txt`, `probe/out_mixed.txt`, `probe/out_sizes.txt`, `probe/sizeplan.py`, `probe/out_sizeplan.txt`, `probe/commit_after_error.py`; git-ignored).
