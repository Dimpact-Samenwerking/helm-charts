"""Fast reachability/authorization preflight for every repo Chart.yaml's
dependencies and values.yaml's pinned images (scan_image_pins) need.

Runs before "Dependencies"/"Image digests", which are far slower. Successes
are cached briefly (lib.repo_access_cache) to avoid Docker Hub's anonymous
pull-rate limit on repeated runs; failures are never cached."""

import re

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Literal
from typing import NamedTuple
from typing import TypedDict
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.request import urlopen

from lib.chart.chart_yaml import chart_dir_dependencies
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.repo_and_path_resolution import subchart_needs_vendoring
from lib.chart.values_tree_primitives import values_key_of
from lib.image.digests import ImagePin
from lib.image.digests import cached_tag_exists
from lib.image.digests import distinct_lines
from lib.image.digests import image_targets
from lib.image.digests import scan_image_pins
from lib.image.digests import tag_digest_lookup
from lib.registry import parse_repo
from lib.render_scope import resolve_dependency_repo
from lib.repo_access_cache import cache_entry_is_fresh
from lib.repo_access_cache import cache_key
from lib.repo_access_cache import load_cache
from lib.repo_access_cache import save_cache
from lib.settings import helm_repos_urls_by_alias
from lib.settings import repo_access_cache_ttl_minutes
from lib.settings import repo_access_no_probe_suffixes
from lib.settings import repo_access_timeout_seconds


def is_denylisted_host(host: str, denylisted_host_suffixes: tuple[str, ...]):
    """True when `host` ends with a denylisted suffix.

    Private registries (e.g. an env-specific ACR mirror) belong in each
    environment's podiumd.yml override, never in this chart's defaults."""
    return any(host.endswith(suffix) for suffix in denylisted_host_suffixes)


# Recovers a dependency's source line; PyYAML safe_load doesn't track lines.
DEP_NAME_RE = re.compile(r'^\s*-\s*name:\s*"?([\w.\-]+)"?\s*(?:#.*)?$')

# (host, repo_path, version) of a registry artifact.
type RegistryTarget = tuple[str, str, str]
# (target, values.yaml lines) of one pinned image — see image_repos.
type ImageRepoTarget = tuple[RegistryTarget, list[int]]


class DependencyRepo(NamedTuple):
    """A network-resolved Chart.yaml dependency; see dependency_repos."""

    name: str
    line: int | None
    kind: str
    target: str | RegistryTarget


class AccessEntry(NamedTuple):
    """One unique repo or image to probe; see _build_entries."""

    kind: str
    description: str
    test_kind: str
    target: str | RegistryTarget


# (kind, description, error) of an unreachable entry.
type AccessFailure = tuple[str, str, str | None]
# (kind, description, host) of an entry on a denylisted host.
type DeniedEntry = tuple[str, str, str]
type ProbeDenied = tuple[Literal["denied"], str, str, str]
type ProbeFailure = tuple[Literal["failure"], str, str, str | None]
type ProbeResult = ProbeDenied | ProbeFailure | tuple[Literal["ok"]]


class _ChartGroup(TypedDict):
    """The Chart.yaml dependencies sharing one (kind, target)."""

    names: list[str]
    lines: list[int]


def _dependency_line_numbers(chart_yaml_text: str) -> dict[str, int]:
    """name -> 1-indexed line number of its "- name: <name>" entry."""
    line_numbers: dict[str, int] = {}
    for line_number, line in enumerate(chart_yaml_text.splitlines(), start=1):
        name_match = DEP_NAME_RE.match(line)
        if name_match:
            line_numbers[name_match.group(1)] = line_number
    return line_numbers


def dependency_repos(chart_dir: Path) -> list[DependencyRepo]:
    """(name, line, kind, target) for every network-resolved Chart.yaml dependency.

    kind "http": target is the base URL ("@alias" resolved). kind "oci":
    target is (host, repo_path, version), repo_path including the chart name
    as `helm dependency update` pulls it. line is None if not found.
    "file://" dependencies are omitted."""
    required_repos = helm_repos_urls_by_alias(chart_dir)
    chart_yaml_path = chart_dir / "Chart.yaml"
    deps = load_chart_dependencies(chart_yaml_path)
    line_numbers = _dependency_line_numbers(chart_yaml_path.read_text(encoding="utf-8"))
    repos: list[DependencyRepo] = []
    for dep in deps:
        repository = resolve_dependency_repo(dep.get("repository", ""), required_repos)
        name = values_key_of(dep)
        line = line_numbers.get(dep["name"])
        if repository.startswith("file://"):
            continue
        if repository.startswith("oci://"):
            host, _, oci_path = repository[len("oci://") :].partition("/")
            repo_path = f"{oci_path}/{dep['name']}" if oci_path else dep["name"]
            repos.append(DependencyRepo(name, line, "oci", (host, repo_path, dep["version"])))
        else:
            repos.append(DependencyRepo(name, line, "http", repository))
    return repos


