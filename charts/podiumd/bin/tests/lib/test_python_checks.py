"""lib.python_checks: the inputs run_python_checks derives from the code and pyproject.toml."""

from pathlib import Path

from lib.python_checks import pylint_disable_for_tests
from lib.python_checks import typeddict_field_names


def test_typeddict_field_names_follows_subclasses_and_skips_other_classes(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "rows.py").write_text(
        "class Row(TypedDict):\n    name: str\n\n"
        "class TableRow(Row):\n    line_index: int\n\n"
        "class Plain:\n    other: int\n",
        encoding="utf-8",
    )
    (tmp_path / "script").write_text("class Item(TypedDict):\n    app: str\n", encoding="utf-8")

    assert sorted(typeddict_field_names([tmp_path / "pkg", tmp_path / "script"])) == ["app", "line_index", "name"]


def test_pylint_disable_for_tests_joins_the_pyproject_list(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.podiumd.pylint-tests]\ndisable = [\n    # why\n    "a-rule",\n    "b-rule",\n]\n', encoding="utf-8"
    )

    assert pylint_disable_for_tests(pyproject) == "a-rule,b-rule"
