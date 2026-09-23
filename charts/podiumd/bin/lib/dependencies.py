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
fallback stays degraded, not that the whole run is meaningless.

vendored_dependency_problems/require_vendored_dependencies are the
read-only side of the same concern: a purely local "is charts/ + Chart.lock
still what Chart.yaml asks for?" check, and the fail-fast guard every
script that renders the chart or reads its vendored .tgz calls first (see
require_vendored_dependencies for why that one does exit)."""

import contextlib
import shutil
import sys
import time

from pathlib import Path

import yaml

from lib.checks.vendored_tgz import TGZ_NAME_RE
from lib.procutil import run
from lib.settings import dependency_fetch_retry_attempts
from lib.settings import dependency_fetch_retry_backoff_seconds
from lib.settings import helm_repos_urls_by_alias


def _dependency_key(dep, required_repos):
    """(name, version, repository) — the identity a dependency's own
    Chart.lock entry and its current Chart.yaml entry must agree on for
    vendored_state_matches_chart_yaml to trust the lock file at all.

    str() on version: Chart.yaml can write a bare-looking version
    ("version: 26") that YAML parses as an int, while Chart.lock always
    quotes it back out as a string — comparing raw values would treat
    that as a mismatch even though nothing actually changed.

    repository is resolved through `required_repos` (see
    lib.settings.helm_repos_urls_by_alias) when Chart.yaml references it
    by "@alias" (e.g. "@maykinmedia") — Chart.lock never stores an alias,
    only the fully-resolved plain URL it points at, so comparing the two
    forms directly would treat every single alias-referenced dependency
    as "changed" even when nothing has (real bug this fixes: caught live
    against the actual chart, where 17 of 25 dependencies use an alias
    and vendored_state_matches_chart_yaml never once returned True as a
    result). A repository Chart.yaml already writes as a plain URL/oci://
    reference (no dependency here uses an alias Helm itself doesn't also
    resolve identically) passes through unchanged."""
    repo = dep.get("repository") or ""
    if repo.startswith("@"):
        repo = required_repos.get(repo[1:], repo)
    return dep.get("name"), str(dep.get("version")), repo


def _lock_problems(chart_dir, chart_deps):
    """Every way chart_dir/Chart.lock disagrees with Chart.yaml's current
    `chart_deps` — [] when the lock lists exactly the same (name, version,
    repository) triples (see _dependency_key). One entry per affected
    dependency, naming both sides where it can, e.g. "kiss-chart:
    Chart.yaml wants 3.1.1, Chart.lock has 3.0.0"."""
    lock_path = chart_dir / "Chart.lock"
    if not lock_path.is_file():
        return ["Chart.lock is missing"]
    try:
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ["Chart.lock is not valid YAML"]

    required_repos = helm_repos_urls_by_alias(chart_dir)
    lock_deps = lock.get("dependencies") or []
    wanted = {_dependency_key(d, required_repos) for d in chart_deps}
    locked = {_dependency_key(d, required_repos) for d in lock_deps}

    problems = [_describe_lock_mismatch(key, locked) for key in sorted(wanted - locked)]
    wanted_names = {k[0] for k in wanted}
    problems.extend(
        f"{name}: in Chart.lock ({version}) but no longer in Chart.yaml"
        for name, version, _repo in sorted(locked - wanted)
        if name not in wanted_names
    )
    if not problems and len(lock_deps) != len(chart_deps):
        problems.append(f"Chart.lock lists {len(lock_deps)} dependencies, Chart.yaml {len(chart_deps)}")
    return problems


def _describe_lock_mismatch(wanted_key, locked):
    """One _lock_problems entry for a Chart.yaml (name, version,
    repository) triple Chart.lock doesn't have: a different repository
    for the same version, a different version, or no entry at all."""
    name, version, repo = wanted_key
    same_name = sorted(k for k in locked if k[0] == name)
    same_version_repos = sorted({k[2] for k in same_name if k[1] == version})
    if same_version_repos:
        return f"{name}: Chart.yaml wants repository {repo}, Chart.lock has {', '.join(same_version_repos)}"
    if same_name:
        return f"{name}: Chart.yaml wants {version}, Chart.lock has {', '.join(k[1] for k in same_name)}"
    return f"{name}: missing from Chart.lock"


def _tgz_problems(chart_dir, chart_deps):
    """One entry per Chart.yaml dependency whose charts/<name>-<version>.tgz
    isn't vendored, naming whatever other version of it charts/ has
    instead (parsed with lib.checks.vendored_tgz.TGZ_NAME_RE, the same
    <name>-<version>.tgz split that check already uses)."""
    charts_dir = chart_dir / "charts"
    vendored = {}
    if charts_dir.is_dir():
        for path in charts_dir.glob("*.tgz"):
            match = TGZ_NAME_RE.match(path.name)
            if match:
                vendored.setdefault(match["name"], []).append(match["version"])

    problems = []
    for name, version in sorted({(d.get("name"), str(d.get("version"))) for d in chart_deps}):
        if (charts_dir / f"{name}-{version}.tgz").is_file():
            continue
        others = sorted(vendored.get(name, []))
        if others:
            problems.append(f"{name}: Chart.yaml wants {version}, charts/ has {', '.join(others)}")
        else:
            problems.append(f"{name}: charts/{name}-{version}.tgz is missing")
    return problems


