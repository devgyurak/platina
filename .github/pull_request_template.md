<!-- Title: `<PREFIX>: <summary>` with one of ADD / FIX / REF / DEL / DOCS / UPT (see the `commit` skill).
     Work PRs target `develop`; only release PRs target `main`. -->

## What

Closes #

<!-- Roadmap item (docs/design/design.md section) or bug. -->

## How

<!-- Packages/zones touched, design sections and ADRs relied on, spikes that back it. -->

## Verification

- [ ] `make check` green (lint, pyright + mypy, guards, unit + type tests)
- [ ] `make test-int` (when PostgreSQL is involved)
- [ ] public typing changed? `make test-types` covers every promised misuse under pyright and mypy
- [ ] `review-change`: no open BLOCKER/MAJOR (paste the consolidated table)
- [ ] docs updated per the `docs-sync` rule (design + KO, architecture, CHANGELOG, skills, translations)
- [ ] ADR needed? Accepted by the maintainer before merge
