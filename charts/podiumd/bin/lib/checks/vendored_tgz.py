"""Verify no vendored sub-chart has both a .tgz and an extracted directory of the same name.

Helm silently prefers the extracted directory (e.g. left over from inspecting a
package) over the pinned .tgz. Must run before check_dependencies, whose rmtree of
charts/ would otherwise remove the evidence.
"""

import re

from collections.abc import Collection
from pathlib import Path

# Version must start with a digit so hyphenated names (e.g. "keycloak-operator") parse.
TGZ_NAME_RE = re.compile(r"^(?P<name>.+)-(?P<version>\d[\w.+-]*)\.tgz$")


def find_extracted_vendored_dirs(chart_dir: Path) -> list[str]:
    """Sorted chart names with both a `<name>-<version>.tgz` and a `<name>/` under charts/."""
    charts_subdir = chart_dir / "charts"
    return sorted(name for name in vendored_tgz_versions(charts_subdir) if (charts_subdir / name).is_dir())


def vendored_tgz_versions(charts_dir: Path) -> dict[str, list[str]]:
    """{chart name: [version, ...]} of the `<name>-<version>.tgz` files in charts/; {} without charts/."""
    vendored: dict[str, list[str]] = {}
    if not charts_dir.is_dir():
        return vendored
    for path in charts_dir.glob("*.tgz"):
        name_match = TGZ_NAME_RE.match(path.name)
        if name_match:
            vendored.setdefault(name_match.group("name"), []).append(name_match.group("version"))
    return vendored


def vendored_tgz_names(charts_dir: Path) -> set[str]:
    """File names of the charts/*.tgz files; empty without charts/."""
    return {path.name for path in charts_dir.glob("*.tgz")} if charts_dir.is_dir() else set()


def other_vendored_versions(tgz_names: Collection[str], name: str, version: str) -> list[str] | None:
    """None when <name>-<version>.tgz is in `tgz_names`, else the sorted other vendored versions of `name` (maybe []).

    Parsed against `name`, not TGZ_NAME_RE, whose greedy name takes "foo-1.0.0-rc" from
    foo-1.0.0-rc-1.tgz. A version starts with a digit, so keycloak-operator-*.tgz is no keycloak.
    """
    if f"{name}-{version}.tgz" in tgz_names:
        return None
    prefix = f"{name}-"
    others = (tgz.removeprefix(prefix).removesuffix(".tgz") for tgz in tgz_names if tgz.startswith(prefix))
    return sorted(other for other in others if other[:1].isdigit())


def check_vendored_tgz_extraction(chart_dir: Path):
    """Fail if any vendored sub-chart has both a pinned .tgz and an extracted directory."""
    extracted = find_extracted_vendored_dirs(chart_dir)

    if not extracted:
        print("OK: no vendored sub-chart has both a pinned .tgz and an extracted directory")
        return True, "0 conflict(s)"

    print(
        f"Found {len(extracted)} vendored sub-chart(s) with BOTH a pinned .tgz AND an "
        f"extracted directory (Helm silently prefers the extracted copy over the pinned "
        f"package — see .claude/commands/helm-tgz-inspect.md — delete the extracted "
        f"directory before any helm operation):"
    )
    for name in extracted:
        print(f"  charts/{name}/  (next to a pinned {name}-<version>.tgz)")

    return False, f"{len(extracted)} conflict(s)"
