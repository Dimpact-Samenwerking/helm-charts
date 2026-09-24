"""Chart.yaml: its types and checked loader. Keys follow
Helm's Chart.yaml reference; keys this repo never reads are left out of
the types but kept in the loaded dict (a TypedDict allows extra keys)."""

from collections.abc import Callable
from pathlib import Path
from typing import NotRequired
from typing import TypedDict
from typing import TypeGuard

from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlShapeError
from lib.yaml_types import YamlValue
from lib.yaml_types import first_problem
from lib.yaml_types import key_problem
from lib.yaml_types import parse_yaml_mapping
from lib.yaml_types import yaml_path

# One Chart.yaml dependencies[] entry. Functional syntax because of the
# "import-values" key.
ChartDependency = TypedDict(
    "ChartDependency",
    {
        "name": str,
        "version": str,
        "repository": NotRequired[str],
        "condition": NotRequired[str],
        "alias": NotRequired[str],
        "tags": NotRequired[list[str]],
        "enabled": NotRequired[bool],
        "import-values": NotRequired[list[YamlValue]],
    },
)


class ChartYaml(TypedDict):
    """A Chart.yaml, with the keys this repo reads."""

    apiVersion: str
    name: str
    version: str
    description: NotRequired[str]
    type: NotRequired[str]
    # A string, also when a chart leaves it unquoted (see
    # normalize_app_version).
    appVersion: NotRequired[str]
    dependencies: NotRequired[list[ChartDependency]]


_DEPENDENCY_OPTIONAL_STR_KEYS = ("repository", "condition", "alias")


def normalize_int_version(mapping: YamlValue) -> None:
    """Replace an unquoted integer "version" (YAML reads `version: 26` as
    26) in `mapping` by its string, in place. Lossless, unlike a float
    ("1.10" reads as 1.1), which the checks reject instead."""
    if isinstance(mapping, dict):
        version = mapping.get("version")
        if isinstance(version, int) and not isinstance(version, bool):
            mapping["version"] = str(version)


def normalize_app_version(mapping: YamlMapping) -> None:
    """Replace an unquoted numeric "appVersion" (third-party charts often
    write `appVersion: 8.4`) by its string, in place. Helm itself does the
    same: its Chart.AppVersion is a string field, filled from YAML's
    number."""
    app_version = mapping.get("appVersion")
    if isinstance(app_version, int | float) and not isinstance(app_version, bool):
        mapping["appVersion"] = str(app_version)


def normalize_dependency_versions(deps: YamlValue) -> None:
    """normalize_int_version for every entry of a dependencies list."""
    if isinstance(deps, list):
        for dep in deps:
            normalize_int_version(dep)


def chart_dependency_problem(value: YamlValue, where: str) -> str | None:
    """None if `value` is a ChartDependency, else what is wrong with it."""
    if not isinstance(value, dict):
        return f"{where}: expected a mapping, got {type(value).__name__}"
    tags = value.get("tags")
    return first_problem(
        key_problem(value, "name", str, where, required=True),
        key_problem(value, "version", str, where, required=True),
        *(key_problem(value, key, str, where, required=False) for key in _DEPENDENCY_OPTIONAL_STR_KEYS),
        key_problem(value, "enabled", bool, where, required=False),
        None
        if tags is None or (isinstance(tags, list) and all(isinstance(tag, str) for tag in tags))
        else f"{yaml_path(where, 'tags')}: expected a list of strings",
        key_problem(value, "import-values", list, where, required=False),
    )


def is_chart_dependency_list(value: YamlValue) -> TypeGuard[list[ChartDependency]]:
    """Whether `value` is a list of ChartDependency."""
    return isinstance(value, list) and all(chart_dependency_problem(dep, "") is None for dep in value)


def dependencies_problem(
    mapping: YamlMapping, entry_problem: Callable[[YamlValue, str], str | None], *, required: bool
) -> str | None:
    """What is wrong with mapping["dependencies"] (see entry_problem for
    one entry), or None."""
    if "dependencies" not in mapping:
        return "(top level): missing 'dependencies'" if required else None
    deps = mapping["dependencies"]
    if deps is None:
        return None  # a bare "dependencies:" key
    if not isinstance(deps, list):
        return f"dependencies: expected a list, got {type(deps).__name__}"
    return first_problem(*(entry_problem(dep, f"dependencies[{i}]") for i, dep in enumerate(deps)))


def chart_yaml_problem(mapping: YamlMapping) -> str | None:
    """None if `mapping` is a ChartYaml, else what is wrong with it."""
    return first_problem(
        key_problem(mapping, "apiVersion", str, "", required=True),
        key_problem(mapping, "name", str, "", required=True),
        key_problem(mapping, "version", str, "", required=True),
        key_problem(mapping, "description", str, "", required=False),
        key_problem(mapping, "type", str, "", required=False),
        key_problem(mapping, "appVersion", str, "", required=False),
        dependencies_problem(mapping, chart_dependency_problem, required=False),
    )


def is_chart_yaml(mapping: YamlMapping) -> TypeGuard[ChartYaml]:
    """Whether `mapping` is a ChartYaml."""
    return chart_yaml_problem(mapping) is None


def parse_chart_yaml(text: str, source: str) -> ChartYaml:
    """`text` parsed as a Chart.yaml. Raises YamlShapeError naming
    `source` if it does not match ChartYaml."""
    mapping = parse_yaml_mapping(text, source)
    normalize_int_version(mapping)
    normalize_app_version(mapping)
    normalize_dependency_versions(mapping.get("dependencies"))
    if not is_chart_yaml(mapping):
        raise YamlShapeError(source, chart_yaml_problem(mapping) or "not a Chart.yaml")
    return mapping


def load_chart_yaml(path: Path) -> ChartYaml:
    """parse_chart_yaml of the file at `path`."""
    return parse_chart_yaml(path.read_text(encoding="utf-8"), str(path))


def chart_dependencies(chart: ChartYaml) -> list[ChartDependency]:
    """`chart`'s dependencies, [] if it has none."""
    return chart.get("dependencies") or []


def parse_chart_dependencies(text: str, source: str) -> list[ChartDependency]:
    """The dependencies of the Chart.yaml in `text`, [] if it has none.
    Checks only the dependencies, so a minimal Chart.yaml (as tests and
    vendored-chart fixtures write) is accepted. Raises YamlShapeError
    naming `source` if a dependency does not match ChartDependency."""
    mapping = parse_yaml_mapping(text, source)
    deps = mapping.get("dependencies")
    if deps is None:
        return []
    normalize_dependency_versions(deps)
    if not is_chart_dependency_list(deps):
        raise YamlShapeError(source, dependencies_problem(mapping, chart_dependency_problem, required=False) or "")
    return deps


def load_chart_dependencies(path: Path) -> list[ChartDependency]:
    """parse_chart_dependencies of the file at `path`."""
    return parse_chart_dependencies(path.read_text(encoding="utf-8"), str(path))


def parse_chart_app_version(text: str, source: str) -> str | None:
    """The appVersion of the Chart.yaml in `text` (see
    normalize_app_version), or None if it has none. Checks only that key."""
    mapping = parse_yaml_mapping(text, source)
    normalize_app_version(mapping)
    app_version = mapping.get("appVersion")
    if app_version is not None and not isinstance(app_version, str):
        raise YamlShapeError(source, f"appVersion: expected a string or number, got {type(app_version).__name__}")
    return app_version
