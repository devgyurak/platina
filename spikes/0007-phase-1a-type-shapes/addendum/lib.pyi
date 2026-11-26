# pyright: reportInvalidTypeVarUse=false
# ^ Finding L1 of the write-up (field specifiers solve T from the annotation only).
"""Spike 0007: copy of spike 0002's `lib.pyi` (sha256 ad6ea7fec42121cd...) with the shapes of #48,
#57, #59 and #60 (decided 2026-11-26) and the decided shapes of #49 and #51 used as given.

Every line added or changed by spike 0007 carries `# [0007]` (a declaration the formatter wraps
carries it on its first and last line); `# [0002]` lines are spike 0002's
additions, kept. The #49 `parent_fk` and the #51 comparison overloads are copied from the decision
comments of those issues; spike 0006 pins them, this spike only uses them.

--- Spike 0002's docstring:
Spike 0002: copy of spike 0001's final stub `round2/lib_final_declared.pyi` plus additions.

Every line added or changed by spike 0002 carries `# [0002]`. Those signatures are NOT confirmed by
spike 0001: the design gives no signature for them (sections 4.7, 4.8, 4.10, 4.12) and they were
written as the minimum the use cases needed (write-up section "Stub additions").

Original docstring - Spike 0001, round 2 (P-A, P-C): the surface after the maintainer's decisions.

Owner-typed columns `Column[O, T]`, owner propagated into operations, predicates, relations and set
changes; an `Entity` base with `frozen_default=True` and no `new` (creation is `Order(...)`);
embedded paths `Order.total.path(Money.amount)` with value fields declared `Col[...]`.
"""

from collections.abc import (
    Awaitable,  # [0002]
    Callable,
    Iterable,  # [0002]
    Mapping,  # [0002]
    Sequence,
)
from datetime import datetime
from typing import Annotated, Generic, Literal, Never, Self, TypeVar, dataclass_transform, overload
from uuid import UUID

# Variance declared explicitly (reproduction round 2, discrepancy 3): owner covariant, value invariant.
_O_co = TypeVar("_O_co", covariant=True)
_T = TypeVar("_T")

# --------------------------------------------------------------------------- expressions
class Expr:
    def desc(self) -> Expr: ...

class Pred[O](Expr):
    """A predicate over columns of O."""

class Op[O]:
    """A field operation on a row of O."""

class OwnedExpr[O](Expr):
    """An expression over columns of O (used by the S2 query variant)."""

