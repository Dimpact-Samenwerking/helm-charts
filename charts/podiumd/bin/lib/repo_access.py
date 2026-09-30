"""Fast reachability/authorization preflight for every repo Chart.yaml's
dependencies and values.yaml's digest-pinned images need.

Runs before "Dependencies"/"Image digests", which are far slower. Successes
are cached briefly (lib.repo_access_cache) to avoid Docker Hub's anonymous
pull-rate limit on repeated runs; failures are never cached."""

import re
import urllib.error
import urllib.parse
import urllib.request

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Literal
from typing import TypedDict

from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.values_tree_primitives import values_key_of
from lib.image.digests import cached_tag_exists
from lib.image.digests import scan_digest_pins
from lib.registry import parse_repo
from lib.render_scope import resolve_dependency_repo
from lib.repo_access_cache import cache_entry_is_fresh
from lib.repo_access_cache import cache_key
from lib.repo_access_cache import load_cache
from lib.repo_access_cache import save_cache
from lib.settings import helm_repos_urls_by_alias
from lib.settings import repo_access_cache_ttl_minutes
from lib.settings import repo_access_never_probe_host_suffixes
from lib.settings import repo_access_request_timeout_seconds


def is_denylisted_host(host: str, denylisted_host_suffixes: tuple[str, ...]):
    """True when `host` ends with a denylisted suffix.

    Private registries (e.g. an env-specific ACR mirror) belong in each
    environment's podiumd.yml override, never in this chart's defaults."""
    return any(host.endswith(suffix) for suffix in denylisted_host_suffixes)


# Recovers a dependency's source line; PyYAML safe_load doesn't track lines.
DEP_NAME_RE = re.compile(r'^\s*-\s*name:\s*"?([\w.\-]+)"?\s*(?:#.*)?$')

# (host, repo_path, version) of a registry artifact.
RegistryTarget = tuple[str, str, str]
# (name, line, kind, target) of a Chart.yaml dependency — see dependency_repos.
DependencyRepo = tuple[str, int | None, str, str | RegistryTarget]
# (kind, description, test_kind, target) — see _build_entries.
AccessEntry = tuple[str, str, str, str | RegistryTarget]
# (kind, description, error) of an unreachable entry.
AccessFailure = tuple[str, str, str | None]
# (kind, description, host) of an entry on a denylisted host.
DeniedEntry = tuple[str, str, str]
ProbeResult = (
    tuple[Literal["denied"], str, str, str] | tuple[Literal["failure"], str, str, str | None] | tuple[Literal["ok"]]
)


class _ChartGroup(TypedDict):
    """The Chart.yaml dependencies sharing one (kind, target)."""

    names: list[str]
    lines: list[int]


def _dependency_line_numbers(chart_yaml_text: str) -> dict[str, int]:
    """name -> 1-indexed line number of its "- name: <name>" entry."""
    return {
        m.group(1): i + 1 for i, line in enumerate(chart_yaml_text.splitlines()) for m in [DEP_NAME_RE.match(line)] if m
    }


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
            repos.append((name, line, "oci", (host, repo_path, dep["version"])))
        else:
            repos.append((name, line, "http", repository))
    return repos


def image_repos(values_path: Path) -> list[tuple[RegistryTarget, list[int]]]:
    """(target, lines) per unique (host, repo_path, version) digest pin in values.yaml.

    Pins without an explicit repository are skipped: resolving them needs
    charts/*.tgz, which "Dependencies" populates later."""
    pins = scan_digest_pins(values_path.read_text(encoding="utf-8").splitlines())
    grouped: dict[RegistryTarget, list[int]] = {}
    for p in pins:
        if not p["repository"]:
            continue
        target = (*parse_repo(p["repository"]), p["version"])
        grouped.setdefault(target, []).append(p["line"])
    return list(grouped.items())


