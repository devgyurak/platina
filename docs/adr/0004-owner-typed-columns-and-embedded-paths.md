# ADR-0004: Columns carry their owner; embedded paths are `Order.total.path(Money.amount)`

- Status: Accepted (maintainer, 2026-11-25)
- Date: 2026-11-25
- Related: design sections 4.2 (`Money`, `Meta.checks`), 4.3 (query, Finder), 4.4, 4.5, 4.7,
  8.2 ("Field type surface"), 9.1, 11.8; ADR-0003; issue #2; spike 0001
  (`docs/spikes/0001-type-surface.md`, item 4, F1, F3, P-A, P-C, L6); #51 and spike 0006
  (`docs/spikes/0006-parent-fk-and-column-operands.md`, part B); ADR-0010 and spike 0007
  (`docs/spikes/0007-phase-1a-type-shapes.md`, conditions 1-3, `probe_owner_widen.py`)

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- Section 4 used `Order.total.amount` (a column inside the embedded `Money`) and
  `Wallet.balance.add(-order.total.amount)` (increment a `Money` column by a `Decimal`); section 4.4
  named a path helper `Order.total.path(Money.amount)` as the fallback.
- Spike 0001, item 4, identical in pyright and mypy: with `total: Col[Money]` and a one-parameter
  `Column[T]`, `Order.total.amount` is an error (a generic cannot map the attributes of its type
  argument), and the fallback `path(Money.amount)` accepts any argument, because `Money.amount` on
  the class is just `Decimal`.
- F1 and P-A: a column can carry the class it is declared on. With
  `Col[T].__get__[O](self, instance: None, owner: type[O]) -> Column[O, T]` and value-class fields
  declared `Col[...]`, both checkers type `Order.total.path(Money.amount)` as
  `Column[Order, Decimal]` and reject `path(Rate.amount)` and `path(Wallet.balance)`. The owner then
  flows into operations (`Op[O]`), predicates (`Pred[O]`), relations (`Relation[O, E]`) and set
  changes (`SetChange[O]`), and both checkers reject an operation, predicate or relation operation
  of another entity in `order.set`, `Entity.where`, `SetChange.set` and a child `update`, a wrong
  child type, and a Finder column of another entity (`reportArgumentType` / `arg-type`).
- P-A, queries: where the owner has to be inferred from several arguments of one call, the
  checkers disagree. `select_from(OrderSummary, id=Order.id, item_count=Item.id)` solves the owner
  to `Order | Item` in pyright and to the common base `Entity` in mypy, so a predicate over `Wallet`
  is rejected by pyright and accepted by mypy. An explicit root entity does not pin the owner
  either. The design's query shape (`where(*preds: Pred[object])`) is not broken by owner types,
  but its predicates are not owner-checked.
