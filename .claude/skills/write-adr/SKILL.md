---
name: write-adr
description: Write a lightweight Architecture Decision Record for an expensive-to-reverse decision that the design document does not already settle (public API shape, versions, dependencies, guards, a change to a section 8 decision). The bar is that the maintainer reads it and is convinced. Use when architect says an ADR is needed or a change deviates from the design.
---
# Write an ADR

The ADR's job is to let the maintainer read the decision and be convinced. No more ceremony than
that. Rules: `.agents/rules/docs-and-adr.md`.

1. Check the design document first: if section 8 already decides it, follow it - no ADR. If the
   choice is small and easily reversed, explain it in the commit body instead.
2. Next number: `ls docs/adr` -> `NNNN-kebab-title.md`, copy `docs/adr/0000-template.md`.
3. Write it short and concrete:
   - **Context**: the facts and the constraint (link design sections, spikes, issues).
   - **Decision**: what we do, in a few sentences.
   - **Consequences**: what becomes easier, what becomes harder or costs more.
   - **Alternatives considered**: one or two lines each on why not.
   Add evidence (a spike write-up, a test, a measurement) when the decision rests on a fact that
   could be wrong. A cross-layer decision is worth an **architect** review; quote its verdict if
   you asked for one.
4. Status `Proposed`. Show it to the maintainer and stop for their answer. When they accept (in
   the conversation or the PR review), set `Status: Accepted (maintainer, <date>)`. Never accept it
   yourself; if they reject it, set `Rejected` and keep the file.
5. Update `docs/design/design.md` (+ `design-KO.md`) where the decision changes or extends the
   design, link the ADR from there and from `docs/architecture.md` when it shapes the code, and
   from code that depends on it (`# See ADR-0003`).

## Change an ADR later
- Same direction, refined detail: edit in place and append a line to `## History`
  (`2026-12-01 - narrowed the retry budget to commands only`).
- Direction reversed: new ADR with `Supersedes ADR-NNNN`; set the old one to
  `Superseded by ADR-MMMM`.
English only; ADRs are not translated.
