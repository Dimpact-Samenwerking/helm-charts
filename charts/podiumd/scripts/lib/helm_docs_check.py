"""Verifies charts/podiumd/README.md is not out of sync with values.yaml
(and README.md.gotmpl, if present) via a real `helm-docs --dry-run`
regen — companion to the /helm-docs-check skill (which covers every chart
in this repo and falls back to an approximate values.yaml-key-vs-README-
row heuristic when helm-docs isn't installed); this is the deterministic,
CI-safe version scoped to charts/podiumd only, matching every other check
in this pipeline. No fallback heuristic here: if `helm-docs` isn't
installed, this check fails with a clear message like every other
external-tool check in this pipeline (yamllint/kubeconform/shellcheck/
kube-score) — pass --skip=helm-docs-check to bypass.

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
separate, explicit, human-run step (the real `helm-docs` command, same as
/helm-docs-check's Tier 1) does the actual fix, never this script."""
import shutil

from lib.procutil import run

README_FILENAME = "README.md"
TEMPLATE_FILENAME = "README.md.gotmpl"


def check_helm_docs(chart_dir):
    if shutil.which("helm-docs") is None:
        return False, "helm-docs is not installed — see --help"

    readme_path = chart_dir / README_FILENAME
    if not readme_path.is_file():
        return False, f"{readme_path} does not exist — run helm-docs (see /helm-docs-check) to create it"

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

    changed = sum(1 for a, b in zip(original_lines, regenerated_lines) if a != b) \
        + abs(len(original_lines) - len(regenerated_lines))
    print(f"DRIFT: {readme_path} is out of sync with values.yaml — {changed} line(s) would change. "
          f"Run helm-docs (see /helm-docs-check) to regenerate; never auto-fixed here.")
    return False, f"{changed} line(s) out of sync"
