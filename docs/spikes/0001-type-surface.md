# Spike 0001: Type surface under pyright and mypy

- Design section: 9.1 "Type stub spike (top priority)" - "The whole syntax of §4 depends on this.
  Without an implementation, run the pass and fail files of §11.8 through pyright and mypy with
  stubs alone."
- Issue: #2
- Date: 2026-11-25
- Code: `spikes/0001-type-surface/` (throwaway; raw output in `results/`, git-ignored)

## Question
Does the syntax of design section 4 type-check as the design promises, under **both** pyright
(strict) and mypy (`--strict`), with stub-only code (signatures, no behaviour)? Section 4 opens
with: "the type surface (`Col[T]` in §4.2, constructor types, embedded paths) is a hypothesis
until confirmed by the type stub spike (§9)".

General rule for every item: a positive line *holds* when both checkers accept it with no error
and `assert_type` pins the type the design states. A negative line *holds* when both checkers
reject it **for the stated reason** (the message is read, the rule/code recorded). The domain
code (`Order`, `Wallet`, use cases) is written as in section 4; where the stubs need a construct
the design does not show (a base class, a different annotation), the item is at best *partly*
and the deviation is named. Neither the domain code nor the pass/fail files may use `cast`,
`Any` or `# type: ignore`; the library stubs may not use `Any` in any position that a checked
line flows through (an `Any` there would make a negative line pass for the wrong reason).
Where the two checkers disagree, that is recorded as a finding, not resolved.

**0. Prerequisite (not on the issue checklist, but every item rests on it).** Section 4.2
declares `@entity(table="orders", aggregate_root=True) class Order:` with no base class, and the
rest of section 4 uses `Order.new(...)`, `Order.ref(id)`, `Order.where(...)`, `Order.stub(...)`
and `order.set(...)`.
- Holds if, with the class decorator alone, both checkers see these members with the expected
  types (`Order.ref(id)` -> `Order`, `Order.new(...)` -> `Order`, `order.set(...)` -> `Changes`).
- Does not hold if either checker reports them as unknown attributes; then the variant that makes
  them visible (e.g. a base class) is tested and named as a syntax change.

**1. `Col[T]`.** Design 8.2 "Field type surface": "For it to appear as `Column[T]` on the class
and `T` on the instance, the annotation itself must be a descriptor type with an overloaded
`__get__`." Design 4.2: "Collection fields are a read-only `Sequence[Item]` on the instance."
- Holds if `assert_type(Order.status, Column[OrderStatus])`,
  `assert_type(order.status, OrderStatus)`, `assert_type(order.items, Sequence[Item])` (declared
  `Rel[list[Item]]`) and `assert_type(order.user, User)` (declared `Rel[User]`) pass in both,
  and class access `Order.items` offers `.add/.remove/.update/.count()`.

**2. Constructor.** Design 8.2 "Creation syntax and constructor types", step 1: "The
descriptor's `__set__(self, instance: Never, value: T)`: type checkers take constructor parameter
types from the value of `__set__`, and assignment may be blocked by the instance type mismatch."
Step 2: "Typed creation functions in a generated real Python module." Step 3: runtime checks
only. Design 4.2: "A missing required field is the most common mistake, so it must be caught
statically."
- (a) The constructor synthesised through `dataclass_transform` takes each parameter type from
  the `value` type of `__set__` (not the descriptor type `Col[T]`).
- (b) `order.status = OrderStatus.PAID` is rejected in both checkers.
- (c) The creation syntax is the classmethod `Order.new(...)`, not `Order(...)`: `new` must carry
  the same parameters - `Order.new(number="A-1")` is rejected for the missing `total`, `user_id`,
  `Order.new(number=1, ...)` for the type.
- (d) Fields that must not be required at creation (client-generated `pk`, `version_column`,
  `server_default`, relations) are not required parameters; fields with `default=` are optional.
- Step 1 holds if (a)-(d) hold in both. If not, step 2 is tested (a module in the shape a
  generator would emit, and whether `Order.new` can be typed through it), and the write-up
  records the first step that holds. Step 2 or later is a design change (stop and ask).

**3. Writes.** Design 4.4: "`Order.status.to(v)` - Assign a value (`v` checked against `T` of
`Column[T]`)"; 8.2 "Write syntax": "snapshots remain immutable at the type level too".
- Holds if `order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now))` and
  `Order.items.add(item)` pass, and `Order.status.to(123)`, `order.status = ...` and
  `order.items.append(item)` are each rejected in both checkers for the stated reason.

**4. Embedded paths and value-object operations.** Design 4.4: "The types of embedded paths
(`Order.total.amount`) and value object increments (`Wallet.balance.add(Decimal)`) are a spike
task. If that fails, replace them with a path helper (`Order.total.path(Money.amount)`)."
Section 4.5 and 4.12 make `Wallet.balance` a `Money` (`wallet.balance < order.total`,
`Wallet.stub(balance=Money(...))`) and increment it with a `Decimal`
(`Wallet.balance.add(-order.total.amount)`).
- Holds if, with `total: Col[Money] = embedded(...)`, `assert_type(Order.total.amount,
  Column[Decimal])` passes and `Wallet.balance.add(Decimal("1"))` passes while
  `Wallet.balance.add("1")` is rejected, in both.
- If not, the path helper is tested: holds if `Order.total.path(Money.amount)` is
  `Column[Decimal]` and a field that does not belong to `Money` is rejected.

**5. `bind`.** Design 4.5: "`bind(*args: P.args, **kwargs: P.kwargs)` of `Usecase[P]` has the
same signature as `pay`. A ref is an entity at the type level, and parameters injected by the
runner (`Now`, `Actor`, `RequestId`) have the default `INJECTED`, so they can be omitted."
- Holds if `pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid))` passes (no `now`),
  `pay.bind(order=oid, ...)` (a UUID) and `pay.bind(ordr=..., ...)` are rejected, a missing
  required argument is rejected, `INJECTED` type-checks as the default of a `Now` parameter whose
  direct call takes a `datetime` (4.12: `pay(order, wallet, now=datetime(...))`), and the
  parameter types written as `Annotated` PEP 695 aliases (`PayableOrder`) are the entity type.

**6. `chain`.** Design 4.6: "`chain(*snapshots)` is typed with TypeVarTuple, so the returned
`order` and `wallet` appear as `Order` and `Wallet` respectively."
- Holds if in `with chain(order, wallet) as (c, o2, w2):` `o2` is `Order` and `w2` is `Wallet`,
  the same-name rebinding `as (c, order, wallet)` of 4.6 passes, `c.run(apply_coupon, order,
  coupon)` and `c.run(pay, order, wallet, now)` pass while `c.run(apply_coupon, coupon, order)`
  is rejected, and `c.changes` is `Changes`.

**7. `StepResult` and Finders.** Design 4.6: "`+` between steps is a type error. A step call
result (`StepResult`) has no `+`." Design 4.3: "Finder arguments are checked against the column
type." (`by_number = Finder(Order.number)  # orders.by_number("A-1") -> Order`).
- Holds if `apply_coupon(o, c) + pay(o, w)` is rejected while `Changes + Changes` passes, and
  `orders.by_number("A-1")` is `Order` while `orders.by_number(42)` is rejected.

**8. Section 11.8 codes.** The `pass_composition` / `fail_misuse` files of 11.8 are run through
`tools/typetests.py`; the real `[pyright rule, mypy code]` of each of the eight misuse lines is
pinned. The codes printed in 11.8 are expectations only.

## Setup
- Python 3.14.7 (`uv run python -V`), pyright 1.1.414 (`uv run pyright --version`), mypy 2.4.1
  compiled (`uv run mypy --version`). `dev` dependency group only; no database.
- Configuration from `pyproject.toml`: pyright `strict = [..., "spikes"]`, `pythonVersion =
  "3.14"`; mypy `strict = true`, and the commands add `--strict`.
- Branch `docs/spike-0001-type-surface` cut from `origin/develop` at `1770be6`.
- Library stubs are `.pyi` files: mypy `--strict` rejects `...` bodies in a `.py` module
  (`[empty-body]`, seen in step H), and a `.pyi` is what "stubs alone" means in design 9.1.

## Method
Everything is run from the repository root on branch `docs/spike-0001-type-surface`, with the
`dev` dependency group only (no new dependency), and pyright/mypy configured by `pyproject.toml`
(pyright `strict` covers `spikes/`; mypy `--strict`).

Layout of `spikes/0001-type-surface/` (no `__init__.py`; sibling modules are imported by plain
name - whether both checkers resolve that is checked first, step H):
- library stubs: modules with signatures only (bodies `...`), one per variant where a variant is
  needed (e.g. decorator-only entity vs. base class; `Never`-instance `__set__` vs. frozen).
- domain modules: `Money`, `Order`, `Item`, `User`, `Wallet`, `Coupon`, `OrderPaid`, the
  repositories and the use cases `pay`, `apply_coupon`, `checkout`, transcribed from sections
  4.2-4.6.
- `probe_*.py`: one per item, with `reveal_type` lines (what each checker infers) and the
  positive/negative lines of the item.
- `pass_*.py` / `fail_*.py`: the final pinned files, including the transcriptions of 11.8.

