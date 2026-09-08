"""check_lockstep_versions / find_lockstep_mismatches /
find_chart_version_mismatches — every component registered as
"lockstep" in lib.chart (COMPONENT_IMAGE_PATHS/COMPONENT_VERSION_PATHS
multi-path entries, and CHART_VERSION_LOCKSTEP_COMPONENTS) must
actually agree on one version in values.yaml/Chart.yaml."""
import pytest


@pytest.fixture(autouse=True)
def _lockstep_registries(liblockstepcheck, monkeypatch):
    """Isolate every test from the real, ever-growing COMPONENT_IMAGE_
    PATHS/COMPONENT_VERSION_PATHS/CHART_VERSION_LOCKSTEP_COMPONENTS —
    a real entry added later for an unrelated component must never
    change what these tests exercise."""
    monkeypatch.setattr(liblockstepcheck, "COMPONENT_IMAGE_PATHS",
                         {"zgw-office-addin": ["frontend.image", "backend.image"]})
    monkeypatch.setattr(liblockstepcheck, "COMPONENT_VERSION_PATHS",
                         {"eck-stack": ["eck-elasticsearch.version", "eck-kibana.version"]})
    monkeypatch.setattr(liblockstepcheck, "CHART_VERSION_LOCKSTEP_COMPONENTS",
                         frozenset({"kiss-chart", "pabc"}))


# --- find_lockstep_mismatches ---

def test_matching_multi_path_image_versions_no_mismatch(liblockstepcheck):
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.9.352"}]
    values = {"zgw-office-addin": {
        "frontend": {"image": {"tag": "0.9.352@sha256:aaa"}},
        "backend": {"image": {"tag": "0.9.352@sha256:bbb"}},
    }}
    assert liblockstepcheck.find_lockstep_mismatches(deps, values) == []


def test_drifted_multi_path_image_versions_reported(liblockstepcheck):
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.9.352"}]
    values = {"zgw-office-addin": {
        "frontend": {"image": {"tag": "0.9.352@sha256:aaa"}},
        "backend": {"image": {"tag": "0.9.300@sha256:bbb"}},
    }}
    mismatches = liblockstepcheck.find_lockstep_mismatches(deps, values)
    assert len(mismatches) == 1
    component, values_key, resolved = mismatches[0]
    assert component == "zgw-office-addin"
    assert values_key == "zgw-office-addin"
    assert resolved == [("frontend.image", "0.9.352"), ("backend.image", "0.9.300")]


def test_matching_multi_path_bare_version_no_mismatch(liblockstepcheck):
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}, "eck-kibana": {"version": "8.19.19"}}}
    assert liblockstepcheck.find_lockstep_mismatches([dep], values) == []


def test_drifted_multi_path_bare_version_reported(liblockstepcheck):
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}, "eck-kibana": {"version": "8.19.3"}}}
    mismatches = liblockstepcheck.find_lockstep_mismatches([dep], values)
    assert len(mismatches) == 1
    component, values_key, resolved = mismatches[0]
    assert component == "eck-stack"
    assert values_key == "kiss-eck"
    assert resolved == [("eck-elasticsearch.version", "8.19.19"), ("eck-kibana.version", "8.19.3")]


def test_digest_ignored_when_comparing_image_tag_versions(liblockstepcheck):
    """Two paths pinned to the SAME version but different digests must
    never be reported — only the version (before "@") is compared."""
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.9.352"}]
    values = {"zgw-office-addin": {
        "frontend": {"image": {"tag": "0.9.352@sha256:" + "a" * 64}},
        "backend": {"image": {"tag": "0.9.352@sha256:" + "b" * 64}},
    }}
    assert liblockstepcheck.find_lockstep_mismatches(deps, values) == []


def test_path_with_no_explicit_value_is_skipped_not_flagged(liblockstepcheck):
    """backend.image has no override at all (relies on the vendored
    chart's own default) — comparing "no override" against frontend's
    explicit tag would flag a legitimate config choice, not real drift."""
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.9.352"}]
    values = {"zgw-office-addin": {"frontend": {"image": {"tag": "0.9.352@sha256:aaa"}}}}
    assert liblockstepcheck.find_lockstep_mismatches(deps, values) == []


def test_component_missing_from_values_entirely_is_skipped(liblockstepcheck):
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.9.352"}]
    assert liblockstepcheck.find_lockstep_mismatches(deps, {}) == []


def test_component_with_no_matching_dependency_is_skipped(liblockstepcheck):
    """A registered component absent from Chart.yaml's own dependency
    list (shouldn't happen in practice) must never raise."""
    values = {"zgw-office-addin": {
        "frontend": {"image": {"tag": "0.9.352@sha256:aaa"}},
        "backend": {"image": {"tag": "0.9.300@sha256:bbb"}},
    }}
    assert liblockstepcheck.find_lockstep_mismatches([], values) == []


