# pyright: reportInvalidTypeVarUse=false
# ^ Finding L1 of the write-up (field specifiers solve T from the annotation only).
"""Spike 0002: copy of spike 0001's final stub `round2/lib_final_declared.pyi` plus additions.

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
    @overload  # type: ignore[override]  # [0007] repro: #51 (mypy reports here)
    def __eq__[O2](self, other: Column[O2, _T], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __eq__[O2](self, other: Column[O2, _T | None], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __eq__[O2, U](
        self: Column[_O_co, U | None], other: Column[O2, U], /
    ) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __eq__(self, other: _T, /) -> Pred[_O_co]: ...  # pyright: ignore[reportIncompatibleMethodOverride]  # [0007] pyright reports here
    @overload  # type: ignore[override]  # [0007] repro: #51 (mypy reports here)
    def __ne__[O2](self, other: Column[O2, _T], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __ne__[O2](self, other: Column[O2, _T | None], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __ne__[O2, U](
        self: Column[_O_co, U | None], other: Column[O2, U], /
    ) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __ne__(self, other: _T, /) -> Pred[_O_co]: ...  # pyright: ignore[reportIncompatibleMethodOverride]  # [0007] pyright reports here
    @overload  # [0007] repro: #51
    def __lt__[O2](self, other: Column[O2, _T], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __lt__[O2](self, other: Column[O2, _T | None], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __lt__[O2, U](
        self: Column[_O_co, U | None], other: Column[O2, U], /
    ) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __lt__(self, other: _T, /) -> Pred[_O_co]: ...  # [0007]
    @overload  # [0007] repro: #51
    def __ge__[O2](self, other: Column[O2, _T], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __ge__[O2](self, other: Column[O2, _T | None], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __ge__[O2, U](
        self: Column[_O_co, U | None], other: Column[O2, U], /
    ) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __ge__(self, other: _T, /) -> Pred[_O_co]: ...  # [0007]
    @overload  # [0007] repro: #51
    def __gt__[O2](self, other: Column[O2, _T], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __gt__[O2](self, other: Column[O2, _T | None], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __gt__[O2, U](
        self: Column[_O_co, U | None], other: Column[O2, U], /
    ) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __gt__(self, other: _T, /) -> Pred[_O_co]: ...  # [0007]
    @overload  # [0007] repro: #51
    def __le__[O2](self, other: Column[O2, _T], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __le__[O2](self, other: Column[O2, _T | None], /) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __le__[O2, U](
        self: Column[_O_co, U | None], other: Column[O2, U], /
    ) -> Pred[_O_co | O2]: ...  # [0007]
    @overload  # [0007]
    def __le__(self, other: _T, /) -> Pred[_O_co]: ...  # [0007]
    def in_(self, values: Iterable[_T], /) -> Pred[_O_co]: ...  # [0007]

class Relation[O, E](OwnedExpr[O]):  # [0007] repro: base OwnedExpr[O]
    """Class access of a relation of O with children E that is not owned: read and load only."""

    def count(self) -> Expr: ...
    def where(self, *preds: Pred[E]) -> Relation[O, E]: ...  # [0002]
    def exists(self) -> Expr: ...
    def load(self, *paths: OwnedExpr[E]) -> Self: ...  # [0007] repro: nested path (#59.1)

_O_inv = TypeVar("_O_inv")  # [0007] repro: RelOp's owner is invariant (F11)

class RelOp[O](Op[O]):  # variant: owner variance inferred
    """A relation operation on an owned relation of O."""

class OwnedRelation[O, E](Relation[O, E]):  # [0007] repro: owned relations only (#60.4)
    def add(self, item: E, /) -> RelOp[O]: ...  # [0007]
    def remove(self, item: E, /) -> RelOp[O]: ...  # [0007]
    def update(self, item: E, /, *ops: Op[E]) -> RelOp[O]: ...  # [0007]

class RelColumn[O, T](OwnedExpr[O]):  # [0007] repro: base OwnedExpr[O]
    """Class access of a single-valued relation (`Order.user`)."""

    def load(self, *paths: OwnedExpr[T]) -> Self: ...  # [0007] repro

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

class Owned[T]:  # [0007] repro: an owned=True relation
    @overload  # [0007]
    def __get__[O, E](
        self: Owned[list[E]], instance: None, owner: type[O], /
    ) -> OwnedRelation[O, E]: ...  # [0007]
    @overload  # [0007]
    def __get__[E](
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
def embedded[T](*, prefix: str) -> Col[T]: ...
def version_column(*, init: Literal[False] = False) -> Col[int]: ...
def many_to_one[T](*, via: Callable[[], Expr], init: Literal[False] = False) -> Rel[T]: ...
@overload  # [0007] repro
def one_to_many[T](  # [0007]
    target: Callable[[], Expr],  # [0007]
    /,  # [0007]
    *,  # [0007]
    owned: Literal[True],  # [0007]
    order_by: Callable[[], Expr] | None = ...,  # [0007]
    init: Literal[False] = False,  # [0007]
) -> Owned[T]: ...  # [0007]
@overload  # [0007]
def one_to_many[T](  # [0007]
    target: Callable[[], Expr],  # [0007]
    /,  # [0007]
    *,  # [0007]
    owned: Literal[False] = ...,  # [0007]
    order_by: Callable[[], Expr] | None = ...,  # [0007]
    init: Literal[False] = False,  # [0007]
) -> Rel[T]: ...  # [0007]
def parent_fk[T](
    target: Callable[[], type[object]], /, *, init: Literal[False] = False
) -> Col[T]: ...  # [0007] #49
def server_now() -> Expr: ...

# --------------------------------------------------------------------------- changes
class Changes:
    def __add__(self, other: Changes, /) -> Changes: ...
    def returning(self, value: object, /) -> Changes: ...

class SetChange[O](Changes):
    def set(self, *ops: Op[O], unsafe_bypass: str | None = ...) -> SetChange[O]: ...  # [0002] 4.13
    def emit_each(self, event: type[object], /, **fields: OwnedExpr[O]) -> SetChange[O]: ...

class RowSet[E]:  # [0007] repro: Entity.where(...); not a Changes
    def set(self, *ops: Op[E], unsafe_bypass: str | None = ...) -> SetChange[E]: ...  # [0007]
    def delete(self) -> Changes: ...  # [0007]

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
def insert[E: Entity](entity: E, /, *ops: RelOp[E]) -> Changes: ...  # [0007] repro (#60)
def insert_all(entities: Iterable[Entity], /) -> Changes: ...  # [0002] 4.8 `insert_all(...)`

# --------------------------------------------------------------------------- declarations
@dataclass_transform(
    kw_only_default=True,
    frozen_default=True,
    field_specifiers=(
        column,
        pk,
        fk,
        parent_fk,
        embedded,
        version_column,
        many_to_one,
        one_to_many,
    ),  # [0007]
)
class Entity:
    def __init_subclass__(cls, *, table: str, aggregate_root: bool = ...) -> None: ...
    @classmethod
    def ref(cls, id: UUID, /, *, expected_version: int | None = ...) -> Self: ...
    @classmethod
    def where(cls, *preds: Pred[Self]) -> RowSet[Self]: ...  # [0007] repro
    @classmethod
    def stub(cls, **fields: object) -> Self: ...
    def set(self, *ops: Op[Self], unsafe_bypass: str | None = ...) -> Changes: ...
    def delete(self) -> Changes: ...  # [0007] repro (#57)

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
    def when(  # [0007] repro
        condition: Pred[object],
        /,
        *,
        match: Pred[object],
        missing: Literal["error", "none"] = ...,  # [0007]
    ) -> Load: ...  # [0007]
    @overload  # [0007] repro: a row set
    @staticmethod
    def after[**P, E: Entity](
        fn: Callable[P, RowSet[E]], /, *paths: OwnedExpr[E]
    ) -> Load: ...  # [0007]
    @overload  # [0007] repro: a list of refs
    @staticmethod
    def after[**P, E: Entity](
        fn: Callable[P, list[E]], /, *paths: OwnedExpr[E]
    ) -> Load: ...  # [0007]
    @overload  # [0007] repro: one ref or None
    @staticmethod
    def after[**P, E: Entity](  # [0007]
        fn: Callable[P, E | None],
        /,
        *paths: OwnedExpr[E],
        missing: Literal["error", "none"] = ...,  # [0007]
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