The files sit in three directories, each self-contained (modules import only siblings):
`harness/` (step H), `round1/` (items 0-8 and the follow-ups F1-F3) and `round2/` (P-A, P-B, P-C
and the variance probes after the maintainer's decisions). Library stubs are `lib_*.pyi`, the
transcribed domain is `domain*.py`, probes are `probe_<item>_*.py`, pinned files `pass_*` /
`fail_*`.

**Renaming after the runs.** The files were first written flat in `spikes/0001-type-surface/` with
other names and moved into this layout after both reproductions; names in this write-up, including
the Reproduction sections, are the new ones. Every file was checked by both checkers before and
after the move: the diagnostics are identical (same counts, codes and messages) except for the
module names inside the messages. Raw output in `results/` keeps the names of the run (for example
`results/probe_2_ctor-*.txt` belongs to `round1/probe_2_constructor.py`). Old -> new:

| Old | New | Old | New |
|---|---|---|---|
| `plat.pyi` | `round1/lib_design.pyi` | `harness_lib.pyi` | `harness/lib_harness.pyi` |
| `plat_variants.pyi` | `round1/lib_ctor_variants.pyi` | `lib_query_s3.pyi` | `round2/lib_query_root.pyi` |
| `plat_embedded.pyi` | `round1/lib_embedded_variants.pyi` | `lib_hash.pyi` | `round2/lib_eq_hash.pyi` |
| `plat_owner.pyi` | `round1/lib_owner.pyi` | `shop_final.py` | `round2/domain_final.py` |
| `shop.py` | `round1/domain.py` | `shop_final_declared.py` | `round2/domain_final_declared.py` |
| `pass_surface.py` / `fail_surface.py` | `round1/pass_items.py` / `fail_items.py` | `probe_pa_s3.py` | `round2/probe_pa_query_root.py` |
| `probe_0_base.py` | `round1/probe_0_base_class.py` | `probe_pa_s3b.py` | `round2/probe_pa_followup.py` |
| `probe_2_ctor.py` | `round1/probe_2_constructor.py` | `probe_pb_hash.py` | `round2/probe_pb_eq_hash.py` |
| `probe_2_variants.py` | `round1/probe_2_ctor_variants.py` | `probe_f2_misc.py` | `round1/probe_f2_corners.py` |

Every other file kept its name and moved into `harness/`, `round1/` or `round2/`.

Steps:
- **H. Harness.** A no-behaviour stub module plus a minimal `pass_harness.py` / `fail_harness.py`
  that import it; run `uv run python -m tools.typetests spikes/0001-type-surface/harness/pass_harness.py
  spikes/0001-type-surface/harness/fail_harness.py` and confirm both checkers resolve the sibling import
  (an unresolved import must show up as an error, so `fail_harness.py` contains one deliberate
  error and the harness must report it under both checkers).
- **Probes.** For each item 0-7 in order:
  `uv run pyright spikes/0001-type-surface/round1/<probe>` and
  `uv run mypy --strict --show-error-codes --no-incremental spikes/0001-type-surface/round1/<probe>`;
  the output is saved under `results/` and the relevant lines are quoted below. Library and
  domain modules are always passed to both checkers as well, because `tools/typetests.py` judges
  only the files it is given: an error inside an imported module would otherwise go unseen.
- **Pinning.** `uv run python -m tools.typetests <library and domain modules> <pass/fail files>`
  must end with `0 problem(s)`; `fail_misuse.py` carries the codes actually observed.
- **Fallbacks** are tested only after the design form is shown not to hold, and each is reported
  as a deviation with its own verdict.

## Observations
All raw output is in `spikes/0001-type-surface/results/` (git-ignored); every claim below is also
pinned in a `pass_*` / `fail_*` file, so one command re-checks all of them:

```bash
D=spikes/0001-type-surface
uv run python -m tools.typetests \
  $D/round1/lib_design.pyi $D/round1/lib_embedded_variants.pyi $D/round1/domain.py \
  $D/harness/pass_harness.py $D/harness/fail_harness.py \
  $D/round1/pass_items.py $D/round1/fail_items.py \
  $D/round1/pass_embedded.py $D/round1/fail_embedded.py \
  $D/round1/pass_composition.py $D/round1/fail_misuse.py
# -> typetests: 0 problem(s) in 11 file(s)
```

Code under `spikes/0001-type-surface/` (round 1 in `round1/`, step H in `harness/`):
| File | What it is |
|---|---|
| `lib_design.pyi` | Library stub: `Col`/`Rel` descriptors, `Column`/`Relation`, field specifiers, `entity` (decorator, design form) and `Entity` (base class variant), `Changes`/`StepResult`, `Usecase`/`Step`/`usecase`/`step`, `chain`, `Finder`/`Repository`, `App` |
| `lib_ctor_variants.pyi` | Item 2 alternatives: `__set__` absent / `instance: Never` / `instance: object`; frozen and non-frozen bases |
| `lib_embedded_variants.pyi` | Item 4 alternatives: `PCol` with `path`/`at`, `Emb` (class access is the value class), `Value` base, `ACol` with a declared delta type |
| `lib_owner.pyi`, `lib_delta.pyi` | Follow-ups F1 (owner-typed column) and F3 (delta type through a Protocol) |
| `domain.py` | Sections 4.2-4.6 transcribed (Money, User, Order, Item, Wallet, Coupon, OrderPaid, OrderExpired, OrderSummary, OrderRepo, WalletRepo, `pay`, `apply_coupon`, `checkout`) |
| `probe_<item>_*.py` | `reveal_type` and positive/negative lines per item, run directly through both checkers |
| `pass_items.py` / `fail_items.py` | Items 0-3, 5-7 pinned |
| `pass_embedded.py` / `fail_embedded.py` | Item 4 pinned |
| `pass_composition.py` / `fail_misuse.py` | Section 11.8 transcribed |
| `lib_harness.pyi`, `pass_harness.py`, `fail_harness.py`, `fail_harness_unresolved.py` | Step H |

Signatures chosen where the design leaves them open (all in `lib_design.pyi`):
- `Col[T]`: `__get__` overloaded on `instance: None` -> `Column[T]` / `instance: object` -> `T`;
  `__set__(self, instance: Never, value: T)`.
- `Rel[T]`: four `__get__` overloads; the first two are self-typed on `Rel[list[E]]` and return
  `Relation[E]` (class) / `Sequence[E]` (instance), the last two return `RelColumn[T]` / `T`.
- Field specifiers listed in `dataclass_transform(kw_only_default=True, field_specifiers=...)`.
  Fields that must not be constructor parameters declare `init: Literal[False] = False` (`pk`,
  `version_column`, `many_to_one`, `one_to_many`, and the `column(server_default=...)` overload).
- `Entity.new` is `@classmethod def new[**P, S](cls: Callable[P, S], *args: P.args,
  **kwargs: P.kwargs) -> S`, i.e. it takes the parameters of the synthesised `__init__`.
- `INJECTED: Never`; `type Now = Annotated[datetime, _Injected]`.
- `Usecase[**P]` has `bind(*P.args, **P.kwargs) -> Bound` and `__call__(...) -> StepResult`;
  `Changes.__add__` exists, `StepResult` has no `__add__`.
- `chain[*Ts](*snapshots: *Ts) -> ChainBlock[*Ts]`, whose `__enter__` returns
  `tuple[Chain, *Ts]`; `Chain.run[**P](fn: Callable[P, StepResult], /, *P.args, **P.kwargs)`.
- `Finder[T](column: Column[T])` is a descriptor; read through an instance of `Repository[E]` it
  returns `BoundFinder[E, T]` (`__call__(value: T) -> E`). The entity type comes from the
  repository, not from the column (a `Column[T]` in this stub does not know its owner - a stub
  choice, not a type-system limit: see follow-up F1).
- No `Any`, `cast` or `# type: ignore` in `domain.py` and the pass/fail files. In the library stubs:
  no `Any` except the gradual bound of `query[F: Callable[..., object]]` (`lib_design.pyi`; mypy
  `--disallow-any-explicit` reports it, and the reproduction checked that it does not reach a
  checked line); two library-side suppressions, both findings (L1, L2 below).

### H. Harness
- Sibling imports in a directory whose name has hyphens resolve in both checkers:
  `pass_harness.py` (`assert_type(make_box(), Box[int])`) passes, `fail_harness.py` fails as
  marked. An unresolved import is reported by both (`reportMissingImports` - plus
  `reportUnknownVariableType` on a `from` import - and `import-not-found`), so a broken import
  cannot pass silently.
- `tools/typetests.py` judges only the files it is given; errors in an imported module that is not
  passed are not reported. Every run above passes the library and domain modules explicitly.

### Item 0 - members of a decorator-only entity
`probe_0_decorator.py`, `fail_items.py::item0`. With `@entity(table=..., aggregate_root=True)
class Order:` the synthesised constructor exists (`Order(number="A-1")` is `Order` in both) but:

| Line | pyright | mypy |
|---|---|---|
| `Order.new(...)`, `Order.ref(oid)`, `Order.where(...)`, `Order.stub()` | `Cannot access attribute "new" for class "type[Order]"` (`reportAttributeAccessIssue`, + `reportUnknownMemberType`) | `"type[Order]" has no attribute "new"` (`attr-defined`) |
| `order.set(...)` | `Cannot access attribute "set" for class "Order"` (+ `reportUnknownMemberType`) | `"Order" has no attribute "set"` |

Without checker plugins (pyright has none), a `dataclass_transform` class decorator can only make
a checker synthesise `__init__` (and comparison methods); both checkers ignore its return type, so
it cannot add other members. (A plain class decorator's return type is honoured by pyright - the
class then stops being a class - and ignored by mypy; reproduction discrepancy 10.) With a base class carrying the members and
`dataclass_transform` (`class Order(Entity, table="orders", aggregate_root=True):`,
`probe_0_base_class.py`) all five resolve in both: `new` -> `Order`, `ref` -> `Order`, `where` ->
`SetChange`, `stub` -> `Order`, `set` -> `Changes`. Keeping the design's decorator for the options
on top of the base class (`@options(...) class Order2(Entity, ...)`) also works.

Side finding: `Order.where(Order.status == OrderStatus.PENDING)` is an error in strict mode in
both checkers when `Column` has no `__eq__` of its own (pyright `reportUnnecessaryComparison`
"Condition will always evaluate to False", mypy `comparison-overlap`). See L2.

### Item 1 - `Col[T]`
`probe_1_col.py`, `pass_items.py::item1`. Revealed types, identical in both checkers:

| Expression | pyright | mypy |
|---|---|---|
| `Order.status` | `Column[OrderStatus]` | `lib_design.Column[domain.OrderStatus]` |
| `order.status` | `OrderStatus` | `domain.OrderStatus` |
| `Order.items` / `order.items` | `Relation[Item]` / `Sequence[Item]` | same |
| `Order.user` / `order.user` | `RelColumn[User]` / `User` | same |
| `Order.total` / `order.total` | `Column[Money]` / `Money` | same |
| `OrderPaid.order_id` / `paid.order_id` | `Column[Id[Order]]` / `Id[Order]` | same |

All `assert_type` lines of `pass_items.py::item1` pass in both, including
`Order.paid_with` -> `Column[PaymentMethod | None]` (the `column(default=None)` specifier is
solved from the annotation) and `Order.items.add/remove/update/count()`.

### Item 2 - constructor
`probe_2_constructor.py`, `probe_2_ctor_variants.py`, `pass_items.py::item2`, `fail_items.py::item2`.

(a) The synthesised constructor takes the `value` type of `__set__`. pyright:
`Order.__init__` is `(self: Order, *, number: str, status: OrderStatus = OrderStatus.PENDING,
paid_with: PaymentMethod | None = None, paid_at: datetime | None = None, total: Money, user_id:
Id[User]) -> None`; mypy reveals the same parameters. Variant table (`probe_2_ctor_variants.py`,
field `a: <descriptor>[int]`; the unused helper `field()` in `lib_ctor_variants.pyi` is itself an
error in both checkers - `reportInvalidTypeVarUse` / `type-var` - without effect on the table):

| Descriptor | constructor parameter (both) | `x.a = 1` pyright | `x.a = 1` mypy |
|---|---|---|---|
| no `__set__`, plain | `a: ColNoSet[int]` (wrong) | error, wrong reason (`"Literal[1]" is not assignable to "ColNoSet[int]"`) | no error |
| no `__set__`, frozen | `a: ColNoSet[int]` (wrong) | same as above | `Property "a" ... is read-only` (`misc`) |
| `__set__(instance: object, ...)` | `a: int` | **no error** | **no error** |
| `__set__(instance: Never, ...)`, plain | `a: int` | `reportAttributeAccessIssue` | `arg-type` |
| `__set__(instance: Never, ...)`, frozen | `a: int` | `reportAttributeAccessIssue` ("... Never" and "Attribute "a" is read-only") | `misc` **and** `arg-type` |

So the constructor type comes from `__set__`'s value, and the assignment is blocked by the
`Never` instance, not by `frozen`; `frozen` alone cannot give constructor types.

(b) `order.status = OrderStatus.PAID`: pyright `Cannot assign to attribute "status" for class
"Order" / Argument of type "Order" cannot be assigned to parameter "instance" of type "Never" in
function "__set__"` (`reportAttributeAccessIssue`); mypy `Argument 1 to "__set__" of "Col" has
incompatible type "Order"; expected "Never"` (`arg-type`).

(c) `Order.new` carries the same signature. pyright reveals `Order.new` as `(*, number: str,
status: OrderStatus = OrderStatus.PENDING, ..., total: Money, user_id: Id[User]) -> Order`; mypy
`def (*, number: str, status: domain.OrderStatus =, ..., total: domain.Money, user_id:
lib_design.Id[domain.User]) -> domain.Order`. Rejections:

| Line | pyright | mypy |
|---|---|---|
| `Order.new(number="A-1")` | `Arguments missing for parameters "total", "user_id"` (`reportCallIssue`) | `Missing named argument "total" for "new" of "Entity"` + same for `user_id` (`call-arg`) |
| `Order.new(number=1, ...)` | `reportArgumentType` | `arg-type` |
| `Order.new("A-1", money, uid)` | `Expected 0 positional arguments` (`reportCallIssue`) | `Too many positional arguments` and `Missing named argument` for `total`, `user_id` (`call-arg`), plus per-position `arg-type` that maps positions onto the keyword-only parameters (`Argument 2 ... expected "OrderStatus"`) |
| `OrderPaid(order_id=..., user_id=..., total=...)` | `Argument missing for parameter "paid_at"` | `Missing named argument "paid_at"` |

(d) `init: Literal[False]` in the field specifier is honoured by both: passing `version=3`,
`id=oid`, `created_at=now` or `items=[]` is `No parameter named "..."` (`reportCallIssue`) /
`Unexpected keyword argument "..." for "new" of "Entity"` (`call-arg`). Fields with `default=`
are optional.

Observations (accepted by both, pinned in `pass_items.py::item2`): `Order(number="A-1",
total=money, user_id=uid)` type-checks as well as `Order.new(...)`, so the type level does not
enforce the single creation syntax; `Order.stub(statuss=1)` type-checks (with
`stub(**fields: object)` the stub's keywords are not checked; a "same fields, all optional"
signature cannot be derived from `P`).

### Item 3 - writes
`probe_3_writes.py`, `pass_items.py::item3`, `fail_items.py::item3`.
`order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now))` -> `Changes`,
`order.set(Order.items.add(item))` -> `Changes`, `Order.paid_at.to(None)` -> `Op` in both.

| Line | pyright | mypy |
|---|---|---|
| `Order.status.to(123)` | `Argument of type "Literal[123]" cannot be assigned to parameter "value" of type "OrderStatus"` (`reportArgumentType`) | `Argument 1 to "to" of "Column" has incompatible type "int"; expected "OrderStatus"` (`arg-type`) |
| `order.status = ...` | as item 2 (b) | as item 2 (b) |
| `order.items.append(item)` | `Cannot access attribute "append" for class "Sequence[Item]"` (`reportAttributeAccessIssue`) and `Type of "append" is unknown` (`reportUnknownMemberType`) | `"Sequence[Item]" has no attribute "append"` (`attr-defined`) |
| `Order.number.to(None)`, `Order.status.to("paid")` | `reportArgumentType` | `arg-type` |

Observation: `order.set(Wallet.balance.to(money))` is accepted by both - the entity an operation
belongs to is not checked (`Column[T]` does not carry its owner). The design does not claim this
check.

### Item 4 - embedded paths and value-object operations
`probe_4_embedded.py`, `pass_embedded.py`, `fail_embedded.py`; `lib_embedded_variants.pyi`.

(a) The design form with `total: Col[Money] = embedded(prefix="total_")`:

| Line | pyright | mypy |
|---|---|---|
| `Order.total.amount` | `Cannot access attribute "amount" for class "Column[Money]"` (`reportAttributeAccessIssue`, + `reportUnknownMemberType`) | `"Column[Money]" has no attribute "amount"` (`attr-defined`) |
| `Wallet.balance.add(Decimal("1"))` | `Argument of type "Decimal" cannot be assigned to parameter "delta" of type "Money"` (`reportArgumentType`) | `Argument 1 to "add" of "Column" has incompatible type "Decimal"; expected "Money"` (`arg-type`) |
| `Check(lambda: Order.total.amount >= 0)` (4.2 `Meta`) | as the first line, + `reportUnknownLambdaType` | as the first line |

The same three errors appear when `domain.py` is first transcribed verbatim (4.2 `Meta.checks`, 4.3
`select(..., total=Order.total.amount)`, 4.5 `Wallet.balance.add(-order.total.amount)`); those
three lines were then moved to the probe and marked in `domain.py`.

(b) Path helpers on a `PathColumn[T]` (class access of `PCol[T]`):
- b1, the design's fallback `Order.total.path(Money.amount)` with `def path[U](self, field: U) ->
  Column[U]`: `Money.amount` on the class is plain `Decimal` in both checkers (a dataclass field
  read through the class), so the result is `Column[Decimal]` - but anything is accepted:
  `OrderB.total.path(Coupon.rate)` is `Column[Column[Decimal]]` with no error in either checker.
  A typed path from an attribute reference would need value-class fields declared as `Col[...]`,
  and even then `Column[T]` does not know its owner, so the field's class is still unchecked.
- b2, a getter over the value type, `def at[U](self, getter: Callable[[T], U]) -> Column[U]`:
  `OrderB.total.at(lambda m: m.amount)` is `Column[Decimal]` in both (the lambda parameter is
  inferred as `Money` from context); `at(lambda m: m.rate)` is rejected (`Cannot access attribute
  "rate" for class "Money"`, `reportAttributeAccessIssue` + `reportUnknownMemberType` +
  `reportUnknownLambdaType` / `"Money" has no attribute "rate"`, `attr-defined`);
  `.at(lambda m: m.amount).add(Decimal("-1"))` is `Op` and `.add("1")` is rejected
  (`reportArgumentType` / `arg-type`).

- b2 follow-up (`probe_4_check.py`), the examples of ADR-0004:
  `Check(lambda: OrderB.total.at(lambda m: m.amount) >= Decimal(0))` and
  `wallet.set(WalletB.balance.at(lambda m: m.amount).add(-order.total.amount))` pass in both;
  `... >= 0` (an `int` literal, as design 4.2 writes it) is rejected in both (`Operator ">=" not
  supported for types "Column[Decimal]" and "Literal[0]"`, `reportOperatorIssue` +
  `reportUnknownLambdaType` / `Unsupported
  operand types for >= ("Column[Decimal]" and "int")`, `operator`) because the stub's comparisons
  take exactly `T` (L5).

(c) An embedded descriptor `Emb[V]` whose class access returns `type[V]`, with value-class fields
declared `PCol[...]`: `OrderC.total.amount` is `PathColumn[Decimal]` and `order.total.amount` is
`Decimal` in both - the design's literal syntax - but `OrderC.total.to(...)` is rejected
(`type[MoneyC]` has no `to`) unless the value class inherits a `Value` base with a `to`
classmethod (c'), and the class leaks: `OrderC.total(amount=Decimal("1"), currency="KRW")`
type-checks as constructing a `MoneyC`.

(d) A declared delta type (`class Money(Additive[Decimal])`, `def add_delta[D](self:
AddColumn[Additive[D]], delta: D)`) does not bind in either checker: pyright `Type parameter
"T@AddColumn" is contravariant, but "MoneyD" is not a supertype of "Additive[D@add_delta]"`
(`reportAttributeAccessIssue`); mypy `Invalid self argument "AddColumn[MoneyD]" to attribute
function "add_delta"` (`misc`) and `expected "Never"` (`arg-type`). `Column[T]` is inferred
**contravariant** (PEP 695 variance inference; `T` occurs only in parameters), and an invariant
`T` would not match a subclass either, so `Wallet.balance.add(Decimal)` cannot take its delta type
from `Money` generically.

### Item 5 - `bind`
`probe_5_bind.py`, `pass_items.py::item5`, `fail_items.py::item5`.
- `pay` is `Usecase[(order: Order, wallet: Wallet, now: datetime = INJECTED)]` (pyright) /
  `lib_design.Usecase[[order: domain.Order, wallet: domain.Wallet, now: datetime.datetime =]]` (mypy): the
  `Annotated` PEP 695 aliases (`PayableOrder`, `ChargeableWallet`, `Now`) resolve to the entity /
  `datetime`. `INJECTED` is `Never` in both and is accepted as the default.
- `Order.ref(oid)`, `Order.ref(oid, expected_version=3)` -> `Order`; `wallets.by_user(uid)` ->
  `Wallet`; `pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid))` -> `Bound`;
  `pay(order, wallet, now=now)` -> `StepResult`. The options form `@usecase(isolation=...,
  retry=Retry(...), timeout="2s")` keeps the same `Usecase[...]` type.

| Line | pyright | mypy |
|---|---|---|
| `pay.bind(order=oid, ...)` | `"UUID" is not assignable to "Order"` (`reportArgumentType`) | `Argument "order" to "bind" of "Usecase" has incompatible type "UUID"; expected "Order"` (`arg-type`) |
| `pay.bind(ordr=..., ...)` | `No parameter named "ordr"` and `Argument missing for parameter "order"` (both `reportCallIssue`) | `Unexpected keyword argument "ordr" for "bind" of "Usecase"; did you mean "order"?` (`call-arg`) |
| `pay.bind(order=...)` (no wallet) | `reportCallIssue` | `call-arg` |
| swapped `order`/`wallet`, `now="now"` | `reportArgumentType` | `arg-type` |
| `@usecase` on a function returning `int` | `reportArgumentType` | `arg-type` |

Observations (accepted by both, pinned in `pass_items.py::item5`): `bind(..., now=now)` (an
injected parameter can be passed by the caller), positional `bind(Order.ref(oid),
wallets.by_user(uid))`, and a direct `pay(order, wallet)` without `now` (the default is
`INJECTED`, so supplying the value outside a runner is a runtime concern). Because `INJECTED` is
`Never`, it is also accepted as the default of a parameter that is not injected (`def f(order:
Order = INJECTED)` type-checks and `f.bind()` is `Bound`; found by the reproduction) - only seal
can reject that.

### Item 6 - `chain`
`probe_6_chain.py`, `pass_items.py::item6`, `fail_items.py::item6`.
`chain(order, wallet)` is `ChainBlock[Order, Wallet]`; inside `with ... as (c, o2, w2)`: `c` is
`Chain`, `o2` is `Order`, `w2` is `Wallet` in both. Three snapshots give `tuple[Order, Wallet,
Coupon]`. The same-name rebinding of 4.6 (`as (c, order, wallet)`, also in `domain.checkout`)
passes. `c.run(apply_coupon, o2, coupon)`, `c.run(pay, o2, w2, now)`, `c.run(pay, o2, w2)` and
`c.run(pay, order=o2, wallet=w2)` pass; `c.changes` is `Changes`.

| Line | pyright | mypy |
|---|---|---|
| `c.run(apply_coupon, coupon, o2)` | `reportArgumentType` (twice) | `Argument 2 to "run" of "Chain" has incompatible type "Coupon"; expected "Order"` and the same for argument 3 (`arg-type`, twice) |
| `c.run(apply_coupon, o2)` | `Argument missing for parameter "coupon"` (`reportCallIssue`) | `Missing positional argument "coupon"` (`call-arg`) |
| `c.run(apply_coupon, o2, coupon, 1)` | `Expected 2 positional arguments` (`reportCallIssue`) | `Too many arguments for "run" of "Chain"` (`call-arg`) |
| `as (c4, x)` for two snapshots | `Tuple size mismatch; expected 2 but received 3` (`reportAssignmentType`) | `Too many values to unpack (2 expected, 3 provided)` (`misc`) |
| `as (c5, wallet, order)` (swapped rebinding of typed parameters) | `reportAssignmentType` (twice) | `assignment` (twice) |

### Item 7 - `StepResult` and Finders
`probe_7_step_finder.py`, `pass_items.py::item7`, `fail_items.py::item7`.
- `apply_coupon(order, coupon)` -> `StepResult`; `order.set() + wallet.set()` -> `Changes`.
- `apply_coupon(o, c) + pay(o, w)`: pyright `Operator "+" not supported for types "StepResult"
  and "StepResult"` (`reportOperatorIssue`, + `reportUnusedExpression` because the line is a
  bare expression); mypy `Unsupported left operand type for + ("StepResult")` (`operator`).
  `Changes + StepResult` is rejected the same way.
- `OrderRepo.by_number` is `Finder[str]`, `orders.by_number` is `BoundFinder[Order, str]`,
  `orders.by_number("A-1")` is `Order`. `orders.by_number(42)`: `"Literal[42]" is not assignable
  to "str"` (`reportArgumentType`) / `Argument 1 to "__call__" of "BoundFinder" has incompatible
  type "int"; expected "str"` (`arg-type`). `wallets.by_user(oid)` with an `Id[Order]` and with a
  plain `UUID` are rejected the same way (`Id[E]` is inferred covariant).

### Item 8 - section 11.8
`pass_composition.py` and `fail_misuse.py` are the 11.8 snippets with only the scaffolding added
(an `async def` with typed parameters, `app = App(dsn=...)`, `w = wallets.by_user(uid)`). Both
pass `tools/typetests.py`. Observed codes against the codes printed in 11.8:

| Line | 11.8 expected | pyright observed | mypy observed |
|---|---|---|---|
| `pay.bind(order=oid, wallet=w)` | `reportArgumentType, arg-type` | `reportArgumentType` | `arg-type` |
| `pay.bind(ordr=Order.ref(oid), wallet=w)` | `reportCallIssue, call-arg` | `reportCallIssue` (x2) | `call-arg` |
| `order.set(Order.status.to(123))` | `reportArgumentType, arg-type` | `reportArgumentType` | `arg-type` |
| `order.status = OrderStatus.PAID` | `reportAttributeAccessIssue, misc` | `reportAttributeAccessIssue` | **`arg-type`** |
| `order.items.append(item)` | `reportAttributeAccessIssue, attr-defined` | `reportAttributeAccessIssue` **+ `reportUnknownMemberType`** | `attr-defined` |
| `apply_coupon(o, c) + pay(o, w)` | `reportOperatorIssue, operator` | `reportOperatorIssue` **+ `reportUnusedExpression`** | `operator` |
| `orders.by_number(42)` | `reportArgumentType, arg-type` | `reportArgumentType` | `arg-type` |
| `Order.new(number="A-1")` | `reportCallIssue, call-arg` | `reportCallIssue` | `call-arg` |

Pinned markers (as in `fail_misuse.py`):

```python
pay.bind(order=oid, wallet=w)                 # expect-error[reportArgumentType, arg-type]
pay.bind(ordr=Order.ref(oid), wallet=w)       # expect-error[reportCallIssue, call-arg]
order.set(Order.status.to(123))               # expect-error[reportArgumentType, arg-type]
order.status = OrderStatus.PAID               # expect-error[reportAttributeAccessIssue, arg-type]
order.items.append(item)                      # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]
apply_coupon(o, c) + pay(o, w)                # expect-error[reportOperatorIssue, reportUnusedExpression, operator]
orders.by_number(42)                          # expect-error[reportArgumentType, arg-type]
Order.new(number="A-1")                       # expect-error[reportCallIssue, call-arg]
```

The extra pyright code on the `+` line depends on how the line is written: as a bare expression
it is `reportUnusedExpression`, as `_ = ...` it is `reportUnknownVariableType`. 11.8 must pin the
code for the exact form it uses.

The immutability line would carry mypy `misc` (as 11.8 expected) only if the entity base were
also `frozen`, and then mypy reports `misc` **and** `arg-type` on it (item 2 variant table).

### Library-side and tooling findings
These do not change what users see, but the real implementation inherits them.
- **L1** Field specifiers without a value (`column()` without `default`, `pk()`, `fk()`,
  `embedded()`, the relation specifiers) are `def column[T](...) -> Col[T]`: `T` occurs only in
  the return type and is solved from the field annotation. Both checkers solve it correctly at the
  use site, but pyright strict rejects the declaration itself (`TypeVar "T" appears only once in
  generic function signature`, `reportInvalidTypeVarUse`); mypy accepts it. The stub disables that
  one rule at file level (`# pyright: reportInvalidTypeVarUse=false`). The alternative,
  `-> Col[Any]` (SQLAlchemy's `mapped_column`), would stop `status: Col[OrderStatus] =
  column(default=123)` from being an error (with `Col[T]` it is rejected: pyright
  `reportAssignmentType`, mypy `arg-type`).
- **L2** `Column.__eq__` / `__ne__` returning a predicate are incompatible overrides of `object`
  in both checkers (`reportIncompatibleMethodOverride` / `override`) and need `# type: ignore
  [override]` in the library (SQLAlchemy does the same). Without them `Order.status == x` is a
  `bool` in user code and strict mode reports the comparison as always false (item 0).
- **L3** ruff `ASYNC109` flags the run option `timeout` on an async `App.run`; the stub omits it.
- **L4** `Column[T]` is contravariant by PEP 695 inference (item 4 d). The library should decide
  the variance of its public generics explicitly rather than inherit what inference picks.
- **L5** The stub's comparison operators take exactly `T` (`Column[T].__ge__(other: T)`), so
  `Column[Decimal] >= 0` is an error; which operand types a numeric column accepts is a library
  decision the design has not made.
- **T1** `ruff format` (line length 100) wraps a statement whose `# expect-error[...]` marker makes
  it long, moving the marker off the line that errors; `tools/typetests.py` then reports both
  lines. The fail files here fence the misuse block with `# fmt: off` / `# fmt: on`.
- Design 4.2's `Meta` lists (`indexes = [...]`, `checks = [...]`) trip ruff `RUF012` (mutable
  class attribute) in the project's lint configuration; tuples do not.

