"""Spike 0007 type reproduction, round 4: lines both checkers must reject."""

from domain import Allocation, Item, Order, Stock, Variant, Warehouse
from lib import Load, Profile


def variants_tuple(order: Order) -> tuple[Variant, ...]:
    return tuple(Variant.ref(i.variant_id) for i in order.items)


# fmt: off
f30 = Order.items.load(Item.quantity)  # expect-error[reportArgumentType, arg-type]: F30 a column is not a load path
f31 = Stock.warehouse.load(Warehouse.group)  # expect-error[reportArgumentType, arg-type]: F31 a column is not a load path
g1 = Order.items.load(Item.allocations.load(Allocation.quantity))  # expect-error[reportArgumentType, arg-type]: G1 a column one level deeper
g2 = Profile(Order.items.load(Item.quantity))  # expect-error[reportArgumentType, arg-type]: G2 a column inside Profile
g3 = Load.after(variants_tuple, Variant.sku)  # expect-error[reportArgumentType, reportCallIssue, reportUnknownVariableType, call-overload]: G3 a column as a Load.after path
g4 = Load.after(variants_tuple, Order.items)  # expect-error[reportArgumentType, reportCallIssue, reportUnknownVariableType, arg-type]: G4 tuple form, not a path of Variant
g5 = Order.where(Stock.allocated <= Stock.quantity)  # expect-error[reportArgumentType, operator]: G5 a predicate over another entity (mypy: operator, reads Stock.quantity as int)
g6 = Stock.allocated <= Stock.warehouse_id  # expect-error[reportOperatorIssue, reportUnknownVariableType, operator]: G6 int against Id[Warehouse]
# fmt: on
