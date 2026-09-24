"""lib.chart.chart_yaml loaders (Chart.yaml, its dependencies, appVersion),
lib.chart.release_baseline_basics.chart_version and the lib.chart_lock
loaders."""

import pytest

from lib.chart.chart_yaml import chart_dependencies
from lib.chart.chart_yaml import load_chart_yaml
from lib.chart.chart_yaml import parse_chart_app_version
from lib.chart.chart_yaml import parse_chart_dependencies
from lib.chart.chart_yaml import parse_chart_yaml
from lib.chart.release_baseline_basics import chart_version
from lib.chart_lock import parse_chart_lock_dependencies
from lib.yaml_types import YamlShapeError

CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.2
appVersion: 4.9.2
dependencies:
  - name: zaakafhandelcomponent
    alias: zac
    version: 1.0.257
    repository: "@zac"
    condition: zac.enabled
    tags: [zaak]
  - name: local-chart
    version: 0.1.0
"""


def test_parse_chart_yaml_reads_dependencies():
    chart = parse_chart_yaml(CHART_YAML, "Chart.yaml")
    deps = chart_dependencies(chart)
    assert [dep["name"] for dep in deps] == ["zaakafhandelcomponent", "local-chart"]
    assert deps[0].get("alias") == "zac"
    assert deps[1].get("repository") is None


def test_parse_chart_yaml_keeps_keys_outside_the_type():
    chart = parse_chart_yaml(CHART_YAML + "keywords: [zgw]\n", "Chart.yaml")
    assert "keywords" in chart


def test_parse_chart_yaml_reads_unquoted_numeric_app_version_as_string():
    chart = parse_chart_yaml("apiVersion: v2\nname: x\nversion: 1.0.0\nappVersion: 8.4\n", "Chart.yaml")
    assert chart.get("appVersion") == "8.4"


def test_chart_dependencies_without_dependencies_key():
    assert chart_dependencies(parse_chart_yaml("apiVersion: v2\nname: x\nversion: 1.0.0\n", "Chart.yaml")) == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("name: x\nversion: 1.0.0\n", "(top level): missing 'apiVersion'"),
        ("apiVersion: v2\nname: x\nversion: 1.0\n", "version: expected str, got float"),
        (
            "apiVersion: v2\nname: x\nversion: 1.0.0\ndependencies:\n  - name: a\n",
            "dependencies[0]: missing 'version'",
        ),
        (
            "apiVersion: v2\nname: x\nversion: 1.0.0\ndependencies:\n  - name: a\n    version: 1.0.0\n    tags: a\n",
            "dependencies[0].tags: expected a list of strings",
        ),
        ("apiVersion: v2\nname: x\nversion: 1.0.0\ndependencies: a\n", "dependencies: expected a list, got str"),
    ],
)
def test_parse_chart_yaml_names_the_problem(text, problem):
    with pytest.raises(YamlShapeError) as excinfo:
        parse_chart_yaml(text, "Chart.yaml")
    assert str(excinfo.value) == f"Chart.yaml: {problem}"


def test_load_chart_yaml_reads_file(tmp_path):
    path = tmp_path / "Chart.yaml"
    path.write_text(CHART_YAML, encoding="utf-8")
    assert load_chart_yaml(path)["name"] == "podiumd"


def test_parse_chart_dependencies_reads_unquoted_int_version_as_string():
    deps = parse_chart_dependencies("dependencies:\n  - name: keycloak\n    version: 26\n", "Chart.yaml")
    assert deps == [{"name": "keycloak", "version": "26"}]


def test_parse_chart_dependencies_rejects_float_version():
    # "1.10" unquoted reads as 1.1: the real version is already lost.
    with pytest.raises(YamlShapeError, match=r"dependencies\[0\]\.version: expected str, got float"):
        parse_chart_dependencies("dependencies:\n  - name: a\n    version: 1.10\n", "Chart.yaml")


def test_parse_chart_dependencies_accepts_minimal_or_bare_chart_yaml():
    assert parse_chart_dependencies("dependencies:\n", "Chart.yaml") == []
    assert parse_chart_dependencies("name: x\n", "Chart.yaml") == []


def test_parse_chart_app_version():
    assert parse_chart_app_version("appVersion: 8.4\n", "Chart.yaml") == "8.4"
    assert parse_chart_app_version("appVersion: v1.2\n", "Chart.yaml") == "v1.2"
    assert parse_chart_app_version("name: x\n", "Chart.yaml") is None
    with pytest.raises(YamlShapeError, match="appVersion: expected a string or number, got list"):
        parse_chart_app_version("appVersion: [1]\n", "Chart.yaml")


def test_chart_version(tmp_path):
    path = tmp_path / "Chart.yaml"
    path.write_text("version: 4.9.2\n", encoding="utf-8")
    assert chart_version(path) == "4.9.2"
    path.write_text("version: 5\n", encoding="utf-8")
    assert chart_version(path) == "5"
    path.write_text("version: 4.90\n", encoding="utf-8")
    with pytest.raises(YamlShapeError, match="version: expected str, got float"):
        chart_version(path)


def test_parse_chart_lock_dependencies():
    text = "dependencies:\n- name: a\n  version: 1.0.0\n- name: b\n  version: 2\n  repository: https://x\n"
    assert parse_chart_lock_dependencies(text, "Chart.lock") == [
        {"name": "a", "version": "1.0.0"},
        {"name": "b", "version": "2", "repository": "https://x"},
    ]
    assert parse_chart_lock_dependencies("digest: sha256:abc\n", "Chart.lock") is None
    with pytest.raises(YamlShapeError, match=r"dependencies\[0\]: missing 'version'"):
        parse_chart_lock_dependencies("dependencies:\n- name: a\n", "Chart.lock")