### Follow-up after review (F1-F3)
Run after the architect review of the first verdict (which asked for facts on an owner-typed
column and on several untested corners) and, for F3, taken from the reproduction and rerun.
Commands as for the probes; raw output in `results/probe_f1_owner-*.txt`,
`results/probe_f2_misc-*.txt`.

**F1 - a column that carries its owner** (`lib_owner.pyi`, `probe_f1_owner.py`). `Col[T].__get__`
is overloaded as `def __get__[O](self, instance: None, owner: type[O]) -> Column[O, T]`; operations
return `Op[O]`; `Entity.set(self, *ops: Op[Self])`; value-class fields are declared `Col[...]`
(`@value class Money: amount: Col[Decimal]`); `Column[O, T].path[U](self, field: Column[T, U]) ->
Column[O, U]`; `Finder[E, T](column: Column[E, T])`. Identical in both checkers:

| Expression | Result |
|---|---|
| `Order.number` / `order.number` | `Column[Order, str]` / `str` |
| `Money.amount` / `m.amount` | `Column[Money, Decimal]` / `Decimal`; `Money(amount=Decimal("1"), currency="KRW")` constructs |
| `Order.total.path(Money.amount)` | `Column[Order, Decimal]`; `>= Decimal(0)` is `Pred` |
| `Wallet.balance.path(Money.amount).add(Decimal("-1"))` | `Op[Wallet]` |
| `OrderRepo.by_number` / `orders.by_number("A-1")` | `Finder[Order, str]` (the design's own comment) / `Order` |
| `Order.total.path(Rate.amount)`, `Order.total.path(Wallet.balance)`, `Order.number.path(Money.amount)` | rejected: pyright `reportArgumentType` (`Type parameter "O@Column" is covariant, but "Rate" is not a subtype of "Money"`), mypy `arg-type` - mypy's message names the instance type (`incompatible type "Decimal"; expected "Column[Money, Never]"`) |
| `order.set(Wallet.balance.to(m))`, `order.set(Wallet.balance.path(Money.amount).add(...))` | rejected: `"Op[Wallet]" is not assignable to "Op[Order]"` (`reportArgumentType`) / `Argument 1 to "set" of "Entity" has incompatible type "Op[Wallet]"; expected "Op[Order]"` (`arg-type`) |
| `Finder(Wallet.balance)` in `OrderRepo(Repository[Order])`, read as `orders.wrong` | rejected at the read: `reportAttributeAccessIssue` / `arg-type` |
| `Order.total.path(Money.amount).add("1")` | rejected: `reportArgumentType` / `arg-type` |

The reproduction found the same independently (its discrepancies 1 and 3, `rp_probe_owner*.py`).
So the design's own fallback `Order.total.path(Money.amount)` can reject misuse, and the owner of
an operation (item 3 observation) and of a Finder's column can be checked - at the price of a
two-parameter `Column[O, T]` and `Col[...]` annotations in value classes.

**F2 - corners** (`probe_f2_corners.py`):

| Line | pyright | mypy |
|---|---|---|
| 4.7 child creation without the parent key, `Order.items.add(Item.new(price=money, position=1))` | `Argument missing for parameter "order_id"` (`reportCallIssue`) + `reportUnknownArgumentType` | `Missing named argument "order_id"` (`call-arg`) |
| `order == o2` / `hash(order)` | `bool` / `int` | `bool` / `int` |
| `{order}` | `Type "Order" is not hashable` (`reportUnhashable`) | **accepted** |
| `class K(Entity, table=..., kw_only=False)`, `frozen=True` | `Incorrect keyword arguments for __init_subclass__` (`reportGeneralTypeIssues`) + `No parameter named "kw_only"` (`reportCallIssue`) | `Unexpected keyword argument "kw_only" for "__init_subclass__"` (`call-arg`) |
| a field named `set` / `new` | `"set" overrides method of same name in class "Entity" with incompatible type "Col[int]"` (`reportIncompatibleMethodOverride`) | `Incompatible types in assignment ... base class "Entity" defined the type as "def set(...)"` (`assignment`) |
| getter on a nullable embedded value, `spare: PCol[Money \| None]`, `.at(lambda m: m.amount)` | `"amount" is not a known attribute of "None"` (`reportOptionalMemberAccess`); reveals `Column[Decimal]` | `Item "None" of "Money \| None" has no attribute "amount"` (`union-attr`); reveals `Column[Decimal \| Any]` (error recovery) |
| `Order.ref(uid)` with an `Id[User]` | accepted (`Order`) | accepted |

The `{order}` line is the first place in this spike where the checkers disagree on accept/reject
(round 2 found more: P-A S2/S3 and `Column`'s variance): an entity with the synthesised `__eq__` and no `frozen` is unhashable for pyright, hashable for
mypy. Section 4.7's `Item.new(...)` without `order_id` is a type error under these stubs: owned
children need a rule for the parent key.

**F3 - `Wallet.balance.add(Decimal)` through a structural self-type** (`round1/lib_delta.pyi`,
`round1/probe_f3_delta.py`: the round-1 reproducer's `rp_delta.pyi` / `rp_probe_delta.py`, copied
into the spike unchanged apart from the module name and rerun with the same output). `Column[T]`
exposes a property `_of -> T` and overloads `add[D](self: _HasDelta[D], n: D)` / `add(self, n: T)`,
where `_HasDelta[D]` is a Protocol with a property `_of -> Additive[D]` and the value class declares
`class Money(Additive[Decimal])`. Both checkers: `Wallet.balance.add(Decimal("-1"))` is `Op`,
`Wallet.count.add(1)` is `Op`, `Wallet.balance.add("1")` is rejected (pyright `reportCallIssue` +
`reportArgumentType`, mypy `call-overload`). `Wallet.balance.add(m)` with a whole `Money` is also
accepted (the second overload). The cost is a declared base on the value class; the Protocol route
avoids the variance problem of item 4 (d).

### Round 2 - the surface after the maintainer's decisions (P-A, P-B, P-C)
After round 1 the maintainer decided: entities use the `Entity` base (ADR-0003) with the plain
constructor `Order(...)` as the only creation syntax (no `new`) and `frozen_default=True`; embedded
paths use owner-typed columns `Column[O, T]` with `Order.total.path(Money.amount)` and value fields
declared `Col[...]` (ADR-0004); no `Additive` base. Round 2 checks that combination.

New files under `spikes/0001-type-surface/round2/`:

| File | What it is |
|---|---|
| `lib_final.pyi` | Library stub of the decided surface: `Col[T].__get__[O]` -> `Column[O, T]`; `Op[O]`, `Pred[O]` (comparisons on a column), `Relation[O, E]` (`add`/`remove` -> `Op[O]`, `update(item: E, *ops: Op[E])` -> `Op[O]`), `RelColumn[O, T]`; `Entity` with `dataclass_transform(kw_only_default=True, frozen_default=True, ...)`, `ref`, `where(*preds: Pred[Self]) -> SetChange[Self]`, `stub`, `set(*ops: Op[Self])` and no `new`; `SetChange[O].set(*ops: Op[O])` and `emit_each(event, **fields: OwnedExpr[O])` (`**fields: Expr` in the runs before the `emit_each` follow-up); `Column.path[U](field: Column[T, U]) -> Column[O, U]`; `Finder[E, T](column: Column[E, T])`. Queries in two shapes: `Select[R]` with `where(*preds: Pred[object])` (S1, the design's 4.3 shape) and `SelectFrom[R, O]` / `select_from(dto, **columns: OwnedExpr[O])` with `join(Relation[O, E]) -> SelectFrom[R, O \| E]` and `where(*preds: Pred[O])` (S2) |
| `lib_query_root.pyi` | S3: `select_root(dto, root: type[O], **columns: OwnedExpr[O]) -> Query[R, O]`, same `join`/`where` as S2 |
| `domain_final.py` | Sections 4.2-4.6 transcribed onto `lib_final.pyi`. Deviations: the `Entity` base, `Money` fields `amount: Col[Decimal]`, `currency: Col[str] = column(default="KRW")`, `Order.total.path(Money.amount)` in `Meta.checks` and the 4.3 query, `Wallet.balance.path(Money.amount).add(-order.total.amount)` in 4.5, and `>= Decimal(0)` in the check (L5 open) |
| `probe_pa_owner.py`, `probe_pa_query_root.py` | P-A |
| `lib_eq_hash.pyi`, `probe_pb_eq_hash.py` | P-B |
| `pass_final.py`, `fail_final.py` | P-C: 11.8 and the round-2 lines pinned |

Commands: as for the probes (`uv run pyright <file>`, `uv run mypy --strict --show-error-codes
--no-incremental <file>`), raw output in `results/pa-*.txt`, `results/pa-s3-*.txt`,
`results/pb-*.txt`, `results/pc-*.txt`; and the round-2 pinning command:

```bash
D=spikes/0001-type-surface
uv run python -m tools.typetests \
  $D/round2/lib_final.pyi $D/round2/domain_final.py $D/round2/pass_final.py $D/round2/fail_final.py
# -> typetests: 0 problem(s) in 4 file(s)
```

**P-A - owner types propagated** (`probe_pa_owner.py`). Revealed types, identical in both
checkers: `Order.status` `Column[Order, OrderStatus]`; `Order.items` `Relation[Order, Item]`;
`Order.status == OrderStatus.PAID` `Pred[Order]`; `Order.items.add(item)` and
`Order.items.update(item, Item.position.to(2))` `Op[Order]`; `order.set(Order.items.update(...))`
`Changes`; `Order.where(Order.status == OrderStatus.PENDING, Order.created_at < now)` and
`... .set(Order.status.to(OrderStatus.EXPIRED))` `SetChange[Order]`;
`Order.total.path(Money.amount)` `Column[Order, Decimal]`; `orders.summaries(user_id=uid)`
`Select[OrderSummary]`. Misuse, each rejected by both:

| Line | pyright | mypy |
|---|---|---|
| `Order.items.update(item, Order.status.to(PAID))` (parent op in a child update) | `"Op[Order]" is not assignable to "Op[Item]"` (`reportArgumentType`) | `Argument 2 to "update" of "Relation" has incompatible type "Op[Order]"; expected "Op[Item]"` (`arg-type`) |
| `Order.items.update(item, Wallet.balance.to(m))` | `"Op[Wallet]" is not assignable to "Op[Item]"` | same shape (`arg-type`) |
| `wallet.set(Order.items.add(item))` | `"Op[Order]" is not assignable to "Op[Wallet]"` | `Argument 1 to "set" of "Entity" ... expected "Op[Wallet]"` |
| `Order.where(Wallet.user_id == uid)` | `"Pred[Wallet]" is not assignable to "Pred[Order]"` | `Argument 1 to "where" of "Entity" ... expected "Pred[Order]"` |
| `Order.where(...).set(Wallet.balance.to(m))` | `"Op[Wallet]" is not assignable to "Op[Order]"` | `Argument 1 to "set" of "SetChange" ... expected "Op[Order]"` |
| `Order.items.add(coupon)` | `"Coupon" is not assignable to "Item"` | `Argument 1 to "add" of "Relation" has incompatible type "Coupon"; expected "Item"` |

All six are `reportArgumentType` / `arg-type`.

**P-A follow-up - `emit_each`** (`round2/probe_pa_emit_each.py`, `results/pa-emit-each-*.txt`;
added after the round-2 reproduction and not independently reproduced). With
`SetChange[O].emit_each(event, /, **fields: OwnedExpr[O])` in `lib_final.pyi` and
`lib_final_declared.pyi` (it took `**fields: Expr` before), `Order.where(...).set(...)
.emit_each(OrderExpired, order_id=Order.id)` and `.emit_each(OrderPaid, order_id=Order.id,
user_id=Order.user_id)` are `SetChange[Order]` in both checkers. `.emit_each(OrderExpired,
order_id=Wallet.id)` and `.emit_each(OrderPaid, order_id=Order.id, user_id=Wallet.user_id)` are
rejected: pyright `"Column[Wallet, Id[Wallet]]" is not assignable to "OwnedExpr[Order]"`
(`reportArgumentType`), mypy `Argument "order_id" to "emit_each" of "SetChange" has incompatible
type "Id[Wallet]"; expected "OwnedExpr[Order]"` (`arg-type`; mypy names the instance type, as in
F1). The owner is fixed by the receiver, so `emit_each` is a receiver-fixed place; the lines are
pinned in `pass_final*.py` / `fail_final*.py`, and both round-2 pinning commands still end with `0
problem(s) in 4 file(s)`.

**P-A - queries: a checker disagreement** (`probe_pa_owner.py::queries`, `probe_pa_query_root.py`). The
4.3 query `summaries` (`select(...).join(Order.items, outer=True).where(Order.user_id ==
user_id)...`) type-checks in both in the S1 shape (`domain_final.py`); the S2/S3 probes use reduced
queries, and the full 4.3 query does not fit the S2/S3 stubs (`count(...)` is not an owned
expression; no `order_by`/`limit` there - found by the round-2 reproduction). Whether a predicate over an entity that is not
in the query is rejected:

| Shape | pyright | mypy |
|---|---|---|
| S1 (`where(*preds: Pred[object])`): `select(OrderSummary, id=Order.id).where(Wallet.user_id == uid)` | accepted | accepted |
| S2, one entity then a join: `select_from(OrderSummary, id=Order.id, number=Order.number)` is `SelectFrom[OrderSummary, Order]`, `.join(Order.items)` is `SelectFrom[OrderSummary, Order \| Item]`, then `.where(Wallet.user_id == uid)` | rejected: `"Pred[Wallet]" is not assignable to "Pred[Order \| Item]"` (`reportArgumentType`) | rejected: `expected "Pred[Order \| Item]"` (`arg-type`) |
| S2, columns of two entities in one call: `select_from(OrderSummary, id=Order.id, item_count=Item.id)` | `SelectFrom[OrderSummary, Order \| Item]`; `.where(Wallet.user_id == uid)` **rejected** | `SelectFrom[OrderSummary, Entity]` (the type variable is solved to the common base); `.where(Wallet.user_id == uid)` **accepted** |
| S3, explicit root: `select_root(OrderSummary, Order, id=Order.id, item=Item.id)` (an `Item` column before any join) | accepted; `Query[OrderSummary, Order \| Item]` | accepted; `Query[OrderSummary, Entity]` |
| S3, that two-entity query, then `.where(Wallet.user_id == uid)` (`probe_pa_followup.py`) | **rejected** (`reportArgumentType`) | **accepted** |
| S3, `select_root(..., Order, ...).join(Order.items).where(Wallet.user_id == uid)` | rejected (`reportArgumentType`) | rejected (`arg-type`) |

When the owner has to be inferred from several arguments of one call, pyright solves it to the
union `Order | Item` and mypy to the common base `Entity`, so the same line is rejected by one
checker and accepted by the other (S2, and S3 once a second entity's column is given). An explicit
root does not pin the owner (S3). A query that starts from one entity and widens only through
`.join(...)` is agreed by both. The round-2 reproduction measured what mypy's solution depends on:
kwargs, `*args`, separate parameters, a bound and an explicit `root: type[O]` all give pyright's
union and mypy's join; an invariant owner parameter makes both reject the two-entity call itself
(mypy `misc`, `Cannot infer value of type parameter`); a declared target type
(`w: Cov[A | B] = ...`) lets mypy solve the union from context; with no common base but `object`,
mypy solves `object`. The
design's query shape (S1) is not broken by owner types, but its predicates are not owner-checked.
**Variance of `Column`'s `T` - a checker disagreement** (`probe_pa_followup.py::variance`, found by the
round-2 reproduction and rerun): in `lib_final.pyi`, `x: Column[Order, int] = c` with `c:
Column[Order, object]` is rejected by pyright (`Type parameter "T@Column" is invariant`,
`reportAssignmentType`) and accepted by mypy, which infers `T` contravariant (as round 1's
one-parameter `Column[T]`, L4). The reproducer's own stub, with the variance declared explicitly
(old-style type variables: owner covariant, value invariant), shows no disagreement.

**P-B - entity equality and hashing** (`lib_eq_hash.pyi`, `probe_pb_eq_hash.py`). Five bases, a field
`a: int`; for each: `{e}`, `{e: 1}`, `takes(e)` with `def takes(h: Hashable)`, `hash(e)`.

| Variant | pyright `{e}` / `{e: 1}` / `Hashable` | mypy `{e}` / `{e: 1}` / `Hashable` | `hash(e)` (both) |
|---|---|---|---|
| V1 synthesised `__eq__`, not frozen | rejected / rejected / rejected (`Set entry must be hashable`, `Dictionary key must be hashable`, `reportUnhashable`; `reportArgumentType`) | accepted / accepted / accepted | accepted |
| V2 synthesised `__eq__` + `frozen_default=True` | accepted | accepted | accepted |
| V3 `eq_default=False` | accepted | accepted | accepted |
| V4 synthesised `__eq__` + `__hash__: ClassVar[None]` | rejected / rejected / rejected | accepted / accepted / **rejected** (`Argument 1 to "takes" has incompatible type "V4"; expected "Hashable"`, `arg-type`) | accepted |
| V5 `eq_default=False` + `__hash__: ClassVar[None]` | rejected / rejected / rejected | accepted / accepted / **rejected** | accepted |

mypy never rejects a set or dict literal of an unhashable entity; it rejects only a `Hashable`
parameter, and only when `__hash__` is declared `None`. Only V2 and V3 make both checkers accept
all four lines; only V2 keeps the synthesised `__eq__`. (`lib_eq_hash.pyi` line 5, the helper
`field()`, is itself an error in pyright - `reportInvalidTypeVarUse` - with no effect on the table.
V4 and V5 declare `__hash__: ClassVar[None]` with `# type: ignore[assignment]` in `lib_eq_hash.pyi`,
as typeshed does for unhashable builtins: the declaration is the variant under test.)

**P-C - the decided combination** (`domain_final.py`, `pass_final.py`, `fail_final.py`). Sections
4.2-4.6 type-check on `lib_final.pyi` with no error in either checker, including `wallet.balance <
order.total` (ordering of the frozen `@value` `Money` with `Col[...]` fields),
`Money(Decimal("1000"))` positionally, `Wallet.balance.path(Money.amount).add(-order.total.amount)`,
`Check(lambda: Order.total.path(Money.amount) >= Decimal(0))`, `Finder(Order.number)` as
`Finder[Order, str]`, and `{order}` as `set[Order]`. `pass_final.py` holds the 11.8
`pass_composition` (with `Order(number="A-1", total=money, user_id=uid)` and
`assert_type(Order.status, Column[Order, OrderStatus])`) and the round-2 positive lines;
`fail_final.py` the eight 11.8 lines plus the owner-propagation lines and `Order.new(...)`. The
pinning command above ends with `0 problem(s) in 4 file(s)`. Codes of the lines whose syntax or
codes differ from round 1 (only the immutability line's codes changed; `Order(...)` keeps the codes
of round 1's `Order.new(...)` line, and `Order.new(...)` is a new line):

| Line | pyright | mypy |
|---|---|---|
| `order.status = OrderStatus.PAID` | `reportAttributeAccessIssue` (message: `... "Never" in function "__set__"` and `Attribute "status" is read-only`) | `Property "status" defined in "Order" is read-only` (`misc`) **and** `Argument 1 to "__set__" of "Col" ...; expected "Never"` (`arg-type`) |
| `Order(number="A-1")` | `reportCallIssue` | `call-arg` |
| `Order.new(number="A-1")` | `reportAttributeAccessIssue` + `reportUnknownMemberType` | `"type[Order]" has no attribute "new"` (`attr-defined`) |

The other seven 11.8 lines keep their round-1 codes.

## Verdict

The round-1 verdict below is kept as written before the maintainer's decisions (ADR statuses and
open choices as they were then); the round-2 verdict after it supersedes it.

Rule from the Question: an item that holds only with a construct the design does not show is at
best *partly*. Items 2, 3 and 5 use `Order.new`, `order.set` and `Order.ref`, which exist only on
the `Entity` base of item 0; they are marked "holds on ADR-0003" accordingly.

| # | Item | pyright | mypy | Verdict |
|---|---|---|---|---|
| 0 | Entity members with `@entity` only | not visible | not visible | **Does not hold.** Holds with an `Entity` base class (ADR-0003, Proposed) |
| 1 | `Col[T]` class/instance access, `Rel` -> `Sequence` | holds | holds | **Holds** |
| 2 | Constructor via `__set__(instance: Never, value: T)` | holds | holds | **Holds at step 1 on ADR-0003's base** (partly by the rule above); steps 2-3 not needed. Not covered by section 4.2-4.6: 4.7's `Item.new(...)` without `order_id` is rejected (F2) |
| 3 | Writes `to`, assignment, `append` | holds | holds | **Holds** (`order.set` on ADR-0003's base); the immutability code is mypy `arg-type`, not `misc` |
| 4 | `Order.total.amount`, `Wallet.balance.add(Decimal)` | does not hold | does not hold | **Does not hold as written** (`total: Col[Money]`, one-parameter `Column[T]`). Typed alternatives that hold in both, each with a declaration cost: `path(Money.amount)` with owner-typed columns (F1); a getter `.at(lambda m: m.amount)` (b2); `Wallet.balance.add(Decimal)` through `Additive[Decimal]` (F3); literal `Order.total.amount` via `Emb` + `Value` base, with a leaking class (c'). `path(Money.amount)` on the one-parameter `Column[T]`: **partly** (accepts any argument) |
| 5 | `bind` with ParamSpec, `INJECTED` | holds | holds | **Holds** (`Order.ref` on ADR-0003's base) |
| 6 | `chain` with TypeVarTuple, `c.run` | holds | holds | **Holds** |
| 7 | `StepResult + StepResult`, Finder argument | holds | holds | **Holds** |
| 8 | 11.8 codes | pinned | pinned | Three of eight lines differ from 11.8 (table in item 8) |

On every checked line of items 0-8 the two checkers agreed on accept/reject; they differ in the
codes they attach and in pyright strict's extra `reportUnknown*` / `reportUnusedExpression` codes.
The disagreements found later are listed under the round-2 verdict.

Consequences for the design (proposals; the maintainer decides):
- **Item 0 changes the section 4 syntax.** `@entity(table=...) class Order:` cannot expose
  `new`/`ref`/`where`/`stub`/`set`; entities need a base class. Draft: ADR-0003 (Proposed); it
  also has to choose between `Order.new(...)` and the plain `Order(...)` as the one creation
  syntax, because both type-check.
- **Item 4 changes the section 4 syntax or declarations.** With `total: Col[Money]` and a
  one-parameter `Column[T]`, neither `Order.total.amount` nor `Wallet.balance.add(Decimal)` types.
  Four typed alternatives exist (row 4); ADR-0004 (Proposed) chose the getter before F1 and F3 were
  known and is on hold until the maintainer picks a direction.
- **Section 8.2 "Creation syntax"**: step 1 holds; the type level accepts `Order(...)` next to
  `Order.new(...)`, does not check `Order.stub(...)` keywords, and does not express "the parent
  sets the key" for owned children (4.7).
- **Section 4.5 / 8.2 "Call syntax"**: `INJECTED` (`Never`) is accepted as any parameter's default
  and an injected parameter can be passed to `bind`; both need a stated rule (seal / runtime).
- **Section 11.8**: replace the expected codes by the pinned ones (item 8).
- **Entity equality/hashing** needs a decision; the checkers disagree on the default (F2).

### Round 2 verdict - the decided surface
| Item | pyright | mypy | Verdict |
|---|---|---|---|
| Entity members on the `Entity` base, creation `Order(...)`, no `new` (ADR-0003) | holds | holds | **Holds** |
| Constructor step 1 with `frozen_default=True` (P-C) | holds | holds | **Holds**; the immutability line is `reportAttributeAccessIssue` / `misc` + `arg-type` |
| Embedded paths `Order.total.path(Money.amount)`, increments `Wallet.balance.path(Money.amount).add(...)`, value fields `Col[...]` (F1, P-C) | holds | holds | **Holds** |
| Owner checks where the owner is fixed by the receiver: `order.set`, `Entity.where`, `SetChange.set`, `SetChange.emit_each`, relation operations, Finders of `Repository[E]`, `path` (F1, P-A, P-A follow-up) | holds | holds | **Holds** |
| Owner checks where the owner must be solved from columns of several entities in one call (query shapes S2, S3; a one-entity query widened by `.join` is agreed) | union `Order \| Item` | common base `Entity` | **Does not hold** - the checkers disagree; the maintainer decided these places are not checked by types: queries (`select`/`join`/`where`) are validated when their description is built (seal: #52), `Profile`, `Load`, `Index`, `Check` and `@invariant(fields=...)` by seal; the 4.3 query shape (S1) stays |
| Entity hashability with `frozen_default=True` (P-B) | hashable | hashable | **Holds** - both checkers agree only for frozen or `eq_default=False` |

**After the round-2 reproduction - declared variance** (`lib_final_declared.pyi` with
`domain_final_declared.py`, `pass_final_declared.py`, `fail_final_declared.py`, copies of the round-2
files with only the import changed; `probe_variance_declared.py`; `results/declared-*.txt`).
`Column` declared with old-style type variables, owner covariant and value invariant
(`class Column(OwnedExpr[_O_co], Generic[_O_co, _T])`): the round-2 pinning set ends with `0
problem(s) in 4 file(s)` on it, and `x: Column[Order, int] = c` with `c: Column[Order, object]` is
rejected by both checkers (pyright `reportAssignmentType`, mypy `assignment`), where the inferred
`lib_final.Column` is rejected by pyright only. **L6**: PEP 695 syntax cannot declare variance, and
the project's ruff configuration flags the old-style declaration (`UP046`); the copy carries `# noqa:
UP046` with the reason, and the real library needs a per-file decision.
A second way keeps PEP 695 syntax (`lib_variance.pyi`, `probe_variance_pep695.py`,
`results/variance-pep695-*.txt`; checked by assigning `C[Order, object]` and `C[Order, bool]` to
`C[Order, int]`):

| PEP 695 `Column[O, T]` shape | pyright | mypy |
|---|---|---|
| `to(value: T)` and `path(field: Column[T, U])` (as `lib_final.pyi`) | invariant | contravariant |
| the same plus a member returning `T` (`@property def value_type(self) -> T`) | invariant | invariant |
| `to(value: T)` only, no `path` | contravariant | contravariant |

The disagreement comes from `path`'s reference to `Column[T, U]`; a member returning `T` makes
both checkers infer invariance. Either way the variance then rests on the members present, so a
type test has to pin it.

**The final surface** is `lib_final.pyi` with `Column`'s variance fixed (owner covariant, value
invariant), as in `lib_final_declared.pyi`; the method of fixing it is left to the implementation
(ADR-0004). The declared-variance and PEP 695 variance probes were run after the round-2
reproduction and are not independently reproduced; the reproducer's own round-2 stub declared the
same variance and reached the same verdicts.

Checker disagreements found in the whole spike: entity hashability without `frozen` (F2, P-B),
the owner solved from several entities' columns in one call (P-A S2, S3), and the variance of
`Column`'s `T` when it is left to inference (P-A, `lib_final.pyi`).

Not covered by the claims above (from the round-2 reproduction): `Check(...)` takes
`Callable[[], Pred[object]]`, so a check over another entity's column in `Order.Meta` is accepted
by both checkers (another place for seal); 4.7's `Load.when(..., match=Wallet.user_id ==
Order.user_id)` is rejected by both (`reportOperatorIssue` / `operator`) because `Column.__eq__`
takes only `T`, not another column (related to L5); and a receiver-fixed query shape
(`select_root(dto, Order).columns(...)`, the open `.columns(...)` item) held in both checkers on
the reproducer's own stub, which is not part of this spike (git-ignored `results/repro2/`; #52
tests that shape).

Left open by the maintainer, tracked as issues: the seal rule for `INJECTED` defaults (#48), the
parent key of owned children (4.7, #49), typed `stub` keywords (#50), the operand types of column
comparisons (L5, #51), and type-checking query predicates (including a `.columns(...)` shape, not
tested here; #52).

## Reproduction

### Round 1

- **Who:** type-reviewer (independent; worked from this write-up, the code under
  `spikes/0001-type-surface/` and design sections 4, 8.2, 9.1, 11.8). It reproduced the first
  version of this write-up (before the follow-up F1-F3 and the corrections it triggered).
- **Date:** 2026-11-25
- **Tools observed:** Python 3.14.7, pyright 1.1.414, mypy 2.4.1 (compiled: yes). Branch
  `docs/spike-0001-type-surface` at `1770be6`, with the spike files untracked. Configuration from
  `pyproject.toml` (pyright `strict` includes `spikes`; mypy `strict = true`).

**What was run**
1. The pinning command from Observations, unchanged: `typetests: 0 problem(s) in 11 file(s)`, as
   stated.
2. Every probe and `fail_harness_unresolved.py` through `uv run pyright <file>` and
   `uv run mypy --strict --show-error-codes --no-incremental <file>` (output in
   `results/repro/rerun/`), compared line by line with Observations.
3. Each library and domain module alone through both checkers: `lib_design.pyi`, `lib_embedded_variants.pyi`,
   `lib_ctor_variants.pyi`, `lib_harness.pyi`, `domain.py`.
4. An `Any` audit: mypy `--disallow-any-expr --disallow-any-explicit --disallow-any-decorated`
   over `domain.py` and the spike's `pass_*` files, plus a grep for `Any`, `cast` and suppressions.
5. Its own stubs and probes written from the design text, in `spikes/0001-type-surface/results/
   repro/` (git-ignored): an independent library stub and 4.2-4.6 domain (`rp_lib.pyi`,
   `rp_shop.py`, with deliberately different choices - `step` returning `Callable[P, StepResult]`,
   a bound Finder as `Callable[[T], E]`), `pass_rp_items.py` / `fail_rp_items.py` (items 0-3, 5-7,
   plus a sanity line that `assert_type` rejects an `Any`), `fail_rp_misuse.py` (11.8 with the
   pinned codes), `fail_rp_misuse_118.py` (11.8 with the codes printed in 11.8),
   decorator-only alternatives (`rp_entity_variants.pyi`, `rp_probe_0_2.py`, `rp_probe_0b.py`),
   owner-carrying columns (`rp_owner*.pyi`, `rp_probe_owner*.py`), a delta type through a Protocol
   (`rp_delta.pyi`, `rp_probe_delta.py`), L1/L2/L5 and the getter without the file-level pragma
   (`rp_misc.pyi`, `rp_probe_misc.py`), `INJECTED` on a non-injected parameter and a missing
   sibling import (`rp_probe_5h.py`), and the `[empty-body]` claim (`rp_emptybody.py`). Its own
   set gives `0 problem(s) in 7 file(s)`; `fail_rp_misuse_118.py` gives exactly the 3 problems of
   item 8.

**Observations.** Every revealed type and quoted message reproduced word for word, except the
omissions listed below (7-9). No probe found a line one checker accepts and the other rejects
(its only checker disagreement is outside the spike's stubs: a plain class decorator, 10). The
spike's imports are real (`lib_design` and `domain` resolve nowhere else; revealed types name them). No
`Any` reaches a checked line: under `--disallow-any-expr` the only `Any` is the `@query` decorator
expression, and `orders.summaries` keeps its signature and rejects wrong arguments. Every `fail_*`
marker fails for the stated reason. Its independent stubs reach the same verdicts for items 0-3
and 5-7 and the same 11.8 codes; L1, L2, L5, the getter (whose lambda parameter is really `Money`
in mypy) and `[empty-body]` reproduce.

| # | Reproducer | Reason |
|---|---|---|
| H | agree | Sibling imports resolve; an unresolved import is reported by both (a `from` import adds `reportUnknownVariableType`; mypy then treats the name as `Any`, so the import line is the only signal). |
| 0 | agree | Both checkers ignore a `dataclass_transform` decorator's return type; a wrapper return and a wrapper with `__getattr__` leave `.new` unknown in both. The base class exposes all five members. |
| 1 | agree | Independently reproduced, including `Rel[list[E]]` -> `Sequence[E]` and `Rel[User]` -> `User`. |
| 2 | agree | Step 1 holds on the base class; `init: Literal[False]` honoured by both; the `Order(...)` and `Order.stub(statuss=1)` observations reproduce. |
| 3 | agree (verdict) | All lines and codes reproduce; the explanation of the owner observation is wrong (1). |
| 4 | **partly agree** | Agrees that `Order.total.amount` with `total: Col[Money]` does not hold and that the getter holds. Disagrees that `Wallet.balance.add(Decimal)` cannot be typed and that `path(Money.amount)` cannot reject misuse: both can, in both checkers (2-4). |
| 5 | agree | Reproduced; unnamed cost: `INJECTED` is accepted as the default of a non-injected parameter. |
| 6 | agree | Reproduced; a 4-tuple chain also keeps every type. |
| 7 | agree (verdict) | Reproduced; `Finder[Order, str]` can come from the column (1). |
| 8 | agree | Same eight codes; the same three lines differ from 11.8. |

**Discrepancies it reported** (each now addressed in Observations or F1-F3):
1. "`Column[T]` does not know its owner" is a stub choice: `__get__[O](self, obj: None, cls:
   type[O]) -> OColumn[O, T]` carries it; `OrderRepo.by_number` becomes `OFinder[Order, str]` and
   `order.set(Wallet.note.to("x"))` is rejected (`reportArgumentType` / `arg-type`). mypy's
   message then names the instance type when the context is incompatible.
2. Item 4 (d) and L4: the delta type can be read generically through a Protocol self-type (F3).
3. Item 4 b1: `path(Money.amount)` rejects misuse with owner-carrying columns and `Col[...]`
   value fields (F1).
4. The consequence "Neither `Order.total.amount` nor `Wallet.balance.add(Decimal)` can be typed"
   was overstated ((c') and 2).
5. `lib_ctor_variants.pyi` has an error in both checkers (unused `field()`), not mentioned; no effect
   on the item 2 table.
6. "No `Any` in the library stubs" was not literally true (`query[F: Callable[..., object]]`); it
   does not leak.
7. Item 0 table omitted pyright's `reportUnknownMemberType` on the `order.set(...)` row.
8. Item 2 table: mypy also reports the missing named arguments on the positional line, and its
   per-position `arg-type` messages map positions onto the keyword-only parameters.
9. Item 6: mypy reports `arg-type` twice on the swapped line; the `>= 0` follow-up also gets
   pyright `reportUnknownLambdaType`.
10. Item 0 nuance: a plain (non-`dataclass_transform`) class decorator's return type is honoured
    by pyright (`B` becomes `Ops[B]`) and ignored by mypy.
11. Item 8: the extra pyright code on the `+` line depends on the statement form.
12. L1: `column(default=123)` on `Col[OrderStatus]` is rejected with pyright
    `reportAssignmentType`, mypy `arg-type`.

**Summary (reproducer):** agrees with H, 0, 1, 2, 3, 5, 6, 7, 8; partly agrees with 4, in the
direction of *more* holding than the first write-up claimed. Items 0-3, 5-8 and the 11.8 code
changes can go ahead; the item 4 consequence and ADR-0004 should be re-weighed against 2-4 before
the embedded-path checkbox is ticked. Per the spikes rule, this disagreement goes to the
maintainer: **no design checkbox is ticked by this change until the maintainer decides.**

The follow-up F1-F3 was added after this reproduction; F1 confirms its discrepancies 1 and 3 with
the spike's own files, F3 is its own probe rerun. F2 has not been independently reproduced.

### Round 2

- **Who:** type-reviewer (independent; worked from this write-up, the round-2 files under
  `spikes/0001-type-surface/` and design sections 4, 8.2, 11.8; did not run the spike). Scope: F2,
  P-A (propagation, misuse, S1, S2, S3), P-B, P-C.
- **Date:** 2026-11-25
- **Tools observed:** Python 3.14.7, pyright 1.1.414, mypy 2.4.1 (compiled: yes); branch at
  `1770be6` with the spike files untracked; configuration from `pyproject.toml`.

**What was run**
1. The round-2 pinning command, unchanged: `typetests: 0 problem(s) in 4 file(s)`.
2. Both checkers on `probe_f2_corners.py`, `probe_pa_owner.py`, `probe_pa_query_root.py`, `probe_pb_eq_hash.py`,
   and on `lib_final.pyi`, `lib_query_root.pyi`, `domain_final.py`, `pass_final.py`, `fail_final.py`,
   `lib_eq_hash.pyi` each alone (output in `results/repro2/rerun/`), compared line by line.
3. An `Any` audit (mypy `--disallow-any-expr --disallow-any-explicit --disallow-any-decorated` over
   `domain_final.py`, `pass_final.py`, `probe_pa_owner.py`; grep for `Any`, `cast`, suppressions).
4. Its own files in `spikes/0001-type-surface/results/repro2/` (git-ignored): an independent stub and
   domain (`r2_lib.pyi`, `r2_shop.py`) with deliberately different choices (declared variance,
   a separate children descriptor, `Bulk[O]` set changes, a bound Finder as `Callable[[T], E]`, a
   receiver-fixed query shape S4); `pass_r2.py` / `fail_r2.py` (markers chosen from the reason
   before running, raw output read for every line); `probe_r2_queries.py` (S1-S3);
   `probe_r2_solve.py` (how each checker solves one type variable from several arguments);
   `r2_hash_lib.pyi` / `probe_r2_hash.py` (V1-V5, plus V6 non-frozen with an own `__hash__`, V7 the
   decorator form, a `{[1]}` control); `r2_imm_lib.pyi` / `probe_r2_imm.py` (sources of the
   immutability codes, the nullable getter); probes on the spike's own stubs (S3 R1 solved types,
   the full 4.3 query in S2/S3 shapes, `Column` variance, negative controls). Its own set: `0
   problem(s) in 4 file(s)`.

**Observations.** Every revealed type and quoted message in F2, P-A, P-B and P-C reproduced, except
the points below. No `Any` reaches a checked line (the only one is the `@query` decorator
expression, which does not leak); the round-2 suppressions are the documented L1 pragma and the two
L2 ignores. The independent stub reaches the same verdicts with the same codes. The immutability
codes have separate sources: frozen plus `__set__(instance: Never)` gives mypy `misc` and
`arg-type`, `Never` alone only `arg-type`, frozen alone only `misc`; pyright reports one
`reportAttributeAccessIssue` in every case.

| Part | Reproducer | Reason |
|---|---|---|
| F2 | agree | Every row reproduces; on its own stub the 4.7 child without the parent key, a dataclass keyword and a field named `set` are rejected the same way. Small omissions (1, 9). |
| P-A propagation | agree | Identical reveals in both checkers; pinned with `assert_type` on its own stub. |
| P-A misuse | agree | All six lines `reportArgumentType` / `arg-type` with the quoted messages on both stubs; also `order.set(Wallet.balance.path(...).add(...))`, `Order.total.path(Wallet.balance)` and a Finder over another entity's column. |
| S1 | agree | An unjoined predicate is accepted by both, on both stubs. |
| S2 | agree | The disagreement is real and correctly attributed (union vs join); a one-entity query widened by `.join` is agreed. |
| S3 | **partly agree** | The rows reproduce, but the table hid that S3 has the same pyright/mypy split as S2 once a second entity's column is given (5). |
| P-B V1-V5 | agree | As in the table; `frozen_default=True` on the base is honoured; the `lib_eq_hash.pyi` line-5 error reproduces. |
| P-C | agree | Clean in both; every `fail_final.py` line carries its marker's codes; negative controls (`m < 1`, `Money("1000")`, `>= 0`) are rejected, so the value-object positives are not loose. |
| Round 2 verdict | agree, two wording points | All six rows agree; the S2/S3 row and the "only disagreement" sentences needed precision (2, 7). |

**Discrepancies it reported** (all corrected in the text above):
1. F2 G1: pyright also reports `reportUnknownArgumentType`.
2. The "only disagreement" sentences were no longer true after round 2 (S2, S3, `Column`'s variance).
3. `Column`'s `T`: pyright invariant, mypy contravariant - a checker disagreement on the public
   `Column` of `lib_final.pyi`, not only a change against round 1; its own stub with declared
   variance has none.
4. What mypy's solution in S2 depends on (stub variance, the annotation context) - recorded in P-A.
5. S3: with a reveal, pyright `Query[OrderSummary, Order | Item]`, mypy `Query[OrderSummary,
   Entity]`, and an unjoined `Wallet` predicate on that query is rejected by pyright and accepted by
   mypy; the table showed only agreement.
6. The P-C table title called unchanged codes "changed".
7. "The 4.3 query type-checks in every shape" held only for S1; the S2/S3 stubs cannot express the
   full 4.3 query. No effect on the decision.
8. mypy does not check hashability of set or dict literal entries at all (`{[1]}` is accepted);
   for pyright a non-frozen synthesised-`__eq__` base with its own `__hash__` (V6) is still
   unhashable in subclasses, and the decorator form (V7) behaves like V1.
9. F2 G8: pyright reveals `Column[Decimal]`; mypy's `Any` is error recovery.

Outside the claims: `Check(...)` in `Meta` is not owner-checked; 4.7's `Load.when(match=Wallet.user_id
== Order.user_id)` is rejected by both (`Column.__eq__` takes only `T`); the receiver-fixed S4 shape
held in both on its own stub.

**Summary (reproducer):** agrees with F2, P-A propagation, P-A misuse, S1, S2, P-B V1-V5 and P-C;
partly agrees with S3 (a missing row, in the direction of the S2 disagreement). Nothing changes a
round-2 verdict row. Discrepancy 3 is a second checker disagreement, on the public `Column`, and
goes to the maintainer under the spikes rule along with S2/S3. The two points it raised (5 and 3)
were rerun with the spike's stubs (`probe_pa_followup.py`, `results/pa-s3b-*.txt`) and confirmed.

### Maintainer decisions after the reproductions
2026-11-25 - the maintainer decided the points the reproductions sent back: the S2/S3 checker
disagreement (owners inferred from several arguments are not checked by types; ADR-0004 Decisions
4-5) and the variance disagreement (variance fixed and pinned by type tests; ADR-0004 Decision 3).
ADR-0003 and ADR-0004 were accepted and design 9.1 ticked. The declared-variance and PEP 695
variance probes (`round2/lib_final_declared.pyi`, `round2/probe_variance_*.py`) were run after the
round-2 reproduction and are not independently reproduced.
Afterwards the maintainer placed two entries of ADR-0004's "checked by seal" list by when they can
actually be checked: queries are validated when their description is built (seal: #52), and
`emit_each` is a receiver-fixed place (the P-A follow-up on `emit_each`, run after the round-2
reproduction and not independently reproduced).
