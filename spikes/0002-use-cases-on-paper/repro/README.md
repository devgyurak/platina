# Spike 0002 - reproduction sources

The independent reproductions of spike 0002 (write-up section "Reproduction") were run by the
`type-reviewer` and `pg-researcher` sub-agents on 2026-11-25. Their sources are kept here so the
reproduction can be rerun from the repository alone; their raw output is regenerated into the
git-ignored `results/repro-types/` and `results/repro-db/`.

The files are the reproducers' code, unchanged (they were moved from `results/`; none needed a
path change). Rerunning them is a rerun, not a new independent reproduction.

**Temporary suppression headers.** The reproducers' code does not pass the project's ruff format
and lint (RUF005, UP037, SIM115, and an intentional F821 in `x1_extra.py`, which probes an
undefined name). To keep the code byte-identical, eleven files start with a two-line
`# TEMPORARY (spike 0002)` comment, a file-level `# ruff: noqa: <codes it has>` and/or
`# fmt: off`, at the maintainer's instruction; everything below the header is the reproducer's
text. Whether to keep, reformat or exclude these files is the maintainer's decision.

The two `run.sh` files are glue written when the sources were moved (not the reproducers' code).
Use them rather than retyping the commands below: they run under bash, pass `--project` to `uv`,
and must be run from the repository root, because pyright's configuration (`strict` for
`spikes/`) applies only inside the repository.

All commands run from the repository root, with `uv sync --group spike`.

## Types (`repro/types/`)

- `x1_extra.py`, `x13_reveal.py`, `x51_same_type.py`: the reproducer's own probes. They import the
  spike's `lib` and `domain` as siblings, so they run from a copy of the spike directory.
- `patches/*.patch`: the four stub variants the reproducer checked, as diffs against the spike's
  `lib.pyi` (instead of full copies):

  | Patch | Change | Question |
  |---|---|---|
  | `hash.patch` | `Column.__hash__` | X2 candidate fix |
  | `tight.patch` | `process[E, **P](*, on: type[E])` with a `Concatenate[E, ProcessContext, P]` handler | X13 item 2 |
  | `tight-ref.patch` | `Entity.ref(id: Id[Self])` | X13 item 8 |
  | `tight-after.patch` | `Load.after(...) -> LoadAfter[R]` (the function's result type carried) | X13 item 1 |

```bash
D=spikes/0002-use-cases-on-paper
R=$D/results/repro-types
F16="lib.pyi domain.py uc01_payment.py uc02_refund.py uc03_coupon_checkout.py uc04_stock_allocation.py
  uc05_seat_hold.py uc06_order_merge.py uc07_expire_orders.py uc08_transfer.py uc09_profile_edit.py
  uc10_payment_approval.py fail_findings.py probe_accepted.py probe_annotated_metadata.py
  probe_column_key.py"
MYPY="uv run mypy --strict --show-error-codes --no-incremental"

# a copy of the spike per variant, with the variant's patch applied to lib.pyi
for v in base hash tight tight-ref tight-after; do
  rm -rf "$R/$v" && mkdir -p "$R/$v"
  cp $D/lib.pyi $D/domain.py $D/uc*.py $D/fail_findings.py $D/probe_*.py "$R/$v/"
  if [ "$v" != base ]; then patch -s "$R/$v/lib.pyi" < $D/repro/types/patches/$v.patch; fi
done
cp $D/repro/types/x*.py "$R/base/"

# the 16 files under both checkers, per variant
for v in base hash tight tight-ref tight-after; do
  (cd "$R/$v" && uv run pyright $F16 > "../$v-pyright-16.txt"; $MYPY $F16 > "../$v-mypy-16.txt")
done

# the reproducer's probes
for p in x1_extra x13_reveal x51_same_type; do
  (cd "$R/base" && uv run pyright $p.py > "../$p-pyright.txt"; $MYPY $p.py > "../$p-mypy.txt")
done

# spike 0001's pinned files against this stub, without and with hash.patch
for v in regress0001 regress0001-hash; do
  rm -rf "$R/$v" && mkdir -p "$R/$v"
  cp spikes/0001-type-surface/round2/{domain,pass,fail}_final_declared.py "$R/$v/"
  cp $D/lib.pyi "$R/$v/lib_final_declared.pyi"
  if [ "$v" = regress0001-hash ]; then
    patch -s "$R/$v/lib_final_declared.pyi" < $D/repro/types/patches/hash.patch
  fi
  uv run python -m tools.typetests "$R/$v/lib_final_declared.pyi" "$R/$v/domain_final_declared.py" \
    "$R/$v/pass_final_declared.py" "$R/$v/fail_final_declared.py" > "$R/$v.txt"
done
```

The 14-file `tools.typetests` command of the write-up's Method can also be pointed at a variant
directory (`$R/<variant>/...`). The output file names of the first run (`08-...`, `09-...`,
`10-...`, `11-...`, `12-...`) were chosen by the reproducer; the commands above write
`<variant>-*.txt` instead.

## Database (`repro/db/`)

`harness.py` (sessions, observed lock waits), `script.py` (the pinned-interleaving interpreter),
`part_a.py` (X8's six rows), `part_b.py`, `part_b_three.py`, `part_b_timeout.py` (design 4.6's
statement order), `part_c.py` (use case 3's SQLSTATE), `summarize.py` (condenses part C). They
need the fast database (`make db-up`, port 26432; `PLATINA_TEST_DSN` overrides it) and create and
drop their own schema `repro0002_<pid>`.

```bash
D=spikes/0002-use-cases-on-paper
R=$D/results/repro-db
mkdir -p $R
uv run python $D/repro/db/part_a.py > $R/partA-verified.txt
uv run python $D/db_increment_conflicts.py > $R/partA-original-script.txt
uv run python $D/repro/db/part_b.py > $R/partB.txt
uv run python $D/repro/db/part_b_three.py > $R/partB-three-sessions.txt
uv run python $D/repro/db/part_b_timeout.py > $R/partB-timeout.txt
uv run python $D/repro/db/part_c.py asked > $R/partC-asked.txt
uv run python $D/repro/db/part_c.py extra > $R/partC-extra.txt
uv run python $D/repro/db/summarize.py $R/partC-asked.txt > $R/partC-asked-summary.txt
uv run python $D/repro/db/summarize.py $R/partC-extra.txt > $R/partC-extra-summary.txt
```

Each run is one pass per scenario on the fast profile: it shows whether an outcome happens, not
how often.
