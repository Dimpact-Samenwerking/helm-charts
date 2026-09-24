#!/usr/bin/env python3
"""
Migrate the ZAC office_converter image repository in podiumd.yml files
for the ZAC 4.7.0 upgrade (PodiumD 4.7.0).

The ZAC helm chart switched from kontextwork-converter to native Gotenberg.
The ACR mirror for the new image is acrprodmgmt.azurecr.io/gotenberg
(previously acrprodmgmt.azurecr.io/office-converter).

Changes zac.office_converter.image.repository:
  acrprodmgmt.azurecr.io/office-converter  →  acrprodmgmt.azurecr.io/gotenberg

Requires: yq v4 (https://github.com/mikefarah/yq) — install with: brew install yq

Usage:
    # Migrate all podiumd.yml files in the default gemeenten directory
    python3 scripts/migrate-zac-4.7.0.py

    # Preview changes without modifying files
    python3 scripts/migrate-zac-4.7.0.py --dry-run

    # Migrate specific files
    python3 scripts/migrate-zac-4.7.0.py path/to/podiumd.yml ...
"""

import argparse
import glob
import os
import subprocess
import sys

GEMEENTEN_DIR = os.path.expanduser(
    "~/projects/dimpact/ssctwente/Applications/applications/gemeenten"
)

OLD_REPO_SUFFIX = "/office-converter"
NEW_REPO_SUFFIX = "/gotenberg"


def yq_get(expr, file):
    r = subprocess.run(["yq", expr, file], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def yq_set(expr, file):
    subprocess.run(["yq", "-i", expr, file], capture_output=True, check=True)


def check_yq():
    try:
        r = subprocess.run(["yq", "--version"], capture_output=True, text=True, check=True)
        if "mikefarah" not in r.stdout and "github.com/mikefarah" not in r.stdout:
            print("Warning: yq found but may not be mikefarah/yq v4. Output:", r.stdout.strip())
    except FileNotFoundError:
        print("Error: yq not found. Install with: brew install yq")
        sys.exit(1)


def process_file(podiumd_yml, dry_run):
    """Process a single podiumd.yml. Returns (changed, reason)."""

    repo = yq_get(".zac.office_converter.image.repository", podiumd_yml)

    if repo in ("null", "~", ""):
        return False, "no zac.office_converter.image.repository override"

    if repo.endswith(NEW_REPO_SUFFIX):
        return False, "already migrated"

    if not repo.endswith(OLD_REPO_SUFFIX):
        return False, f"unexpected repository value: {repo!r} — skipping"

    new_repo = repo[: -len(OLD_REPO_SUFFIX)] + NEW_REPO_SUFFIX

    if dry_run:
        return True, f"would change repository to {new_repo!r}"

    yq_set(
        f'.zac.office_converter.image.repository = "{new_repo}"',
        podiumd_yml,
    )
    return True, f"changed repository to {new_repo!r}"


def find_podiumd_files():
    pattern = os.path.join(os.path.expanduser(GEMEENTEN_DIR), "*", "*", "podiumd.yml")
    return sorted(glob.glob(pattern))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Specific podiumd.yml files to process (default: all files in gemeenten dir)",
    )
    args = parser.parse_args()

    check_yq()

    files = args.files if args.files else find_podiumd_files()
    if not files:
        print(f"No podiumd.yml files found in {GEMEENTEN_DIR}")
        sys.exit(1)

    if args.dry_run:
        print("Dry run — no files will be modified.\n")

    migrated = skipped = errors = 0

    for f in files:
        rel = os.path.relpath(f, os.path.expanduser(GEMEENTEN_DIR))
        try:
            changed, reason = process_file(f, args.dry_run)
            status = "CHANGED " if changed else "skipped "
            print(f"{status}  {rel}  ({reason})")
            if changed:
                migrated += 1
            else:
                skipped += 1
        except subprocess.CalledProcessError as e:
            print(f"ERROR    {rel}  (yq failed: {e.stderr.strip() if e.stderr else e})")
            errors += 1
        except Exception as e:
            print(f"ERROR    {rel}  ({e})")
            errors += 1

    print(f"\nDone: {migrated} migrated, {skipped} skipped, {errors} errors")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
