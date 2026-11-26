# ADR-0011: Row-set loads and the shape of dependent loads

- Status: Proposed
- Date: 2026-11-26
- Related: design sections 3.1, 4.3, 4.7, 4.13, 8.2 ("Dependent loads", "Partial loads of large
  aggregates", "Field type surface"), 8.3 ("2 round trips"), 9.6; issues #59 (decisions of
  2026-11-26), #10, #14, #27, #28, #51, #57, #64; spike 0007
  (`docs/spikes/0007-phase-1a-type-shapes.md`, ADR direction 2 and round 6); spike 0003 (SIRead
  locks); ADR-0004 (amended in place), ADR-0006 (message layout), ADR-0008 (run budget)

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- Design 4.7 / 8.2 let a `Load.after` function return "a ref or `None`". Spike 0002 found four
  use cases that could not declare what they read: unexpired holds of a seat (a predicate over
  `Now`), one redemption by (coupon, user), the stocks of an order's variants, and the seats near a
  seat. They loaded whole relations and filtered in Python.
- #59 (2026-11-26) decided:
  - nested paths written on the relation they continue, with the flat form a seal error;
  - a list of refs as a `Load.after` result;
  - `missing="none"` on `Load.when`;
  - constant predicates in partial loads;
  - that `Load.after(fn, ...)` takes the load arguments of `Load(...)`.

  It left row-set results to spike 0007 and this ADR. Later decisions: `Entity.where(pred, /,
  *preds)` needs a predicate, and a row-set load has no required `limit`. Combining predicates in
  `match` is #10 / #51's; the rows and order `lock="for_update"` locks are #64's.
- Spike 0007, rounds 1-5 (pyright and mypy, both strict): the three result forms type-check. With
  `Load.after(fn, *paths)`, however, a path of another entity passed unless the path type was an
  invariant `Path[O]`, because the entity is solved from two arguments (spike 0001 P-A). Even then
  mypy blamed the function, and a declared type that widens a relation's owner still got past mypy
  (W5).
