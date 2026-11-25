# Spike 0002: Ten real use cases on paper

- Design section: 9.4 "Port 10 real use cases to this syntax" ("If something does not translate
  onto paper, fix the syntax")
- Issue: #5
- Date: 2026-11-25
- Code: `spikes/0002-use-cases-on-paper/` (throwaway; raw output in `results/`, git-ignored)

## Question

Can the section 4 syntax, as decided by ADR-0003 (`Entity` base, `Order(...)`) and ADR-0004
(`Column[Owner, T]`, `path(...)`), express real business rules without bending them? The
dangerous error is a false "it is expressed": a rule that silently got simpler so that it fits.
So the requirements of every use case are fixed below, from the source, **before** any code was
written, and the code is judged against them, not against what the syntax happens to allow.

Each use case gets one of three verdicts:
- **Expressed** - every requirement is written in the section 4 syntax as the design shows it.
- **Expressed, awkward** - every requirement is written, but only with a workaround (more rows
  loaded than the rule needs, a rule moved to Python or to another transaction, a cast, a
  repeated long expression), or with a signature the design does not give (listed under "Stub
  additions").
- **Not expressible** - at least one requirement cannot be written without a syntax or design
  change. These are not decided here; each comes with alternatives for the maintainer.

For every use case four items are recorded (issue #5): entity `==`, set/dict keys or comparison
with a stub (#54); `Order(...)` creation with identity keys and the parent key of owned children
(#49); column comparison operands (#51); the length of `path(...).add(...)` (9.5).

### Sources

The rules are taken from open-source code and restated in our own words; no code is copied (pretix
is AGPL-3.0 with additional terms, Platina is Apache-2.0). Every source was read at the commit
below, the latest of its default branch on 2026-11-25. The excerpts were read by four
sub-agents; the lines marked "checked" were re-read by the author of this write-up in the
downloaded file.

| # | Use case | Repository @ commit | Paths and lines read |
|---|---|---|---|
| 1 | Payment | `brandur/rocket-rides-atomic` @ `94b370ddbdc8d08fb263f07c221bab42190d48e6` (2022-12-01); control `dotnet/eShop` @ `3c6e531a6063676ece317644f72172fb42a935b3` | `api.rb` L10-168 (`POST /rides`), L365-403 (`atomic_phase`), `schema.sql`, `completer.rb`, `enqueuer.rb` (checked: L36-48 params/lock check); eShop `src/Ordering.API/Application/Commands/IdentifiedCommandHandler.cs` L39-104, `src/Ordering.Infrastructure/Idempotency/RequestManager.cs`, `src/Ordering.API/Application/Behaviors/TransactionBehavior.cs` |
| 2 | Refund | `pretix/pretix` @ `c0d887738b6cd97f724b926718c55e2ae87c9901` | `src/pretix/base/services/orders.py` `_cancel_order` L517-706 (checked: L520-536 lock), `_try_auto_refund` L3261-3378; `src/pretix/base/models/orders.py` `cancel_allowed` L646-649, `propose_auto_refunds` L787-838, `OrderRefund` L2111+ |
| 3 | Coupon then payment | `saleor/saleor` @ `e1ccf4d580025b06c2ff01441a1e798dc4635f24` | `saleor/checkout/complete_checkout.py` L115-182 (`_increase_checkout_voucher_usage`), L1062-1099 (`_process_payment`), L1852-1987; `saleor/discount/utils/voucher.py` L85-167 (checked: L85-96 `increase_voucher_usage`); `saleor/checkout/utils.py` L575-628 |
| 4 | Stock reservation | `saleor/saleor` @ `e1ccf4d5...` | `saleor/warehouse/management.py` L90-357 (`allocate_stocks`, `_create_allocations`), `saleor/warehouse/reservations.py` L91-245 (`reserve_stocks`), `saleor/warehouse/lock_objects.py` (checked: L1-10 `order_by("pk").select_for_update`) |
| 5 | Seat reservation | `pretix/pretix` @ `c0d88773...` | `src/pretix/base/models/seating.py` `Seat.is_available` L285-357 (checked: L285-310), `services/orders.py` `_check_positions` L726+ (L780-855), `services/cart.py` L1244-1257, `services/locking.py` L68-117 |
| 6 | Order merge | `solidusio/solidus` @ `600c7f73f66da3c46a52b028d19b1b7a229eb644` | `core/app/models/spree/order_merger.rb` L48-141 (checked: L48-63 `merge!`), `core/app/models/spree/mergeable_orders_finder.rb` L38-42, `order_merger_spec.rb` |
| 7 | Expire unpaid orders | `pretix/pretix` @ `c0d88773...`; `saleor/saleor` @ `e1ccf4d5...` | pretix `services/orders.py` `expire_orders` L1436-1457, `mark_order_expired` L360-382, `models/orders.py` `payment_term_expire_date` L1000-1024; saleor `saleor/order/tasks.py` `_expire_orders` L144-179 (checked: L31 batch size 100, L163 batch slice), `saleor/warehouse/management.py` L762-807 |
| 8 | Account transfer | `adamcharnock/django-hordak` @ `de63cba9cafc3cec8a6140205637956165704728`; `tigerbeetle/tigerbeetle` @ `7d7d78c46bdca3eeeff0ba4e435ed591ca8a397e` (documentation only) | hordak `hordak/models/core.py` `Account.transfer_to` L387-428 (checked: L386-388), migrations `0002_check_leg_trigger_20160903_1149.py`, `0052_amount_to_debit_credit_sql.pg.sql`, `0054_check_debit_credit_positive.sql`; TigerBeetle `docs/reference/account.md`, `docs/reference/transfer.md`, `docs/reference/requests/create_transfers.md` (checked: `accounts_must_be_different` L318, `exceeds_credits` L626) |
| 9 | Profile edit | `saleor/saleor` @ `e1ccf4d5...` | `saleor/graphql/account/mutations/account/` (`account_update.py`, `account_address_create.py`, `account_address_update.py`, `account_address_delete.py`, `account_set_default_address.py`), `saleor/graphql/account/mutations/base.py` L43-160, L274-438, `saleor/account/models.py` L63-190, `saleor/account/utils.py` L76-147 |
| 10 | Payment approval notice | `brandur/rocket-rides-atomic` @ `94b370dd...`; `dotnet/eShop` @ `3c6e531a...` | `api.rb` L100-140 (Stripe charge, idempotency key `rocket-rides-atomic-<key id>`), `enqueuer.rb` L17-36 (`StagedJob`); eShop `src/PaymentProcessor/IntegrationEvents/EventHandling/OrderStatusChangedToStockConfirmedIntegrationEventHandler.cs` L9-33, `src/EventBusRabbitMQ/RabbitMQEventBus.cs` ~L159-180 |

Weak points of the sources, stated up front:
- #8: hordak stores no balance (a balance is the sum of the account's legs) and checks no
  overdraft. "Commutative increments" need a stored balance, so the stored balance and the
  overdraft rule come from TigerBeetle's documentation (`debits_must_not_exceed_credits`,
  `exceeds_credits`, `accounts_must_be_different`), read directly, not from its code.
- #9: no source with an `If-Match`-style version check was found. Saleor's profile mutations
  check no version, take no lock and are last-writer-wins per field. **`expected_version` is a
  requirement this spike adds**, not one taken from a source.
- #10: eShop's payment processor calls no gateway (a configuration flag decides success) and is
  used only as the shape "event in, success or failure event out". The external call and its
  idempotency key come from rocket-rides.

### The domain

One domain, a shop that sells goods and event tickets, extending the `billing` module of section
4.2 (`Money`, `User`, `Order`, `Item`, `Wallet`, `Coupon`, `OrderPaid`). Added entities, each
needed by at least one use case: `Payment` and `Refund` (#1, #2, #10), `CouponRedemption` (#3),
`Variant`, `Warehouse`, `Stock`, `Allocation` (#4, #7), `Show`, `Seat`, `SeatHold`, `Ticket` (#2,
#5, #7), `Account`, `Transfer`, `Leg` (#8), `Address` (#9). The code is
`spikes/0002-use-cases-on-paper/domain.py`.

### Requirements, fixed before the code

Each block: the source's rules (our words), what changed when porting and why, then the
requirements R*n*.*m* the code is judged against. "Concurrency" states what must hold when two
requests overlap.

#### 1. Payment (idempotency key, run ID)
Source rules: the client must send an idempotency key; the first request with a key records it
with the request parameters; a repeat with the same key and **different parameters** is rejected
(409); a repeat while the first is still running is rejected (409 "in progress"); a repeat after
completion returns the stored response, including stored failures (402 card declined); the ride
row and an audit row are written together; a receipt job is staged in the same transaction as
the final step; a serialization failure is returned to the client (409), not retried. eShop
(control): the request ID is looked up, then inserted, under READ COMMITTED, and an exception of
the inner command is swallowed, so a failed command still records its request ID.

Changed when porting: the payment is from the user's wallet (internal), so there is no external
call in this use case (the external call is use case 10). Serialization failures are retried by
the engine (design 8.3) instead of returned. A stored failure is not replayed: a declined payment
leaves no trace and a retry with the same key runs again (stated as R1.5, because it differs
from the source). A repeat while the first request is still running is answered with 409 by the
source; here it waits on the run ID's unique key and then gets the stored result (4.6) - added
after the review, the requirement R1.3 was already written that way.

- R1.1 The caller's key identifies the run; a repeat with the same key returns the first result
  without running the rules again (it must not raise `AlreadyPaid`).
- R1.2 A repeat with the same key and different arguments is rejected, not answered with the
  stored result.
- R1.3 Concurrency: two requests with the same key never both run the rules; two requests with
  different keys for the same order: exactly one pays, the other gets `AlreadyPaid`.
- R1.4 The result carries the new payment's ID, also on a repeat.
- R1.5 A domain failure (insufficient balance) commits nothing; a retry with the same key runs
  again.
- R1.6 The payment row, the order change and the domain event are committed together.
- R1.7 The receipt is requested in the same transaction and sent after commit.

#### 2. Refund (dependent loads)
Source rules: cancellation is allowed only for pending, paid or expired orders with at least one
position; the order row is locked first. With a cancellation fee, the fee may not exceed the
total, positions are cancelled and the order's total becomes the fee (it stays paid if payments
cover the fee); without a fee the order becomes cancelled. Voucher redemption counts go down by
one per position, never below zero. Gift cards bought in the order are drained. Refunds are a
separate step after commit: the amount is "paid minus refunded minus the new total"; for each
payment whose provider can refund, the code picks an exact match first, else the smallest larger
partially refundable payment, else the largest smaller one, and repeats; one refund row per chosen
payment; any remainder becomes a manual refund. A refund can also go to a new gift card of the
customer. The refunds run without a lock, so two concurrent refunds can both read the same
outstanding amount.

Changed when porting: gift cards are the user's wallet (the design's own 4.7 example refunds point
payments to the wallet); the refund rows are created in the same transaction as the cancellation
(the source's race is not carried over); the provider call that executes a card refund happens
in a `@process` handler after commit (as in use case 10). Coupons are per order in this domain
(use case 3), so the usage goes down by one per order, not per position. A fee that payments do
not cover sends the order back to PENDING with a new expiry of now + 3 days (the source computes a
payment deadline). Left out: gift cards bought in the order (the source drains them), memberships,
invoices, ticket secrets. (The last three sentences were made explicit after the review; R2.2 and
R2.3 below were corrected to match - see Reproduction.)

- R2.1 Allowed only when the status is PENDING, PAID or EXPIRED and the order has at least one
  active (not cancelled) item; otherwise `CannotCancel`.
- R2.2 With a fee: fee <= total else `FeeTooHigh`; the active items are marked cancelled, the
  total becomes the fee; the status stays as it is if confirmed payments (minus refunds) cover the
  fee, else it becomes PENDING with a new expiry. Without a fee: status CANCELLED, items cancelled.
- R2.3 If the order used a coupon, its usage count goes down by one (per order), never below zero.
- R2.4 Refund amount = sum of confirmed payments - sum of refunds - new total; nothing if <= 0.
- R2.5 The source's greedy rule picks the payments to refund from; each chosen part is refunded the
  way it was paid: wallet parts to the user's wallet (balance increment) with a `Refund` row, card
  parts as `Refund` rows (state CREATED) for the provider; a remainder gets a manual `Refund` row.
- R2.6 An `OrderCancelled` event; card refunds are executed after commit with the provider's
  idempotency key.
- R2.7 Concurrency: two cancellations of one order: one succeeds, the other gets `CannotCancel`;
  the outstanding amount is never refunded twice.

#### 3. Coupon then payment (`chain`)
Source rules: the voucher code must be active; with a usage limit the code row is locked and
`used` is incremented; "once per customer" inserts a (code, customer) row under a unique
constraint, a second use is rejected; a single-use code is deactivated; the usage increment
happens before payment, and on a payment error saleor does **not** release it (the failure
handler is called without the voucher; on other failure paths it is released).

Changed when porting: payment is from the wallet (use case 1's rules) so it is one transaction
with the coupon; a failed payment therefore releases the coupon by rollback, which is what
saleor's other failure paths do.

- R3.1 The coupon must be active, else `CouponNotApplicable`.
- R3.2 With a usage limit: `used < usage_limit` else `CouponNotApplicable`; `used` goes up by one.
- R3.3 Once per customer: a second use by the same user is rejected with `CouponNotApplicable`
  (a domain error, not a database error).
- R3.4 Single use: the coupon is deactivated.
- R3.5 The payment charges the discounted total (rules of use case 1).
- R3.6 If the payment fails, nothing of the coupon is consumed.
- R3.7 Concurrency: two checkouts racing for the last use: exactly one succeeds.

#### 4. Stock reservation (hot rows, pessimistic lock profile)
Source rules: one stock row per (warehouse, variant); only variants that track inventory; the
candidate rows are the stocks of the line's variant in the channel's warehouses, locked with
`SELECT ... FOR UPDATE` in primary-key order; available = quantity - allocated - unexpired
reservations of other checkouts; warehouses are ordered by the channel's strategy (highest stock
first, or the channel's warehouse order); each line is split greedily over the ordered stocks
(one line can produce several allocation rows); all short lines are collected and reported in one
`InsufficientStock` before anything is written; allocations are inserted and
`Stock.quantity_allocated` is incremented in the database.

Changed when porting: reservations (carts) are left out; available = quantity - allocated. The
strategy is "highest available first".

- R4.1 For every item of the order whose variant tracks inventory, the stocks of that variant in
  the order's channel warehouses are read.
- R4.2 Each item is split greedily over its stocks, highest available first.
- R4.3 One `Allocation` row per (item, stock) part; each stock's `allocated` goes up by the parts.
- R4.4 If any item is short, `InsufficientStock` lists all short items and nothing is written.
- R4.5 Concurrency: no oversell; the stock rows are hot, so they are locked (`FOR UPDATE`) in a
  fixed order instead of relying on serialization failures. (After the review this is read as two
  parts: "no oversell" is the business rule and counts for the verdict; "locked instead of
  serialization failures" is the design's expectation from 9.4 and 8.3, judged as a design finding,
  X8, not as a syntax verdict.)

#### 5. Seat reservation (write skew, SERIALIZABLE)
Source rules: a blocked seat is unavailable unless the sales channel may sell blocked seats; a seat
is unavailable if a non-cancelled ticket of a pending or paid order holds it, or a cart position
with `expires >= now` holds it (the caller's own excepted), or a valid voucher is bound to it;
with a minimal distance, a seat is also unavailable if another taken seat of the event lies closer
than the distance (only in the same row if so configured); availability is computed only from the
absence of rows (no flag, no unique constraint); double booking is prevented by advisory locks per
seat (or per event when the distance rule is on), under READ COMMITTED.

Changed when porting: vouchers are left out; the lock is replaced by SERIALIZABLE (this is what 9.4
tests). One seat per call. The sales channel's permission to sell blocked seats became a setting
of the show (stated after the review).

- R5.1 A blocked seat is unavailable unless the show's `allow_blocked` is set.
- R5.2 Unavailable if an active ticket holds it (ticket not cancelled, its order PENDING or PAID)
  or an unexpired hold of another user holds it (`expires_at >= now`).
- R5.3 If the show's `min_distance > 0`: unavailable if any taken seat of the show (same row only
  when `distance_within_row`) is closer than `min_distance`.
- R5.4 On success a `SeatHold(seat, user, expires_at = now + 15 min)` is created.
- R5.5 Concurrency: two users holding the same seat: one succeeds. Two users holding two seats
  closer than the distance: one succeeds (write skew across different rows).

#### 6. Order merge (two parameters of one type)
Source rules: lines are merged only if the currencies are equal (otherwise all lines are skipped
silently and the source order is still destroyed); a source line with the same variant (and equal
options) as a target line adds its quantity to that line; other lines are copied to the target
(new ID); the target gets the user if it has none; totals are recalculated; the source order and
its lines are destroyed; there is no transaction and no self-merge guard in the merger (the finder
excludes the current order).

Changed when porting: a currency mismatch is rejected instead of losing lines; everything is one
transaction; merging an order into itself is rejected in the use case.

- R6.1 `src` and `dst` must be different orders, else `CannotMerge`; currencies must match, else
  `CannotMerge`; both must be PENDING.
- R6.2 For each src item: if dst has an item with the same variant, its quantity grows by the src
  quantity; otherwise the item is copied into dst.
- R6.3 If dst has no user, it gets the given user.
- R6.4 dst's total is recalculated from its items.
- R6.5 src and its items are deleted.
- R6.6 Concurrency: a concurrent change to either order makes one of the two fail (or retry).

#### 7. Expire unpaid orders (set change, `emit_each`)
Source rules (pretix): orders with status pending and `expires < now`, not "valid if pending", not
awaiting approval, without a cancellation fee; per event, only if the event's setting "expire
automatically" is on; per order, only when now is past the payment-term expiry date, which is
`expires`, or `expires + delay days` (end of that day in the event's time zone, moved past a
weekend if configured, capped at a last date); each order in its own transaction: status expired,
log entry, invoice cancelled, ledger rows; a signal after commit; no batch limit. Saleor: batches
of 100 ids, one transaction: status expired + `expired_at`, voucher usage released in bulk, events
inserted, stock allocations released (allocated set to 0, stock `allocated` decremented), webhooks
after commit; the update does not re-check the status.

Changed when porting: the per-show settings are `auto_expire` and `expire_delay_days` (no time
zone or weekend rule); bounded batches as in saleor. Left out (stated after the review): "valid if
pending", "awaiting approval" and "without a cancellation fee". The first two are column
predicates like `status`; the third is the absence of a related row (X7) and would not fit the set
change either.

- R7.1 Select orders with status PENDING and `expires_at < now`, whose show has `auto_expire` on,
  and for which `now >= expires_at + show.expire_delay_days`.
- R7.2 Each selected order: status EXPIRED, `expired_at = now`, an `OrderExpired` event with its
  sequence number.
- R7.3 Each selected order releases its resources: the coupon's usage goes down by one (not below
  zero); every allocation of its items is removed and the stock's `allocated` goes down by it.
- R7.4 The number of expired orders is returned (for the scheduler's log).
- R7.5 At most 100 orders per run.
- R7.6 Concurrency: an order paid concurrently is not expired (the status is re-checked when
  written).
- R7.7 A notification per expired order is sent after commit.

#### 8. Account transfer (ledger, commutative increments)
Source rules (hordak): one atomic transaction creates a transaction row and two legs (a credit on
the source, a debit on the target) of the same amount; amounts must be positive; per currency the
legs of a transaction must sum to zero, checked at commit by a deferred constraint trigger; balances
are sums over legs, not stored; no overdraft check, no lock, no check that source and target
differ. TigerBeetle (documentation): accounts store running totals (`debits_posted`,
`credits_posted`, ...); with `debits_must_not_exceed_credits` a transfer is rejected with
`exceeds_credits` when it would overdraw; source and target must differ
(`accounts_must_be_different`); a transfer `id` is an idempotency key: an identical repeat returns
`exists`, a repeat with different fields `exists_with_different_<field>`.

Changed when porting: a stored balance on `Account` (TigerBeetle) so that increments exist at
all; the overdraft rule from TigerBeetle.

- R8.1 amount > 0 and in the accounts' currency, else `InvalidTransfer`; source != target, else
  `InvalidTransfer`.
- R8.2 A `Transfer` with two `Leg`s (credit source, debit target, same amount); the legs sum to
  zero.
- R8.3 The stored balances change by increments: source - amount, target + amount.
- R8.4 If the source does not allow overdraft: balance >= amount, else `InsufficientFunds`.
- R8.5 The transfer ID is the idempotency key: an identical repeat returns the first result; a
  repeat with different fields is rejected.
- R8.6 Concurrency: two transfers out of one account never overdraw it; transfers into one account
  should not have to conflict with each other (the point of commutative increments). (After the
  review: the second clause comes from 9.4's label "commutative increments", not from a source; it
  is judged as a design finding, X8, not as a syntax verdict.)

#### 9. Profile edit (`expected_version`, owned children)
Source rules (saleor): the user edits first name, last name, language and the default billing and
shipping addresses; an address given as default is validated and updated in place; addresses
belong to the user through a many-to-many link; creating an address beyond 100 deletes the oldest
non-default address; deleting an address clears the defaults that point to it; setting a default
requires the address to belong to the user; no version check, no lock.

Changed when porting: addresses are `owned` children of `User` (one owner, which saleor's code
assumes "in most cases"); the two defaults (billing and shipping) became one default address
(stated after the review; a second default is the same kind of column); one request carries the
whole edit screen (fields plus the address list as it should be), and the **added requirement**
R9.1.

- R9.1 (added, no source) The request carries the version the screen was opened with; if the user
  or any address changed since, `VersionMismatch`.
- R9.2 Only the given fields change (a patch); a field not given is not written.
- R9.3 Addresses: the request's list is diffed against the stored addresses by ID: new ones are
  created, changed ones updated, missing ones deleted.
- R9.4 The default address must be one of the user's addresses after the edit, else
  `InvalidAddress`; deleting the default clears it.
- R9.5 At most 100 addresses, else `TooManyAddresses` (changed: rejected instead of deleting the
  oldest, so that an edit never deletes data the request did not mention).
- R9.6 Concurrency: two edits opened at the same version: the second gets `VersionMismatch`, also
  when only addresses changed.

#### 10. Payment approval notice (`@process`, job pipeline, external idempotency key)
Source rules (rocket-rides): the external charge is made with an idempotency key derived from the
internal key's ID, so a replay after a crash returns the same charge; a card error is a final
402, other gateway errors a 503; on success the charge ID is stored and a receipt job is staged
in the same transaction; the stager only logs (no real queue). eShop: on "stock confirmed" the
payment processor publishes "payment succeeded" or "payment failed"; it is acknowledged even when
it throws.

Changed when porting: the trigger is `PaymentRequested`, emitted by placing a card payment.

- R10.1 On `PaymentRequested`, call the gateway with an idempotency key that is the same on every
  redelivery of that event.
- R10.2 Approved: the payment becomes CONFIRMED with the gateway's ID, the order PAID, and a
  receipt is requested. Declined: the payment becomes DECLINED and the order stays PENDING, open
  for another attempt (wording made precise after the review; "released" was ambiguous).
- R10.3 The receipt (the "notice") is sent after the approval committed, and only then.
- R10.4 A transient gateway error is retried; a decline is final.
- R10.5 A redelivered event never charges twice and never commits the approval twice.

### Hypotheses written before the code (predictions, not facts)
From the maintainer's brief; each is checked in Observations.
- H2: `Load.when(..., match=Wallet.user_id == Order.user_id)` is a type error today (#51).
- H4: there is no way to declare N stock rows for N items (`Load.after` returns a ref or `None`);
  the lock is written `Load(..., lock=FOR_UPDATE)` in 3.1 and `Profile(..., lock="for_update")` in
  4.3.
- H5: a set read by a predicate that is not a relation, and a declaration that reads "no row", are
  needed.
- H6: there is no operation that moves an owned child to another parent (#49); comparing whether
  `src` and `dst` are the same row (#54).
- H7: 4.13's `SealError` example is exactly this set change; a rule that reads another entity's
  setting per row; returning the count; per-order follow-up work.
- H8: a balance check (a read) mixed with commutative increments; two parameters of one type.
- H9: diffing owned children needs dict/set keys (#54); creating a child needs the parent key
  (#49).
- H10: whether the notice follows the approval through `then` when `@process` returns one use
  case.

## Setup
- Python 3.14.7 (`uv run python -V`), pyright 1.1.414 (`uv run pyright --version`), mypy 2.4.1
  compiled (`uv run mypy --version`), psycopg 3.3.9; PostgreSQL 18.6 (`SELECT version()`:
  `PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2) on aarch64-unknown-linux-gnu`), fast profile
  (`make db-up`, port 26432) for the one database check. `uv sync --group spike`; no other
  dependency.
- Branch `docs/spike-0002-use-cases-on-paper` cut from `develop` at `10a8517`. pyright and mypy are
  configured by `pyproject.toml` (pyright `strict` covers `spikes/`; mypy `--strict`).
- The library stub `spikes/0002-use-cases-on-paper/lib.pyi` is a copy of spike 0001's final stub
  `spikes/0001-type-surface/round2/lib_final_declared.pyi` (sha256 `fd0f4624...`) with additions.
  Every added or changed declaration carries `# [0002]` on each of its lines (the review found the
  member lines of added classes and the placeholders unmarked; fixed); the list is under "Stub
  additions" below. Apart from those lines the copy is unchanged (`diff` of the two files with
  comments stripped shows only the docstring, the `collections.abc` import and `SetChange.set`,
  which gained `unsafe_bypass`). Two functions of spike 0001's stub, `fk` and `usecase`, became
  `@overload`s because an overload was added. The type reproduction found ten continuation and
  decorator lines of added declarations still unmarked (now marked) and confirmed that spike 0001's
  pinned `round2/*_final_declared` files still give `0 problem(s) in 4 file(s)` against this stub
  (`repro/types/run.sh`, output `regress0001.txt`).

## Method
1. The requirements above were written first, from the sources, before any code.
2. `spikes/0002-use-cases-on-paper/domain.py`: the shared domain (entities, values, events,
   repositories, domain errors). `ucNN_*.py`: one file per use case with the entities' use cases
   and steps, the `@process` handlers it needs, a call site (`bind` / `app.run` / `app.query`)
   and one or two unit tests in the 4.12 shape. Where the syntax could not state a requirement,
   the closest form was written and the gap is a comment in the code and an observation below.
   Two placeholders, `UNDECIDED_insert` and `UNDECIDED_delete`, stand for operations section 4
   does not have; they are not proposals. After the review only `UNDECIDED_delete` is used (use
   case 8 now uses the design's `insert_all`).
3. Lines the use cases needed (or the design shows) that both checkers reject are in
   `fail_findings.py` with the observed codes. Lines both checkers accept although a reader would
   expect a rejection are in `probe_accepted.py`. Two probes check single questions:
   `probe_annotated_metadata.py` (are expressions inside `Annotated[...]` checked) and
   `probe_column_key.py` (4.12's assertion with `Column` dict keys).
4. Type checks, from the repository root:

   ```bash
   D=spikes/0002-use-cases-on-paper
   uv run python -m tools.typetests $D/lib.pyi $D/domain.py $D/uc01_payment.py $D/uc02_refund.py \
     $D/uc03_coupon_checkout.py $D/uc04_stock_allocation.py $D/uc05_seat_hold.py \
     $D/uc06_order_merge.py $D/uc07_expire_orders.py $D/uc08_transfer.py $D/uc09_profile_edit.py \
     $D/uc10_payment_approval.py $D/fail_findings.py $D/probe_accepted.py
   # -> typetests: 0 problem(s) in 14 file(s)
   # the two probes disagree between the checkers by design, so they are run directly:
   cd $D
   for f in probe_annotated_metadata probe_column_key; do
     uv run pyright $f.py; uv run mypy --strict --show-error-codes --no-incremental $f.py
   done
   ```
   Raw output per file and checker: `results/<file>-pyright.txt`, `results/<file>-mypy.txt`.
   The unit tests are type-checked only, never run (there is no implementation).
5. One database fact both use case 4 and use case 8 rest on was checked on the test database:
   `uv run python spikes/0002-use-cases-on-paper/db_increment_conflicts.py` (two sessions, pinned
   interleaving; output in `results/db-increment-conflicts.txt`). One run per case: it answers
   "does it happen", not "how often".
6. The independent reproductions (see Reproduction): their sources are in
   `spikes/0002-use-cases-on-paper/repro/` (`types/`: the reproducer's probes and the four stub
   variants as patches against `lib.pyi`; `db/`: the reproducer's scripts, unchanged; `README.md`
   describes both). Rerun from the repository root:

   ```bash
   bash spikes/0002-use-cases-on-paper/repro/types/run.sh
   bash spikes/0002-use-cases-on-paper/repro/db/run.sh   # needs `make db-up`
   ```

   The output is regenerated into the git-ignored `results/repro-types/` and `results/repro-db/`.
   The two `run.sh` files are glue written when the sources were moved, not the reproducers'
   code; the first run's output files had the reproducer's own names (`08-...` to `12-...`), the
   glue writes `<variant>-pyright-16.txt` and the like. A rerun is not a new reproduction. The
   reproducers' files carry a temporary header that suppresses ruff lint and format for them
   (their code below it is byte-identical; `repro/README.md`). The
   type commands must run inside the repository: pyright's configuration (`strict` for `spikes/`)
   applies only there.

## Observations

### Cross-cutting findings
These came up in several use cases; the per-use-case sections refer to them by number.

- **X1 - mypy does not check expressions inside `Annotated[...]` metadata; pyright does.**
  `probe_annotated_metadata.py`: the same `Load.when(..., match=Wallet.user_id == Order.user_id)`
  is reported at line 13 (a plain assignment) by both checkers (pyright `reportOperatorIssue`,
  mypy `operator`), but at lines 18 (inside a PEP 695 `type` alias) and 26 (inside a parameter
  annotation) by pyright only. `Profile(Order.items, lock="for_share")` (a wrong literal) is
  rejected by both at line 34 (assignment) and by pyright only at line 32 (inside `Annotated`).
  Every load declaration written inline in a use case signature (`Annotated[Order, Load(...)]`,
  4.5, 4.7) is therefore checked by one checker. Spike 0001's statement that 4.7's `Load.when`
  line "is rejected by both" holds for the expression, not for 4.7's text, which writes it inside
  `Annotated`. Declarations held in a variable (a `Profile` on a repository, a module-level
  `Load`) are checked by both. The type reproduction showed the gap is total, not specific to
  comparisons: inside `Annotated[...]` metadata mypy reports nothing at all - wrong argument types
  (`Load(1, 2, 3)`), an unknown attribute (`Load.no_such_method()`), an undefined name, even
  `1 + "a"` - while pyright reports all of them (seven errors against mypy's `Success`;
  `repro/types/x1_extra.py`). A typo in an inline `Load(...)` is
  invisible to mypy; under mypy, seal is the only check of a load declaration written inline.
- **X2 - 4.12's assertion `r.updated(order) == {Order.status: PAID, ...}` is rejected by pyright,
  accepted by mypy** (`probe_column_key.py`, lines 22 and 25): `Dictionary key must be hashable /
  Type "Column[Order, OrderStatus]" is not hashable` (`reportUnhashable`); mypy infers
  `dict[object, object]` and reports nothing. `Column` overrides `__eq__` (it builds a predicate)
  and declares no `__hash__`, so pyright treats it as unhashable. The use case tests index
  instead (`r.updated(wallet)[Wallet.balance] == Add(...)`), which both accept. Candidate fix:
  `Column` declares `__hash__` (identity hash, as SQLAlchemy's column elements do). This spike did
  not probe it; the type reproducer did, as a new probe of its own (a copy of the stub with one
  line, `def __hash__(self) -> int: ...`; `repro/types/patches/hash.patch`): pyright then accepts
  lines 22 and 25, mypy is unchanged, the 14-file
  set still gives `0 problem(s)` and spike 0001's pinned files too. That probe has run once and is
  not reproduced, and the runtime side (a dict lookup on a class whose `__eq__` returns a predicate
  rests on identity hashing) has no implementation to run.
- **X3 - a newly created root goes into `Changes` only through the bulk path `insert_all`.**
  Section 4 shows creation (`Order(...)`), owned children (`Order.items.add(...)`), events
  (`emit`) and `insert_all` (4.8; 3.2: "COPY / multi-row INSERT, automatic FK ordering, chunk
  streaming"), which returns `Changes` and takes any entities - so `insert_all((transfer, leg1,
  leg2))` is written in design syntax (the first draft missed it and used a placeholder; the review
  pointed it out). Open: whether `insert_all` may share the commit batch with row changes (3.2:
  "COPY cannot be used in pipeline mode, so the bulk insert path runs outside the pipeline"), what
  it costs in round trips for three rows, and whether it is meant as the way to insert one root
  (one way per operation). A non-root entity can also be inserted through any one-to-many relation
  of a loaded parent (`Order.payments.add(...)`, `Seat.holds.add(...)`,
  `Coupon.redemptions.add(...)`; 4.4 says `add` on a non-owned relation is an `INSERT` without a
  version bump), with its parent key passed by hand - two ways to insert such a row. Whether `.set`
  is allowed on an entity created in the same function (not a loaded snapshot) is not stated; both
  checkers accept it (`probe_accepted.py` item 4).
- **X4 - no syntax deletes a root row.** `Order.items.remove(item)` deletes owned children; there
  is no delete for a root (use case 6, placeholder `UNDECIDED_delete`), and nothing says whether
  deleting a root deletes its owned children.
- **X5 - a dependent-load parameter must be passed to `bind` unless it has a default.** `bind`
  has the use case's signature (ParamSpec), so 4.7's `refund(order, wallet: PointWallet)` makes
  `refund.bind(order=Order.ref(oid))` a type error in both checkers (`fail_findings.py` line 52:
  pyright `Argument missing for parameter "wallet"` `reportCallIssue`, mypy `Missing positional
  argument "wallet" in call to "bind"` `call-arg`). The use cases give such parameters the default
  `INJECTED`, which type-checks (the stub types `INJECTED` as `Never`) but is not what the design
  shows and touches the open rule for `INJECTED` defaults (#48).
- **X6 - nested load paths are not shown.** Use cases 4, 5 and 7 need a relation of a relation
  (`Variant.stocks` then `Stock.warehouse`; `Seat.tickets` then `Ticket.order`; `Order.items` then
  `Item.allocations` then `Allocation.stock`). `Profile(Variant.stocks, Stock.warehouse, ...)`
  type-checks (the stub takes `*fields: Expr`) but section 4 only shows relations of the root, so
  what such a list means (a path, or an error at seal) is undecided.
- **X7 - a set of rows chosen by a predicate cannot be declared as a load.** The rules need
  "the stocks of the variants of these items in these warehouses" (4), "unexpired holds and active
  tickets of this seat" (5), "has this user redeemed this coupon" (3). The syntax offers a whole
  relation of a loaded row, partial loads (8.2 names `.count()`, `.exists()`, `.where(...)`
  without signatures; a predicate there can only name columns, so it cannot use a parameter or
  `Now`), a Finder (one row by one column), `Load.after` (a ref or `None` in 4.7, a list of refs
  in 3.1) and `Load.when`, whose `match` relates the loaded row to the columns of another parameter
  (4.7). `Load.when` comes closest for "one row by two keys" (use case 3:
  `match=CouponRedemption.coupon_id == Coupon.id` and `CouponRedemption.user_id == User.id`), but it
  is blocked three times: column-to-column comparison (#51), no way to combine two predicates (no
  `&` is shown), and reading an absence is unstated for it (8.2 states "`None` and `NotFound` are
  distinguished ... when absence is acceptable, state it explicitly with `missing="none"`" for
  dependent loads in general, but the only signature shown, 4.7's, puts `missing=` on
  `Load.after`; whether `Load.when` takes it is not said). A predicate on a parameter or on `Now`,
  and a set of rows (not one) chosen from stage-1 values, have no form at all. The use cases
  over-read a whole relation and filter in Python, or move the lookup to the caller. (The first
  draft omitted `Load.when` from this list; the review pointed it out.)
- **X8 - on a hot row, neither a blind increment nor `SELECT ... FOR UPDATE` avoids
  serialization failures under SERIALIZABLE or REPEATABLE READ** (database check, observed):

  | Isolation | T1 and T2 both do | T2 after T1 commits | Final balance |
  |---|---|---|---|
  | READ COMMITTED | `UPDATE acc SET bal = bal + 1` | committed | 2 |
  | READ COMMITTED | `SELECT ... FOR UPDATE`, then the increment | committed | 2 |
  | REPEATABLE READ | the blind increment | `40001 could not serialize access due to concurrent update` | 1 |
  | REPEATABLE READ | `FOR UPDATE`, then the increment | `40001` (same message) | 1 |
  | SERIALIZABLE | the blind increment | `40001` (same message) | 1 |
  | SERIALIZABLE | `FOR UPDATE`, then the increment | `40001` (same message) | 1 |

  In the author's script T2's snapshot is taken before T1 starts (`SELECT 1`), and the lock wait is
  assumed from a `time.sleep(0.5)`, not observed. The database reproduction observed the wait in
  `pg_locks` / `pg_blocking_pids` and got the same six results; it also got them when T2 issued its
  write only after T1 had committed (no wait at all): what decides is that T2's snapshot predates
  T1's commit, not the wait (`repro/db/part_a.py`). Under 4.6's statement order
  (`BEGIN`, `SET LOCAL statement_timeout`, `INSERT INTO run_claim`, `SELECT ... FOR UPDATE`,
  `UPDATE`, `COMMIT`), identical under SERIALIZABLE and REPEATABLE READ (`repro/db/part_b*.py`):
  - the waiter fails (`40001`, at its `SELECT ... FOR UPDATE`) only when the holder **commits an
    actual update** of the row; a holder that only locked the row, or rolled back, lets the waiter
    proceed and commit;
  - a transaction that begins after the holder's commit does not fail;
  - the `run_claim` insert fixes the snapshot: if the whole holder transaction commits between the
    waiter's `INSERT INTO run_claim` and its `SELECT ... FOR UPDATE`, the waiter still fails;
    `SET LOCAL` alone does not fix it;
  - two waiters behind one holder both fail with `40001`;
  - a waiter whose `statement_timeout` expires first ends with `57014` (query canceled), not
    `40001`; 4.6's retry line names `40001` / `40P01` only, so such a waiter is not retried.

  "Commutative increments" (`.add(n)`) therefore do not let two writers of one row coexist under
  the design's isolation levels; they only avoid reading the old value. And `lock="for_update"`,
  which 4.3 and 8.3 name as the hot-row escape hatch, makes a waiter wait and then, when the
  holder updated the row, fail with `40001` and retry; it moves the failure from the commit batch
  to the load stage, it does not remove it. Only READ COMMITTED lets the lock serialise without a
  failure, and 8.3 forbids READ COMMITTED for commands. Taking a lock before the snapshot exists
  avoids it - a `LOCK TABLE` before the first query worked under both levels - but after the
  `run_claim` insert the same `LOCK TABLE` fails with `40001`, and so does `pg_advisory_xact_lock`
  as the first statement (`partB.txt`, scenarios X1, X1', X2). 8.3 already records the REPEATABLE READ half (its
  `StaleSnapshot` correction: "modifying a row that was updated concurrently makes PostgreSQL raise
  40001 first") but still lists `for_update` and REPEATABLE READ as escape hatches (8.3, 7.3, and
  4.6's mapping of `@Lock(PESSIMISTIC_WRITE)`). Because this changes a statement of a section 8
  decision, it is written up as ADR-0005 (Proposed). Rates are not measured here (9.2).
- **X9 - `RunResult.value` is `object`.** `Changes.returning(v)` loses the type; a caller gets it
  back only through `isinstance` or a cast (`fail_findings.py` line 34: pyright
  `reportReturnType`, mypy `return-value`). That line is rejected because of a declaration this
  spike added (`RunResult.value -> object`); the cause lies in spike 0001's surface, where
  `Changes.returning(value: object)` and the non-generic `Usecase[**P]`, `Bound` and `RunResult`
  carry no result type. Whether a generic chain (`Changes[V]`) can type it was not probed.
- **X10 - an empty `Changes` is not shown.** A use case that decides "nothing to do" (7, 10)
  needs one; `Changes()` type-checks only because the stub class has the default constructor.
- **X11 - two ways to write a child.** `order.set(Order.items.update(item, ...))` (4.4, bumps the
  root's version) and `item.set(...)` on the child snapshot both type-check (`probe_accepted.py`
  item 3); the design does not say whether the second is allowed for owned children and whether it
  bumps the root. For non-owned children loaded through a relation (use case 4's stocks) the code
  uses the second form.
- **X12 - inconsistencies in the design text.** The pessimistic lock is `Load(..., lock=FOR_UPDATE)`
  in 3.1 and `Profile(..., lock="for_update")` in 4.3 and 4.6 (H4); the stub follows 4.3, and
  `Load` has no `lock`. `Load.after` "returns a ref or `None`" in 4.7, while 3.1 says "if the
  function returns a list of refs, they are batch-loaded at once".
- **X13 - unchecked bindings** (`probe_accepted.py`, accepted by both): `Load.after`'s function
  type is not tied to the annotated parameter type (item 1: a function returning `Coupon | None`
  for a `Wallet | None` parameter); a Finder on a non-unique column types as one row (item 5); a
  child added to one parent with another parent's key (item 6, #49); `Coupon.ref(order.id)`, a ref
  built from another entity's key (item 8; `ref` takes any `UUID`, not `Id[E]` - with `id: Id[Self]`
  both checkers reject it, and also the 15 `ref(...)` arguments on 11 lines of the use cases that pass
  a raw `UUID`; `repro/types/patches/tight-ref.patch`). Item 2,
  `@process(on=E)` not tied to the handler's event parameter, is **not** such a case: the type
  reproduction showed it is accepted only because this spike's `process` signature is loose (`on:
  type[object]`, a handler bound of `Callable[..., ...]`). With `process[E, **P](*, on: type[E])`
  taking `Callable[Concatenate[E, ProcessContext, P], Awaitable[Bound | None]]`, both checkers
  reject the mismatch (pyright `reportArgumentType`, mypy `arg-type`) and the four real handlers
  still pass (`repro/types/patches/tight.patch`: the variant adds exactly that one rejection in each
  checker and nothing else). The types
  can carry that rule; it is a signature choice and a candidate for the 11.8 misuse list.
- **X14 - an idempotency key reused with different arguments is answered with the stored
  result.** 4.6's run-ID table has no rule for it; rocket-rides rejects it (409) and TigerBeetle
  answers `exists_with_different_<field>`. Use cases 1 and 8.

- **X15 - a relation operation nested in a child update is not shown.** Use cases 4 and 7 write
  `Order.items.update(item, Item.allocations.add(...))` / `.remove(...)`: an operation on a
  grandchild through the owned child. It type-checks (`Item.allocations.add` is an `Op[Item]`), and
  through the owned item it would bump the order's version, but 4.4 shows only column operations
  inside `update`.
- **X16 - a composite unique key has no syntax.** `CouponRedemption` (unique coupon and user) and
  `Stock` (unique warehouse and variant) need one; 4.2 shows `column(unique=True)` and
  `Meta.indexes` / `Meta.checks` only.

### Per use case
Each block: what was written, where it did not fit, the verdict, and the four items of #5.

#### 1. Payment
- Written: `pay` as in 4.5 plus the payment row and the result value; `send_receipt` as a
  `@process` on `OrderPaid` (R1.7: a receipt is external I/O, so `then` - which runs a use case -
  cannot send it); the call site passes `idempotency_key=` to `app.run`.
- R1.1, R1.3, R1.5, R1.6, R1.7: expressed by the run ID (4.6), SERIALIZABLE and rollback, with no
  code in the use case. R1.4: `returning(payment.id)` works, but the caller gets `object` (X9).
  **R1.2: not expressible** (X14). The payment row goes through `Order.payments.add(...)` (X3).
- eShop control: its lookup-then-insert under READ COMMITTED, which keeps the request ID even when
  the command fails, has no counterpart: the `run_claim` insert rolls back with a domain error.
- **Verdict: not expressible** (R1.2, a run-ID rule rather than syntax). Alternatives: (a) the
  runner stores a fingerprint of the bound arguments with the run ID and answers a mismatch with
  an error (`IdempotencyKeyReuse`); needs a stable serialisation of bound arguments (refs by key);
  (b) callers fold an argument hash into the key - then a reused key with other arguments just
  runs, which is not R1.2; (c) state the gap as a documented limit.
- Items: #54 - no entity `==` or key needed; the test compares the inserted payment by fields,
  because an expected `Payment(...)` cannot be built in the test body (outside a use case it is a
  `UsageError`, ADR-0002) and a `Payment.stub()` has another ID. #49 - `Payment(order_id=order.id,
  ...)` added through `Order.payments`; the key is redundant and a wrong key type-checks (X13).
  Identity keys: `returning(payment.id)` needs the ID inside the function, so a payment with an
  `identity` key could not return it. #51 - none (`wallet.balance < order.total` compares
  instances). 9.5 - `wallet.set(Wallet.balance.path(Money.amount).add(-order.total.amount))`,
  70 characters, one occurrence.

#### 2. Refund
- Written: `cancel_order` with the order (`Load(Order.items, Order.payments, Order.refunds)`), the
  wallet and the coupon as `Load.after` dependent loads, the source's greedy refund rule as a pure
  helper over all confirmed payments (wallet parts to the wallet, card parts as provider refunds),
  refund rows through `Order.refunds.add`, and `execute_refund` as a `@process` that returns
  `mark_refund_done.bind(...)`. The first draft sent the whole outstanding amount to the wallet
  whenever one was loaded, counted cancelled items in R2.1, and sized each payment by its full
  amount although part of it may already be refunded; all three were bugs found by the review and
  are fixed (`uc02_refund.py` `choose_payments`, `cancel_order`).
- H2 holds for the expression and only partly for the text: `Load.when(..., match=Wallet.user_id ==
  Order.user_id)` is rejected by both checkers when written as a value (`fail_findings.py` line 40:
  `Operator "==" not supported for types "Column[Wallet, Id[User]]" and "Column[Order, Id[User] |
  None]"`, `reportOperatorIssue`; mypy `Unsupported operand types for ==`, `operator`), by pyright
  only when written inside `Annotated` as 4.7 does (X1). The message names `Id[User] | None`
  because this domain made `Order.user_id` nullable; the rejection does not depend on it - a
  comparison of two columns of the same type, `Stock.allocated <= Stock.quantity` (line 56), is
  rejected the same way (spike 0001, L5). The function form (`Load.after`) holds.
- The dependent-load parameters need a default to be left out of `bind` (X5). R2.3 "minus one,
  never below zero" cannot be an increment (`.add(-1)` has no floor), so it reads the coupon and
  writes `Coupon.used.to(max(coupon.used - 1, 0))`: correct, but the coupon row joins the read set.
  Two `Load.after` functions depend only on stage 1; whether they share one extra stage or add two
  is not stated (9.5 "how many stages"). `refund_wallet` reads the order's loaded payments, which a
  `Load.after` function may do because it runs after stage 1.
- **Verdict: expressed, awkward** (X5, X1, the floor as a read).
- Items: #54 - none. #49 - three `Refund(order_id=order.id, ...)` by hand (a non-owned relation).
  #51 - the 4.7 expression form (column to column), H2. 9.5 -
  `wallet.set(Wallet.balance.path(Money.amount).add(to_wallet))`, 60 characters.

#### 3. Coupon then payment
- Written: `apply_coupon` (a `@step`) and `checkout` with `chain(order, wallet)` exactly as 4.6,
  reusing use case 1's `pay` as the second step. R3.5 and R3.6 come for free: one transaction, and
  a failed `pay` rolls the coupon back (saleor keeps the usage after a payment error).
- R3.3 needs one row by (coupon, user) or its absence (X7). The nearest design form is `Load.when`
  matching the redemption against both the coupon and the user parameter; it fails on #51, on
  combining two predicates, and on reading an absence (X7). Written instead as `user:
  Annotated[User, Load(User.redemptions)]` - a relation declared only for this, loading every
  redemption of the user - and a check in Python.
- R3.7: the coupon row is read and written, so SERIALIZABLE serialises the last use. Which
  SQLSTATE the loser of a race gets was not checked by this spike; the database reproduction
  checked it (SERIALIZABLE, one run per scenario; `repro/db/part_c.py`):
  - when the coupon `UPDATE` precedes the redemption `INSERT`, the loser always fails with
    `40001` at the `UPDATE` - 64 scenarios, one user or two users racing for the last use,
    sequential or index reads, either transaction first; no `23505`;
  - when the `INSERT` is the first conflicting write (a once-per-customer coupon without a usage
    limit, whose row is not updated, or a commit batch that sends the insert first), the loser
    gets `40001` or `23505`: `23505` in 10 of 74 scenarios. In all ten the absence read went
    through an index on the user and the unique (coupon, user) index had been created before that
    index; the same read with the two indexes created in the other order gave `40001`. (Observed;
    the likely mechanism - PostgreSQL inserts index entries index by index, so a uniqueness check
    that runs first reports `23505` before the serialization check - is an interpretation, not
    checked.) Which error a deployed schema gives therefore depends on how its indexes were
    created.

  So R3.3 ("a second use is a domain error, not a database error") holds under concurrency only
  in the first case. In the second, a `23505` surfaces as `UniqueViolation` unless the use case
  sets `on_unique=True` (4.6), whose retry then sees the committed row and raises
  `CouponNotApplicable`; `uc03_coupon_checkout.py` does not set it (and the stub's `usecase`
  overload has no `retry=`). 4.6 orders row changes "in FK/unique dependency order", which does
  not fix the order of these two statements, so which case applies is not under the author's
  control. The verdict stays "expressed, awkward": `on_unique=True` is a design form, at the cost
  of retrying every unique violation of the use case.
- **Verdict: expressed, awkward** (X7 for R3.3).
- Items: #54 - none in the use case; the test looks up the coupon's changes with
  `r.updated(coupon)`, a lookup by entity (see the hand-over table). #49 -
  `CouponRedemption(coupon_id=coupon.id, user_id=user.id)` through `Coupon.redemptions.add` (a
  non-owned relation). #51 - none in the written form; the `Load.when` form needs column-to-column.
  9.5 - `Coupon.used.add(1)` (a plain column, no path). X16: the (coupon, user) unique key.

#### 4. Stock reservation
- R4.1 needs the stock rows of each item's variant (X7). After stage 1 the variant IDs are known,
  so `Load.after` can name the variants, `[Variant.ref(i.variant_id) for i in order.items]` (3.1's
  list form; X12) - the review pointed out that the first draft dismissed this too quickly. What no
  form says is how those refs are loaded: a load declaration attaches to a parameter
  (`Annotated[T, Profile(...)]`), not to the refs a `Load.after` function returns, so their stocks,
  each stock's warehouse and the lock cannot be declared. A Finder on `Stock.variant_id` types as
  one row (X13). Written instead: the caller reads the variant IDs on the query path and passes
  `variants=[Variant.ref(v) ...]` as a `list[Variant]` parameter with
  `Profile(Variant.stocks, Stock.warehouse, lock="for_update")`; the use case re-checks that every
  item's variant is present (the list may be stale) before using it. Not shown by the design: a
  list-of-refs parameter, the nested path (X6), and which rows the profile's lock covers and in
  which order (saleor locks the stock rows in primary-key order to avoid deadlocks).
- R4.5: "no oversell" holds (SERIALIZABLE, and the lock). "Locked instead of serialization
  failures" does not, whatever the syntax (X8, ADR-0005): concurrent allocators of one stock row
  wait and then fail with `40001`.
- Allocations are written as a relation operation inside a child update,
  `Order.items.update(item, Item.allocations.add(Allocation(...)))` (X15); stock increments are
  `stock.set(Stock.allocated.add(qty))` on the snapshots loaded through the variants (X11).
- **Verdict: expressed, awkward** (R4.1 by a caller-side pre-read and a re-check - the rule moved
  partly to another transaction; X6, X15). The first draft said "not expressible", counting R4.5's
  mechanism; the review disagreed and the write-up now follows the review (see Reproduction).
  Alternatives for R4.1, for the maintainer: (a) a load declaration that applies to the refs a
  `Load.after` function returns (for example `Load.after(variants_of, Profile(...))`); (b) a set
  load with a predicate over stage-1 values; (c) keep the caller-side pre-read and document the
  re-check pattern.
- Items: #54 - none (dicts keyed by IDs); the test looks up stock changes with `r.updated(a)` on
  snapshots nested inside the variants. #49 - `Allocation(item_id=item.id, ...)` (a non-owned
  relation of the owned item). #51 - the table check `Stock.allocated <= Stock.quantity` is
  rejected by both (`fail_findings.py` line 56: pyright `reportOperatorIssue`, mypy `operator`).
  9.5 - `Stock.allocated.add(qty)` (no path). X16: the (warehouse, variant) unique key.

#### 5. Seat reservation
- R5.5 needs nothing written: the reads of the use case are the predicate a concurrent hold
  writes into, so SERIALIZABLE aborts one of two overlapping holds (the design's claim; expected
  from SSI, not run here - 9.2).
- R5.2 needs two existence reads over predicates (H5 holds): "an active ticket of a PENDING/PAID
  order" (a predicate across `Ticket.order`) and "a hold with `expires_at >= now` of another user"
  (a predicate on an injected value). A static partial load can state neither (X7); a literal
  predicate such as `Seat.tickets.where(Ticket.status == ACTIVE).exists()` type-checks but is not
  the rule. Written instead: `Profile(Seat.tickets, Ticket.order, Seat.holds)` (nested, X6) and a
  check in Python, which over-reads expired holds and cancelled tickets.
- R5.3 needs "taken seats near this seat"; written as "load the whole show with its seats, tickets,
  orders and holds". Correct, and under SERIALIZABLE it makes every hold of the show conflict with
  every other (what pretix gets from its event-wide lock when the distance rule is on), but each
  hold reads the whole seating plan.
- **Verdict: expressed, awkward** (X7 and X6; R5.3 by over-reading).
- Items: #54 - the seat appears twice, as the parameter and inside `show.seats`, as two snapshots
  with different relations loaded; the code compares IDs (`other.id == seat.id`). Under the
  provisional rule `==` would compare load state too, so these two snapshots of one row would be
  unequal. #49 - `SeatHold(seat_id=seat.id, ...)` through `Seat.holds.add`. #51 - none (the
  comparisons run in Python on loaded values). 9.5 - none.

#### 6. Order merge
- Two parameters of one type need no dependent load here (the source has none; the 9.4 column
  "`Load.after`" was an expectation the source does not need). Lines with the same variant grow
  by `Order.items.update(match, Item.quantity.add(n))`; other lines are copied with
  `Order.items.add(Item(order_id=dst.id, ...))` (the source copies too, so no "move" is needed; a
  move operation does not exist - H6 holds, without consequence here). R6.4 recalculates dst's
  total from its active lines after the merge (the first draft added the source lines to the old
  total, and then counted cancelled lines; both fixed after the review).
- **R6.5 is not expressible** (X4): `src.set(*(Order.items.remove(i) ...))` removes the lines, the
  order row itself has no delete; placeholder `UNDECIDED_delete(src)`.
- What the loader does when `src` and `dst` are refs to one row (two snapshots? one?) is not
  stated; the use case rejects equal IDs before writing.
- **Verdict: not expressible** (R6.5). Alternatives: (a) a delete operation on a root snapshot
  (for example `order.delete()`, cascading to owned children), (b) a set change
  `Order.where(Order.id == x).delete()` (no invariant to check), (c) a status instead of a delete
  (`MERGED`), which changes the requirement.
- Items: #54 - `src.id == dst.id`, not `src == dst`; the test passes one stub as both arguments,
  and looks up a child's changes with `r.updated(line)`. #49 - the copied `Item(order_id=dst.id,
  ...)` (owned). #51 - none. 9.5 - `Item.quantity.add(...)` inside `update` (no path).

#### 7. Expire unpaid orders
- The set change of 4.3 / 4.8 (`fail_findings.py`, `expire_due_set_change`) cannot state R7.1,
  R7.3, R7.4 or R7.5: a predicate over the order's show is `Pred[Show]` and rejected by
  `Order.where` (line 65: pyright `reportArgumentType`, mypy `arg-type`); `expires_at + delay`
  needs column arithmetic; releasing coupons and stock writes other tables; a set change returns
  no count and has no limit. 4.13's `SealError` is this case (H7 holds): `Order.status` is
  protected by `@invariant`, so the set change needs `unsafe_bypass=` (the stub's `SetChange.set`
  had no such parameter; added from 4.13's fix text).
- The design's third bulk path, `@batch_usecase(chunk=..., cursor=..., job=...)` (4.8; 3.2
  "chunked update"), was missed by the first draft and checked after the review: its chunk function
  is plain Python over loaded rows, so R7.1 and R7.3 could be written there; but it walks all rows
  of an entity by cursor with no filter predicate shown, its `job=` name is a one-shot checkpoint
  (a recurring expiry would need a new name per run), it has no limit per run and no count, and it
  is Phase 2 (9.6). It does not fit a recurring "expire what is due" job as shown.
- Written instead, in the source's own shape: a query (`expiry.due(now)`, joins the show, limit
  100) picks candidates on the query path; the scheduler runs `expire_order` once per order; the
  use case re-checks status, the show's setting and the delay (R7.6), releases allocations
  (through the owned item, X15) and the coupon, and emits `OrderExpired`; `notify_expired` is a
  `@process` (R7.7). It needs a three-level nested load (X6), an empty `Changes` for "nothing to
  do" (X10), and the count is summed from the runs' `returning(...)` values (X9).
- **Verdict: expressed, awkward** with one use case per order; **the set change form does not
  express the rule** (what 9.4 tests here). `emit_each` itself type-checks on the set change.
- Items: #54 - none. #49 - none. #51 - `expires_at + show.expire_delay_days` is column arithmetic
  across entities, outside #51's scope (operand types) - a new question; the owner check rejects
  `Show.auto_expire == True` inside `Order.where` (an owner question, not an operand one). 9.5 -
  `Stock.allocated.add(-a.quantity)` (no path).

#### 8. Account transfer
- Two `Account` parameters with `Load()` need nothing special. R8.4 reads the source balance, so
  the source half is not a blind increment (H8 holds): the source row is in the read set whatever
  syntax writes it. R8.3 is written with two path increments.
- R8.2: `Transfer` is a new root with owned legs, written `insert_all((t, credit, debit))` (X3;
  the first draft used a placeholder and called R8.2 not expressible - the review pointed to
  `insert_all`). Open: whether the bulk path may share the commit batch with the two balance
  updates. "The legs sum to zero" spans rows: `Check` is per row and `@invariant` per snapshot, so
  it holds by construction only (hordak: a deferred constraint trigger).
- **R8.5 is not expressible**: the client's transfer ID can be the run's idempotency key but not
  the `Transfer` primary key (`pk(generated=...)` is not a constructor parameter), and a repeat with
  different fields gets the stored result instead of TigerBeetle's `exists_with_different_<field>`
  (X14, the same gap as R1.2).
- R8.6: "never overdraw" holds (the source row is read and written under SERIALIZABLE). "Transfers
  into one account do not conflict" does not hold under the design's isolation levels, whatever the
  syntax (X8, ADR-0005): two transfers into one account update one row, and the second fails with
  `40001` and retries. Meeting it needs a different model (append-only legs with a computed or
  asynchronously maintained balance, as hordak stores it).
- **Verdict: not expressible** (R8.5, the run-ID rule X14). The first review judged "expressed,
  awkward"; after R8.5 was pointed out it agreed (see Reproduction). Alternatives for R8.5 are
  X14's (use case 1).
- Items: #54 - `src.id == dst.id` (the rule "accounts must be different" is about keys). #49 -
  `Leg(transfer_id=t.id, ...)` by hand (owned children of a new root). #51 - none. 9.5 -
  `src.set(Account.balance.path(Money.amount).add(-amount.amount))`, 63 characters, twice;
  `Money.amount` and `amount.amount` in one line.

#### 9. Profile edit
- R9.1 and R9.6: `User.ref(user_id, expected_version=if_match)` and `owned=True` on
  `User.addresses` - exactly 4.6's pattern; an address-only change bumps the user's version.
- R9.2: a patch is a list of operations built conditionally, `ops: list[Op[User]]`, then
  `user.set(*ops)`. R9.3: the diff is keyed by address IDs (`{a.id: a for a in user.addresses}`),
  creating with `User.addresses.add(Address(user_id=user.id, ...))`, updating only changed fields
  with `User.addresses.update(old, *changed)`, deleting with `User.addresses.remove(...)`. R9.4:
  the default may point at an address created in the same use case - possible only because its ID
  is client-generated (uuid7).
- Not a syntax question, noted for 10.7: `users.default_address_id` references `addresses` and
  `addresses.user_id` references `users`, so the commit order of this use case (insert the new
  address, then update the user; update the user, then delete the old address) needs edges for
  updates of FK columns. The two tables form an FK cycle, but the row-level order is acyclic
  (insert the new address, update the user, delete the old address), so 8.3's cycle error does not
  apply; the gap is that 10.7 names edge kinds for inserts and deletes only, none for updates.
- **Verdict: expressed.**
- Items: #54 - not needed: the diff keys are IDs, H9's "dict/set keys" are not entity keys. #49 -
  `Address(user_id=user.id, ...)` by hand (H9 holds). Identity keys: with `generated="identity"`
  the new default address could not be referenced in the same use case. #51 - none. 9.5 - none.

#### 10. Payment approval notice
- Written as 4.10: `request_card_payment` emits `PaymentRequested`; `approve_payment` is a
  `@process` that calls the gateway with `ctx.idempotency_key` and returns
  `confirm_payment.bind(...)` or `decline_payment.bind(...)`; `confirm_payment` emits `OrderPaid`,
  and use case 1's `send_receipt` reacts to it.
- H10: the notice does not follow through `then`: `then` runs a use case, which cannot send
  anything. One use case per `@process` is enough; the notice is a second `@process` on the event
  the first use case emits. R10.3 and R10.5 follow from the job pipeline (run ID = job ID).
- R10.4: a gateway error raised by the handler is "transient" only if the job runner classifies
  it so; 4.10 lists connection, timeout and exhausted `40001` as transient and domain exceptions
  as dead-letter, and says nothing about other exceptions from a handler.
- `@process(on=PaymentRequested)` is not tied to the handler's event parameter in this spike's
  stub; the type reproduction showed a tighter `process` signature ties it in both checkers (X13
  item 2), so this is a stub choice, not a gap of the design. Tests: a `@process` returns an opaque
  `Bound`; which use case and arguments it describes cannot be asserted (4.12 shows no test for
  handlers).
- **Verdict: expressed, awkward** (R10.4 rests on an unstated rule; the opaque `Bound` in tests).
- Items: #54 - none. #49 - `Payment(order_id=order.id, ...)` through `Order.payments.add`. #51 -
  none. 9.5 - none.

### Stub additions
Signatures the design does not give, added with `# [0002]` as the minimum the use cases needed.
**None of them is confirmed by spike 0001 or proposed by this spike.** The last column names
choices a signature makes that the design has not made (from the review); none of them changes a
verdict.

| Added | Why | Design reference | Choice the stub made |
|---|---|---|---|
| `Column.__gt__`, `__le__` | comparisons the use cases or probes wrote | 4.3 shows `<`, `>=` | - |
| `Relation.where(*preds: Pred[E])`, `Relation.exists()` | partial loads | 8.2 names them, no signature | `where` returns a `Relation`, so a filtered relation is also a write target |
| `fk(target, *, default=...)` overload | nullable FKs (`Order.user_id`, `coupon_id`, `show_id`) | 4.2 shows required FKs only | - |
| `SetChange.set(..., unsafe_bypass=...)` | the 4.13 fix text | 4.13 | - |
| `StepResult.updated / inserted / removed / then / value`, `Add[T]` | 4.12 / 11.11 assertions | calls shown, no signatures | `updated` returns a mapping keyed by expressions; lookups take an entity |
| `then(bound) -> Changes` | 4.6 | shown, not checked by 0001 | - |
| `insert_all(entities) -> Changes` | use case 8 (X3) | 4.8 | takes an iterable of any entities |
| `UNDECIDED_insert`, `UNDECIDED_delete` | **placeholders** for X3 / X4 (only `UNDECIDED_delete` is still used) | none | - |
| `Load.when(cond, *, match)`, `Load.after(fn, *, missing=...)` | dependent loads; the loaded type is not tied to the function (X13) | 4.7 | `missing="error"` is an invented literal for the default |
| `usecase(*, isolation=..., timeout=...)` overload | 4.6 options form (not used by the use cases) | 4.6 | string literals instead of 4.6's constants; no `retry=` |
| `RunResult.run_id / value / events / created(kind)` | 4.5 | shown, `value` untyped (X9) | `created` returns a sequence of IDs |
| `App.provide`, `ProcessContext.idempotency_key`, `RetryLater`, `DomainError(retry_later=...)`, `process(*, on=...)` | 4.10 | shown, not checked by 0001 | `process` takes `on: type[object]` and any async callable, so the event type is not tied to the handler (X13 item 2; a tighter signature is typable) |

## Verdict

| # | Use case | Verdict | One line |
|---|---|---|---|
| 1 | Payment | **Not expressible** | Run ID, retries and the receipt fit; a key reused with other arguments is answered, not rejected (X14) |
| 2 | Refund | Expressed, awkward | `Load.after` holds, `Load.when` with column-to-column `match` does not (#51); dependent-load parameters need a default to leave `bind` (X5) |
| 3 | Coupon then payment | Expressed, awkward | `chain` works as 4.6; "used by this customer?" over-reads a relation, `Load.when` is blocked three ways (X7) |
| 4 | Stock reservation | Expressed, awkward | The stock rows cannot be declared (X7): the caller pre-reads the variants and the use case re-checks; `for_update` still ends in `40001` (X8, ADR-0005) |
| 5 | Seat reservation | Expressed, awkward | SERIALIZABLE covers the write skew with nothing written; availability reads over-read whole relations (X7, X6) |
| 6 | Order merge | **Not expressible** | No delete for a root row (X4); same-row parameters unspecified |
| 7 | Expire unpaid orders | Expressed, awkward (set change: does not express it) | Cross-entity rules, side tables, count and limit fit neither a set change nor `@batch_usecase`; per-order use cases do, with nested loads (X6) |
| 8 | Account transfer | **Not expressible** | Same key-reuse gap as 1 (X14); the new root goes through `insert_all` (X3); increments into one row still conflict (X8) |
| 9 | Profile edit | Expressed | `expected_version` + owned children as 4.6 shows; diff keyed by IDs |
| 10 | Payment approval notice | Expressed, awkward | `@process` returning one use case suffices; the notice is a second `@process`, not `then`; transient-error rule unstated |

Overall: **partly.** The core of section 4 - snapshots, `.set` operations, `chain`, `bind`,
`expected_version`, owned children, `@process` returning a description - expressed every rule it
was meant for. It does not hold as "the syntax for real use cases" yet: three use cases need a
decision (delete of a root; reuse of an idempotency key with other arguments, twice), the others
carry workarounds that a decision would remove (set loads, loads on `Load.after` results, nested
paths, the `bind` rule for dependent loads, `insert_all` in the commit batch), and one design
statement about hot rows does not hold on PostgreSQL (X8, ADR-0005).

### Hand-over table

| Topic | What the use cases showed | Use cases | Goes to |
|---|---|---|---|
| Parent key of children | Every child creation passed the parent key by hand and type-checked: 12 constructor calls in 9 use cases. Only 4 are owned children (an item, an address, two legs); the other 8 go through non-owned relations (payments, refunds, a redemption, an allocation, a hold), so #49's question is wider than owned children. The redundant key can disagree with the parent it is added to, and both checkers accept it (X13 item 6). Identity keys: five places needed the new ID inside the function (use case 1 `returning(payment.id)`, 2 and 10 events carrying the new row's ID, 8 the legs of a new transfer, 9 a new default address), so none of them could use an `identity` key | 1-6, 8-10 | #49 |
| Column comparison operands | Needed column-to-column twice (4.7 `Load.when` `match`; a table check `allocated <= quantity`), both rejected by both checkers (also between two columns of the same type, type reproduction `12-x51-same-type.txt`); a third time if use case 3's lookup is written with `Load.when`. Never needed numeric literal widening (comparisons ran in Python on loaded values). Also needed column arithmetic (`expires_at + delay`), outside #51's scope. Inside `Annotated`, mypy does not check the comparison at all (X1) | 2, 3, 4, 7 | #51 |
| Entity equality and hashing | No use case needed entity `==` or an entity as a set member or dict key: every "same row" question (merge, transfer, seat in show) compared IDs, and every diff was keyed by IDs. But the test API does look rows up by entity: `r.updated(entity)` / `r.removed(entity)` on snapshots that were nested (a stock inside a variant, a line inside an order) or passed through a chain, which needs key-based identity (type + primary key) for the lookup. Tests compared inserted rows by fields, because an expected entity cannot be constructed in a test body and a stub has another ID. The provisional rule's concern showed once: one row loaded through two paths gives two snapshots that would be unequal (use case 5). 4.12's dict-literal assertion is a pyright error (X2) - a `Column` hashing question, not an entity one | 1, 3, 4, 5, 6, 8 | #54 |
| `path(...).add(...)` length | 3 of 10 use cases, 4 lines: 60-70 characters for one increment of a part of an embedded value (`wallet.set(Wallet.balance.path(Money.amount).add(-order.total.amount))`); every other increment is a plain column (`Coupon.used.add(1)`, `Stock.allocated.add(qty)`, 30-46 characters). The length is concentrated in money; the increment brings no concurrency benefit on the same row (X8) | 1, 2, 8 | design 9.5 |
| Commit planner | Use case 9 needs edges for updates of FK columns (insert an address, then point the user at it; clear the user's default, then delete the address). The tables form an FK cycle but the row-level order is acyclic; 10.7 names edge kinds for inserts and deletes only | 9 | #15 (comment), #6 |
| Phase 1 scope | Phase 1 needs: a delete for a root (X4) and a rule for `insert_all` in the commit batch (X3) - basic writes, not features; a decision on loads for `Load.after` results and set loads (X7), or a documented caller-side pattern; the `bind` rule for dependent loads (X5, with #48); nested load paths (X6); the commit planner row above; the key-reuse rule (X14). `@batch_usecase` (Phase 2) does not cover recurring "expire what is due" jobs as shown. The `@process` handlers of 1, 2, 7, 10 are Phase 2 (9.6), so in Phase 1 no use case can send a receipt or execute a refund. The hot-row text needs ADR-0005 before it is documented | all | #6 |

Consequence for the design: X8 changes a statement of a section 8 decision, so it is ADR-0005
(Proposed), linked from 7.3 and 8.3 with a note; the decision itself is not changed until the
maintainer accepts it. The other findings are open questions for the maintainer, each with
alternatives above, now tracked as issues: X4 (delete a root) #57, X14 (key reuse) #58, X7 and X6
(set loads, loads on `Load.after` results, nested paths) #59, X3 (`insert_all` in the commit
batch, inserting through parent relations) #60. Proposed as scope of existing issues (comments,
bodies left to the maintainer): X5 (the `bind` rule for dependent loads) #48, X2
(`Column.__hash__`) #10 and #27, X13 item 2 (the `@process` signature) #32, FK-update edges of the
commit planner #15. Smaller text fixes once decided: X12 (3.1 vs 4.3 / 4.7), X1 (where load
declarations are written, or stating that seal is their only check under mypy), X15, X16.

## Reproduction

### Independent review (architect sub-agent), round 1
- **Who:** the `architect` sub-agent, given only this write-up and the repository (the code under
  `spikes/0002-use-cases-on-paper/`, the design document, ADR-0003/0004, spike 0001); not the
  author's conclusions. **Date:** 2026-11-25. It had no shell in that session and checked every
  cited line number against `results/*.txt` instead of rerunning the checkers.
- **Verdict:** approve with changes. It agreed with use cases 1, 2, 3, 5, 6, 7, 9, 10 and disagreed
  with two:
  - Use case 4: "expressed, awkward", not "not expressible" - by this write-up's own scale the
    caller-side pre-read is a workaround (as in use case 7), and R4.5's "instead of serialization
    failures" is a mechanism, not a business rule. **Accepted**; the write-up changed.
  - Use case 8: "expressed, awkward" - `insert_all` (4.8) expresses the new root, so X3's "cannot
    be written at all" was false. **Accepted for R8.2** (the code now uses `insert_all`, X3
    narrowed); the verdict stays "not expressible" because of R8.5 (round 2).
- **Errors it found and what was done:**
  - False or incomplete gap claims: `insert_all` missed (X3, use case 8); `Load.after` returning
    variant refs dismissed too quickly (use case 4); `Load.when` left out of X7 (use case 3);
    `@batch_usecase` not evaluated (use case 7). All four corrected in the text above.
  - Silent trims: use case 2 (voucher per position, "stays paid if covered", gift cards), use case
    7 (three selection conditions), use case 9 (two defaults), use case 5 (channel became show),
    use case 1 (409 while in progress). Now stated under "Changed when porting"; R2.2 and R2.3 were
    corrected to the source.
  - Code that weakened a requirement: use case 2 R2.5 (whole amount to the wallet) and R2.1
    (cancelled items counted); use case 6 R6.4 (old total plus source lines); use case 4 (stale
    check after the lookup). Fixed.
  - Missing findings: X15 (relation operation nested in an update), X16 (composite unique keys),
    the commit-planner row, lookups by entity in the test API (#54 row), the #49 scope (8 of 12 child
    creations are not owned). Added.
  - Evidence: unmarked stub lines and stub signatures that make choices (now marked and listed).
    The cited `fail_findings.py` and probe line numbers matched the raw output.
  - X8 needs an ADR in the same change (it contradicts 7.3 and 8.3): ADR-0005 (Proposed).
  - R3.7's "40001 or 23505" is an unverified PostgreSQL fact: now marked as not checked.

### Independent review, round 2
- **Who / date:** the same sub-agent, 2026-11-25, rereading the changed files.
- **Use case 8:** it agreed that R8.5 (TigerBeetle's `exists_with_different_<field>`, fixed before
  the code) is the same gap as R1.2 (X14), so consistency requires "not expressible"; it withdrew
  its disagreement. **No disagreement remains on the ten verdicts.**
- **Remaining errors it found and what was done:** the Korean translation of the design not yet
  updated (done by the `translator` sub-agent in this change); this section empty (filled); stub
  lines still unmarked (marked); use case 2's greedy rule ignored refunds already made against a
  payment (fixed, `choose_payments`); use case 6 counted cancelled lines (fixed); X7 said
  `missing="none"` belongs to `Load.after` only, while 8.2 states it generally (reworded: unstated
  for `Load.when`); the commit-planner text implied a cycle error that row-level ordering avoids
  (reworded).
- **ADR-0005:** changes needed, then fine to stay Proposed: add that the observation is one run
  and not reproduced, link PostgreSQL's documentation, add the retry limit (`RetryExhausted` under
  sustained contention); do not pre-decide the removal of `lock=`; remove "an inline projection" as
  an answer for hot rows (it updates its target inside the same SERIALIZABLE transaction) and state
  the ledger model as a candidate to measure, since an overdraft check reads the legs; add the
  alternatives of a separate non-SERIALIZABLE counter, of locking before the snapshot (`LOCK
  TABLE`), and of a retry policy for lock waiters. All applied to ADR-0005.

### Type reproduction (type-reviewer)
- **Who / date:** the `type-reviewer` sub-agent, 2026-11-25, launched by the maintainer's session
  (not by the author), given this write-up and the code; it did not run the spike. It wrote its
  own probes; the sources are now in `repro/types/` (probes, and the stub variants as patches),
  their first output in the git-ignored `results/repro-types/`. The author of this write-up
  compared the write-up with that output; the author did not rerun it as a reproduction (the
  moved sources were only checked to run at their new path). File names `00-...` to `12-...` below
  are that first run's git-ignored output; `run.sh` regenerates the checker, probe and regression
  output, not the version and gate listings (`00-`, `01-`) or the stub listings (`07-`).
- **Setup:** Python 3.14.7, pyright 1.1.414, mypy 2.4.1 (compiled), psycopg 3.3.9 - the same as
  Setup (`01-versions.txt`). Repository gates clean (`00-repo-gates.txt`).
- **Ran and observed:**
  - The 14-file `tools.typetests` command of Method: `0 problem(s) in 14 file(s)`
    (`02-typetests-14.txt`). **Agree.**
  - `fail_findings.py` lines 34, 40, 52, 56, 65: rejected by both checkers with the codes and
    reasons stated in X5, X9, use case 2, use case 4, use case 7. **Agree.** A column-to-column
    comparison of two columns of the same type is rejected the same way (`12-x51-same-type.txt`).
  - X1 (`probe_annotated_metadata.py`): pyright reports lines 13, 18, 26, 32, 34; mypy only 13 and
    34. **Agree.** Extended: mypy reports nothing inside `Annotated[...]` metadata at all (X1 now
    says so; `base/x1_extra.py`, `10-x1_extra-*.txt`).
  - X2 (`probe_column_key.py`): pyright `reportUnhashable` at lines 22 and 25, mypy silent.
    **Agree.** As a new probe of its own it tried `Column.__hash__` (X2; `patches/hash.patch`) -
    run once, not reproduced.
  - X13 (`probe_accepted.py`, `10-x13_reveal-*.txt`): items 1, 5, 6, 8 are real limits of the
    design's signatures. **Agree.** Item 2 (`@process(on=E)` not tied to the handler): **disagree**
    - it is accepted only because this spike's `process` signature is loose; with
    `process[E, **P](*, on: type[E])` taking `Callable[Concatenate[E, ProcessContext, P], ...]` both
    checkers reject it and the four real handlers still pass (`patches/tight.patch`). The
    write-up now says so (X13, use case 10, Stub additions). The reproducer also tried item 1
    with `Load.after` carrying the function's result type (`patches/tight-after.patch`): no
    rejection in either checker, so item 1 stays a limit (an earlier version of this write-up
    cited that output for item 2 by mistake). Item 8
    with `ref(id: Id[Self])`: both reject it, and also 15 `ref(...)` arguments on 11 lines of the use
    cases that pass a raw `UUID` (`tight-ref/`, `11-tight-ref-*.txt`; the maintainer's summary said
    "15 call sites", which are 15 arguments on 11 lines).
  - Stub marking: **partly** - ten continuation and decorator lines of added declarations were not
    marked `# [0002]` (`07-stub-unmarked.txt`); now marked. Spike 0001's pinned files still pass
    against this stub (`09-regress0001.txt`).
  - X9: the rejection at line 34 comes from this spike's `RunResult.value -> object`; the cause
    is spike 0001's non-generic surface (X9 now says so).
  - Stale output: three pairs of files in `results/` came from an earlier batch and showed errors
    that no longer exist; deleted.
- **Verdict:** agree on every checker result the write-up cites; disagree on X13 item 2 (fixed in
  the text); the other points were additions, now in the text. No use case verdict changes:
  use case 10 stays "expressed, awkward" on R10.4.

### Database reproduction (pg-researcher)
- **Who / date:** the `pg-researcher` sub-agent, 2026-11-25, launched by the maintainer's
  session, from this write-up; it did not run the spike. Scripts and raw output in
  `repro/db/` (`harness.py`, `script.py`, `part_a.py`, `part_b*.py`, `part_c.py`, `summarize.py`;
  output in the git-ignored `results/repro-db/`). The
  author compared them; the author did not rerun them.
- **Setup:** PostgreSQL 18.6 (`PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2) on aarch64-unknown-linux-
  gnu`), psycopg 3.3.9 (libpq 18.0.6), fast profile (port 26432, `fsync = off`), one run per
  scenario with pinned interleavings and lock waits observed in `pg_locks` / `pg_blocking_pids`.
  Documentation consulted: PostgreSQL 18, sections 13.2.2, 13.2.3, 13.3.2 (`FOR UPDATE`), 13.4.2.
- **A - X8's six rows** (`partA-verified.txt`, `partA-original-script.txt`): all six reproduced;
  in the `FOR UPDATE` rows the failure is at the `SELECT ... FOR UPDATE`. The same results when T2
  writes only after T1 committed (no wait). **Agree**, with two notes now in X8: the author's
  script pins T2's snapshot before T1 starts (narrower than its comment) and assumes the lock wait
  from a sleep.
- **B - design 4.6's statement order** (`partB.txt`, `partB-three-sessions.txt`,
  `partB-timeout.txt`), identical under SERIALIZABLE and REPEATABLE READ: the waiter fails with
  `40001` only when the holder commits an update of the row; lock-only or rolled-back holders let
  it commit; a transaction that begins after the holder's commit does not fail; the `run_claim`
  insert fixes the snapshot (`SET LOCAL` does not); `LOCK TABLE` before the first query avoids the
  failure, after `run_claim` it does not, and `pg_advisory_xact_lock` as the first statement does
  not; two waiters both fail; a `statement_timeout` during the wait gives `57014`. **Agree** with
  X8's direction; its conditions were missing and are now in X8 and ADR-0005.
- **C - R3.7's SQLSTATE** (`partC-asked*.txt`, `partC-extra*.txt`): coupon `UPDATE` before the
  redemption `INSERT`: always `40001` at the `UPDATE` (64 scenarios, no `23505`); `INSERT` as the
  first conflicting write: `40001` or `23505` (10 of 74), depending on index creation order (use
  case 3). This answers a question the spike had left open; use case 3 now records it. No verdict
  changes.
- **Not run by the reproducer:** rates, part C under REPEATABLE READ, a whole checkout use case,
  pipelined batches, the durable profile.

### Not done
- Not reproduced by a second agent: the `Column.__hash__` probe (X2) and part C's extra scenarios
  (the `INSERT`-first cases) were each run once by the reproducers themselves, as new probes.
- Rates (how often hot rows and the coupon race fail, `RetryExhausted`) are not measured: 9.2.
