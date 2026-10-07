"""Inputs run_python_checks derives from the code and pyproject.toml."""

import ast
import tomllib

from collections.abc import Sequence
from pathlib import Path


def typeddict_field_names(paths: Sequence[Path]) -> list[str]:
    """The field names of every TypedDict, also one subclassing another, in `paths` (files or directories).

    vulture doesn't link a field to its string-key reads (row["app"]), so
    run_python_checks passes these to it as a whitelist.
    """
    classes: list[ast.ClassDef] = []
    for path in paths:
        for file in [path] if path.is_file() else sorted(path.rglob("*.py")):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            classes += [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    typeddicts = {"TypedDict"}
    while True:
        found = {c.name for c in classes if any(isinstance(b, ast.Name) and b.id in typeddicts for b in c.bases)}
        if found <= typeddicts:
            break
        typeddicts |= found
    return [
        statement.target.id
        for c in classes
        if c.name in typeddicts
        for statement in c.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    ]


def pylint_disable_for_tests(pyproject: Path) -> str:
    """[tool.podiumd.pylint-tests] disable, comma-joined for pylint --disable."""
    with pyproject.open("rb") as f:
        config = tomllib.load(f)
    return ",".join(config["tool"]["podiumd"]["pylint-tests"]["disable"])
