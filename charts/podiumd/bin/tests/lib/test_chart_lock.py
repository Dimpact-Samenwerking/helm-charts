"""lib.chart_lock — Chart.lock content and digest byte-compatible with
`helm dependency update`. The expected digests below were produced by a
real Helm 3.22 `helm dependency update` (file:// sub-charts, so no
network), not computed by the code under test."""

from pathlib import Path
from types import ModuleType

import yaml

# Exercises every Go JSON quirk helm_lock_digest mirrors: omitempty
# fields present and absent, tags with "&", import-values with a map
# (key order), a version range with ">" and "<", and the same chart twice
# under two aliases.
EDGE_CASE_CHART_DEPS = [
    {
        "name": "sub-a",
        "version": "1.2.3",
        "repository": "file://../sub-a",
        "condition": "a.enabled",
        "tags": ["x", "y&z"],
        "alias": "first",
        "import-values": [{"child": "exports.data", "parent": "zdata"}, "simple"],
    },
    {"name": "sub-a", "version": ">=1.0.0 <2.0.0", "repository": "file://../sub-a", "alias": "second"},
    {"name": "sub-b", "version": "0.4.0-rc.1", "repository": "file://../sub-b"},
]
EDGE_CASE_LOCK_DEPS = [
    {"name": "sub-a", "repository": "file://../sub-a", "version": "1.2.3"},
    {"name": "sub-a", "repository": "file://../sub-a", "version": "1.2.3"},
    {"name": "sub-b", "repository": "file://../sub-b", "version": "0.4.0-rc.1"},
]
EDGE_CASE_HELM_DIGEST = "sha256:5dab970ee5d9a982f33fa6e5d4278e4a84784af13c7a219ca7cfeae539c9061b"


def test_helm_lock_digest_matches_real_helm(libchartlock: ModuleType):
    assert libchartlock.helm_lock_digest(EDGE_CASE_CHART_DEPS, EDGE_CASE_LOCK_DEPS, {}) == EDGE_CASE_HELM_DIGEST


def test_helm_lock_digest_ignores_map_key_order_in_import_values(libchartlock: ModuleType):
    """Go marshals a map with sorted keys, whatever order Chart.yaml wrote."""
    reordered = [
        {**EDGE_CASE_CHART_DEPS[0], "import-values": [{"parent": "zdata", "child": "exports.data"}, "simple"]},
        *EDGE_CASE_CHART_DEPS[1:],
    ]
    assert libchartlock.helm_lock_digest(reordered, EDGE_CASE_LOCK_DEPS, {}) == EDGE_CASE_HELM_DIGEST


def test_helm_lock_digest_resolves_alias_repository(libchartlock: ModuleType):
    """Helm hashes Chart.yaml's dependencies after resolving "@alias" to
    the repo URL, so an alias and the URL it stands for hash the same."""
    url = "https://maykinmedia.github.io/charts/"
    lock = [{"name": "openzaak", "repository": url, "version": "1.14.2"}]
    by_alias = [{"name": "openzaak", "version": "1.14.2", "repository": "@maykinmedia"}]
    by_url = [{"name": "openzaak", "version": "1.14.2", "repository": url}]
    assert libchartlock.helm_lock_digest(by_alias, lock, {"maykinmedia": url}) == libchartlock.helm_lock_digest(
        by_url, lock, {}
    )


def test_lock_dependencies_keeps_order_and_resolves_alias(libchartlock: ModuleType):
    chart_deps = [
        {"name": "zac", "version": "1.0.297", "repository": "@zac", "alias": "zac", "condition": "zac.enabled"},
        {"name": "kiss-chart", "version": "3.1.1", "repository": "oci://ghcr.io/kiss"},
        {"name": "old-style", "version": 26, "repository": "@unknown"},
    ]
    assert libchartlock.lock_dependencies(chart_deps, {"zac": "https://zac.example/charts"}) == [
        {"name": "zac", "repository": "https://zac.example/charts", "version": "1.0.297"},
        {"name": "kiss-chart", "repository": "oci://ghcr.io/kiss", "version": "3.1.1"},
        {"name": "old-style", "repository": "@unknown", "version": "26"},
    ]


def test_write_chart_lock_matches_helm_digest_for_its_own_lock(libchartlock: ModuleType, tmp_path: Path):
    """The real e2e case: sub-a bumped 1.2.3 -> 1.3.0 next to an unchanged
    sub-b; `helm dependency update` wrote this exact digest."""
    chart_deps = [
        {"name": "sub-a", "version": "1.3.0", "repository": "file://../sub-a"},
        {"name": "sub-b", "version": "0.4.0", "repository": "file://../sub-b"},
    ]
    libchartlock.write_chart_lock(tmp_path, chart_deps, {})
    lock = yaml.safe_load((tmp_path / "Chart.lock").read_text(encoding="utf-8"))
    assert lock["dependencies"] == [
        {"name": "sub-a", "repository": "file://../sub-a", "version": "1.3.0"},
        {"name": "sub-b", "repository": "file://../sub-b", "version": "0.4.0"},
    ]
    assert lock["digest"] == "sha256:cb94126f8db6f57af6ace30364c438f06565a4428d20b7a1c80b1ab4396b43b9"
    assert lock["generated"]
