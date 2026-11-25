# Platina

Translations: [Korean](README-KO.md)

> *Platina* is the old Spanish name of platinum. Platinum resists acids and does not react;
> domain code does not react with the database.

Platina is an ORM for Python 3.14+ and PostgreSQL built on one rule: **domain code never knows
the database exists.** Use cases declare the data they need in their signature, run as pure
functions over immutable snapshots and return their changes as data. All I/O happens in one
place (`app.run` / `app.query`), in a transaction the library owns, with SERIALIZABLE and
automatic retries by default.

```python
type PayableOrder = Annotated[Order, orders.payable]

@usecase
def pay(order: PayableOrder, wallet: Annotated[Wallet, Load()], now: Now = INJECTED) -> Changes:
    if order.status is not OrderStatus.PENDING:
        raise AlreadyPaid(order.id)
    return (
        order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now))
        + wallet.set(Wallet.balance.path(Money.amount).add(-order.total.amount))
    )

await app.run(pay.bind(order=Order.ref(order_id), wallet=wallets.by_user(user_id)))
```

## Status

**Design settled, implementation just started.** Only the exception hierarchy
(`platina.PlatinaError` and its subclasses) exists so far; the code above is the target syntax,
not a working API. The type-surface spike ([`docs/spikes/0001-type-surface.md`](docs/spikes/0001-type-surface.md))
and the ten use cases on paper ([`docs/spikes/0002-use-cases-on-paper.md`](docs/spikes/0002-use-cases-on-paper.md))
are done; the remaining experiments in the design document (SSI concurrency, Alembic round trip,
measurements) come before the rest of the prototype.

- Design document: [`docs/design/design.md`](docs/design/design.md)
- Current architecture: [`docs/architecture.md`](docs/architecture.md)
- Decisions after the design document: [`docs/adr/`](docs/adr/)
- How the repository is developed (coding agents + a human maintainer):
  [`docs/workflow.md`](docs/workflow.md)

## Development

Requires [uv](https://docs.astral.sh/uv/) and, for integration tests, Docker.

```bash
uv sync              # dependencies
make check           # fast gate: lint, pyright + mypy, guards, unit and type tests
make db-up           # PostgreSQL 18 on localhost:26432
make check-all       # everything, including integration tests
make help            # all targets
```

Agents and humans follow the same rules: [`AGENTS.md`](AGENTS.md).

## License

Apache-2.0.
