"""Print `checker file line code` for every error both checkers report on FILES in DIR.

Usage: python errors_r6x.py DIR FILE [...]. Runs pyright (JSON) and mypy --strict inside DIR, so
`from lib import ...` resolves to DIR's stub. Exits 2 when a checker exits other than 0 or 1.
"""

import json
import re
import subprocess
import sys

MYPY = re.compile(r"^(?P<f>[^:]+):(?P<l>\d+): error: .*?(?:\s+\[(?P<c>[a-z0-9-]+)\])?$")


def main() -> int:
    d, files = sys.argv[1], sys.argv[2:]
    p = subprocess.run(["pyright", "--outputjson", *files], cwd=d, capture_output=True, text=True)
    m = subprocess.run(
        ["mypy", "--strict", "--show-error-codes", "--no-incremental", *files],
        cwd=d,
        capture_output=True,
        text=True,
    )
    if p.returncode not in (0, 1) or m.returncode not in (0, 1):
        print(p.stderr, m.stdout, m.stderr, file=sys.stderr)
        return 2
    rows: set[str] = set()
    for x in json.loads(p.stdout)["generalDiagnostics"]:
        if x["severity"] == "error":
            name = x["file"].rsplit("/", 1)[-1]
            rows.add(f"pyright {name} {x['range']['start']['line'] + 1} {x.get('rule', '-')}")
    for line in m.stdout.splitlines():
        hit = MYPY.match(line)
        if hit:
            rows.add(f"mypy {hit['f']} {hit['l']} {hit['c'] or '-'}")
    print("\n".join(sorted(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
