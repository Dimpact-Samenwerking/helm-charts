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
    if not charts_subdir.is_dir():
        return []

    tgz_names: set[str] = set()
    for path in charts_subdir.glob("*.tgz"):
        m = TGZ_NAME_RE.match(path.name)
        if m:
            tgz_names.add(m.group("name"))

    return sorted(name for name in tgz_names if (charts_subdir / name).is_dir())


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
