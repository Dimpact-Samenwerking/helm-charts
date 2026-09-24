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


def parse_yaml(text: str, source: str) -> YamlValue:
    """`text` parsed as YAML of any shape (an empty document is None).
    Raises YamlShapeError naming `source` if it holds something that is
    not a YamlValue; yaml.YAMLError passes through."""
    data = yaml.safe_load(text)
    if not is_yaml_value(data):
        raise YamlShapeError(source, yaml_problem(data) or "not YAML data")
    return data


def is_yaml_value(value: object) -> TypeGuard[YamlValue]:
    """Whether `value` is a YamlValue."""
    return yaml_problem(value) is None


def load_yaml_mapping(path: Path) -> YamlMapping:
    """parse_yaml_mapping of the file at `path`."""
    return parse_yaml_mapping(path.read_text(encoding="utf-8"), str(path))


def scalar_text(value: YamlValue) -> str | None:
    """`value` as the text Helm renders for a scalar: a string as it is, a
    number through str() (an unquoted `tag: 1.5`); None for null, a
    boolean, a date, a list or a mapping."""
    if isinstance(value, str):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return None


def _alternatives_problem(value: object, shape: tuple[object, ...], where: str) -> str | None:
    problems = [shape_problem(value, alternative, where) for alternative in shape]
    return None if None in problems else next(p for p in problems if p is not None)


def _list_problem_of(value: object, item_shape: object, where: str) -> str | None:
    if not isinstance(value, list):
        return f"{where or '(top level)'}: expected a list, got {type(value).__name__}"
    items: list[object] = value
    return first_problem(*(shape_problem(item, item_shape, f"{where}[{i}]") for i, item in enumerate(items)))


def _mapping_problem_of(value: object, shape: dict[str, object], where: str) -> str | None:
    if not isinstance(value, dict):
        return f"{where or '(top level)'}: expected a mapping, got {type(value).__name__}"
    mapping: dict[object, object] = value
    for spec, key_shape in shape.items():
        key = spec.removesuffix("?")
        if key not in mapping:
            if spec.endswith("?"):
                continue
            return f"{where or '(top level)'}: missing {key!r}"
        problem = shape_problem(mapping[key], key_shape, yaml_path(where, key))
        if problem is not None:
            return problem
    return None


def shape_problem(value: object, shape: object, where: str = "") -> str | None:
    """None if parsed JSON/YAML `value` has `shape`, else what is wrong
    with it. `shape` is a type (checked with isinstance; a bool never
    counts as an int), a tuple of alternative shapes, a one-item list
    [item_shape] for a list of those, or a dict {key: shape} for a mapping
    that has (at least) those keys, where a key written "key?" may be
    missing. Used by the TypeGuard of a TypedDict whose fields the shape
    spells out."""
    if isinstance(shape, tuple):
        return _alternatives_problem(value, shape, where)
    if isinstance(shape, list):
        return _list_problem_of(value, shape[0], where)
    if isinstance(shape, dict):
        return _mapping_problem_of(value, shape, where)
    if not isinstance(shape, type):
        msg = f"not a shape: {shape!r}"
        raise TypeError(msg)
    if isinstance(value, shape) and not (isinstance(value, bool) and shape is int):
        return None
    return f"{where or '(top level)'}: expected {shape.__name__}, got {type(value).__name__}"
