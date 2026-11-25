---
name: translate-docs
description: Keep -XX translations (README-KO.md, docs/workflow-KO.md, docs/design/design-KO.md) in sync with their English sources and stamp the i18n header. Use when guards report L201/L202/L203 or after editing a translated English document.
---
# Translate docs

1. Find work: `uv run python -m tools.guards` -> L202 (stale) / L203 (missing) / L204
   (translation edited directly: if the meaning changed, port it to the English source first;
   if only the wording changed, just re-stamp).
2. For each: delegate to **translator**, or do it yourself:
   - diff the English source since the last translated revision (`git log -p -- <source>`);
   - mirror the change in the translation, keeping structure (headings, tables, code, links)
     identical; translate prose only;
   - `uv run python -m tools.guards i18n-stamp <translation>`;
   - `uv run python -m tools.guards <translation>` must be clean.
3. Adding a language: add the code to `languages` in `docs/i18n.toml`, list it under the
   documents in `[required]`, create the files, stamp them.
4. Adding a translated document: add it to `[required]`, create `<stem>-<LANG>.md`, stamp it.
