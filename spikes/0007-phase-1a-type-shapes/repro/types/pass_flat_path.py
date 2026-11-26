"""Own probe: the flat, ambiguous path #59 makes a seal error - neither checker rejects it."""

from domain import Allocation, Item, Order
from lib import Load, Profile

flat_profile = Profile(Order.items, Item.allocations, Allocation.stock)  # seal error (#59 point 1)
flat_load = Load(Order.items, Item.allocations)  # seal error (#59 point 1)
