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

Probes with `helm-docs --dry-run` first and only runs the real (writing)
command when the output actually differs from the current README.md — so a
no-op run never touches the file's mtime or its content.

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


def build_cmd(dry_run):
    cmd = ["helm-docs"]
    if dry_run:
        cmd.append("--dry-run")
    cmd += ["--chart-search-root", str(CHART_DIR)]
    if (CHART_DIR / TEMPLATE_FILENAME).is_file():
        cmd += ["--template-files", TEMPLATE_FILENAME]
    return cmd


def main():
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)
        sys.exit(0)
    if shutil.which("helm-docs") is None:
        print("FAIL: helm-docs is not installed (https://github.com/norwoodj/helm-docs)", file=sys.stderr)
        sys.exit(1)

    if "--dry-run" in sys.argv[1:]:
        ok, _ = check_helm_docs(CHART_DIR)
        sys.exit(0 if ok else 1)

    readme_path = CHART_DIR / README_FILENAME
    dry_result = run(build_cmd(dry_run=True), capture_output=True, text=True)
    if dry_result.returncode != 0:
        print(f"FAIL: helm-docs failed: {dry_result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    current_lines = readme_path.read_text(encoding="utf-8").splitlines() if readme_path.is_file() else None
    if dry_result.stdout.splitlines() == current_lines:
        print(f"OK: {README_FILENAME} already matched helm-docs output — nothing changed")
        return

    result = run(build_cmd(dry_run=False), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAIL: helm-docs failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    diff = run(["git", "diff", "--stat", "--", str(readme_path)], capture_output=True, text=True)
    if diff.stdout.strip():
        print(diff.stdout, end="")
        print(f"{README_FILENAME} regenerated — review the diff above and stage it yourself before committing")
    else:
        print(f"OK: {README_FILENAME} already matched helm-docs output — nothing changed")


if __name__ == "__main__":
    main()
