"""Spike 0006, observation O5: `== None` / `!= None` on a nullable and on a non-null column.

Run directly through both checkers; the verdicts and revealed types are recorded, not pinned
(the meaning of `== None` is decided in #9).
"""

from typing import reveal_type

from domain import Order

reveal_type(Order.guest_id == None)  # noqa: E711 - the probe; nullable column
reveal_type(Order.guest_id != None)  # noqa: E711 - the probe
reveal_type(Order.user_id == None)  # noqa: E711 - the probe; non-null column
reveal_type(Order.user_id != None)  # noqa: E711 - the probe
reveal_type(Order.guest_id.__eq__(None))
reveal_type(Order.user_id.__eq__(None))
reveal_type(Order.guest_id >= None)  # ordering against None (found by the reproduction)