def image_repos(values_path: Path) -> tuple[list[ImageRepoTarget], list[ImagePin]]:
    """([(target, lines) per unique (host, repo_path, version) pinned image], unresolved pins) of values.yaml.

    A pin whose repository is only in a subchart's default is unresolved
    while charts/*.tgz isn't vendored yet: "Dependencies" populates it later.
    """
    pins = scan_image_pins(values_path.parent)
    targets = image_targets(pins)
    resolved = [
        ((*parse_repo(repository), version), distinct_lines(group)) for (repository, version), group in targets.items()
    ]
    return resolved, [pin for pin in pins if not pin["repository"]]


def _report_unresolved(chart_dir: Path, unresolved: list[ImagePin]) -> None:
    """Print the pins this step cannot check, and why, so a skip is never silent."""
    if not unresolved:
        return
    deps = chart_dir_dependencies(chart_dir)
    print(f"Not checked: {len(unresolved)} pin(s) without a known repository:")
    for pin in unresolved:
        reason = (
            "its subchart is not vendored yet (Dependencies runs later)"
            if subchart_needs_vendoring(chart_dir, deps, pin["path"])
            else "no repository found"
        )
        print(f"  {'.'.join(pin['path'])} (values.yaml:{pin['line']}): {reason}")


def check_http_repo(url: str, timeout_seconds: float):
    """Fetch a classic Helm repo's index.yaml to prove reachability/auth."""
    index_url = urljoin(url if url.endswith("/") else f"{url}/", "index.yaml")
    try:
        # index_url comes from trusted config, never an attacker-controlled scheme.
        with urlopen(index_url, timeout=timeout_seconds):  # nosec B310
            return True, None
    except HTTPError as error:
        return False, f"HTTP {error.code} fetching {index_url}"
    except (URLError, OSError) as error:
        return False, f"{getattr(error, 'reason', error)} fetching {index_url}"


def check_registry_repo(chart_dir: Path, host: str, repo_path: str, version: str, timeout_seconds: float):
    """Manifest-existence check for an OCI chart or image.

    Shares cached_tag_exists's disk cache with the image digest checks, so a
    pin resolved by either is not fetched twice. One attempt: `timeout_seconds`
    already bounds each probe of an unreachable host."""
    _digest, error = tag_digest_lookup(
        lambda: cached_tag_exists(chart_dir, f"{host}/{repo_path}", version, timeout=timeout_seconds), attempts=1
    )
    return error is None, error


def _host_of(test_kind: str, target: str | tuple[str, ...]):
    """Hostname of an entry's target (URL for "http", tuple for "registry")."""
    if test_kind == "http" and isinstance(target, str):
        return urlparse(target).hostname or ""
    return target[0]


@dataclass
class ProbeConfig:
    """Settings shared by every _probe_entry call."""

    chart_dir: Path
    denylisted_host_suffixes: tuple[str, ...]
    cache_ttl_minutes: float
    timeout_seconds: float


def _build_entries(chart_deps: list[DependencyRepo], img_targets: list[ImageRepoTarget]) -> list[AccessEntry]:
    """(kind, description, test_kind, target) per unique repo/image to probe.

    Chart dependencies sharing one repo are grouped so each is tested once."""
    grouped_chart: dict[tuple[str, str | RegistryTarget], _ChartGroup] = {}
    for dep_repo in chart_deps:
        info = grouped_chart.setdefault((dep_repo.kind, dep_repo.target), {"names": [], "lines": []})
        info["names"].append(dep_repo.name)
        if dep_repo.line:
            info["lines"].append(dep_repo.line)
    entries = [_chart_entry(kind, target, info) for (kind, target), info in grouped_chart.items()]
    for target, lines in img_targets:
        host, repo_path, version = target
        endpoint = f"{host}/{repo_path}:{version}"
        location = f"values.yaml:{_joined_line_numbers(lines)}"
        entries.append(AccessEntry("image", f"{endpoint}  ({location})", "registry", target))
    return entries


def _chart_entry(kind: str, target: str | RegistryTarget, info: _ChartGroup) -> AccessEntry:
    """The AccessEntry of the Chart.yaml dependencies sharing one (kind, target)."""
    location = "Chart.yaml"
    if info["lines"]:
        location = f"{location}:{_joined_line_numbers(info['lines'])}"
    if isinstance(target, str):
        endpoint = target
    else:
        host, repo_path, version = target
        endpoint = f"oci://{host}/{repo_path}:{version}"
    names = ", ".join(info["names"])
    return AccessEntry("chart", f"{endpoint}  ({names} — {location})", kind, target)


