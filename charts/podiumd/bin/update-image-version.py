#!/usr/bin/env python3
"""
Bump every values.yaml image tag pin sharing a given image's basename (the
last "/"-separated segment of its "repository:" value) to a new version,
re-resolving each pin's digest against the registry. The same base image
is sometimes pinned in more than one unrelated place (e.g.
curlimages/curl, used as a generic init-container/health-check helper) —
every one of those gets updated together, not just the first found.

Refuses to touch values.yaml unless the new version verifiably exists
upstream for every matched repository first — a bad version name fails
loudly with nothing written, never a half-updated file.

Usage:
    update-image-version.py <image-basename> <new-version>

Examples:
    update-image-version.py curl 8.22.0
        # updates every "repository: .../curl" pin's tag, wherever it appears
    update-image-version.py pabc-api 1.1.2

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

from lib.image_version import update_image_version

VALUES_YAML = SCRIPT_DIR.parents[0] / "values.yaml"


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    basename, new_version = sys.argv[1], sys.argv[2]

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
