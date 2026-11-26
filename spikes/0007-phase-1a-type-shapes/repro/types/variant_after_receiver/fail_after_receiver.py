"""Variant probe: Load.after(fn).load(*paths) - E fixed by the receiver."""

from domain import Order, Stock, Variant, Wallet
from lib import Load, RowSet


def payer_wallet(order: Order) -> Wallet | None:
    return None if order.user_id is None else Wallet.ref(order.user_id)


def stocks_of(order: Order) -> RowSet[Stock]:
    return Stock.where(Stock.variant_id.in_([i.variant_id for i in order.items]))


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


ok1 = Load.after(payer_wallet, missing="none").load(Wallet.user_id)
ok2 = Load.after(stocks_of).load(Stock.warehouse)
ok3 = Load.after(variants_of).load(Variant.stocks.load(Stock.warehouse))
# fmt: off
g1 = Load.after(payer_wallet).load(Order.items)  # expect-error[reportArgumentType, arg-type]: G1 not a path of Wallet
g2 = Load.after(payer_wallet, missing="none").load(Order.items)  # expect-error[reportArgumentType, arg-type]: G2 not a path of Wallet
g4 = Load.after(stocks_of).load(Order.items)  # expect-error[reportArgumentType, arg-type]: G4 not a path of Stock
g5 = Load.after(variants_of).load(Order.items)  # expect-error[reportArgumentType, arg-type]: F17 not a path of Variant
# fmt: on
