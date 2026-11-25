"""P-A follow-up S3: does an explicit root make both checkers agree on the entity set?"""

from typing import reveal_type

from domain_final import Item, Order, OrderSummary, User, Wallet
from lib_final import Id
from lib_query_root import select_root


def s3(uid: Id[User]) -> None:
    q = select_root(OrderSummary, Order, id=Order.id, number=Order.number)
    reveal_type(q)
    select_root(OrderSummary, Order, id=Order.id, item=Item.id)  # R1 Item column before the join
    j = q.join(Order.items, outer=True)
    reveal_type(j)
    reveal_type(j.where(Order.user_id == uid, Item.position < 3))
    j.where(Wallet.user_id == uid)  # R2 not joined