def test_single_path_registration_never_compared(liblockstepcheck, monkeypatch):
    """A COMPONENT_IMAGE_PATHS entry with just one path has nothing to
    compare against, so it's skipped outright — regardless of whatever
    that lone path resolves to."""
    monkeypatch.setattr(liblockstepcheck, "COMPONENT_IMAGE_PATHS", {"openbao": ["server.image"]})
    dep = {"name": "openbao", "alias": "", "version": "2.0.0"}
    values = {"openbao": {"server": {"image": {"tag": "2.0.0@sha256:aaa"}}}}
    assert liblockstepcheck.find_lockstep_mismatches([dep], values) == []


def test_unrelated_components_sharing_a_version_never_flagged(liblockstepcheck):
    """Two DIFFERENT registered components that happen to share a
    version number is normal, not a mismatch — find_lockstep_mismatches
    only ever compares paths WITHIN one component's own entry."""
    deps = [
        {"name": "zgw-office-addin", "alias": "", "version": "0.9.352"},
        {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"},
    ]
    values = {
        "zgw-office-addin": {
            "frontend": {"image": {"tag": "1.0.0@sha256:aaa"}},
            "backend": {"image": {"tag": "1.0.0@sha256:bbb"}},
        },
        "kiss-eck": {
            "eck-elasticsearch": {"version": "1.0.0"},
            "eck-kibana": {"version": "1.0.0"},
        },
    }
    assert liblockstepcheck.find_lockstep_mismatches(deps, values) == []


# --- find_chart_version_mismatches ---

def test_chart_version_matches_image_version_no_mismatch(liblockstepcheck):
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    values = {"kiss": {"image": {"tag": "3.1.1@sha256:aaa"}}}
    assert liblockstepcheck.find_chart_version_mismatches([dep], values) == []


def test_chart_version_disagrees_with_image_version_reported(liblockstepcheck):
    dep = {"name": "pabc", "alias": "pabc", "version": "1.1.1"}
    values = {"pabc": {"image": {"tag": "1.1.0@sha256:aaa"}}}
    mismatches = liblockstepcheck.find_chart_version_mismatches([dep], values)
    assert mismatches == [("pabc", "pabc", "1.1.1", "1.1.0")]


def test_chart_version_component_with_no_image_tag_skipped(liblockstepcheck):
    """Relies entirely on the vendored chart's own appVersion default —
    nothing to compare, not a mismatch."""
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    assert liblockstepcheck.find_chart_version_mismatches([dep], {"kiss": {}}) == []


def test_chart_version_component_with_no_dependency_skipped(liblockstepcheck):
    assert liblockstepcheck.find_chart_version_mismatches([], {}) == []


def test_chart_version_digest_ignored_when_comparing(liblockstepcheck):
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    values = {"kiss": {"image": {"tag": "3.1.1@sha256:" + "f" * 64}}}
    assert liblockstepcheck.find_chart_version_mismatches([dep], values) == []


# --- check_lockstep_versions (integration) ---

def make_chart(tmp_path, chart_yaml_deps, values_text):
    (tmp_path / "Chart.yaml").write_text(
        "name: podiumd\nversion: 1.0.0\ndependencies:\n" + chart_yaml_deps, encoding="utf-8")
    (tmp_path / "values.yaml").write_text(values_text, encoding="utf-8")
    return tmp_path


def test_check_passes_when_everything_agrees(liblockstepcheck, tmp_path):
    make_chart(
        tmp_path,
        "  - name: kiss-chart\n    alias: kiss\n    version: 3.1.1\n",
        "kiss:\n  image:\n    tag: \"3.1.1@sha256:aaa\"\n",
    )
    ok, detail = liblockstepcheck.check_lockstep_versions(tmp_path)
    assert ok is True
    assert "0 mismatch(es)" in detail


def test_check_fails_and_reports_chart_version_drift(liblockstepcheck, tmp_path, capsys):
    make_chart(
        tmp_path,
        "  - name: pabc\n    alias: pabc\n    version: 1.1.1\n",
        "pabc:\n  image:\n    tag: \"1.1.0@sha256:aaa\"\n",
    )
    ok, detail = liblockstepcheck.check_lockstep_versions(tmp_path)
    assert ok is False
    assert "1 mismatch(es)" in detail
    out = capsys.readouterr().out
    assert "pabc" in out
    assert "1.1.1" in out and "1.1.0" in out


def test_check_fails_and_reports_multi_path_drift(liblockstepcheck, tmp_path, capsys):
    make_chart(
        tmp_path,
        "  - name: zgw-office-addin\n    version: 0.9.352\n",
        "zgw-office-addin:\n"
        "  frontend:\n    image:\n      tag: \"0.9.352@sha256:aaa\"\n"
        "  backend:\n    image:\n      tag: \"0.9.300@sha256:bbb\"\n",
    )
    ok, detail = liblockstepcheck.check_lockstep_versions(tmp_path)
    assert ok is False
    assert "1 mismatch(es)" in detail
    out = capsys.readouterr().out
    assert "zgw-office-addin" in out
    assert "frontend.image" in out and "backend.image" in out
