"""check_lockstep_versions and its find_*_mismatches helpers: every component
registered as lockstep in lib.chart must agree on one version."""

from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture(autouse=True)
def _lockstep_registries(liblockstepcheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Isolate tests from the real, growing lockstep registries."""
    monkeypatch.setattr(
        liblockstepcheck, "component_image_paths", lambda: {"zgw-office-addin": ["frontend.image", "backend.image"]}
    )
    monkeypatch.setattr(
        liblockstepcheck,
        "component_version_paths",
        lambda: {"eck-stack": ["eck-elasticsearch.version", "eck-kibana.version"]},
    )
    monkeypatch.setattr(
        liblockstepcheck, "chart_version_lockstep_components", lambda: frozenset({"kiss-chart", "pabc"})
    )
    monkeypatch.setattr(
        liblockstepcheck,
        "embedded_version_images",
        lambda: {"keycloak.keycloakConfigCli.image": "keycloak.image"},
    )


# --- find_lockstep_mismatches ---


def test_matching_multi_path_image_versions_no_mismatch(liblockstepcheck: ModuleType):
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.9.352"}]
    values = {
        "zgw-office-addin": {
            "frontend": {"image": {"tag": "0.9.352@sha256:aaa"}},
            "backend": {"image": {"tag": "0.9.352@sha256:bbb"}},
        }
    }
    assert liblockstepcheck.find_lockstep_mismatches(deps, values) == []


def test_drifted_multi_path_image_versions_reported(liblockstepcheck: ModuleType):
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.9.352"}]
    values = {
        "zgw-office-addin": {
            "frontend": {"image": {"tag": "0.9.352@sha256:aaa"}},
            "backend": {"image": {"tag": "0.9.300@sha256:bbb"}},
        }
    }
    mismatches = liblockstepcheck.find_lockstep_mismatches(deps, values)
    assert len(mismatches) == 1
    component, values_key, resolved = mismatches[0]
    assert component == "zgw-office-addin"
    assert values_key == "zgw-office-addin"
    assert resolved == [("frontend.image", "0.9.352"), ("backend.image", "0.9.300")]


def test_matching_multi_path_bare_version_no_mismatch(liblockstepcheck: ModuleType):
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}, "eck-kibana": {"version": "8.19.19"}}}
    assert liblockstepcheck.find_lockstep_mismatches([dep], values) == []


def test_drifted_multi_path_bare_version_reported(liblockstepcheck: ModuleType):
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}, "eck-kibana": {"version": "8.19.3"}}}
    mismatches = liblockstepcheck.find_lockstep_mismatches([dep], values)
    assert len(mismatches) == 1
    component, values_key, resolved = mismatches[0]
    assert component == "eck-stack"
    assert values_key == "kiss-eck"
    assert resolved == [("eck-elasticsearch.version", "8.19.19"), ("eck-kibana.version", "8.19.3")]


def test_digest_ignored_when_comparing_image_tag_versions(liblockstepcheck: ModuleType):
    """Two paths pinned to the SAME version but different digests must
    never be reported — only the version (before "@") is compared."""
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.9.352"}]
    values = {
        "zgw-office-addin": {
            "frontend": {"image": {"tag": "0.9.352@sha256:" + "a" * 64}},
            "backend": {"image": {"tag": "0.9.352@sha256:" + "b" * 64}},
        }
    }
    assert liblockstepcheck.find_lockstep_mismatches(deps, values) == []


def test_path_with_no_explicit_value_is_skipped_not_flagged(liblockstepcheck: ModuleType):
    """backend.image without an override (vendored default) is a config
    choice, not drift."""
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.9.352"}]
    values = {"zgw-office-addin": {"frontend": {"image": {"tag": "0.9.352@sha256:aaa"}}}}
    assert liblockstepcheck.find_lockstep_mismatches(deps, values) == []


def test_component_missing_from_values_entirely_is_skipped(liblockstepcheck: ModuleType):
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.9.352"}]
    assert liblockstepcheck.find_lockstep_mismatches(deps, {}) == []


def test_component_with_no_matching_dependency_is_skipped(liblockstepcheck: ModuleType):
    """A registered component absent from Chart.yaml's own dependency
    list (shouldn't happen in practice) must never raise."""
    values = {
        "zgw-office-addin": {
            "frontend": {"image": {"tag": "0.9.352@sha256:aaa"}},
            "backend": {"image": {"tag": "0.9.300@sha256:bbb"}},
        }
    }
    assert liblockstepcheck.find_lockstep_mismatches([], values) == []


def test_single_path_registration_never_compared(liblockstepcheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """A single-path entry has nothing to compare against: skipped."""
    monkeypatch.setattr(liblockstepcheck, "component_image_paths", lambda: {"openbao": ["server.image"]})
    dep = {"name": "openbao", "alias": "", "version": "2.0.0"}
    values = {"openbao": {"server": {"image": {"tag": "2.0.0@sha256:aaa"}}}}
    assert liblockstepcheck.find_lockstep_mismatches([dep], values) == []


def test_unrelated_components_sharing_a_version_never_flagged(liblockstepcheck: ModuleType):
    """Different components sharing a version number is not a mismatch."""
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


def test_chart_version_matches_image_version_no_mismatch(liblockstepcheck: ModuleType):
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    values = {"kiss": {"image": {"tag": "3.1.1@sha256:aaa"}}}
    assert liblockstepcheck.find_chart_version_mismatches([dep], values) == []


def test_chart_version_disagrees_with_image_version_reported(liblockstepcheck: ModuleType):
    dep = {"name": "pabc", "alias": "pabc", "version": "1.1.1"}
    values = {"pabc": {"image": {"tag": "1.1.0@sha256:aaa"}}}
    mismatches = liblockstepcheck.find_chart_version_mismatches([dep], values)
    assert mismatches == [("pabc", "pabc", "1.1.1", "1.1.0")]


def test_chart_version_component_with_no_image_tag_skipped(liblockstepcheck: ModuleType):
    """Relying on the vendored appVersion default is not a mismatch."""
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    assert liblockstepcheck.find_chart_version_mismatches([dep], {"kiss": {}}) == []


def test_chart_version_component_with_no_dependency_skipped(liblockstepcheck: ModuleType):
    assert liblockstepcheck.find_chart_version_mismatches([], {}) == []


def test_chart_version_digest_ignored_when_comparing(liblockstepcheck: ModuleType):
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    values = {"kiss": {"image": {"tag": "3.1.1@sha256:" + "f" * 64}}}
    assert liblockstepcheck.find_chart_version_mismatches([dep], values) == []


def test_eck_operator_chart_version_lockstep_registered(liblockstepcheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """eck-operator is registered because its chart and operator image share
    one version. Opts back in past the autouse isolation fixture."""
    monkeypatch.setattr(
        liblockstepcheck, "chart_version_lockstep_components", lambda: frozenset({"kiss-chart", "pabc", "eck-operator"})
    )
    dep = {"name": "eck-operator", "version": "3.5.0"}
    values = {"eck-operator": {"image": {"tag": "3.5.0"}}}
    assert liblockstepcheck.find_chart_version_mismatches([dep], values) == []


def test_eck_operator_chart_version_drift_reported(liblockstepcheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """An eck-operator dependency bump without the matching image tag bump
    (or vice versa) is caught."""
    monkeypatch.setattr(
        liblockstepcheck, "chart_version_lockstep_components", lambda: frozenset({"kiss-chart", "pabc", "eck-operator"})
    )
    dep = {"name": "eck-operator", "version": "3.5.0"}
    values = {"eck-operator": {"image": {"tag": "3.4.0"}}}
    mismatches = liblockstepcheck.find_chart_version_mismatches([dep], values)
    assert mismatches == [("eck-operator", "eck-operator", "3.5.0", "3.4.0")]


# --- check_lockstep_versions (integration) ---


def make_chart(tmp_path: Path, chart_yaml_deps, values_text):
    (tmp_path / "Chart.yaml").write_text(
        "name: podiumd\nversion: 1.0.0\ndependencies:\n" + chart_yaml_deps, encoding="utf-8"
    )
    (tmp_path / "values.yaml").write_text(values_text, encoding="utf-8")
    return tmp_path


def test_check_passes_when_everything_agrees(liblockstepcheck: ModuleType, tmp_path: Path):
    make_chart(
        tmp_path,
        "  - name: kiss-chart\n    alias: kiss\n    version: 3.1.1\n",
        'kiss:\n  image:\n    tag: "3.1.1@sha256:aaa"\n',
    )
    ok, detail = liblockstepcheck.check_lockstep_versions(tmp_path)
    assert ok is True
    assert "0 mismatch(es)" in detail


def test_check_fails_and_reports_chart_version_drift(
    liblockstepcheck: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    make_chart(
        tmp_path,
        "  - name: pabc\n    alias: pabc\n    version: 1.1.1\n",
        'pabc:\n  image:\n    tag: "1.1.0@sha256:aaa"\n',
    )
    ok, detail = liblockstepcheck.check_lockstep_versions(tmp_path)
    assert ok is False
    assert "1 mismatch(es)" in detail
    out = capsys.readouterr().out
    assert "pabc" in out
    assert "1.1.1" in out and "1.1.0" in out


def test_check_fails_and_reports_multi_path_drift(
    liblockstepcheck: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    make_chart(
        tmp_path,
        "  - name: zgw-office-addin\n    version: 0.9.352\n",
        "zgw-office-addin:\n"
        '  frontend:\n    image:\n      tag: "0.9.352@sha256:aaa"\n'
        '  backend:\n    image:\n      tag: "0.9.300@sha256:bbb"\n',
    )
    ok, detail = liblockstepcheck.check_lockstep_versions(tmp_path)
    assert ok is False
    assert "1 mismatch(es)" in detail
    out = capsys.readouterr().out
    assert "zgw-office-addin" in out
    assert "frontend.image" in out and "backend.image" in out


# --- find_embedded_version_mismatches ---


def _keycloak_values(config_cli_tag: str, keycloak_tag: str = "26.7.3"):
    return {
        "keycloak": {
            "image": {"tag": keycloak_tag},
            "keycloakConfigCli": {"image": {"tag": config_cli_tag}},
        }
    }


def test_embedded_version_older_same_major_no_mismatch(liblockstepcheck: ModuleType):
    values = _keycloak_values("6.5.1-26.5.5@sha256:aaa")
    assert liblockstepcheck.find_embedded_version_mismatches(values) == []


def test_embedded_version_equal_no_mismatch(liblockstepcheck: ModuleType):
    values = _keycloak_values("6.5.1-26.7.3")
    assert liblockstepcheck.find_embedded_version_mismatches(values) == []


def test_floating_tag_without_full_embedded_version_reported(liblockstepcheck: ModuleType):
    values = _keycloak_values("6.5.1-26@sha256:aaa")
    findings = liblockstepcheck.find_embedded_version_mismatches(values)
    assert findings == [("keycloak.keycloakConfigCli.image", "tag 6.5.1-26 embeds no full MAJOR.MINOR.PATCH version")]


def test_embedded_version_other_major_reported(liblockstepcheck: ModuleType):
    values = _keycloak_values("6.5.1-25.0.1")
    [(path, problem)] = liblockstepcheck.find_embedded_version_mismatches(values)
    assert path == "keycloak.keycloakConfigCli.image"
    assert "built for major 25" in problem


def test_embedded_version_newer_than_followed_image_reported(liblockstepcheck: ModuleType):
    values = _keycloak_values("6.5.1-26.8.0")
    [(_path, problem)] = liblockstepcheck.find_embedded_version_mismatches(values)
    assert "newer version than keycloak.image 26.7.3" in problem


def test_embedded_version_compares_numerically(liblockstepcheck: ModuleType):
    """26.10.0 is newer than 26.9.0, although lexically smaller."""
    values = _keycloak_values("6.5.1-26.9.0", keycloak_tag="26.10.0")
    assert liblockstepcheck.find_embedded_version_mismatches(values) == []


def test_embedded_version_skipped_when_a_tag_is_missing(liblockstepcheck: ModuleType):
    values = {"keycloak": {"image": {"tag": "26.7.3"}}}
    assert liblockstepcheck.find_embedded_version_mismatches(values) == []


def test_check_lockstep_versions_fails_on_embedded_version_mismatch(
    liblockstepcheck: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    (tmp_path / "Chart.yaml").write_text("apiVersion: v2\nname: podiumd\nversion: 1.0.0\n", encoding="utf-8")
    (tmp_path / "values.yaml").write_text(
        'keycloak:\n  image:\n    tag: "26.7.3"\n  keycloakConfigCli:\n    image:\n      tag: "6.5.1-26"\n',
        encoding="utf-8",
    )
    ok, summary = liblockstepcheck.check_lockstep_versions(tmp_path)
    assert not ok
    assert summary == "1 mismatch(es)"
    assert "keycloak.keycloakConfigCli.image: tag 6.5.1-26 embeds no full" in capsys.readouterr().out
