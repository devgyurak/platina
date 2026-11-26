"""Spike 0007 type reproduction, round 6: can a declared type widen an owner into `.load`?

Run per checker. W1-W5 are round 4's probe in the reproducer's words (W5 in the receiver form);
W6-W16 are the reproducer's own: the widening moved onto the `LoadAfter` itself, a function
whose result is a union of entities, and the variance of `LoadAfter`.
"""

from collections.abc import Sequence

from domain import Item, Money, Order, Seat, Transfer, Variant, Wallet, wallets
from lib import Changes, Load, LoadAfter, OwnedRelation, Relation, RowSet, insert


def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.user_id is not None else None


def wallet_or_order(order: Order) -> Sequence[Wallet | Order]:
    return [order]


def widen(amount: Money, item: Item) -> Changes:
    rel: OwnedRelation[Transfer | Order, Item] = Order.items  # W1 on the class access
    t: Transfer = Transfer(amount=amount)
    return insert(t, rel.add(item))  # W2 F11 through W1


def through_a_variable() -> object:
    x = Order.items
    rel: OwnedRelation[Transfer | Order, Item] = x  # W3 the same through a variable
    return rel


wide: Relation[Wallet | Order, Item] = Order.items  # W4 a widened Relation
w5 = Load.after(point_wallet).load(wide)  # W5 F21 through W4, receiver form

wide_after: LoadAfter[Wallet | Order] = Load.after(point_wallet)  # W6 a widened LoadAfter
w7 = wide_after.load(Order.items)  # W7 F21 through W6
w8 = Load.after(wallet_or_order).load(Order.items)  # W8 a union result takes either's path


def la_widen(a: LoadAfter[Order]) -> LoadAfter[Wallet | Order]:
    return a  # W9 the variance of LoadAfter (covariant?)


def la_narrow(a: LoadAfter[Wallet | Order]) -> LoadAfter[Order]:
    return a  # W10 the variance of LoadAfter (contravariant?)


def seats_near(seat: Seat) -> RowSet[Seat]:
    return Seat.where(Seat.show_id == seat.show_id)


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


# W11-W13: W6/W7 for each return form, in one statement each
w11: LoadAfter[Variant | Order] = Load.after(variants_of).load(Order.items)  # W11 list form
w12: LoadAfter[Seat | Order] = Load.after(seats_near).load(Order.items)  # W12 row-set form
w13: Load = Load.after(point_wallet).load(Order.items)  # W13 a plain Load as the declared type

# W14, W15: W6/W7 in two statements for the list and the row-set forms
w14: LoadAfter[Variant | Order] = Load.after(variants_of)  # W14 list form, declared wider
w14_load = w14.load(Order.items)  # W14 then a path of Order
w15: LoadAfter[Seat | Order] = Load.after(seats_near)  # W15 row-set form, declared wider
w15_load = w15.load(Order.items)  # W15 then a path of Order

# W16: W7 through a variable (the class access is not an argument, so no descriptor solving)
items_var = Order.items
w16 = wide_after.load(items_var)  # W16
