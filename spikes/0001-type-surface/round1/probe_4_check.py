"""Item 4 follow-up: the ADR-0004 examples with the getter form."""

from decimal import Decimal
from typing import reveal_type

from domain import Money
from lib_design import Check, Entity
from lib_embedded_variants import PCol, embedded_p


class OrderB(Entity, table="orders_b"):
    total: PCol[Money] = embedded_p(prefix="total_")


class WalletB(Entity, table="wallets_b"):
    balance: PCol[Money] = embedded_p(prefix="balance_")


def probe(wallet: WalletB, order: OrderB) -> None:
    reveal_type(Check(lambda: OrderB.total.at(lambda m: m.amount) >= 0))  # G1 int literal
    reveal_type(Check(lambda: OrderB.total.at(lambda m: m.amount) >= Decimal(0)))  # G2
    reveal_type(wallet.set(WalletB.balance.at(lambda m: m.amount).add(-order.total.amount)))  # G3
