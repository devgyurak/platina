---
description: The design principles every change must keep - no implicit I/O, immutability, one way, remove rather than detect
paths:
  - "src/**"
  - "tests/typing/**"
  - "docs/design/**"
---
# Design invariants

These come from `docs/design/design.md` sections 1-2 and 8. No guard can check most of them;
`architect`, `arch-guardian` and `code-reviewer` do. Breaking one is a BLOCKER unless an accepted
ADR says otherwise.

## Priority
**Correctness > explicitness > incremental convenience > performance.** When two options trade
these off, pick by this order and say so in the commit body or ADR.

## The three pillars
1. **Declared reads.** A use case declares everything it loads in its signature
   (`Annotated[Entity, Load(...)]`, `Load.when`, `Load.after`, `Load.recursive`). The number of
   load stages is fixed at seal time, never discovered while running. No generators in use cases.
2. **Pure domain.** Snapshots are immutable. A use case or step is a plain function from snapshots
   to `Changes`: no session, no `await`, no I/O, no effect requests. External I/O lives only in
   `@process` handlers, which return a *description* of the use case to run, never call `app.run`.
3. **Changes are data.** No dirty checking. `Changes` can be inspected, combined and serialized.

## Rules that shape every API
- **No implicit I/O.** Attribute access never hits the database; an unloaded relation raises at
  once (`RelationNotLoaded`). A ref placeholder raises on field reads, on `.set` and on `.delete()`
  (`UnloadedReference`).
- **Safe defaults, danger is opt-in.** `lazy="raise"`, no expiry, no autoflush, SERIALIZABLE for
  commands. READ COMMITTED is never allowed for commands (the escape hatch is REPEATABLE READ +
  `version`).
- **The library owns the boundary.** `app.run()` once = one transaction. No session objects
  passed around, no transaction API inside a use case.
- **Configuration never changes meaning.** If behaviour differs, the name (syntax) differs. Never
  add a flag that makes the same code mean something else.
- **One way to do each thing.** Writes, one verb per operation (ADR-0010, Proposed): a loaded
  row is modified with `.set(Column op)` and deleted with `.delete()`, a new row is written with
  `insert(entity, *children)`; the rows of an `owns_many` relation only through their root
  (`Order.items.add/update/remove`), every other row directly. Creation: the keyword constructor
  `Order(...)` of an `Entity` subclass (ADR-0003); there is no `new`. Embedded paths:
  `Order.total.path(Money.amount)` (ADR-0004). Composition across steps: `with chain(...)`.
  Execution: `app.run` / `app.query`. Do not add a second syntax for the same operation.
- **Remove rather than detect.** Prefer making a mistake impossible (structure, a type error) over
  detecting it afterwards. A runtime check is the last resort, and must fail immediately and
  deterministically.
- **References, not strings; codegen, not runtime magic.** Fields are referenced as attributes
  (`Order.status`), other classes through `lambda`, never by name strings.
- **Errors point at the cause** (use case, file:line, the declaration to add) - design section 4.13.
- **Small core, batteries as official plugins.** Soft delete, audit, multi-tenancy, pagination,
  Pydantic and saga helpers live outside the core.

## Transaction and storage invariants (design section 8.3)
- Commands: SERIALIZABLE + automatic retry on 40001/40P01, always restarting from the load.
  23505 is retried only with `on_unique=True`; the run-ID table's 23505 is the idempotency path.
- Every `app.run` has a run ID, claimed by `INSERT` into `run_claim` **without a prior read**,
  as the first table statement (after `BEGIN` and the budget's `set_config`).
- **Internal tables** (`run_claim`, `run_result`, the outbox log, job tables, consumer
  checkpoints) are **never read or updated inside a SERIALIZABLE transaction** - a use case's
  transaction only INSERTs into them. Outside SERIALIZABLE the design does update some of them:
  consumer checkpoints (REPEATABLE READ, design section 8.4) and job leases (short READ COMMITTED
  transactions). `run_claim`, `run_result` and the outbox log are never updated anywhere.
- Load batch + commit batch = two round trips (plus one per `Load.after` stage).
- `version`: optimistic lock between requests, event order, intra-use-case overlap detection,
  coexistence with other ORMs. Event sequence numbers are filled in by the engine, never by hand.