def _check_http_repo(url: str, timeout_seconds: float):
    """Fetch a classic Helm repo's index.yaml to prove reachability/auth."""
    index_url = urllib.parse.urljoin(url if url.endswith("/") else url + "/", "index.yaml")
    try:
        # index_url comes from trusted config, never an attacker-controlled scheme.
        with urllib.request.urlopen(index_url, timeout=timeout_seconds):  # nosec B310
            pass
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} fetching {index_url}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"{getattr(e, 'reason', e)} fetching {index_url}"
    return True, None


def _check_registry_repo(chart_dir: Path, host: str, repo_path: str, version: str, timeout_seconds: float):
    """Manifest-existence check for an OCI chart or image.

    Shares cached_tag_exists's disk cache with the image digest checks, so a
    pin resolved by either is not fetched twice."""
    try:
        exists, _ = cached_tag_exists(chart_dir, f"{host}/{repo_path}", version, timeout=timeout_seconds)
    except (urllib.error.URLError, OSError) as e:
        return False, f"{getattr(e, 'reason', e)}"
    if not exists:
        return False, "not found"
    return True, None


def _host_of(test_kind: str, target: str | tuple[str, ...]):
    """Hostname of an entry's target (URL for "http", tuple for "registry")."""
    if test_kind == "http" and isinstance(target, str):
        return urllib.parse.urlparse(target).hostname or ""
    return target[0]


@dataclass
class ProbeConfig:
    """Settings shared by every _probe_entry call."""

    chart_dir: Path
    denylisted_host_suffixes: tuple[str, ...]
    cache_ttl_minutes: float
    timeout_seconds: float


def _build_entries(
    chart_deps: list[DependencyRepo], img_targets: list[tuple[RegistryTarget, list[int]]]
) -> list[AccessEntry]:
    """(kind, description, test_kind, target) per unique repo/image to probe.

    Chart dependencies sharing one repo are grouped so each is tested once."""
    entries: list[AccessEntry] = []
    grouped_chart: dict[tuple[str, str | RegistryTarget], _ChartGroup] = {}
    for name, line, kind, target in chart_deps:
        info = grouped_chart.setdefault((kind, target), {"names": [], "lines": []})
        info["names"].append(name)
        if line:
            info["lines"].append(line)
    for (kind, target), info in grouped_chart.items():
        location = "Chart.yaml"
        if info["lines"]:
            location += ":" + ",".join(str(n) for n in sorted(info["lines"]))
        if isinstance(target, str):
            endpoint = target
        else:
            host, repo_path, version = target
            endpoint = f"oci://{host}/{repo_path}:{version}"
        entries.append(("chart", f"{endpoint}  ({', '.join(info['names'])} — {location})", kind, target))

    for target, lines in img_targets:
        host, repo_path, version = target
        endpoint = f"{host}/{repo_path}:{version}"
        location = "values.yaml:" + ",".join(str(n) for n in sorted(lines))
        entries.append(("image", f"{endpoint}  ({location})", "registry", target))
    return entries


def _probe_entry(config: ProbeConfig, entry: AccessEntry) -> ProbeResult:
    """Probe one entry (denylist, cache, then live check) and print its result.

    Returns ("denied", kind, description, host), ("failure", kind,
    description, error), or ("ok",)."""
    kind, description, test_kind, target = entry
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
        ok, error = _check_http_repo(target, config.timeout_seconds)
    else:
        host, repo_path, version = target
        ok, error = _check_registry_repo(config.chart_dir, host, repo_path, version, config.timeout_seconds)
    print(f"  [{'OK' if ok else 'FAIL'}] {kind:5}  {description}" + (f"  — {error}" if error else ""))
    if not ok:
        return "failure", kind, description, error
    if test_kind == "http":
        cache[key] = {"checked_at": datetime.now(timezone.utc).isoformat()}
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
        repo_access_never_probe_host_suffixes(chart_dir),
        repo_access_cache_ttl_minutes(chart_dir),
        repo_access_request_timeout_seconds(chart_dir),
    )

    chart_deps = dependency_repos(chart_dir)
    values_path = chart_dir / "values.yaml"
    img_targets = image_repos(values_path) if values_path.is_file() else []
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
