"""lib.yaml_types — yaml_problem, parse_yaml_mapping,
load_yaml_mapping, key_problem."""

import datetime

import pytest

from lib.yaml_types import YamlShapeError
from lib.yaml_types import key_problem
from lib.yaml_types import load_yaml_mapping
from lib.yaml_types import parse_yaml_mapping
from lib.yaml_types import yaml_problem


def test_parse_yaml_mapping_keeps_nested_values():
    parsed = parse_yaml_mapping("a:\n  b: [1, x, true, null]\n  when: 2026-09-24\n", "t.yaml")
    assert parsed == {"a": {"b": [1, "x", True, None], "when": datetime.date(2026, 9, 24)}}


def test_parse_yaml_mapping_empty_document_is_empty_mapping():
    assert parse_yaml_mapping("", "t.yaml") == {}
    assert parse_yaml_mapping("# only a comment\n", "t.yaml") == {}


def test_parse_yaml_mapping_rejects_a_list_naming_the_source():
    with pytest.raises(YamlShapeError, match=r"^t\.yaml: expected a mapping, got list$"):
        parse_yaml_mapping("- a\n", "t.yaml")


def test_parse_yaml_mapping_rejects_non_str_key_with_its_path():
    with pytest.raises(YamlShapeError, match=r"^t\.yaml: a\.b: key 1 is not a string$"):
        parse_yaml_mapping("a:\n  b:\n    1: x\n", "t.yaml")


def test_parse_yaml_mapping_rejects_yaml_boolean_key():
    # YAML 1.1 reads a bare `on:` key as True, which is never what a
    # values.yaml author meant.
    with pytest.raises(YamlShapeError, match="key True is not a string"):
        parse_yaml_mapping("on: push\n", "t.yaml")


def test_load_yaml_mapping_names_the_file(tmp_path):
    path = tmp_path / "values.yaml"
    path.write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(YamlShapeError, match=str(path)):
        load_yaml_mapping(path)


def test_yaml_problem_locates_list_items():
    assert yaml_problem({"a": [1, {2: "x"}]}) == "a[1]: key 2 is not a string"
    assert yaml_problem({"a": {1, 2}}) == "a: unexpected set"
    assert yaml_problem({"a": [1, "x"]}) is None


def test_key_problem():
    mapping = {"name": "x", "version": 1}
    assert key_problem(mapping, "name", str, "dep", required=True) is None
    assert key_problem(mapping, "version", str, "dep", required=True) == "dep.version: expected str, got int"
    assert key_problem(mapping, "alias", str, "dep", required=True) == "dep: missing 'alias'"
    assert key_problem(mapping, "alias", str, "dep", required=False) is None
