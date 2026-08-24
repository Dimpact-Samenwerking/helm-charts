"""Vendors every Chart.yaml dependency into charts/*.tgz via a real `helm
dependency update` — the action behind verify-podiumd.py's "Dependencies"
step, extracted here (rather than kept inline like check_lint/check_render)
because set-image-digests.py also needs to trigger it: its subchart-
default-repository fallback (lib.chart.subchart_default_repository) reads
straight from charts/*.tgz, which is gitignored — on a checkout where
nothing has vendored dependencies yet, it simply doesn't exist.

Both functions here return (ok, detail)/(ok, message) rather than the
die()-and-sys.exit() verify-podiumd.py originally used for a repo-add
failure: a lib module has no business deciding a whole process should
exit — that's a policy call each caller makes for itself. verify-podiumd.py
still dies on failure (same as before, just one level up); set-image-
digests.py instead warns and carries on with whatever it could already
resolve, since a failed re-vendor there means only its subchart-default
fallback stays degraded, not that the whole run is meaningless."""
import shutil

from lib.procutil import run
from lib.render_scope import REQUIRED_REPOS


def ensure_repos_configured():
    """Adds every Helm chart repo Chart.yaml's dependencies reference by
    alias (e.g. "@maykinmedia") — required before `helm dependency
    update`/`helm pull` can resolve any of them."""
    for name, url in REQUIRED_REPOS.items():
        result = run(["helm", "repo", "add", name, url, "--force-update"],
                      capture_output=True, text=True)
        if result.returncode != 0:
            return False, f"helm repo add {name} failed: {result.stderr.strip()}"
    result = run(["helm", "repo", "update"], capture_output=True, text=True)
    if result.returncode != 0:
        return False, f"helm repo update failed: {result.stderr.strip()}"
    return True, "repos configured"


def check_dependencies(chart_dir):
    """Rebuilds chart_dir/charts/ from scratch (rm -rf + `helm dependency
    update`) and confirms every Chart.yaml dependency actually resolved
    and bundled."""
    shutil.rmtree(chart_dir / "charts", ignore_errors=True)
    (chart_dir / "Chart.lock").unlink(missing_ok=True)
    result = run(["helm", "dependency", "update", str(chart_dir)])
    if result.returncode != 0:
        return False, "helm dependency update failed"

    result = run(["helm", "dependency", "list", str(chart_dir)], capture_output=True, text=True)
    if result.returncode != 0:
        return False, f"helm dependency list failed: {result.stderr.strip()}"
    print(result.stdout, end="")

    rows = [line for line in result.stdout.splitlines()[1:] if line.strip()]
    bad_rows = [line for line in rows if line.split()[-1] != "ok"]
    if bad_rows:
        return False, "one or more dependencies did not resolve (STATUS != ok above)"

    dep_count = len(rows)
    chart_count = len(list((chart_dir / "charts").glob("*.tgz")))
    if dep_count != chart_count:
        return False, f"expected {dep_count} bundled dependencies, found {chart_count} in charts/"
    detail = f"{dep_count} dependencies bundled"
    print(f"OK: all {detail} in charts/")
    return True, detail
