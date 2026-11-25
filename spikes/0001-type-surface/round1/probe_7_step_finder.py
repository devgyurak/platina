"""Item 7: + between StepResults; Finder argument types."""

from typing import reveal_type
from uuid import UUID

from domain import Coupon, Order, OrderRepo, User, Wallet, apply_coupon, orders, pay, wallets
from lib_design import Id


def probe(
    order: Order, wallet: Wallet, coupon: Coupon, uid: Id[User], oid: Id[Order], raw: UUID
) -> None:
    reveal_type(apply_coupon(order, coupon))
    reveal_type(order.set() + wallet.set())
    apply_coupon(order, coupon) + pay(order, wallet)  # S1 + between StepResults
    order.set() + pay(order, wallet)  # S2 Changes + StepResult

    reveal_type(OrderRepo.by_number)
    reveal_type(orders.by_number)
    reveal_type(orders.by_number("A-1"))
    reveal_type(wallets.by_user(uid))
    orders.by_number(42)  # F1 int is not str
    wallets.by_user(oid)  # F2 Id[Order] is not Id[User]
    wallets.by_user(raw)  # O1 plain UUID for an Id[User] column
