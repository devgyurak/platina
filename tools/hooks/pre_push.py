"""Git pre-push hook: refuse pushes to ``main`` and ``develop``.

The GitHub rulesets described in docs/workflow.md are the real protection. Until they exist (and
as a second line afterwards) this hook stops a push to a protected branch from any agent or
person whose clone has the hooks installed (``make hooks-install``). The maintainer can bypass it
deliberately with ``git push --no-verify``.

Run by pre-commit at the ``pre-push`` stage, which exports ``PRE_COMMIT_REMOTE_BRANCH``. Without
pre-commit, git passes ``<local ref> <local sha> <remote ref> <remote sha>`` lines on stdin.
"""

from __future__ import annotations

import os
import sys

PROTECTED = frozenset({"refs/heads/main", "refs/heads/develop"})


def protected_targets(remote_branch: str | None, stdin_lines: list[str]) -> list[str]:
    refs = (
        [remote_branch]
        if remote_branch
        else [line.split()[2] for line in stdin_lines if line.strip()]
    )
    return sorted(ref for ref in refs if ref in PROTECTED)


def main() -> int:
    stdin = [] if sys.stdin.isatty() else sys.stdin.read().splitlines()
    blocked = protected_targets(os.environ.get("PRE_COMMIT_REMOTE_BRANCH"), stdin)
    if not blocked:
        return 0
    print(
        f"Refusing to push to {', '.join(blocked)}: work goes through a PR from a "
        "`<prefix>/<kebab-summary>` branch (see the `commit` skill).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
