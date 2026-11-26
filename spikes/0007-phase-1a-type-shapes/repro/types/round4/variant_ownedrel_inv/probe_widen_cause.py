"""Round 4 own probe: is mypy's owner widening the descriptor solving O from the context?"""

from domain import Item, Order, Payment
from lib import Column, Entity, OwnedRelation, Relation

x = Order.items
via_var: OwnedRelation[Entity, Item] = x  # line 7: no context at the class access
direct: OwnedRelation[Entity, Item] = Order.items  # line 8: context at the class access
plain: Relation[Entity, Payment] = Order.payments  # line 9: a relation that is not owned (Rel)
col: Column[Entity, int] = Item.quantity  # line 10: a column (Col)
