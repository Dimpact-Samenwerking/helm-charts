"""lib.chart.upgrade_check — version comparison, index parsing, sources, caching and the report."""

from pathlib import Path

import pytest

from lib.chart import upgrade_check
from lib.chart.chart_yaml import parse_chart_dependencies
from lib.chart.upgrade_check import ChartSource
from lib.chart.upgrade_check import chart_sources
from lib.chart.upgrade_check import check_chart_upgrades
from lib.chart.upgrade_check import index_chart_versions
from lib.chart.upgrade_check import newest_stable_version
from lib.chart.upgrade_check import stable_version_key

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


def test_stable_version_key_accepts_v_prefix_and_rejects_prereleases():
    assert stable_version_key("v1.2.3") == (1, 2, 3)
    assert stable_version_key("1.2.3-rc.1") is None
    assert stable_version_key("1.2") is None


def test_newest_stable_version_compares_numerically_and_skips_prereleases():
    assert newest_stable_version("1.0.9", ["1.0.10", "1.0.2", "2.0.0-beta.1"]) == "1.0.10"
    assert newest_stable_version("1.0.9", ["1.0.8"]) == "1.0.9"
    # A pin that isn't stable semver is never reported as upgradable.
    assert newest_stable_version("0.0.1-dev", ["1.0.0"]) == "0.0.1-dev"


def test_index_chart_versions_reads_only_the_named_chart():
    assert index_chart_versions(INDEX, "zaakafhandelcomponent", "t") == ["1.0.310", "1.1.0-rc.1", "1.0.297"]
    assert not index_chart_versions(INDEX, "missing", "t")
    assert not index_chart_versions("apiVersion: v1\n", "zaakafhandelcomponent", "t")


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


def test_check_reports_newer_charts_caches_them_and_never_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    (tmp_path / "Chart.yaml").write_text(CHART_YAML)
    published = {"zaakafhandelcomponent": ["1.0.297", "1.0.310"], "ita": ["2.0.0"]}
    calls: list[str] = []

    def fake_versions(_self: object, source: ChartSource) -> list[str]:
        calls.append(source.chart)
        return published[source.chart]

    monkeypatch.setattr(upgrade_check._Fetcher, "versions", fake_versions)  # pyright: ignore[reportPrivateUsage]

    assert check_chart_upgrades(tmp_path) == (True, "upgradable: 1/2 chart(s); 0 fetch error(s)")
    out = capsys.readouterr().out
    assert "zac (zaakafhandelcomponent 1.0.297): newer chart version available: 1.0.310" in out
    assert "ita (ita 2.0.0): newer" not in out

    # A second run within the TTL is served from the cache.
    assert check_chart_upgrades(tmp_path)[0]
    assert calls == ["zaakafhandelcomponent", "ita"]
    assert "2/2 chart(s) served from cache" in capsys.readouterr().out


def test_check_reports_a_fetch_error_as_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    (tmp_path / "Chart.yaml").write_text(CHART_YAML)

    def failing_versions(_self: object, _source: ChartSource) -> list[str]:
        msg = "unreachable"
        raise OSError(msg)

    monkeypatch.setattr(upgrade_check._Fetcher, "versions", failing_versions)  # pyright: ignore[reportPrivateUsage]

    assert check_chart_upgrades(tmp_path) == (True, "upgradable: 0/2 chart(s); 2 fetch error(s)")
    out = capsys.readouterr().out
    assert "INCOMPLETE: 2/2 chart(s) could not be checked" in out
    assert "OK:" not in out
