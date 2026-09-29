"""Vendor Chart.yaml dependencies into charts/*.tgz and check that the vendored
state (charts/ + Chart.lock, both gitignored) still matches Chart.yaml.

Functions return (ok, detail) and leave exiting to the caller, except
ensure_vendored_dependencies, the shared guard scripts call from main()."""

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
    """(name, version, repository) identity shared by Chart.yaml and Chart.lock entries.

    version is str()'d: YAML parses "version: 26" as an int, Chart.lock quotes it.
    repository is resolved through `required_repos`, since Chart.lock stores the
    URL behind an "@alias", never the alias itself."""
    return dep.get("name"), str(dep.get("version")), resolved_repository(dep, required_repos)


def _lock_problems(chart_dir: Path, chart_deps: list[ChartDependency]):
    """Every way Chart.lock disagrees with `chart_deps`, one entry per dependency; [] when in sync."""
    lock_path = chart_dir / "Chart.lock"
    if not lock_path.is_file():
        return ["Chart.lock is missing"]
    try:
        lock_deps = parse_chart_lock_dependencies(lock_path.read_text(encoding="utf-8"), "Chart.lock") or []
    except (OSError, UnicodeDecodeError) as e:
        return [f"Chart.lock can not be read: {e}"]
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
    """Describe a Chart.yaml triple missing from Chart.lock: other repository, other version, or absent."""
    name, version, repo = wanted_key
    same_name = sorted(k for k in locked if k[0] == name)
    same_version_repos = sorted({k[2] for k in same_name if k[1] == version})
    if same_version_repos:
        return f"{name}: Chart.yaml wants repository {repo}, Chart.lock has {', '.join(same_version_repos)}"
    if same_name:
        return f"{name}: Chart.yaml wants {version}, Chart.lock has {', '.join(k[1] for k in same_name)}"
    return f"{name}: missing from Chart.lock"


