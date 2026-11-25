import pytest

from tests.support.guards import hook_paths
from tools.hooks.agent_hook import extract_paths, pre

CODEX_PATCH = """*** Begin Patch
*** Update File: src/platina/core/engine/__init__.py
@@
-a
+b
*** Add File: tests/unit/test_new.py
+x
*** End Patch"""


@pytest.mark.parametrize(
    ("tool_input", "expected"),
    [
        ({"file_path": "/repo/a.py", "content": "x"}, ["/repo/a.py"]),
        ({"path": "b.py"}, ["b.py"]),
        (
            {"command": CODEX_PATCH},
            ["src/platina/core/engine/__init__.py", "tests/unit/test_new.py"],
        ),
        ({"command": "ls -la"}, []),
    ],
    ids=["claude-edit", "pi-write", "codex-apply-patch", "shell"],
)
def test_paths_are_extracted_from_every_agent_payload(tool_input, expected):
    # when
    paths = extract_paths(tool_input)
    # then
    assert paths == expected


@pytest.mark.parametrize(
    ("path", "expected_exit"),
    [
        (".claude/agents/architect.md", 2),
        (".codex/agents/x.toml", 2),
        (".agents/agents/architect.md", 0),
    ],
)
def test_pre_hook_blocks_only_generated_agent_files(path, expected_exit):
    # when
    exit_code = pre([path])
    # then
    assert exit_code == expected_exit


def test_patch_text_inside_file_content_is_not_read_as_a_patch():
    # given
    tool_input = {
        "file_path": "tests/unit/tools/test_x.py",
        "content": "PATCH = '*** Update File: .claude/agents/architect.md'\n",
    }
    # when
    paths = hook_paths(tool_input)
    # then
    assert paths == ["tests/unit/tools/test_x.py"]


PATCH = "*** Begin Patch\n*** Update File: .claude/agents/architect.md\n@@\n-a\n+b\n*** End Patch"


@pytest.mark.parametrize(
    "tool_input",
    [
        {"command": ["apply_patch", PATCH]},
        {"command": ["bash", "-lc", f"apply_patch <<'EOF'\n{PATCH}\nEOF"]},
        {"input": PATCH},
    ],
    ids=["argv-list", "shell-heredoc", "input-key"],
)
def test_patches_in_any_payload_shape_are_found(tool_input):
    # when
    paths = hook_paths(tool_input)
    # then
    assert paths == [".claude/agents/architect.md"]


@pytest.mark.parametrize("key", ["content", "new_string", "old_string", "new_source"])
def test_patch_text_in_content_keys_is_ignored(key):
    # given
    tool_input = {"file_path": "docs/notes.md", key: PATCH}
    # when
    paths = hook_paths(tool_input)
    # then
    assert paths == ["docs/notes.md"]
