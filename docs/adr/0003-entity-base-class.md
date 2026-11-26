# ADR-0003: Entities are declared with an `Entity` base class and created with `Order(...)`

- Status: Accepted (maintainer, 2026-11-25)
- Date: 2026-11-25
- Related: design sections 4.2, 4.7, 4.8, 4.12, 8.2 ("Creation syntax and constructor types",
  "Aggregate boundaries"), 9.1, 10.3, 10.8, 11.8, 11.11; ADR-0002; issue #2; spike 0001
  (`docs/spikes/0001-type-surface.md`, items 0 and 2, F2, P-B, P-C); #49 and spike 0006
  (`docs/spikes/0006-parent-fk-and-column-operands.md`, part A); ADR-0010 and spike 0007 (F29)

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- Section 4.2 declared `@entity(table="orders", aggregate_root=True) class Order:` with no base
  class, and section 4 called `Order.new(...)`, `Order.ref(id)`, `Order.where(...)`,
  `Order.stub(...)` and `order.set(...)` on it.
- Spike 0001, item 0: with the decorator alone, pyright and mypy both reject all five
  (`reportAttributeAccessIssue` / `attr-defined`). Without checker plugins (pyright has none), a
  `dataclass_transform` decorator only makes a checker synthesise `__init__` (and comparison
  methods); both ignore its return type, so it cannot add members.
- With a base class carrying the members and the `dataclass_transform`, all members resolve in both
  checkers, and step 1 of 8.2 holds: the synthesised constructor takes the `value` type of
  `Col.__set__(self, instance: Never, value: T)`, a missing required field is rejected, and
  `init: Literal[False]` keeps generated and server-side fields out (items 0 and 2, P-C).
- A classmethod `new` can only be typed by taking the synthesised constructor's `ParamSpec`, so
  `Order(...)` type-checks next to it; the type checker cannot make either the only way.
- Hashability (F2, P-B): with the synthesised `__eq__` and no `frozen`, pyright rejects `{order}`,
  `{order: 1}` and a `Hashable` argument while mypy accepts all three; declaring `__hash__ = None`
  makes mypy reject only the `Hashable` argument. Only `frozen_default=True` (or `eq_default=False`)
  makes both checkers agree, and only `frozen` keeps the synthesised `__eq__`.

## Decision
1. Entities inherit from `platina.Entity`; the table options are class keywords. There is no
   `@entity` decorator.

   ```python
   class Order(Entity, table="orders", aggregate_root=True):
       id: Col[Id[Order]] = pk(generated="uuid7")
       ...
   ```

   `Entity` carries `dataclass_transform(kw_only_default=True, frozen_default=True,
   field_specifiers=...)` and declares `ref`, `where`, `stub`, `set` and `delete` (ADR-0010). `__init_subclass__`
   declares only Platina's options, so dataclass keywords (`kw_only=`, `frozen=`) are rejected.
