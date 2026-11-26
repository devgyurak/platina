"""Round 4 own probe: a cross-entity column predicate inside Order.where, per checker."""

from domain import Order, SeatHold, Wallet
from lib import RowSet

w1 = Order.where(Order.user_id == Wallet.user_id)  # line 6: ==, nullable vs non-null
w2 = Order.where(Order.expires_at <= SeatHold.expires_at)  # line 7: <=, same type
w3 = Order.where(Order.expires_at == SeatHold.expires_at)  # line 8: ==, same type
w4 = Order.where(Order.expires_at > SeatHold.expires_at)  # line 9: >, same type
r: RowSet[Order] = w2