- Variance: on the same PEP 695 stub, pyright inferred `Column`'s value parameter invariant and
  mypy contravariant, so assigning `Column[Order, object]` to `Column[Order, int]` was an error in
  pyright only. With the variance fixed (owner covariant, value invariant) both checkers agree and
  every round-2 line keeps its verdict. Two ways fix it: old-style type variables with declared
  variance (which the project's ruff configuration flags as `UP046`), or PEP 695 syntax with a
  member that returns the value type; the split comes from `path`'s reference to `Column[T, U]`
  (spike L6).

## Decision
1. A field's class access is `Column[O, T]`, where `O` is the class that declares it
   (`Order.status`: `Column[Order, OrderStatus]`). Value-class fields are declared `Col[...]` too:

   ```python
   @value
   class Money:
       amount: Col[Decimal]
       currency: Col[str] = column(default="KRW")
   ```

2. A path into an embedded value is `Order.total.path(Money.amount)`, typed
   `Column[Order, Decimal]`. Increments of a part of a value object go through the path:
   `wallet.set(Wallet.balance.path(Money.amount).add(-order.total.amount))`. Whole-value writes are
   unchanged (`Order.total.to(Money(...))`). There is no other syntax for the same increment.
3. **Variance.** `Column`'s owner parameter is covariant and its value parameter invariant, and
   type tests pin both under pyright and mypy. How the variance is fixed (old-style type variables
   with a ruff exception, or PEP 695 syntax with a member returning the value type) is chosen when
   `Column` is implemented. The same holds for the types ADR-0010 adds, each declared and pinned:
   `RelOp[O]` (and `AddOp[O]`) and `RowSet[E]` are **invariant** (inferred, `RowSet` came out
   contravariant; with a covariant `RelOp` both checkers accepted another entity's operation in
   `insert`, spike 0007 F11). The dependent-load ADR (ADR-0011, #59) takes the receiver form
   `Load.after(fn).load(*paths: LoadPath[E])`, so no invariant `Path[O]` is needed (spike 0007
   round 6). Declared and pinned there: `LoadPath[O]` **covariant**, and only relations derive
   from it (a column is not a load path, F30, F31); `LoadAfter[E]` **invariant**; `Relation` /
   `RelColumn` covariant in the owner and invariant in the second parameter.
4. **Where the owner is checked.** Owner types are checked only where the receiver fixes the owner:
   `order.set(...)`, `Entity.where(...)`, `SetChange.set(...)`, `SetChange.emit_each(...)`,
   relation operations (`Order.items.add/remove/update`), `RowSet.set(...)`, the Finders of
   `Repository[E]`, `path`, and the load paths `relation.load(...)` (#59) and
   `Load.after(...).load(...)` (ADR-0011). Where the owner would have to be inferred
   from several arguments of one call it is not checked by types, with one exception:
   `insert(entity, *children: AddOp[E])` (ADR-0010) solves `E` from the entity and the
   children, and the invariant `AddOp` leaves the given entity as the only solution, so both
   checkers reject another entity's `add` (spike 0007 F11). Elsewhere: queries
   (`select`/`join`/`where`) are validated when their description is
   built (whether seal can also catch them is #52), and `Profile`, `Load`, `Index`, `Check` and
   `@invariant(fields=...)` are validated by seal. Reason: at those places pyright solves the owner
   to a union and mypy to the common base `Entity`, so the same misuse would be an error under one
   checker only (spike 0001, P-A, S2).
5. A query that references a column of an entity it has not joined is rejected when the query
   description is built. Whether seal can also catch it, and the exact moment, are open (#52).

## Consequences
- The design's own fallback syntax holds and rejects misuse in both checkers; no lambda and no
  runtime rule for paths.
- Operations of the wrong entity are type errors at every receiver-fixed place (the item 3 gap of
  spike 0001 is closed), and `Finder(Order.number)` is `Finder[Order, str]`, as 4.3 already wrote.
- `Column` has two type parameters wherever users name it (`assert_type(Order.status,
  Column[Order, OrderStatus])`, 11.8).
- Value classes declare their fields as `Col[...]`; their instances still read as plain values
  (`m.amount` is `Decimal`), and `Money(Decimal("1000"))` still constructs positionally.
- Query predicates are checked when the query description is built; profiles, load declarations,
  indexes, checks and invariant field lists rely on seal for owner checks. Type-checking query
  predicates is open (#52; a shape that adds the columns of joined entities after the join was not
  tested).
- Left to inference, `Column`'s variance differs between the checkers and changes whenever a
  member is added or removed (spike L4, L6); Decision 3 fixes it and a type test guards it.
- Among the receiver-fixed places, those that take operation or predicate objects (`order.set`,
  `Entity.where`, `SetChange.set`, a child `update`) are rejected by both checkers for the same
  reason (an `Op[Wallet]` or `Pred[Wallet]` is not an `Op[Order]` / `Pred[Order]`). Those that take
  a column by class access (`path`, `emit_each`) get the same verdict, but mypy's reason differs:
  it falls back to `Col.__get__`'s instance overload, reads the column as its value and rejects the
  value, not the owner (which is why its message names the instance type, `incompatible type
  "Decimal"; expected "Column[Money, Never]"`; spike 0001, column-as-value follow-up and round 3).
- **Constraint:** no parameter takes both a column and a value in one union type
  (`T | Column[O, T]`). With such a parameter mypy accepts another entity's column and pyright
  rejects it; narrowing the instance overload to `instance: Entity` makes mypy reject it too, but
  breaks instance access on `@value` / `@event` classes, which have no base. Where an operation
  takes either, the two forms are separate overloads, which both checkers resolve the same way
  (the comparison operators, #51, spike 0006).
- Comparisons on a column take a value of exactly `T` (no numeric widening, so 4.2's check is
  written `>= Decimal(0)`), or a column of the same value type up to nullability through a
  separate overload, which gives a predicate over both owners, `Pred[O | O2]` (#51). 4.7's
  `Load.when(match=Wallet.user_id == Order.user_id)` type-checks (outside `Annotated`; inside it
  pyright only), and `Order.where(...)` rejects a predicate over two owners in both checkers. The
  exceptions are the comparison gaps of design 8.2 "Field type surface" (open, #9; `==` with a
  wrong value type is `bool` until a predicate is required), and the typing spec's `int` to
  `float` promotion applies to a `float` column. The column-as-value fallback does not occur there:
  mypy resolves a column on the right to a column overload (spike 0006, O4).

- **Known gap (mypy):** a declared type written directly on a relation's class access widens its
  owner - `rel: OwnedRelation[Transfer | Order, Item] = Order.items`, then `insert(t,
  rel.add(item))` type-checks for a `Transfer` `t`. It no longer reaches `Load.after`: in
  ADR-0011's receiver form both checkers reject it (spike 0007 round 6, W5). It is how mypy
  infers a descriptor's class access under an expected type, not variance (declaring the relation
  types invariant does not change it); pyright rejects the declaration, and so does mypy when the
  relation goes through a variable first (spike 0007 `probe_owner_widen.py`, W1-W5). Not closed.

## Alternatives considered
- A getter, `Order.total.path(lambda m: m.amount)` (spike item 4 b2; this ADR's first draft): holds
  in both checkers without `Col[...]` value fields, but needs a runtime rule that the lambda is an
  attribute chain, does not check the owner of operations, and adds a lambda to every path.
- `class Money(Additive[Decimal])` so that `Wallet.balance.add(Decimal)` types directly (F3): holds
  in both, but gives the same increment two syntaxes (`Wallet.balance.add(...)` and
  `Wallet.balance.path(Money.amount).add(...)`) and hides which column is incremented.
- An embedded descriptor whose class access is the value class, `Emb[Money]` (item 4 c/c'): types
  the literal `Order.total.amount`, but needs a `Value` base for `.to` and the class leaks
  (`Order.total(amount=...)` type-checks as constructing a `Money`).
- A one-parameter `Column[T]` with `path(Money.amount)`: accepts any argument (item 4 b1).
- Queries that track their entity set (`SelectFrom[R, O]`, an explicit root): the checkers disagree
  or the root does not pin the owner (P-A S2, S3).

## History
- 2026-11-25 - created (Proposed) from spike 0001 as "embedded paths through a getter".
- 2026-11-25 - on hold after the architect review and the reproduction (owner-typed columns, F1;
  `Additive`, F3).
- 2026-11-25 - rewritten in the direction the maintainer chose: owner-typed columns and
  `path(Money.amount)`, the boundary of owner checks (including `Check`), the query rule and fixed
  variance; the getter, `Additive` and `Emb` are alternatives. Renamed from
  `0004-embedded-paths-through-a-getter.md`.
- 2026-11-25 - accepted by the maintainer.
- 2026-11-25 - open items linked to their issues (#51, #52).
- 2026-11-25 - after acceptance, Decision 4 corrected without changing its direction: two entries
  of the list checked "by seal" were placed by when they can actually be checked. Queries
  (`select`/`join`/`where`) are validated when their description is built, as Decision 5 already
  said (seal: #52). `emit_each` moved to the receiver-fixed places: a set change is built when its
  factory is called, so seal cannot see it, and `emit_each` is a method of `SetChange[O]`, whose
  owner is fixed (`**fields: OwnedExpr[O]`; spike 0001 P-A follow-up, both checkers reject another
  entity's column).
- 2026-11-25 - after acceptance, Consequences extended without changing the direction: the
  receiver-fixed places split into those taking operation/predicate objects (same reason in both
  checkers) and those taking a column by class access (`path`, `emit_each`: same verdict, mypy
  rejects the column read as a value), and the constraint that no parameter takes both a column and
  a value before both checkers are probed (#51). Source: spike 0001 round 3 and the column-as-value
  follow-up.
- 2026-11-26 - amended in place after #51's decision and spike 0006, without changing the
  direction: the constraint now forbids only a union parameter (`T | Column[O, T]`) and names
  separate overloads as the shape both checkers agree on; the comparison operands are stated
  (value exactly `T`, column of the same value type up to nullability, `Pred[O | O2]`).
- 2026-11-26 - amended in place, without changing the direction, from spike 0007 and the shapes
  decided on #57 / #60 (recorded in ADR-0010): Decision
  3 lists the variance of `RelOp` / `AddOp` and `RowSet` (invariant) and records spike 0007's
  `Path` / `LoadPath` finding for #59; Decision 4 adds `RowSet.set` and `insert(entity,
  *children)`, an owner solved from several arguments that invariance keeps checkable; the mypy
  gap of a declared type that widens a relation's owner is a Consequence.
- 2026-11-26 - amended in place, without changing the direction: the load paths `relation.load(...)`
  (#59 point 1, nested paths) and `Load.after(...).load(...)` (ADR-0011) are added to
  Decision 4's receiver-fixed places; both checkers reject a path of another entity there (spike
  0007 S5 and round 6). Decision 3's #59 sentence now records what ADR-0011 adopted (no
  invariant `Path`; `LoadPath` covariant, `LoadAfter` invariant, `Relation` / `RelColumn`
  covariant in the owner), and the known mypy gap no longer reaches `Load.after` (W5).
