"""Spike 0007: misuse that both checkers must reject, with the codes each one reported.

Every marked line (the expect-error marker of the `type-tests` skill) must fail under both
checkers with one of the named codes (`tools/typetests.py`). Written outside `Annotated[...]` on purpose:
inside its metadata mypy checks nothing (spike 0002, X1; `probe_annotated.py` here).
"""

from datetime import datetime
from decimal import Decimal

from domain import (
    Account,
    Allocation,
    Item,
    Leg,
    LegSide,
    Money,
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    Seat,
    SeatHold,
    Stock,
    Transfer,
    Variant,
    Wallet,
    Warehouse,
    wallets,
)
from lib import (
    Changes,
    Col,
    Entity,
    Id,
    Load,
    Owned,
    Profile,
    Rel,
    RowSet,
    column,
    insert,
    one_to_many,
    owns_many,
    pk,
)

NOW = datetime(2026, 11, 26)


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


def active_holds(seat: Seat) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.expires_at > NOW)


def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.user_id is not None else None


# fmt: off
# --- #57 / #59: a row set is not a Changes
def f_bare_where_as_changes() -> Changes:
    return Order.where(Order.status == OrderStatus.EXPIRED)  # expect-error[reportReturnType, return-value]: F1 a row set is not a Changes


def f_row_set_plus_changes(order: Order) -> Changes:
    return Order.where(Order.status == OrderStatus.EXPIRED) + order.delete()  # expect-error[reportOperatorIssue, reportUnknownVariableType, operator, no-any-return]: F2 a row set has no +


def f_row_set_set_of_other_entity(m: Money) -> Changes:
    return Order.where(Order.status == OrderStatus.EXPIRED).set(Wallet.balance.to(m))  # expect-error[reportArgumentType, arg-type]: F3 an operation of another entity in a row set's set


def f_where_with_other_entity(seat: Seat) -> RowSet[SeatHold]:
    return SeatHold.where(Seat.id == seat.id)  # expect-error[reportArgumentType, arg-type]: F4 a predicate over another entity in where


# --- #60 point 4: relation operations only on owned relations
def f_add_on_non_owned(order: Order, payment: Payment) -> Changes:
    return order.set(Order.payments.add(payment))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType, attr-defined]: F5 add on a relation that is not owned


def f_remove_on_non_owned(item: Item, a: Allocation) -> Changes:
    return item.set(Item.allocations.remove(a))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType, attr-defined]: F6 remove on a relation that is not owned


def f_update_on_non_owned(stock: Stock, v: Variant) -> Changes:
    return v.set(Variant.stocks.update(stock, Stock.allocated.add(1)))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType, attr-defined]: F7 update on a relation that is not owned


class F8Order(Entity, table="f8_orders"):
    id: Col[Id[F8Order]] = pk()
    items: Rel[list[Item]] = one_to_many(lambda: Item.order_id, owned=True)  # expect-error[reportAssignmentType, reportUnknownVariableType, assignment]: F8 owned=True declared as Rel[...]


class F9Order(Entity, table="f9_orders"):
    id: Col[Id[F9Order]] = pk()
    items: Owned[list[Item]] = one_to_many(lambda: Item.order_id)  # expect-error[reportAssignmentType, reportUnknownVariableType, assignment]: F9 Owned[...] without owned=True


# --- #60 point 3, candidate B: `insert` takes relation operations of the new entity only
def f_insert_with_column_op(amount: Money) -> Changes:
    t = Transfer(amount=amount)
    return insert(t, Transfer.amount.to(amount))  # expect-error[reportArgumentType, arg-type]: F10 candidate B takes relation operations only


def f_insert_with_other_entitys_relation_op(amount: Money, item: Item) -> Changes:
    t = Transfer(amount=amount)
    return insert(t, Order.items.add(item))  # expect-error[reportArgumentType, misc]: F11 a relation operation of another entity (needs the invariant RelOp)


