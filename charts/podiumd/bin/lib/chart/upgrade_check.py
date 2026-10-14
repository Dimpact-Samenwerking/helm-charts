"""Report-only check for newer stable versions of every Chart.yaml dependency chart.

Per chart it lists the newest newer version in each major, so a same-major upgrade
shows next to the newest release, each with its appVersion: the pinned one from the
vendored chart, newer ones from index.yaml or the OCI chart's config blob.

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
from typing import TypeGuard

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.chart_yaml import normalize_app_version
from lib.chart.pull_and_subchart_resolution import subchart_app_version
from lib.chart.values_tree_primitives import values_key_of
from lib.image.upgrade_cache import UpgradeEntry
from lib.image.upgrade_cache import cache_entry_is_fresh
from lib.json_cache import cache_file
from lib.json_cache import load_json_cache
from lib.json_cache import save_json_cache
from lib.registry import chart_app_version
from lib.registry import list_tags
from lib.render_scope import resolve_dependency_repo
from lib.settings import chart_upgrade_check_cache_ttl_days
from lib.settings import helm_repos_urls_by_alias
from lib.settings import repo_access_request_timeout_seconds
from lib.version_numbers import newest_per_major
from lib.version_numbers import stable_semver_key
from lib.yaml_types import YamlShapeError
from lib.yaml_types import parse_yaml
from lib.yaml_types import shape_problem

CACHE_FILENAME = "chart-upgrade-cache.json"


class ChartUpgradeEntry(UpgradeEntry):
    """An UpgradeEntry plus the appVersion of each "newer" version, in the same order (None if unset)."""

    app_versions: list[str | None]


def is_chart_upgrade_entry(value: object) -> TypeGuard[ChartUpgradeEntry]:
    """Whether a parsed cache entry is a ChartUpgradeEntry."""
    shape = {"checked_at": str, "newer": [str], "app_versions": [(str, type(None))]}
    return shape_problem(value, shape) is None


def newer_stable_versions(current: str, published: list[str]) -> list[str]:
    """The highest stable version in `published` above `current`, one per major; [] if none."""
    current_key = stable_semver_key(current)
    if current_key is None:
        return []
    keyed = ((version, stable_semver_key(version)) for version in published)
    return newest_per_major(current_key, [(version, key) for version, key in keyed if key is not None])


def index_chart_releases(index_text: str, chart_name: str, source: str) -> dict[str, str | None]:
    """version -> appVersion (None if unset) of every `chart_name` release in a Helm repository index.yaml."""
    index = parse_yaml(index_text, source)
    releases = index.get("entries") if isinstance(index, dict) else None
    chart_releases = releases.get(chart_name) if isinstance(releases, dict) else None
    if not isinstance(chart_releases, list):
        return {}
    versions: dict[str, str | None] = {}
    for release in chart_releases:
        if not isinstance(release, dict):
            continue
        normalize_app_version(release)
        version, app_version = release.get("version"), release.get("appVersion")
        if isinstance(version, str):
            versions[version] = app_version if isinstance(app_version, str) else None
    return versions


@dataclass(frozen=True)
class ChartSource:
    """Where one dependency's published versions are listed."""

    name: str
    chart: str
    version: str
    repository: str
    app_version: str | None = None

    @property
    def cache_key(self) -> str:
        """The cache key, e.g. "https://example.org/charts/zac:1.0.297"."""
        return f"{self.repository}/{self.chart}:{self.version}"


def chart_sources(chart_dir: Path, deps: list[ChartDependency]) -> list[ChartSource]:
    """A ChartSource per network-resolved dependency, "@alias" resolved; "file://" ones left out.

    app_version is the vendored chart's appVersion (None if not vendored).
    """
    repos_by_alias = helm_repos_urls_by_alias(chart_dir)
    sources: list[ChartSource] = []
    for dep in deps:
        repository = resolve_dependency_repo(dep.get("repository", ""), repos_by_alias)
        if repository and not repository.startswith("file://"):
            sources.append(
                ChartSource(
                    values_key_of(dep),
                    dep["name"],
                    str(dep["version"]),
                    repository.rstrip("/"),
                    subchart_app_version(chart_dir, dep),
                )
            )
    return sources


