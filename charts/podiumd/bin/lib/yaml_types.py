"""Types for parsed YAML, and the checked conversion from yaml.safe_load's
untyped result to them. YAML reads in lib go through parse_yaml_mapping/
load_yaml_mapping (or a schema loader built on them, such as
lib.chart.chart_yaml), so the Any that yaml.safe_load returns stays in
this module."""

import datetime

from collections.abc import Mapping
from pathlib import Path
from typing import TypeGuard

import yaml

# What yaml.safe_load produces. An unquoted timestamp becomes a
# datetime.date (or datetime.datetime, a subclass). Mapping keys can be
# non-str in YAML (1:, on:); the checks below reject those, so every
# mapping here has str keys.
YamlScalar = str | int | float | bool | datetime.date | None
YamlValue = YamlScalar | list["YamlValue"] | dict[str, "YamlValue"]
YamlMapping = dict[str, YamlValue]


class YamlShapeError(ValueError):
    """Parsed YAML does not have the shape its reader expects."""

    def __init__(self, source: str, problem: str):
        super().__init__(f"{source}: {problem}")


def yaml_path(where: str, key: str) -> str:
    """The dotted path of `key` below `where` ("" = top level)."""
    return f"{where}.{key}" if where else key


def _list_problem(items: list[object], where: str) -> str | None:
    return next((p for i, item in enumerate(items) if (p := yaml_problem(item, f"{where}[{i}]")) is not None), None)


def _mapping_problem(mapping: dict[object, object], where: str) -> str | None:
    for key, item in mapping.items():
        if not isinstance(key, str):
            return f"{where or '(top level)'}: key {key!r} is not a string"
        problem = yaml_problem(item, yaml_path(where, key))
        if problem is not None:
            return problem
    return None


def yaml_problem(value: object, where: str = "") -> str | None:
    """None if `value` is a YamlValue, else a description of the first
    node that is not (a non-str mapping key, or a type safe_load does not
    produce), located by its dotted path."""
    if value is None or isinstance(value, str | int | float | bool | datetime.date):
        return None
    if isinstance(value, list):
        return _list_problem(value, where)
    if isinstance(value, dict):
        return _mapping_problem(value, where)
    return f"{where or '(top level)'}: unexpected {type(value).__name__}"


def key_problem(
    mapping: Mapping[str, YamlValue], key: str, expected: type, where: str, *, required: bool
) -> str | None:
    """What is wrong with mapping[key] (missing although required, or not
    of type `expected`), or None. `where` locates `mapping` for the message."""
    if key not in mapping:
        return f"{where or '(top level)'}: missing {key!r}" if required else None
    value = mapping[key]
    if not isinstance(value, expected):
        return f"{yaml_path(where, key)}: expected {expected.__name__}, got {type(value).__name__}"
    return None


def first_problem(*problems: str | None) -> str | None:
    """The first of `problems` that is not None, or None."""
    return next((p for p in problems if p is not None), None)


def is_yaml_mapping(value: object) -> TypeGuard[YamlMapping]:
    """Whether `value` is a mapping with str keys whose values are all
    YamlValues."""
    return isinstance(value, dict) and yaml_problem(value) is None


def parse_yaml_mapping(text: str, source: str) -> YamlMapping:
    """`text` parsed as a YAML mapping; an empty document is {}. Raises
    YamlShapeError naming `source` if it is not a mapping of YamlValues."""
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not is_yaml_mapping(data):
        raise YamlShapeError(source, yaml_problem(data) or f"expected a mapping, got {type(data).__name__}")
    return data


def load_yaml_mapping(path: Path) -> YamlMapping:
    """parse_yaml_mapping of the file at `path`."""
    return parse_yaml_mapping(path.read_text(encoding="utf-8"), str(path))
