---
name: run-spike
description: Run an experiment that answers one of the design's open questions (design section 9 - type surface, SSI false conflicts, Alembic round trip, use cases on paper, measurements) and record the verdict. Use when a design assumption needs checking before implementation, or when asked to "run the spike for 9.x".
---
# Run a spike

Rules: `.agents/rules/spikes.md`. One spike answers one question (or one checklist group of
design section 9).

1. **Number and name**: next free `NNNN` across `docs/spikes/` -> `NNNN-kebab-slug`
   (e.g. `0001-type-surface`, `0002-ssi-run-claim`).
2. **Write the question first**: copy `docs/spikes/0000-template.md` to
   `docs/spikes/NNNN-slug.md`; fill Question (quote the design assumption and its section), and
   Method *before* running anything. Decide what result would confirm or refute the assumption.
3. **Build the experiment** in `spikes/NNNN-slug/` (Python scripts, `.pyi` stubs, SQL). Keep it
   minimal; it is throwaway. Outputs go to `spikes/NNNN-slug/results/` (git-ignored).
   Dependencies: psycopg comes with the defaults (`uv sync`), `uv sync --group spike` adds
   SQLAlchemy and Alembic; if you need anything else, stop and ask the maintainer.
   - Type surface: stub-only code + pass/fail files run through `uv run python -m tools.typetests`
     (see `type-tests`); record what each checker inferred.
   - PostgreSQL: two sessions with explicit steps for interleavings (`make db-up` is fine), or N
     concurrent workers reporting a rate (serialization failures / attempts) with its spread -
     rates, throughput and latency only on `make db-up-durable`. **pg-researcher** can design or
     check the experiment.
   - Alembic round trip: a throwaway registry -> `MetaData` -> autogenerate against the test DB.
   - Use cases on paper: write the ten use cases of design section 9.4 in the proposed syntax;
     note every place the syntax could not express the intent.
4. **Record**: setup (versions: `uv run python -V`, `uv run pyright --version`,
   `uv run mypy --version`, `SELECT version()`), exact commands, observations (numbers, inferred
   types, error messages), and the **Verdict**: holds / does not hold / partly, with the
   consequence for the design.
5. **Independent reproduction**: hand the write-up (not your conclusions, not the code you ran
   in your head) to **pg-researcher** (database) or **type-reviewer** (typing) and ask it to rerun
   the experiment from the write-up alone. It fills the `Reproduction` section. If it disagrees,
   stop and bring both results to the maintainer; do not tick anything.
6. **Close the loop in the same change**: tick the section 9 checkbox in `docs/design/design.md`
   and `design-KO.md`, link the write-up next to it, and if the verdict changes a decision, edit
   the design (and write an ADR when the change is significant - `write-adr`). Ask **architect** to
   review a verdict that changes a decision.
7. Commit as `DOCS:` (the spike code ships nowhere) - see the `commit` skill.
