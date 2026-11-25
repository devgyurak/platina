"""Follow-up F2: 4.7 child creation, eq/hash, class keywords, reserved names, nullable getter, ref ids."""

from decimal import Decimal
from typing import reveal_type
from uuid import UUID

from domain import Item, Money, Order, User
from lib_design import Col, Entity, Id, column, fk, pk
from lib_embedded_variants import PCol, embedded_p


def child_creation(order: Order, money: Money) -> None:
    # design 4.7: Order.items.add(Item.new(sku=..., price=..., position=...)) - no order_id
    order.set(Order.items.add(Item.new(price=money, position=1)))  # G1


def eq_hash(order: Order, o2: Order) -> None:
    reveal_type(order == o2)
    reveal_type(hash(order))  # G2
    reveal_type({order})  # G3


class KwOnlyOff(Entity, table="t1", kw_only=False):  # G4 a dataclass keyword on the entity
    a: Col[int] = column()


class FrozenOn(Entity, table="t2", frozen=True):  # G5
    a: Col[int] = column()


class SetField(Entity, table="t3"):
    set: Col[int] = column()  # G6 a field named like an Entity member


class NewField(Entity, table="t4"):
    new: Col[int] = column()  # G7


class Wallet2(Entity, table="t5"):
    id: Col[Id[Wallet2]] = pk(generated="uuid7")
    user_id: Col[Id[User]] = fk(lambda: User)
    spare: PCol[Money | None] = embedded_p(prefix="spare_")


def nullable_getter(uid: Id[User]) -> None:
    reveal_type(Wallet2.spare.at(lambda m: m.amount))  # G8 m is Money | None
    reveal_type(KwOnlyOff.new(1))


def ref_ids(uid: Id[User], raw: UUID) -> None:
    reveal_type(Order.ref(uid))  # G9 an Id[User] used as an Order id
    reveal_type(Order.ref(raw))
    _ = Decimal
