"""Column-as-value follow-up (after the round-3 reproduction): another entity's column where a value
or a column of the receiver's entity is expected, and the instance overload of `Col.__get__`."""

from decimal import Decimal
from typing import reveal_type

from lib_instance_overload import ColEntity, ColWide, Entity, col_entity, col_wide, value


class OrderW(Entity, table="orders_w"):
    number: ColWide[str] = col_wide()
    user_id: ColWide[int] = col_wide()


class WalletW(Entity, table="wallets_w"):
    user_id: ColWide[int] = col_wide()


class OrderE(Entity, table="orders_e"):
    number: ColEntity[str] = col_entity()
    user_id: ColEntity[int] = col_entity()


class WalletE(Entity, table="wallets_e"):
    user_id: ColEntity[int] = col_entity()


@value
class MoneyE:
    amount: ColEntity[Decimal] = col_entity()


def probe(m: MoneyE, o: OrderE) -> None:
    # R1: a column in a value position - instance overload on `object`
    OrderW.number.to(OrderW.user_id)  # V1 own column (int) where a str is expected
    OrderW.user_id.to(WalletW.user_id)  # V2 another entity's column where an int is expected
    # R2: an operand that takes a value or a column of the receiver's entity
    reveal_type(OrderW.user_id.ge_value_or_column(OrderW.user_id))  # V3 own column
    reveal_type(OrderW.user_id.ge_value_or_column(1))  # V4 literal
    OrderW.user_id.ge_value_or_column(WalletW.user_id)  # V5 another entity's column
    # R3: the instance overload narrowed to `Entity`
    OrderE.user_id.ge_value_or_column(WalletE.user_id)  # V6 another entity's column
    reveal_type(OrderE.user_id.ge_value_or_column(OrderE.user_id))  # V7 own column
    reveal_type(o.number)  # V8 entity instance access
    reveal_type(m.amount)  # V9 instance access on a value class without a base
