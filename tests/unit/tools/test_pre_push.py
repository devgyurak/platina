import pytest

from tools.hooks.pre_push import protected_targets

SHA = "0" * 40


@pytest.mark.parametrize(
    ("remote_branch", "stdin", "expected"),
    [
        ("refs/heads/main", [], ["refs/heads/main"]),
        ("refs/heads/develop", [], ["refs/heads/develop"]),
        ("refs/heads/add/commit-planner", [], []),
        (None, [f"refs/heads/x {SHA} refs/heads/main {SHA}"], ["refs/heads/main"]),
        (None, [f"refs/heads/x {SHA} refs/heads/fix/y {SHA}", ""], []),
    ],
    ids=["main", "develop", "work-branch", "stdin-main", "stdin-work-branch"],
)
def test_only_pushes_to_main_and_develop_are_refused(remote_branch, stdin, expected):
    # when
    blocked = protected_targets(remote_branch, stdin)
    # then
    assert blocked == expected
