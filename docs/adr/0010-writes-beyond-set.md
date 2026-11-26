# ADR-0010: Writes beyond `.set`: `insert`, `delete`, and owned rows only through their root

- Status: Proposed
- Date: 2026-11-26
- Related: design sections 4.2, 4.3, 4.4, 4.6, 4.8, 4.12, 8.2 ("Write syntax", "Aggregate
  boundaries", "Field type surface", "Creation syntax"), 8.3, 9.6, 10.7, 10.12, 11.3, 11.8; issues
  #57 and #60 (closed by this ADR's PR), #9, #13, #15, #18, #23, #25, #33, #59, #76; spike 0002
  (X3, X4, X11, X15; use cases 6, 8, 9), spike 0006, spike 0007 and its "Addendum for ADR-0010"
  (`docs/spikes/0007-phase-1a-type-shapes.md`); amends ADR-0003 and ADR-0004

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- Design 8.2 "Write syntax: a single `.set`" has one write verb. A new root can only be written
  through the bulk path `insert_all` (COPY, outside the pipeline, Phase 2 #33; spike 0002 X3), a
  root cannot be deleted (X4), a non-owned row can be inserted two ways (X3), a child written two
  ways (X11), and a relation operation nested in a child update has no rule (X15). The Phase 1a
  exit (9.6) needs use cases 6 (delete a root), 8 (a new root with owned children) and 9 (owned
  children of a loaded root).
- #57 and #60 recommended the shape, spike 0007 checked it under pyright and mypy (holds with an
  invariant `RelOp`, `insert` taking `AddOp` only, and `RelOp` not an `Op`), and the maintainer
  decided the points below. Spike 0007 left R6, R7, R10-R14, R17 and R18 to runtime or seal rules.
- ADR-0003 calls creation and modification different operations; the same argument makes
  inserting and deleting operations of their own, not `.set` arguments.
- Facts checked for this ADR (spike 0007's addendum; scripts and rerun commands are there):
  - **Types** (pyright 1.1.414, mypy 2.4.1, strict; reproduced by type-reviewer): A1, a child
    update narrowed to `Op[E]` rejects a grandchild operation and keeps every spike 0007 line; A2,
    `type Write[O] = Op[O] | RelOp[O]` widens no receiver, and without an annotation mypy types a
    mixed list `list[object]` (pyright the union); A3, a `Part` base for owned children makes
    R10-R12 type errors in both.
  - **PostgreSQL 18.6, psycopg 3.3.9** (pg-researcher, fast profile, every interleaving pinned and
    repeated):
    - **P1.** One statement `WITH c AS (DELETE FROM addresses WHERE user_id = ANY($1)) DELETE FROM
      users WHERE id = ANY($1)` deletes a root whose own FK points at one of its owned rows
      (`users.default_address_id`), which two statements cannot do in either order (`23503`), and
      sibling owned tables with an FK between them in all 24 orders of the sub-statements. NO
      ACTION FKs are checked once, after all sub-statements (PostgreSQL docs 7.8.4 and 38.1,
      `AfterTriggerEndQuery`). RESTRICT also passes inside one statement (a PostgreSQL deviation
      documented only in `ri_triggers.c`); as separate statements it fails with `23001`.
    - **P2.** A child insert racing a delete, with the writer bumping the root's `version` as
      `Order.items.add` does: the deleter or the writer gets `40001` under SERIALIZABLE and under
      REPEATABLE READ, in every interleaving, also against a READ COMMITTED writer. `23503` came
      from a race only when the writer did not bump the root and ran REPEATABLE READ, or ran READ
      COMMITTED (code outside Platina).
    - **P3.** `23503` is raised at the end of the statement (a deferred FK: at `COMMIT`);
      `diag.table_name` / `constraint_name` name the **referencing** table and constraint. In a
      pipeline a later psycopg call can raise an earlier statement's error; the queued `COMMIT`
      does not commit.
    - **P4.** A cascade that matches no row holds the same SIRead locks as the root DELETE alone
      (the NO ACTION check reads the child table with the same predicate), as separate statements
      or in one; without an index on the parent key both take a relation lock. Load rates could
      not separate the variants (noise; fast profile).
  - Not verified (the spike's list): the durable profile, pipelined batches under load, deferred
    constraints, a version check over several roots, partitioned tables, the async connection.
    - **P5.** `DELETE ... AND version = $2` matching no row is `DELETE 0`, not an error; with
      `COMMIT` queued the batch commits the rest. A concurrent committed UPDATE after the load
      makes the DELETE fail with `40001` first.

## Decision

### Recorded: decided by the maintainer (2026-11-26)
Sources: #57 [decision](https://github.com/devgyurak/platina/issues/57#issuecomment-7185865712) and
[predicate](https://github.com/devgyurak/platina/issues/57#issuecomment-7188647657); #60
[decision](https://github.com/devgyurak/platina/issues/60#issuecomment-7185866586) and
[`owns_many`, candidate B](https://github.com/devgyurak/platina/issues/60#issuecomment-7188647123).
1. `insert(entity, /, *children: AddOp[E]) -> Changes` inserts one new row in the commit batch;
   `insert_all` is a different operation (COPY or chunked, #33). (#60 points 1, 2)
2. Owned rows are written only through their root (`Order.items.add / update / remove`); every
   other row directly (`insert`, `row.set`, `row.delete()`); a relation that is not owned has no
   write operations. (#60 point 4)
3. `owns_many(...)` declares an owned relation; `one_to_many(..., owned=True)` goes away.
4. Candidate B: `insert(t, Transfer.legs.add(...), ...)`; `.set` is for loaded snapshots, and
   `.set` on a new entity is a runtime error.
5. `Entity.where(pred, /, *preds)` needs a predicate; an empty unpacked list is a runtime rule.
6. `order.delete() -> Changes` on a loaded root deletes it and its owned children with
   engine-issued statements (no `ON DELETE CASCADE`); non-owned rows are untouched; `.delete()` on
   a ref is `UnloadedReference`; `.delete()` and `.set` of one snapshot in one step are
   `ConflictingWrites`.
7. Owned children of an `identity`-key root are rejected in Phase 1a; a created entity never
   inserted is a `UsageError` when the step returns. (#60, "Added")
8. Events of a deleted aggregate: #23. The set-level delete: #33, which must not skip the
   aggregate rule silently.

### Proposed
1. **Ownership is one level deep**: only an `aggregate_root=True` class declares `owns_many`, and
   a class with a `parent_fk` is not an aggregate root (seal, proposal 2). So
   `OwnedRelation.update(item, *ops: Op[E])` takes column operations only (A1), and X15 and
   candidate B's cost ("a new child brings no children") stop being questions. Depth is a seal
   guarantee, not a type one.
2. **Seal checks the ownership declarations against each other** (R18), each a `SealError` naming
   both: an `owns_many` over a plain `fk`; a `parent_fk` that no `owns_many` names, that two
   `owns_many` name, or that targets another class; `owns_many` on a class without
   `aggregate_root=True`; a class with a `parent_fk` that is an aggregate root, declares
   `owns_many` or has a second `parent_fk`. A `many_to_one(via=...)` over a `parent_fk` (the child
   reading its root) is allowed. Both declarations stay: the child's constructor needs its own
   specifier (`init: Literal[False]`, #49), the root's operations need `Owned[...]` (spike 0007 S4).
   Final names: #9.
3. **A direct write of an owned child is a `UsageError` at the call**: `item.set(...)`,
   `item.delete()`, `insert(Leg(...))`, `insert_all` given an owned child (R10-R12, R14), and
   `.set` / `.delete()` on a row set of an owned child entity. The class knows from its
   `parent_fk` field, so the check needs no seal and no database; the `hint` names the root
   operation. **This bends "remove rather than detect"** for R10-R12, R14: a type-level `Part` base
   removes them (A3) but is a fourth declaration of ownership, a second way to declare an entity
   (ADR-0003) and takes `Item.where` from #59 (Alternatives).
4. **New, loaded and ref are runtime states of one type** (a constructor builds a *new* entity;
   the loader and `stub` a *loaded* one; `ref` and Finders a *ref*). Rows marked "decided" are
   the maintainer's; the others are proposed. Each fails at the call:

   | Misuse | Error |
   |---|---|
   | `.set` on a new entity (R13; decided) | `UsageError` - values go in the constructor, owned children in `insert` |
   | a new entity never inserted, on normal return of the step (R6; decided) | `UsageError` naming where it was constructed |
   | `.delete()` on a ref (decided) | `UnloadedReference` |
   | `.delete()` and `.set` (or two `.delete()`) of one snapshot in one step (decided) | `ConflictingWrites` |
   | `.delete()` on a new entity | `UsageError` - leave it out |
   | `insert(e)` of a loaded snapshot or a stub (R7) | `UsageError` - use `e.set(...)` |
   | `insert(e)`, or `add(e)` / `update(e)` / `remove(e)`, of a ref | `UnloadedReference` |
   | `add(e)` of a loaded snapshot | `UsageError` - `add` inserts (moving a child is #9's) |
   | `update(e)` / `remove(e)` of a new entity, or of a child whose parent key is not the receiving root's | `UsageError` at the `.set` |
   | one new entity inserted twice in one use case | `ConflictingWrites` |
   | reading the `identity` key of a new entity before commit | `UsageError` (as its `hash()`, ADR-0003) |

   An empty `.set()` and an `update(item)` without operations change nothing and bump no
   `version` (use case 9 can produce an empty patch).
5. **`identity`-key roots in Phase 1a: a `SealError` for an `identity`-key class that declares
   `owns_many`.** It fails at startup on every path, whatever the data, and none of the exit use
   cases needs it. The planned relaxation is a `UsageError` at `insert(t, *children)` for a new
   root only (a loaded one has its key), once a schema with `identity` roots must be modelled.
6. **Delete semantics (#57).**
   - **Owned relations are deleted whether or not they are loaded** (`src.delete()` in use case 6
     also deletes `Order.tickets`): the declaration decides the aggregate, not the load.
   - **One statement per deleted-root table**: every owned relation and the root,
     `WITH c1 AS (DELETE FROM items WHERE order_id = ANY($1)), c2 AS (DELETE FROM tickets WHERE
     order_id = ANY($1)) DELETE FROM orders WHERE id = ANY($1)`. A root's FK into its own owned
     table (`User.default_address_id`) and FKs between sibling owned tables then need no order
     and form no cycle (P1). It relies on NO ACTION FKs; the generated schema uses them, and
     `platina check` should require them on FKs into, out of and between the tables of an
     aggregate (#25); until then the Phase 1a test DDL (`tests/support`) declares them.
   - **Key only.** `expected_version` is compared at the load, as for every write; the root's
     predicate is the primary key, as the UPDATE's (10.7). A concurrent change is `40001` (P5). A
     `version` predicate would add nothing and would let the batch commit the cascade without the
     root (P5).
   - **Planner (#15).** The statement is a node of the row-level graph (8.3 ②), not a set change
     (①, which runs first). Edges: every change that removes a reference into one of the
     aggregate's tables (a DELETE of a row with an FK to it, an UPDATE that changes or clears such
     an FK) runs before it; it runs before an INSERT into an owned table, or an UPDATE of a unique
     column there, only for unique constraints that do not contain the `parent_fk` column (a row
     under another root cannot collide on those; this keeps re-pointing a row to a new child
     acyclic). Between the delete statements of two root tables in one use case,
     `AggregateDelete(X)` runs before `AggregateDelete(Y)` when a table of X has an FK into a table
     of Y (from the registry, since the rows are not loaded); aggregates that reference each other
     are merged into one statement, for P1's reason (not verified for two root tables). Operations
     on owned children of a deleted root from **earlier chain steps** are dropped, as a `.set` followed by a `.delete()` leaves a delete; within one step they are
     `ConflictingWrites` or proposal 4's `UsageError`, never dropped. A write to a row an earlier
     step deleted is a `UsageError`. `IntraUsecaseConflict` does not apply. An earlier-step
     operation that changes a child's `parent_fk` (a move, still open in #9) is not dropped but a
     `UsageError` until #9 decides moves, so a moved child is never deleted silently.
   - **Concurrency.** A concurrent `add` to the deleted root is a retried `40001` under
     SERIALIZABLE and REPEATABLE READ (P2). Writers outside Platina that skip the root's `version`
     or run READ COMMITTED can turn the race into `23503`.
   - **`Changes` and tests** record "every owned child of this root", per relation, not rows.
     `r.removed(src)` is true, and so is `r.removed(item)` for a loaded child of `src`; unloaded
     children are not listed.
   - The cascade is issued also when no child exists: it adds no predicate lock (P4). Schema
     tooling should index every `parent_fk` column, which both the cascade and the FK check scan
     (#25).
7. **`23503` and `23001` are `ForeignKeyViolation(DatabaseError)`**, typed by the driver like
   `UniqueViolation`, not retried. It is now common: non-owned rows carry hand-passed keys, and a
   delete leaves non-owned referrers to the use case (an `Allocation` of a deleted item). Not a
   `UsageError`, because it depends on rows the use case did not read. The engine attributes it by
   statement position, not by the psycopg call that raised it (P3; ADR-0008 decides the commit
   outcome the same way). The diagnostics name the referencing table and constraint (P3): the
   error names the referencing entity and field where the constraint name follows #25's naming
   rule, otherwise the table; a deferred FK fails at `COMMIT`, where the error can still name the
   entity and field but not the operation. Recorded in
   design 10.12, proposed to #18.
8. **`Write[O] = Op[O] | RelOp[O]`**, a public alias for what `.set` takes. A list that collects
   both kinds must be annotated - under mypy an unannotated one is `list[object]` and `.set(*ops)`
   fails (A2) - and `list[Write[Order]]` is the short form (use cases 2, 6, 9). It widens no
   receiver (A2). A name, not a second way to write; the name is open.

### The Phase 1a exit use cases
Spike 0007's `uc06_order_merge.py`, `uc08_transfer_b.py` and `uc09_profile_edit.py` are written in
this syntax (with `Write` in place of the union); design 4.4 shows the transfer and the merge's
delete. Use case 6 deletes `src`'s items without loading their allocations: if one exists, the
commit fails with `ForeignKeyViolation` naming `Allocation.item_id`, and the use case must load and
delete or re-point the allocations first, which the planner orders before the delete statement.
The Phase 1a integration test of use case 6 should cover both, and a delete of a `User` with a
default address (P1).

## Consequences
- Every kind of row has one way to be written: `.set` (and owned relations through it) for a
  loaded row, `insert` for a new one, `.delete()` for a loaded one. 8.2 "Write syntax" changes
  from "a single `.set`" to three verbs; "one way" holds per operation.
- Adding an owned relation to a root changes what every existing `.delete()` of it deletes,
  without touching those use cases. Plugins that rewrite the ChangeSet (10.10: soft delete, audit)
  see one delete statement per root table, not the child rows.
- Runtime rules stand where types cannot reach (proposals 3, 4); each fails at its line in every
  test that runs the path.
- Deep aggregates (`Order -> Shipment -> ShipmentLine`) own the grandchild from the root (its
  `parent_fk` to the order, a plain `fk` to the shipment) or split the aggregate. Allowing nesting
  later relaxes a seal error, which is backward compatible.
- `RowSet[E]` (spike 0007 S2) is "the rows of E that match", invariant, not a `Changes`, with
  `.set(*ops: Op[E])` and `.delete()`; both are Phase 2 (#33). Whether it is a load is #59's.
- `insert` solves `E` from the entity and the children; invariance keeps it checked (spike 0007
  F11), except under mypy through a declared type on a relation's class access (ADR-0004).
- Build issues: #9 (proposals 1, 2, 5; `owns_many`, no `owned=`), #13 (`insert`, `.delete()`,
  proposals 3, 4, 8), #15 (proposal 6's statement, edges and drops), #18 (proposal 7), #25 (NO
  ACTION and `parent_fk` indexes), #33 (set-level writes of owned children and of roots).

## Alternatives considered
- **Nested ownership**: needs a rule for operations on grandchildren (do they bump the root?),
  nested cascades, and the children of a new child under candidate B; nothing in spike 0002 needs
  it.
- **A `Part` base for owned children** (A3; for proposal 3): both checkers reject `line.set`,
  `line.delete()`, `MLine.where`, `insert(MLine(...))` and `insert_all([MLine(...)])`. Costs: a
  fourth declaration of ownership that seal must compare too, a second way to declare an entity
  next to ADR-0003's single base, no `Item.where` for #59, and `RowSet[MLine]` still nameable
  unless `RowSet` is bounded by `Entity`. It is the "remove" option; the maintainer may prefer it.
- **A `UsageError` at `insert(t, *children)` for `identity` roots now** (proposal 5's relaxation):
  precise, but it fails only when the children list is non-empty, which depends on the data.
- **Requiring owned relations to be loaded before `.delete()`**: the tests could list the deleted
  children, but a delete would read every child, and adding an owned relation would break existing
  deletes at run time (use case bodies are opaque to seal).
- **Separate statements per owned relation** (this ADR's first draft): cannot delete a root that
  references its own owned row, and needs an order between sibling owned tables (P1).
- **`ON DELETE CASCADE` in the schema**: invisible to `Changes`, tests and events, and dependent on
  who owns the schema (#57).
- **No alias for `list[Op[O] | RelOp[O]]`**: possible; three of ten spike use cases spell it.

## Open for the maintainer
1. Ownership depth: one level (proposed) or nested.
2. Direct writes of an owned child: a runtime `UsageError` (proposed) or the `Part` base (A3).
3. `identity`-key roots in Phase 1a: a `SealError` (proposed) or a `UsageError` at
   `insert(t, *children)`.
4. Unloaded owned relations: deleted without loading (proposed) or loading required.
5. `Write[O]`: adopt, its name (`Write`, `SetArg`, `RowWrite`), or no alias.
6. `ForeignKeyViolation` for `23503` and `23001`: the name, and a `DatabaseError` (proposed).

## History
- 2026-11-26 - created (Proposed) from spike 0007 and the maintainer's decisions on #57 and #60.
- 2026-11-26 - after the architect review (round 1): one delete statement per root table (P1),
  narrower unique edges, drops only across chain steps, a foreign-child `UsageError`, the
  concurrency claim corrected with the root's `version` bump (P2), `identity` roots back to a
  seal error, empty writes as no-ops, PostgreSQL scripts kept in the repository.
- 2026-11-26 - after the architect review, round 2: ordering between the delete statements of two
  root tables, no silent drop of a child move, wording.
