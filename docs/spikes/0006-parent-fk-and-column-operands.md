# Spike 0006: Parent-set foreign keys and column comparison operands

- Design section: 9.6, Phase 1a - "Before the build issues they gate: the type spike for #49 and
  #51" (a follow-up of 9.1, "The whole syntax of §4 depends on this")
- Issue: #49, #51
- Date: 2026-11-26
- Code: `spikes/0006-parent-fk-and-column-operands/` (throwaway; raw output in `results/`,
  git-ignored)

## Question
On 2026-11-25 the maintainer decided two type-surface questions. Each decision comment carries a
probe table from one run outside the repository, not independently reproduced. This spike reruns
both decisions inside the repository, pins them with `tools.typetests` and states whether they
hold under **both** pyright (strict) and mypy (`--strict`) with stub-only code.

**A - parent-set foreign key (#49).** "The foreign key of an owned child is set by the parent, not
passed by the caller. The child declares it with its own field specifier (working name
`parent_fk(lambda: Order)`; the final name is fixed in #9), it is not a constructor parameter, and
`Order.items.add(Item(...))` fills it. A child of a relation that is not `owned` keeps its FK as an
ordinary required constructor parameter (`fk(lambda: Order)`)." The decided specifier:

```python
def parent_fk[T](target: Callable[[], type[object]], /, *, init: Literal[False] = False) -> Col[T]: ...
```

Holds if, with that specifier added to `Entity`'s `field_specifiers`, each of the five lines of the
#49 decision table gets the stated verdict in both checkers, and each rejection carries the stated
code (`reportCallIssue` / `call-arg`):
1. `Item(sku="A", price=Decimal(1))` (FK declared with `parent_fk`) - accepted.
2. `Item(order_id=order.id, sku="A", price=Decimal(1))` - rejected, `order_id` is not a parameter.
3. `Payment(amount=Decimal(1))` (non-owned, FK declared with `fk`) - rejected, `order_id` missing.
4. `order.set(Order.items.add(item))` - accepted.
5. `item.order_id` / `Item.order_id` - `Id[Order]` / `Column[Item, Id[Order]]`.

**B - column comparison operands (#51).** "1. Values: exactly `T`. No numeric widening. 2.
Column-to-column comparisons are allowed directly, through an overload. The two columns must have
the same value type; a difference in nullability only (`T` against `T | None`) is allowed. 3. A
comparison of two columns is a predicate over both owners: `Column[O, T] == Column[O2, T]` is
`Pred[O | O2]`. Places where the receiver fixes the owner (`Order.where(...)`, ADR-0004) therefore
still reject a predicate that mentions another entity's column." The six comparison operators of
`Column` become four overloads each, in this order:

```python
@overload  # type: ignore[override]   (only on __eq__ / __ne__)
def __eq__[O2](self, other: Column[O2, _T], /) -> Pred[_O_co | O2]: ...
@overload
def __eq__[O2](self, other: Column[O2, _T | None], /) -> Pred[_O_co | O2]: ...
@overload
def __eq__[O2, U](self: Column[_O_co, U | None], other: Column[O2, U], /) -> Pred[_O_co | O2]: ...
@overload
def __eq__(self, other: _T, /) -> Pred[_O_co]: ...
```

Holds if every line of the #51 decision table gets the stated verdict in both checkers, with the
stated code on rejections (`reportOperatorIssue` / `operator` for an operand,
`reportArgumentType` / `arg-type` at `Order.where`), and `assert_type` pins the stated result
(`Pred[Order]`, `Pred[Wallet | Order]`, `Pred[Order | Wallet]`).

**Both parts.** The stub itself is clean under both checkers, apart from the two library-side
suppressions spike 0001 already recorded (L1 file-level `reportInvalidTypeVarUse`, L2
`# type: ignore[override]` on `__eq__` / `__ne__`). Spike 0001's round-2 pinned files
(`domain_final_declared.py`, `pass_final_declared.py`, `fail_final_declared.py`), pointed at the
new stub, still end with `0 problem(s)`: the overloads must not change a verdict that is already
decided. The domain, pass and fail files use no `cast`, `Any` or `# type: ignore`.

**Refuted** if any line of either table gets another verdict, another code or another inferred
type in either checker, or the checkers disagree on it. In that case the spike stops and reports to
the maintainer; the design is not edited.

**Observations outside the tables** (recorded, not part of the verdict; a surprise is reported):
- O1 - the variance of `Pred[O]`. It is inferred from an empty body (PEP 695). The rejection at
  `Order.where(...)` depends on it, as `Column`'s did in spike 0001 (L4, L6).
- O2 - a value on the left (`Decimal(0) <= Order.amount`, `0 <= Order.amount`): the reflected
  operator path.
- O3 - embedded paths: 4.2's `Order.total.path(Money.amount) >= Decimal(0)`, a path against a
  column, a path against a path of another entity.
- O4 - the column-as-value fallback (spike 0001, ADR-0004 Consequences): whether mypy reads the
  right-hand column as its value through `Col.__get__`'s instance overload and so picks the value
  overload (`Pred[Order]` instead of `Pred[Order | Wallet]`), in a bare expression and under an
  expected type.
- O5 - `== None` on a nullable and on a non-null column: what each checker infers. Not decided
  here (#9).
- O6 - 4.7's `Load.when(Order.paid_with == PaymentMethod.POINT, match=Wallet.user_id ==
  Order.user_id)`, outside `Annotated` (both checkers) and inside it (pyright only, spike 0002 X1).
- O7 - spike 0002 `probe_accepted.py` item 6 (a child added to one parent with another parent's
  key): not writable for an owned child; still writable for a non-owned one (#60).
- O8 (added during the run, after O6 showed it) - `==` / `!=` with a value of the wrong type.
- O9, O10 (added after the architect review; independently reproduced, Reproduction round 2) - a child's parent key
  changed after creation; ordering on an enum column, and comparisons on an embedded value column
  (O10 corrected after the maintainer's review: the embedded value class itself is ordered).

## Setup
- Python 3.14.7 (`uv run python -V`), pyright 1.1.414 (`uv run pyright --version`), mypy 2.4.1
  compiled (`uv run mypy --version`). `dev` dependency group only; no database.
- Configuration from `pyproject.toml`: pyright `strict = [..., "spikes"]`, `pythonVersion =
  "3.14"`; mypy `strict = true`, and every command adds `--strict`.
- Repository at `567684f` (`origin/develop`), spike files untracked; run first in the primary
  checkout, the pinning commands rerun unchanged in the worktree of branch
  `docs/spike-0006-parent-fk-and-column-operands` (same commit).

## Method
Code under `spikes/0006-parent-fk-and-column-operands/` (call it `$D`):

| File | What it is |
|---|---|
| `lib.pyi` | Copy of `spikes/0001-type-surface/round2/lib_final_declared.pyi`, changed in three places (below) |
| `domain.py` | The smallest domain the lines need: `Money` (`@value`), `User`; `Order` (root; `amount: Col[Decimal]`, `qty`/`cap: Col[int]`, `ratio: Col[float]`, `number: Col[str]`, `user_id: Col[Id[User]]` by `fk`, `guest_id: Col[Id[User] \| None]`, `paid_with: Col[PaymentMethod \| None]`, `total: Col[Money]` embedded, `items` owned, `payments` not owned); `Item` (`order_id` by `parent_fk`, `sku`, `price: Col[Decimal]`, `position` with a default); `Payment` (`order_id` by `fk`, `amount`); `Wallet` (`user_id` by `fk`, `balance: Col[Money]`) |
| `pass_parent_fk.py` / `fail_parent_fk.py` | Part A, the five lines of the #49 table (labelled A1-A5) |
| `pass_operands.py` / `fail_operands.py` | Part B, every line of the #51 table (labelled B1-B12 by table row) |
| `pass_observed.py` / `fail_observed.py` | O1-O4, O6 (outside `Annotated`), O7 |
| `probe_none.py`, `probe_load_when.py`, `probe_eq_fallback.py`, `probe_reveal.py`, `probe_reviews.py` | Run directly: O5, O6 inside `Annotated`, O8, the revealed types behind the `assert_type` lines, and O9-O10 (after the review) |
| `domain_final_declared.py`, `pass_final_declared.py`, `fail_final_declared.py` | Regression: spike 0001's round-2 files, copied with one change each - `from lib_final_declared import` became `from lib import` |

The stub diff against `lib_final_declared.pyi` (`results/stub.diff`):
1. `Column`'s comparison operators. The two `__eq__` / `__ne__` lines and the `__lt__` / `__ge__`
   lines are replaced by four overloads for **each** of `__eq__`, `__ne__`, `__lt__`, `__le__`,
   `__gt__`, `__ge__` (`__le__` and `__gt__` are new), in this order:

   ```python
   @overload  # type: ignore[override]  # finding L2           (only on __eq__ / __ne__)
   def __eq__[O2](self, other: Column[O2, _T], /) -> Pred[_O_co | O2]: ...
   @overload
   def __eq__[O2](self, other: Column[O2, _T | None], /) -> Pred[_O_co | O2]: ...
   @overload
   def __eq__[O2, U](
       self: Column[_O_co, U | None], other: Column[O2, U], /
   ) -> Pred[_O_co | O2]: ...
   @overload
   def __eq__(self, other: _T, /) -> Pred[_O_co]: ...  # pyright: ignore[reportIncompatibleMethodOverride]   (only on __eq__ / __ne__; finding S1)
   ```
2. `parent_fk` after `fk`, and in `Entity`'s `dataclass_transform(field_specifiers=(column, pk,
   fk, parent_fk, embedded, version_column, many_to_one, one_to_many))`:

   ```python
   def parent_fk[T](
       target: Callable[[], type[object]], /, *, init: Literal[False] = False
   ) -> Col[T]: ...
   ```
3. For O6 only, `Load` gains a minimal expression form (the design leaves its signature open; the
   owner of a two-entity predicate is checked by seal, ADR-0004, so both arguments take
   `Pred[object]`):

   ```python
   @staticmethod
   def when(condition: Pred[object], /, *, match: Pred[object]) -> Load: ...
   ```

Shape of the fail lines (found while building the files, before any verdict was read): pyright
strict adds a second code wherever an expression that failed to type is used - on a bare
expression statement `reportUnusedExpression`, on an assignment or `return`
`reportUnknownVariableType`, on a call argument `reportUnknownArgumentType`. In an `assert`
statement both checkers report the operator code alone, and an accepted comparison reports
nothing (checked on `assert Order.amount >= Order.amount`). So every rejected comparison stands
in an `assert`; the one `Load.when` fail line passes it as an argument and lists
`reportUnknownArgumentType` as well. (mypy types a failed comparison as `Any` and adds
`no-any-return` when it is returned - found by the reproduction; the `assert` form avoids that
too.)

Commands (raw output in `results/`):

```bash
D=spikes/0006-parent-fk-and-column-operands
# the stub alone (results/stub-*.txt)
uv run pyright $D/lib.pyi
uv run mypy --strict --show-error-codes --no-incremental $D/lib.pyi
# the decision tables (results/typetests-tables.txt)
uv run python -m tools.typetests $D/lib.pyi $D/domain.py \
  $D/pass_parent_fk.py $D/fail_parent_fk.py $D/pass_operands.py $D/fail_operands.py
# the observations (results/typetests-observed.txt)
uv run python -m tools.typetests $D/lib.pyi $D/domain.py $D/pass_observed.py $D/fail_observed.py
# the regression (results/typetests-regression.txt)
uv run python -m tools.typetests $D/lib.pyi $D/domain_final_declared.py \
  $D/pass_final_declared.py $D/fail_final_declared.py
# messages and revealed types, for each F in fail_parent_fk fail_operands fail_observed
#   probe_none probe_load_when probe_eq_fallback probe_reveal probe_reviews
#   (results/<F>-<checker>.txt)
uv run pyright $D/lib.pyi $D/domain.py $D/$F.py
uv run mypy --strict --show-error-codes --no-incremental $D/lib.pyi $D/domain.py $D/$F.py
```

Two controls, run once each:
- **Overload order.** `results/order-variant/lib.pyi` is `lib.pyi` with the value overload moved
  first in each operator and both suppressions removed; `domain.py`, the six pass/fail files and
  the three regression files are copied next to it unchanged (`V=$D/results/order-variant`):

  ```bash
  uv run pyright $V/lib.pyi; uv run mypy --strict --no-incremental $V/lib.pyi
  uv run python -m tools.typetests $V/domain.py $V/pass_parent_fk.py $V/fail_parent_fk.py \
    $V/pass_operands.py $V/fail_operands.py $V/pass_observed.py $V/fail_observed.py
  uv run python -m tools.typetests $V/domain_final_declared.py $V/pass_final_declared.py \
    $V/fail_final_declared.py
  ```

  The stub then reports exactly the two expected override errors per checker (pyright
  `reportIncompatibleMethodOverride` x2, mypy `override` x2), and every pinned file, passed
  without the stub, still ends with `0 problem(s)` (7 files, then 3 files).
- **O8 on spike 0001's stub.** `results/probe_eq_fallback_0001.py` runs O8's lines against copies
  of `lib_final_declared.pyi` and `domain_final_declared.py` (`Order.number == 1`, `!= 1`, inside
  `Order.where`).

## Observations
No database. Every pinning command ends with `0 problem(s)`:

```text
typetests: 0 problem(s) in 6 file(s)   # tables
typetests: 0 problem(s) in 4 file(s)   # observations
typetests: 0 problem(s) in 4 file(s)   # regression (spike 0001 round 2 on the new stub)
```

**The stub.** pyright `0 errors, 0 warnings, 0 informations`; mypy `Success: no issues found in 1
source file`.

- **S1 - where the `__eq__` / `__ne__` override is reported.** Without suppressions (`results/s1/`)
  mypy reports `Signature of "__eq__" incompatible with supertype "builtins.object"` (`override`)
  on the **first** overload's `@overload` line; pyright reports `Method "__eq__" overrides class
  "object" in an incompatible manner - No overload signature in override is compatible with base
  method` (`reportIncompatibleMethodOverride`) on the **last** overload's `def`. One
  `# type: ignore[override]` cannot cover both: on the last line mypy `--strict` would report it
  as unused. The stub therefore carries `# type: ignore[override]` on the first overload and
  `# pyright: ignore[reportIncompatibleMethodOverride]` on the last, for each of `__eq__` and
  `__ne__`. This extends spike 0001's L2 (a library-side suppression); users see nothing of it.

### A - parent-set foreign key (#49)

| # | Line | pyright | mypy | As decided |
|---|---|---|---|---|
| A1 | `Item(sku="A", price=Decimal(1))` (FK by `parent_fk`) | accepted, `Item` | accepted, `Item` | yes |
| A2 | `Item(order_id=order.id, sku="A", price=Decimal(1))` | `No parameter named "order_id"` (`reportCallIssue`) | `Unexpected keyword argument "order_id" for "Item"` (`call-arg`) | yes |
| A3 | `Payment(amount=Decimal(1))` (non-owned, FK by `fk`) | `Argument missing for parameter "order_id"` (`reportCallIssue`) | `Missing named argument "order_id" for "Payment"` (`call-arg`) | yes |
| A4 | `order.set(Order.items.add(item))` | accepted, `Changes` | accepted, `Changes` | yes |
| A5 | `item.order_id` / `Item.order_id` | `Id[Order]` / `Column[Item, Id[Order]]` | `Id[Order]` / `Column[Item, Id[Order]]` | yes |

The synthesised constructor (`reveal_type(Item.__init__)`): pyright `(self: Item, *, sku: str,
price: Decimal, position: int = 0) -> None`; mypy `def (self: domain.Item, *, sku: str, price:
decimal.Decimal, position: int =)`. `Order.items.add(Item(...))` is `Op[Order]` in both;
`Payment(order_id=order.id, amount=Decimal(1))` is accepted (`Payment`) in both.

### B - column comparison operands (#51)

| # | Line | pyright | mypy | As decided |
|---|---|---|---|---|
| B1 | `Order.amount >= Decimal(0)` | `Pred[Order]` | `Pred[Order]` | yes |
| B2 | `Order.amount >= 0` | `Operator ">=" not supported for types "Column[Order, Decimal]" and "Literal[0]"` (`reportOperatorIssue`) | `No overload variant of "__ge__" of "Column" matches argument type "int"` (`operator`) | yes |
| B3 | `Order.amount >= 1.5`, `Order.amount >= "1"`, `Order.qty >= Decimal(1)` | the same message with `"float"`, `"Literal['1']"`, and `"Column[Order, int]" and "Decimal"` (`reportOperatorIssue`) | the same message with `"float"`, `"str"`, `"Decimal"` (`operator`) | yes |
| B4 | `Order.ratio >= 1` (`Col[float]`) | `Pred[Order]` | `Pred[Order]` | yes |
| B5 | `Order.qty <= Order.cap` | `Pred[Order]` | `Pred[Order]` | yes |
| B6 | `Wallet.user_id == Order.user_id` | `Pred[Wallet \| Order]` | `Pred[Wallet \| Order]` | yes |
| B7 | `Wallet.user_id == Order.guest_id` / `Order.guest_id == Wallet.user_id` | `Pred[Wallet \| Order]` / `Pred[Order \| Wallet]` | the same | yes |
| B8 | `Wallet.user_id == Order.number` | `Operator "==" not supported for types "Column[Wallet, Id[User]]" and "Column[Order, str]"` (`reportOperatorIssue`) | `Unsupported operand types for == ("Column[Wallet, Id[User]]" and "Column[Order, str]")` (`operator`) | yes |
| B9 | `Order.qty == Order.amount`, `Order.amount >= Order.qty` | the same message with `"Column[Order, int]" and "Column[Order, Decimal]"` and the reverse (`reportOperatorIssue`) | `Unsupported operand types for == / >= (...)` (`operator`) | yes |
| B10 | `Check(lambda: Order.qty <= Order.cap)` | accepted | accepted | yes |
| B11 | `Order.where(Order.qty <= Order.cap)` | `SetChange[Order]` | `SetChange[Order]` | yes |
| B12 | `Order.where(Order.user_id == Wallet.user_id)`, `Order.where(Wallet.user_id == Order.user_id)` | `Argument of type "Pred[Order \| Wallet]"` (resp. `"Pred[Wallet \| Order]"`) `cannot be assigned to parameter "preds" of type "Pred[Order]"` (`reportArgumentType`) | `Argument 1 to "where" of "Entity" has incompatible type "Pred[Wallet \| Order]"; expected "Pred[Order]"` on both lines (`arg-type`) | yes |

On B12 mypy prints the union as `Wallet | Order` for both lines, while a bare
`reveal_type(Order.user_id == Wallet.user_id)` is `Pred[Order | Wallet]` in both checkers
(`results/probe_reveal-*.txt`); only the printed order differs.

### Observations outside the tables
- **O1 - `Pred[O]` behaves as covariant in both checkers.** `Order.qty <= Order.cap` is accepted
  for a `Pred[Order | Wallet]` parameter and `Wallet.user_id == Order.user_id` for a
  `Pred[object]` one; `_narrow: Pred[Order] = Wallet.user_id == Order.user_id` is rejected
  (pyright `Type "Pred[Wallet | Order]" is not assignable to declared type "Pred[Order]"`,
  `reportAssignmentType`; mypy `Incompatible types in assignment (expression has type
  "Pred[Wallet | Order]", variable has type "Pred[Order]")`, `assignment`). The variance is still
  inferred from an empty class body (PEP 695), as `Column`'s was before ADR-0004 Decision 3 fixed
  it: if `Pred` gains a member that uses `O` in another position, B12 and O1 can change.
- **O2 - a value on the left.** `Decimal(0) <= Order.amount` is `Pred[Order]` in both (the
  reflected `Column.__ge__` answers). `0 <= Order.amount` is rejected by both: pyright `Operator
  "<=" not supported for types "Literal[0]" and "Column[Order, Decimal]"` (`reportOperatorIssue`),
  mypy `Unsupported operand types for <= ("int" and "Column[Order, Decimal]")` (`operator`).
- **O3 - embedded paths.** 4.2's `Order.total.path(Money.amount) >= Decimal(0)` and
  `Order.amount >= Order.total.path(Money.amount)` are `Pred[Order]`;
  `Order.total.path(Money.amount) == Wallet.balance.path(Money.amount)` is `Pred[Order | Wallet]`;
  `Order.total.path(Money.currency) == Order.amount` (`str` against `Decimal`) and design 11.8's
  `Order.total.path(Money.amount) >= 0` (pinned after the review) are rejected
  (`reportOperatorIssue` / `operator`). Both checkers agree on each.
- **O4 - no column-as-value fallback here.** mypy picks a column overload, never the value
  overload, for a column on the right: B6 and B7 are `Pred[Wallet | Order]` in a bare expression;
  under an expected `Pred[Order]` (O1's assignment, B12) mypy still infers the two-owner
  predicate and rejects it. A same-entity comparison under an expected `Pred[Order]`
  (`Order.amount >= Order.total.path(Money.amount)`) is accepted by both. The separate overloads
  avoid the split spike 0001 found for a `T | Column[O, T]` parameter. One display detail: in
  O6's `Load.when` fail line (expected `Pred[object]`), mypy prints the right operand as
  `"Column[object, str]"` - the owner of the class access is solved from the context - while
  pyright prints `"Column[Order, str]"`; the verdict is the same.
- **O5 - `== None`** (`probe_none.py`). On the nullable `Order.guest_id`, `== None` and `!= None`
  are `Pred[Order]` in both (the value overload with `T = Id[User] | None`). On the non-null
  `Order.user_id` both are `bool` in both checkers, with no diagnostic (no
  `reportUnnecessaryComparison`, no `comparison-overlap`): the operator falls back to `None`'s
  reflected `__eq__`. Ordering against `None` on the nullable column is accepted too:
  `Order.guest_id >= None` is `Pred[Order]` in both (found by the reproduction, rerun here). The direct call `Order.user_id.__eq__(None)` is rejected by both (pyright
  `reportCallIssue` + `reportArgumentType`, mypy `operator`). Not decided here (#9).
- **O6 - 4.7's `Load.when`.** Outside `Annotated`, `Load.when(Order.paid_with ==
  PaymentMethod.POINT, match=Wallet.user_id == Order.user_id)` is accepted by both (`Load`), and a
  `match` of `Wallet.user_id == Order.number` is rejected by both (pyright `reportOperatorIssue` +
  `reportUnknownArgumentType`, mypy `operator`). Inside `Annotated` (`probe_load_when.py`):
  4.7 as written, and the match reversed, are accepted by both; the `Wallet.user_id ==
  Order.number` match is rejected by pyright only (`reportOperatorIssue` +
  `reportUnknownArgumentType`), and a condition `Order.paid_with == 1` by pyright only (`Argument of
  type "bool" cannot be assigned to parameter "condition" of type "Pred[object]"`,
  `reportArgumentType`); mypy reports `Success: no issues found`. Spike 0002's X1 holds with the
  new operators: an inline load declaration is checked by pyright and by seal, not by mypy.
- **O7 - spike 0002 `probe_accepted.py` item 6.** For an owned child it can no longer be written:
  `order.set(Order.items.add(Item(order_id=other.id, ...)))` is rejected by both (`reportCallIssue`
  / `call-arg`, as A2). For a non-owned child it still type-checks:
  `order.set(Order.payments.add(Payment(order_id=other.id, amount=Decimal(1))))` is `Changes` in
  both (#60).
- **O8 - `==` / `!=` with a value of the wrong type is `bool`, not an error** (`probe_eq_fallback.py`).
  `Order.amount == 0`, `Order.number == 1` and `Order.number != 1` are `bool` in both checkers,
  with no diagnostic: when no overload of `Column.__eq__` matches, both checkers try the value's
  reflected `__eq__`, which typeshed types `(object) -> bool`. Ordering operators have no such
  fallback (B2, B3). The mistake is caught where a predicate is required: `Order.where(Order.amount
  == 0)` is rejected by both (pyright `Argument of type "bool" cannot be assigned to parameter
  "preds" of type "Pred[Order]"`, `reportArgumentType`; mypy `Argument 1 to "where" of "Entity" has
  incompatible type "bool"; expected "Pred[Order]"`, `arg-type`), as are `Check`, `Load.when` and
  `select(...).where` (all take a `Pred`). On `Check(lambda: Order.amount == 0)` mypy reports two
  codes on the line, `arg-type` (`Argument 1 to "Check" has incompatible type "Callable[[], bool]"`)
  and `return-value` (`Incompatible return value type (got "bool", expected "Pred[object]")`);
  pyright one (`reportArgumentType`). The same happens on spike 0001's stub (`Order.number ==
  1` is `bool` in both, `Order.where(Order.number == 1)` rejected by both), so the overloads did
  not introduce it. O5's non-null case is this fallback with `None` as the value. This is the
  checkers' view: at run time `Column.__eq__` is called first, so what it does with a value that
  is not a `T` is the implementation's choice (#9).
- **O9 - a child's parent key can still be changed after creation** (`probe_reviews.py`, after the
  architect review; reproduced in Reproduction round 2). `parent_fk` returns an ordinary `Col[T]`, so
  `order.set(Order.items.update(item, Item.order_id.to(other.id)))` is `Changes`,
  `Item.where(Item.sku == "A").set(Item.order_id.to(other.id))` is `SetChange[Item]`, and
  `order.set(Order.items.add(other.items[0]))` (a child loaded under another order) is `Changes`
  in both checkers, with no diagnostic. The reproduction found a fourth way: the child's own
  `item.set(Item.order_id.to(other.id))` is `Changes` in both, without going through the parent.
  What #49 removes is *creating* a new owned child with another parent's key; moving an existing
  child stays writable (open, #9).
- **O10 - an enum column and an embedded value column** (`probe_reviews.py`, as O9; reproduced in round 2). The value
  overloads of `__lt__` / `__le__` / `__gt__` / `__ge__` put no bound on `T`.
  - Enum: `Order.paid_with >= PaymentMethod.POINT` is `Pred[Order]` in both checkers, although
    Python's plain `Enum` has no order (a direct `PaymentMethod.CARD < PaymentMethod.POINT` is
    rejected by both, reproduction round 2) and the SQL order depends on `enum_as`. `IntEnum` and
    `StrEnum` members are ordered in both checkers and at run time, and a `StrEnum`'s order (by
    value) can differ from a native PostgreSQL enum's (declaration order) - found by the
    reproduction.
  - Embedded value: `Order.total >= Money(Decimal(1))` and `Order.total == Money(Decimal(1))` are
    `Pred[Order]` in both. Here the value class *is* ordered: `Money(Decimal(1)) < Money(Decimal(2))`
    is `bool` in both checkers (`@value` has `order_default=True`; 4.5 writes
    `wallet.balance < order.total`; without `order_default=True` both reject `Money < Money`,
    reproduction round 2). The open question is not an order but the column: it spans several SQL
    columns, so whether a comparison (`>=` and `==` alike, also between two embedded columns:
    `Wallet.balance < Order.total` is `Pred[Wallet | Order]`) compiles to a row comparison or is
    allowed only through `path(...)` is open.

  Both are open (#9). (An earlier version of this item listed the embedded value as a type without
  a natural order; the maintainer's review corrected it, and the two last lines were added then.)

## Verdict
**Holds.** Every line of both decision tables gets the stated verdict, code and inferred type in
both checkers; the stub is clean under both; spike 0001's round-2 files give the same verdicts on
the new stub; the order of the overloads changes no verdict.

- **A (#49) holds.** `parent_fk(..., init: Literal[False] = False)` takes an owned child's FK out
  of the constructor in both checkers, a non-owned child's `fk` stays a required parameter, and
  creating an owned child with another parent's key is no longer writable (O7). Moving an existing
  child to another parent still is (O9, open).
- **B (#51) holds.** Values are exactly `T` for the ordering operators, column-to-column
  comparisons type-check through overloads with the same value type up to nullability, the result
  is `Pred[O | O2]`, and `Order.where(...)` rejects a predicate over two owners.

Consequences for the design (edited in the same change): 4.2, 4.4, 4.7 and 8.2 state the decided
rules (design and `design-KO.md`), ADR-0003 lists the parent-set FK among the fields that are not
constructor parameters, ADR-0004's constraint on parameters taking a column and a value is
amended, and the type-tests skill names this stub as the reference for the operators and
`parent_fk`. Points the implementation (#9) inherits:
- `==` / `!=` with a wrong value type is `bool` until a `Pred` is required (O8); `== None` on a
  non-null column is the same case, and ordering against `None` on a nullable column is accepted
  (O5). Decided in #9 together with the meaning of `== None`.
- `{Order.amount}` (a column in a set) is rejected by pyright (`reportUnhashable`: `Column` defines
  `__eq__` without `__hash__`) and accepted by mypy - a checker disagreement already present on
  spike 0001's stub, found by the reproduction; #9 settles it when `Column` is written.
- A child's parent key stays writable after creation (O9); ordering is accepted on an enum column,
  and a comparison on an embedded value column, which spans several SQL columns, is accepted
  without deciding whether it compiles to a row comparison or needs `path(...)` (O10).
- The reproduction's points 1-3, 5 and 6 are carried into O5, the Method's shape paragraph, O8,
  this list and the overload-order command; point 4 (mypy's notes list three of the four
  overloads) is cosmetic.
- Two suppressions per equality operator, one per checker (S1).
- `Pred`'s variance is inferred (O1); like `Column`'s, it should be declared and pinned by a type
  test when `Pred` is written for real.

Not decided here and left open in the design text: reading the FK of an owned child that has not
been added yet (#76); owned children of a new root and `add` on a relation that is not `owned`
(#60); the seal check that an `owned=True` relation and a `parent_fk` declaration match, the final
name of `parent_fk`, the meaning of `== None`, and an explicit cast between numeric column types
(#9); how a predicate over two owners is accepted where two entities are in scope (ADR-0004, #52).

## Reproduction

- **Who:** type-reviewer (independent; did not run the spike; worked from this write-up and
  spike 0001's round-2 files only). The spike's own `lib.pyi`, `domain.py`, `pass_*` / `fail_*` /
  `probe_*` files and `results/` were not opened before its own run was finished; afterwards only
  `lib.pyi` was diffed and the three pinning commands of Method were rerun unchanged.
- **Date:** 2026-11-26
- **Tools observed:** Python 3.14.7, pyright 1.1.414, mypy 2.4.1 (compiled: yes). Branch
  `docs/phase-1a-decisions` at `567684f`, spike files untracked. Configuration from
  `pyproject.toml`.

**What was built** (all in `spikes/0006-parent-fk-and-column-operands/results/repro/`, git-ignored;
call it `$R`)
- `lib.pyi`: `lib_final_declared.pyi` with the three changes of Method applied by a script (the six
  operators as four overloads each in the stated order, `# type: ignore[override]` on the first
  `@overload` of `__eq__` / `__ne__` and `# pyright: ignore[reportIncompatibleMethodOverride]` on
  the last `def`; `parent_fk` after `fk` and in `field_specifiers`; `Load.when`).
- `rp_domain.py`: its own domain after the Method table (`Money`, `User`, `Order` with the listed
  fields and `Meta.checks = (Check(lambda: Order.qty <= Order.cap),)`, `Item` by `parent_fk`,
  `Payment` by `fk`, `Wallet`).
- `pass_rp_a.py` / `fail_rp_a.py` (A1-A5, plus the non-owned `Payment(order_id=...)` control),
  `pass_rp_b.py` / `fail_rp_b.py` (B1-B12, plus `>`, `<`, `<=`, `!=` lines of the same shape),
  `pass_rp_obs.py` / `fail_rp_obs.py` (O1-O4, O6 outside `Annotated`, O7), with the markers chosen
  from the reason before running; `probe_rp_none.py` (O5), `probe_rp_load_when.py` (O6 inside
  `Annotated`, both as a `type` alias and as a parameter annotation of a `@usecase`),
  `probe_rp_eq_fallback.py` (O8, including `Check`, `Load.when`, `select(...).where`),
  `probe_rp_reveal.py`, `probe_rp_shape.py` (the fail-line shape: bare, assignment, argument,
  `assert`, `return`, and an accepted `assert`), `probe_rp_extra.py` (its own extra lines).
- `s1a/lib.pyi` (both suppressions removed), `s1b/lib.pyi` (one `# type: ignore[override]` on the
  last overload only), `order/lib.pyi` (value overload first, no suppressions) with copies of the
  pinned files, `o8_0001/` (spike 0001's stub and domain with an O8 probe), and the regression
  files `domain_final_declared.py` / `pass_final_declared.py` / `fail_final_declared.py` copied
  from spike 0001 round 2 with `from lib_final_declared import` replaced by `from lib import`
  (`diff` confirms that is the only change).

**What was run** (from the repository root)

```bash
R=spikes/0006-parent-fk-and-column-operands/results/repro
uv run pyright $R/lib.pyi; uv run mypy --strict --show-error-codes --no-incremental $R/lib.pyi
uv run python -m tools.typetests $R/lib.pyi $R/rp_domain.py \
  $R/pass_rp_a.py $R/fail_rp_a.py $R/pass_rp_b.py $R/fail_rp_b.py       # 0 problem(s) in 6 file(s)
uv run python -m tools.typetests $R/lib.pyi $R/rp_domain.py $R/pass_rp_obs.py $R/fail_rp_obs.py
                                                                        # 0 problem(s) in 4 file(s)
uv run python -m tools.typetests $R/lib.pyi $R/domain_final_declared.py \
  $R/pass_final_declared.py $R/fail_final_declared.py                   # 0 problem(s) in 4 file(s)
# for F in fail_rp_a fail_rp_b fail_rp_obs probe_rp_none probe_rp_load_when
#          probe_rp_eq_fallback probe_rp_reveal probe_rp_shape probe_rp_extra:
uv run pyright $R/lib.pyi $R/rp_domain.py $R/$F.py
uv run mypy --strict --show-error-codes --no-incremental $R/lib.pyi $R/rp_domain.py $R/$F.py
# S1 and the overload-order control
uv run pyright $R/s1a/lib.pyi $R/s1b/lib.pyi $R/order/lib.pyi    # and mypy --strict on each
uv run python -m tools.typetests $R/order/rp_domain.py $R/order/pass_rp_*.py $R/order/fail_rp_*.py
                                                                        # 0 problem(s) in 7 file(s)
uv run python -m tools.typetests $R/order/domain_final_declared.py \
  $R/order/pass_final_declared.py $R/order/fail_final_declared.py       # 0 problem(s) in 3 file(s)
# Any audit
uv run mypy --strict --disallow-any-expr --disallow-any-explicit --disallow-any-decorated \
  $R/lib.pyi $R/rp_domain.py $R/pass_rp_a.py $R/pass_rp_b.py $R/pass_rp_obs.py
```

After its own run it also reran the three pinning commands of Method on the spike's files,
unchanged: `0 problem(s)` in 6, 4 and 4 files, and the stub alone clean in both checkers.

**Observations**

| # | Reproducer | Evidence |
|---|---|---|
| Stub | agree | pyright `0 errors, 0 warnings, 0 informations`; mypy `Success: no issues found in 1 source file`. |
| S1 | agree | Without suppressions mypy reports `override` on line 38 (the first `@overload` of `__eq__`), pyright `reportIncompatibleMethodOverride` on line 47 (the last `def`), same for `__ne__`; messages word for word. With one `# type: ignore[override]` on the last line pyright is clean and mypy reports the `override` on the first line plus `unused-ignore` on the last. |
| A1 | agree | `Item`; constructor `(self: Item, *, sku: str, price: Decimal, position: int = 0) -> None` / `def (self: rp_domain.Item, *, sku: str, price: decimal.Decimal, position: int =)`. |
| A2 | agree | `No parameter named "order_id"` (`reportCallIssue`) / `Unexpected keyword argument "order_id" for "Item"` (`call-arg`). |
| A3 | agree | `Argument missing for parameter "order_id"` (`reportCallIssue`) / `Missing named argument "order_id" for "Payment"` (`call-arg`). |
| A4 | agree | `Changes` in both; `Order.items.add(Item(...))` is `Op[Order]`; `Payment(order_id=order.id, amount=Decimal(1))` is `Payment`. |
| A5 | agree | `Id[Order]` / `Column[Item, Id[Order]]` in both. |
| B1, B4, B5 | agree | `Pred[Order]` in both. |
| B2, B3 | agree | Messages and codes as tabled (pyright `"Literal[0]"`, `"float"`, `"Literal['1']"`, `"Column[Order, int]" and "Decimal"`; mypy `"int"`, `"float"`, `"str"`, `"Decimal"`). |
| B6, B7 | agree | `Pred[Wallet \| Order]`, `Pred[Wallet \| Order]`, `Pred[Order \| Wallet]` in both. |
| B8, B9 | agree | Messages and codes as tabled in both checkers. |
| B10, B11 | agree | `Check`, `SetChange[Order]` in both. |
| B12 | agree | pyright `Pred[Order \| Wallet]` / `Pred[Wallet \| Order]` to `"preds"` (`reportArgumentType`); mypy prints `Pred[Wallet \| Order]` on both lines (`arg-type`) while `reveal_type(Order.user_id == Wallet.user_id)` is `Pred[Order \| Wallet]` in both. |
| O1 | agree | Both accept the wider parameters and reject the narrow assignment with the quoted messages (`reportAssignmentType` / `assignment`); pyright's message names the inferred variance (`Type parameter "O@Pred" is covariant`). |
| O2 | agree | `Decimal(0) <= Order.amount` is `Pred[Order]`; `0 <= Order.amount` rejected with the quoted messages. |
| O3 | agree | `Pred[Order]`, `Pred[Order]`, `Pred[Order \| Wallet]`, and `str` path against `Decimal` column rejected (`reportOperatorIssue` / `operator`) in both. |
| O4 | agree | No value-overload fallback for a column on the right in mypy; `_same: Pred[Order] = Order.amount >= Order.total.path(Money.amount)` accepted by both; mypy prints `"Column[object, str]"` and pyright `"Column[Order, str]"` on the `Load.when` fail line. |
| O5 | agree | Nullable: `Pred[Order]` for `== None` / `!= None`; non-null: `bool` with no diagnostic in both; `Order.user_id.__eq__(None)` rejected (pyright `reportCallIssue` + `reportArgumentType`, mypy `operator`). |
| O6 | agree | Outside `Annotated` as stated. Inside `Annotated` pyright rejects the `Order.number` match (`reportOperatorIssue` + `reportUnknownArgumentType`) and `Order.paid_with == 1` (`Argument of type "bool" ...`, `reportArgumentType`); mypy reports nothing, both in a `type` alias and in a parameter annotation. |
| O7 | agree | Owned child: `call-arg` / `reportCallIssue`; non-owned child: `Changes` in both. |
| O8 | agree | `bool` in both, no diagnostic; `Order.where`, `Check`, `Load.when`, `select(...).where` each rejected by both. |
| Overload order | agree | Exactly one `reportIncompatibleMethodOverride` per `__eq__` / `__ne__` (pyright) and one `override` each (mypy); every pinned file `0 problem(s)` (7 and 3 files). |
| O8 on 0001's stub | agree | `Order.number == 1` / `!= 1` are `bool` and `Order.where(Order.number == 1)` is rejected in both. |
| Regression | agree | `0 problem(s) in 4 file(s)`. |

**Fail-line shape.** Reproduced with `probe_rp_shape.py`: on `Order.amount >= 0` pyright adds
`reportUnusedExpression` (bare), `reportUnknownVariableType` (assignment, `return`),
`reportUnknownArgumentType` (argument); in an `assert` both checkers report the operator code
alone, and `assert Order.amount >= Order.amount` reports nothing. The shape is sound: the marker
pins the operand reason, and an accepted comparison (including an `==` that falls back to `bool`,
O8) reports nothing, which `tools.typetests` turns into `expected [...], got none` - an acceptance
cannot pass unnoticed. One residual looseness: the `Load.when` fail line lists
`reportUnknownArgumentType`, so on the pyright side a line that only produced an unknown argument
would also pass; the mypy code (`operator`) still pins the reason.

**Stub completeness.** `diff` of its stub against `spikes/0006-parent-fk-and-column-operands/lib.pyi`
shows only comments and the formatting of the `field_specifiers` tuple; the write-up describes
the stub completely. The spike's domain, pass and fail files contain no `cast`, `Any` or
suppression (grep). The `Any` audit finds only spike 0001's `query[F: Callable[..., object]]` in
the stub (`explicit-any`, already recorded there); nothing reaches the pinned lines.

**Discrepancies.** None on any claimed verdict, code, message or inferred type. Points the
write-up does not record (none changes the verdict):
1. Ordering against `None` on a nullable column is accepted: `Order.guest_id >= None` is
   `Pred[Order]` in both (the value overload with `T = Id[User] | None`). It belongs with O5 and
   the meaning of `== None` in #9.
2. mypy adds `no-any-return` when a failed comparison is returned, and turns a failed comparison
   into `Any` (`reveal_type` of `Order.user_id.__eq__(None)` is `Any` in mypy, `Unknown` in
   pyright). The shape paragraph names pyright's extra codes only; the `assert` form avoids both.
3. On `Check(lambda: Order.amount == 0)` (O8) mypy reports two codes, `arg-type` and
   `return-value`; a future fail line there must list both.
4. mypy's `Possible overload variants` and `override` notes list three of the four overloads (the
   self-typed one is omitted); cosmetic.
5. Outside this spike's scope, pre-existing on spike 0001's stub: `{Order.amount}` is rejected by
   pyright (`reportUnhashable`, `Column` defines `__eq__` without `__hash__`) and accepted by mypy.
   A checker disagreement for #9 to settle when `Column` is written.
6. The overload-order control gives no exact command (only the file counts); it was reproducible
   from the description.

**Overall: agree.** Both decision tables, S1, O1-O8, both controls and the regression reproduce
with an independently built stub and domain, under both checkers, with the stated codes, messages
and inferred types. Parts A (#49) and B (#51) hold.

### Round 2 - O9 and O10

- **Who:** type-reviewer (independent; did not run O9 / O10; worked from this write-up and spike
  0001's round-2 files only). `probe_reviews.py` and `results/probe_reviews-*.txt` were not
  opened before its own run was finished.
- **Date:** 2026-11-26
- **Tools observed:** Python 3.14.7, pyright 1.1.414, mypy 2.4.1 (compiled: yes). Worktree of
  `docs/spike-0006-parent-fk-and-column-operands`. Configuration from `pyproject.toml`.

**What was built** (all in `spikes/0006-parent-fk-and-column-operands/results/repro2/`,
git-ignored; call it `$R2`)
- `lib.pyi`: built anew from `spikes/0001-type-surface/round2/lib_final_declared.pyi` by a script
  applying the three changes of Method (four overloads per operator in the stated order, the two
  suppressions per `__eq__` / `__ne__`, `parent_fk` after `fk` and in `field_specifiers`,
  `Load.when`). Not the first reproduction's `results/repro/lib.pyi`. A comment-stripped `diff`
  against the spike's `lib.pyi` (after the run) shows only comments and line wrapping.
- `r2_domain.py`: its own domain after the Method table (`PaymentMethod(Enum)`, `Money` by
  `@value` with `amount: Col[Decimal]`, `currency: Col[str] = column(default="KRW")`, `User`,
  `Order` with every listed field, `Item` by `parent_fk`, `Payment` by `fk`, `Wallet`).
- `probe_r2.py`: every claim of O9 and O10 as `reveal_type` lines plus typed assignments
  (`Changes`, `SetChange[Item]`, `Pred[Order]`, `bool`), all four ordering operators and `!=` on
  both columns, `reveal_type(Money.__lt__)`, and one deliberate control
  `assert PaymentMethod.CARD < PaymentMethod.POINT`.
- `noorder/`: the same stub with only `order_default=True` removed from `value`'s
  `dataclass_transform`, the same domain, and `probe_noorder.py` (`Money(...) < Money(...)` and a
  plain undecorated class `Plain(...) < Plain(...)`).
- `probe_r2_extra.py`: 4.5's `wallet.balance < order.total` on instances, and `IntEnum` /
  `StrEnum` members compared with `<`.

**What was run** (from the worktree root)

```bash
R2=spikes/0006-parent-fk-and-column-operands/results/repro2
uv run python -V; uv run pyright --version; uv run mypy --version
uv run pyright $R2/lib.pyi                                       # 0 errors, 0 warnings, 0 informations
uv run mypy --strict --show-error-codes --no-incremental $R2/lib.pyi   # Success: no issues found
# for P in probe_r2 probe_r2_extra:
uv run pyright $R2/lib.pyi $R2/r2_domain.py $R2/$P.py
uv run mypy --strict --show-error-codes --no-incremental $R2/lib.pyi $R2/r2_domain.py $R2/$P.py
# the order_default control
uv run pyright $R2/noorder/lib.pyi $R2/noorder/r2_domain.py $R2/noorder/probe_noorder.py
uv run mypy --strict --show-error-codes --no-incremental \
  $R2/noorder/lib.pyi $R2/noorder/r2_domain.py $R2/noorder/probe_noorder.py
# Any audit of the probe
uv run mypy --strict --show-error-codes --no-incremental --disallow-any-expr \
  $R2/lib.pyi $R2/r2_domain.py $R2/probe_r2.py
# typeshed and run time: is Enum ordered?
grep -nE "__lt__|__le__|__gt__|__ge__" \
  .venv/lib/python3.14/site-packages/{mypy/typeshed,pyright/dist/dist/typeshed-fallback}/stdlib/enum.pyi
uv run python -c "..."   # PaymentMethod.CARD < PaymentMethod.POINT; '__lt__' in vars(enum.Enum)
```

After its own run it opened `probe_reviews.py` and its results and reran
`uv run pyright` / `uv run mypy --strict ...` on `$D/lib.pyi $D/domain.py $D/probe_reviews.py`
unchanged: `0 errors, 0 warnings, 7 informations` and `Success: no issues found in 3 source files`,
the seven revealed types as in `results/probe_reviews-*.txt`.

**Observations**

| Claim | Reproducer | Evidence (pyright / mypy, same in both unless stated) |
|---|---|---|
| O9 - `order.set(Order.items.update(item, Item.order_id.to(other.id)))` is `Changes` | agree | `Item.order_id` is `Column[Item, Id[Order]]`, `.to(other.id)` `Op[Item]`, `Order.items.update(...)` `Op[Order]`, the whole `Changes`; no diagnostic, the `a: Changes = ...` assignment accepted. |
| O9 - `Item.where(Item.sku == "A").set(Item.order_id.to(other.id))` is `SetChange[Item]` | agree | `SetChange[Item]` (mypy `lib.SetChange[r2_domain.Item]`); no diagnostic. |
| O9 - `order.set(Order.items.add(other.items[0]))` is `Changes` | agree | `other.items` is `Sequence[Item]`, `other.items[0]` `Item`, the whole `Changes`; no diagnostic. |
| O9 - "no diagnostic" | agree | No error on any O9 line in either checker. |
| O10 - `Order.paid_with >= PaymentMethod.POINT` is `Pred[Order]` | agree | `Pred[Order]`; also `>`, `<`, `<=` give `Pred[Order]`; `p: Pred[Order] = ...` accepted. `Order.paid_with` is `Column[Order, PaymentMethod \| None]`, so the value overload is taken with `T = PaymentMethod \| None`. |
| O10 - Python's `Enum` has no order | agree | `Enum` in both bundled typeshed copies (`mypy/typeshed`, `pyright/.../typeshed-fallback`) defines none of `__lt__` / `__le__` / `__gt__` / `__ge__`; the control `PaymentMethod.CARD < PaymentMethod.POINT` is rejected by both (pyright `Operator "<" not supported for types "Literal[PaymentMethod.CARD]" and "Literal[PaymentMethod.POINT]"`, `reportOperatorIssue`; mypy `Unsupported left operand type for < ("PaymentMethod")`, `operator`); at run time it raises `TypeError: '<' not supported between instances of 'P' and 'P'` and `vars(enum.Enum)` has no ordering method. |
| O10 - the value overloads put no bound on `T` | agree | Follows from the line above: an unordered `T` is accepted by `>=`, `>`, `<`, `<=`. |
| O10 - `Order.total >= Money(Decimal(1))` and `Order.total == Money(Decimal(1))` are `Pred[Order]` | agree | Both `Pred[Order]`; also `<` and `!=`; the two `Pred[Order]` assignments accepted. `Order.total` is `Column[Order, Money]`. |
| O10 - `Money(Decimal(1)) < Money(Decimal(2))` is `bool` | agree | `bool` in both; `>=` also `bool`; `r: bool = ...` accepted. `Money.__lt__` is pyright `(self: Money, other: Money) -> bool`, mypy `def [_DT] (self: _DT, other: _DT) -> bool` (each checker's synthesised dataclass method). |
| O10 - `order_default=True` of `@value` is what orders `Money` | agree | Control `noorder/`: with only `order_default=True` removed, `Money(...) < Money(...)` is rejected by both (pyright `Operator "<" not supported for types "Money" and "Money"`, `reportOperatorIssue`; mypy `Unsupported left operand type for < ("Money")`, `operator`), as is the plain class; `==` stays `bool`. |
| O10 - 4.5's `wallet.balance < order.total` is a plain `bool` | agree | `bool` in both (`probe_r2_extra.py`). |
| Any audit | - | `--disallow-any-expr` reports `Any` only on the deliberate enum control line (mypy types a failed comparison as `Any`, as recorded); no `Any` on an O9 / O10 line. |

**Discrepancies.** None on any claimed type or on the absence of diagnostics. Points the
write-up does not record (none changes O9 or O10):
1. A fourth way to move a child: the child's own `item.set(Item.order_id.to(other.id))` is
   `Changes` in both checkers, without going through the parent (`Entity.set` is on every
   entity, owned child or not). It belongs with O9 in #9.
2. Column-to-column on two embedded columns is accepted as well: `Wallet.balance < Order.total`
   is `Pred[Wallet | Order]` in both (the first column overload, `T = Money`). The open question
   of O10 (row comparison or `path(...)` only) covers the column-to-column form too.
3. "Python's `Enum` has no order" holds for `Enum` and for this domain's `PaymentMethod`, but not
   for every enum a user may declare: `IntEnum` and `StrEnum` members are ordered in both
   checkers (`Prio.LOW < Prio.HIGH`, `Code.A < Code.B` are `bool`) and at run time, through their
   `int` / `str` base. If #9 decides to reject ordering on enum columns, it has to say whether
   these count, and the Python order of a `StrEnum` (lexical on the value) need not match a native
   PostgreSQL enum's order (declaration order) - the same `enum_as` dependency O10 names.

**Overall: agree** on O9 and on O10, including the corrected reading: the plain `Enum` is
unordered in typeshed and at run time, and `@value`'s `order_default=True` is what makes `Money`
ordered in both checkers (removing it alone makes both reject `Money < Money`).
