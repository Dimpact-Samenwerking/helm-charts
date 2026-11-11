"""Verify no vendored sub-chart has both a .tgz and an extracted directory of the same name.

Helm silently prefers the extracted directory (e.g. left over from inspecting a
package) over the pinned .tgz. Must run before check_dependencies, whose rmtree of
charts/ would otherwise remove the evidence.
"""

import re

from collections.abc import Collection
from pathlib import Path

# Whether a file name looks like <name>-<version>.tgz; its greedy name group is not a chart name (vendored_versions).
TGZ_NAME_RE = re.compile(r"^(?P<name>.+)-(?P<version>\d[\w.+-]*)\.tgz$")


def find_extracted_vendored_dirs(chart_dir: Path) -> list[str]:
    """Sorted chart names with both a `<name>-<version>.tgz` and a `<name>/` under charts/."""
    charts_subdir = chart_dir / "charts"
    tgz_names = vendored_tgz_names(charts_subdir)
    if not tgz_names:
        return []
    return sorted(
        path.name for path in charts_subdir.iterdir() if path.is_dir() and vendored_versions(tgz_names, path.name)
    )


def vendored_tgz_names(charts_dir: Path) -> set[str]:
    """File names of the charts/*.tgz files; empty without charts/."""
    return {path.name for path in charts_dir.glob("*.tgz")} if charts_dir.is_dir() else set()


def vendored_versions(tgz_names: Collection[str], name: str) -> list[str]:
    """Sorted versions of the `<name>-<version>.tgz` files in `tgz_names`.

    Parsed against `name`, not TGZ_NAME_RE, whose greedy name takes "foo-1.0.0-rc" from
    foo-1.0.0-rc-1.tgz. A version starts with a digit, so keycloak-operator-*.tgz is no keycloak.
    """
    prefix = f"{name}-"
    versions = (tgz.removeprefix(prefix).removesuffix(".tgz") for tgz in tgz_names if tgz.startswith(prefix))
    return sorted(version for version in versions if version[:1].isdigit())


def other_vendored_versions(tgz_names: Collection[str], name: str, version: str) -> list[str] | None:
    """None when <name>-<version>.tgz is in `tgz_names`, else vendored_versions of `name` (maybe [])."""
    if f"{name}-{version}.tgz" in tgz_names:
        return None
    return vendored_versions(tgz_names, name)


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