2. **The creation syntax is the plain keyword constructor `Order(...)`; there is no `new`.** This
   matches events (`OrderPaid(...)`) and values (`Money(...)`), needs no runtime rule against a
   second creation path, and ADR-0002's ID-source rule applies to `Order(...)` unchanged.
   Generated keys, `version_column()`, server defaults, relations and the parent key of an owned
   child are not parameters (`init: Literal[False]` on their field specifiers). The parent key is
   declared with `parent_fk(lambda: Order)` (working name, fixed in #9) and set by the parent,
   `Order.items.add(Item(...))`; a child of a relation that is not owned keeps `fk`, a required
   parameter (#49, spike 0006).
3. **Equality and hashing - type level (decided).** `frozen_default=True`, so both checkers treat
   entities as hashable (spike 0001 P-B: without it pyright and mypy disagree on `{order}`).
4. **Equality and hashing - runtime (decided in #54, from spike 9.4's data).**
   - Two snapshots are equal when they are of the same entity type and all their column values
     are equal (embedded values included). Relations and the load state are not compared. A
     column that has no value yet (a server default or an `identity` key of a new entity) is
     equal only when it has no value on both sides. The hash is the entity type plus the primary
     key (equal snapshots have the same key, so the contract holds). The parent key of an owned
     child that has not been added yet (`parent_fk`, #49) has no value either; how equality and
     the hash treat it is decided in #76.
   - Boundaries: `==` and `hash()` on a ref raise `UnloadedReference` (a ref holds no values). The
     hash of a new entity with an `identity` primary key, whose ID exists only after commit,
     raises `UsageError`. A chain view compares its latest state with `==`; its hash is the
     entity type plus the primary key, so it does not change while the chain runs. `==` and `hash()` through a moved
     alias raise `MovedSnapshotAccess`, like every other read through it.
   - Why columns only: spike 0002 found no use case that needed entity `==` or an entity as a
     set member or dict key (every "same row" check compared IDs); comparing the load state made
     a stub and a loaded snapshot, and one row loaded through two paths (use case 5), unequal
     although they hold the same values. `version` is a column, so two snapshots of one row
     before and after a commit still differ. Identity equality (type and key, as in Django and
     Rails) would make `assert before == after` pass after a change. `==` does not compare
     children; a deep comparison of an aggregate belongs to the test kit (#27).
   - Remaining cost: a new entity with an `identity` primary key cannot be a set member or dict
     key before commit, and two such entities with equal values compare equal - the engine and
     the planner therefore identify new rows by object identity, never by `==`.
5. `@value`, `@event` and `@dto` stay decorators (constructors, ordering and class access work
   through `dataclass_transform` on a decorator).

## Consequences
- One construct declares an entity, and one constructor creates it, as for events and values.
- Every method name of `Entity` is a reserved field name: `ref`, `where`, `stub`, `set` and
  `delete`. Both checkers reject a field named `set` (spike 0001 F2) or `delete` (spike 0007 F29:
  pyright `reportIncompatibleMethodOverride`, mypy `assignment`); class creation rejects all of
  them at runtime.
- `Order.stub(...)` keywords are not type-checked (a "same fields, all optional" signature cannot be
  derived from the constructor) - open, #50.
- Owned children are created without the parent key (4.7 `Order.items.add(Item(sku=..., ...))`):
  passing it is a type error in both checkers (spike 0006), so a new child cannot be created with
  another parent's key. Reading the key before the child is added is open (#76). Owned children
  of a new root are added in `insert(t, Transfer.legs.add(...))` and a relation that is not owned
  has no `add` (ADR-0010). Moving an existing child to another parent still type-checks
  (`Item.order_id.to(...)`, spike 0006 O9) and is open (#9); ADR-0010 decides that seal checks
  `owns_many` and `parent_fk` against each other.
- Section 10.8 generates a slots class per entity at seal; with a base class this needs a metaclass
  `__new__` (or a separate snapshot class), since `__init_subclass__` cannot add `__slots__`.
- With `table=` required on every subclass, entity inheritance and shared-column mixins are not
  possible until a rule says otherwise.
- The immutability error is pyright `reportAttributeAccessIssue`, mypy `misc` and `arg-type`
  (frozen plus the `Never`-instance `__set__`; P-C).

## Alternatives considered
- Keep `Order.new(...)` and make `Order(...)` raise `UsageError`: detection instead of removal,
  and a reserved name `new`.
- `@entity(...)` plus the base class: type-checks (spike item 0) but is two constructs for one
  declaration.
- Free functions (`ref(Order, id)`, `set(order, ...)`): works with a decorator, loses `Self`
  typing on `ref`/`stub`, and changes every example.
- Unhashable entities (`__hash__ = None` without `frozen`): the checkers disagree on set and dict
  literals (P-B), so the type checker would not report the misuse consistently.
- A metaclass is not an alternative to the base class but a way to implement it (users still write
  `class Order(Entity, ...)`); it is the likely way to do 10.8's slots class.

## History
- 2026-11-25 - created (Proposed) from spike 0001.
- 2026-11-25 - amended after the architect review: creation-syntax choice as an open option,
  equality/hashing, class keywords, reserved names, slots and inheritance, section list.
- 2026-11-25 - accepted by the maintainer with creation as `Order(...)` (no `new`) and the
  equality/hashing rules of Decision 3, including chain views and moved aliases; facts from spike
  0001 round 2 (P-B, P-C).
- 2026-11-25 - open items linked to their issues (#49, #50).
- 2026-11-25 - at the maintainer's request the runtime equality/hashing rule became a provisional
  working rule (Decision 3 split into the decided type level, Decision 3, and the provisional
  runtime rule, Decision 4, with its known concerns; #5, #54). The direction is unchanged.
- 2026-11-26 - amended in place (#49, spike 0006): the parent key of an owned child (`parent_fk`)
  joins the fields that are not constructor parameters in Decision 2, and the Consequence that
  called the rule open states it. The direction is unchanged.
- 2026-11-26 - Decision 4 decided by the maintainer in #54 from spike 0002's data: value equality
  over columns only (relations and the load state are no longer compared), a column without a
  value yet is equal only when unset on both sides; no longer provisional. The parent key of an
  owned child before `add` (#49) is pointed to #76, not decided here.
- 2026-11-26 - amended in place, without changing the direction: `delete` (decided on #57,
  recorded in ADR-0010) joins the methods `Entity` declares and the reserved field names (spike
  0007 F29), and the Consequence on owned children points to ADR-0010 instead of #60.
