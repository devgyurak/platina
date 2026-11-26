# ADR-0007: Ever-increasing entity keys and SSI false conflicts

- Status: Proposed
- Date: 2026-11-26
- Related: design sections 4.2 (`pk(generated=...)`, "Client-generated IDs are the default"),
  7.3, 8.3 (internal-table rule), 9.2, 9.5; ADR-0002 (injected ID source), ADR-0003 (its
  `pk(generated="uuid7")` example); spike 0003 (`docs/spikes/0003-ssi-internal-tables.md`, A6,
  A7, C3); issues #3, #58, #65

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- Design 4.2 makes a client-side UUIDv7 the default primary key of an entity
  (`pk(generated="uuid7")`); `generated="identity"` (a sequence) is the alternative. Both are
  ever-increasing: new rows land on or near the rightmost leaf page of the primary-key index
  (exactly the rightmost for one process; near it with several hosts and clock skew).
- Design 8.3 already relies on what that means under SERIALIZABLE: PostgreSQL takes B-tree
  predicate (SIRead) locks per leaf page, so transactions that read the rightmost page and insert
  into it form rw-dependency cycles; that is why internal tables are only INSERTed into inside
  SERIALIZABLE. Spike 0003 confirmed the rule for the internal tables, and showed that a user
  table with an ever-increasing primary key meets the same mechanism:
  - A6 (fixed interleaving; reproduced, 20/20 pinned reps in the reproducer's own probe): two
    transactions that each read **their own** recently inserted order by primary key and then
    INSERT a new order both hold an SIRead lock on the same rightmost leaf. When both reads come
    before both inserts, one fails with `40001 ... read/write dependencies` (pivot); in the
    sequential order both commit. With uuid4 keys, or when the row read is old, the leaves differ
    and both commit.
  - C3 (32 worker processes, durable profile, 5 runs of 15 s, quiet-host gate; reproduced): 69 %
    of attempts failed (reproduction 65 %; its own probe without retries 74 %) and about 20 % of
    commands ended in `RetryExhausted` with uuid7 keys and recent reads; 0 % with uuid7 and old
    reads; about 0.1 % with uuid4 keys.
- **Scope of C3** - a worst case, not an application rate: every command read a row certain to be on
  the rightmost leaf (the order it inserted one command earlier), 32 workers inserted with no pause,
  the table had 100,000 rows and no foreign keys, and the pattern needs the same command to read the
  right edge **and** insert into the same index. A read conflicts only while its row is within about
  one leaf's worth of the newest inserts into that index; how fast that window closes as rows age
  was not measured.
- **Foreign keys reach the same edge without any read in the use case** (A7, fixed
  interleavings, added after the first version of this ADR; reproduced in round 3): a child
  INSERT's FK check (`SELECT 1 FROM ONLY <parent> x WHERE id = $1 FOR KEY SHARE OF x`, with the
  transaction snapshot) takes an SIRead lock on the parent's primary-key leaf - the rightmost one
  for a new or recent uuid7 parent. Three sessions that each insert a parent and its child, or
  two that each insert a child of their own just-committed parent and then a new parent, fail
  with a pivot 40001 at COMMIT in 10/10 pinned repetitions with uuid7 parents and 0/10 with uuid4
  parents (100,000 or 1,000,000 parents; the child's key generator does not matter); inserting
  both parents before both children commits with either. This holds while the planner reads the
  parent by an index scan: on a small or empty **analyzed** parent (up to about 400 single-column
  rows in the reproducer's probe) the check is a sequential scan with a relation-level lock, and
  every order fails with uuid4 parents too - the small-table case of spike 0003 item 4b, which no
  key generator fixes. Creating an aggregate root with owned children is the most common write,
  so the foreign-key case may matter more than C3's read-then-insert; its rate was not measured.
- The conflicting transactions in A6, A7 and C3 touch disjoint rows: the failures are false
  conflicts, retried (safe by design 8.3) and, under sustained concurrency, ending in
  `RetryExhausted` - a command failure the caller sees, caused by the key generator. (Spike
  0003's mixed workload D also showed SERIALIZABLE-only failures of a command that reads a
  user's latest orders and inserts one, but through the `(user_id, id)` index, partly as true
  conflicts and partly from page granularity; a uuid4 primary key would not change that, so D is
  not evidence here.)
- Not measured: uuid4 itself beyond C3/A6 (its ~0.1 % is at 100k rows, about 400 leaves; small
  tables with random keys share few leaves, and A5 adds relation locks from sequential scans);
  the insert-side cost of random keys on this stack (page splits, WAL after each checkpoint,
  cache misses once the index exceeds `shared_buffers`) - measured by the 9.5 item (#65); how common
  the pattern is in real use cases. REPEATABLE READ is not affected (it has no SSI).

## Decision
Proposed, for the maintainer to decide **after** the measurements of point 4 (#65):
1. **The default entity key becomes a random UUID (v4), still client-generated**: `pk()` means
   `pk(generated="uuid4")`; `generated="uuid7"` and `generated="identity"` stay available as
   explicit choices, documented as "ever-increasing: under SERIALIZABLE, commands that read
   recent rows of this table through the primary key and insert into it conflict with each other
   (7.3)". The argument is not correctness - both keys are correct, since a retry is safe - but
   the design's order of convenience over performance and "remove rather than detect": uuid7
   turns concurrency into failed commands, uuid4 costs insert speed. It removes the cause for
   the primary-key case only.
2. Run IDs stay uuid7: `run_claim` and `run_result` are never read inside SERIALIZABLE, so their
   right edge is harmless (spike 0003 item 1).
3. Indexes on other ever-increasing columns (timestamps, sequences; e.g. 4.2's
   `Index(user_id, created_at.desc())`) keep the right-edge pattern; 7.3 documents it, and the
   per-use-case retry metric makes it visible. This ADR cannot remove it.
4. **Before acceptance**, three durable-profile measurements (a 9.5 item, #65): uuid4 vs uuid7
   insert rate and WAL bytes per insert with the index at about 1x and 10x `shared_buffers`; the
   conflict window - C3 with the "recent" row aged by N inserts, as a curve; and a "create a parent
   and its children" load with a real foreign key (A7 under concurrency), uuid7 vs uuid4: 40001 per
   attempt and the `RetryExhausted` share of commands. A large uuid4 cost, or a window that closes
   within a few inserts, strengthens the alternative "keep uuid7 and document". The decision should
   come before `pk()` is implemented (#9, #12), while reversing it is cheap.

## Consequences
- Commands no longer conflict through the primary key's right edge by default (C3: 65-69 % ->
  about 0.1 % of attempts, in that worst case).
- **ADR-0002's ID source changes shape**: it must produce v4 or v7 depending on each entity's
  `generated=` (a kind parameter, or one source per kind). Its Decision 3 ("real IDs are version
  7") and Consequences ("uuid7 values are random too") are amended, with a History line; its
  fallback sequence still differs from real IDs by version.
- Random keys spread inserts over the index: more page splits and WAL, worse cache locality at
  scale - the cost point 4 measures.
- Time order is no longer in the key: "newest first" and keyset pagination need a `created_at`
  column (`(created_at, id)` for keyset); an `.order_by(Order.id)` written for recency silently
  loses its meaning.
- Coexistence and codegen: `platina pull` has to write out the existing key generator of a table
  explicitly; database-side defaults (`gen_random_uuid()`, PostgreSQL 18's `uuidv7()`) are the
  other ORM's choice and are not changed.
- Unaffected: event order (engine sequence numbers, `version`) and the outbox (identity key plus
  xid watermark).
- On acceptance: design 4.2 (the `pk` example and the "Client-generated IDs are the default"
  bullet), 7.3, 8.3 (the internal-table rationale notes that user tables share the mechanism),
  9.2's header, ADR-0002 and ADR-0003's example (EN + KO). The type surface does not change.

## Alternatives considered
- **Keep uuid7 as the default and document the cost** (7.3, the retry metric, guidance on which
  tables should declare `generated="uuid4"`): keeps insert locality and time order; the false
  conflicts are opt-out rather than opt-in. The right choice if point 4 shows a large uuid4 cost
  or a window that closes quickly - and the same pattern stays anyway in timestamp indexes.
- **No default** (`pk()` requires `generated=`): the most explicit option; every entity then
  carries a decision most users cannot make without this ADR, which is why it is not proposed,
  but it fits "configuration never changes meaning" best and is cheap to state.
- **A time-bucketed key** (a coarse prefix such as the minute, then random bits): keeps some
  locality and most of the spread; a custom format, measurable with point 4's setup.
- **Leave it to REPEATABLE READ**: gives up write-skew protection (spike 0003 D: REPEATABLE READ
  broke the pocket invariant in 2-4 of 30 runs).

## History
- 2026-11-26 - created (Proposed) from spike 0003.
- 2026-11-26 - revised after the architect review: D removed as evidence (its conflicts are on
  the `(user_id, id)` index); C3's worst-case scope stated; the argument restated as convenience
  over performance, not correctness; the change to ADR-0002 named; uuid4's unmeasured costs and
  two measurements before acceptance (a new 9.5 item) added; "no default" and a time-bucketed
  key added as alternatives; Related corrected (8.3, ADR-0003, #58).
- 2026-11-26 - renumbered from 0006 to 0007: develop gained ADR-0006 (exception fields) while this
  ADR was proposed on the spike branch; no content change.
- 2026-11-26 - after spike 0003's A7 and its reproduction (round 3): Context gains the foreign-key
  case (a child's FK check reads the parent's primary-key leaf; uuid7 parents 10/10 vs uuid4 0/10
  in two orders, while the parent is read by an index scan) and drops "no foreign keys, not
  measured" from C3's scope; Decision 4 gains a third measurement (the rate of the foreign-key
  case). The direction is unchanged.
