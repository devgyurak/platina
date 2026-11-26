"""Own probe: what E is solved to when fn returns Wallet | None and the path is Order's."""

from collections.abc import Callable
from typing import reveal_type

from domain import Order, Wallet
from lib import Entity, OwnedExpr, RowSet


def after_one[**P, E: Entity](fn: Callable[P, E | None], /, *paths: OwnedExpr[E]) -> E: ...  # type: ignore[empty-body]
def payer_wallet(order: Order) -> Wallet | None:
    return None if order.user_id is None else Wallet.ref(order.user_id)


reveal_type(after_one(payer_wallet, Order.items))
reveal_type(after_one(payer_wallet))


def any_rows() -> RowSet[Stock_]:
    return Entity.where()  # contravariant RowSet: a RowSet[Entity] passes as RowSet[Stock]


from domain import Stock as Stock_  # noqa: E402
