---
name: type-tests
description: Pin the public type surface with tests/typing/pass_*.py and fail_*.py files checked by BOTH pyright and mypy (tools/typetests.py) - assert_type for inference, `# expect-error[<pyright rule>, <mypy code>]` for misuse. Use when adding or changing public syntax, descriptors, stubs, bind/chain/Finder signatures, or for the type-surface spike.
---
# Type tests (design section 11.8)

Platina's safety lives in the type checker: misuse must be a type error under **both** pyright
and mypy, because users run either. `tools/typetests.py` enforces it.

## Files
- `tests/typing/pass_<topic>.py` - must produce **no** error in either checker. Use
  `typing.assert_type(expr, T)` to pin inference (`assert_type(Order.status, Column[Order, OrderStatus])`,
  `assert_type(order.status, OrderStatus)`).
- `tests/typing/fail_<topic>.py` - every line that must be rejected ends with
  `# expect-error[<pyright rule>, <mypy code>]: <why>`, e.g.
  `pay.bind(order=oid)  # expect-error[reportArgumentType, arg-type]: UUID is not Order`.
  **Each** checker must report an error on that line, **every** error it reports there must carry
  one of the listed codes (codes starting with `report` are pyright's, the rest mypy's; list
  several when either is acceptable), and no unmarked line may have an error. A marker without a
  code for a checker is itself a failure. One misuse per line; keep the setup lines valid.
- A marker makes its line long, and `ruff format` (line length 100) would wrap the statement and
  move the marker off the line that errors. Fence the misuse block of a fail file with
  `# fmt: off` / `# fmt: on` (spike 0001, T1).
- pyright strict can attach more than one rule to a line (`reportUnknownMemberType` next to
  `reportAttributeAccessIssue` on an unknown attribute, `reportUnusedExpression` on a bare
  expression); list every code each checker reports there.
- pyright runs in strict mode on `tests/typing` and `spikes/` (`[tool.pyright] strict`), mypy
  with `--strict`, so a file gives the same verdict in both places.
- `tests/typing` is outside pyright's `include` on purpose (its fail lines must not break
  `make typecheck`) and must never be put in `exclude`: pyright skips excluded files even when
  they are passed explicitly, which would silently turn the type tests off.
- pytest does not collect these files; they are never executed.

## Run
```bash
uv run python -m tools.typetests                         # all files (also part of make check)
uv run python -m tools.typetests tests/typing/fail_bind.py
```
A failure names the checker and the codes: `expected [...], got none`, `error [...] is not the
expected [...]` (the line fails for another reason), `unexpected type error [...]`, or `the marker
names no <checker> code`. To see why, run the checker directly:
`uv run pyright tests/typing/fail_bind.py` / `uv run mypy --strict tests/typing/fail_bind.py`.

## Rules
- The codes are what make a fail line meaningful: an unrelated error (an undefined name) has a
  different code and is reported. Still read the message once when you add a line;
  `type-reviewer` checks that the code matches the reason.
- When the two checkers disagree, that is a finding, not something to paper over with
  `# type: ignore`. Prefer a construct both understand; otherwise record the gap and the chosen
  fallback in the design document (section 8.2 lists fallbacks) or an ADR.
- Every misuse listed in design section 11.8 gets a line as soon as the construct exists.

## The spike's reference surface (design section 9.1)
Spike 0001 is done (`docs/spikes/0001-type-surface.md`, ADR-0003, ADR-0004). Its stubs are the
reference for the real public surface: `spikes/0001-type-surface/round2/lib_final_declared.pyi`
(with `domain_final_declared.py` and the pinned `pass_final_declared.py` / `fail_final_declared.py`)
shows the decided shape - `Entity` base, `Order(...)`, `Column[Owner, T]` with fixed variance,
`path(Money.amount)`. Rewrite them under `src/` and `tests/typing/` through the feature loop (#9);
never move or import the spike files.
