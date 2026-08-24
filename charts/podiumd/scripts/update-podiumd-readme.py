#!/usr/bin/env python3
"""
Regenerate charts/podiumd/README.md via the real `helm-docs` command — the
fixer for verify-podiumd.py's "Helm docs check" step (lib.helm_docs_check),
which only ever reports drift via `helm-docs --dry-run` and never writes
to the real file itself. Same convention as strip-utf8-bom.py/
set-image-digests.py: a report-only check pairs with a separate, explicit
fixer script.

Usage:
    update-podiumd-readme.py             # regenerate README.md in place
    update-podiumd-readme.py --dry-run   # report only, no write — delegates
                                          # to the exact same check
                                          # verify-podiumd.py runs
                                          # (lib.helm_docs_check.check_helm_docs)

Does not stage or commit — review the diff and stage it yourself.

Requires the `helm-docs` binary on PATH (https://github.com/norwoodj/helm-docs).
"""
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.helm_docs_check import README_FILENAME, TEMPLATE_FILENAME, check_helm_docs
from lib.procutil import run

CHART_DIR = SCRIPT_DIR.parent


def main():
    if shutil.which("helm-docs") is None:
        print("FAIL: helm-docs is not installed (https://github.com/norwoodj/helm-docs)", file=sys.stderr)
        sys.exit(1)

    if "--dry-run" in sys.argv[1:]:
        ok, _ = check_helm_docs(CHART_DIR)
        sys.exit(0 if ok else 1)

    cmd = ["helm-docs", "--chart-search-root", str(CHART_DIR)]
    if (CHART_DIR / TEMPLATE_FILENAME).is_file():
        cmd += ["--template-files", TEMPLATE_FILENAME]

    result = run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAIL: helm-docs failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    readme_path = CHART_DIR / README_FILENAME
    diff = run(["git", "diff", "--stat", "--", str(readme_path)], capture_output=True, text=True)
    if diff.stdout.strip():
        print(diff.stdout, end="")
        print(f"{README_FILENAME} regenerated — review the diff above and stage it yourself before committing")
    else:
        print(f"OK: {README_FILENAME} already matched helm-docs output — nothing changed")


if __name__ == "__main__":
    main()
