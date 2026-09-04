"""Vendors every Chart.yaml dependency into charts/*.tgz via a real `helm
dependency update` — the action behind verify-podiumd's "Dependencies"
step, extracted here (rather than kept inline like check_lint/check_render)
because fix-image-digests also needs to trigger it: its subchart-
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
import shutil
import sys
import time

import yaml

from lib.procutil import run
from lib.render_scope import REQUIRED_REPOS

# `helm dependency update` fails intermittently on some repos (transient
# network blips, registry throttling) — retried a few times with backoff
# before it's treated as a real failure.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (5, 15, 45)


def _dependency_key(dep):
    """(name, version, repository) — the identity a dependency's own
    Chart.lock entry and its current Chart.yaml entry must agree on for
    _vendored_state_matches_chart_yaml to trust the lock file at all.

    str() on version: Chart.yaml can write a bare-looking version
    ("version: 26") that YAML parses as an int, while Chart.lock always
    quotes it back out as a string — comparing raw values would treat
    that as a mismatch even though nothing actually changed.

    repository is resolved through REQUIRED_REPOS when Chart.yaml
    references it by "@alias" (e.g. "@maykinmedia") — Chart.lock never
    stores an alias, only the fully-resolved plain URL it points at, so
    comparing the two forms directly would treat every single alias-
    referenced dependency as "changed" even when nothing has (real bug
    this fixes: caught live against the actual chart, where 17 of 25
    dependencies use an alias and _vendored_state_matches_chart_yaml
    never once returned True as a result). A repository Chart.yaml
    already writes as a plain URL/oci:// reference (no dependency here
    uses an alias Helm itself doesn't also resolve identically) passes
    through unchanged."""
    repo = dep.get("repository") or ""
    if repo.startswith("@"):
        repo = REQUIRED_REPOS.get(repo[1:], repo)
    return dep.get("name"), str(dep.get("version")), repo


def _vendored_state_matches_chart_yaml(chart_dir):
    """True when Chart.lock's own dependency list already exactly matches
    Chart.yaml's CURRENT one (same (name, version, repository) triples,
    order-independent — see _dependency_key) AND every one of those
    dependencies' own charts/<name>-<version>.tgz is already vendored on
    disk. When this holds, a fresh `helm dependency update` would do
    nothing new — the on-disk state already IS what Chart.yaml asks for
    — so check_dependencies below skips it entirely rather than paying
    for a full re-download of every dependency (Helm re-fetches all of
    them unconditionally every time, never just the ones that changed —
    see check_dependencies' own docstring; measured ~80s against the
    real chart's 25 dependencies, `--skip-refresh` or `helm dependency
    build` included, neither actually skips re-fetching an already-
    correct dependency in the Helm version this repo currently uses).

    False (never raises) for any reason the lock can't be trusted as-is:
    missing, unparseable, a different dependency set/version/repository,
    or a dependency missing its own vendored .tgz — check_dependencies'
    own full rebuild-from-scratch path is the safe fallback for every
    one of those, exactly as if this check didn't exist at all."""
    lock_path = chart_dir / "Chart.lock"
    if not lock_path.is_file():
        return False
    try:
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
        chart_yaml = yaml.safe_load((chart_dir / "Chart.yaml").read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return False

    lock_deps = lock.get("dependencies") or []
    chart_deps = chart_yaml.get("dependencies") or []
    if not chart_deps or len(lock_deps) != len(chart_deps):
        return False
    if {_dependency_key(d) for d in lock_deps} != {_dependency_key(d) for d in chart_deps}:
        return False

    return all((chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz").is_file() for dep in chart_deps)


def ensure_repos_configured():
    """Adds every Helm chart repo Chart.yaml's dependencies reference by
    alias (e.g. "@maykinmedia") — required before `helm dependency
    update`/`helm pull` can resolve any of them.

    The final `helm repo update` is scoped to just REQUIRED_REPOS' own
    names — never a blanket, argument-less `helm repo update`, which
    refreshes EVERY repo this machine has ever had `helm repo add`ed to
    it (measured live: 19 configured locally, only 9 of them actually
    used by this chart — the other 10 are leftovers from unrelated Helm
    work, e.g. bitnami/grafana/hashicorp/traefik, that this project's
    dependencies never reference at all). Refreshing those extra repos'
    indexes is pure waste: ~6.2s for all 19 vs. ~0.6s scoped to the 9
    this function itself just added/verified above."""
    for name, url in REQUIRED_REPOS.items():
        result = run(["helm", "repo", "add", name, url, "--force-update"],
                      capture_output=True, text=True)
        if result.returncode != 0:
            return False, f"helm repo add {name} failed: {result.stderr.strip()}"
    result = run(["helm", "repo", "update", *REQUIRED_REPOS.keys()], capture_output=True, text=True)
    if result.returncode != 0:
        return False, f"helm repo update failed: {result.stderr.strip()}"
    return True, "repos configured"


def check_dependencies(chart_dir):
    """Confirms every Chart.yaml dependency actually resolved and bundled
    into chart_dir/charts/ — skipping the (always slow — Helm re-fetches
    every single dependency unconditionally, never just the changed ones;
    see _vendored_state_matches_chart_yaml's own docstring) `helm
    dependency update` entirely when Chart.lock already proves the
    on-disk vendored state matches Chart.yaml's current dependencies
    exactly. Otherwise rebuilds chart_dir/charts/ from scratch (rm -rf +
    `helm dependency update`), retried a few times on failure (transient
    network blips, registry throttling).

    The `helm dependency list` verification below always runs regardless
    of which path was taken above — cheap (no network, purely local) and
    the one thing that actually proves the vendored state resolves
    correctly, so skipping the expensive re-download step never skips
    that guarantee too.

    Deliberately does NOT capture_output= the update call, unlike every
    other `run(...)` here: `helm dependency update` re-downloads every
    single dependency from scratch (see above) and prints its own per-
    dependency "Downloading X from repo Y" progress as it goes —
    capturing it would buffer that away until the whole (often tens-of-
    seconds) update finishes, making this step look hung the entire
    time. Letting the subprocess inherit stdout/stderr directly instead
    streams Helm's own progress live, interleaved with this step's own
    prints — flushing first (same reason lib.procutil.run_script's own
    docstring flushes before a live-streamed child) so an earlier, still-
    buffered print from this process can't end up appearing AFTER output
    the child already wrote straight to the same fd."""
    if _vendored_state_matches_chart_yaml(chart_dir):
        print("Chart.lock already matches Chart.yaml and every dependency is vendored — "
              "skipping helm dependency update")
    else:
        shutil.rmtree(chart_dir / "charts", ignore_errors=True)
        (chart_dir / "Chart.lock").unlink(missing_ok=True)

        result = None
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            print(f"Running helm dependency update (attempt {attempt}/{RETRY_ATTEMPTS})...")
            sys.stdout.flush()
            result = run(["helm", "dependency", "update", str(chart_dir)])
            if result.returncode == 0:
                break

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
