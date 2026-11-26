"""Round 6: a copy of `../probe_owner_widen.py` with the `Load.after` lines in the receiver form; every changed
line carries `# [r6]`.

Spike 0007, round 4: can a declared type widen a relation's owner? Run per checker.

Independent review observation, rerun here; cause corrected by the round-4 reproduction: mypy
solves the descriptor's owner from the declared type when the annotation sits directly on the
class access (`rel: X = Order.items`), and then rejects nothing; through a variable it rejects
the widening. pyright rejects every widening line.
"""

from domain import Item, Money, Order, Transfer, Wallet, wallets
from lib import Changes, Load, OwnedRelation, Relation, insert


def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.user_id is not None else None


def widen(amount: Money, item: Item) -> Changes:
    rel: OwnedRelation[Transfer | Order, Item] = Order.items  # W1 on the class access
    t: Transfer = Transfer(amount=amount)
    return insert(t, rel.add(item))  # W2 F11 through W1 (a plain Transfer)


def through_a_variable() -> object:
    x = Order.items
    rel: OwnedRelation[Transfer | Order, Item] = x  # W3 the same widening through a variable
    return rel


wide: Relation[Wallet | Order, Item] = Order.items  # W4 a widened Relation
path_bypass = Load.after(point_wallet).load(wide)  # [r6] W5 F21 through W4
