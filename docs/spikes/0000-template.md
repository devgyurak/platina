# Spike NNNN: Title

- Design section: 9.x (quote the checklist item)
- Issue: #N
- Date: YYYY-MM-DD
- Code: `spikes/NNNN-slug/` (throwaway; raw output in `results/`, git-ignored)

## Question
The design assumption being tested, quoted, and what result would confirm or refute it.
Written before running anything.

## Setup
Versions (Python, pyright, mypy, psycopg, PostgreSQL `SELECT version()`), settings, data size.

## Method
Exact commands and the shape of the experiment (interleaving steps, worker count, iterations).

## Observations
Numbers with their spread, inferred types per checker, error messages - verbatim where it matters.

Database profile: fast (`make db-up`) or durable (`make db-up-durable`, required for rates,
throughput and latency).

## Verdict
Holds / does not hold / partly. Consequence for the design: unchanged, edited (which section),
or an ADR (link).

## Reproduction
Filled in by a second agent (pg-researcher / type-reviewer) that reran the experiment from this
write-up alone: who, date, what it ran, its observations, agree / disagree. The design checkbox
is ticked only after an agreeing reproduction.
