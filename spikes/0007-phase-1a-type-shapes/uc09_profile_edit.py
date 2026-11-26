"""Use case 9 - profile edit (`expected_version`, owned children). Requirements R9.1-R9.6.

[0007] Ported from spike 0002 because the spike 0007 stub no longer type-checks it (architect
review of spike 0007): only the statements marked `# [0007]` changed (a wrapped statement
carries the marker on its first line).

Source: saleor/saleor `graphql/account/mutations/account/` (`account_update.py`,
`account_address_create/update/delete.py`, `account_set_default_address.py`),
`account/models.py`. R9.1 (`expected_version`) is a requirement this spike adds; no source.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import pytest
from domain import Address, InvalidAddress, TooManyAddresses, User
from lib import App, Changes, Id, Load, Op, RelOp, usecase  # [0007] + RelOp

app = App(dsn="postgresql://app@primary/shop")

MAX_ADDRESSES = 100


@dataclass(frozen=True)
class AddressInput:
    id: Id[Address] | None  # None: a new address
    line1: str
    city: str
    country: str


@dataclass(frozen=True)
class ProfilePatch:
    first_name: str | None = None
    last_name: str | None = None
    language: str | None = None
    addresses: tuple[AddressInput, ...] | None = None  # None: addresses not part of this edit
    default_address: int | None = None  # index into `addresses`


type EditableUser = Annotated[User, Load(User.addresses)]


@usecase
def edit_profile(user: EditableUser, patch: ProfilePatch) -> Changes:
    ops: list[Op[User] | RelOp[User]] = []  # [0007] a relation operation is not an Op
    # R9.2 - a patch: one optional operation per field
    if patch.first_name is not None:
        ops.append(User.first_name.to(patch.first_name))
    if patch.last_name is not None:
        ops.append(User.last_name.to(patch.last_name))
    if patch.language is not None:
        ops.append(User.language.to(patch.language))
    if patch.addresses is not None:
        # R9.3 - diff by ID; the keys are IDs, so no entity `==`/hash is needed (#54)
        if len(patch.addresses) > MAX_ADDRESSES:  # R9.5
            raise TooManyAddresses(user.id)
        current = {a.id: a for a in user.addresses}
        kept: set[Id[Address]] = set()
        final_ids: list[Id[Address]] = []
        for given in patch.addresses:
            if given.id is None:
                # [0007] no parent key (#49): `User.addresses.add` sets it. The ID is known before  # [0007]
                # commit only because the key is client-generated (uuid7) - with  # [0007]
                # `generated="identity"` the default address below could not point at it in the  # [0007]
                # same use case (#60 rejects identity-key roots with owned children in Phase 1a)  # [0007]
                new = Address(line1=given.line1, city=given.city, country=given.country)  # [0007]
                ops.append(User.addresses.add(new))
                final_ids.append(new.id)
                continue
            old = current.get(given.id)
            if old is None:
                raise InvalidAddress(given.id)
            kept.add(old.id)
            final_ids.append(old.id)
            changed = [
                op
                for op, differs in (
                    (Address.line1.to(given.line1), old.line1 != given.line1),
                    (Address.city.to(given.city), old.city != given.city),
                    (Address.country.to(given.country), old.country != given.country),
                )
                if differs
            ]
            if changed:
                ops.append(User.addresses.update(old, *changed))
        for gone in current.keys() - kept:
            ops.append(User.addresses.remove(current[gone]))
        # R9.4 - the default must be one of the addresses after the edit; deleting it clears it
        if patch.default_address is not None:
            if not 0 <= patch.default_address < len(final_ids):
                raise InvalidAddress(user.id)
            ops.append(User.default_address_id.to(final_ids[patch.default_address]))
        elif user.default_address_id is not None and user.default_address_id not in final_ids:
            ops.append(User.default_address_id.to(None))
    return user.set(*ops)


# --------------------------------------------------------------------------- call site (R9.1, R9.6)
async def put_profile(user_id: UUID, if_match: int, patch: ProfilePatch) -> None:
    await app.run(edit_profile.bind(user=User.ref(user_id, expected_version=if_match), patch=patch))


# --------------------------------------------------------------------------- 4.12 unit tests
def test_deleting_the_default_address_clears_it() -> None:
    home = Address.stub(line1="1 Main", city="Seoul", country="KR")
    work = Address.stub(line1="2 Side", city="Seoul", country="KR")
    user = User.stub(addresses=[home, work], default_address_id=home.id)
    keep = AddressInput(id=work.id, line1="2 Side", city="Seoul", country="KR")
    r = edit_profile(user, ProfilePatch(addresses=(keep,)))
    assert r.removed(home)
    assert r.updated(user)[User.default_address_id] is None


def test_unknown_address_id_is_rejected() -> None:
    user = User.stub(addresses=[])
    stray = AddressInput(id=Address.stub().id, line1="x", city="y", country="KR")
    with pytest.raises(InvalidAddress):
        edit_profile(user, ProfilePatch(addresses=(stray,)))
