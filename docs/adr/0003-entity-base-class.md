# ADR-0003: Entities are declared with an `Entity` base class and created with `Order(...)`

- Status: Accepted (maintainer, 2026-11-25)
- Date: 2026-11-25
- Related: design sections 4.2, 4.7, 4.8, 4.12, 8.2 ("Creation syntax and constructor types",
  "Aggregate boundaries"), 9.1, 10.3, 10.8, 11.8, 11.11; ADR-0002; issue #2; spike 0001
  (`docs/spikes/0001-type-surface.md`, items 0 and 2, F2, P-B, P-C)

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
   field_specifiers=...)` and declares `ref`, `where`, `stub` and `set`. `__init_subclass__`
   declares only Platina's options, so dataclass keywords (`kw_only=`, `frozen=`) are rejected.
2. **The creation syntax is the plain keyword constructor `Order(...)`; there is no `new`.** This
   matches events (`OrderPaid(...)`) and values (`Money(...)`), needs no runtime rule against a
   second creation path, and ADR-0002's ID-source rule applies to `Order(...)` unchanged.
3. **Equality and hashing - type level (decided).** `frozen_default=True`, so both checkers treat
   entities as hashable (spike 0001 P-B: without it pyright and mypy disagree on `{order}`).
4. **Equality and hashing - runtime (provisional working rule).** Set without an implementation or
   use cases; spike 9.4 (#5) confirms or changes it, tracked in #54. Until then:
   - Two snapshots are equal when they hold the same values - columns and loaded relations,
     including what is loaded and what is not. The hash is the entity type plus the primary key
     (equal snapshots have the same key, so the contract holds).
   - Boundaries: `==` and `hash()` on a ref raise `UnloadedReference` (a ref holds no values). The
     hash of a new entity with an `identity` primary key, whose ID exists only after commit,
     raises `UsageError`. A chain view compares its latest state with `==`; its hash is the
     primary key, so it does not change while the chain runs. `==` and `hash()` through a moved
     alias raise `MovedSnapshotAccess`, like every other read through it.
   - Known concerns: because the load state is compared, `Order.stub(...)` and a snapshot with
     loaded relations can be unequal although they hold the same values; and a new entity with an
     `identity` primary key cannot be a set member or dict key before commit.
5. `@value`, `@event` and `@dto` stay decorators (constructors, ordering and class access work
   through `dataclass_transform` on a decorator).

## Consequences
- One construct declares an entity, and one constructor creates it, as for events and values.
- `ref`, `where`, `stub` and `set` are reserved field names. Both checkers reject a field named
  `set` (F2; the other names are untested); class creation rejects all of them at runtime.
- `Order.stub(...)` keywords are not type-checked (a "same fields, all optional" signature cannot be
  derived from the constructor) - open, #50.
- Owned children created without the parent key (4.7 `Order.items.add(Item(sku=..., ...))`) are a
  type error while the FK field is a required parameter - the rule for the parent key is open, #49.
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
