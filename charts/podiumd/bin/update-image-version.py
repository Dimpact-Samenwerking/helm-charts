#!/usr/bin/env python3
"""
Bump every values.yaml image tag pin sharing a given image's basename (the
last "/"-separated segment of its "repository:" value) to a new version,
re-resolving each pin's digest against the registry. The same base image
is sometimes pinned in more than one unrelated place (e.g.
curlimages/curl, used as a generic init-container/health-check helper) —
every one of those gets updated together, not just the first found.

<target> can also be a Chart.yaml dependency's own name or alias instead
of a bare basename (e.g. "openklant", "zac") — tried only if <target>
isn't already a real basename, and only resolved when that dependency
pins exactly one image; a dependency pinning several (most of them —
e.g. "zac" has eight) fails loudly listing them instead of guessing
which one you meant. No release-table.csv involved either way — this
reads straight from Chart.yaml/values.yaml (see
lib.image_version.resolve_basename).

Refuses to touch values.yaml unless the new version verifiably exists
upstream for every matched repository first — a bad version name fails
loudly with nothing written, never a half-updated file.

Usage:
    update-image-version.py <target> <new-version>

Examples:
    update-image-version.py curl 8.22.0
        # updates every "repository: .../curl" pin's tag, wherever it appears
    update-image-version.py pabc-api 1.1.2
    update-image-version.py openklant 2.15.1
        # "openklant" isn't a basename -- resolved as a Chart.yaml
        # dependency whose own values.yaml scope pins exactly one image

A component's app version is not always its image's basename (e.g.
zgw-office-addin bumps two distinctly-named images, frontend + backend) —
see update-component-version.py, which resolves each of a component's
image path(s) to its own actual basename and calls this same logic
(lib.image_version.update_image_version) per path.

After writing, re-render the chart (verify-podiumd.py or /helm-render-all)
to confirm before committing.
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.image_version import resolve_basename, update_image_version

CHART_DIR = SCRIPT_DIR.parents[0]
VALUES_YAML = CHART_DIR / "values.yaml"


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    target, new_version = sys.argv[1], sys.argv[2]

    lines = VALUES_YAML.read_text(encoding="utf-8").splitlines()
    basename = resolve_basename(CHART_DIR, lines, target)
    if basename != target:
        print(f"'{target}' resolved to image basename '{basename}'")

    changes = update_image_version(VALUES_YAML, basename, new_version)
    if not changes:
        print(f"'{basename}' is already at {new_version} everywhere it's pinned — nothing to do.")
        return

    print(f"=== Writing {VALUES_YAML} ===")
    for c in changes:
        print(f"  values.yaml:{c['line']}  ({c['repository']})")
        print(f"    {c['old_version']}@{c['old_digest']}")
        print(f"    {c['new_version']}@{c['new_digest']}")

    print()
    print(f"Updated {len(changes)} pin(s). Re-render the chart to confirm "
          "(verify-podiumd.py or /helm-render-all) before committing.")


if __name__ == "__main__":
    main()