- Spike 0007 round 6 probed the receiver form on the final stub: `Load.after(fn, missing=...) ->
  LoadAfter[E]`, with `LoadAfter[E].load(*paths: LoadPath[E])`. `type-reviewer` reproduced it
  independently (the write-up's "Type reproduction, round 6"); it agrees on what follows and found
  the last item.
  - Rejected by both checkers: every wrong-path line (F17, F21-F23), a column as a path, a
    skipped level, `missing=` where it does not apply, and W5.
  - Accepted by both: the three forms with load arguments and nested paths, also through a nullable
    many-to-one.
  - mypy now names the path, not the function.
  - The invariant `Path` is no longer needed for these lines. Without it, the owners of
    `Relation` / `RelColumn` are inferred covariant.
  - Found by the reproduction: the receiver fixes `E` only when nothing widens it. Both checkers
    accept another entity's path in two cases that round 5's invariant `Path` rejected (U6, U8):
    - a declared type on the result, `la: LoadAfter[Wallet | Order] = Load.after(point_wallet)`,
      then `la.load(Order.items)` (W6 / W7, also for the list form);
    - a function returning a union of entities, `-> Sequence[Wallet | Order]` (W8).

    The row-set form stays safe for any real body, because `RowSet` is invariant (a declared
    `-> RowSet[Wallet | Order]` still widens it). An invariant `Path` on `LoadAfter.load` alone
    closes these cases in pyright only. A union result with no path type-checks in round 5's form
    too (N1, N2), and under mypy a one-ref union joins `E` to `Entity`, so `.load` then takes a path
    of any entity (M6x; pyright rejects it).
- Spike 0002 X1 (unchanged in round 6): mypy checks nothing inside `Annotated[...]`.
- Spike 0003: a predicate read takes SIRead locks on what the plan scans, and a sequential scan
  takes a relation-level lock.

## Decision
1. **`Entity.where(pred, /, *preds)` is a `RowSet[E]`**, "the rows of E that match". It is used
   for a set change (`.set(...)`), for a set-level delete (`.delete()`, #57), and as a load (the
   result of a `Load.after` function). It is not a `Changes`, so a bare `where(...)` cannot stand
   for one (type error). This ADR owns `RowSet` as a load result; `.set` / `.delete()` on it are
   the #57 / #60 ADR's.
2. **A `Load.after` function returns a `RowSet[E]`, a `Sequence[E]` of refs, or one ref
   (`E | None`).**
   - `missing=` applies only to one ref (a type error on the other forms), and only to an optional
     parameter (seal).
   - A row set may be empty. A ref of a list with no row is `NotFound`, as for a required load.
3. **Load arguments go on the result: `Load.after(fn, missing=...).load(*paths)`.**
   - The receiver fixes `E`, as on `relation.load(...)` (spike 0007 S5), and `.load` takes the same
     covariant `LoadPath[E]`, which only relations derive from.
   - This **changes #59 point 3**, where the load arguments went into `Load.after(fn, ...)` itself.
   - It adds `relation.load(...)` and `Load.after(...).load(...)` to the receiver-fixed places of
     ADR-0004 Decision 4 (amended in place).
   - The invariant `Path` of spike 0007's condition 2 is not part of the surface.
   - **Seal rule**: a `Load.after` function's return annotation names one registered entity class
     `E` (as `E | None`, `Sequence[E]` or `RowSet[E]`; not a union of entities, not `Entity` or
     another base), and every load argument's owner is `E`. This catches what the types cannot: a
     result widened by a declared type or a union return (W6-W8, N1, N2, and M6x under mypy). R9
     reads the same annotation, so a `Load.after` function without one (a lambda) is a
     `SealError`: the typed function the design only recommended becomes required.
   - `Load.when` takes no load arguments.

   ```python
   def other_holds(seat: Seat, user_id: Id[User], now: Now) -> RowSet[SeatHold]:
       return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.user_id != user_id,
                             SeatHold.expires_at > now)

   holds_load = Load.after(other_holds)
   seats_load = Load.after(seats_near).load(Seat.tickets.load(Ticket.order), Seat.holds)
   ```
4. **Partial `.where` loads stay, with constant predicates. They are not replaced by row sets.**
   The rule is the maintainer's distinction between what is **known when the declaration is
   written** and what is not:
   - **Folds, no stage of its own** (into the stage of the row it continues, stage 1 under a
     parameter's own declaration): what is expressible as SQL over the declared rows' columns and
     constants known when the declaration is written. That is a nested path, a partial load
     (`.where`, `.count()`, `.exists()`) or `Load.when`.
   - **Adds one load stage**: what needs a value known only per run (a use case parameter that is
     not loaded, or `Now`), Python logic over loaded values, or a case `Load.when` does not allow
     (two parameters of the entity type, 4.7). That is a `Load.after` function.
   - **Neither: one row chosen by a key the caller has, when its absence is an error.** That is a
     ref parameter the caller passes to `bind` (`wallet=wallets.by_user(recipient_id)`,
     `Order.ref(id)`), loaded in stage 1; a missing row is `NotFound` (4.6). A ref has no
     `missing="none"`, so when absence is acceptable the row is a one-ref
     `Load.after(fn, missing="none")` over the key parameter, one stage more. This bullet takes
     precedence over the previous one.
   - **A `Load.after` always adds one stage**: it runs in the stage after the latest stage its
     arguments come from (stage 2 at the earliest), also when every argument of its function is
     an unloaded parameter or `Now` and it could in principle run before stage 1. Functions at
     the same depth share a stage, so the stage count is the depth of the load plan, a plain
     function of the declarations (10.3, 11.3). Folding such a function into stage 1 is an
     optimisation left to #14 / #28.
5. **Seal rejects a date or a date-time constant in any predicate written in a load declaration.**
   - **Where**: a partial `.where` at any depth (also under `relation.load(...)` and
     `Load.after(...).load(...)`). It also covers `Load.when`'s condition and `match`; that
     extension is this ADR's proposal, since the maintainer asked about partial `.where` only.
   - **Why**: it closes the hole of a module-level declaration such as
     `Order.items.where(Item.created_at > datetime.now() - timedelta(days=30))`, which calls the
     clock once, at import, so every run and retry uses that one value.
   - **Rejected operands**:
     - a value that is an instance of `datetime.date`, which covers `datetime` and its subclasses;
     - any value other than `None` compared with a column whose SQL type is `date`, `timestamp` or
       `timestamptz`, which catches another Python type mapped to one of them;
     - each element of `in_(...)` by the same test.

     Allowed: `timedelta` / `interval` (a duration, not a point in time) and `time` / `timetz` (a
     time of day such as opening hours is usually a schedule constant; a time of day taken from the
     clock is not caught).
   - **Cost**: a legitimate fixed date (`Item.created_at >= CUTOVER`, a migration cut-off) is
     rejected too. It becomes a row-set function, one load stage more: `Load.after(items_since)`
     returning `Item.where(Item.order_id == order.id, Item.created_at >= CUTOVER)`. A time from the
     clock takes `now: Now` as a parameter of the function.
   - **Message**: design 4.13, in ADR-0006's layout. The headline names the declaration (the
     partial load, or `Load.when`), the column and the value; `Fix:` points to a row-set function.
   - **What it needs**:
     - from #10's AST, a value operand as its own node that keeps the Python value (bind values
       are already separate, kept out of the cache key) and the column it is compared with;
     - the column's SQL type comes from the registry at seal;
     - the declaration's location is recorded when the load declaration is built (ADR-0006's frame
       helper, at declaration time only).
   - **Known limits**:
     - It detects one source of non-constant values, the clock. A value read from the environment
       or configuration, or chosen at random, at import is still a constant to seal, and so is a
       time encoded as a number (`Item.created_epoch > int(time.time())`).
     - Seal does not see inside a `Load.after` function, so a module-level
       `CUTOFF = datetime.now() - ...` read in a row-set function is just as frozen.
     - It is detection, not removal (see Consequences).
