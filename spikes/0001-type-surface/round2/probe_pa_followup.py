"""P-A follow-up (after reproduction): S3 with two entities' columns; Column variance per checker."""

from typing import reveal_type

from domain_final import Item, Order, OrderSummary, User, Wallet
from lib_final import Column, Id
from lib_query_root import select_root


def s3_two_entities(uid: Id[User]) -> None:
    q = select_root(OrderSummary, Order, id=Order.id, item=Item.id)
    reveal_type(q)
    q.where(Wallet.user_id == uid)  # R3 not joined, two-entity root query


def variance(c: Column[Order, object]) -> None:
    x: Column[Order, int] = c  # V1 object -> int: contravariant accepts, invariant rejects
    reveal_type(x)
