---
description: Experiments that answer the design's open questions - throwaway code, durable write-ups
paths:
  - "spikes/**"
  - "docs/spikes/**"
---
# Spike rules

Design section 9 says the open questions are answered by experiment, not argument. A spike is how.

- **Code is throwaway, the write-up is not.** Spike code lives in `spikes/NNNN-slug/`, is never
  imported by `src/` or `tests/`, and is exempt from the test-style guard (it is not under
  `tests/`). Raw output goes to `spikes/NNNN-slug/results/` (git-ignored).
- **The write-up** `docs/spikes/NNNN-slug.md` (template `docs/spikes/0000-template.md`) states the
  question, the setup (versions of Python, PostgreSQL, pyright, mypy, psycopg), what was run (exact
  commands), the observations, and the **verdict** against the design's assumption: holds / does
  not hold / partly, with the consequence for the design.
- **Dependencies** come from the `spike` group (`uv sync --group spike`: psycopg, SQLAlchemy,
  Alembic). A spike that needs anything else stops and asks the maintainer; it never adds a
  dependency on its own.
- **The right database.** `make db-up` (tmpfs, fsync off) answers "does X happen at all".
  Anything that reports a rate, a throughput or a latency (design sections 9.2 last item, 9.5)
  runs on `make db-up-durable`: fast commits shorten the overlap between transactions and would
  understate conflict rates. The write-up names the profile.
- **Reproducible.** Anyone can rerun it from the write-up alone. Concurrency spikes pin
  interleavings (barriers) or run enough iterations to report a rate with its spread.
- **Independently reproduced before the checkbox is ticked.** The dangerous error is a false
  "the assumption holds". Before ticking, a second agent that did not run the spike -
  **pg-researcher** for database spikes, **type-reviewer** for typing spikes - reruns it from the
  write-up only and records its result in the write-up's `Reproduction` section. A disagreement
  goes to the maintainer.
- **Close the loop in the same change:** after the reproduction, tick the design section 9
  checkbox (and the KO translation), and if the verdict changes a decision, write an ADR or edit
  the design document.
- Spike code that proves worth keeping is promoted by rewriting it under `src/` or `tests/`
  through the normal feature loop, never by moving the spike file.
