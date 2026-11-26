"""Spike 0007 round 6: the owner variance of `Relation` / `RelColumn` without `Path`. Run per checker.

Round 5's `Path[O]` base made the owner of `Relation` and `RelColumn` invariant (inferred); with
`Path` removed it is inferred covariant, like `Column`'s (declared). `run.sh` runs this file
against both stubs: the round-5 stub rejects both lines, the round-6 stub accepts both.
"""

from domain import Item, Order, Show, Wallet
from lib import Relation, RelColumn

v1: Relation[Wallet | Order, Item] = Order.items.load()  # V1 a widened owner, through a call
v2: RelColumn[Wallet | Order, Show | None] = Order.show.load()  # V2 the same for a many-to-one