@dataclass
class _Fetcher:
    """Published versions per source; an index.yaml is downloaded once per repository."""

    timeout_seconds: float
    index_texts: dict[str, str] = field(default_factory=dict)

    def newer(self, source: ChartSource) -> tuple[list[str], list[str | None]]:
        """`source`'s newer_stable_versions and their appVersions.

        An OCI tag list has no appVersions, so those cost one config-blob read per listed version.
        """
        if source.repository.startswith("oci://"):
            host, _, path = source.repository[len("oci://") :].partition("/")
            repo = f"{path}/{source.chart}" if path else source.chart
            newer = newer_stable_versions(source.version, list_tags(host, repo))
            return newer, [chart_app_version(host, repo, version, self.timeout_seconds) for version in newer]
        if source.repository not in self.index_texts:
            index_url = f"{source.repository}/index.yaml"
            # index_url comes from Chart.yaml/settings.yaml, never an attacker-controlled scheme.
            with urllib.request.urlopen(index_url, timeout=self.timeout_seconds) as resp:  # nosec B310
                self.index_texts[source.repository] = resp.read().decode("utf-8")
        releases = index_chart_releases(self.index_texts[source.repository], source.chart, source.repository)
        newer = newer_stable_versions(source.version, list(releases))
        return newer, [releases[version] for version in newer]


@dataclass
class ChartUpgradeScan:
    """Newer versions per checked source, sources that could not be checked, and cache hits."""

    newer: dict[ChartSource, ChartUpgradeEntry] = field(default_factory=dict)
    fetch_errors: list[ChartSource] = field(default_factory=list)
    cache_hits: int = 0


def _scan(chart_dir: Path, sources: list[ChartSource], ttl_days: int) -> ChartUpgradeScan:
    """Resolve every source from a fresh cache entry or the network; the saved cache drops unused entries."""
    cache_path = cache_file(chart_dir, CACHE_FILENAME)
    old_cache = load_json_cache(cache_path, is_chart_upgrade_entry)
    new_cache: dict[str, ChartUpgradeEntry] = {}
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
                newer, app_versions = fetcher.newer(source)
            except (urllib.error.URLError, OSError, UnicodeDecodeError, YamlShapeError) as e:
                print(f"  [FETCH-ERR] {source.name}  {e}")
                scan.fetch_errors.append(source)
                continue
            entry: ChartUpgradeEntry = {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "newer": newer,
                "app_versions": app_versions,
            }
        new_cache[source.cache_key] = entry
        scan.newer[source] = entry
    save_json_cache(cache_path, new_cache)
    return scan


def _with_app_version(version: str, app_version: str | None) -> str:
    """ "1.0.345 (app 5.12.0)", or just the version when the chart sets no appVersion."""
    return f"{version} (app {app_version})" if app_version else version


def _print_findings(scan: ChartUpgradeScan, total: int, ttl_days: int) -> None:
    """Print upgradable charts, then OK/INCOMPLETE and the cache summary."""
    upgradable = [(s, e) for s, e in scan.newer.items() if e["newer"]]
    for source, entry in upgradable:
        newer = ", ".join(map(_with_app_version, entry["newer"], entry["app_versions"]))
        current = _with_app_version(f"{source.chart} {source.version}", source.app_version)
        print(f"{source.name} ({current}): newest chart version per major: {newer}")
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
    upgradable = sum(1 for e in scan.newer.values() if e["newer"])
    return True, f"upgradable: {upgradable}/{len(sources)} chart(s); {len(scan.fetch_errors)} fetch error(s)"
