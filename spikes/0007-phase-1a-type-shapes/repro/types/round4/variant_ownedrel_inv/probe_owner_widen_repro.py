"""Round 4 own probe (d): a declared type that widens a relation's owner, per checker."""

from domain import Item, Money, Order, Transfer
from lib import Changes, Entity, OwnedRelation, Relation, insert


def widen_union(t: Transfer | Order, item: Item) -> Changes:
    rel: OwnedRelation[Transfer | Order, Item] = Order.items  # line 8: the widening
    return insert(t, rel.add(item))  # line 9: F11 through the annotation


def widen_plain(m: Money, item: Item) -> Changes:
    t = Transfer(amount=m)
    rel: OwnedRelation[Transfer | Order, Item] = Order.items  # line 14
    return insert(t, rel.add(item))  # line 15: t is a plain Transfer


def widen_entity(item: Item) -> None:
    rel: OwnedRelation[Entity, Item] = Order.items  # line 19: widen to the base
    view: Relation[Entity, Item] = Order.items.where()  # line 20: the read-only view
    del rel, view


def widen_set(o: Transfer, item: Item) -> Changes:
    rel: OwnedRelation[Transfer | Order, Item] = Order.items  # line 25
    return o.set(rel.add(item))  # line 26: another entity's add through .set
