"""Verifies no vendored sub-chart under charts/podiumd/charts/ has both a
pinned .tgz package AND an extracted directory of the same chart name
sitting next to it, per .claude/commands/helm-tgz-inspect.md's documented
warning: Helm prefers an extracted chart directory over a .tgz of the same
name, so a stray extracted copy (e.g. left over from manually `tar -xzf`-ing
a package to inspect it) makes `helm template`/`lint`/`upgrade` silently
use that possibly-modified/stale directory instead of the pinned package —
"has caused broken deployments" per that doc.

Runs BEFORE check_dependencies deliberately: check_dependencies's own
`shutil.rmtree(chart_dir / "charts")` would otherwise silently wipe any
such extracted directory before this check ever got to see it, making the
check a no-op if it ran any later in the pipeline."""
import re

# <chart-name>-<version>.tgz — version must start with a digit so a
# hyphenated chart name (e.g. "notifynl-omc-nodep", "keycloak-operator")
# doesn't get misparsed as part of the version.
TGZ_NAME_RE = re.compile(r"^(?P<name>.+)-(?P<version>\d[\w.+-]*)\.tgz$")


def find_extracted_vendored_dirs(chart_dir):
    """Returns a sorted list of chart names that have BOTH a pinned
    `<name>-<version>.tgz` package and an extracted `<name>/` directory
    under chart_dir/charts/."""
    charts_subdir = chart_dir / "charts"
    if not charts_subdir.is_dir():
        return []

    tgz_names = set()
    for path in charts_subdir.glob("*.tgz"):
        m = TGZ_NAME_RE.match(path.name)
        if m:
            tgz_names.add(m.group("name"))

    return sorted(name for name in tgz_names if (charts_subdir / name).is_dir())


def check_vendored_tgz_extraction(chart_dir):
    extracted = find_extracted_vendored_dirs(chart_dir)

    if not extracted:
        print("OK: no vendored sub-chart has both a pinned .tgz and an extracted directory")
        return True, "0 conflict(s)"

    print(f"Found {len(extracted)} vendored sub-chart(s) with BOTH a pinned .tgz AND an "
          f"extracted directory (Helm silently prefers the extracted copy over the pinned "
          f"package — see .claude/commands/helm-tgz-inspect.md — delete the extracted "
          f"directory before any helm operation):")
    for name in extracted:
        print(f"  charts/{name}/  (next to a pinned {name}-<version>.tgz)")

    return False, f"{len(extracted)} conflict(s)"
