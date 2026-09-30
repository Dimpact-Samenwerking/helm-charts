"""compare(): keycloak-operator's anchor-decorated split tag/sha image,
basenames pinned under a sibling scope, and check_images_source's
vendored-subchart-default fallback. In-memory inputs; no Chart.yaml or network."""

from pathlib import Path
from types import ModuleType

import pytest
import yaml


def csv_row(name, component, alias="", image_basename="", source_app="", source_helm="", target_app="", target_helm=""):
    return {
        "section": "Product",
        "vendor": "",
        "used_by": "",
        "name": name,
        "component": component,
        "alias": alias,
        "image_basename": image_basename,
        "source_version_app": source_app,
        "source_version_helm": source_helm,
        "target_version_app": target_app,
        "target_version_helm": target_helm,
    }


def values_lines(*blocks):
    return "\n".join(blocks).splitlines()


CLAMAV_CURRENT_BLOCK = (
    f'clamav:\n  image:\n    repository: docker.io/clamav/clamav\n    tag: "1.5.3@sha256:{"a" * 64}"\n'
)
CLAMAV_BASELINE_BLOCK = (
    "clamav:\n"
    "  image:\n"
    '    tag: "1.5.2"\n'  # no repository override at all — the real 4.8.5 shape
)
CLAMAV_BASELINE_VALUES = {"clamav": {"image": {"tag": "1.5.2"}}}


# --- compare(): keycloak-operator's own anchor-decorated split tag/sha image ---

KEYCLOAK_BLOCK = (
    "keycloak-operator:\n"
    "  operator:\n"
    "    config:\n"
    "      keycloakImage:\n"
    "        repository: &keycloakImageRepo quay.io/keycloak/keycloak\n"
    '        tag: &keycloakImageVersion "{tag}"\n'
    '        sha: &keycloakImageDigest "deadbeef"\n'
)


def keycloak_values(tag="26.7.2"):
    return yaml.safe_load(KEYCLOAK_BLOCK.format(tag=tag))


def keycloak_lines(tag="26.7.2"):
    return values_lines(KEYCLOAK_BLOCK.format(tag=tag))


def test_compare_checks_keycloak_anchor_decorated_image(vrt: ModuleType):
    """keycloak-operator's server image is a split "tag:"/"sha:" pair with
    per-scalar YAML anchors; the normal any_tag scan resolves it using the
    real settings.yaml image_paths registration."""
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [csv_row("Keycloak", "keycloak-operator", image_basename="keycloak", target_app="26.7.3")]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, keycloak_values(), keycloak_lines()))
    assert any("target 26.7.3 != values.yaml 26.7.2" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings


def test_compare_keycloak_anchor_decorated_image_matching_passes(vrt: ModuleType):
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [
        csv_row("Keycloak", "keycloak-operator", image_basename="keycloak", source_helm="1.12.1", target_app="26.7.2")
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, keycloak_values(), keycloak_lines()))
    assert findings == {}


def test_compare_finds_basename_pinned_under_a_sibling_scope(vrt: ModuleType):
    """A basename is a repository identity, not a values.yaml path, so
    keycloak-config-cli pinned under sibling "keycloak" is found via the
    whole-file fallback (as resolve_basename does)."""
    keycloak_config_cli_block = (
        "keycloak:\n"
        "  keycloakConfigCli:\n"
        "    image:\n"
        "      repository: adorsys/keycloak-config-cli\n"
        f'      tag: "6.5.1-26@sha256:{"c" * 64}"\n'
    )
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [
        csv_row("Keycloak Config CLI", "keycloak-operator", image_basename="keycloak-config-cli", target_app="6.5.2-27")
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(keycloak_config_cli_block)))
    assert any("target 6.5.2-27 != values.yaml 6.5.1-26" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings


def test_compare_sibling_scope_basename_matching_passes(vrt: ModuleType):
    keycloak_config_cli_block = (
        "keycloak:\n"
        "  keycloakConfigCli:\n"
        "    image:\n"
        "      repository: adorsys/keycloak-config-cli\n"
        f'      tag: "6.5.1-26@sha256:{"c" * 64}"\n'
    )
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [
        csv_row(
            "Keycloak Config CLI",
            "keycloak-operator",
            image_basename="keycloak-config-cli",
            source_helm="1.12.1",
            target_app="6.5.1-26",
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(keycloak_config_cli_block)))
    assert findings == {}


def test_compare_image_source_sibling_scope_basename_still_matches(vrt: ModuleType):
    """The legitimate sibling-scope case must keep resolving now that the
    baseline-side unscoped fallback is cross-checked against the current
    chart's repository."""
    current_block = (
        "keycloak:\n"
        "  keycloakConfigCli:\n"
        "    image:\n"
        "      repository: adorsys/keycloak-config-cli\n"
        f'      tag: "6.5.2-27@sha256:{"c" * 64}"\n'
    )
    baseline_block = (
        "keycloak:\n"
        "  keycloakConfigCli:\n"
        "    image:\n"
        "      repository: adorsys/keycloak-config-cli\n"
        f'      tag: "6.5.1-26@sha256:{"c" * 64}"\n'
    )
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    baseline_deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.0"}]
    rows = [
        csv_row(
            "Keycloak Config CLI",
            "keycloak-operator",
            image_basename="keycloak-config-cli",
            source_app="6.5.1-26",
            target_app="6.5.2-27",
            source_helm="1.12.0",
            target_helm="1.12.1",
        )
    ]
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(current_block)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(baseline_block)),
    )
    assert findings == {}


