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

Re-vendoring fetches as little as it can (update_vendored_dependencies):
nothing when charts/ + Chart.lock already match Chart.yaml, only the
changed dependencies when it can (update_changed_dependencies, with
lib.chart_lock writing the same Chart.lock Helm would), and a full `helm
dependency update` otherwise.

vendored_dependency_problems is the purely local "is charts/ + Chart.lock
still what Chart.yaml asks for?" check behind all of that, and
ensure_vendored_dependencies the guard every script that renders the
chart or reads its vendored .tgz calls first: it re-vendors a stale state
on the spot (see there for why that one does exit when it can't)."""

import contextlib
import re
import shutil
import sys
import tempfile
import time

from pathlib import Path
from typing import TextIO
from typing import Unpack

import yaml

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import parse_chart_dependencies
from lib.chart_lock import ChartLockDependency
from lib.chart_lock import parse_chart_lock_dependencies
from lib.chart_lock import resolved_repository
from lib.chart_lock import write_chart_lock
from lib.checks.vendored_tgz import TGZ_NAME_RE
from lib.procutil import RunOptions
from lib.procutil import run
from lib.settings import dependency_fetch_retry_attempts
from lib.settings import dependency_fetch_retry_backoff_seconds
from lib.settings import helm_repos_urls_by_alias
from lib.yaml_types import YamlShapeError

# An exact (semver) version, as opposed to a range like "~1.2" or ">=1".
_EXACT_VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def _dependency_key(dep: ChartDependency | ChartLockDependency, required_repos: dict[str, str]) -> tuple[str, str, str]:
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
    return dep.get("name"), str(dep.get("version")), resolved_repository(dep, required_repos)


def _lock_problems(chart_dir: Path, chart_deps: list[ChartDependency]):
    """Every way chart_dir/Chart.lock disagrees with Chart.yaml's current
    `chart_deps` — [] when the lock lists exactly the same (name, version,
    repository) triples (see _dependency_key). One entry per affected
    dependency, naming both sides where it can, e.g. "kiss-chart:
    Chart.yaml wants 3.1.1, Chart.lock has 3.0.0"."""
    lock_path = chart_dir / "Chart.lock"
    if not lock_path.is_file():
        return ["Chart.lock is missing"]
    try:
        lock_deps = parse_chart_lock_dependencies(lock_path.read_text(encoding="utf-8"), "Chart.lock") or []
    except yaml.YAMLError:
        return ["Chart.lock is not valid YAML"]
    except YamlShapeError as e:
        return [str(e)]

    required_repos = helm_repos_urls_by_alias(chart_dir)
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


def _describe_lock_mismatch(wanted_key: tuple[str, str, str], locked: set[tuple[str, str, str]]):
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


def _tgz_problems(chart_dir: Path, chart_deps: list[ChartDependency]):
    """One entry per Chart.yaml dependency whose charts/<name>-<version>.tgz
    isn't vendored, naming whatever other version of it charts/ has
    instead (parsed with lib.checks.vendored_tgz.TGZ_NAME_RE, the same
    <name>-<version>.tgz split that check already uses)."""
    charts_dir = chart_dir / "charts"
    vendored: dict[str, list[str]] = {}
    if charts_dir.is_dir():
        for path in charts_dir.glob("*.tgz"):
            match = TGZ_NAME_RE.match(path.name)
            if match:
                vendored.setdefault(match["name"], []).append(match["version"])

    problems: list[str] = []
    for name, version in sorted({(d.get("name"), str(d.get("version"))) for d in chart_deps}):
        if (charts_dir / f"{name}-{version}.tgz").is_file():
            continue
        others = sorted(vendored.get(name, []))
        if others:
            problems.append(f"{name}: Chart.yaml wants {version}, charts/ has {', '.join(others)}")
        else:
            problems.append(f"{name}: charts/{name}-{version}.tgz is missing")
    return problems


def _dependency_state(chart_dir: Path) -> tuple[list[ChartDependency], list[str]]:
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
        chart_deps = parse_chart_dependencies(chart_yaml_path.read_text(encoding="utf-8"), "Chart.yaml")
    except yaml.YAMLError:
        return [], ["Chart.yaml is not valid YAML"]
    except YamlShapeError as e:
        return [], [str(e)]
    if not chart_deps:
        return [], []
    return chart_deps, _lock_problems(chart_dir, chart_deps) + _tgz_problems(chart_dir, chart_deps)


def vendored_dependency_problems(chart_dir: Path):
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
    ensure_vendored_dependencies for the scripts' own guard built on
    this."""
    return _dependency_state(chart_dir)[1]


def vendored_state_matches_chart_yaml(chart_dir: Path):
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


def ensure_vendored_dependencies(chart_dir: Path):
    """Guard for scripts that render chart_dir or read its vendored
    charts/*.tgz / Chart.lock: when those don't match Chart.yaml, names
    every stale or missing dependency and re-vendors them right away (see
    update_vendored_dependencies — only the changed ones where it can),
    instead of letting a later render fail on an unrelated-looking
    sub-chart schema error. Raises SystemExit (exit 1, the message on
    stderr) only when that re-vendor fails or still leaves a mismatch,
    naming what's left and the manual `helm dependency update` fallback.

    All progress goes to stderr, so a script's own stdout (a report, an
    image list) is exactly what it would be on an in-sync checkout.

    The module's one exit-deciding function, on purpose: it is only ever
    called from a script's own main(), never from another lib function,
    so the "should this process exit?" policy still belongs to each
    script — this just keeps the messages and exit code identical across
    all of them. Scripts that re-vendor as a step of their own (verify-
    podiumd's "Dependencies" step, fix-image-digests) call
    check_dependencies instead."""
    problems = vendored_dependency_problems(chart_dir)
    if not problems:
        return
    shown = chart_dir
    with contextlib.suppress(ValueError):
        shown = chart_dir.resolve().relative_to(Path.cwd())
    details = "\n".join(f"  - {problem}" for problem in problems)
    print(f"{shown}/charts/ and Chart.lock do not match Chart.yaml, re-vendoring:\n{details}", file=sys.stderr)

    ok, detail = ensure_repos_configured(chart_dir)
    if ok:
        ok, detail = update_vendored_dependencies(chart_dir, out=sys.stderr)
    remaining = vendored_dependency_problems(chart_dir)
    if ok and not remaining:
        return
    reason = detail if not ok else "re-vendored, but still out of sync"
    details = "".join(f"\n  - {problem}" for problem in remaining)
    message = f"error: could not re-vendor {shown}/charts/ ({reason}){details}\nRun: helm dependency update {shown}"
    raise SystemExit(message)


def ensure_repos_configured(chart_dir: Path):
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


def _output_stream(out: TextIO | None) -> TextIO:
    """`out`, or the current sys.stdout when it is None."""
    return sys.stdout if out is None else out


def _run_with_retries(chart_dir: Path, cmd: list[str], label: str, out: TextIO, **run_kwargs: Unpack[RunOptions]):
    """run(cmd, **run_kwargs), retried per settings.yaml dependency_fetch
    (transient network blips, registry throttling), announcing each
    attempt on `out` as "Running <label> (attempt n/N)...". Flushes `out`
    before each attempt so an earlier, still-buffered print can't end up
    AFTER output a live-streamed child already wrote to the same fd (same
    reason lib.procutil.run_script flushes). Returns the last result."""
    retry_attempts = dependency_fetch_retry_attempts(chart_dir)
    retry_backoff_seconds = dependency_fetch_retry_backoff_seconds(chart_dir)
    result = None
    for attempt in range(1, retry_attempts + 1):
        print(f"Running {label} (attempt {attempt}/{retry_attempts})...", file=out)
        out.flush()
        result = run(cmd, **run_kwargs)
        if result.returncode == 0:
            break
        if attempt < retry_attempts:
            delay = retry_backoff_seconds[attempt - 1]
            print(f"{label} failed (attempt {attempt}/{retry_attempts}), retrying in {delay}s...", file=out)
            time.sleep(delay)
    if result is None:
        msg = f"error: settings.yaml dependency_fetch.retry_attempts must be at least 1, got {retry_attempts}"
        raise SystemExit(msg)
    return result


def _usable_lock_dependencies(chart_dir: Path):
    """Chart.lock's own dependency list, or None when there's no lock to
    update in place (missing, not valid YAML, no dependency list)."""
    lock_path = chart_dir / "Chart.lock"
    if not lock_path.is_file():
        return None
    try:
        return parse_chart_lock_dependencies(lock_path.read_text(encoding="utf-8"), "Chart.lock")
    except (yaml.YAMLError, YamlShapeError):
        return None


def _changed_dependencies(
    chart_dir: Path,
    chart_deps: list[ChartDependency],
    lock_deps: list[ChartLockDependency],
    required_repos: dict[str, str],
):
    """The Chart.yaml dependencies update_changed_dependencies must fetch:
    those whose (name, version, repository) Chart.lock doesn't list (see
    _dependency_key), or whose charts/<name>-<version>.tgz is missing.
    One entry per (name, version, repository), so the same chart listed
    twice under two aliases is fetched once."""
    locked = {_dependency_key(dep, required_repos) for dep in lock_deps}
    changed: dict[tuple[str, str, str], ChartDependency] = {}
    for dep in chart_deps:
        key = _dependency_key(dep, required_repos)
        tgz = chart_dir / "charts" / f"{key[0]}-{key[1]}.tgz"
        if key not in locked or not tgz.is_file():
            changed.setdefault(key, dep)
    return list(changed.values())


def _fetch_command(chart_dir: Path, dep: ChartDependency, required_repos: dict[str, str], dest: Path):
    """The helm command that writes dep's <name>-<version>.tgz into
    `dest`, the same source `helm dependency update` would use: `helm
    package` for a file:// chart, `helm pull` straight from the oci://
    reference or (with --repo, so no `helm repo add`/index refresh of
    the local repo cache is needed) the plain repository URL. None for
    an "@alias" settings.yaml helm_repos.urls_by_alias doesn't know."""
    name, version = str(dep.get("name")), str(dep.get("version"))
    repo = resolved_repository(dep, required_repos)
    if repo.startswith("file://"):
        source = (chart_dir / repo.removeprefix("file://")).resolve()
        return ["helm", "package", str(source), "--destination", str(dest)]
    if repo.startswith("oci://"):
        return ["helm", "pull", f"{repo.rstrip('/')}/{name}", "--version", version, "--destination", str(dest)]
    if repo.startswith("@"):
        return None
    return ["helm", "pull", name, "--repo", repo, "--version", version, "--destination", str(dest)]


def _fetch_dependency(chart_dir: Path, dep: ChartDependency, required_repos: dict[str, str], dest: Path, out: TextIO):
    """Fetches one dependency's .tgz into `dest` (see _fetch_command),
    retried like the full update. (ok, reason-if-not)."""
    name, version = dep.get("name"), str(dep.get("version"))
    cmd = _fetch_command(chart_dir, dep, required_repos, dest)
    if cmd is None:
        return False, f"{name}: repository {dep.get('repository')} is not in settings.yaml helm_repos.urls_by_alias"
    label = f"{' '.join(cmd[:2])} {name} {version}"
    result = _run_with_retries(chart_dir, cmd, label, out, capture_output=True, text=True)
    if result.returncode != 0:
        return False, f"{label} failed: {(result.stderr or '').strip()}"
    if not (dest / f"{name}-{version}.tgz").is_file():
        return False, f"{label} did not produce {name}-{version}.tgz"
    return True, ""


def _replace_vendored_tgz(chart_dir: Path, chart_deps: list[ChartDependency], fetched_dir: Path):
    """Drops every charts/<name>-<version>.tgz Chart.yaml no longer asks
    for (what `helm dependency update` does too), then moves the freshly
    fetched ones in. Extracted charts/<name>/ directories are left alone
    (fix-vendored-tgz's job)."""
    charts_dir = chart_dir / "charts"
    charts_dir.mkdir(exist_ok=True)
    wanted = {f"{dep.get('name')}-{dep.get('version')}.tgz" for dep in chart_deps}
    for path in charts_dir.glob("*.tgz"):
        if path.name not in wanted and TGZ_NAME_RE.match(path.name):
            path.unlink()
    for path in fetched_dir.glob("*.tgz"):
        shutil.move(str(path), str(charts_dir / path.name))


def update_changed_dependencies(chart_dir: Path, out: TextIO | None = None):
    """Re-vendors only the Chart.yaml dependencies that changed (see
    _changed_dependencies) instead of all of them: fetches each one into
    a temp dir, and only once every fetch succeeded drops the charts/*.tgz
    Chart.yaml no longer asks for, moves the new ones in, and rewrites
    Chart.lock (lib.chart_lock.write_chart_lock — the same content and
    digest Helm itself would write). charts/ and Chart.lock stay
    untouched on any failure.

    (False, reason) when this doesn't apply — no Chart.lock to update in
    place, or a version range (only Helm's own repo index lookup
    resolves one) — or a fetch failed; update_vendored_dependencies then
    falls back to a full `helm dependency update`. Progress goes to
    `out` (default: stdout)."""
    out = _output_stream(out)
    chart_deps, _problems = _dependency_state(chart_dir)
    if not chart_deps:
        return False, "Chart.yaml has no dependencies"
    lock_deps = _usable_lock_dependencies(chart_dir)
    if lock_deps is None:
        return False, "no usable Chart.lock to update"
    ranged = sorted(dep.get("name") for dep in chart_deps if not _EXACT_VERSION_RE.match(str(dep.get("version"))))
    if ranged:
        return False, f"version range for {', '.join(ranged)}"

    required_repos = helm_repos_urls_by_alias(chart_dir)
    changed = _changed_dependencies(chart_dir, chart_deps, lock_deps, required_repos)
    with tempfile.TemporaryDirectory(prefix="podiumd-dependencies-") as tmp:
        fetched_dir = Path(tmp)
        for dep in changed:
            ok, reason = _fetch_dependency(chart_dir, dep, required_repos, fetched_dir, out)
            if not ok:
                return False, reason
        _replace_vendored_tgz(chart_dir, chart_deps, fetched_dir)
    write_chart_lock(chart_dir, chart_deps, required_repos)
    fetched = ", ".join(f"{dep.get('name')} {dep.get('version')}" for dep in changed) or "none, Chart.lock only"
    return True, f"fetched {len(changed)} of {len(chart_deps)} dependencies ({fetched})"


def _full_dependency_update(chart_dir: Path, out: TextIO):
    """Rebuilds chart_dir/charts/ from scratch (rm -rf + `helm dependency
    update`), retried a few times on failure.

    Deliberately does NOT capture_output= the update call, unlike every
    other `run(...)` here: `helm dependency update` re-downloads every
    single dependency (see vendored_state_matches_chart_yaml) and prints
    its own per-dependency "Downloading X from repo Y" progress as it
    goes — capturing it would buffer that away until the whole (often
    tens-of-seconds) update finishes, making this step look hung the
    entire time. The subprocess writes straight to `out` instead, live,
    interleaved with this module's own prints."""
    shutil.rmtree(chart_dir / "charts", ignore_errors=True)
    (chart_dir / "Chart.lock").unlink(missing_ok=True)
    cmd = ["helm", "dependency", "update", str(chart_dir)]
    result = _run_with_retries(chart_dir, cmd, "helm dependency update", out, text=True, stdout=out)
    if result.returncode != 0:
        attempts = dependency_fetch_retry_attempts(chart_dir)
        return False, f"helm dependency update failed after {attempts} attempt(s)"
    return True, "full helm dependency update"


def update_vendored_dependencies(chart_dir: Path, out: TextIO | None = None):
    """Brings chart_dir/charts/ + Chart.lock in line with Chart.yaml,
    fetching as little as possible: nothing when they already match (see
    vendored_state_matches_chart_yaml), only the changed dependencies
    when update_changed_dependencies can (seconds, instead of the ~80s a
    full re-fetch of all 25 takes), and a full `helm dependency update`
    otherwise. The full fallback resolves "@alias" repositories through
    the local repo config, so ensure_repos_configured must have run
    first. Progress goes to `out` (default: stdout). Returns (ok,
    detail)."""
    out = _output_stream(out)
    if vendored_state_matches_chart_yaml(chart_dir):
        print(
            "Chart.lock already matches Chart.yaml and every dependency is vendored — skipping helm dependency update",
            file=out,
        )
        return True, "already vendored"
    ok, detail = update_changed_dependencies(chart_dir, out)
    if ok:
        print(f"Re-vendored only what changed: {detail}", file=out)
        return True, detail
    print(f"Cannot re-vendor only what changed ({detail}) — falling back to a full helm dependency update", file=out)
    return _full_dependency_update(chart_dir, out)


def check_dependencies(chart_dir: Path):
    """Confirms every Chart.yaml dependency actually resolved and bundled
    into chart_dir/charts/, re-vendoring first as little as needed (see
    update_vendored_dependencies: nothing, only what changed, or a full
    `helm dependency update`).

    The `helm dependency list` verification below always runs regardless
    of which path was taken above — cheap (no network, purely local) and
    the one thing that actually proves the vendored state resolves
    correctly, so skipping the expensive re-download step never skips
    that guarantee too."""
    ok, detail = update_vendored_dependencies(chart_dir)
    if not ok:
        return False, detail

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
