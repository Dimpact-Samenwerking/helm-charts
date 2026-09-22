"""Verifies charts/podiumd/README.md is not out of sync with values.yaml
(and README.md.gotmpl, if present) via a real `helm-docs --dry-run`
regen — companion to the /helm-docs-check skill (which covers every chart
in this repo and falls back to an approximate values.yaml-key-vs-README-
row heuristic when helm-docs isn't installed); this is the deterministic,
CI-safe version scoped to charts/podiumd only, matching every other check
in this pipeline. No fallback heuristic here: if `helm-docs` isn't
installed, this check fails with a clear message like every other
external-tool check in this pipeline (yamllint/kubeconform/shellcheck/
kube-score) — pass --skip=helm-doc to bypass.

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
script — fix-helm-doc wraps the real (non-dry-run) `helm-docs`
command for that.

On drift, prints an actual unified diff (capped at helm_doc.
max_diff_lines_shown, see lib.settings) rather than just a changed-line
count — seeing WHICH lines moved is what makes the finding actionable; a
bare count isn't."""

import difflib
import shutil

from lib.procutil import run
from lib.settings import helm_doc_max_diff_lines_shown

README_FILENAME = "README.md"
TEMPLATE_FILENAME = "README.md.gotmpl"
FIX_COMMAND = "fix-helm-doc"


def check_helm_docs(chart_dir):
    """Regenerate README.md via `helm-docs --dry-run` (see module
    docstring) and diff it against the real file. Fails outright if
    helm-docs isn't installed or README.md doesn't exist yet — no
    fallback heuristic, unlike the more permissive /helm-docs-check
    skill. On drift, prints a unified diff capped at helm_doc.
    max_diff_lines_shown (lib.settings) and points at fix-helm-doc to
    actually regenerate the file; this check itself never writes to
    README.md."""
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

    diff = list(
        difflib.unified_diff(
            original_lines,
            regenerated_lines,
            fromfile=f"{README_FILENAME} (current)",
            tofile=f"{README_FILENAME} (helm-docs)",
            lineterm="",
        )
    )
    changed = sum(1 for line in diff if line[:1] in ("+", "-") and line[:3] not in ("+++", "---"))
    max_diff_lines = helm_doc_max_diff_lines_shown(chart_dir)

    print(f"DRIFT: {readme_path} is out of sync with values.yaml — {changed} line(s) would change:")
    for line in diff[:max_diff_lines]:
        print(f"  {line}")
    if len(diff) > max_diff_lines:
        print(f"  ... ({len(diff) - max_diff_lines} more diff line(s) not shown)")
    print(f"Run {FIX_COMMAND} to regenerate.")
    return False, f"{changed} line(s) out of sync — run {FIX_COMMAND}"
