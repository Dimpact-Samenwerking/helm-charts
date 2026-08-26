#!/usr/bin/env python3
"""
Strip a UTF-8 BOM (bytes EF BB BF) from charts/podiumd/values.yaml, if
present. A BOM breaks YAML tooling that doesn't expect one — verify-podiumd.py
only detects and reports it (a verify script never writes to a tracked
file); this script is the fixer.

Usage:
    strip-utf8-bom.py             # strip the BOM in place, if present
    strip-utf8-bom.py --dry-run   # report only, no write
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import UTF8_BOM as BOM

VALUES_PATH = SCRIPT_DIR.parents[0] / "values.yaml"


def main():
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)
        sys.exit(0)
    dry_run = "--dry-run" in sys.argv[1:]

    data = VALUES_PATH.read_bytes()
    if not data.startswith(BOM):
        print(f"OK: no BOM in {VALUES_PATH}")
        sys.exit(0)

    if dry_run:
        print(f"BOM found in {VALUES_PATH} (dry-run, not writing)")
        sys.exit(1)

    VALUES_PATH.write_bytes(data[len(BOM):])
    print(f"BOM removed from {VALUES_PATH} — re-stage this file before committing")
    sys.exit(0)


if __name__ == "__main__":
    main()
