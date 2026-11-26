"""Round 4 own probe: F21 through one widening annotation, per checker."""

from domain import Item, Order, Wallet
from lib import Load, Relation


def payer_wallet(order: Order) -> Wallet | None:
    return None if order.user_id is None else Wallet.ref(order.user_id)


wide: Relation[Wallet | Order, Item] = Order.items  # line 11: the widening
bypass = Load.after(payer_wallet, wide)  # line 12: F21 through the annotation