def _joined_line_numbers(lines: list[int]) -> str:
    return ",".join(str(line_number) for line_number in sorted(lines))


def _probe_entry(config: ProbeConfig, entry: AccessEntry) -> ProbeResult:
    """Probe one entry (denylist, cache, then live check) and print its result.

    Returns ("denied", kind, description, host), ("failure", kind,
    description, error), or ("ok",)."""
    kind, description = entry.kind, entry.description
    test_kind, target = entry.test_kind, entry.target
    host = _host_of(test_kind, target)
    if is_denylisted_host(host, config.denylisted_host_suffixes):
        print(
            f"  [DENIED] {kind:5}  {description}  — {host} may not be used: this chart's own "
            f"tracked defaults must not reference this registry directly (see "
            f"repo_access.never_probe_host_suffixes in lib.settings) — an environment-specific "
            f"mirror override belongs in that environment's own podiumd.yml, not here"
        )
        return "denied", kind, description, host

    # Reload per entry: cached_tag_exists writes this same file mid-loop, so a
    # single up-front snapshot saved at the end would clobber those writes.
    cache = load_cache(config.chart_dir)
    key = cache_key(test_kind, target)
    cache_entry = cache.get(key)
    if cache_entry and cache_entry_is_fresh(cache_entry, config.cache_ttl_minutes):
        print(f"  [OK] {kind:5}  {description}  (cached)")
        return ("ok",)

    if isinstance(target, str):
        ok, error = check_http_repo(target, config.timeout_seconds)
    else:
        host, repo_path, version = target
        ok, error = check_registry_repo(config.chart_dir, host, repo_path, version, config.timeout_seconds)
    status = "OK" if ok else "FAIL"
    error_suffix = f"  — {error}" if error else ""
    print(f"  [{status}] {kind:5}  {description}{error_suffix}")
    if not ok:
        return "failure", kind, description, error
    if test_kind == "http":
        cache[key] = {"checked_at": datetime.now(UTC).isoformat()}
        save_cache(config.chart_dir, cache)
    return ("ok",)


def _format_result(
    checked: int, total_refs: int, failures: list[AccessFailure], denied: list[DeniedEntry]
) -> tuple[bool, str]:
    """(ok, message) summarizing failures and denied entries, or a success count."""
    if not (failures or denied):
        return True, f"{checked} repo(s)/image(s) reachable ({total_refs} references)"
    parts: list[str] = []
    if failures:
        parts.append(
            f"{len(failures)}/{checked} repo(s)/image(s) unreachable or unauthorized — "
            + "; ".join(f"{kind} {description}: {error}" for kind, description, error in failures)
        )
    if denied:
        parts.append(
            f"{len(denied)} repo(s)/image(s) may not be used (denylisted host) — "
            + "; ".join(f"{kind} {description} ({host})" for kind, description, host in denied)
        )
    return False, " | ".join(parts)


def check_repo_access(chart_dir: Path):
    """Return (ok, message): fail if any Chart.yaml repo or values.yaml pin registry is unreachable/unauthorized.

    Each unique repo/image is tested once. A host on
    repo_access.never_probe_host_suffixes fails without probing. Only http
    entries write the cache here; registry entries are cached by
    cached_tag_exists."""
    config = ProbeConfig(
        chart_dir,
        repo_access_no_probe_suffixes(chart_dir),
        repo_access_cache_ttl_minutes(chart_dir),
        repo_access_timeout_seconds(chart_dir),
    )

    chart_deps = dependency_repos(chart_dir)
    values_path = chart_dir / "values.yaml"
    img_targets, unresolved = image_repos(values_path) if values_path.is_file() else ([], [])
    _report_unresolved(chart_dir, unresolved)
    entries = _build_entries(chart_deps, img_targets)

    total_refs = len(chart_deps) + sum(len(lines) for _, lines in img_targets)
    print(
        f"Checking access to {len(entries)} unique repo(s)/image(s) for {total_refs} network-resolved reference(s)..."
    )

    failures: list[AccessFailure] = []
    denied: list[DeniedEntry] = []
    for entry in entries:
        result = _probe_entry(config, entry)
        if result[0] == "denied":
            denied.append(result[1:])
        elif result[0] == "failure":
            failures.append(result[1:])

    checked = len(entries) - len(denied)
    return _format_result(checked, total_refs, failures, denied)