def test_compare_image_source_rejects_stripped_name_collision(vrt: ModuleType):
    """Regression: redis-operator's unrelated quay.io/opstree/redis pin (also
    basename "redis") must not be accepted as global.images.redis's baseline
    value; the image is reported as never pinned at that baseline."""
    current_block = f'global:\n  images:\n    redis:\n      repository: redis\n      tag: "8.0@sha256:{"d" * 64}"\n'
    baseline_block = (
        "redis-operator:\n"
        "  redis-ha:\n"
        "    image:\n"
        "      repository: quay.io/opstree/redis\n"
        f'      tag: "v8.6.2@sha256:{"e" * 64}"\n'
    )
    rows = [csv_row("Redis", "MULTIPLE", alias="MULTIPLE", image_basename="redis", source_app="8.0")]
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, [], {}, values_lines(current_block)),
        baseline=vrt.ChartState(None, [], {}, values_lines(baseline_block)),
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "wasn't pinned anywhere" in m and "release_table baseline yet" in m
        for m in findings["mismatches"]
    )
    assert not any("8.6.2" in m for m in findings["mismatches"])


# --- check_images_source: vendored-subchart-default fallback ---
# At podiumd-4.8.5 several components pinned only "tag:" and relied on the
# subchart's default repository. primary_image_repositories is patched on
# lib.release_table_verification (its resolution is tested elsewhere).


def test_compare_image_source_falls_back_to_vendored_subchart_default(vrt: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Regression: the fallback yields a comparable baseline version instead
    of "wasn't pinned anywhere"; a matching source_app is OK."""
    monkeypatch.setattr(
        "lib.release_table_verification.primary_image_repositories",
        lambda chart_dir, dep, values, allow_pull=True: ({"image": "docker.io/clamav/clamav"}, None),
    )
    dep = {"name": "clamav", "version": "3.9.0"}
    baseline_dep = {"name": "clamav", "version": "3.7.1"}
    rows = [
        csv_row(
            "ClamAV",
            "clamav",
            image_basename="clamav",
            source_app="1.5.2",
            target_app="1.5.3",
            source_helm="3.7.1",
            target_helm="3.9.0",
        )
    ]
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(Path("/fake/chart/dir"), [dep], {}, values_lines(CLAMAV_CURRENT_BLOCK)),
        baseline=vrt.ChartState(
            Path("/fake/chart/dir"), [baseline_dep], CLAMAV_BASELINE_VALUES, values_lines(CLAMAV_BASELINE_BLOCK)
        ),
    )
    assert findings == {}


def test_compare_image_source_vendored_subchart_default_still_catches_mismatch(
    vrt: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    """A fallback-resolved baseline that disagrees with the CSV source is
    still reported, with a distinct wording."""
    monkeypatch.setattr(
        "lib.release_table_verification.primary_image_repositories",
        lambda chart_dir, dep, values, allow_pull=True: ({"image": "docker.io/clamav/clamav"}, None),
    )
    dep = {"name": "clamav", "version": "3.9.0"}
    baseline_dep = {"name": "clamav", "version": "3.7.1"}
    rows = [
        csv_row(
            "ClamAV",
            "clamav",
            image_basename="clamav",
            source_app="1.5.9",
            target_app="1.5.3",
            source_helm="3.7.1",
            target_helm="3.9.0",
        )
    ]
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(Path("/fake/chart/dir"), [dep], {}, values_lines(CLAMAV_CURRENT_BLOCK)),
        baseline=vrt.ChartState(
            Path("/fake/chart/dir"), [baseline_dep], CLAMAV_BASELINE_VALUES, values_lines(CLAMAV_BASELINE_BLOCK)
        ),
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "source 1.5.9" in m and "baseline subchart-default values.yaml 1.5.2" in m
        for m in findings["mismatches"]
    )
    assert not any("wasn't pinned anywhere" in m for m in findings.get("mismatches", []))


def test_compare_image_source_vendored_subchart_default_resolution_failure_is_reported_honestly(
    vrt: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    """A pull failure is a distinct "can't verify" finding, never "wasn't
    pinned anywhere" (something was pinned) and never a crash."""
    monkeypatch.setattr(
        "lib.release_table_verification.primary_image_repositories",
        lambda chart_dir, dep, values, allow_pull=True: ({"image": None}, "helm pull failed: no such chart version"),
    )
    dep = {"name": "clamav", "version": "3.9.0"}
    baseline_dep = {"name": "clamav", "version": "3.7.1"}
    rows = [
        csv_row(
            "ClamAV",
            "clamav",
            image_basename="clamav",
            source_app="1.5.2",
            target_app="1.5.3",
            source_helm="3.7.1",
            target_helm="3.9.0",
        )
    ]
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(Path("/fake/chart/dir"), [dep], {}, values_lines(CLAMAV_CURRENT_BLOCK)),
        baseline=vrt.ChartState(
            Path("/fake/chart/dir"), [baseline_dep], CLAMAV_BASELINE_VALUES, values_lines(CLAMAV_BASELINE_BLOCK)
        ),
    )
    assert any(
        "[IMAGE-SOURCE]" in m
        and "couldn't be resolved to verify" in m
        and "helm pull failed: no such chart version" in m
        for m in findings["ambiguous"]
    )
    assert not any("wasn't pinned anywhere" in m for m in findings.get("mismatches", []))


