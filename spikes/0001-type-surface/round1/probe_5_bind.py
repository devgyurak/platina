"""Item 5: bind with ParamSpec, INJECTED defaults, refs as entities."""

from datetime import datetime
from typing import reveal_type
from uuid import UUID

from domain import ChargeableWallet, Order, PayableOrder, User, Wallet, pay, wallets
from lib_design import INJECTED, Changes, Id, Now, Retry, usecase


def probe(oid: UUID, uid: Id[User], order: Order, wallet: Wallet, now: datetime) -> None:
    reveal_type(pay)
    reveal_type(pay.bind)
    reveal_type(INJECTED)
    reveal_type(Order.ref(oid))
    reveal_type(Order.ref(oid, expected_version=3))
    reveal_type(wallets.by_user(uid))
    reveal_type(pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid)))
    reveal_type(pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid), now=now))  # O1
    reveal_type(pay.bind(Order.ref(oid), wallets.by_user(uid)))  # O2 positional
    reveal_type(pay(order, wallet, now=now))  # direct call (4.12)
    reveal_type(pay(order, wallet))  # O3 direct call without now

    pay.bind(order=oid, wallet=wallets.by_user(uid))  # B1 UUID is not Order
    pay.bind(ordr=Order.ref(oid), wallet=wallets.by_user(uid))  # B2 name typo
    pay.bind(order=Order.ref(oid))  # B3 missing wallet
    pay.bind(order=wallets.by_user(uid), wallet=Order.ref(oid))  # B4 swapped
    pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid), now="now")  # B5 str is not datetime


# the options form of the decorator (4.6)
@usecase(isolation="serializable", retry=Retry(max_attempts=4, on_unique=False), timeout="2s")
def pay2(order: PayableOrder, wallet: ChargeableWallet, now: Now = INJECTED) -> Changes:
    return order.set(Order.paid_at.to(now))


def probe_options(oid: UUID, uid: Id[User]) -> None:
    reveal_type(pay2)
    reveal_type(pay2.bind(order=Order.ref(oid), wallet=wallets.by_user(uid)))
    pay2.bind(order=oid, wallet=wallets.by_user(uid))  # B6 UUID is not Order


@usecase
def not_changes(order: Order) -> int:  # B7 a use case must return Changes
    return 1
