"""lib.chart.upgrade_check — version comparison, index parsing, sources, caching and the report."""

import io

from pathlib import Path

import pytest

from lib.chart import upgrade_check
from lib.chart.chart_yaml import parse_chart_dependencies
from lib.chart.upgrade_check import ChartSource
from lib.chart.upgrade_check import chart_sources
from lib.chart.upgrade_check import check_chart_upgrades
from lib.chart.upgrade_check import index_chart_releases
from lib.chart.upgrade_check import newer_stable_versions

INDEX = """\
apiVersion: v1
entries:
  zaakafhandelcomponent:
    - version: 1.0.310
      created: 2026-09-01T10:00:00Z
    - version: 1.1.0-rc.1
    - version: 1.0.297
  other:
    - version: 9.9.9
"""

INDEX_WITH_APP_VERSIONS = """\
apiVersion: v1
entries:
  zaakafhandelcomponent:
    - version: 1.0.310
      appVersion: 5.10.0
    - version: 1.0.297
      appVersion: "5.9.1"
    - version: 1.0.200
      appVersion: 5.1
"""


def test_newer_stable_versions_compares_numerically_and_skips_prereleases():
    assert newer_stable_versions("1.0.9", ["1.0.10", "1.0.2", "2.0.0-beta.1"]) == ["1.0.10"]
    assert newer_stable_versions("1.0.9", ["1.0.8"]) == []
    # A pin that isn't stable semver is never reported as upgradable.
    assert newer_stable_versions("0.0.1-dev", ["1.0.0"]) == []


def test_newer_stable_versions_lists_the_newest_per_major():
    published = ["1.1.1", "1.1.4", "1.2.0", "2.0.3", "2.1.0", "3.0.0-rc.1"]
    assert newer_stable_versions("1.1.1", published) == ["1.2.0", "2.1.0"]


def test_index_chart_releases_reads_only_the_named_chart():
    assert index_chart_releases(INDEX, "zaakafhandelcomponent", "t") == {
        "1.0.310": None,
        "1.1.0-rc.1": None,
        "1.0.297": None,
    }
    assert not index_chart_releases(INDEX, "missing", "t")
    assert not index_chart_releases("apiVersion: v1\n", "zaakafhandelcomponent", "t")


def test_index_chart_releases_reads_app_versions_as_text():
    assert index_chart_releases(INDEX_WITH_APP_VERSIONS, "zaakafhandelcomponent", "t") == {
        "1.0.310": "5.10.0",
        "1.0.297": "5.9.1",
        "1.0.200": "5.1",
    }


def test_chart_sources_resolve_aliases_and_skip_file_dependencies(tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        "helm_repos:\n  urls_by_alias:\n    zac: https://example.org/zac/\n"
    )
    deps = parse_chart_dependencies(
        "dependencies:\n"
        "  - {name: zaakafhandelcomponent, alias: zac, version: 1.0.297, repository: '@zac'}\n"
        "  - {name: mi-data, version: 1.0.0, repository: 'file://../mi-data'}\n"
        "  - {name: ita, version: 2.0.0, repository: 'oci://ghcr.io/org'}\n",
        "Chart.yaml",
    )
    assert chart_sources(tmp_path, deps) == [
        ChartSource("zac", "zaakafhandelcomponent", "1.0.297", "https://example.org/zac"),
        ChartSource("ita", "ita", "2.0.0", "oci://ghcr.io/org"),
    ]


CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.3
dependencies:
  - name: zaakafhandelcomponent
    alias: zac
    version: 1.0.297
    repository: https://example.org/zac
  - name: ita
    version: 2.0.0
    repository: oci://ghcr.io/org
"""


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def test_check_reports_newer_charts_with_app_versions_caches_them_and_never_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A classic repository's appVersions come from index.yaml, an OCI chart's from its config blob."""
    (tmp_path / "Chart.yaml").write_text(CHART_YAML)
    calls: list[str] = []

    def fake_urlopen(url: str, timeout: float) -> _Response:
        calls.append(url)
        return _Response(INDEX_WITH_APP_VERSIONS.encode())

    def fake_list_tags(host: str, repo: str) -> list[str]:
        calls.append(f"{host}/{repo}")
        return ["2.0.0", "2.1.0", "3.0.0"]

    monkeypatch.setattr(upgrade_check.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(upgrade_check, "list_tags", fake_list_tags)
    monkeypatch.setattr(upgrade_check, "chart_app_version", lambda host, repo, version, timeout: f"app-{version}")
    monkeypatch.setattr(upgrade_check, "subchart_app_version", lambda chart_dir, dep: "5.9.1")

    assert check_chart_upgrades(tmp_path) == (True, "upgradable: 2/2 chart(s); 0 fetch error(s)")
    out = capsys.readouterr().out
    assert (
        "zac (zaakafhandelcomponent) app 5.9.1, chart 1.0.297: newest version per major: app 5.10.0, chart 1.0.310"
        in out
    )
    assert (
        "ita (ita) app 5.9.1, chart 2.0.0: newest version per major: app app-2.1.0, chart 2.1.0 | "
        "app app-3.0.0, chart 3.0.0" in out
    )

    # A second run within the TTL is served from the cache, app versions included.
    assert check_chart_upgrades(tmp_path)[0]
    assert calls == ["https://example.org/zac/index.yaml", "ghcr.io/org/ita"]
    out = capsys.readouterr().out
    assert "2/2 chart(s) served from cache" in out
    assert "app app-3.0.0, chart 3.0.0" in out


def test_check_omits_an_unset_app_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    (tmp_path / "Chart.yaml").write_text(CHART_YAML)
    monkeypatch.setattr(upgrade_check.urllib.request, "urlopen", lambda url, timeout: _Response(INDEX.encode()))
    monkeypatch.setattr(upgrade_check, "list_tags", lambda host, repo: ["2.0.0"])
    monkeypatch.setattr(upgrade_check, "subchart_app_version", lambda chart_dir, dep: None)

    check_chart_upgrades(tmp_path)
    assert (
        "zac (zaakafhandelcomponent) chart 1.0.297: newest version per major: chart 1.0.310\n"
        in capsys.readouterr().out
    )


def test_check_reports_a_fetch_error_as_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    (tmp_path / "Chart.yaml").write_text(CHART_YAML)

    def failing_newer(_self: object, _source: ChartSource) -> tuple[list[str], list[str | None]]:
        msg = "unreachable"
        raise OSError(msg)

    monkeypatch.setattr(upgrade_check._Fetcher, "newer", failing_newer)  # pyright: ignore[reportPrivateUsage]

    assert check_chart_upgrades(tmp_path) == (True, "upgradable: 0/2 chart(s); 2 fetch error(s)")
    out = capsys.readouterr().out
    assert "INCOMPLETE: 2/2 chart(s) could not be checked" in out
    assert "OK:" not in out