# omc's image has no active "repository:" (only a commented-out sibling) and
# no digest; its row's image_basename is "notifynl-omc", resolved by the
# digest-optional scanner via resolve_pin_repo's commented-sibling fallback.
OMC_BLOCK = 'omc:\n  image:\n    # repository: docker.io/worthnl/notifynl-omc\n    tag: "1.17.19"\n'


def test_compare_omc_image_matches_via_ordinary_basename_path(vrt: ModuleType):
    """omc's row goes through the standard basename-matching path."""
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    rows = [
        csv_row(
            "OMC / Notify",
            "notifynl-omc-nodep",
            alias="omc",
            image_basename="notifynl-omc",
            target_app="1.17.19",
            target_helm="0.14.1",
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(OMC_BLOCK)))
    assert findings == {}


def test_compare_omc_image_mismatch_via_ordinary_basename_path(vrt: ModuleType):
    """A target that disagrees with the pin is an [IMAGE] mismatch."""
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    rows = [
        csv_row(
            "OMC / Notify",
            "notifynl-omc-nodep",
            alias="omc",
            image_basename="notifynl-omc",
            target_app="1.17.20",
            target_helm="0.14.1",
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(OMC_BLOCK)))
    assert any("[IMAGE]" in m and "target 1.17.20 != values.yaml 1.17.19" in m for m in findings["mismatches"])


def test_compare_omc_image_source_matches_via_ordinary_basename_path(vrt: ModuleType):
    """omc's row also works on the source side (check_images_source)."""
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    baseline_deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.0"}]
    rows = [
        csv_row(
            "OMC / Notify",
            "notifynl-omc-nodep",
            alias="omc",
            image_basename="notifynl-omc",
            source_app="1.17.19",
            target_helm="0.14.1",
        )
    ]
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(OMC_BLOCK)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(OMC_BLOCK)),
    )
    assert findings == {}


def test_compare_omc_image_source_mismatch_via_ordinary_basename_path(vrt: ModuleType):
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    baseline_deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.0"}]
    rows = [
        csv_row("OMC / Notify", "notifynl-omc-nodep", alias="omc", image_basename="notifynl-omc", source_app="1.17.18")
    ]
    omc_baseline_block = 'omc:\n  image:\n    # repository: docker.io/worthnl/notifynl-omc\n    tag: "1.17.19"\n'
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(OMC_BLOCK)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(omc_baseline_block)),
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "source 1.17.18 != baseline values.yaml 1.17.19" in m for m in findings["mismatches"]
    )


def test_compare_omc_still_catches_genuinely_untracked_sibling_basename(vrt: ModuleType):
    """A different, untracked basename in the same scope is still reported."""
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    rows = [
        csv_row(
            "OMC / Notify",
            "notifynl-omc-nodep",
            alias="omc",
            image_basename="notifynl-omc",
            target_app="1.17.19",
            target_helm="0.14.1",
        )
    ]
    omc_block_with_sidecar = OMC_BLOCK + (
        f'  sidecar:\n    image:\n      repository: example/some-other-image\n      tag: "2.0.0@sha256:{"a" * 64}"\n'
    )

    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(omc_block_with_sidecar)))
    assert any(
        "'some-other-image' is pinned in values.yaml but not tracked" in m
        for m in findings["missing_from_release_table"]
    )
