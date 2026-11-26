"""Spike 0007 type reproduction, round 6 (type-reviewer): lines both checkers must reject.

The receiver form of `Load.after` on the reproducer's own stub. H1-H5 are the write-up's F17, F18,
F21, F22, F23 rewritten by the reproducer; H6-H15 are the write-up's G-lines (and round 5's
positional form for each overload) in the reproducer's words; H16-H20 are the reproducer's own.
Codes are the ones observed.
"""

from datetime import datetime

from domain import Item, Order, Seat, SeatHold, Show, Stock, Variant, Wallet, Warehouse, wallets
from lib import Load, RowSet

NOW = datetime(2026, 11, 26)


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


def active_holds(seat: Seat) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.expires_at > NOW)


def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.user_id is not None else None


def stocks_of(order: Order) -> RowSet[Stock]:
    return Stock.where(Stock.variant_id.in_([i.variant_id for i in order.items]))


def shows_of(order: Order) -> RowSet[Show]:
    return Show.where(Show.name == order.number)


# fmt: off
h1 = Load.after(variants_of).load(Order.items)  # expect-error[reportArgumentType, arg-type]: H1 = F17 list form, a path of Order
h2 = Load.after(active_holds, missing="none")  # expect-error[reportArgumentType, reportUnknownVariableType, call-overload]: H2 = F18 missing= on a row-set function
h3 = Load.after(point_wallet).load(Order.items)  # expect-error[reportArgumentType, arg-type]: H3 = F21 one ref, a path that is not of Wallet
h4 = Load.after(point_wallet, missing="none").load(Order.items)  # expect-error[reportArgumentType, arg-type]: H4 = F22 the same with missing=
h5 = Load.after(active_holds).load(Order.items)  # expect-error[reportArgumentType, arg-type]: H5 = F23 row set, a path that is not of SeatHold
h6 = Load.after(stocks_of).load(Stock.quantity)  # expect-error[reportArgumentType, arg-type]: H6 = G1 a column is not a path
h7 = Load.after(point_wallet).load(Wallet.balance)  # expect-error[reportArgumentType, arg-type]: H7 = G2 an embedded column is not a path
h8 = Load.after(variants_of).load(Stock.warehouse)  # expect-error[reportArgumentType, arg-type]: H8 = G3 a skipped level
h9 = Load.after(variants_of).load(Variant.stocks.load(Order.items))  # expect-error[reportArgumentType, arg-type]: H9 = G4 a wrong owner one level deeper
h10 = Load.after(variants_of, Variant.stocks)  # expect-error[reportCallIssue, reportUnknownVariableType, call-overload]: H10 = G5 round 5's positional path, list form
h11 = Load.after(point_wallet, Order.items)  # expect-error[reportCallIssue, reportUnknownVariableType, call-overload]: H11 round 5's positional path, one ref
h12 = Load.after(stocks_of, Stock.warehouse)  # expect-error[reportCallIssue, reportUnknownVariableType, call-overload]: H12 round 5's positional path, row set, even a right one
h13 = Load.after(variants_of, missing="none")  # expect-error[reportArgumentType, reportUnknownVariableType, call-overload]: H13 = G6 missing= on the list form
h14 = Load.after(variants_of).load(Variant.stocks, missing="none")  # expect-error[reportCallIssue, reportUnknownVariableType, call-arg]: H14 = G7 missing= on .load, with a right path
h15 = Load.after(stocks_of).load(Stock.warehouse, Warehouse.group)  # expect-error[reportArgumentType, arg-type]: H15 = G8 a good path, then a column
h16 = Load.after(shows_of).load(Order.show)  # expect-error[reportArgumentType, arg-type]: H16 own: the relation that leads to Show, not one of Show
h17 = Load.after(shows_of).load(Order.show.load(Show.seats))  # expect-error[reportArgumentType, arg-type]: H17 own: an Order path under a Show function
h18 = Load.after(variants_of).load(Variant.stocks).load(Item.allocations)  # expect-error[reportArgumentType, arg-type]: H18 own: a wrong path in the second link of a chain
h19 = Load.after(point_wallet, "none")  # expect-error[reportCallIssue, reportUnknownVariableType, call-overload]: H19 own: missing= is keyword-only
h20 = Load.after(variants_of).load(Variant.stocks).load(missing="none")  # expect-error[reportCallIssue, reportUnknownVariableType, call-arg]: H20 own: missing= on a chained .load with no path
# fmt: on
