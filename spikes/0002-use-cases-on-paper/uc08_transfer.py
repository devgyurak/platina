"""Use case 8 - account transfer (ledger, commutative increments). Requirements R8.1-R8.6.

Sources: adamcharnock/django-hordak `hordak/models/core.py` `Account.transfer_to` and its leg
triggers; tigerbeetle/tigerbeetle `docs/reference/` (stored balances, overdraft flag,
`accounts_must_be_different`, transfer ID idempotency). Rules restated, no code copied.
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

import pytest
from domain import (
    Account,
    InsufficientFunds,
    InvalidTransfer,
    Leg,
    LegSide,
    Money,
    Transfer,
)
from lib import Add, App, Changes, Load, insert_all, usecase

app = App(dsn="postgresql://app@primary/shop")

type LedgerAccount = Annotated[Account, Load()]


@usecase
def transfer(src: LedgerAccount, dst: LedgerAccount, amount: Money) -> Changes:
    # R8.1 - "different accounts" by key (#54: `src == dst` would compare values)
    if src.id == dst.id:
        raise InvalidTransfer("accounts must be different")
    currency = src.balance.currency
    if amount.amount <= 0 or amount.currency != currency or dst.balance.currency != currency:
        raise InvalidTransfer("amount must be positive and in the accounts' currency")
    # R8.4 - a read of the source balance: the source row is in the read set, so this half is not
    # a blind increment, whatever syntax writes it
    if not src.allow_overdraft and src.balance.amount < amount.amount:
        raise InsufficientFunds(src.id)
    # R8.2 - a new root with owned children. Section 4 has no single-row insert of a root;
    # `insert_all` (4.8, the bulk path of 3.2: COPY or multi-row INSERT, FK order) returns
    # `Changes` and takes any entities, so it is the only design form. Not stated: whether it may
    # share the commit batch with row changes (3.2: COPY runs outside the pipeline), and whether
    # bulk insert for three rows is "the one way" to insert. The parent key is by hand (#49).
    t = Transfer(amount=amount)
    credit = Leg(transfer_id=t.id, account_id=src.id, side=LegSide.CREDIT, amount=amount)
    debit = Leg(transfer_id=t.id, account_id=dst.id, side=LegSide.DEBIT, amount=amount)
    # "the legs of a transfer sum to zero" spans rows: no `Check` (one row) or `@invariant` (one
    # snapshot) states it; it holds here by construction only (hordak: a deferred trigger)
    return (
        insert_all((t, credit, debit))
        # R8.3 - 9.5: `<entity>.set(<Entity>.balance.path(Money.amount).add(<n>))`
        + src.set(Account.balance.path(Money.amount).add(-amount.amount))
        + dst.set(Account.balance.path(Money.amount).add(amount.amount))
    ).returning(t.id)


# --------------------------------------------------------------------------- call site
async def post_transfer(transfer_id: UUID, src: UUID, dst: UUID, amount: Money) -> None:
    # R8.5: the client's transfer ID can be the run's idempotency key (identical repeat -> stored
    # result). It cannot be the `Transfer` row's primary key: `pk(generated=...)` is not a
    # constructor parameter. A repeat with different fields is answered with the stored result
    # (same gap as R1.2).
    await app.run(
        transfer.bind(src=Account.ref(src), dst=Account.ref(dst), amount=amount),
        idempotency_key=str(transfer_id),
    )


# --------------------------------------------------------------------------- 4.12 unit tests
def test_transfer_moves_balances_with_increments() -> None:
    src = Account.stub(balance=Money(Decimal("100")), allow_overdraft=False)
    dst = Account.stub(balance=Money(Decimal("0")))
    r = transfer(src, dst, Money(Decimal("30")))
    assert r.updated(src)[Account.balance] == Add(Decimal("-30"))
    assert r.updated(dst)[Account.balance] == Add(Decimal("30"))
    assert sorted(leg.side.value for leg in r.inserted(Leg)) == ["credit", "debit"]


def test_overdraft_is_rejected() -> None:
    src = Account.stub(balance=Money(Decimal("10")), allow_overdraft=False)
    with pytest.raises(InsufficientFunds):
        transfer(src, Account.stub(), Money(Decimal("30")))