def _tgz_problems(chart_dir: Path, chart_deps: list[ChartDependency]):
    """One entry per dependency whose charts/<name>-<version>.tgz is missing, naming other vendored versions."""
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
    """(chart_deps, problems) for chart_dir; the single implementation behind both public checks."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    if not chart_yaml_path.is_file():
        return [], ["Chart.yaml is missing"]
    try:
        chart_deps = parse_chart_dependencies(chart_yaml_path.read_text(encoding="utf-8"), "Chart.yaml")
    except (OSError, UnicodeDecodeError) as e:
        return [], [f"Chart.yaml can not be read: {e}"]
    except yaml.YAMLError:
        return [], ["Chart.yaml is not valid YAML"]
    except YamlShapeError as e:
        return [], [str(e)]
    if not chart_deps:
        return [], []
    return chart_deps, _lock_problems(chart_dir, chart_deps) + _tgz_problems(chart_dir, chart_deps)


def vendored_dependency_problems(chart_dir: Path):
    """Every reason chart_dir's Chart.lock + charts/*.tgz don't match its current Chart.yaml.

    [] when in sync or Chart.yaml has no dependencies. Local only, no helm call.
    A stale state otherwise surfaces as an unrelated sub-chart schema error in
    `helm template`, and vendored-.tgz lookups silently return None."""
    return _dependency_state(chart_dir)[1]


def vendored_state_matches_chart_yaml(chart_dir: Path):
    """True when Chart.lock and charts/*.tgz already match Chart.yaml, so re-vendoring can be skipped.

    Worth checking because `helm dependency update` always re-fetches every
    dependency (~80s). False, never raising, for any untrustworthy state or a
    Chart.yaml without dependencies."""
    chart_deps, problems = _dependency_state(chart_dir)
    return bool(chart_deps) and not problems


def ensure_vendored_dependencies(chart_dir: Path):
    """Re-vendor chart_dir when its vendored state doesn't match Chart.yaml, listing what is stale.

    Progress goes to stderr so the script's stdout is unaffected. Raises
    SystemExit(1) when re-vendoring fails or leaves a mismatch. Call only from a
    script's main(); steps that re-vendor themselves use check_dependencies."""
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
    """`helm repo add` every repo Chart.yaml references by "@alias", then update just those.

    A bare `helm repo update` would also refresh unrelated locally configured
    repos (~6s vs ~0.6s)."""
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
    """run(cmd), retried per settings.yaml dependency_fetch; returns the last result.

    Flushes `out` before each attempt so buffered prints can't land after output
    a live-streamed child already wrote to the same fd."""
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
    """Chart.lock's dependency list, or None when there is no usable lock to update in place."""
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
    """Dependencies Chart.lock doesn't list or whose .tgz is missing, deduplicated by (name, version, repository)."""
    locked = {_dependency_key(dep, required_repos) for dep in lock_deps}
    changed: dict[tuple[str, str, str], ChartDependency] = {}
    for dep in chart_deps:
        key = _dependency_key(dep, required_repos)
        tgz = chart_dir / "charts" / f"{key[0]}-{key[1]}.tgz"
        if key not in locked or not tgz.is_file():
            changed.setdefault(key, dep)
    return list(changed.values())


def _fetch_command(chart_dir: Path, dep: ChartDependency, required_repos: dict[str, str], dest: Path):
    """The helm command that writes dep's .tgz into `dest`, from the same source `helm dependency update` uses.

    `helm pull --repo` avoids needing `helm repo add`. None for an "@alias"
    missing from settings.yaml helm_repos.urls_by_alias."""
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
    """Fetch one dependency's .tgz into `dest` with retries; (ok, reason-if-not)."""
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
    """Delete charts/*.tgz Chart.yaml no longer wants, then move the fetched ones in.

    Extracted charts/<name>/ directories are left to fix-vendored-tgz."""
    charts_dir = chart_dir / "charts"
    charts_dir.mkdir(exist_ok=True)
    wanted = {f"{dep.get('name')}-{dep.get('version')}.tgz" for dep in chart_deps}
    for path in charts_dir.glob("*.tgz"):
        if path.name not in wanted and TGZ_NAME_RE.match(path.name):
            path.unlink()
    for path in fetched_dir.glob("*.tgz"):
        shutil.move(str(path), str(charts_dir / path.name))


def update_changed_dependencies(chart_dir: Path, out: TextIO | None = None):
    """Re-vendor only changed dependencies and rewrite Chart.lock as Helm would.

    Everything is fetched into a temp dir first, so charts/ and Chart.lock stay
    untouched on failure. (False, reason) when there is no Chart.lock, a version
    range needs Helm's index lookup, or a fetch failed."""
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
    """Rebuild charts/ from scratch with `helm dependency update`, with retries.

    Output is not captured so Helm's per-dependency progress streams live;
    otherwise the long update looks hung."""
    shutil.rmtree(chart_dir / "charts", ignore_errors=True)
    (chart_dir / "Chart.lock").unlink(missing_ok=True)
    cmd = ["helm", "dependency", "update", str(chart_dir)]
    result = _run_with_retries(chart_dir, cmd, "helm dependency update", out, text=True, stdout=out)
    if result.returncode != 0:
        attempts = dependency_fetch_retry_attempts(chart_dir)
        return False, f"helm dependency update failed after {attempts} attempt(s)"
    return True, "full helm dependency update"


def update_vendored_dependencies(chart_dir: Path, out: TextIO | None = None):
    """Bring charts/ + Chart.lock in line with Chart.yaml, fetching as little as possible.

    Skips when already in sync, else tries update_changed_dependencies, else a
    full `helm dependency update` (which needs ensure_repos_configured first for
    "@alias" repositories). Returns (ok, detail)."""
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
    """Re-vendor as needed, then verify with `helm dependency list` that every dependency resolved.

    The verification always runs, so skipping the download never skips the check."""
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
