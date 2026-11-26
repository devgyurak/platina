"""Spike 0007 type reproduction, round 3: nested loads through a nullable single relation."""

from typing import assert_type

from domain import Order, Seat, Show, User
from lib import Profile, RelColumn

assert_type(Order.show.load(Show.seats), RelColumn[Order, Show | None])
assert_type(Order.user.load(User.addresses), RelColumn[Order, User | None])
nullable = Profile(Order.show.load(Show.seats.load(Seat.tickets)), Order.user.load(User.addresses))
