"""Spike 0006, part A (#49): the parent-set FK misuse lines, with the observed codes."""

from decimal import Decimal

from domain import Item, Order, Payment


def misuse(order: Order) -> None:
    # fmt: off
    Item(order_id=order.id, sku="A", price=Decimal(1))  # expect-error[reportCallIssue, call-arg]: A2 the parent sets an owned child's key
    Payment(amount=Decimal(1))                          # expect-error[reportCallIssue, call-arg]: A3 a non-owned child passes its key
    # fmt: on