def _dependency_state(chart_dir):
    """(chart_deps, problems): Chart.yaml's current dependency list, plus
    every reason the vendored state (Chart.lock + charts/*.tgz) doesn't
    match it — see vendored_dependency_problems. The one shared
    implementation behind both vendored_dependency_problems and
    vendored_state_matches_chart_yaml, so the two can never disagree about
    what "in sync" means."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    if not chart_yaml_path.is_file():
        return [], ["Chart.yaml is missing"]
    try:
        chart_yaml = yaml.safe_load(chart_yaml_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return [], ["Chart.yaml is not valid YAML"]
    chart_deps = chart_yaml.get("dependencies") or []
    if not chart_deps:
        return [], []
    return chart_deps, _lock_problems(chart_dir, chart_deps) + _tgz_problems(chart_dir, chart_deps)


def vendored_dependency_problems(chart_dir):
    """Every reason chart_dir's vendored state doesn't match its CURRENT
    Chart.yaml: Chart.lock missing, unparseable, or listing a different
    (name, version, repository) set (see _dependency_key), and any
    dependency whose own charts/<name>-<version>.tgz isn't on disk. []
    when everything lines up, or when Chart.yaml has no dependencies at
    all (nothing to vendor). Purely local — no helm call, no network.

    Both files are gitignored, so a branch switch or pull that moves
    Chart.yaml on leaves them silently stale; a later `helm template`
    then fails with a sub-chart schema error that never mentions the
    real cause, and every vendored-.tgz-only lookup (lib.chart.
    subchart_values & co.) silently returns None instead. See
    require_vendored_dependencies for the scripts' own fail-fast guard
    built on this."""
    return _dependency_state(chart_dir)[1]


def vendored_state_matches_chart_yaml(chart_dir):
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
    a dependency missing its own vendored .tgz (see vendored_dependency_
    problems for the itemized list), or a Chart.yaml with no dependencies
    at all — check_dependencies' own full rebuild-from-scratch path is
    the safe fallback for every one of those, exactly as if this check
    didn't exist at all."""
    chart_deps, problems = _dependency_state(chart_dir)
    return bool(chart_deps) and not problems


def require_vendored_dependencies(chart_dir):
    """Fail-fast guard for scripts that render chart_dir or read its
    vendored charts/*.tgz / Chart.lock: raises SystemExit (exit 1, the
    message on stderr) naming every stale or missing dependency and the
    `helm dependency update` command that fixes it, instead of letting a
    later render fail on an unrelated-looking sub-chart schema error.

    The module's one exit-deciding function, on purpose: it is only ever
    called from a script's own main(), never from another lib function,
    so the "should this process exit?" policy still belongs to each
    script — this just keeps the message and exit code identical across
    all of them. Scripts that repair the state themselves (verify-
    podiumd's "Dependencies" step, fix-image-digests) don't call it
    before that repair."""
    problems = vendored_dependency_problems(chart_dir)
    if not problems:
        return
    shown = chart_dir
    with contextlib.suppress(ValueError):
        shown = chart_dir.resolve().relative_to(Path.cwd())
    details = "\n".join(f"  - {problem}" for problem in problems)
    message = (
        f"error: {shown}/charts/ and Chart.lock do not match Chart.yaml (stale or missing sub-charts):\n"
        f"{details}\n"
        f"Run: helm dependency update {shown}"
    )
    raise SystemExit(message)


def ensure_repos_configured(chart_dir):
    """Adds every Helm chart repo Chart.yaml's dependencies reference by
    alias (e.g. "@maykinmedia") — required before `helm dependency
    update`/`helm pull` can resolve any of them.

    The final `helm repo update` is scoped to just the resolved
    helm_repos_urls_by_alias' own names — never a blanket, argument-less
    `helm repo update`, which refreshes EVERY repo this machine has ever
    had `helm repo add`ed to it (measured live: 19 configured locally,
    only 9 of them actually used by this chart — the other 10 are
    leftovers from unrelated Helm work, e.g. bitnami/grafana/hashicorp/
    traefik, that this project's dependencies never reference at all).
    Refreshing those extra repos' indexes is pure waste: ~6.2s for all 19
    vs. ~0.6s scoped to the 9 this function itself just added/verified
    above."""
    required_repos = helm_repos_urls_by_alias(chart_dir)
    for name, url in required_repos.items():
        result = run(["helm", "repo", "add", name, url, "--force-update"], capture_output=True, text=True)
        if result.returncode != 0:
            return False, f"helm repo add {name} failed: {result.stderr.strip()}"
    result = run(["helm", "repo", "update", *required_repos.keys()], capture_output=True, text=True)
    if result.returncode != 0:
        return False, f"helm repo update failed: {result.stderr.strip()}"
    return True, "repos configured"


def check_dependencies(chart_dir):
    """Confirms every Chart.yaml dependency actually resolved and bundled
    into chart_dir/charts/ — skipping the (always slow — Helm re-fetches
    every single dependency unconditionally, never just the changed ones;
    see vendored_state_matches_chart_yaml's own docstring) `helm
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
    if vendored_state_matches_chart_yaml(chart_dir):
        print(
            "Chart.lock already matches Chart.yaml and every dependency is vendored — skipping helm dependency update"
        )
    else:
        retry_attempts = dependency_fetch_retry_attempts(chart_dir)
        retry_backoff_seconds = dependency_fetch_retry_backoff_seconds(chart_dir)

        shutil.rmtree(chart_dir / "charts", ignore_errors=True)
        (chart_dir / "Chart.lock").unlink(missing_ok=True)

        result = None
        for attempt in range(1, retry_attempts + 1):
            print(f"Running helm dependency update (attempt {attempt}/{retry_attempts})...")
            sys.stdout.flush()
            result = run(["helm", "dependency", "update", str(chart_dir)])
            if result.returncode == 0:
                break

            if attempt < retry_attempts:
                delay = retry_backoff_seconds[attempt - 1]
                print(f"helm dependency update failed (attempt {attempt}/{retry_attempts}), retrying in {delay}s...")
                time.sleep(delay)

        if result.returncode != 0:
            return False, f"helm dependency update failed after {retry_attempts} attempt(s)"

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
