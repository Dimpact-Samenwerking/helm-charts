"""Report-only check for a newer stable version of every Chart.yaml dependency chart.

Versions come from a classic repository's index.yaml or an OCI registry's
tag list; "file://" dependencies are skipped. Pre-releases ("-rc.1") never
count as newer. Results are cached per (repository, chart, version) in the
gitignored .cache/chart-upgrade-cache.json. Never fails on findings.
"""

import urllib.error
import urllib.request

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.values_tree_primitives import values_key_of
from lib.image.upgrade_cache import UpgradeEntry
from lib.image.upgrade_cache import cache_entry_is_fresh
from lib.image.upgrade_cache import is_upgrade_entry
from lib.json_cache import cache_file
from lib.json_cache import load_json_cache
from lib.json_cache import save_json_cache
from lib.registry import list_tags
from lib.render_scope import resolve_dependency_repo
from lib.settings import chart_upgrade_check_cache_ttl_days
from lib.settings import helm_repos_urls_by_alias
from lib.settings import repo_access_request_timeout_seconds
from lib.version_numbers import stable_semver_key
from lib.yaml_types import YamlShapeError
from lib.yaml_types import parse_yaml

CACHE_FILENAME = "chart-upgrade-cache.json"


def newest_stable_version(current: str, published: list[str]) -> str:
    """The highest stable version in `published` above `current`, else `current`."""
    best, best_key = current, stable_semver_key(current)
    if best_key is None:
        return current
    for version in published:
        key = stable_semver_key(version)
        if key is not None and key > best_key:
            best, best_key = version, key
    return best


def index_chart_versions(index_text: str, chart_name: str, source: str) -> list[str]:
    """The versions `chart_name` has in a Helm repository index.yaml."""
    index = parse_yaml(index_text, source)
    releases = index.get("entries") if isinstance(index, dict) else None
    chart_releases = releases.get(chart_name) if isinstance(releases, dict) else None
    if not isinstance(chart_releases, list):
        return []
    versions: list[str] = []
    for release in chart_releases:
        version = release.get("version") if isinstance(release, dict) else None
        if isinstance(version, str):
            versions.append(version)
    return versions


@dataclass(frozen=True)
class ChartSource:
    """Where one dependency's published versions are listed."""

    name: str
    chart: str
    version: str
    repository: str

    @property
    def cache_key(self) -> str:
        """The cache key, e.g. "https://example.org/charts/zac:1.0.297"."""
        return f"{self.repository}/{self.chart}:{self.version}"


def chart_sources(chart_dir: Path, deps: list[ChartDependency]) -> list[ChartSource]:
    """A ChartSource per network-resolved dependency, "@alias" resolved; "file://" ones left out."""
    repos_by_alias = helm_repos_urls_by_alias(chart_dir)
    sources: list[ChartSource] = []
    for dep in deps:
        repository = resolve_dependency_repo(dep.get("repository", ""), repos_by_alias)
        if repository and not repository.startswith("file://"):
            sources.append(ChartSource(values_key_of(dep), dep["name"], str(dep["version"]), repository.rstrip("/")))
    return sources


@dataclass
class _Fetcher:
    """Published versions per source; an index.yaml is downloaded once per repository."""

    timeout_seconds: float
    index_texts: dict[str, str] = field(default_factory=dict)

    def versions(self, source: ChartSource) -> list[str]:
        """All published versions of `source`'s chart."""
        if source.repository.startswith("oci://"):
            host, _, path = source.repository[len("oci://") :].partition("/")
            return list_tags(host, f"{path}/{source.chart}" if path else source.chart)
        if source.repository not in self.index_texts:
            index_url = f"{source.repository}/index.yaml"
            # index_url comes from Chart.yaml/settings.yaml, never an attacker-controlled scheme.
            with urllib.request.urlopen(index_url, timeout=self.timeout_seconds) as resp:  # nosec B310
                self.index_texts[source.repository] = resp.read().decode("utf-8")
        return index_chart_versions(self.index_texts[source.repository], source.chart, source.repository)


@dataclass
class ChartUpgradeScan:
    """newest version per checked source, sources that could not be checked, and cache hits."""

    newest: dict[ChartSource, str] = field(default_factory=dict)
    fetch_errors: list[ChartSource] = field(default_factory=list)
    cache_hits: int = 0


def _scan(chart_dir: Path, sources: list[ChartSource], ttl_days: int) -> ChartUpgradeScan:
    """Resolve every source from a fresh cache entry or the network; the saved cache drops unused entries."""
    cache_path = cache_file(chart_dir, CACHE_FILENAME)
    old_cache = load_json_cache(cache_path, is_upgrade_entry)
    new_cache: dict[str, UpgradeEntry] = {}
    fetcher = _Fetcher(repo_access_request_timeout_seconds(chart_dir))
    scan = ChartUpgradeScan()
    for i, source in enumerate(sources, 1):
        cached = old_cache.get(source.cache_key)
        if cached and cache_entry_is_fresh(cached, ttl_days):
            scan.cache_hits += 1
            entry = cached
        else:
            print(f"  [{i}/{len(sources)}] checking {source.name} ({source.chart} {source.version})...", flush=True)
            try:
                newest = newest_stable_version(source.version, fetcher.versions(source))
            except (urllib.error.URLError, OSError, UnicodeDecodeError, YamlShapeError) as e:
                print(f"  [FETCH-ERR] {source.name}  {e}")
                scan.fetch_errors.append(source)
                continue
            entry: UpgradeEntry = {"checked_at": datetime.now(timezone.utc).isoformat(), "newest": newest}
        new_cache[source.cache_key] = entry
        scan.newest[source] = entry["newest"]
    save_json_cache(cache_path, new_cache)
    return scan


def _print_findings(scan: ChartUpgradeScan, total: int, ttl_days: int) -> None:
    """Print upgradable charts, then OK/INCOMPLETE and the cache summary."""
    upgradable = [(s, n) for s, n in scan.newest.items() if n != s.version]
    for source, newest in upgradable:
        print(f"{source.name} ({source.chart} {source.version}): newer chart version available: {newest}")
    if scan.fetch_errors:
        print(f"INCOMPLETE: {len(scan.fetch_errors)}/{total} chart(s) could not be checked for a newer version:")
        for source in scan.fetch_errors:
            print(f"  {source.name} ({source.repository})")
    elif not upgradable:
        print("OK: no newer stable version published for any dependency chart")
    print(f"{scan.cache_hits}/{total} chart(s) served from cache (checked within the last {ttl_days} day(s))")


def check_chart_upgrades(chart_dir: Path) -> tuple[bool, str]:
    """verify-podiumd check: report dependency charts with a newer stable version.

    Always returns True; the detail counts upgradable charts and fetch errors.
    """
    ttl_days = chart_upgrade_check_cache_ttl_days(chart_dir)
    sources = chart_sources(chart_dir, load_chart_dependencies(chart_dir / "Chart.yaml"))
    print(f"Checking {len(sources)} dependency chart(s) for a newer published version...")
    scan = _scan(chart_dir, sources, ttl_days)
    _print_findings(scan, len(sources), ttl_days)
    upgradable = sum(1 for s, n in scan.newest.items() if n != s.version)
    return True, f"upgradable: {upgradable}/{len(sources)} chart(s); {len(scan.fetch_errors)} fetch error(s)"
