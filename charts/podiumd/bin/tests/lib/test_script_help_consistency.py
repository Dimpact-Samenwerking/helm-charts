"""Every script's --help: one argument or option name has one explanation in every script that takes it.

A script whose argument means something else (e.g. a narrower set of
values) must give it another name. jscpd skips these help texts, so this
test is what keeps them from drifting apart.
"""

import ast
import re

from collections import defaultdict
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parents[2]
# An entry: 4-space indent, the name, 2+ spaces, its explanation; wrapped lines are indented deeper.
ENTRY_RE = re.compile(r"^    (?P<name><[^>]+>|--?[\w-]+(?: <[^>]+>| [A-Z_]+)?)\s{2,}(?P<text>\S.*)$")
SECTIONS = ("Arguments:", "Options:")


def _python_scripts() -> list[Path]:
    return sorted(
        path
        for path in BIN_DIR.iterdir()
        if path.is_file() and path.stat().st_mode & 0o100 and path.read_text(encoding="utf-8").startswith("#!")
        if "python" in path.read_text(encoding="utf-8").splitlines()[0]
    )


def _help_entries(doc: str) -> dict[str, str]:
    """{argument or option name: explanation, wrapped lines joined} of a docstring's Arguments/Options sections."""
    entries: dict[str, str] = {}
    in_section, current = False, None
    for line in doc.splitlines():
        if re.match(r"^\S", line):
            in_section, current = line.strip() in SECTIONS, None
            continue
        match = ENTRY_RE.match(line) if in_section else None
        if match:
            current = match.group("name")
            entries[current] = match.group("text").strip()
        elif current and line.startswith("      ") and line.strip():
            entries[current] += " " + line.strip()
        else:
            current = None
    return entries


def _explanations_by_name() -> dict[str, dict[str, list[str]]]:
    """{name: {explanation: [script, ...]}} over every script's help."""
    by_name: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for script in _python_scripts():
        doc = ast.get_docstring(ast.parse(script.read_text(encoding="utf-8")), clean=False) or ""
        for name, text in _help_entries(doc).items():
            by_name[name][text].append(script.name)
    return by_name


def test_the_help_parser_finds_the_shared_arguments():
    """Guards the parser itself: a format change must not silently make the next test pass."""
    by_name = _explanations_by_name()

    assert {"<key>", "<image-basename>", "<component>", "--dry-run"} <= set(by_name)
    assert len(next(iter(by_name["--dry-run"].values()))) > 1


def test_one_argument_name_has_one_explanation_in_every_script():
    drifted = {name: dict(texts) for name, texts in _explanations_by_name().items() if len(texts) > 1}

    assert not drifted, "\n".join(
        f"{name}:\n" + "\n".join(f"  {scripts}: {text}" for text, scripts in texts.items())
        for name, texts in drifted.items()
    )
