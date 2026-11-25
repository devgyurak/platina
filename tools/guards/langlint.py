"""Language guard: English is the source language; selected docs carry `-XX` translations.

Policy (see .agents/rules/language-and-i18n.md):
* Python comments and docstrings are English. String literals may hold any language (test data).
* Every other text file is English, except translation files.
* Data files under ``tests/`` (anything but ``.py``) may hold any language: fixtures.
* A translation lives next to its source as ``<stem>-<LANG><suffix>`` (``README-KO.md``) and
  starts with ``<!-- i18n: source=<repo path> source-sha256=<12 hex> translation-sha256=<12 hex> -->``.
  The first hash pins the English revision it was translated from; the second pins the
  translation's own body, so drift is detectable in both directions.
* Checking an English source also checks its existing translations, so editing only the source
  is reported at once (edit hook, pre-commit), not only by a full scan.
* docs/i18n.toml lists which sources require which translations.

Codes
    L101  non-English comment / docstring in Python
    L102  non-English text in an English-only file
    L201  malformed translation (bad header, unknown language, missing source)
    L202  stale translation (source changed since the recorded hash)
    L203  required translation missing (full scans only)
    L204  translation edited since it was stamped (meaning changed: carry it into the English
          source, then re-stamp; wording only: re-stamp)
"""

from __future__ import annotations

import ast
import hashlib
import io
import re
import tokenize
import tomllib
from pathlib import PurePosixPath

from tools.guards.core import ROOT, Violation, parse

CONFIG_PATH = "docs/i18n.toml"
# Scripts that signal untranslated prose. Extend when another source language shows up.
_FOREIGN = re.compile(r"[ᄀ-ᇿ぀-ヿ㄰-㆏㐀-䶿一-鿿가-힣]")
_HEADER = re.compile(
    r"^<!-- i18n: source=(?P<source>\S+) source-sha256=(?P<sha>[0-9a-f]{12})"
    r" translation-sha256=(?P<own>[0-9a-f]{12}) -->$"
)
_TEXT_SUFFIXES = {
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".sh",
    ".sql",
    ".ts",
    ".js",
    ".cfg",
    ".ini",
    ".txt",
}
_TEXT_NAMES = {"Makefile", "Dockerfile", ".gitignore", ".python-version"}


def config() -> tuple[set[str], dict[str, list[str]]]:
    data = tomllib.loads((ROOT / CONFIG_PATH).read_text())
    return set(data["languages"]), {k: list(v) for k, v in data["required"].items()}


def translation_of(path: str, languages: set[str]) -> tuple[str, str] | None:
    """Return (language, expected source path) when ``path`` is named like a translation."""
    p = PurePosixPath(path)
    m = re.fullmatch(r"(?P<stem>.+)-(?P<lang>[A-Z]{2})", p.stem)
    if not m or m.group("lang") not in languages:
        return None
    return m.group("lang"), str(p.with_name(m.group("stem") + p.suffix))


def source_hash(source_path: str) -> str:
    return hashlib.sha256((ROOT / source_path).read_bytes()).hexdigest()[:12]


def applies_to(path: str) -> bool:
    p = PurePosixPath(path)
    return p.suffix == ".py" or p.suffix in _TEXT_SUFFIXES or p.name in _TEXT_NAMES


def body_hash(text: str) -> str:
    """Hash of a translation without its header line."""
    body = text.split("\n", 1)[1] if text.startswith("<!-- i18n:") else text
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def translations_of(source_path: str, languages: set[str]) -> list[tuple[str, str]]:
    """(translation path, language) for every translation of ``source_path`` that exists."""
    p = PurePosixPath(source_path)
    candidates = [
        (str(p.with_name(f"{p.stem}-{lang}{p.suffix}")), lang) for lang in sorted(languages)
    ]
    return [(t, lang) for t, lang in candidates if (ROOT / t).is_file()]


