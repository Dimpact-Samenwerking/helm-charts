"""Vendors every Chart.yaml dependency into charts/*.tgz via a real `helm
dependency update` — the action behind verify-podiumd's "Dependencies"
step, extracted here (rather than kept inline like check_lint/check_render)
because set-image-digests also needs to trigger it: its subchart-
default-repository fallback (lib.chart.subchart_default_repository) reads
straight from charts/*.tgz, which is gitignored — on a checkout where
nothing has vendored dependencies yet, it simply doesn't exist.

Both functions here return (ok, detail)/(ok, message) rather than the
die()-and-sys.exit() verify-podiumd originally used for a repo-add
failure: a lib module has no business deciding a whole process should
exit — that's a policy call each caller makes for itself. verify-podiumd
still dies on failure (same as before, just one level up); set-image-
digests.py instead warns and carries on with whatever it could already
resolve, since a failed re-vendor there means only its subchart-default
fallback stays degraded, not that the whole run is meaningless."""
import re
import shutil
import time

from lib.procutil import run
from lib.render_scope import REQUIRED_REPOS

# `helm dependency update` fails intermittently on some repos (transient
# network blips, registry throttling) — retried a few times with backoff
# before it's treated as a real failure.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (5, 15, 45)

AZURE_HOST_RE = re.compile(r"\b([a-z0-9-]+\.azurecr\.io)\b", re.IGNORECASE)


def _find_azure_host(text):
    match = AZURE_HOST_RE.search(text)
    return match.group(1) if match else None


def _azure_login_hint(azure_host):
    """Checks `az account show` and returns a hint to append to the failure
    message when the user isn't logged in to Azure, or None if they already
    are (so the failure is something else — retrying is still worthwhile).
    A `helm dependency update` failure against an ACR-hosted repo gives no
    way to tell "not logged in" apart from "network blip" from its own
    error output alone, and retrying an auth failure only wastes time."""
    try:
        result = run(["az", "account", "show"], capture_output=True, text=True)
    except FileNotFoundError:
        return (f"Azure CLI (`az`) not found — install it, run "
                f"`az login --use-device-code`, then "
                f"`az acr login --name {azure_host.split('.')[0]}` before retrying.")
    if result.returncode == 0:
        return None
    return (f"not logged in to Azure — run `az login --use-device-code` "
            f"(a plain `az login` needs a local browser, which won't work here), "
            f"then `az acr login --name {azure_host.split('.')[0]}`, then re-run this check.")


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
    and bundled. Retries the update a few times on failure (Helm always
    re-downloads every dependency here — see module docstring — and that
    fails intermittently on some repos), except when the failing repo is
    Azure-hosted (*.azurecr.io) and the user isn't logged in to Azure:
    retrying an auth failure never helps, so that's reported immediately."""
    shutil.rmtree(chart_dir / "charts", ignore_errors=True)
    (chart_dir / "Chart.lock").unlink(missing_ok=True)

    result = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        result = run(["helm", "dependency", "update", str(chart_dir)],
                      capture_output=True, text=True)
        output = result.stdout + result.stderr
        print(output, end="" if output.endswith("\n") else "\n")
        if result.returncode == 0:
            break

        azure_host = _find_azure_host(output)
        if azure_host:
            hint = _azure_login_hint(azure_host)
            if hint:
                return False, f"helm dependency update failed reaching {azure_host}: {hint}"

        if attempt < RETRY_ATTEMPTS:
            delay = RETRY_BACKOFF_SECONDS[attempt - 1]
            print(f"helm dependency update failed (attempt {attempt}/{RETRY_ATTEMPTS}), "
                  f"retrying in {delay}s...")
            time.sleep(delay)

    if result.returncode != 0:
        return False, f"helm dependency update failed after {RETRY_ATTEMPTS} attempt(s)"

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
