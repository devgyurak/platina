"""Spike 0007 type reproduction, round 6: the owner variance of relations. Run per checker.

Run against this directory's stub (no `Path`) and against the round-5 stub (with the invariant
`Path`). Every assignment goes through a variable, so mypy's descriptor solving from the declared
type (round 4's discrepancy) does not enter.
"""

from domain import Item, Order, Seat, Ticket, Transfer, Wallet
from lib import OwnedRelation, Relation, RelColumn

items = Order.items
seat_tickets = Seat.tickets
ticket_order = Ticket.order


def v1() -> Relation[Wallet | Order, Item]:
    return items  # V1: an owned relation, read as a Relation with a wider owner


def v2(r: Relation[Seat, Ticket]) -> Relation[Wallet | Seat, Ticket]:
    return r  # V2: a Relation with a wider owner


def v3() -> RelColumn[Wallet | Ticket, Order]:
    return ticket_order  # V3: a RelColumn with a wider owner


def v4() -> OwnedRelation[Transfer | Order, Item]:
    return items  # V4: an OwnedRelation with a wider owner


def v5(r: Relation[Wallet | Seat, Ticket]) -> Relation[Seat, Ticket]:
    return r  # V5: a narrower owner (must stay rejected)
