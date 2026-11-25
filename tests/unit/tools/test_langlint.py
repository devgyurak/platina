import pytest

from tests.support.guards import lint_language, stamped_translation
from tools.guards.langlint import body_hash, source_hash, translation_of, translations_of


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = 1  # an English comment\n", []),
        ("x = 1  # 한국어 주석\n", ["L101"]),
        ('"""모듈 설명."""\n', ["L101"]),
        ('def f():\n    """함수 설명."""\n', ["L101"]),
        ('label = "음수 ✓"\n', []),
    ],
    ids=[
        "english-comment",
        "korean-comment",
        "korean-module-docstring",
        "korean-function-docstring",
        "korean-string-literal-is-data",
    ],
)
def test_python_comments_and_docstrings_must_be_english(source, expected):
    # when
    codes = lint_language(source)
    # then
    assert codes == expected


def test_non_english_markdown_outside_translations_is_reported():
    # given
    text = "# Title\n\n설명\n"
    # when
    codes = lint_language(text, path="docs/notes.md")
    # then
    assert codes == ["L102"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("README-KO.md", ("KO", "README.md")),
        ("docs/design/design-KO.md", ("KO", "docs/design/design.md")),
        ("docs/plan-V2.md", None),
        ("docs/adr/0001-run-id-claim.md", None),
    ],
)
def test_translation_files_are_recognised_by_suffix(path, expected):
    # when
    result = translation_of(path, {"KO"})
    # then
    assert result == expected


@pytest.mark.parametrize(
    "path",
    ["tests/integration/fixtures/rows.sql", "tests/unit/data/names.json"],
    ids=["sql", "json"],
)
def test_non_english_test_data_files_are_allowed(path):
    # given
    text = '{"name": "가나다"}\n'
    # when
    codes = lint_language(text, path=path)
    # then
    assert codes == []


def test_translation_edited_after_stamping_is_reported():
    # given
    text = stamped_translation(
        "README.md", "# Platina\n", source_sha=source_hash("README.md"), own_sha="000000000000"
    )
    # when
    codes = lint_language(text, path="README-KO.md")
    # then
    assert codes == ["L204"]


def test_translation_stamped_with_both_hashes_is_clean():
    # given
    text = stamped_translation(
        "README.md",
        "# Platina\n",
        source_sha=source_hash("README.md"),
        own_sha=body_hash("# Platina\n"),
    )
    # when
    codes = lint_language(text, path="README-KO.md")
    # then
    assert codes == []


def test_existing_translations_of_a_source_are_found():
    # when
    found = translations_of("README.md", {"KO"})
    # then
    assert found == [("README-KO.md", "KO")]
