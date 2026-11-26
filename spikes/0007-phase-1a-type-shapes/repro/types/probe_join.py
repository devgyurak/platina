"""Own probe: is E of Load.after solved from fn and paths together (spike 0001 P-A)?"""

from typing import reveal_type

from domain import Order, Stock, Variant, Wallet
from lib import Entity, Load, RowSet


def payer_wallet(order: Order) -> Wallet | None:
    return None if order.user_id is None else Wallet.ref(order.user_id)


def one_wallet(order: Order) -> Wallet:
    return Wallet.ref(order.id)


def stocks_of(order: Order) -> RowSet[Stock]:
    return Stock.where(Stock.variant_id.in_([i.variant_id for i in order.items]))


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


g1 = Load.after(payer_wallet, Order.items)  # G1 path of Order on a Wallet | None load
g2 = Load.after(payer_wallet, Order.items, missing="none")  # G2 the same with missing=
g3 = Load.after(one_wallet, Order.items)  # G3 a function returning Wallet (no None)
g4 = Load.after(stocks_of, Order.items)  # G4 path of Order on a RowSet[Stock] load
g5 = Load.after(variants_of, Order.items)  # G5 = F17
rs: RowSet[Entity] = Stock.where()  # G6 RowSet variance (is it covariant?)
reveal_type(Order.payments)