def check(path: str, text: str) -> list[Violation]:
    languages, _ = config()
    if translation := translation_of(path, languages):
        return _check_translation(path, text, *translation)
    if path.endswith(".py"):
        return _check_python(path, text)
    own_translations = [
        v
        for t, lang in translations_of(path, languages)
        for v in _check_translation(t, (ROOT / t).read_text(), lang, path)
    ]
    if PurePosixPath(path).parts[:1] == ("tests",):
        return own_translations
    return (
        own_translations
        + [
            Violation(
                path,
                n,
                "L102",
                "non-English text - write English, or move it into a -XX translation file",
            )
            for n, line in enumerate(text.splitlines(), 1)
            if _FOREIGN.search(line)
        ][:5]
    )


def missing_translations(existing: set[str]) -> list[Violation]:
    _, required = config()
    return [
        Violation(src, 1, "L203", f"required translation `{target}` is missing (docs/i18n.toml)")
        for src, langs in required.items()
        for lang in langs
        if (
            target := str(
                PurePosixPath(src).with_name(
                    f"{PurePosixPath(src).stem}-{lang}{PurePosixPath(src).suffix}"
                )
            )
        )
        not in existing
    ]


def stamp(translation_path: str) -> str:
    """Rewrite the header hash after the translation has been brought up to date."""
    languages, _ = config()
    found = translation_of(translation_path, languages)
    if not found:
        raise SystemExit(f"{translation_path} is not named like a translation (<stem>-<LANG>.md)")
    _, source = found
    file = ROOT / translation_path
    lines = file.read_text().splitlines(keepends=True)
    body = "".join(lines[1:] if lines and lines[0].startswith("<!-- i18n:") else lines)
    header = (
        f"<!-- i18n: source={source} source-sha256={source_hash(source)}"
        f" translation-sha256={body_hash(body)} -->\n"
    )
    file.write_text(header + body)
    return header.strip()


def _check_translation(path: str, text: str, lang: str, source: str) -> list[Violation]:
    if not (ROOT / source).is_file():
        return [Violation(path, 1, "L201", f"translation has no English source `{source}`")]
    first = text.splitlines()[0] if text else ""
    m = _HEADER.match(first)
    if not m or m.group("source") != source:
        return [
            Violation(
                path, 1, "L201",
                f"first line must be `<!-- i18n: source={source} source-sha256=<hash> "
                "translation-sha256=<hash> -->` "
                f"(run: uv run python -m tools.guards i18n-stamp {path})",
            )
        ]  # fmt: skip
    if m.group("sha") != source_hash(source):
        return [
            Violation(
                path, 1, "L202",
                f"stale {lang} translation: `{source}` changed. Update the translation, then run "
                f"`uv run python -m tools.guards i18n-stamp {path}`",
            )
        ]  # fmt: skip
    if m.group("own") != body_hash(text):
        return [
            Violation(
                path, 1, "L204",
                f"{lang} translation edited since it was stamped. If the meaning changed, carry "
                f"it into `{source}` first; if only the wording changed, just re-stamp: "
                f"`uv run python -m tools.guards i18n-stamp {path}`",
            )
        ]  # fmt: skip
    return []


def _check_python(path: str, source: str) -> list[Violation]:
    out = [
        Violation(path, tok.start[0], "L101", "comments must be English")
        for tok in _tokens(source)
        if tok.type == tokenize.COMMENT and _FOREIGN.search(tok.string)
    ]
    tree = parse(source, path)
    if isinstance(tree, Violation):
        return [*out, tree]
    nodes = [
        tree,
        *(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        ),
    ]
    out += [
        Violation(path, getattr(node, "lineno", 1), "L101", "docstrings must be English")
        for node in nodes
        if (doc := ast.get_docstring(node, clean=False)) and _FOREIGN.search(doc)
    ]
    return out


def _tokens(source: str) -> list[tokenize.TokenInfo]:
    try:
        return list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError, SyntaxError:
        return []
