"""[repro] reveal_type on the items of probe_accepted.py: is any of them accepted through Any/Unknown?"""

from typing import Annotated, reveal_type

from domain import Coupon, Order, OrderPaid, Payment, PaymentMethod, PaymentRequested, Stock, Wallet
from lib import Bound, Changes, Finder, Load, ProcessContext, Repository, process
from uc02_refund import order_coupon

# item 1
reveal_type(Load.after(order_coupon))
type MismatchedAfter = Annotated[Wallet | None, Load.after(order_coupon)]


# item 2
@process(on=OrderPaid)
async def wrong_event(e: PaymentRequested, ctx: ProcessContext) -> Bound | None:
    return None


reveal_type(wrong_event)
reveal_type(process(on=OrderPaid))


# item 5
class StockRepo(Repository[Stock]):
    by_variant = Finder(Stock.variant_id)


reveal_type(StockRepo.by_variant)
reveal_type(StockRepo().by_variant)


def item5(v: Stock) -> None:
    reveal_type(StockRepo().by_variant(v.variant_id))


# item 6
def wrong_parent(order: Order, other: Order) -> Changes:
    reveal_type(other.id)
    reveal_type(Payment.order_id)
    p = Payment(order_id=other.id, method=PaymentMethod.WALLET, amount=order.total)
    reveal_type(Order.payments.add(p))
    return order.set(Order.payments.add(p))


# item 8
def wrong_ref(order: Order) -> Coupon:
    reveal_type(order.id)
    reveal_type(Coupon.ref)
    reveal_type(Coupon.ref(order.id))
    return Coupon.ref(order.id)