class Column(OwnedExpr[_O_co], Generic[_O_co, _T]):  # noqa: UP046 - finding L6: PEP 695 cannot declare variance
    """Class access of a `Col[T]` field declared on O (`Order.status`: `Column[Order, OrderStatus]`)."""

    def to(self, value: _T, /) -> Op[_O_co]: ...
    def add(self, delta: _T, /) -> Op[_O_co]: ...
    def path[U](self, field: Column[_T, U], /) -> Column[_O_co, U]: ...
    # [0007] #51: spike 0006's final overloads on all six operators (copied, not re-probed)
    # Spike 0006 (#51): a value is exactly `_T`; a column of the same value type (up to
    # nullability) gives a predicate over both owners.
    @overload  # type: ignore[override]  # finding L2  # [0007] from spike 0006
    def __eq__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __eq__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T | None], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __eq__[O2, U](  # [0007] from spike 0006
        self: Column[_O_co, U | None],
        other: Column[O2, U],
        /,  # [0007] from spike 0006
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __eq__(self, other: _T, /) -> Pred[_O_co]: ...  # pyright: ignore[reportIncompatibleMethodOverride]  # L2, spike 0006 S1  # [0007] from spike 0006
    @overload  # type: ignore[override]  # finding L2  # [0007] from spike 0006
    def __ne__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __ne__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T | None], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __ne__[O2, U](  # [0007] from spike 0006
        self: Column[_O_co, U | None],
        other: Column[O2, U],
        /,  # [0007] from spike 0006
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __ne__(self, other: _T, /) -> Pred[_O_co]: ...  # pyright: ignore[reportIncompatibleMethodOverride]  # L2, spike 0006 S1  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __lt__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __lt__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T | None], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __lt__[O2, U](  # [0007] from spike 0006
        self: Column[_O_co, U | None],
        other: Column[O2, U],
        /,  # [0007] from spike 0006
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __lt__(self, other: _T, /) -> Pred[_O_co]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __le__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __le__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T | None], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __le__[O2, U](  # [0007] from spike 0006
        self: Column[_O_co, U | None],
        other: Column[O2, U],
        /,  # [0007] from spike 0006
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __le__(self, other: _T, /) -> Pred[_O_co]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __gt__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __gt__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T | None], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __gt__[O2, U](  # [0007] from spike 0006
        self: Column[_O_co, U | None],
        other: Column[O2, U],
        /,  # [0007] from spike 0006
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __gt__(self, other: _T, /) -> Pred[_O_co]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __ge__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __ge__[O2](  # [0007] from spike 0006
        self, other: Column[O2, _T | None], /
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __ge__[O2, U](  # [0007] from spike 0006
        self: Column[_O_co, U | None],
        other: Column[O2, U],
        /,  # [0007] from spike 0006
    ) -> Pred[_O_co | O2]: ...  # [0007] from spike 0006
    @overload  # [0007] from spike 0006
    def __ge__(self, other: _T, /) -> Pred[_O_co]: ...  # [0007] from spike 0006
    def in_(  # [0007]
        self, values: Iterable[_T], /
    ) -> Pred[_O_co]: ...  # [0007] #59 "needs an `in_` operand"

_O_inv = TypeVar("_O_inv")  # [0007] invariant on purpose: see RelOp
_P_inv = TypeVar("_P_inv")  # [0007] invariant on purpose: see Path
_LP_co = TypeVar("_LP_co", covariant=True)  # [0007] see LoadPath

class Path(Generic[_P_inv]):  # noqa: UP046  # [0007] a load-path step owned by _P_inv; Load.after's arguments
    """[0007] Invariant in its owner: with the covariant OwnedExpr[E] as the type of load
    arguments, both checkers accepted `Load.after(point_wallet, Order.items)` (E solved from two
    arguments, spike 0001 P-A). Invariance leaves the returned entity as the only solution."""

class LoadPath(Generic[_LP_co]):  # noqa: UP046  # [0007] a step of `relation.load(...)`; covariant
    """[0007] Only relations derive from it, so a column is not a load path. Round 3 typed
    `relation.load` with `OwnedExpr`, which columns also are: both checkers accepted
    `Order.items.load(Item.quantity)` (independent review). Covariant, so a nullable
    many-to-one (`T | None`) still takes a path of T."""

class RelOp(Generic[_O_inv]):  # noqa: UP046  # [0007] #60: a relation operation; not an Op
    """[0007] A relation operation on the owned children of a row of _O_inv.

    Invariant in the owner: with an inferred (covariant) owner both checkers accepted
    `insert(t, Order.items.add(item))` for a new `Transfer` t (F11). Not an `Op`: a relation
    operation inside a set change (`Order.where(...).set(Order.items.remove(i))`) is then a type
    error instead of a seal check (R8 of round 1)."""

class AddOp(RelOp[_O_inv]):  # [0007] `add` - the only relation operation `insert` takes
    """[0007] Adds an owned child."""

# [0010] A2: a public name for "what `entity.set(...)` takes", for lists that collect both kinds
type Write[O] = Op[O] | RelOp[O]  # [0010]

class Relation[O, E](  # [0007]
    OwnedExpr[O], Path[O], LoadPath[O]
):  # [0007] bases OwnedExpr, Path, LoadPath (was Expr)
    """Class access of a collection relation of O with children E (`Order.items`).

    [0007] #60 point 4: a relation that is not `owned` has no write operations; only
    `OwnedRelation` has `add` / `remove` / `update`.
    """

    def count(self) -> Expr: ...
    # [0002] partial loads of section 8.2 ("`.exists()`, `.where(...)`"); no signature in the design
    def where(self, *preds: Pred[E]) -> Relation[O, E]: ...  # [0002]
    def exists(self) -> Expr: ...  # [0002]
    # [0007] #59 point 1: the receiver fixes E, so a covariant path type suffices here
    def load(self, *paths: LoadPath[E]) -> Relation[O, E]: ...  # [0007]

class OwnedRelation[O, E](Relation[O, E]):  # [0007] #60 point 4: an owned relation's type
    def add(self, item: E, /) -> AddOp[O]: ...  # [0007] (was on Relation, returning Op[O])
    def remove(self, item: E, /) -> RelOp[O]: ...  # [0007] (was on Relation)
    def update(  # [0010] A1: ownership is one level deep, so a child update takes column
        self, item: E, /, *ops: Op[E]
    ) -> RelOp[O]: ...  # [0010] operations only (was `Op[E] | RelOp[E]`, spike 0002 X15)
    # [0007] `where` / `load` are inherited: they return the read-only Relation[O, E]

class RelColumn[O, T](  # [0007]
    OwnedExpr[O], Path[O], LoadPath[O]
):  # [0007] bases OwnedExpr, Path, LoadPath (was Expr)
    """Class access of a single-valued relation (`Order.user`)."""

    # [0007] #59 point 1: covariant, so a `T | None` relation takes a path of T (round 3)
    def load(self, *paths: LoadPath[T]) -> RelColumn[O, T]: ...  # [0007]

# --------------------------------------------------------------------------- field descriptors
class Col[T]:
    @overload
    def __get__[O](self, instance: None, owner: type[O], /) -> Column[O, T]: ...
    @overload
    def __get__(self, instance: object, owner: type[object], /) -> T: ...
    def __set__(self, instance: Never, value: T, /) -> None: ...

class Rel[T]:
    @overload
    def __get__[O, E](self: Rel[list[E]], instance: None, owner: type[O], /) -> Relation[O, E]: ...
    @overload
    def __get__[E](self: Rel[list[E]], instance: object, owner: type[object], /) -> Sequence[E]: ...
    @overload
    def __get__[O](self, instance: None, owner: type[O], /) -> RelColumn[O, T]: ...
    @overload
    def __get__(self, instance: object, owner: type[object], /) -> T: ...
    def __set__(self, instance: Never, value: T, /) -> None: ...

class Owned[T]:  # [0007] #60 point 4: annotation of an owned collection relation (`owns_many`)
    @overload  # [0007]
    def __get__[O, E](  # [0007]
        self: Owned[list[E]], instance: None, owner: type[O], /
    ) -> OwnedRelation[O, E]: ...  # [0007]
    @overload  # [0007]
    def __get__[E](  # [0007]
        self: Owned[list[E]], instance: object, owner: type[object], /
    ) -> Sequence[E]: ...  # [0007]
    def __set__(self, instance: Never, value: T, /) -> None: ...  # [0007]

class Id[E](UUID): ...

# --------------------------------------------------------------------------- field specifiers
@overload
def column[T](
    *,
    default: T,
    unique: bool = ...,
    length: int | None = ...,
    enum_as: Literal["text", "native"] = ...,
) -> Col[T]: ...
@overload
def column[T](
    *,
    server_default: Expr,
    init: Literal[False] = False,
    unique: bool = ...,
    length: int | None = ...,
) -> Col[T]: ...
@overload
def column[T](
    *,
    unique: bool = ...,
    length: int | None = ...,
    enum_as: Literal["text", "native"] = ...,
) -> Col[T]: ...
def pk[T](
    *, generated: Literal["uuid7", "identity"] = ..., init: Literal[False] = False
) -> Col[T]: ...
@overload  # [0002]
def fk[T](target: Callable[[], type[object]], /) -> Col[T]: ...
@overload  # [0002] a nullable FK with a default (4.2 shows only required FKs)
def fk[T](target: Callable[[], type[object]], /, *, default: T) -> Col[T]: ...  # [0002]
def parent_fk[T](  # [0007]
    target: Callable[[], type[object]],  # [0007]
    /,
    *,
    init: Literal[False] = False,  # [0007]
) -> Col[T]: ...  # [0007] #49 decision comment
def embedded[T](*, prefix: str) -> Col[T]: ...
def version_column(*, init: Literal[False] = False) -> Col[int]: ...
def many_to_one[T](*, via: Callable[[], Expr], init: Literal[False] = False) -> Rel[T]: ...

# [0007] REJECTED ALTERNATIVE (maintainer, 2026-11-26: `owns_many` below). The `owned=` overloads
# [0007] stay only so that F8, F9 and probe_owned_flag.py keep running; #9 removes the flag.
@overload  # [0007] #60 point 4: `owned=True` gives the `Owned[...]` annotation
def one_to_many[T](  # [0007]
    target: Callable[[], Expr],  # [0007]
    /,  # [0007]
    *,  # [0007]
    owned: Literal[True],  # [0007]
    order_by: Callable[[], Expr] | None = ...,  # [0007]
    init: Literal[False] = False,  # [0007]
) -> Owned[T]: ...  # [0007]
@overload  # [0007]
def one_to_many[T](  # [0007] the overload for relations that are not owned
    target: Callable[[], Expr],
    /,
    *,
    owned: Literal[False] = ...,  # [0007] (was `bool`)
    order_by: Callable[[], Expr] | None = ...,
    init: Literal[False] = False,
) -> Rel[T]: ...  # [0007]
def owns_many[T](  # [0007] S4, chosen (maintainer, 2026-11-26): an owned relation's specifier
    target: Callable[[], Expr],  # [0007]
    /,  # [0007]
    *,  # [0007]
    order_by: Callable[[], Expr] | None = ...,  # [0007]
    init: Literal[False] = False,  # [0007]
) -> Owned[T]: ...  # [0007]
def server_now() -> Expr: ...

# --------------------------------------------------------------------------- changes
class Changes:
    def __add__(self, other: Changes, /) -> Changes: ...
    def returning(self, value: object, /) -> Changes: ...

_E_inv = TypeVar("_E_inv")  # [0007] invariant on purpose: see RowSet

class RowSet(Generic[_E_inv]):  # noqa: UP046  # [0007] #57 / #59: "the rows of E that match" - not a Changes
    """[0007] Invariant in the entity, declared (inferred, it came out contravariant)."""

    def set(  # [0007]
        self, *ops: Op[_E_inv], unsafe_bypass: str | None = ...
    ) -> SetChange[_E_inv]: ...  # [0007] set change
    def delete(self) -> Changes: ...  # [0007] #57 set-level delete

class SetChange[O](Changes):
    def set(self, *ops: Op[O], unsafe_bypass: str | None = ...) -> SetChange[O]: ...  # [0002] 4.13
    def emit_each(self, event: type[object], /, **fields: OwnedExpr[O]) -> SetChange[O]: ...

class StepResult:
    @property
    def events(self) -> Sequence[object]: ...
    # [0002] 4.12 / 11.11 assertions; the design shows calls, not signatures
    def updated(self, entity: object, /) -> Mapping[Expr, object]: ...  # [0002]
    def inserted[E](self, kind: type[E], /) -> Sequence[E]: ...  # [0002]
    def removed(self, entity: object, /) -> bool: ...  # [0002]
    @property  # [0002]
    def then(self) -> Sequence[Bound]: ...  # [0002]
    @property  # [0002]
    def value(self) -> object: ...  # [0002] the `Changes.returning(v)` value

class Add[T]:  # [0002] 4.12 `Add(Decimal("-1000"))`: the recorded increment
    def __init__(self, delta: T, /) -> None: ...  # [0002]

def then(bound: Bound, /) -> Changes: ...  # [0002] 4.6 `then(issue_receipt.bind(...))`
def emit(event: object, /) -> Changes: ...

# [0007] #60 points 1 and 3: one new row in the commit batch. With no `ops` this is candidate A
# [0007] (`insert(t) + t.set(Transfer.legs.add(...))`); with `ops` candidate B
# [0007] (`insert(t, Transfer.legs.add(...))`), which accepts relation operations only.
def insert[E: Entity](entity: E, /, *children: AddOp[E]) -> Changes: ...  # [0007]
def insert_all(entities: Iterable[Entity], /) -> Changes: ...  # [0002] 4.8 `insert_all(...)`

# --------------------------------------------------------------------------- declarations
@dataclass_transform(
    kw_only_default=True,
    frozen_default=True,
    field_specifiers=(  # [0007]
        column,
        pk,
        fk,
        parent_fk,
        embedded,
        version_column,
        many_to_one,
        one_to_many,
        owns_many,  # [0007] S4, chosen
    ),  # [0007] + parent_fk
)
class Entity:
    def __init_subclass__(cls, *, table: str, aggregate_root: bool = ...) -> None: ...
    @classmethod
    def ref(cls, id: UUID, /, *, expected_version: int | None = ...) -> Self: ...
    @classmethod
    def where(  # [0007]
        cls, pred: Pred[Self], /, *preds: Pred[Self]
    ) -> RowSet[Self]: ...  # [0007] was SetChange[Self]; round 5: one predicate required
    @classmethod
    def stub(cls, **fields: object) -> Self: ...
    def set(  # [0007] + RelOp[Self]
        self,
        *ops: Op[Self] | RelOp[Self],
        unsafe_bypass: str | None = ...,
    ) -> Changes: ...  # [0007]
    def delete(self) -> Changes: ...  # [0007] #57: the row and its owned children

# [0010] A3 - the ALTERNATIVE to a runtime rule for direct writes of an owned child (spike 0007
# [0010] R10-R12): a second base for owned children, without `where` / `set` / `delete`. `insert`
# [0010] is bound to `Entity`, so it rejects a `Part`. Probed only to weigh it; not proposed.
@dataclass_transform(  # [0010]
    kw_only_default=True,
    frozen_default=True,
    field_specifiers=(  # [0010] the same specifiers as Entity's (type-reviewer: without
        column,
        pk,
        fk,
        parent_fk,
        embedded,
        version_column,
        many_to_one,
        one_to_many,
        owns_many,
    ),  # [0010] owns_many, pyright made a declared `owns_many` a constructor parameter)
)  # [0010]
class Part:  # [0010]
    def __init_subclass__(cls, *, table: str) -> None: ...  # [0010]
    @classmethod  # [0010]
    def ref(cls, id: UUID, /) -> Self: ...  # [0010]
    @classmethod  # [0010]
    def stub(cls, **fields: object) -> Self: ...  # [0010]

def invariant[F](*, fields: Callable[[], tuple[Expr, ...]]) -> Callable[[F], F]: ...

class Index:
    def __init__(self, columns: Callable[[], tuple[Expr, ...]], /) -> None: ...

class Check:
    def __init__(self, predicate: Callable[[], Pred[object]], /) -> None: ...

@dataclass_transform(frozen_default=True, order_default=True, field_specifiers=(column,))
def value[C](cls: type[C], /) -> type[C]: ...
@dataclass_transform(kw_only_default=True, field_specifiers=())
def event[C](*, aggregate: Callable[[], Expr]) -> Callable[[type[C]], type[C]]: ...
@dataclass_transform(kw_only_default=True)
def dto[C](cls: type[C], /) -> type[C]: ...

# --------------------------------------------------------------------------- repositories
class Repository[E]: ...

class Profile(Expr):
    def __init__(self, *fields: Expr, lock: Literal["for_update"] | None = ...) -> None: ...

class Load:
    def __init__(self, *fields: Expr) -> None: ...
    # [0002] 4.7 dependent loads; the type of the loaded value is not tied to the declaration
    @staticmethod  # [0002]
    def when(  # [0007] (was one line, spike 0002)
        condition: Pred[object],
        /,
        *,
        match: Pred[object],
        missing: Literal["error", "none"] = ...,  # [0007] #59 point 3
    ) -> Load: ...  # [0007]
    # [0007] #59 points 2 and 3: the function may return a row set, a list of refs or one ref; the
    # [0007] load arguments are paths of the entity it returns; `missing` only for one ref
    @overload  # [0007]
    @staticmethod  # [0007]
    def after[**P, E: Entity](  # [0007]
        fn: Callable[P, RowSet[E]],
        /,
        *paths: Path[E],
    ) -> Load: ...  # [0007]
    @overload  # [0007]
    @staticmethod  # [0007]
    def after[**P, E: Entity](  # [0007]
        fn: Callable[P, Sequence[E]],  # [0007] round 4: was list[E]
        /,
        *paths: Path[E],
    ) -> Load: ...  # [0007]
    @overload  # [0007]
    @staticmethod  # [0007]
    def after[**P, E: Entity](  # [0007]
        fn: Callable[P, E | None],
        /,
        *paths: Path[E],
        missing: Literal["error", "none"] = ...,
    ) -> Load: ...  # [0007]

class BoundFinder[E, T]:
    def __call__(self, value: T, /) -> E: ...

class Finder[E, T]:
    def __init__(self, column: Column[E, T], /) -> None: ...
    @overload
    def __get__(self, instance: None, owner: type[object], /) -> Self: ...
    @overload
    def __get__(self, instance: Repository[E], owner: type[object], /) -> BoundFinder[E, T]: ...

# S1: a query takes predicates over any entity (the joined set is not tracked)
class Select[R]:
    def join(self, relation: Expr, /, *, outer: bool = ...) -> Self: ...
    def where(self, *preds: Pred[object]) -> Self: ...
    def group_by(self, *columns: Expr) -> Self: ...
    def order_by(self, *columns: Expr) -> Self: ...
    def limit(self, n: int, /) -> Self: ...

def select[R](dto: type[R], /, **columns: Expr) -> Select[R]: ...
def count(column: Expr, /) -> Expr: ...
def query[F: Callable[..., object]](fn: F, /) -> F: ...

# S2: a query that tracks the entities it reads, `SelectFrom[R, O]`
class SelectFrom[R, O]:
    def join[E](
        self, relation: Relation[O, E], /, *, outer: bool = ...
    ) -> SelectFrom[R, O | E]: ...
    def where(self, *preds: Pred[O]) -> SelectFrom[R, O]: ...
    def group_by(self, *columns: OwnedExpr[O]) -> SelectFrom[R, O]: ...

def select_from[R, O](dto: type[R], /, **columns: OwnedExpr[O]) -> SelectFrom[R, O]: ...

# --------------------------------------------------------------------------- use cases
class _Injected: ...

INJECTED: Never
type Now = Annotated[datetime, _Injected]

class Bound: ...

class Usecase[**P]:
    def bind(self, *args: P.args, **kwargs: P.kwargs) -> Bound: ...
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> StepResult: ...

class Step[**P]:
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> StepResult: ...

@overload  # [0002]
def usecase[**P](fn: Callable[P, Changes], /) -> Usecase[P]: ...
@overload  # [0002] 4.6 options form; not checked by spike 0001
def usecase[**P](  # [0002]
    *,  # [0002]
    isolation: Literal["serializable", "repeatable_read"] = ...,  # [0002]
    timeout: str | None = ...,  # [0002]
) -> Callable[[Callable[P, Changes]], Usecase[P]]: ...  # [0002]
def step[**P](fn: Callable[P, Changes], /) -> Step[P]: ...

class Chain:
    def run[**P](
        self, fn: Callable[P, StepResult], /, *args: P.args, **kwargs: P.kwargs
    ) -> None: ...
    @property
    def changes(self) -> Changes: ...

class ChainBlock[*Ts]:
    def __enter__(self) -> tuple[Chain, *Ts]: ...
    def __exit__(self, *exc: object) -> None: ...

def chain[*Ts](*snapshots: *Ts) -> ChainBlock[*Ts]: ...

# --------------------------------------------------------------------------- app
class ConsistencyToken: ...

class RunResult:
    @property
    def token(self) -> ConsistencyToken: ...
    @property  # [0002]
    def run_id(self) -> str: ...  # [0002]
    @property  # [0002]
    def value(self) -> object: ...  # [0002] 4.5 `result.value`; untyped in the design
    @property  # [0002]
    def events(self) -> Sequence[object]: ...  # [0002]
    def created[E](  # [0002]
        self,  # [0002]
        kind: type[E],  # [0002]
        /,  # [0002]
    ) -> Sequence[Id[E]]: ...  # [0002] 4.5 `result.created(Order)`

class App:
    def __init__(self, *, dsn: str) -> None: ...
    async def run(self, bound: Bound, /, *, idempotency_key: str | None = ...) -> RunResult: ...
    async def query[R](self, q: Select[R], /) -> list[R]: ...
    def provide[T](self, kind: type[T], factory: Callable[[], T], /) -> None: ...  # [0002] 4.10

# --------------------------------------------------------------------------- [0002] 4.10 process
class ProcessContext:  # [0002]
    @property  # [0002]
    def idempotency_key(self) -> str: ...  # [0002]

class RetryLater:  # [0002]
    def __init__(self, *, max_attempts: int, within: str) -> None: ...  # [0002]

class DomainError(Exception):  # [0002]
    def __init_subclass__(cls, *, retry_later: RetryLater | None = ...) -> None: ...  # [0002]

def process[F: Callable[..., Awaitable[Bound | None]]](  # [0002] 4.10 `@process(on=Event)`
    *,  # [0002]
    on: type[object],  # [0002]
) -> Callable[[F], F]: ...  # [0002]
