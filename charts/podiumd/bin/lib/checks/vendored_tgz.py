"""Verify no vendored sub-chart has both a .tgz and an extracted directory of the same name.

Helm silently prefers the extracted directory (e.g. left over from inspecting a
package) over the pinned .tgz. Must run before check_dependencies, whose rmtree of
charts/ would otherwise remove the evidence.
"""

import re

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
