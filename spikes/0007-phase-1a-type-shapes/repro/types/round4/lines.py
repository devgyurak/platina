"""Error lines per checker for a directory (round-2 reproduction glue): lines.py DIR FILE..."""

import json
import re
import subprocess
import sys
from pathlib import Path

d = Path(sys.argv[1])
files = sys.argv[2:]
out: set[str] = set()
pr = subprocess.run(
    ["uv", "run", "pyright", "--outputjson", *files], cwd=d, capture_output=True, text=True
)
if pr.returncode not in (0, 1):
    raise SystemExit(f"pyright exit {pr.returncode}: {pr.stdout[:300]}{pr.stderr[:300]}")
for g in json.loads(pr.stdout)["generalDiagnostics"]:
    if g["severity"] == "error":
        out.add(f"pyright {Path(g['file']).name} {g['range']['start']['line'] + 1}")
my = subprocess.run(
    ["uv", "run", "mypy", "--strict", "--show-error-codes", "--no-incremental", *files],
    cwd=d,
    capture_output=True,
    text=True,
)
if my.returncode not in (0, 1):
    raise SystemExit(f"mypy exit {my.returncode}: {my.stdout[:300]}{my.stderr[:300]}")
for line in my.stdout.splitlines():
    if m := re.match(r"^([^:]+):(\d+): error:", line):
        out.add(f"mypy {Path(m.group(1)).name} {m.group(2)}")
print("\n".join(sorted(out)))
