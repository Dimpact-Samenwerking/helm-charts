"""Verifies charts/podiumd/README.md is not out of sync with values.yaml
(and README.md.gotmpl, if present) via a real `helm-docs --dry-run`
regen — companion to the /helm-docs-check skill (which covers every chart
in this repo and falls back to an approximate values.yaml-key-vs-README-
row heuristic when helm-docs isn't installed); this is the deterministic,
CI-safe version scoped to charts/podiumd only, matching every other check
in this pipeline. No fallback heuristic here: if `helm-docs` isn't
installed, this check fails with a clear message like every other
external-tool check in this pipeline (yamllint/kubeconform/shellcheck/
kube-score) — pass --skip=helm-docs to bypass.

Relation to check_docs_consistency (a separate step, see lib.
docs_consistency): none. That check verifies docs/_UPGRADE_PATHS/*.md and
docs/images/images-<version>.yaml against component version BUMPS. This
one verifies README.md's values-reference content against values.yaml's
actual keys/comments, independent of any version bump at all — a renamed
key, a changed default, or an edited comment triggers this check, not
that one, and neither substitutes for the other.

--dry-run makes helm-docs print the regenerated markdown to stdout
instead of writing README.md — this check never touches the real file,
matching check_image_digests/check_utf8_format's report-only contract: a
separate, explicit, human-run step does the actual fix, never this
script — update-podiumd-readme wraps the real (non-dry-run) `helm-docs`
command for that.

On drift, prints an actual unified diff (capped at MAX_DIFF_LINES) rather
than just a changed-line count — seeing WHICH lines moved is what makes
the finding actionable; a bare count isn't."""
import difflib
import shutil

from lib.procutil import run

README_FILENAME = "README.md"
TEMPLATE_FILENAME = "README.md.gotmpl"
FIX_COMMAND = "update-podiumd-readme"

# Past this many diff lines, printing every one stops being useful (a
# renamed top-level key can ripple through hundreds of rows) — show a
# capped, representative excerpt instead and say how many more there are.
MAX_DIFF_LINES = 40


def check_helm_docs(chart_dir):
    if shutil.which("helm-docs") is None:
        return False, "helm-docs is not installed — see --help"

    readme_path = chart_dir / README_FILENAME
    if not readme_path.is_file():
        return False, f"{readme_path} does not exist — run {FIX_COMMAND} to create it"

    cmd = ["helm-docs", "--dry-run", "--chart-search-root", str(chart_dir)]
    if (chart_dir / TEMPLATE_FILENAME).is_file():
        cmd += ["--template-files", TEMPLATE_FILENAME]

    result = run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False, f"helm-docs failed: {result.stderr.strip()}"

    original_lines = readme_path.read_text(encoding="utf-8").splitlines()
    regenerated_lines = result.stdout.splitlines()

    if regenerated_lines == original_lines:
        print(f"OK: {README_FILENAME} matches helm-docs output")
        return True, "in sync"

    diff = list(difflib.unified_diff(
        original_lines, regenerated_lines,
        fromfile=f"{README_FILENAME} (current)", tofile=f"{README_FILENAME} (helm-docs)",
        lineterm="",
    ))
    changed = sum(1 for line in diff if line[:1] in ("+", "-") and line[:3] not in ("+++", "---"))

    print(f"DRIFT: {readme_path} is out of sync with values.yaml — {changed} line(s) would change:")
    for line in diff[:MAX_DIFF_LINES]:
        print(f"  {line}")
    if len(diff) > MAX_DIFF_LINES:
        print(f"  ... ({len(diff) - MAX_DIFF_LINES} more diff line(s) not shown)")
    print(f"Run {FIX_COMMAND} to regenerate.")
    return False, f"{changed} line(s) out of sync — run {FIX_COMMAND}"