6. **Nested paths: one rule, two checks.** A path continues the relation it is written on.
   - Where a receiver fixes the owner (`relation.load(...)`, `LoadAfter.load(...)`), the following
     are type errors in both checkers, outside `Annotated[...]` (X1): a path of another entity, a
     skipped level, a flat path, and a column (G1, G2).
   - At the top of `Profile(...)` / `Load(...)`, the owner is the parameter's entity, which only
     seal knows. There the flat form (`Profile(Order.items, Item.allocations)`) is a `SealError`
     (spike 0007 R15).
7. **`in_([])` matches no row.** How `in_` compiles (one array parameter, so the statement text
   does not depend on the list's length) is #10's. #10 and #51 also decide two open questions:
   - `None` in the list (`= ANY` never matches NULL, and a negation would recreate the `NOT IN`
     trap);
   - whether an empty list of refs skips its statement.

## Consequences
- **Transactions.**
  - Load arguments and nested paths on a `Load.after` result add no stage. They go into the same
    pipeline as the row set: a child statement selects by the row set's predicate as a subquery
    (or by the refs' keys).
    - Under SERIALIZABLE every statement sees the transaction's one snapshot, so the repeated
      predicate selects the same rows.
    - The cost: the predicate is scanned again per child statement, with its SIRead locks.
    - The stage count stays fixed at seal (8.3: one more per `Load.after` stage).
  - Result order:
    - a row set is ordered by primary key, so the body sees one order on every attempt and in
      integration tests (a unit test passes rows in the order it writes them);
    - a list of refs keeps the function's order (duplicates: #14).
  - A `Load.after` function runs again on every attempt, from the snapshots of that attempt's
    earlier stages.
    - If it raises, the attempt ends like the body (ROLLBACK, the error propagates, no retry).
    - A 40001 / 40P01 in stage k restarts from `BEGIN` and the claim, and the function runs again
      with a fresh `Now`.
    - Each extra round trip spends the run budget (ADR-0008) and lies outside the commit shield.
  - A `now: Now` parameter of the function binds by name like every argument. The use case must
    therefore declare `now: Now = INJECTED` (a `SealError` otherwise), even if its body does not
    read it; both then see the attempt's single value.
  - Predicate reads take SIRead locks, and a sequential scan escalates to a relation lock (spike
    0003). Whether a row-set load reads less than a whole relation depends on the plan. "A smaller
    read set" is not an argument until #28 measures it.
- **The invariants this bends: "one way per operation" and "remove rather than detect".**
  - Five overlaps can load the same rows:
    - a constant partial load and a row-set function with the same predicate;
    - `Load.when` and a one-ref `Load.after`;
    - a `Load.after` returning refs of a foreign key, and a nested path through that key's
      many-to-one;
    - a one-ref `Load.after` without `missing="none"` over unloaded parameters only, and a ref
      parameter the caller binds (point 4);
    - `.load(a).load(b)` and `.load(a, b)` (and `.load()` and nothing). #14 rejects one spelling,
      by type or by seal.
  - A function body is opaque to seal, so the first four are kept apart by point 4's documented
    rule, not by structure.
  - No removal is known:
    - row sets in place of partial loads would not remove the clock hole (see Alternatives);
    - the only type-level check was not probed (see Alternatives).

    Point 5 is therefore a detection of the most likely mistake. The design states the rule next to
    each form (4.7, 8.2).
- **What stays a seal check** (types cannot see it):
  - the parameter's declared type against the function's result (R9; `Annotated[T, x]` relates
    nothing);
  - `missing="none"` on a parameter that is not optional (R16);
  - the flat path under `Profile` / `Load` (R15);
  - one registered entity per `Load.after` function, read from its return annotation
    (required), and the owner of every load argument (W6-W8, N1, N2, M6x; point 3);
  - point 5;
  - a `Load.after` argument name with no use case parameter.
- **Tests.**
  - A row-set predicate never runs in a unit test, which passes the loaded rows by hand
    (`hold_seat(..., holds=[...])`, 4.12), so a wrong predicate is caught only by an integration
    test.
  - The test kit (#27) can make it visible (a SQL snapshot of the function's row set), but cannot
    make it run.
- **Load declarations are named values.** Inline in `Annotated[...]` they are checked by pyright
  only (X1; 4.7).
- **Type surface**, pinned by type tests under both checkers when #14 writes it:
  - `LoadAfter[E]` is new, and its parameter is invariant.
  - `Relation[O, E]` / `RelColumn[O, T]`: the owner is covariant (like `Column`'s, now that no
    invariant `Path` base needs it) and the second parameter invariant. Each is declared, not
    inferred, for the reason ADR-0004 Decision 3 gives for `Column` (ADR-0004 itself is not
    amended for variance).
  - `OwnedRelation` stays invariant in its owner through `AddOp` / `RelOp` (F11).
  - mypy still names a path's instance type (`Sequence[Item]`), the descriptor effect ADR-0004
    records.
  - `.count()` / `.exists()` return an expression, not a load path, so a nested partial count
    or existence check cannot be written: `Order.items.load(Item.allocations.count())` and
    `Load.after(fn).load(Seat.holds.exists())` are type errors. Only the top of a `Profile` /
    `Load` takes them (not `Load.after(...).load(...)`, G10). Whether that is the intended limit or `.count()` / `.exists()` become
    load paths is a scope item for #14.
- **Expressiveness gained** (spike 0007, use-case table):
  - use case 3 declares exactly the redemption it reads;
  - use case 5 declares its seat's holds and tickets and the seats near it (their holds and
    tickets stay whole relations: a `now` in a nested path needs one more `Load.after` stage);
  - use case 4 declares its variants' stocks (all of them, filtered in Python).

## Alternatives considered
- **Row sets replace partial `.where` loads** (keeping `.count()` / `.exists()`): this removes one
  overlap, but not the clock hole, since a function reading a module-level
  `CUTOFF = datetime.now() - ...` is as frozen as a partial load and seal cannot see inside it.
  Every constant filter would cost a round trip (8.3's "1 load batch + 1 commit batch"). Rejected:
  no correctness gain to pay for.
- **`Load.after(fn, *paths: Path[E])` with an invariant `Path`** (spike 0007 round 5): both
  checkers reject the same wrong paths, and point 3's seal rule is needed in this form too: a
  union return without a path type-checks (N1, N2 on the round-5 stub), and a relation whose
  owner is widened by a declared type gets past mypy (W5). The forms differ only in which
  widening the types catch before seal: this form rejects a wider type written on the result
  (W6 / W7) and every union result with a path (M1x-M8x) in both checkers; the receiver form
  rejects W5 in both. Not chosen:
  - it needs a second relation base class only for this call;
  - mypy blames the function instead of the path.
- **A type-level time check** (comparison overloads on time-typed columns returning a predicate
  type that declarations reject): not probed.
  - It needs self-typed overloads per time type on six operators and `in_`, where spike 0006 found
    the checkers' agreement fragile.
  - It cannot see a non-time Python type mapped to a time SQL type.
  - Every receiver that takes a predicate would need a second predicate type.

  Revisit it if the seal check proves noisy.
- **A clock placeholder in declarations** (`Item.expires_at > NOW`, bound per attempt), or
  `server_now()` in a predicate: either folds into the stage with a fresh time. Rejected: it is a
  second way to read the clock next to the `Now` parameter, and the SQL clock is one `freeze_now`
  cannot pin (4.12). Whether `server_now()` is accepted in a predicate at all is #10's.
- **A required `limit` on a row-set load**: rejected by the maintainer (2026-11-26).

## History
- 2026-11-26 - created (Proposed) from #59's decisions, spike 0007's ADR direction 2 and round 6;
  revised after the architect review (verdict: agree with changes, one BLOCKER and seven MAJOR,
  all applied: the rule of point 4 made decisive, the time check's scope,
  the `None` exception, `time` dropped, both bent invariants named, transaction consequences).
- 2026-11-26 - after the round-6 type reproduction: the widening of `E` by a declared type or a
  union result (W6-W8) is recorded, a seal rule (one entity per function, every path owned by it)
  is added, and the invariant-`Path` alternative is weighed against it.
- 2026-11-26 - renumbered from 0010 (`0010-writes-beyond-set.md` takes it). Maintainer
  direction: the receiver form stays and W6-W8 are a seal rule; the time check covers
  `Load.when` and leaves out `time` / `timetz`; a `Load.after` always adds one stage. Probed
  N1 / N2 (a union result without a path passes both stubs), so the invariant-`Path` comparison
  is narrowed to W6 / W7 (once the seal rule exists; the reproduction's addendum, incl. M6x).
  After the architect's second review, narrowed to these changes (verdict: agree with changes,
  three MAJOR and three MINOR, all applied): the stage count is the depth of the load plan (independent
  functions share a stage); the ref-parameter rule applies when absence is an error; the seal rule
  reads a required return annotation (a lambda is a `SealError`). Point 4 separates a ref parameter bound by the caller from a
  `Load.after`; the nested `.count()` / `.exists()` limit is stated.
