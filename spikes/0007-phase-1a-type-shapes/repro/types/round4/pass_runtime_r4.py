"""Spike 0007 type reproduction, round 4: R16-R18, which both checkers must accept."""

from typing import Annotated

from domain import Item, Order, OrderStatus, PaymentMethod, Wallet
from lib import (
    INJECTED,
    Changes,
    Col,
    Entity,
    Id,
    Load,
    Owned,
    column,
    fk,
    one_to_many,
    parent_fk,
    pk,
    usecase,
)


# R16: missing="none" on a result that is not optional
def wallet_of(order: Order) -> Wallet:
    return Wallet.ref(order.id)


after_not_optional = Load.after(wallet_of, missing="none")
when_not_optional = Load.when(
    Order.paid_with == PaymentMethod.WALLET, match=Wallet.user_id == Order.user_id, missing="none"
)
type StrictWallet = Annotated[Wallet, when_not_optional]


@usecase
def r16(order: Order, wallet: StrictWallet = INJECTED) -> Changes:
    return wallet.set(Wallet.balance.to(order.total))


# R17: a row set without predicates - every row
def r17() -> Changes:
    return Order.where().delete() + Order.where().set(Order.status.to(OrderStatus.EXPIRED))


# R18: the owned declaration, parent_fk and aggregate_root disagree
class Note(Entity, table="notes"):
    id: Col[Id[Note]] = pk(generated="uuid7")
    root_id: Col[Id[Root]] = fk(lambda: Root)  # a plain fk under an Owned relation
    text: Col[str] = column()


class Stray(Entity, table="strays"):
    id: Col[Id[Stray]] = pk(generated="uuid7")
    item_id: Col[Id[Item]] = parent_fk(lambda: Item)  # a parent_fk under no owned relation


class Root(Entity, table="roots"):  # owned children, but not aggregate_root=True
    id: Col[Id[Root]] = pk(generated="uuid7")
    notes: Owned[list[Note]] = one_to_many(lambda: Note.root_id, owned=True)