def f_owned_child_with_parent_key(t: Transfer, src: Account, amount: Money) -> Leg:
    return Leg(transfer_id=t.id, account_id=src.id, side=LegSide.CREDIT, amount=amount)  # expect-error[reportCallIssue, call-arg]: F12 #49: the parent key of an owned child is not a parameter


# --- #59 point 1: nested paths
wrong_owner = Order.items.load(Order.payments)  # expect-error[reportArgumentType, arg-type]: F13 a path of Order under Order.items
skipped_level = Order.items.load(Allocation.stock)  # expect-error[reportArgumentType, arg-type]: F14 a skipped level
wrong_owner_deeper = Order.items.load(Item.allocations.load(Order.payments))  # expect-error[reportArgumentType, arg-type]: F15 a wrong owner one level deeper
wrong_owner_in_profile = Profile(Order.items.load(Stock.warehouse))  # expect-error[reportArgumentType, arg-type]: F16 a wrong owner inside a profile


# --- #59 points 2, 3: dependent loads
after_wrong_path = Load.after(variants_of, Order.items)  # expect-error[reportArgumentType, reportCallIssue, reportUnknownVariableType, arg-type]: F17 a load argument that is not a path of the returned entity
after_row_set_missing = Load.after(active_holds, missing="none")  # expect-error[reportArgumentType, call-overload]: F18 missing= on a row-set function
in_wrong_type = Stock.variant_id.in_([Decimal(1)])  # expect-error[reportArgumentType, list-item]: F19 in_ with values of another type
when_wrong_literal = Load.when(Order.paid_with == PaymentMethod.WALLET, match=Wallet.user_id == Order.user_id, missing="skip")  # expect-error[reportArgumentType, arg-type]: F20 a missing= literal that does not exist


# --- round 2 (architect review of spike 0007)
one_ref_wrong_path = Load.after(point_wallet, Order.items)  # expect-error[reportArgumentType, reportCallIssue, reportUnknownVariableType, arg-type]: F21 one-ref form, a path that is not of Wallet
one_ref_wrong_path_missing = Load.after(point_wallet, Order.items, missing="none")  # expect-error[reportArgumentType, call-overload]: F22 the same with missing=
row_set_wrong_path = Load.after(active_holds, Order.items)  # expect-error[reportArgumentType, reportCallIssue, reportUnknownVariableType, misc]: F23 row-set form, a path that is not of SeatHold


def f_insert_with_remove(t: Transfer, leg: Leg) -> Changes:
    return insert(t, Transfer.legs.remove(leg))  # expect-error[reportArgumentType, arg-type]: F24 insert takes `add` only


def f_write_through_where(order: Order, item: Item) -> Changes:
    return order.set(Order.items.where(Item.quantity == 1).remove(item))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType, attr-defined]: F25 a filtered relation is read-only


def f_write_through_load(order: Order, item: Item) -> Changes:
    return order.set(Order.items.load(Item.allocations).add(item))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType, attr-defined]: F26 a load path is read-only


def f_relation_op_in_set_change(item: Item) -> Changes:
    return Order.where(Order.status == OrderStatus.PENDING).set(Order.items.remove(item))  # expect-error[reportArgumentType, arg-type]: F27 a relation operation in a set change (was R8)


class F28Order(Entity, table="f28_orders"):
    id: Col[Id[F28Order]] = pk()
    items: Rel[list[Item]] = owns_many(lambda: Item.order_id)  # expect-error[reportAssignmentType, reportUnknownVariableType, assignment]: F28 owns_many needs Owned[...]


class F29Entity(Entity, table="f29"):
    id: Col[Id[F29Entity]] = pk()
    delete: Col[int] = column()  # expect-error[reportIncompatibleMethodOverride, assignment]: F29 `delete` is a reserved name, like `set`


# --- round 4 (independent review): a column is not a load path
column_as_path = Order.items.load(Item.quantity)  # expect-error[reportArgumentType, arg-type]: F30 a column is not a load path
column_as_path_many_to_one = Stock.warehouse.load(Warehouse.group)  # expect-error[reportArgumentType, arg-type]: F31 the same under a many-to-one
# fmt: on
