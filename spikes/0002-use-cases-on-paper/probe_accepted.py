"""Lines both checkers ACCEPT that a reader of section 4 would expect to be rejected or undefined.

Each is a place where the types do not carry the rule, so the rule is left to seal, to the runtime
or to the design text. Run directly through both checkers; no line here should report an error.
"""

from decimal import Decimal
from typing import Annotated

from domain import (
    Coupon,
    Item,
    Money,
    Order,
    OrderPaid,
    Payment,
    PaymentMethod,
    PaymentRequested,
    Stock,
    Transfer,
    Wallet,
)
from lib import Bound, Changes, Finder, Load, ProcessContext, Repository, process, usecase
from uc02_refund import order_coupon

# 1. `Load.after`'s function returns `Coupon | None`; the declared parameter is `Wallet | None`.
#    The metadata is not tied to the annotated type (and mypy does not check it at all).
type MismatchedAfter = Annotated[Wallet | None, Load.after(order_coupon)]


# 2. `@process(on=OrderPaid)` on a handler whose event parameter is `PaymentRequested`.
@process(on=OrderPaid)
async def wrong_event(e: PaymentRequested, ctx: ProcessContext) -> Bound | None:
    return None


# 3. Two ways to write an owned child: through the root's relation (bumps the root's version,
#    4.4) and directly on the child snapshot (does it?).
def child_writes(order: Order, item: Item) -> Changes:
    via_root = order.set(Order.items.update(item, Item.quantity.to(2)))
    direct = item.set(Item.quantity.to(2))
    return via_root + direct


# 4. `.set` on an entity created in this function (not a loaded snapshot).
def set_on_new() -> Changes:
    t = Transfer(amount=Money(Decimal(1)))
    return t.set(Transfer.amount.to(Money(Decimal(2))))


# 5. A Finder on a non-unique column types as "one row".
class StockRepo(Repository[Stock]):
    by_variant = Finder(Stock.variant_id)


# 6. A child added to one parent with another parent's key (#49): the redundant key can disagree.
def wrong_parent(order: Order, other: Order) -> Changes:
    p = Payment(order_id=other.id, method=PaymentMethod.WALLET, amount=order.total)
    return order.set(Order.payments.add(p))


# 7. An empty `Changes` - not in the design; exists only because the stub class has the default
#    constructor.
@usecase
def nothing(order: Annotated[Order, Load()]) -> Changes:
    return Changes()


# 8. `Coupon.ref(...)` takes any UUID: a ref of one entity built from another entity's key.
def wrong_ref(order: Order) -> Coupon:
    return Coupon.ref(order.id)
