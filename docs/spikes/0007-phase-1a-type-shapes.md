# Spike 0007: Phase 1a type shapes for #48, #57, #59 and #60

- Design section: 9.6 ("a separate type spike for the shapes of #48, #57, #59 and #60"); shapes
  of 4.4, 4.5, 4.7, 4.8 and 8.2; the use cases of 9.4 (spike 0002)
- Issue: #79 (decisions: #48, #57, #59, #60, 2026-11-26)
- Date: 2026-11-26
- Code: `spikes/0007-phase-1a-type-shapes/` (throwaway; raw output in `results/`, git-ignored)

## Question

The maintainer decided #48 and took the recommendations of #57, #59 and #60 as hypotheses
(decision comments of 2026-11-26). Before the design text changes, the shapes must hold under
**both** pyright (strict) and mypy (strict), and the use cases of spike 0002 that needed them must
read better in them. For each shape: what both checkers must accept, what both must reject, and
what neither can reject (and therefore needs the runtime or seal rule of the decision).

| # | Shape (decision) | Confirmed when | Refuted when |
|---|---|---|---|
| S1 | `Entity.delete() -> Changes`; `.delete()` on a ref (#57) | both accept `order.delete()` as `Changes` | either rejects it or infers another type |
| S2 | `Entity.where(...) -> RowSet[Self]` with `.set`, `.delete`, and as a load result; a bare `where(...)` where `Changes` is expected is rejected (#57, #59) | both accept the three uses and reject the bare row set | a row set passes as `Changes` in either checker |
| S3 | `insert(entity) -> Changes`; owned children of a new root as candidate A `insert(t) + t.set(Transfer.legs.add(...))` or candidate B `insert(t, Transfer.legs.add(...))` (#60 points 1, 3) | both accept `insert` and both candidates; the misuse each candidate is meant to exclude is rejected by both | either checker accepts the misuse |
| S4 | Relation operations only on `owned` relations, by a separate relation type (#60 point 4) | both reject `add` / `remove` / `update` on a relation that is not owned, and a declaration whose annotation and `owned=` disagree | either accepts one of them |
| S5 | Nested paths `relation.load(...)`; a wrong owner and a skipped level are rejected (#59 point 1) | both accept three levels and reject both misuses | either accepts a misuse |
| S6 | `Load.after` returning a `RowSet`, a list of refs or one ref; load arguments of `Load.after(fn, ...)` are paths of the returned entity (#59 points 2, 3) | both accept the three forms with load arguments and reject a path of another entity | either accepts it |
| S7 | `missing="none"` on `Load.when` (#59 point 3) | both accept it | either rejects it |
| S8 | `= INJECTED` on dependent-load parameters; `bind` leaves them out (#48) | both accept the declaration and the `bind` call; the parameter's type inside is the annotated one | either rejects the `bind` call |

Spike 0002's use cases 3, 4, 5 and 7 (loads), 6 (delete) and 8 (insert) are rewritten in these
shapes (1, 2, 9 and 10 are ported, because the new stub rejects their writes). Each is judged by spike 0002's scale (expressed / expressed, awkward / not expressible)
against the same requirements (R3.x-R8.x of spike 0002), and every workaround spike 0002 recorded
for it is checked: removed or still there.

Two decided shapes are **used as given, not probed**: #49's `parent_fk` (the parent key of an
owned child is not a constructor parameter) and #51's comparison overloads (column-to-column
predicates). Since round 4 they are copied from the final stub of
[spike 0006](0006-parent-fk-and-column-operands.md) (`spikes/0006-parent-fk-and-column-operands/lib.pyi`),
which pins them; rounds 1-3 had #51's overloads on `__eq__` only, from its decision comment.

## Setup
- Python 3.14.7, pyright 1.1.414, mypy 2.4.1 (compiled) - `results/versions.txt`. No database.
- Branch `docs/spike-0007-phase-1a-type-shapes`, cut from `develop` at `567684f` and rebased in
  round 4 onto `2876e1b` (spike 0006 merged). pyright and mypy
  are configured by `pyproject.toml` (pyright `strict` covers `spikes/`; mypy `--strict`); the
  commands must run inside the repository.
- `lib.pyi` is a copy of spike 0002's stub (sha256 `ad6ea7fec42121cd...`); `domain.py` of spike
  0002's domain (`caf83036e63451df...`). Every changed declaration carries `# [0007]` (one the
  formatter wraps carries it on its first and last line). Round 4 (after two rounds of architect
  review, three of reproduction and an independent review session, see Review) is the state
  described here:
  - `Column`'s six comparison operators: spike 0006's final overloads for #51 (copied, not
    re-probed); and `Column.in_(values)`.
  - `Path[O]`: a base class **invariant** in its owner; `Relation[O, E]` and `RelColumn[O, T]`
    derive from `OwnedExpr[O]` and `Path[O]`. The load arguments of the three `Load.after`
    overloads are typed `Path[E]`.
  - `LoadPath[O]`: a **covariant** base that only `Relation` and `RelColumn` derive from; it types
    `Relation.load` and `RelColumn.load`, where the receiver fixes the owner. History: typed
    `Path[E]` (round 2), pyright rejected a nested load through a nullable many-to-one
    (`Order.show.load(Show.seats)`, `T = Show | None`), and mypy did too once the path was
    chained; typed `OwnedExpr[E]` (round 3), a plain column passed as a path
    (`Order.items.load(Item.quantity)`, found by the independent review, round 4).
  - `Relation[O, E]` (not owned) is read and load only: `count` / `exists` / `where` / `load`.
    `OwnedRelation[O, E]`, its subclass, adds `add -> AddOp[O]`, `remove -> RelOp[O]` and
    `update(item, *ops: Op[E] | RelOp[E]) -> RelOp[O]`; its inherited `where` / `load` return the
    read-only `Relation[O, E]`.
  - `RelOp[O]`: a relation operation, **invariant** in its owner and **not** an `Op`; `AddOp[O]`,
    its subclass, is the only kind `insert` takes. `Entity.set(*ops: Op[Self] | RelOp[Self])`;
    `RowSet.set(*ops: Op[E])` takes column operations only.
  - A descriptor `Owned[T]` (class access `OwnedRelation[O, E]`, instance access `Sequence[E]`);
    `owns_many(...) -> Owned[T]` declares it (chosen by the maintainer, round 5), next to
    `one_to_many(...) -> Rel[T]`. The rejected alternative, two `one_to_many` overloads on
    `owned: Literal[True]` -> `Owned[T]` / `owned: Literal[False] = ...` -> `Rel[T]`, stays in the
    stub, marked, only for its probes (F8, F9, `probe_owned_flag.py`).
  - `parent_fk` (#49) as a field specifier.
  - `RowSet[E]`, declared **invariant**, with `set(*ops) -> SetChange[E]` and `delete() ->
    Changes`; `Entity.where(pred, /, *preds) -> RowSet[Self]` (was `SetChange[Self]`; one
    predicate required since round 5); `Entity.delete() ->
    Changes`; `insert[E: Entity](entity: E, /, *children: AddOp[E]) -> Changes` (candidate A uses
    no `children`, candidate B - chosen - uses them). Spike 0002's placeholders `UNDECIDED_insert` /
    `UNDECIDED_delete` are gone.
  - `Load.when(..., missing=)`; `Load.after` as three overloads: `fn` returning `RowSet[E]`,
    `Sequence[E]` (round 4; was `list[E]`) or `E | None`, each with `*paths: Path[E]`, `missing=`
    only on the last.
  - Domain: the four owned relations are annotated `Owned[list[...]]` and declared with
    `owns_many(...)` (round 5; before, `one_to_many(..., owned=True)`), and their children's
    foreign keys are `parent_fk(...)`; three stale comments updated. Final hashes: `lib.pyi`
    `9c0de329717a2ac2...`, `domain.py` `05862bf0dad939ae...`.

## Method
1. This Question was written before the probes ran.
2. Files (all under `spikes/0007-phase-1a-type-shapes/`):
   - `pass_shapes.py` - lines both checkers must accept, with `assert_type` on what they infer.
   - `fail_shapes.py` - lines both must reject, each marked `# expect-error[<pyright rule>, <mypy
     code>]` with the codes observed (F1-F20 in round 1, F21-F29 in round 2, F30-F31 in round 4,
     F32-F34 in round 5).
   - `probe_runtime_only.py` - misuse the decisions reject at seal or at run time; both checkers
     must accept every line (R1-R18; R8 of round 1 became F27).
   - `probe_annotated.py` - four misuse lines written inside `Annotated[...]` metadata, run per
     checker (they disagree by design, spike 0002 X1).
   - `probe_owned_flag.py`, `probe_owner_widen.py` (round 4; the first extended in round 5) - run
     per checker: `owned=` given a constant (call- and literal-initialised), and a declared type
     that widens a relation's owner.
   - The use cases: `uc03_coupon_checkout.py`, `uc04_stock_allocation.py`, `uc05_seat_hold.py`,
     `uc06_order_merge.py`, `uc07_expire_orders.py`, `uc08_transfer_a.py`, `uc08_transfer_b.py`
     (the rewrites), and `uc01_payment.py`, `uc02_refund.py`, `uc09_profile_edit.py`,
     `uc10_payment_approval.py` (spike 0002's files with only the statements marked `# [0007]`
     changed, because the new stub rejects their writes through relations that are not owned and
     the hand-passed parent keys; use case 10's port is not mechanical, see its row). Unit tests are
     type-checked, never run.
3. Everything runs from the repository root with one script:

   ```bash
   bash spikes/0007-phase-1a-type-shapes/run.sh
   # typetests: 0 problem(s) in 16 file(s)
   # variant relop covariant - error lines lost (main - variant):
   # mypy fail_shapes.py 112
   # pyright fail_shapes.py 112
   # error lines gained (variant - main):
   # variant path covariant - error lines lost (main - variant):
   # mypy fail_shapes.py 127
   # mypy fail_shapes.py 134
   # mypy fail_shapes.py 135
   # pyright fail_shapes.py 127
   # pyright fail_shapes.py 134
   # pyright fail_shapes.py 135
   # error lines gained (variant - main):
   ```

   It runs `uv run python -m tools.typetests` over the stub, the domain, the three probe files and
   the eleven use-case files; then `probe_annotated.py`, `probe_owned_flag.py` and
   `probe_owner_widen.py` under each checker (`results/<probe>-{pyright,mypy}.txt`; a checker exit
   other than 0 or 1 - a missing file - fails the script); then two variants. Each makes one TypeVar
   covariant (`_O_inv` of `RelOp`, `_P_inv` of `Path`) and changes nothing else. The script fails
   if a variant stub has diagnostics of its own (mypy through `fail_shapes.py`, pyright on the
   stub itself), and prints which error lines of `fail_shapes.py` differ from the main run
   (`results/variant-*.txt`). Line 112 is F11; lines 127, 134 and 135 are F17, F21 and F22.

## Observations

### The shapes (`pass_shapes.py`, `fail_shapes.py`)
Both checkers accepted every line of `pass_shapes.py` with the pinned inference, and rejected
every line of `fail_shapes.py` with the codes below. These are the lines the spike wrote; where the
checkers differ on other lines, the sections below say so.

| Shape | Line | pyright | mypy |
|---|---|---|---|
| S1 | `order.delete()` | `Changes` | `Changes` |
| S2 | `Order.where(...)` | `RowSet[Order]` | `RowSet[Order]` |
| S2 | `Order.where(...).delete()` | `Changes` | `Changes` |
| S2 | `Order.where(...).set(...).emit_each(OrderExpired, order_id=Order.id)` (4.3) | `SetChange[Order]` | `SetChange[Order]` |
| S2 | F1 `return Order.where(...)` in a function returning `Changes` | rejected (`reportReturnType`) | rejected (`return-value`) |
| S2 | F2 `Order.where(...) + order.delete()` | rejected (`reportOperatorIssue`) | rejected (`operator`) |
| S2 | F3 `Order.where(...).set(Wallet.balance.to(m))` | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| S2 | F4 `SeatHold.where(Seat.id == seat.id)` | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| S2 | F27 `Order.where(...).set(Order.items.remove(item))` (a relation operation in a set change) | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| S3 | `insert(SeatHold(...))` | `Changes` | `Changes` |
| S3 | A: `insert(t) + t.set(Transfer.legs.add(leg))` (`t` new) | accepted | accepted |
| S3 | B: `insert(t, Transfer.legs.add(leg))` | `Changes` | `Changes` |
| S3 | F10 B with a column operation, `insert(t, Transfer.amount.to(m))` | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| S3 | F11 B with another entity's `add`, `insert(t, Order.items.add(item))` | rejected (`reportArgumentType`) | rejected (`misc`: cannot infer `E`) |
| S3 | F11 with `RelOp`'s owner covariant (variant `relop`) | **accepted** | **accepted** |
| S3 | F24 B with `remove`, `insert(t, Transfer.legs.remove(leg))` | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| S4 | `Order.items` / `Order.payments` | `OwnedRelation[Order, Item]` / `Relation[Order, Payment]` | the same |
| S4 | `Order.items.add(item)` / `Order.items.remove(item)` | `AddOp[Order]` / `RelOp[Order]` | the same |
| S4 | F5-F7 `add` / `remove` / `update` on `Order.payments`, `Item.allocations`, `Variant.stocks` | rejected (`reportAttributeAccessIssue`) | rejected (`attr-defined`) |
| S4 | F25 / F26 a write through `Order.items.where(...)` / `Order.items.load(...)` | rejected (`reportAttributeAccessIssue`) | rejected (`attr-defined`) |
| S4 | F8 `items: Rel[list[Item]] = one_to_many(..., owned=True)` | rejected (`reportAssignmentType`) | rejected (`assignment`) |
| S4 | F9 `items: Owned[list[Item]] = one_to_many(...)` (no `owned=True`) | rejected (`reportAssignmentType`) | rejected (`assignment`) |
| S4 alt | `items: Owned[list[Item]] = owns_many(...)` / F28 `items: Rel[list[Item]] = owns_many(...)` | `OwnedRelation[S4bOrder, Item]` / rejected (`reportAssignmentType`) | the same / rejected (`assignment`) |
| S1 | F29 a field named `delete` | rejected (`reportIncompatibleMethodOverride`) | rejected (`assignment`) |
| S2 | F32-F34 `Order.where()`, `Order.where().delete()`, `Order.where().set(...)` - no predicate (round 5: `where(pred, /, *preds)`) | rejected (`reportCallIssue`) | rejected (`call-arg`: too few arguments) |
| S2 | `Order.where(*preds)`, `preds: list[Pred[Order]]` (R17) | accepted | accepted |
| - | F12 `Leg(transfer_id=t.id, ...)` (#49 as given) | rejected (`reportCallIssue`) | rejected (`call-arg`) |
| S5 | `Order.items.load(Item.allocations.load(Allocation.stock))` | `Relation[Order, Item]` | the same |
| S5 | `Seat.tickets.load(Ticket.order)` / `Ticket.order.load(Order.items)` | `Relation[Seat, Ticket]` / `RelColumn[Ticket, Order]` | the same |
| S5 | `Order.show.load(Show.seats)` / `Order.user.load(User.addresses)` (nullable many-to-one) | `RelColumn[Order, Show \| None]` / `RelColumn[Order, User \| None]` | the same |
| S5 | the same two lines with `load(*paths: Path[T])` (round 2's stub) | **rejected** (`reportArgumentType`) | accepted |
| S5 | F30 / F31 a column as a load path, `Order.items.load(Item.quantity)` / `Stock.warehouse.load(Warehouse.group)` | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| S5 | F30 / F31 with round 3's `load(*paths: OwnedExpr[E])` (a column is an `OwnedExpr`) | **accepted** | **accepted** |
| S5 | F13 `Order.items.load(Order.payments)` (wrong owner) | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| S5 | F14 `Order.items.load(Allocation.stock)` (skipped level) | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| S5 | F15 wrong owner one level deeper; F16 inside `Profile(...)` | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| S6 | `Load.after(active_holds)` (row set), `Load.after(variants_of, Variant.stocks.load(Stock.warehouse))` (list of refs), `Load.after(point_wallet, missing="none")` (one ref), `Load.after(stocks_of, Stock.warehouse)` | accepted | accepted |
| S6 | F17 / F21 / F23 a path that is not of the returned entity - list / one-ref / row-set form | rejected (`reportArgumentType`, `reportCallIssue`) | rejected (`arg-type` / `arg-type` / `misc`) |
| S6 | F22 the one-ref form with a wrong path and `missing="none"` | rejected (`reportArgumentType`) | rejected (`call-overload`) |
| S6 | F17, F21, F22 with `Path`'s owner covariant (variant `path`) | **accepted** | **accepted** |
| S6 | `Load.after(variants_tuple, Variant.stocks)`, a function returning `tuple[Variant, ...]` (the list form takes any `Sequence[E]`, round 4) | accepted | accepted |
| - | `Stock.allocated <= Stock.quantity` (#51, spike 0006's overloads) | `Pred[Stock]` | `Pred[Stock]` |
| S6 | F18 `Load.after(active_holds, missing="none")` (`missing` on a row set) | rejected (`reportArgumentType`) | rejected (`call-overload`) |
| S6 | `Stock.variant_id.in_([...])` / F19 with `Decimal` values | `Pred[Stock]` / rejected (`reportArgumentType`) | `Pred[Stock]` / rejected (`list-item`) |
| S7 | `Load.when(..., match=Wallet.user_id == Order.user_id, missing="none")` / F20 `missing="skip"` | accepted / rejected (`reportArgumentType`) | accepted / rejected (`arg-type`) |
| S8 | inside `hold(..., holds: ActiveHolds = INJECTED, now: Now = INJECTED)`: `holds`, `now` | `Sequence[SeatHold]`, `datetime` | the same |
| S8 | `hold.bind(seat=..., user_id=...)`; 4.7's `refund.bind(order=...)` with `wallet: PointWallet = INJECTED` | accepted | accepted |

Additional pyright-only rules reported on the rejected lines (strict mode's unknown-type rules,
listed in the markers): `reportUnknownVariableType`, `reportUnknownMemberType`,
`reportUnknownArgumentType`. mypy also reports `no-any-return` on F2. On F13-F16 mypy's message
names the wrong argument's *instance* type (`"Sequence[Payment]"`, `"Stock"`, `"Warehouse"`),
pyright names the relation (`Relation[Order, Payment]`) - mypy reads a class attribute through
the descriptor's instance overload in the error message (ADR-0004, Consequences); the verdict and
the code are the same. On F17 and F21 mypy blames the function, not the path (`expected
"Callable[[Order], RowSet[Order]]"`: it solves `E` from the path first) - the same verdict with a
misleading reason.

**Two owners solved from several arguments (spike 0001 P-A).** Both `insert` and `Load.after`
solve their entity type from more than one argument: `insert` from the entity and its children,
`Load.after` from the function's result and the paths.
- **With a covariant owner, both checkers accepted misuse silently, without any error.**
  - `insert(t, Order.items.add(item))` for a new `Transfer`.
  - `Load.after(point_wallet, Order.items)` for a function returning `Wallet | None`, also with
    `missing="none"`.
  - In each case pyright widens the entity type to a union and mypy joins it to `Entity`.
- **The list and row-set forms were rejected for incidental reasons** in round 1: `list` is
  invariant, and `RowSet`'s inferred variance came out contravariant. That is why round 1 missed
  the one-ref form (found by both the review and the reproduction). Since round 4 the list form
  takes `Sequence[E]`, which is covariant, so F17 too rests on the invariant `Path` (the `path`
  variant now loses F17, F21 and F22).
- **Declaring the owner invariant** makes the given entity the only solution, and both checkers
  reject the misuse. The variants isolate each cause: making only `RelOp`'s owner covariant loses
  exactly F11, and making only `Path`'s owner covariant loses exactly F21 and F22.
- **Where the receiver fixes the owner, invariance is not needed and costs a false rejection.**
  `Relation.load` / `RelColumn.load` reject a wrong path with a covariant type (F13-F16 stay
  rejected in the `path` variant), and an invariant `Path` there made pyright reject a nested load
  through a nullable many-to-one - mypy only once the path was chained (round 3; found by the
  architect's second review, the chained case by the round-3 reproduction). So `Path[E]` types
  `Load.after`'s arguments only, and `relation.load` takes the covariant `LoadPath[E]`, which
  columns do not derive from (round 3's `OwnedExpr[E]` let a column through, F30 / F31).
- **Nothing that should type-check is lost.** `Entity.set`, every use case and every
  `pass_shapes.py` line, including the two nullable nested loads, type-check with the invariant
  `Path` (on `Load.after`), `RelOp` and `RowSet`.
- **A declared type can still widen an owner under mypy** (`probe_owner_widen.py`, round 4;
  observed by the independent review, cause and scope from the round-4 reproduction, rerun here).
  - When the annotation sits directly on the class access, `rel: OwnedRelation[Transfer | Order,
    Item] = Order.items` (W1), mypy solves the descriptor's owner from the declared type and
    accepts it; then `insert(t, rel.add(item))` passes with a plain `t: Transfer` (W2) - F11
    reached through one annotation.
  - The same works for any relation and reaches condition 2 too: `wide: Relation[Wallet | Order,
    Item] = Order.items`, then `Load.after(point_wallet, wide)` (W4, W5) - F21 under mypy.
  - Through a variable (`x = Order.items`, then the annotated assignment, W3) mypy rejects the
    widening (`assignment`). pyright rejects W1, W3 and W4 (`reportAssignmentType`).
  - Declaring the relation types invariant does not change it (the reproduction's
    `variant_ownedrel_inv/`): it is how mypy infers a descriptor's class access under an expected
    type, not variance. A known gap for ADR-0004's amendment, not closed here.
- **`owned=` given a constant instead of a literal** (`probe_owned_flag.py`; the rejected
  `owned=` alternative). Two cases, both observed:
  - A constant initialised from a literal (`ANNOTATED: bool = True`, `BARE = True`; G3, G4 - the
    independent review's case, added in round 5): pyright narrows it to the literal and accepts
    the declaration (no error); mypy rejects the call (`call-overload`). **The checkers split.**
  - A constant initialised from a call (`FLAG: bool = flag()`; G0-G2, round 4): both reject in
    strict mode, for different reasons - pyright evaluates the call to the union of both
    overloads' results (`Owned[list[Item]] | Rel[Unknown]`) and rejects the declaration
    (`reportAssignmentType`), or with no declared type only reports the unknown part
    (`reportUnknownVariableType`); mypy rejects the call (`call-overload`).
  Round 4 recorded only the second case and called the review's report different; it tested a
  different input. Both observations hold.
- **An alternative fix, from the reproducer**: `Load.after(fn, missing=...) -> LoadAfter[E]` with
  the paths attached by `.load(*paths)`, so the receiver fixes `E`. Both checkers then also reject
  these lines (Reproduction, `variant_after_receiver/`).

### What neither checker rejects (`probe_runtime_only.py`)
Both checkers accept every line; the decision names the check that catches it instead.

| # | Line | Caught by |
|---|---|---|
| R1 | `Order.ref(id).delete()` | run time, `UnloadedReference` (#57; a ref is an entity at the type level, like `.set` on a ref) |
| R2 | `hold.bind(..., holds=[], now=NOW)` (runner-filled parameters passed) | `bind`, `UsageError` (#48) |
| R3 | `hold(seat, user_id)` (direct call without the runner-filled parameters) | the `@usecase` wrapper, `UsageError` (#48) |
| R4 | `note: str = INJECTED` on a plain parameter | seal, `SealError` (#48) |
| R5 | `insert(t) + t.set(Transfer.amount.to(m))` (a column operation on a new entity) | A: "`.set` on a new entity takes relation operations only"; B: R13's rule. Inside `insert`, B rejects it by type (F10) |
| R6 | `Transfer(amount=m)` never inserted | end of the step, `UsageError` (#60) |
| R7 | `insert(order)` of a loaded snapshot | run time (#60; a loaded snapshot and a new entity have one type) |
| R9 | `holds: Annotated[list[Item], Load.after(active_holds)]` (declared type and the function's result differ) | seal (spike 0002 X13 item 1, unchanged) |
| R10 | `item.delete()` on an owned child | not decided: a second way next to `Order.items.remove(item)` |
| R11 | `item.set(Item.quantity.to(1))` on an owned child, not through its root | not decided: skips the root's version bump |
| R12 | `insert(Leg(...))`, an owned child inserted directly | not decided: the child has no parent key (#49) |
| R13 | candidate B: `insert(t) + t.set(Transfer.legs.add(...))` (`.set` on a new entity) | B's runtime rule: `.set` on a new entity is an error |
| R14 | `insert_all([t, Leg(...)])` (a root and an owned child through the bulk path) | not decided (#33) |
| R15 | `Profile(Order.items, Item.allocations)` (the flat path) | seal (#59 point 1) |
| R16 | `missing="none"` where the result is not optional: `Load.after` of a function returning `Wallet`, and `Load.when(..., missing="none")` for a parameter declared `Wallet` (round 4, observed by the independent review, rerun) | seal (#59) |
| R17 | `Order.where(*preds)` with `preds: list[Pred[Order]]` - an unpacked list that may be empty at run time (round 5) | run time: "at least one predicate" (the maintainer's decision) is a type error only for a literal call (F32-F34) |
| R18 | the owned declaration, the child's `parent_fk` and `aggregate_root=True` disagree: a plain `fk` under an `Owned` relation, a `parent_fk` under no owned relation, owned children on a class that is not an aggregate root (round 4) | seal - spike 0006's open item "how `owned=True` and `parent_fk` are kept consistent" (#9) |

Under both candidates `t.set(...)` on a new entity type-checks (a new entity and a loaded snapshot
have one type): A needs "`.set` on a new entity takes relation operations only" (R5), B needs
"`.set` on a new entity is an error" (R13). R10-R12 are the same gap seen from the child: an owned
child is an entity like any other at the type level, so nothing stops writing it directly; a
type-level marker for owned children (a base without `set` / `delete`) was not probed.

### Inside `Annotated[...]` (`probe_annotated.py`)
pyright reported all four misuse lines (5 errors: F13 in a `type` alias and in a parameter
annotation, F17, F18); mypy reported `Success: no issues found`. Spike 0002's X1 holds for every
new shape: a load declaration written inline in `Annotated[...]` is checked by pyright only, so
the rewrites declare every load as a named value (`holds_load = Load.after(...)`,
`releasable = Profile(...)`) and use the name in the annotation.

### The use cases, rewritten
X9 (a count lives only in the scheduler) and X10 (an empty `Changes()`, not shown in the design)
are spike 0002's numbering.

| # | Spike 0002 verdict | Now | Workarounds of spike 0002, and what is still there |
|---|---|---|---|
| 1 payment | not expressible (R1.2) | expressed - R1.2 rests on #58's decision (`IdempotencyKeyReuse`, a runtime rule), not on a probe | ported only: `insert(payment)` replaces `Order.payments.add(payment)` |
| 2 refund | expressed, awkward | carried over (ported only, not re-judged) | `insert(Refund(...))` replaces three `Order.refunds.add(...)`; the `Op` list becomes `list[Op[Order] \| RelOp[Order]]`. Both reasons for spike 0002's verdict are decided since (#51: its 4.7 `Load.when` form now type-checks, S7; #48: X5) |
| 3 coupon then payment | expressed, awkward | **expressed** | gone: R3.3 reads the one redemption by (coupon, user) as a row set (empty = never redeemed) instead of the user's whole `redemptions` relation; the redemption is `insert(...)`, not `Coupon.redemptions.add`. R3.5 is use case 1's `pay`, imported as spike 0002 did (round 1 had an abridged copy - reproduction discrepancy 2). No empty `Changes()` |
| 4 stock reservation | expressed, awkward | expressed, **less** awkward; `lock=` not expressible | gone: the caller's pre-read of the variants and its stale-list check - `Load.after(variants_of, Variant.stocks.load(Stock.warehouse))` declares them; allocation rows are `insert(...)`. Still there: all stocks of each variant are loaded and filtered by warehouse group in Python (a predicate over a relation of the row, as in use case 5); a new empty `Changes()` start (X10). Not expressible: a lock on `Load.after` rows (no `lock=` argument; #64) |
| 5 seat reservation | expressed, awkward | expressed, **less** awkward | gone: R5.2's two reads are row sets over the stated predicates (unexpired holds of others, using `now`; active tickets with their order), R5.3 reads the seats in a box around the seat instead of the whole show; the hold is `insert(...)`. Still there: the near seats' holds and tickets are whole relations, filtered in Python (holds need `now`, which a partial load cannot name; the tickets could be a constant partial load); "the ticket's order is PENDING or PAID" is a predicate over a relation of the row, which a row set does not state either |
| 6 order merge | not expressible | **expressed** | gone: `src.delete()` replaces `UNDECIDED_delete(src)` and the explicit removal of every source line; copied lines take their parent key from `Order.items.add` (#49). Still there: two parameters of one type may be the same row (guarded by ID, unspecified, as in spike 0002). The unit test can assert `r.removed(src)` but cannot list the deleted lines - they are "every owned child of src" (#57) |
| 7 expire unpaid orders | expressed, awkward | expressed, awkward | gone: the flat, ambiguous `Profile(Order.items, Item.allocations, Allocation.stock, ...)` is one nested path; allocations are deleted with `a.delete()` instead of a relation operation on a relation that is not owned. Still there: one use case per order chosen on the query path, the count summed by the scheduler (X9), `Changes().returning(False)` (X10) |
| 8 account transfer | not expressible (R8.5) | **expressed** in both candidates | gone: `insert_all` for three rows; the legs' parent key (#49). R8.5 is #58's `IdempotencyKeyReuse` (a runtime rule, not a shape). The destination balance assertion, dropped in round 1, is restored (round 4) |
| 9 profile edit | expressed | unchanged (ported only) | `Address(...)` without `user_id` (#49); the `Op` list becomes `list[Op[User] \| RelOp[User]]` |
| 10 payment approval notice | expressed, awkward | carried over (ported, round 4) | `insert(payment)` replaces `Order.payments.add(payment)`, and `payment.set(...)` replaces `Order.payments.update(payment, ...)` in `confirm_payment`. Not mechanical: `decline_payment` took `order` only as the receiver of `Order.payments.update(...)`; written directly, the parameter is unused, so the port drops it and the `@process` handler binds the payment only - one load less, and the order is no longer read in that run |

The cost of R8 becoming a type error is visible in use cases 2, 6 and 9: a list that collects
column and relation operations for one `.set` is `list[Op[O] | RelOp[O]]`.

## Verdict

**Holds, under three conditions the probes found.** On the lines the spike wrote, every shape of
the Question type-checks the same way under pyright and mypy, and every misuse in `fail_shapes.py`
is rejected by both, once the conditions below hold. Where the checkers still differ:
- inside `Annotated[...]` metadata mypy checks nothing (X1);
- mypy accepts a declared type written directly on a relation's class access that widens its
  owner, and then F11 and F21 pass (`probe_owner_widen.py`);
- `owned=` (the rejected alternative) given a literal-initialised constant: pyright accepts, mypy
  rejects (`probe_owned_flag.py`);
- on F13-F17 and F21 mypy names a misleading reason (the instance type, or the function); for a
  predicate over another entity in `where` built from two columns
  (`Order.where(Stock.allocated <= Stock.quantity)`) mypy reports the operator (`Unsupported
  operand types`) where pyright reports `Pred[Stock]` against `Pred[Order]` - both reject it.

The conditions:
1. **`RelOp` is invariant in its owner, and `insert` takes `AddOp` only** (F11, F24).
2. **`Load.after`'s load arguments are typed by an invariant `Path[O]`, not the covariant
   `OwnedExpr[O]`** (F17, F21, F22). Where the receiver fixes the owner (`relation.load(...)`) a
   covariant type stays - invariance there rejected a nested load through a nullable many-to-one
   (pyright; mypy for a chained path) - but it is `LoadPath[O]`, which only relations derive from,
   so a column is not a load path (F30, F31).
3. **`RelOp` is not an `Op`, and `.where` / `.load` on an owned relation return the read-only
   `Relation`** (F25-F27). The price is `list[Op[O] | RelOp[O]]` where both kinds are collected.

Use cases 3, 6 and 8 move to "expressed"; 4 and 5 become less awkward; 7 keeps its spike 0002
shape with the nested path. Two things the rewrites lose or cannot show:
- use case 4 loses R4.5's lock: `Load.after` has no `lock=` argument (spike 0002 locked the
  variants' stock rows through a `lock="for_update"` profile; #64 decides `lock=`);
- use case 6's unit test cannot see the deleted child rows: `src.delete()` records "every owned
  child of src", not the rows (#57). Round 1 ("holds, with two conditions") was wrong for S6: the one-ref
form accepted a path of another entity. Both the architect and the type-reviewer found it.

| Shape | Verdict | Condition or cost |
|---|---|---|
| S1 `Entity.delete()` | holds | `.delete()` on a ref is a runtime error (R1), as `.set` on a ref; `delete` is a reserved field name (F29) - as every `Entity` method name is (the reproduction found `set` rejected the same way) |
| S2 `RowSet[Self]` | holds | declared invariant; a relation operation in a set change is rejected only because `RelOp` is not an `Op` (F27); one predicate is required (round 5, F32-F34), an unpacked possibly-empty list stays a runtime rule (R17) |
| S3 `insert`, candidate A (**rejected**, maintainer 2026-11-26) | holds | needs a runtime rule for `.set` on a new entity (R5); kept as a record in `uc08_transfer_a.py` |
| S3 `insert`, candidate B (**chosen**) | holds | only with an invariant `RelOp` and `AddOp` children (F10, F11, F24); `.set` on a new entity is a runtime error (R13) |
| S4 owned-only operations | holds | read-only `where` / `load` views (F25, F26); declared with **`owns_many(...)`** (chosen; the annotation and the specifier, F28; the domain uses it since round 5). The rejected `owned=True` flag (F8, F9) splits the checkers for a literal-initialised constant (`probe_owned_flag.py`). Owned children can still be written directly (R10-R12); the declaration's consistency with `parent_fk` and the root is seal's (R18) |
| S5 nested paths | holds | with the covariant `LoadPath` on `relation.load` (round 4; F30, F31); checked by mypy only outside `Annotated[...]` (X1); the flat form is a seal error (R15) |
| S6 `Load.after` forms | holds | **only with the invariant `Path`** (F17, F21, F22); the same X1 condition; parameter type vs function result and `missing="none"` on a non-optional result stay seal checks (R9, R16) |
| S7 `missing` on `Load.when` | holds | - |
| S8 `= INJECTED` on dependent loads | holds | passing them to `bind`, leaving them out of a direct call, and a misplaced `INJECTED` are runtime / seal errors (R2-R4) |

Consequence for the design: **no edit to §4.2 / 4.3 / 4.4 / 4.7 / 4.8 / 8.2 in this change.** They
change with the two follow-up ADRs; #57 / #59 / #60 close after them. §9.6 links this write-up and
the maintainer's decisions (#48 needs no follow-up: PR #77 recorded it in 4.5 / 9.1).

### Maintainer decisions (2026-11-26)
1. **`owns_many(...)`** declares an owned relation; `one_to_many(..., owned=True)` goes away (#9
   removes the flag; the stub keeps it only as the rejected alternative's probe). The argument is
   the one #49 used for `parent_fk` over `fk(parent=True)`: if behaviour differs, the name
   differs - the declaration decides version bumps, cascade delete and which write operations
   exist. And the flag splits the checkers for a literal-initialised constant (above).
2. **Candidate B**: the owned children of a new root are written `insert(t,
   Transfer.legs.add(...), ...)`; `.set` is for loaded snapshots only, and `.set` on a new entity
   is a runtime error (R13). One runtime rule instead of two (R13 replaces A's R5), and `insert`
   rejects column and non-`add` operations by type (F10, F24). The cost, accepted: a new child
   cannot bring owned children of its own.
3. **A row set needs a predicate**: `Entity.where(pred, /, *preds)`. `Order.where()` with
   `.delete()` / `.set(...)` is a type error in both checkers (F32-F34); an unpacked list that
   may be empty is not caught by types (R17). Only `Entity.where` changes - a relation's
   `.where(...)` (partial loads) and the query path's `where` are unchanged.

Open: whether row sets replace partial `.where` loads (ADR 2, below).

### ADR directions
1. **Writes beyond `.set`: `insert`, `delete`, and relation operations only through an owned
   root** (#57, #60 points 1, 3, 4).
   - Changes design 8.2 "Write syntax: a single `.set`" (`insert` and `.delete()` are write verbs
     outside `.set`; ADR-0003's "creation and modification are different operations" is the
     argument), "Aggregate boundaries", "Field type surface" (`Owned[...]` / `owns_many` next to
     `Rel[...]` / `one_to_many`), 4.3 (`Entity.where` needs a predicate) and 4.4.
   - Amends ADR-0003 (`delete` reserved, F29; every `Entity` method name is) and ADR-0004:
     Decision 3, the variance of `RelOp`, `Path` and `RowSet` pinned by type tests; Decision 4,
     two new places where the owner is solved from several arguments and still checked by type,
     thanks to invariance - with its known gap: under mypy a declared type written on a
     relation's class access widens the owner and gets past both (`probe_owner_widen.py`).
   - **Decided by the maintainer (2026-11-26)**: `owns_many`; candidate B (`.set` on a new
     entity is an error; a new child brings no children of its own); `Entity.where` requires a
     predicate.
   - **Still for the ADR to decide:**
     - that seal checks `owns_many`, the child's `parent_fk` and `aggregate_root=True` against
       each other (types do not, R18), and the final names (#9);
     - what R10-R12 raise (a direct write of an owned child), or a type-level marker for owned
       children (not probed);
     - `insert_all` and owned children: the bulk path only (Phase 2, #33), whether it rejects
       owned children (R14), and that `insert_all` in the commit batch (#60 point 2) stays with
       #33;
     - the rejection of `identity`-key roots with owned children in Phase 1a;
     - nested relation operations (spike 0002 X15): `OwnedRelation.update` takes `Op[E] |
       RelOp[E]`, so an operation on an owned grandchild type-checks - allowed or not, and
       whether it bumps the root's version;
     - **#57's open semantics**, which gate the Phase 1a exit (use case 6): `src.delete()` also
       deletes `Order.tickets`, an owned relation the use case did not load; whether `.delete()`
       checks `version` / `expected_version`; `.delete()` on a new entity; `.delete()` and `.set`
       of one row in one step (`ConflictingWrites` per the decision); the alternative of requiring
       owned relations to be loaded (the test API could then list the deleted children); the
       set-level `RowSet.delete()` and the owned children it never reads (Phase 2, #33, the same
       decision);
     - the cascade DELETE of a root's owned children is itself a set-level statement (by the
       root's key): how it meets `IntraUsecaseConflict` (an update of one of those children in
       the same use case) and the commit planner's edges (#15: child DELETE before the root's);
     - the error class of a `23503` (a non-owned row still pointing at a deleted child, e.g. an
       `Allocation` of a deleted item): a `DatabaseError` subclass, or a `UsageError` that names
       the non-owned relation to clear.
   - Phase 1a's exit (use cases 6, 8, 9) waits on ADR 1 only: none of them uses a row-set load or
     another ADR 2 form, so ADR 2 can follow with the set-load implementation in Phase 1b (§9.6).
2. **Row-set loads and the dependent-load forms** (#59 points 2, 3).
   - Changes design 8.2 "Dependent loads" and "Partial loads of large aggregates", and 4.7.
   - Proposes:
     - `Entity.where(...)` is a `RowSet[E]` (with at least one predicate), used as a set change, a
       set-level delete or a load.
     - A `Load.after` function returns a `RowSet[E]`, a `Sequence[E]` of refs or `E | None`, and
       `missing=` applies only to one ref (and only to an optional result - a seal rule, R16).
     - Its load arguments: either `*paths: Path[E]` with an invariant `Path` (condition 2), or the
       reproducer's receiver form `Load.after(fn).load(...)`, which spells them like
       `relation.load(...)` and needs no invariance at all. Both reject the same lines; the ADR
       weighs them as equals (the invariant `Path` adds a second relation base class; the
       receiver form adds a `LoadAfter[E]` type and a second call). One observation in favour of
       the receiver form (independent review): there mypy's message points at the wrong path,
       while with `*paths: Path[E]` it blames the function (F17, F21).
   - **Open (not decided by the maintainer): do row sets replace partial `.where` loads?** The
     ADR must name the invariants it bends. Three forms can load the same rows, and no check can
     tell them apart (a function body is opaque to seal):
     - a partial load `Load(Order.items.where(Item.status == ACTIVE))` and a `Load.after`
       returning `Item.where(Item.order_id == order.id, Item.status == ACTIVE)`;
     - `Load.when(..., match=...)` and `Load.after(point_wallet)`.

     That is "one way per operation" kept by a documented rule, not by structure. Replacing
     partial `.where` loads (keeping `.count()` / `.exists()`) removes one overlap and closes the
     hole of a module-level partial load that calls the clock once, since a `Load.after` function
     runs again on every attempt with a fresh `Now`. **Its cost to weigh:** a constant filter that
     is today part of load stage 1 (a partial load folds into the first round trip) becomes a
     `Load.after`, which adds a load stage - one more round trip per such load, against design
     8.3's "two round trips" (1 load batch + 1 commit batch). Use case 5 would not lose anything,
     because it uses whole relations. `Load.when` stays the form that folds into a subquery with
     no extra round trip.
   - States the transactional consequences:
     - load arguments and nested paths on `Load.after` results add no stage;
     - row-set results are ordered by primary key, so the bodies are deterministic across retries
       and tests;
     - row-set functions run again on every attempt;
     - a `Now` parameter of a `Load.after` function binds to the use case's `Now` by name (seal);
     - predicate reads take SIRead locks, and a sequential scan escalates to a relation lock
       (spike 0003). "A smaller read set" is not used as an argument until measured.
   - Not covered by the spike: combining predicates in `Load.when(match=...)` (#59 point 3 leaves
     it to #10 with #51).
   - Also to settle:
     - `in_`'s operand: an empty list (a predicate that is always false, compiled how) and the
       array parameter it binds to;
     - the flat path is a type error under `Load.after` (`*paths: Path[E]` takes one entity's
       paths) but a seal error under `Profile` / `Load` (R15) - one rule, two checks;
     - a row-set function's predicate never runs in a unit test: the test passes the loaded rows
       by hand (`hold_seat(..., holds=[...])`), so a wrong predicate is caught only by an
       integration test.

Both ADRs carry X1's consequence: write load declarations as named values, because mypy does not
check them inline in `Annotated[...]`.

## Reproduction

### Type reproduction, round 1 (type-reviewer)
Round 1 is the state before the review changes (stub `8a0ad0fc70a53ced...`, F1-F20, R1-R9, use
cases 3-8). Its discrepancies 1-3 and 5 led to round 2's changes (Review).

- **Who / date:** the `type-reviewer` sub-agent, 2026-11-26, from this write-up; it did not run
  the spike and wrote its own stub and probes before opening the author's files. Sources in
  `repro/types/`; raw output in the git-ignored `results/repro-types/`. Rerun from the repository
  root: `bash spikes/0007-phase-1a-type-shapes/repro/types/run.sh`.
- **Setup:** Python 3.14.7, pyright 1.1.414, mypy 2.4.1 (compiled) - the same as Setup
  (`results/repro-types/versions.txt`). Repository gates clean: `uv run pyright` 0 errors,
  `uv run mypy` no issues in 24 files, `uv run python -m tools.typetests` 0 problems.
- **Built:** `repro/types/lib.pyi` and `domain.py`, copied from spike 0002 (sha256
  `ad6ea7fec42121cd...` / `caf83036e63451df...`, verified) and changed by the reproducer from the
  Setup list and the decision comments of #48, #49, #51, #57, #59 and #60, not from the author's
  stub. One difference by choice: #51's overloads on all six comparison operators, not on `__eq__`
  only. The `__eq__` / `__ne__` override needs one suppression per checker (mypy reports it on the
  first `@overload`, pyright on the last overload). Probes: `pass_repro.py` (S1-S8, `assert_type`),
  `fail_repro.py` (F1-F20 and the reproducer's E1-E8), `pass_runtime_only.py` (R1-R9),
  `pass_flat_path.py`, and per checker `probe_annotated_repro.py`, `probe_join.py`,
  `probe_join_reveal.py`; two stub variants, `variant_relop_inferred/` and
  `variant_after_receiver/`.
- **Commands:** `uv run python -m tools.typetests <stub, domain, pass, fail, runtime, flat files>`
  -> `0 problem(s) in 6 file(s)`; per checker, inside `repro/types/`: `uv run pyright <f>.py` and
  `uv run mypy --strict --show-error-codes --no-incremental <f>.py`; the author's
  `bash spikes/0007-phase-1a-type-shapes/run.sh`.

| Shape | Reproducer's lines | pyright | mypy | vs. write-up |
|---|---|---|---|---|
| S1 | `order.delete()` | `Changes` | `Changes` | agree |
| S2 | `Order.where(...)` / `.delete()` / `.set(...).emit_each(...)`; F1-F4 (`fail_repro.py` 60, 64, 68, 69) | `RowSet[Order]` / `Changes` / `SetChange[Order]`; `reportReturnType`, `reportOperatorIssue` (+ `reportUnknownVariableType`), `reportArgumentType` x2 | the same types; `return-value`, `operator` (+ `no-any-return`), `arg-type` x2 | agree |
| S3 | `insert(SeatHold(...))`, candidate A, candidate B; F10, F11, F12 (86-88) | `Changes`, accepted, `Changes`; `reportArgumentType`, `reportArgumentType`, `reportCallIssue` | the same; `arg-type`, `misc` (cannot infer `E`), `call-arg` | agree |
| S3 F11 | `variant_relop_inferred/` (`class RelOp[O](Op[O])`) | F11 and E6 accepted | F11 and E6 accepted | agree |
| S4 | `Order.items`, `Order.payments`, `Order.items.add(item)`, `order.items`; F5-F7 (73-75), F8-F9 (80-81) | `OwnedRelation[Order, Item]`, `Relation[Order, Payment]`, `RelOp[Order]`, `Sequence[Item]`; `reportAttributeAccessIssue` (+ `reportUnknownMemberType`), `reportAssignmentType` (+ `reportUnknownVariableType`) | the same types; `attr-defined`, `assignment` | agree |
| S5 | three levels down to `Allocation.stock.load(Stock.warehouse)`, `Seat.tickets.load(Ticket.order)`, `Ticket.order.load(Order.items)`; F13-F16 (92-95) | accepted with the write-up's types; `reportArgumentType` | the same; `arg-type` | agree (mypy's message: discrepancy 4) |
| S6 | the three forms with load arguments; F17-F19 (98-100) | accepted; `reportCallIssue` + `reportArgumentType` (+ `reportUnknownVariableType`), `reportArgumentType`, `reportArgumentType` | accepted; `arg-type`, `call-overload`, `list-item` | agree on these lines; **disagree** with the verdict (discrepancy 1) |
| S7 | `Load.when(..., missing="none")`; F20 (101) | accepted; `reportArgumentType` | accepted; `arg-type` | agree |
| S8 | `holds`, `now`, `wallet` inside the use cases; `hold.bind(seat=..., user_id=...)`, `refund.bind(order=...)` | `Sequence[SeatHold]`, `datetime`, `Wallet \| None`; accepted | the same | agree |
| R1-R9 | `pass_runtime_only.py` | all accepted | all accepted | agree |
| `Annotated` | seven misuse lines in metadata: F13 in an alias and in a parameter, F14, F17, F18, F20, a misspelled method (`laod`) | 10 errors, on every line | `Success: no issues found` | agree |

The reproducer's own lines E1-E8 are rejected by both: `order.set(Order.payments.add(p))`
(`reportAttributeAccessIssue` / `attr-defined`), `order.set(Wallet.balance.to(m))`
(`reportArgumentType` / `arg-type`), `insert(Order.where(...))` (`reportArgumentType` /
`type-var`), `Order.items.add(leg)`, `order.items.add(item)` (instance access is a `Sequence`),
`e6: RelOp[Entity] = Order.items.remove(...)` (`reportAssignmentType` / `assignment`: the
invariance), `Load.after(variants_of, missing="none")` (`reportArgumentType` / `call-overload`),
and an unknown keyword in `bind` (`reportCallIssue` / `call-arg`).

- **The author's script:** `typetests: 0 problem(s) in 12 file(s)` and `variant RelOp inferred -
  errors on line 91: pyright 0, mypy 0`, as Method states; the variant run is not empty (31
  pyright / 22 mypy errors on the other lines). The reproducer's probes against the author's
  `lib.pyi` and `domain.py` (copied to `results/repro-types/on-author-stub/`): `0 problem(s) in
  3 file(s)`, and the same result as discrepancy 1.
- **The author's stub against Setup:** sha256 `lib.pyi` `8a0ad0fc70a53ced...`, `domain.py`
  `d1efaca93598f43d...` - match. The diff against spike 0002 contains every change Setup lists
  and nothing else; the domain diff is the eight lines Setup describes (four `Owned[...]`, four
  `parent_fk`), the same as the reproducer's. **Partly** for "every changed line carries
  `# [0007]`": 26 added code lines have no marker - continuation lines of wrapped declarations
  (`lib.pyi` 65-66, 71-72, 135-136, 139-140, 177-178, 209-210, 246-254, 304-305, 309-310) - and
  line 293 `def when(  # [0002]` was changed but keeps the `[0002]` marker
  (`results/repro-types/stub-unmarked.txt`). Every changed declaration is marked on at least one
  of its lines.

**Discrepancies**
1. **S6: in the one-ref form of `Load.after`, both checkers accept a path of another entity.**
   - The lines (`probe_join.py`):
     - line 25, `Load.after(payer_wallet, Order.items)`, where `payer_wallet` maps `Order` to
       `Wallet | None`;
     - line 26, the same with `missing="none"`;
     - line 27, a function returning `Wallet`.
   - Expected: rejected by both (S6, "Refuted when ... either accepts it").
   - Observed: pyright 0 errors, mypy 0 errors, on the reproducer's stub and on the author's.
   - Cause: `E` is solved from the function and the paths together, spike 0001's P-A (the effect
     F11 found for `insert`). pyright solves it to `Wallet | Order`, mypy to `Entity`
     (`probe_join_reveal.py` line 15).
   - Why the other two forms are rejected:
     - F17 (list form): only because `list[E]` is invariant. Both checkers blame argument 1, the
       function, with `E` solved from the path (mypy: expected
       `Callable[[Order], RowSet[Order]]`).
     - Row-set form (line 28): because `RowSet` is inferred contravariant.
   - So S6 holds for the row-set and list forms and **does not hold for the one-ref form** - the
     only form with `missing=`. The Verdict's "every misuse it is meant to exclude is rejected by
     both" is not true as written.
   - A form both checkers reject (one run, the reproducer's):
     - The shape: `Load.after(fn, missing=...) -> LoadAfter[E]`, with the paths attached by
       `.load(*paths: OwnedExpr[E])`, so the receiver fixes `E` as for `Relation.load`
       (ADR-0004).
     - The result: lines 25, 26, 28 and F17 rejected (`reportArgumentType` / `arg-type`), the
       three good forms accepted (`variant_after_receiver/`,
       `results/repro-types/variant-after-receiver.txt`).
   - The alternative is to keep `*paths` and leave the check to seal. Either way, ADR direction 2
     ("Its load arguments are paths of `E`") needs this condition, as candidate B needs F11's.
2. **Use case 3: the file does not show "expressed".**
   - R3.5 rests on an abridged `pay`:
     - Spike 0002 imported use case 1's `pay` (R3.5: "rules of use case 1").
     - The rewrite has an "abridged" `pay` (`uc03_coupon_checkout.py` line 62). It has no
       `AlreadyPaid`, no `Payment` row, no `paid_with`, no `OrderPaid` event and no
       `returning(payment.id)`.
     - It raises `CouponNotApplicable` (line 64) where use case 1 raises
       `InsufficientBalance`.
     - The write-up does not say so.
     - Use case 1's `pay` writes the payment with `Order.payments.add`, which #60 point 4
       removes. Written with `insert(Payment(...))` it would type-check, but it is not written.
   - A new X10 workaround: the rewrite starts from an empty `Changes()` (line 77) to add the
     redemption conditionally. This is spike 0002's X10 ("an empty `Changes` is not shown"),
     which use case 3 did not need before: the redemption was an `Op` and is now a `Changes`.
   - Agree that the R3.3 workaround is gone. Disagree with "expressed" until `pay` carries use
     case 1's rules, and then only with X10 in the use case.
3. **The use-case table leaves out workarounds that are still there.** Every claimed removal is
   true.
   - Use case 4: the empty `Changes()` start (line 60, X10) is new; spike 0002 started from
     `order.set(...)`.
   - Use case 6: spike 0002's verdict also named "same-row parameters unspecified". It is still
     open (the use case still guards by ID) and not listed.
   - Use case 7: `Changes().returning(False)` (lines 34, 37, 39; X10) and the count summed by the
     scheduler (X9) are still there.
   - Use case 3: `User.redemptions` (`domain.py` line 100, "declared only so that use case 3 can
     read ...") is still declared and no longer used.
   - Tests: the rewrites drop four of spike 0002's assertions, so those rules are no longer
     pinned:
     - use case 3: `r.updated(coupon)[Coupon.used] == Add(1)`;
     - use case 4: `r.updated(b)`;
     - use case 6: `r.updated(dst)[Order.total]` (R6.4);
     - use case 7: `r.updated(order)[Order.status]`.
4. **S5, mypy's message.** On F13-F16 both checkers give the same code and verdict, but they name
   different types:
   - mypy names the instance type of the wrong argument (`"Sequence[Payment]"`, `"Stock"`,
     `"Warehouse"`; `results/repro-types/fail_repro-mypy.txt`);
   - pyright names the relation (`Relation[Order, Payment]`).

   So a mypy user is shown a misleading reason. The #59 recommendation noted it; Observations
   does not.
5. **Missing from the R table:** the flat path that #59 point 1 makes a seal error.
   `Profile(Order.items, Item.allocations, Allocation.stock)` and
   `Load(Order.items, Item.allocations)` are accepted by both (`pass_flat_path.py`).
6. **`RowSet` variance.** Inferred contravariant in `E`. pyright states it ("Type parameter
   "E@RowSet" is contravariant"), and both reject `RowSet[Stock]` as `RowSet[Entity]`
   (`probe_join.py` line 30). Conversely, both accept `Entity.where()` as `RowSet[Stock]`. No
   probe line depends on this; the real surface should declare the variance, as `Column` does.

| Use case | Write-up | Reproducer |
|---|---|---|
| 3 | expressed | **disagree**: the R3.3 workaround is gone, but R3.5 rests on an abridged `pay` and X10 is added (discrepancy 2) |
| 4 | expressed, except `lock=` | agree; X10 is added (`Changes()` start) |
| 5 | expressed, less awkward | agree, on the removals and on both "still there" items |
| 6 | expressed | agree; same-row parameters still unspecified (not listed) |
| 7 | expressed, awkward | agree; X10 and X9 are also still there |
| 8 | expressed in both candidates | agree; R8.5 rests on #58's decision (2026-11-26, `IdempotencyKeyReuse`), not on a probe |

- **Verdict:**
  - Agree on:
    - S1, S2, S4, S5, S7, S8;
    - S3, both candidates, and that B needs the invariant `RelOp` (the variant reproduces F11);
    - R1-R9 and the `Annotated` claim;
    - the codes of every F line, in both checkers.
  - **Disagree on S6:** it does not hold for the one-ref form of `Load.after` (discrepancy 1). The
    overall "holds, with two conditions" needs a third condition, or the receiver form.
  - **Disagree on use case 3's "expressed"** as written (discrepancy 2).
  - Both disagreements go to the maintainer before the design edit and the ADRs.

### Type reproduction, round 2 (type-reviewer)
- **Who / date:** the `type-reviewer` sub-agent, 2026-11-26, on the round-2 state (stub
  `7a7eb7f9892e3206...`), from this write-up. It extended its own round-1 reproduction before it
  opened the author's round-2 files. Sources in `repro/types/round2/`; round 1's files in
  `repro/types/` are unchanged and still rerun. Raw output in the git-ignored
  `results/repro-types/round2/`. Rerun from the repository root:
  `bash spikes/0007-phase-1a-type-shapes/repro/types/round2/run.sh`.
- **Setup:** the same versions as Setup (`results/repro-types/round2/versions.txt`). Repository
  gates clean: `uv run pyright` 0 errors, `uv run mypy` no issues in 24 files,
  `uv run python -m tools.typetests` 0 problems.
- **Built:** `round2/lib.pyi`, the reproducer's round-1 stub changed by a script written from the
  round-2 Setup list. The domain is unchanged from round 1. The stub changes:
  - an invariant `Path[_P_inv]`, as a second base of `Relation` and `RelColumn` and as the type
    of every load argument;
  - `RelOp[_O_inv]` invariant and not an `Op`, with `AddOp` as its subclass;
  - `OwnedRelation.add -> AddOp`, `update(item, *ops: Op[E] | RelOp[E])`, and the inherited
    `where` / `load` returning `Relation[O, E]`;
  - `Entity.set(*ops: Op[Self] | RelOp[Self])`;
  - `RowSet[_E_inv]` invariant, with `set(*ops: Op[E])`;
  - `insert(entity, /, *children: AddOp[E])`;
  - `owns_many(...) -> Owned[T]`, as a field specifier.
- **Probes:**
  - `pass_r2.py`: round 1's S1-S8 with the round-2 types, an `owns_many` entity, a
    `list[Op[Order] | RelOp[Order]]` passed to `.set`, and a one-ref `Load.after` with a nested
    path.
  - `fail_r2.py`: round 1's F1-F20 and E1-E8, F21-F29, and the reproducer's E9-E14.
  - `pass_runtime_r2.py` (R1-R15, without R8) and `pass_flat_path.py`.
  - `probe_annotated_repro.py`, per checker.
  - Two variants made by the script, each making one TypeVar covariant (`_P_inv` or `_O_inv`) and
    nothing else.
  - `lines.py`, which prints the error lines per checker so that the variants' lost and gained
    lines can be compared.

| Claim | Reproducer's lines (`round2/fail_r2.py` unless named) | pyright | mypy | vs. write-up |
|---|---|---|---|---|
| S6, invariant `Path` | F21 134, F22 135, F23 136; own E9 158 (the one-ref form with a function returning `Wallet`, without `None`) | `reportArgumentType` on the path (+ `reportCallIssue`, `reportUnknownVariableType` on 134, 136, 158) | F21 / E9 `arg-type`, F22 `call-overload`, F23 `misc` | agree |
| `Path` covariant (variant) | error lines lost against the main run | 134, 135, 158 | 134, 135, 158 | agree: of the author's lines exactly F21 and F22 (E9 is the same form); nothing gained |
| `RelOp` covariant (variant) | error lines lost | 102 (F11), 129 (E6) | the same | agree; nothing gained |
| `AddOp` | F24 141; own E10 163, `insert(t, Transfer.legs.update(leg))` | `reportArgumentType` | `arg-type` (`RelOp[Transfer]`, expected `AddOp[Transfer]`) | agree |
| read-only views | F25 142, F26 143; in `pass_r2.py`, `Order.items.where(...)` and `Order.items.load(...)` are `Relation[Order, Item]` | `reportAttributeAccessIssue` (+ `reportUnknownMemberType`) | `attr-defined` | agree |
| `RelOp` is not an `Op` | F27 144; own E14 165, `x: Op[Order] = Order.items.add(item)`; in `pass_r2.py`, a `list[Op[Order] \| RelOp[Order]]` passed to `.set` | `reportArgumentType`; `reportAssignmentType` | `arg-type`; `assignment` | agree |
| `owns_many` | `pass_r2.py`: `OwnedRelation[S4bOrder, Item]`; F28 149 | `reportAssignmentType` (+ `reportUnknownVariableType`) | `assignment` (`Owned[Never]`) | agree |
| F29, a `delete` field | 154; own E12 175, a field named `set` | `reportIncompatibleMethodOverride` | `assignment` | agree (and see discrepancy 6) |
| `RowSet` invariant | own E13 170: `Entity.where()` returned as `RowSet[Stock]` (accepted in round 1, discrepancy 6) | `reportReturnType` | `return-value` | agree |
| round-1 lines | F1-F20, E1-E8 | the same codes as round 1 | the same codes as round 1 | agree |
| S1-S8 | `pass_r2.py` | accepted with the types of Observations (`AddOp[Order]`, `RelOp[Order]`, `Relation[Order, Item]` for a nested load) | the same | agree |
| R1-R15 | `pass_runtime_r2.py`, `pass_flat_path.py` | all accepted | all accepted | agree |
| `Annotated` | `probe_annotated_repro.py`, seven misuse lines | 10 errors, on every line | `Success: no issues found` | agree |

The reproducer's E11, `Order.items.update(item, Transfer.legs.add(leg))` (another owner's
operation inside `update`), is rejected by both (`reportArgumentType` / `arg-type`).

- **The author's script:**
  - `typetests: 0 problem(s) in 15 file(s)`.
  - Variant `relop`: both checkers lose `fail_shapes.py` 111 (F11). Variant `path`: both lose 133
    and 134 (F21, F22). Nothing is gained in either - exactly as Method shows.
  - Each author variant differs from `lib.pyi` in one line (`_O_inv` or `_P_inv` with
    `covariant=True`).
  - The reproducer's round-2 probes against the author's `lib.pyi` and `domain.py` (copied to
    `results/repro-types/round2/on-author-stub/`): `0 problem(s) in 4 file(s)`.
- **The author's stub against Setup:** sha256 `lib.pyi` `7a7eb7f9892e3206...`, `domain.py`
  `bd806a2cfd9b00e6...` - match. Every Setup item is in the stub as described:
  - `Path` (line 83), `RelOp` (88), `AddOp` (96);
  - `Relation` (99), `OwnedRelation` (112), `RelColumn` (120);
  - `owns_many` (215), `RowSet` (231), `insert` (264);
  - `Entity.where` / `set` / `delete` (288-296);
  - the `Load.after` paths (337-351).

  The domain diff is round 1's eight lines plus the two comment lines.
- **The marker convention** in the stub docstring ("a declaration the formatter wraps carries it on
  its first and last line"): checked with a script over every declaration that contains a changed
  line (`results/repro-types/round2/stub-markers.txt`). It holds, with two exceptions (discrepancy
  1).

| Use case | Write-up | Reproducer |
|---|---|---|
| 1 | expressed (R1.2 by #58) | agree. The port changes only `insert(payment)` and its comment, both marked. The verdict rests on #58's decision, not on a probe |
| 2 | unchanged (ported only) | agree that only the writes were ported. A comment and the unchanged verdict are stale, and some changed lines are unmarked (discrepancy 2) |
| 3 | expressed | **agree** (round-1 discrepancy 2 resolved). It imports use case 1's `pay` (line 43) and has no empty `Changes()`: the redemption `insert` is added after `order.set(...)` (line 78). `r.updated(coupon)[Coupon.used]` is restored, and `User.redemptions` is now commented as unused |
| 4 | expressed, less awkward; `lock=` not expressible | agree. The warehouse-group filter in Python and the `Changes()` start (line 60) are listed; `r.updated(b)` is restored (line 85) |
| 5 | expressed, less awkward | agree with the table; the file's docstring contradicts it (discrepancy 3) |
| 6 | expressed | agree. The same-row parameters are listed; `r.updated(dst)[Order.total]` is restored (line 67) |
| 7 | expressed, awkward | agree. X9 and X10 are listed; `r.updated(order)[Order.status]` is restored (line 65) |
| 8 | expressed in both candidates | agree. Both type-check: candidate B with `AddOp` children, candidate A with `Entity.set` taking a `RelOp` |
| 9 | unchanged (ported only) | agree; one changed line is unmarked and drops a note (discrepancy 4) |

**Discrepancies** (none on a type verdict)
1. **The stub-marker convention, two exceptions.**
   - `Load.when` (lines 323-329): the first line is marked `# [0007]`, but the last line is
     `) -> Load: ...  # [0002]`.
   - The second `one_to_many` overload (206-214): spike 0002's declaration with one changed line.
     The decorator and the changed `owned:` line are marked; its first line (207) and last line
     (214) are not.

   Also unmarked: the docstrings of the added classes `Path`, `RelOp` and `Relation` (lines
   84-104). They are docstrings, not declarations.
2. **Use case 2 (`uc02_refund.py`).**
   - Method says only the lines marked `# [0007]` changed. Lines 157-161 (the re-indented
     `Refund(` arguments) and line 184 (a joined line) changed and carry no marker.
   - The comment at line 57, "the design's expression form (4.7) is rejected by both checkers (H2,
     #51)", is no longer true under this stub. With #51's overloads, both checkers accept
     `Load.when(..., match=Wallet.user_id == Order.user_id)` (S7).
   - Both of spike 0002's reasons for "awkward" (#51, X5) are now decided. "Unchanged" is
     therefore the old verdict carried over, not a new judgement.
3. **Use case 5:** the docstring of `uc05_seat_hold.py` (line 9) still says the near seats' holds
   and tickets "are partial loads". The table now says whole relations, which is what line 54
   loads (`Seat.tickets.load(Ticket.order), Seat.holds`).
4. **Use case 9:** line 64 changed and carries no marker. The rewritten comment also drops spike
   0002's note that with `generated="identity"` the default address could not point at the new
   address in the same use case - the case #60's decision rejects in Phase 1a.
5. **mypy's message on F21 / E9.** mypy blames argument 1, the function (`expected
   "Callable[[Order], RowSet[Order]]"`, from the first overload), not the path; pyright names the
   path (`Path[E@after]`). The verdict is the same. As with F13-F16, a mypy user is shown a
   misleading reason, but Observations mentions only F13-F16.
6. **F29 is wider than `delete`.** Every `Entity` method name is a reserved field name: a field
   named `set` is rejected the same way (E12; pyright `reportIncompatibleMethodOverride`, mypy
   `assignment`). The Verdict names only `delete`.

- **Verdict:**
  - Agree on every round-2 type claim:
    - "holds, under three conditions";
    - the invariant `Path`: made covariant, it loses exactly F21 and F22 among the author's lines,
      and also the one-ref form without `None`;
    - `AddOp` (F24), the read-only views (F25, F26), and F27 with `RelOp` not an `Op`;
    - `owns_many` (F28), F29, and the `RowSet` invariance;
    - R1-R15 accepted by both, and the `Annotated` claim;
    - the codes of every F line, in both checkers.
  - Round 1's discrepancies are all resolved:
    - 1 (S6), 2 (use case 3), 3 (the table omissions and dropped assertions), 5 (the flat path,
      R15) and 6 (the `RowSet` variance) are resolved;
    - 4 (mypy's message on F13-F16) is now in Observations.
  - What remains are text-level points 1-6 above. **No disagreement with a verdict.**

### Type reproduction, round 3 (type-reviewer)
- **Who / date:** the `type-reviewer` sub-agent, 2026-11-26, on the round-3 state (stub
  `22645da138c52d71...`, verified; `domain.py` unchanged, `bd806a2cfd9b00e6...`). Sources in
  `repro/types/round3/`: the reproducer's round-2 stub with only `Relation.load` and
  `RelColumn.load` back on `OwnedExpr[E]` / `OwnedExpr[T]`, the round-2 probes, and
  `pass_nullable.py`. Raw output in `results/repro-types/round3/`. Rerun with
  `bash spikes/0007-phase-1a-type-shapes/repro/types/round3/run.sh`.
- **The false rejection, reproduced first, on the reproducer's round-2 stub and on the author's
  stub with the two `load` methods put back to `Path`** (`round2-stub-nullable.txt`,
  `author-stub-load-path/`):
  - pyright rejects `Order.show.load(Show.seats)` and `Order.user.load(User.addresses)`
    (`reportArgumentType`: `"Show" is not the same as "Show | None"`).
  - mypy accepts those two lines, but it rejects the chained
    `Profile(Order.show.load(Show.seats.load(Seat.tickets)), ...)` (`arg-type`, `expected
    "Path[Show | None]"`).
- **(a)** Both checkers accept both nullable nested loads, with `RelColumn[Order, Show | None]` and
  `RelColumn[Order, User | None]`, and also the chained `Profile` line. This holds on the
  reproducer's round-3 stub and on the author's stub as shipped.
- **(b)** `typetests: 0 problem(s) in 7 file(s)` (`round3/typetests.txt`). F13-F16 and F21-F23 are
  still rejected with the round-2 codes, and so are all the other F and E lines of rounds 1 and 2.
- **(c)** Covariant `Path` variant: both checkers lose `fail_r2.py` lines 134, 135 and 158 (F21,
  F22, and the reproducer's E9, the same one-ref form). Nothing is gained, and F13-F16 are not
  lost. The `RelOp` variant still loses only F11 and E6 (`variants.txt`).
- **(d)** The author's `run.sh`:
  - typetests `0 problem(s) in 15 file(s)`;
  - variant `relop` loses `fail_shapes.py` line 111, variant `path` lines 133 and 134, and nothing
    is gained in either;
  - it passes its new check, `pyright lib.pyi` on each variant stub.
- **(e)** Setup, Observations and Verdict match the stub:
  - `Path[E]` appears only on the three `Load.after` overloads (lines 339-353).
  - Both `load` methods take `OwnedExpr` (lines 111 and 125).
  - The two nullable lines are in `pass_shapes.py` (lines 132-133).
  - The round-2 minor points are fixed: the marker convention now has no exception
    (`stub-markers.txt`); the use case 2 comment and its "carried over" verdict; the use case 5
    docstring; the use case 9 note; mypy's message on F17 / F21; reserved method names.
- **Discrepancies** (text only):
  1. Observations ("pyright reject[ed] a nested load through a nullable many-to-one while mypy
     accepted it") and Verdict condition 2 ("under pyright only") are true for the two pinned
     lines, but not in general. mypy also rejected a chained nested load through the nullable
     relation. The conclusion, covariant `OwnedExpr` on `relation.load`, is unaffected.
  2. Method line 89 still says "only the lines marked `# [0007]` changed". `uc02_refund.py` now
     states the convention as statements (a wrapped statement is marked on its first line), which
     covers its six unmarked continuation lines (159-163, 186).
- **Verdict:** agree on (a)-(e) and on the round-3 change. No disagreement with a verdict.

### Type reproduction, round 4 (type-reviewer)
- **Who / date:** the `type-reviewer` sub-agent, 2026-11-26, on the round-4 state after the rebase
  onto `2876e1b`. It extended its own reproduction before running the author's script.
- **Sources:** `repro/types/round4/`. The stub is the reproducer's round-3 stub with three changes:
  - a covariant `LoadPath[_L_co]`, which only `Relation` and `RelColumn` derive from, typing
    `Relation.load` / `RelColumn.load`;
  - `Load.after`'s list form taking `Sequence[E]`;
  - the comparison operators unchanged: the reproducer's stub already had spike 0006's final
    overloads on all six operators, with the suppressions where spike 0006 puts them.
- **Rerun:** raw output in `results/repro-types/round4/`; rerun with
  `bash spikes/0007-phase-1a-type-shapes/repro/types/round4/run.sh` (exit 0). Gates clean:
  pyright 0 errors, mypy no issues in 24 files, `tools.typetests` 0 problems, guards 0.
- **Typetests:** `0 problem(s) in 10 file(s)`, covering rounds 1-3's files and the new
  `pass_r4.py`, `fail_r4.py` and `pass_runtime_r4.py`.

| Item | Reproducer's lines | pyright | mypy | vs. write-up |
|---|---|---|---|---|
| (a) | `pass_r4.py`: `Stock.allocated` against `Stock.quantity` with all six operators; `Stock.quantity >= Item.quantity`; `Check(lambda: Stock.allocated <= Stock.quantity)`; `fail_r4.py` G6, an `int` column against an `Id[Warehouse]` column | `Pred[Stock]` x6, `Pred[Stock \| Item]`, accepted; G6 `reportOperatorIssue` | the same; G6 `operator` | agree |
| (b) | `fail_r4.py` F30 (12), F31 (13); own G1, a column one level deeper (14); own G2, a column inside `Profile` (15); the nullable nested loads (`pass_nullable.py`) | `reportArgumentType`; nullable accepted | `arg-type` (`expected "LoadPath[Item]"`); nullable accepted | agree. On the reproducer's round-3 stub (`OwnedExpr`), lines 12-15 are accepted by both (`on-round3-stub/`) |
| (c) | `pass_r4.py`: `Load.after` of a function returning `tuple[Variant, ...]` and one returning `Sequence[Variant]`; F17 (`fail_r2.py` 113); own G4, the tuple form with a wrong path (`fail_r4.py` 17); covariant `Path` variant | accepted; rejected; variant loses 113, 134, 135, 158 and `fail_r4.py` 17 | the same | agree: F17, F21, F22 are lost (plus E9 and G4, the same forms); nothing gained; the `RelOp` variant loses only F11 and E6 |
| (d) | `probe_owner_widen_repro.py`, `probe_widen_cause.py`, `probe_widen_path.py` | rejects every widening (`reportAssignmentType`) | accepts the widening and what follows it | **agree on the observation, disagree on its cause and scope** (discrepancy 1) |
| (e) | `probe_owned_flag_repro.py`: `owned=` given a `bool` variable, under an `Owned[...]` annotation (16), a `Rel[...]` annotation (17), and no annotation (20) | 16, 17 `reportAssignmentType` (+ `reportUnknownVariableType`); 20 only `reportUnknownVariableType`. In the default mode (run outside the repository) 16 and 17 are rejected and 20 is accepted | `call-overload` on all three | agree for a call-initialised `bool`; round 5 adds the literal-initialised case, where the checkers split (Observations) |
| (f) | `pass_runtime_r4.py`: R16 (`Load.after` of a function returning `Wallet` with `missing="none"`; a `Load.when(..., missing="none")` parameter declared `Wallet`); R17 (`Order.where().delete()`, `Order.where().set(...)`); R18 (a plain `fk` under an `Owned` relation, a `parent_fk` with no owned relation, owned children on a class without `aggregate_root=True`) | all accepted | all accepted | agree |
| (g) | `uc10_payment_approval.py` against spike 0002's file; `uc08_transfer_a.py` line 56, `uc08_transfer_b.py` line 55 | - | - | agree. Only marked statements changed. `decline_payment` drops `order`, and no R10 requirement reads the order on a decline. The destination assertion matches spike 0002's line 77 |
| (h) | `repro/types/round3/run.sh` | - | - | **agree; the bug was the reproducer's.** Round 3's stage 2 named `probe_annotated_repro.py`, which the reproducer never copied into `round3/`, and `\|\| true` hid the failure. The added file is identical to the round-2 probe, and the script now exits 0 with output. `\|\| test $? -eq 1` fails on a checker exit of 2 and passes on 1 (checked). Rounds 1 and 2 still use `\|\| true`; their stage-2 files exist, so nothing is masked today |
| (i) | `lib.pyi` / `domain.py` | - | - | agree: `c4ea74464353eb68...` / `4abdfda57ba3ff08...`. The marker check finds no declaration whose first or last line lacks `# [0007]` (`stub-markers.txt`) |

- **The author's script:** exits 0 with exactly Method's output. `0 problem(s) in 16 file(s)`;
  the `relop` variant loses 112 (F11), the `path` variant loses 127, 134 and 135 (F17, F21, F22);
  nothing is gained. Every round-4 probe of the reproducer gives the same results on the author's
  `lib.pyi` and `domain.py` (`results/repro-types/round4/on-author-stub/`).

**Discrepancies**
1. **(d) mypy's owner widening: the cause is the descriptor, not PEP 695 variance, and the gap is
   wider than stated.**
   - **The cause** (`probe_widen_cause.py`):
     - `via_var: OwnedRelation[Entity, Item] = x`, where `x = Order.items` is assigned first, is
       rejected by mypy (line 7). So mypy does treat `OwnedRelation`'s owner as invariant.
     - The same declaration written directly on `Order.items` (line 8) is accepted. The descriptor's
       `__get__(self, instance: None, owner: type[O])` solves `O` from the expected type, and
       `type[...]` is covariant.
     - The variant `variant_ownedrel_inv/` declares `OwnedRelation`'s owner invariant with an
       explicit `TypeVar`. It changes nothing: mypy still accepts lines 8, 14 and 19 of
       `probe_owner_widen_repro.py`.
     - So Observations' "mypy treats `OwnedRelation`'s PEP 695 owner as covariant (it is inferred,
       not declared)" is not the cause, and declaring the variance is not a fix.
   - **The scope:**
     - `t` need not be a union: with a plain `t: Transfer`, `insert(t, rel.add(item))` passes too
       (line 15).
     - A relation that is not owned widens the same way: `Relation[Entity, Payment] =
       Order.payments` (`probe_widen_cause.py` line 9).
     - F21 is bypassed the same way: `wide: Relation[Wallet | Order, Item] = Order.items`, then
       `Load.after(payer_wallet, wide)` - mypy `Success` (`probe_widen_path.py`).
     - So under mypy one annotation defeats both condition 1 (F11) and condition 2 (F21). The
       Verdict's "mypy accepts a declared type that widens an `OwnedRelation`'s owner, and then F11
       passes" should name both.
     - pyright rejects every widening. `.set` is not affected (line 26 is rejected by both), and
       neither is the widening of a `.where()` result (line 20, rejected by both) - only a class
       access under a declared type.
   - For ADR-0004's amendment, the gap is in how mypy solves a descriptor's owner from the context,
     the effect spike 0006 noted in O6's display detail. The ADR needs that cause, not "declare the
     variance".
2. **mypy's message inside `where`** (`fail_r4.py` G5, line 18). `Order.where(Stock.allocated <=
   Stock.quantity)` is rejected by both, but mypy says `Unsupported operand types for <=
   ("Column[Stock, int]" and "int")`: under the expected `Pred[Order]` it reads the right-hand
   column as its value. pyright names the real reason (`Pred[Stock]` is not `Pred[Order]`). This
   does not reach a wrong verdict: every cross-entity predicate tried in `Order.where` (`==`, `<=`,
   `>`, nullable and not) is rejected by both with the two-owner `Pred`
   (`probe_where_cross.py`). But it is one more misleading mypy reason, next to F13-F17 and F21.

- **Verdict:**
  - Agree on (a), (b), (c), (e), (f), (g), (h) and (i).
  - On (d): agree that mypy accepts the widening and that pyright rejects it. **Disagree with the
    stated cause and scope** (discrepancy 1): the gap is the descriptor solving the owner from the
    declared type, it covers every relation, and it reaches F21 as well as F11. Declaring
    `OwnedRelation` invariant does not close it.
  - No disagreement with a shape verdict under pyright. Under mypy, conditions 1 and 2 hold only on
    lines that do not annotate a relation with a wider owner.

### Type reproduction, round 5 (type-reviewer)
- **Who / date:** the `type-reviewer` sub-agent, 2026-11-26, on the round-5 state (rebased after
  #77), changed claims only.
- **Sources:** `repro/types/round5/`. The stub is the reproducer's round-4 stub with
  `Entity.where(cls, pred: Pred[Self], /, *preds: Pred[Self])`; in the domain, the four owned
  relations are declared with `owns_many(...)` instead of `owned=True`.
- **Adapted lines:** two of the reproducer's earlier lines used a predicate-less `where()` and
  were adapted:
  - E13 now returns `Entity.where(Stock.quantity > 0)` and still tests `RowSet`'s invariance;
  - the round-4 R17 line moved to the new probes.
- **Rerun:** raw output in `results/repro-types/round5/`; rerun with
  `bash spikes/0007-phase-1a-type-shapes/repro/types/round5/run.sh` (exit 0). Gates clean.

| Item | Reproducer's lines | pyright | mypy | vs. write-up |
|---|---|---|---|---|
| (a) | `probe_owned_flag_r5.py`: `owned=ANNOTATED` (`ANNOTATED: bool = True`, line 21) and `owned=BARE` (`BARE = True`, line 22) under `Owned[...]`; `owned=FLAG` (`FLAG: bool = flag()`, line 24) | 21, 22 no error; 24 `reportAssignmentType` (+ `reportUnknownVariableType`) | 21, 22, 24 `call-overload` | agree: the checkers split on literal-initialised constants, and both reject `FLAG`. Two of the reproducer's own lines: a `Final` constant (23) is accepted by **both**; `ANNOTATED` under `Rel[...]` (25) is rejected by both (pyright narrows it to `True` and reports `Owned[Unknown]`) |
| (b) | `fail_r5.py`: F32 `Order.where()`, F33 `.delete()`, F34 `.set(Order.total.to(m))`; own H1 `Entity.where()`, H2 `Order.where(pred=...)` (positional-only); `pass_r5.py`: `Order.where(*preds)` with `preds: list[Pred[Order]]` and its `.delete()` / `.set(...)`, a two-predicate `where`, `Order.items.where()`, `select(...).where()` | F32-F34, H1, H2 `reportCallIssue` (+ `reportUnknownMemberType` on F33, F34); `pass_r5.py` accepted, `Order.where(*preds)` is `RowSet[Order]`, `Order.items.where()` is `Relation[Order, Item]` | `call-arg` on all five; `pass_r5.py` accepted | agree |
| (c) | the reproducer's rounds 1-4 files on the `owns_many` domain; the author's `run.sh` | `0 problem(s) in 12 file(s)`; the variants lose the same lines as in round 4 | the same | agree. The author's script exits 0 with `0 problem(s) in 16 file(s)` and the variant lines 112 and 127, 134, 135, nothing gained |
| (d) | `lib.pyi` / `domain.py`; the marker check (`stub-markers.txt`) | - | - | agree on the hashes (`4aee56a8992cbd1e...`, `05862bf0dad939ae...`). **Partly** on the markers (discrepancy 1) |

**Discrepancies** (text only)
1. **`Entity.where` (`lib.pyi` 386-388) is marked on its last line only.** Its first line, `def
   where(`, has no `# [0007]`, against the convention that a wrapped declaration is marked on its
   first and last line.

   Also, line 378 still labels `owns_many` "S4 alternative" in `field_specifiers`, though it is now
   the chosen form, and `OwnedRelation` / `Owned` (204, 239) still describe themselves as "of
   `owned=True`".

- **Verdict:**
  - Agree on (a), (b), (c) and (d)'s hashes.
  - The marker point is cosmetic.
  - Observations now states round 4's discrepancy 1 correctly: the descriptor as the cause, F21 in
    scope, and the invariant variant cited.
  - No disagreement with a verdict.

## Review

### Architect, round 1 (2026-11-26)
- **Who / what:** the `architect` sub-agent read the round-1 write-up, the spike code and spike
  0002 against design 4.4-4.8, 8.2, 9.4, 9.6, ADR-0003, ADR-0004 and the `design-invariants`
  rule. It had no shell and did not rerun the checkers. It ran in parallel with the type
  reproduction, independently.
- **Verdict:** agree with changes - one BLOCKER, twelve MAJOR, four MINOR.
- **What was done** (round 2 is the state of every section above Reproduction):
  - BLOCKER - S6's one-ref form accepted a path of another entity. Confirmed by both checkers
    and independently by the reproduction (discrepancy 1). Fixed by the invariant `Path`
    (condition 2), with F21-F23 and the `path` variant.
  - The F11 variant stub was malformed: the round-1 `run.sh` regex also removed `Relation`.
    `run.sh` was rewritten - one TypeVar per variant, the variant stub must stay clean, and the
    lost / gained error lines are printed. The F11 claim holds under the corrected variant.
  - Candidate B took `remove` / `update` - fixed with `AddOp` (F24). Writes through `.where` /
    `.load` views - fixed with read-only views (F25, F26). R8 - now a type error (F27, `RelOp`
    is not an `Op`, condition 3), with its cost recorded.
  - `owns_many` probed next to `owned=True` (F28). A field named `delete` probed (F29).
  - Owned children written directly (R10-R12), `.set` on a new entity under B (R13), and
    `insert_all` around the owned-root rule (R14) are added to the R table as undecided.
  - Use cases 1, 2 and 9, which the new stub rejected, are ported (only the write lines).
  - The use-case table is corrected: use case 4 over-reads stocks and has X10; use case 5's near
    seats load whole relations, not partial loads; 6 and 7 list what is still there.
  - The ADR directions now name the section 8 decisions and ADRs they change, #57's open
    semantics, the overlaps and invariants of the row-set ADR, its transactional consequences,
    and `insert_all`.
  - Not done: a type-level marker for owned children (named as an ADR choice, not probed); the
    reproducer's receiver form of `Load.after` was not adopted, and is recorded as the
    alternative.
- **Its scope check** (question 4): #48 is covered. The gaps for #57 (cascade over unloaded owned
  relations, non-owned dependents, a version check), #60 (point 2, X11, X15) and #59 (combining
  predicates) are in the ADR directions above.

### Architect, round 2 (2026-11-26)
The sub-agent has no write access; its text is recorded here as it gave it, with line numbers of
the round-2 files.
- **Who / what:** the `architect` sub-agent re-read the round-2 write-up (Setup to Verdict, the
  Reproduction round 1 and the Review), `lib.pyi`, `domain.py`, `pass_shapes.py`, `fail_shapes.py`,
  `probe_runtime_only.py`, `probe_annotated.py`, `run.sh`, use cases 3, 4, 6, 7 and the
  `results/` files of the round-2 run (`typetests.txt`, `errors-main.txt`, `variant-relop.txt`,
  `variant-path.txt`). Checked against design 4.4-4.8, 8.2, 8.3, 9.6, ADR-0003, ADR-0004 and the
  `design-invariants` rule. No shell: it did not rerun the checkers; the reasoning-only finding
  below is marked as such.
- **Verdict:** agree with changes - no BLOCKER, one MAJOR, five MINOR.
  - Every round-1 finding is either fixed in the code or recorded as undecided with its owner
    (R10-R14, the owned-child marker, the receiver form).
  - The three conditions follow from F11 / F24, F21 / F22 and F25-F27. The corrected variants
    isolate the first two: `variant-relop.txt` loses only line 111, `variant-path.txt` only lines
    133-134, and neither gains a line.
  - Both ADR directions can be drafted once the items below are added.
- **Remaining findings:**
  1. MAJOR - the invariant `Path` likely rejects a nested load through a nullable many-to-one
     relation.
     - `RelColumn.load(*paths: Path[T])` gets `T = Show | None` for `Order.show`, and an invariant
       `Path[Show]` is not a `Path[Show | None]`.
     - So "nothing that should type-check was lost" is untested for it.
     - The `path` variant also shows that the receiver-fixed `.load` never needed invariance:
       F13-F16 stay rejected with a covariant `Path`.
     - Fix: add the two lines to `pass_shapes.py`. If they fail, type `Relation.load` /
       `RelColumn.load` with the covariant `OwnedExpr` and keep `Path[E]` only on `Load.after`.
       Record the cost, and weigh the reproducer's receiver form in the ADR, not only as a
       fallback.
     - (Reasoning from the stub, not a run.)
  2. MINOR - ADR direction 1 leaves out X15 (a nested relation operation on an owned grandchild
     type-checks through `update`) and new grandchildren under candidate B.
  3. MINOR - R5's row says "a runtime rule only candidate A needs"; under B the line is caught by
     R13's rule.
  4. MINOR - `run.sh`'s "variant stub stays clean" check sees only mypy's diagnostics in
     `lib.pyi`; pyright through `fail_shapes.py` does not report an imported stub.
  5. MINOR - #57's open semantics should also cover the set-level `RowSet.delete()` (Phase 2,
     #33, the same decision).
  6. MINOR - bookkeeping:
     - Use case 1's "expressed" rests on #58's decision, not on a probe.
     - The round-1 record counts five MINOR findings where there were four.
     - Stale round-1 files remain in `results/`.
- **What it checked:**
  - Each round-1 finding against the code: `Path` / `RelOp` / `AddOp` / `RowSet` variance and
    bases, F21-F29, R10-R15, `owns_many`, use case 3's import of use case 1's `pay`, the four
    restored assertions, the corrected `domain.py` comments and `probe_annotated.py` docstring.
  - The variant script: one TypeVar per variant, substitution and stub checks, lost / gained
    lines.
  - The ADR directions against design 8.2, ADR-0003's reserved names and ADR-0004 decisions 3 and
    4.
- **What was done (round 3):**
  - Finding 1 confirmed by a run: with round 2's stub, pyright rejected `Order.show.load(Show.seats)`
    and `Order.user.load(User.addresses)` (`reportArgumentType`) and mypy accepted them. So the
    checkers disagreed, and pyright gave a false rejection.
    - `Relation.load` / `RelColumn.load` are back to the covariant `OwnedExpr`, and `Path[E]`
      types only `Load.after`'s arguments.
    - The two lines are in `pass_shapes.py`, accepted by both.
    - F13-F16 and F21-F23 stay rejected.
    - Condition 2, the Observations and ADR direction 2 say so, and ADR direction 2 now weighs
      the receiver form as an equal.
  - Findings 2-5 are in the ADR directions, the R table and `run.sh` (each variant stub is also
    checked with `pyright lib.pyi`).
  - Finding 6: use case 1's row says its basis; the count is corrected; the stale files are
    deleted.
  - The round-2 reproduction's MINORs are also addressed:
    - stub markers on `Load.when` and the second `one_to_many` overload;
    - use case 2's comment, and its verdict marked "carried over";
    - use case 5's docstring;
    - use case 9's `identity` note kept and marked;
    - mypy's message on F17 / F21;
    - "every `Entity` method name is reserved".

### Independent review session, round 4 (2026-11-26)
- **Who / what:** a separate session that did not run the spike reviewed PR #80 (write-up, stub,
  probes, use cases, the reproductions) with its own probes (outside the repository). Verdict:
  approve with changes.
- **Applied in round 4:**
  - Rebased onto `develop` after spike 0006 (#78); `Column`'s comparisons are spike 0006's final
    overloads on all six operators, and the write-up links spike 0006 instead of "spike 0006 pins
    them"; `domain.py`'s `Check` comment is true again.
  - A column passed as a nested load path (`Order.items.load(Item.quantity)`,
    `Stock.warehouse.load(Warehouse.group)`, accepted by both with round 3's `OwnedExpr`): fixed
    with the covariant `LoadPath` (F30, F31; the nullable nested loads still pass).
  - `Load.after`'s list form takes `Sequence[E]`; F17 is still rejected, now by the invariant
    `Path` (the `path` variant loses F17 too).
  - Use case 10 ported (not mechanical: `decline_payment` drops its unused `order`); use case 8's
    destination-balance assertion restored.
  - New probes: `probe_owned_flag.py`, `probe_owner_widen.py`, R16-R18.
  - The Verdict is limited to the lines the spike wrote and lists the checker differences; the
    `owns_many` and candidate wording, the receiver-form observation, use case 4's lost lock and
    use case 6's invisible child rows; ADR additions (cascade DELETE vs `IntraUsecaseConflict` and
    #15, the `23503` class, `in_` operands, the flat-path check split, untested row-set
    predicates); four questions recorded as open for the maintainer.
  - `repro/types/round3/run.sh` stage 2 had a missing file and swallowed the failure: the file is
    there, and both scripts now accept a checker exit of 1 (type errors) and fail on anything else.
- **Rerun differently from the review:** `owned=` with a plain `bool` - round 4 tested a
  call-initialised constant, where both checkers reject; the review had tested a
  literal-initialised one, where they split (pyright accepts, mypy rejects). Both hold; round 5
  records both (corrected by the second independent review). The mypy owner widening reproduced as reported; its
  cause (the descriptor's owner solved from the declared type, not variance) and its reach (F21
  too) came from the round-4 reproduction and were rerun.
- **Not applied:** nothing of the review's own list; the four choices it marked for the maintainer
  are recorded, not made.

### Second independent review and maintainer decisions, round 5 (2026-11-26)
- **Second independent review** (head `68cf9d4`): confirmed the `LoadPath` fix and CI. One
  correction: round 4's "the review saw pyright accept, both reject in strict mode" compared two
  different inputs. The review had passed literal-initialised constants (`ANNOTATED: bool = True`,
  `BARE = True`), where pyright accepts and mypy rejects (`call-overload`); round 4 tested
  `FLAG: bool = flag()`, where both reject. Both hold. `probe_owned_flag.py` now has both (G3,
  G4 rerun here: pyright no error, mypy `call-overload`), and Observations, S4 and the round-4
  notes say so.
- **Maintainer decisions** (recorded in the Verdict): `owns_many` (the domain uses it; the stub
  keeps `owned=` only as the rejected alternative's probe); candidate B (`uc08_transfer_a.py`
  marked as the rejected record); `Entity.where(pred, /, *preds)` - F32-F34 rejected by both
  (pyright `reportCallIssue`, mypy `call-arg`), an unpacked possibly-empty list accepted by both
  (R17, a runtime rule); relation `.where(...)` and the query path unchanged. Open: row sets vs
  partial `.where` loads (ADR 2, with the extra-load-stage cost against 8.3's two round trips).
- **Rebased onto `develop` after PR #77** (`ac6aa81`): the only conflict was `design-KO.md`'s
  i18n header (re-stamped); the CHANGELOG entry moved after #77's; `docs/workflow.md` (+ KO)
  issue ranges aligned with `AGENTS.md` (#1-#80).
- **After the round-5 reproduction:** its only finding (a stub marker on `Entity.where`'s first
  line and three stale comments calling `owns_many` an alternative or owned relations "`owned=True`")
  is fixed; the stub hash in Setup is the fixed one.

## Addendum for ADR-0010 (2026-11-26)
[ADR-0010](../adr/0010-writes-beyond-set.md) (writes beyond `.set`, the first follow-up ADR of
"ADR directions") proposes three shapes this spike did not probe. They were checked on a copy of the
final stub before the ADR states them; the Verdict above is unchanged.

- **Code:** `addendum/` - `lib.pyi` (this spike's stub `9c0de329717a2ac2...` with `# [0010]`
  changes; final hash `dda29acaf925bdf3...`), `domain_addendum.py` (entities only these probes
  need; `domain.py` unchanged), `pass_addendum.py`, `fail_addendum.py`, `run.sh`. The script
  assembles the addendum stub with this spike's unchanged domain, probes and eleven use cases in
  `results/addendum/` and runs every file through both checkers. Same versions as Setup.
- **Question and claims:**
  - **A1** `OwnedRelation.update(item, *ops: Op[E])` (was `Op[E] | RelOp[E]`), because the ADR
    makes ownership one level deep. Both must reject a grandchild operation in a child update
    (spike 0002 X15) and keep every line of this spike.
  - **A2** `type Write[O] = Op[O] | RelOp[O]`, a public name for lists that collect both kinds.
    Both must accept `order.set(*ops)` with `ops: list[Write[Order]]`, and the alias must widen no
    receiver.
  - **A3** (the alternative the ADR weighs, not proposes) a second base `Part` for owned children
    with `ref` / `stub` only. Both must reject `set` / `delete` / `where` on it and `insert` of it
    (R10-R12), and accept writes through the root.

| Claim | Line | pyright | mypy |
|---|---|---|---|
| A1 | `GOrder.lines.update(line, GLine.parts.add(GPart(...)))` (`GLine` declares an owned relation, which the ADR makes a seal error) | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| A1 | `Order.items.update(item, Item.quantity.to(2))` | `RelOp[Order]` | `RelOp[Order]` |
| A1 | `pass_shapes.py`, `fail_shapes.py`, `probe_runtime_only.py` and the eleven use cases on the addendum stub | unchanged (0 problems) | unchanged |
| A2 | `ops: list[Write[Order]]` with column, `add`, `update`, `remove` appended; `order.set(*ops)` | `Changes` | `Changes` |
| A2 | `[Wallet.balance.to(...)]` as a `list[Write[Order]]` | rejected (`reportAssignmentType`) | rejected (`list-item`) |
| A2 | `Order.where(...).set(*ops)`, `ops: list[Write[Order]]` | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| A2 | `insert(t, *ops)`, `ops: list[Write[Transfer]]` | rejected (`reportArgumentType`) | rejected (`arg-type`) |
| A3 | `line.set(...)`, `line.delete()`, `MLine.where(...)` on a `Part` | rejected (`reportAttributeAccessIssue` + strict unknown-type rules) | rejected (`attr-defined`) |
| A3 | `insert(MLine(...))` | rejected (`reportArgumentType`) | rejected (`type-var`) |
| A3 | `order.set(MOrder.lines.add(...), MOrder.lines.update(line, ...))`, `insert(MOrder(...), MOrder.lines.add(...))`, `MLine.stub()`, `MLine.ref(...)`, `order.lines` as `Sequence[MLine]` | accepted | accepted |

`bash spikes/0007-phase-1a-type-shapes/addendum/run.sh` -> `typetests: 0 problem(s) in 19 file(s)`.

**Reproduction (type-reviewer, 2026-11-26).** Wrote its own stub changes and probes from the claims
before opening the author's files (`repro/types/addendum/`, raw output in the git-ignored
`results/repro-types/addendum/`; rerun with `bash spikes/0007-phase-1a-type-shapes/repro/types/addendum/run.sh`).
Agrees on every claimed line in both checkers, also with `+=` / `extend` / `insert` on the list
and with nested `remove` / `update` for A1; the author's script exits 0. Control: `reveal_type`
of `Order.items.update` shows the narrowed signature in the narrowed copy only. Findings:
1. **Applied.** `Part`'s field specifiers left out `owns_many`. A `Part` child declaring one then
   got a constructor parameter under pyright only (mypy `call-arg`). The addendum stub now lists the
   same specifiers as `Entity`'s, and both reject it.
2. **Recorded in ADR-0010 proposal 10.** Without an annotation, a list mixing a column and a
   relation operation is `list[Op[Order] | AddOp[Order]]` to pyright but `list[object]` to mypy,
   so `order.set(*ops)` fails under mypy only (`arg-type`). This is already true of this spike's
   stub. The `list[Write[O]]` annotation is needed, not only shorter.
3. **Recorded in ADR-0010 (A3 alternative).** `RowSet[MLine]` is still a nameable type, so A3
   removes `where` but not the type; `RowSet`'s type variable bounded by `Entity` closes it (19 files
   still pass), at the cost of no row set of a `Part` as a #59 load target.
4. **Recorded in ADR-0010 proposal 4.** `Order.items.update(item)` with no operation type-checks.
   The ADR makes it a runtime `UsageError`.
5. **Recorded in ADR-0010 proposal 1.** A1 closes only the nested form. `line.set(GLine.parts.add(...))`
   and `insert(GLine(...), GLine.parts.add(...))` still type-check, so the depth is a seal rule
   and a direct write of an owned child is proposal 3's runtime rule. Under A3, `insert_all([MLine(...)])`,
   an `Entity`-bound helper and an `Entity`-typed helper are also rejected by both.
6. Cosmetic: mypy prints `Op[Order] | RelOp[Order]` where pyright prints `Write[Order]`.

**`Part.ref` without `expected_version`** (noted by the reproduction): the stub's choice. The ADR
does not propose `Part`, so this is not decided.

### PostgreSQL facts for ADR-0010 (pg-researcher, 2026-11-26)
ADR-0010's delete semantics rest on database behaviour, checked here so that the facts have a
durable home next to the type addendum (the spike rule: throwaway code, durable write-up).

- **Setup:** PostgreSQL 18.6 (fast profile, 26432, default settings), psycopg 3.3.9 (binary,
  libpq 18.0.6), Python 3.14.7. Every script creates and drops its own temporary database and
  refuses port 26433. Tables: `orders`, owned `items(order_id)` / `tickets`, `allocations(item_id)`
  outside the aggregate; for P1 `users` <-> `addresses` (`users.default_address_id` references one
  of the user's own addresses) and `shipments` / `shipment_lines(order_id, shipment_id)`; plain NO
  ACTION, NOT DEFERRABLE FKs with indexes unless a case says otherwise. Each pinned interleaving
  ran 3-5 times on its own threads (blocking confirmed with `pg_blocking_pids`); every run gave
  the same outcome.
- **Code:** `addendum/pg/` (`common.py`, `q1.py`, `q1e.py`, `q2.py`, `q3locks.py`, `q3pin.py`,
  `q3load.py`, `q4.py`, `q4pipe.py`, `n1_cte.py`, `n2_race.py`, `n3_review.py`). Rerun from the repository root:
  `bash spikes/0007-phase-1a-type-shapes/addendum/pg/run.sh` (needs `make db-up`; raw logs in the
  git-ignored `results/addendum-pg/`; exit 0 on this state).

| # | Question | Observed |
|---|---|---|
| P1 | Delete the owned relations and the root in one statement, `WITH c1 AS (DELETE FROM addresses WHERE user_id = ANY($1)) DELETE FROM users WHERE id = ANY($1)` (`n1_cte.py`) | Succeeds where two statements fail in either order (`23503`); sibling owned tables with an FK between them succeed in all 24 orders of the sub-statements. NO ACTION is checked once, after all sub-statements (docs 7.8.4 and 38.1; `execMain.c` `standard_ExecutorFinish` -> `AfterTriggerEndQuery`). RESTRICT also passes inside one statement (a deviation from the standard, documented in `ri_triggers.c` only); as separate statements it fails with `23001`. A row outside the aggregate still referencing a child fails the statement with `23503`. Two root tables that reference each other (`ra.rb_id`, `rb.ra_id`, each with an owned child table): two statements fail in either order (`23503`), one merged statement succeeds (`n3_review.py` (e), 3/3; the independent review of PR #81 found it first) |
| P2 | A child insert racing the delete; the writer as Platina's `add` (INSERT plus the root's `version` UPDATE) or a plain INSERT (`q1.py`, `q1e.py`, `n2_race.py`) | With the root bump: `40001` for the deleter or the writer under SERIALIZABLE and REPEATABLE READ, in every interleaving, for separate statements and the P1 statement, also against a READ COMMITTED writer (which itself gets `23503` when the root is gone). Without the bump: `40001` when both run SERIALIZABLE; `23503` for the deleter when both run REPEATABLE READ, or when the writer runs READ COMMITTED (SSI does not see it). A `23503` with SERIALIZABLE on both sides came only when the inserter started after the delete committed. A **non-owned** insert (a `payments` row referencing the order, no root bump - what Platina's `insert(Payment(order_id=x))` sends): when it commits first, the deleter gets `23503` under SERIALIZABLE and REPEATABLE READ alike; when the delete goes first, the insert gets `40001` (`n3_review.py` (f), 3/3 each; found by the independent review of PR #81). A retry of that `23503` would fail again |
| P3 | `23503` from a non-owned referrer (`q2.py`) | NOT DEFERRABLE: at the end of the DELETE statement; DEFERRABLE INITIALLY DEFERRED: at `COMMIT`. `psycopg.errors.ForeignKeyViolation` (`IntegrityError`); `diag.table_name` / `constraint_name` name the referencing table and constraint (`allocations`, `allocations_item_id_fkey`), the deleted table only the message text. In a pipeline the next `execute`, or `commit` / `sync`, raises it depending on timing; the queued `COMMIT` does not commit |
| P4 | SIRead locks of a cascade that matches no row (`q3locks.py`, `q3pin.py`, `q3load.py`) | The same lock set as the root DELETE alone, as separate statements or in the P1 statement: the root DELETE's NO ACTION check reads the child table with the same predicate. With the index: page locks; without it, or on a small analyzed table: relation locks (sequential scans). Under a small load the 40001 rates (uuid7: 0.015-0.2 % of attempts, single runs 0-22 failures) do not separate the variants; an earlier session's reading that the difference came from the extra round trip did not reproduce |
| P5 | `DELETE ... WHERE id = $1 AND version = $2` (`q4.py`, `q4pipe.py`) | A stale version gives `DELETE 0`, not an error; with `COMMIT` queued in the pipeline the child deletes commit and the root stays. A concurrent committed UPDATE after the load makes the DELETE fail with `40001` first |

- **Also observed:** psycopg in non-autocommit mode sends `BEGIN` with its own Sync before a
  pipeline (`_connection_base.py`), one more round trip than design 8.3 counts - for #18.
- **Not verified:** the durable profile; pipelined batches under load; P1 with a version check over
  several roots or with deferred constraints; P2 beyond three runs per case and under load;
  partitioned tables; the async connection; whether a later PostgreSQL moves RESTRICT to the
  standard's timing.

### Maintainer decisions on ADR-0010 (2026-11-26)
The maintainer accepted ADR-0010 with every proposal as written:
- ownership is one level deep (A1's narrowed `update` stands);
- a direct write of an owned child is a runtime `UsageError`, and A3's `Part` base stays a rejected alternative;
- `identity`-key roots with owned relations are a `SealError` in Phase 1a;
- unloaded owned relations are deleted without loading (P1's one statement per root table);
- the `Write[O]` alias is adopted. Its name is a working name that #13 fixes, since `insert` and `.delete()` are writes the alias does not cover;
- `23503` / `23001` are `ForeignKeyViolation(DatabaseError)`.
