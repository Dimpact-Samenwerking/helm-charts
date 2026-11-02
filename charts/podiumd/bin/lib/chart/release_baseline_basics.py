"""Read/write etc/release-baseline.yaml, and read a Chart.yaml version."""

from pathlib import Path

import yaml

from lib.chart.chart_yaml import normalize_int_version
from lib.version_numbers import is_bare_version
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlShapeError
from lib.yaml_types import key_problem
from lib.yaml_types import load_yaml_mapping


def chart_version(chart_yaml_path: Path) -> str:
    """The "version:" of the Chart.yaml at `chart_yaml_path`.

    An unquoted integer is stringified; any other non-string (a bare "4.90"
    is the float 4.9) raises YamlShapeError.
    """
    mapping = load_yaml_mapping(chart_yaml_path)
    normalize_int_version(mapping)
    version = mapping.get("version")
    if not isinstance(version, str):
        problem = key_problem(mapping, "version", str, "", required=True)
        raise YamlShapeError(str(chart_yaml_path), problem or "version: expected str")
    return version


RELEASE_BASELINES_FILE_NAME = "etc/release-baseline.yaml"


def _release_baselines(chart_dir: Path) -> YamlMapping:
    """The parsed etc/release-baseline.yaml, or {} if it doesn't exist."""
    path = chart_dir / RELEASE_BASELINES_FILE_NAME
    if not path.is_file():
        return {}
    return load_yaml_mapping(path)


def _baseline_value(chart_dir: Path, key: str) -> str | None:
    """release-baseline.yaml's `key`, or None if missing; raises YamlShapeError if not a string."""
    baselines = _release_baselines(chart_dir)
    problem = key_problem(baselines, key, str, "", required=False)
    if problem is not None:
        raise YamlShapeError(RELEASE_BASELINES_FILE_NAME, problem)
    value = baselines.get(key)
    return value if isinstance(value, str) else None


def upgrade_docs_baseline(chart_dir: Path):
    """The incremental baseline of _UPGRADE_PATHS/*.md and images-<target>.yaml, or None.

    The immediately preceding release, advanced every release cycle.
    """
    return _baseline_value(chart_dir, "upgrade_docs")


def upgrade_docs_side_paths(chart_dir: Path) -> list[str]:
    """release-baseline.yaml's `side_paths`: further baselines whose docs to the same target are kept, or [].

    A release can be reached from a version that is not upgrade_docs, such
    as a patch released on an older line after it. Its
    <side>-to-<target>-*.md docs are then a second upgrade path, maintained
    like the main one, instead of a leftover to rebase onto upgrade_docs.
    Raises YamlShapeError unless the key is a list of MAJOR.MINOR.PATCH strings.
    """
    value = _release_baselines(chart_dir).get("side_paths", [])
    versions = (
        [item for item in value if isinstance(item, str) and is_bare_version(item)] if isinstance(value, list) else []
    )
    if not isinstance(value, list) or len(versions) != len(value):
        raise YamlShapeError(RELEASE_BASELINES_FILE_NAME, "side_paths: expected a list of MAJOR.MINOR.PATCH strings")
    upgrade_docs = upgrade_docs_baseline(chart_dir)
    return [item for item in dict.fromkeys(versions) if item != upgrade_docs]


def release_table_baseline(chart_dir: Path):
    """The cumulative baseline of release-table.csv, or None; advanced only on a minor bump."""
    return _baseline_value(chart_dir, "release_table")


def write_release_baselines(
    chart_dir: Path,
    upgrade_docs: str | None = None,
    release_table: str | None = None,
    side_paths: list[str] | None = None,
):
    """Update only the given keys of etc/release-baseline.yaml, keeping the others.

    An empty `side_paths` removes that key. Values are written double-quoted
    like the other version files; safe_dump has no "quote every string"
    option, so each value is dumped on its own with default_style='"' to get
    correct escaping, a list in flow style on the key's line.
    """
    path = chart_dir / RELEASE_BASELINES_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _release_baselines(chart_dir)
    if upgrade_docs is not None:
        data["upgrade_docs"] = upgrade_docs
    if release_table is not None:
        data["release_table"] = release_table
    if side_paths:
        data["side_paths"] = list(side_paths)
    elif side_paths is not None:
        data.pop("side_paths", None)
    lines: list[str] = []
    for key, value in data.items():
        quoted_value = yaml.safe_dump(value, default_style='"', default_flow_style=True, width=1000).rstrip("\n")
        lines.append(f"{key}: {quoted_value}\n")
    path.write_text("".join(lines), encoding="utf-8")
