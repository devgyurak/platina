"""Use case 8 (spike 0002) in the spike 0007 shapes, candidate A of #60 point 3 - account transfer.

Requirements R8.1-R8.6. Changed from spike 0002: the new root is `insert(t)` instead of the bulk
`insert_all((t, credit, debit))`, the legs are owned children written through the root, and they
take their parent key from `Transfer.legs.add` (#49, as given). R8.5 (a reused key with other
fields) is #58's `IdempotencyKeyReuse` now, a runtime rule, not a shape.
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

import pytest
from domain import Account, InsufficientFunds, InvalidTransfer, Leg, LegSide, Money, Transfer
from lib import Add, App, Changes, Load, insert, usecase

app = App(dsn="postgresql://app@primary/shop")

type LedgerAccount = Annotated[Account, Load()]


@usecase
def transfer(src: LedgerAccount, dst: LedgerAccount, amount: Money) -> Changes:
    if src.id == dst.id:  # R8.1
        raise InvalidTransfer("accounts must be different")
    currency = src.balance.currency
    if amount.amount <= 0 or amount.currency != currency or dst.balance.currency != currency:
        raise InvalidTransfer("amount must be positive and in the accounts' currency")
    if not src.allow_overdraft and src.balance.amount < amount.amount:  # R8.4
        raise InsufficientFunds(src.id)
    t = Transfer(amount=amount)  # R8.2
    credit = Leg(account_id=src.id, side=LegSide.CREDIT, amount=amount)
    debit = Leg(account_id=dst.id, side=LegSide.DEBIT, amount=amount)
    return (
        insert(t)  # candidate A: the root, then its legs through `.set` on the new entity
        + t.set(Transfer.legs.add(credit), Transfer.legs.add(debit))
        + src.set(Account.balance.path(Money.amount).add(-amount.amount))  # R8.3
        + dst.set(Account.balance.path(Money.amount).add(amount.amount))
    ).returning(t.id)


# --------------------------------------------------------------------------- call site
async def post_transfer(transfer_id: UUID, src: UUID, dst: UUID, amount: Money) -> None:
    await app.run(
        transfer.bind(src=Account.ref(src), dst=Account.ref(dst), amount=amount),
        idempotency_key=str(transfer_id),  # R8.5: a reuse with other fields -> IdempotencyKeyReuse
    )


# --------------------------------------------------------------------------- 4.12 unit tests
def test_transfer_inserts_the_root_with_two_legs() -> None:
    src = Account.stub(balance=Money(Decimal("100")), allow_overdraft=False)
    dst = Account.stub(balance=Money(Decimal("0")))
    r = transfer(src, dst, Money(Decimal("30")))
    assert r.updated(src)[Account.balance] == Add(Decimal("-30"))
    assert r.updated(dst)[Account.balance] == Add(Decimal("30"))
    assert len(r.inserted(Transfer)) == 1
    assert sorted(leg.side.value for leg in r.inserted(Leg)) == ["credit", "debit"]


def test_overdraft_is_rejected() -> None:
    src = Account.stub(balance=Money(Decimal("10")), allow_overdraft=False)
    with pytest.raises(InsufficientFunds):
        transfer(src, Account.stub(), Money(Decimal("30")))
