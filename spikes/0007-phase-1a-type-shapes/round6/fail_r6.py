"""Spike 0007 round 6: misuse of the receiver form of `Load.after` both checkers must reject.

F17, F18 and F21-F23 in the receiver form are in `fail_shapes.py` here (a copy of `../fail_shapes.py`);
this file adds the lines the receiver form raises on its own (G1-G8), and G9 / G10 (added after
the reproduction): `.count()` / `.exists()` are not load paths. Written outside
`Annotated[...]` (X1; `probe_annotated.py` here).
"""

from domain import Item, Order, Seat, SeatHold, Show, Stock, Variant, Wallet, wallets
from lib import Load, RowSet


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


def stocks_of(order: Order) -> RowSet[Stock]:
    return Stock.where(Stock.variant_id.in_([i.variant_id for i in order.items]))


def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.user_id is not None else None


def seats_of(show: Show) -> RowSet[Seat]:
    return Seat.where(Seat.show_id == show.id)


# fmt: off
g1 = Load.after(stocks_of).load(Stock.quantity)  # expect-error[reportArgumentType, arg-type]: G1 a column is not a load path (F30 in the receiver form)
g2 = Load.after(point_wallet).load(Wallet.balance)  # expect-error[reportArgumentType, arg-type]: G2 a column under the one-ref form (F31)
g3 = Load.after(variants_of).load(Stock.warehouse)  # expect-error[reportArgumentType, arg-type]: G3 a skipped level (F14)
g4 = Load.after(variants_of).load(Variant.stocks.load(Order.payments))  # expect-error[reportArgumentType, arg-type]: G4 a wrong owner one level deeper (F15)
g5 = Load.after(variants_of, Variant.stocks)  # expect-error[reportCallIssue, reportUnknownVariableType, call-overload]: G5 round 5's positional paths
g6 = Load.after(variants_of, missing="none")  # expect-error[reportArgumentType, reportUnknownVariableType, call-overload]: G6 missing= on the list form
g7 = Load.after(point_wallet).load(Order.items, missing="none")  # expect-error[reportCallIssue, reportUnknownVariableType, call-arg, arg-type]: G7 missing= on .load
g8 = Load.after(seats_of).load(Seat.holds, SeatHold.seat_id)  # expect-error[reportArgumentType, arg-type]: G8 a good path then a column
g9 = Order.items.load(Item.allocations.count())  # expect-error[reportArgumentType, arg-type]: G9 a nested partial count is not a load path
g10 = Load.after(seats_of).load(Seat.holds.exists())  # expect-error[reportArgumentType, arg-type]: G10 nor a nested existence check
# fmt: on
