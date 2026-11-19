"""Inputs run_python_checks derives from the code and pyproject.toml."""

import ast
import tomllib

from collections.abc import Sequence
from pathlib import Path

from lib.chart.paths import files_under


def typeddict_field_names(paths: Sequence[Path]) -> list[str]:
    """The field names of every TypedDict, also one subclassing another, in `paths` (files or directories).

    vulture doesn't link a field to its string-key reads (row["app"]), so
    run_python_checks passes these to it as a whitelist.
    """
    classes: list[ast.ClassDef] = []
    for path in paths:
        for file in [path] if path.is_file() else files_under(path, "*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            classes += [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    typeddicts = {"TypedDict"}
    while True:
        found = {class_def.name for class_def in classes if _is_subclass_of_any(class_def, typeddicts)}
        if found <= typeddicts:
            break
        typeddicts |= found
    return [
        statement.target.id
        for class_def in classes
        if class_def.name in typeddicts
        for statement in class_def.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    ]


def _is_subclass_of_any(class_def: ast.ClassDef, base_names: set[str]) -> bool:
    return any(isinstance(base, ast.Name) and base.id in base_names for base in class_def.bases)


def pylint_disable_for_tests(pyproject: Path) -> str:
    """[tool.podiumd.pylint-tests] disable, comma-joined for pylint --disable."""
    with pyproject.open("rb") as handle:
        config = tomllib.load(handle)
    return ",".join(config["tool"]["podiumd"]["pylint-tests"]["disable"])
