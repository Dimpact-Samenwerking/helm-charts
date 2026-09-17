"""compare() (the pure comparison core) for verify-release-table-with-podiumd:
keycloak-operator's own anchor-decorated split tag/sha image, basenames
pinned under a sibling scope, and the vendored-subchart-default fallback for
check_images_source (clamav/omc-style components with no "repository:"
override of their own). compare() takes plain in-memory deps/values/lines/
rows, so these tests need neither a real Chart.yaml nor network access.

Split out of test_verify_release_table_with_podiumd.py (pylint
too-many-lines) -- purely a test reorganization, no behavior change. See the
sibling test_verify_release_table_with_podiumd_*.py files for the rest of
that suite."""

from pathlib import Path

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
# (used to need a dedicated special-case workaround here -- see lib.image_
# digests' own anchor-tolerant VERSION_PIN_RE/ACTIVE_REPO_RE fix, which lets
# the normal basenames_under_scope_any_tag scan resolve this image directly)

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


def test_compare_checks_keycloak_anchor_decorated_image(vrt):
    """keycloak-operator's own actual Keycloak SERVER image lives as a
    split "tag:"/"sha:" field pair, each defined via its own per-scalar
    YAML anchor (aliased by a sibling "keycloak.image" block elsewhere in
    the real file) — basenames_under_scope_any_tag resolves it via the
    normal scan, using the real production settings.yaml default (this
    test passes no chart_dir, so image_paths_for("keycloak-operator")
    self-resolves to it — a real component_resolution.image_paths
    registration, not a synthetic override)."""
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [csv_row("Keycloak", "keycloak-operator", image_basename="keycloak", target_app="26.7.3")]
    findings, _ = vrt.compare(rows, deps, keycloak_values(), keycloak_lines())
    assert any("target 26.7.3 != values.yaml 26.7.2" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings


def test_compare_keycloak_anchor_decorated_image_matching_passes(vrt):
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [
        csv_row("Keycloak", "keycloak-operator", image_basename="keycloak", source_helm="1.12.1", target_app="26.7.2")
    ]
    findings, _ = vrt.compare(rows, deps, keycloak_values(), keycloak_lines())
    assert findings == {}


def test_compare_finds_basename_pinned_under_a_sibling_scope(vrt):
    """keycloak-config-cli lives under top-level "keycloak" (a values.yaml
    sibling block, separate from keycloak-operator's own scope) — a
    basename is a real repository identity, not a values.yaml path, so it
    can be pinned somewhere other than its own component's scope. Found
    via the same whole-file find_matches fallback update-image-version's
    own <target> resolution uses (lib.image_version.resolve_basename)."""
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(keycloak_config_cli_block))
    assert any("target 6.5.2-27 != values.yaml 6.5.1-26" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings


def test_compare_sibling_scope_basename_matching_passes(vrt):
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(keycloak_config_cli_block))
    assert findings == {}


def test_compare_image_source_sibling_scope_basename_still_matches(vrt):
    """The EXISTING working case (keycloak-config-cli, a real image
    pinned under a SIBLING scope — see test_compare_finds_basename_
    pinned_under_a_sibling_scope) must still resolve correctly once the
    baseline-side unscoped fallback gets its own cross-check against the
    CURRENT chart's own real repository for the same <scope, basename>:
    this is the legitimate case the fallback exists for, and must never
    regress just because a DIFFERENT, coincidental collision (see below)
    now gets rejected."""
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
        deps,
        {},
        values_lines(current_block),
        baseline_deps=baseline_deps,
        baseline_values={},
        baseline_lines=values_lines(baseline_block),
    )
    assert findings == {}


def test_compare_image_source_rejects_stripped_name_collision(vrt):
    """Regression test: the same real redis/redis-operator basename
    collision fixed twice already today (lib.chart.historical_app_
    version_for_repository/find_images_manifest_list_diff, commits
    c3b27bed/9b9680c1) applies equally to THIS function's own unscoped
    find_matches_any_tag fallback. global.images.redis genuinely doesn't
    exist yet at this baseline; redis-operator's own, completely
    unrelated quay.io/opstree/redis pin (which also reduces to bare
    basename "redis") must never be accepted as if it were global.
    images.redis's own baseline value — the baseline is correctly
    reported as never having had this image pinned at all, not silently
    matched to the wrong one."""
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
        [],
        {},
        values_lines(current_block),
        baseline_deps=[],
        baseline_values={},
        baseline_lines=values_lines(baseline_block),
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "wasn't pinned anywhere" in m and "release_table baseline yet" in m
        for m in findings["mismatches"]
    )
    assert not any("8.6.2" in m for m in findings["mismatches"])


# --- check_images_source: vendored-subchart-default fallback ---
# Real bug, real chart: at podiumd-4.8.5, brp-personen-mock/clamav/kiss's own
# crawler/objecten/open-klant/zaakbrug each had only an explicit "tag:" for
# their own primary image, no "repository:" override at all — relying
# entirely on their vendored subchart's own default repository, exactly like
# primary_image_basename's own CURRENT-side fallback already handles (see
# lib.chart.primary_image_repositories). primary_image_repositories itself
# is monkeypatched here (rather than vendoring a real .tgz or hitting the
# network) — its own pull/vendored-tgz resolution already has its own test
# coverage elsewhere; these tests are purely about check_images_source's own
# NEW consumption of it (matching a resolved repository to `basename`,
# reading the ACTUAL pinned tag from baseline_values, and degrading
# gracefully on failure).


def test_compare_image_source_falls_back_to_vendored_subchart_default(vrt, monkeypatch):
    """Regression test: the vendored-subchart-default fallback resolves a
    real, comparable baseline version instead of reporting "wasn't pinned
    anywhere" — the matching source_app must be accepted as OK."""
    monkeypatch.setattr(
        vrt,
        "primary_image_repositories",
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
        [dep],
        {},
        values_lines(CLAMAV_CURRENT_BLOCK),
        chart_dir=Path("/fake/chart/dir"),
        baseline_deps=[baseline_dep],
        baseline_values=CLAMAV_BASELINE_VALUES,
        baseline_lines=values_lines(CLAMAV_BASELINE_BLOCK),
    )
    assert findings == {}


def test_compare_image_source_vendored_subchart_default_still_catches_mismatch(vrt, monkeypatch):
    """The mirror-image case: the vendored-subchart-default fallback DOES
    resolve a real baseline version, and it genuinely disagrees with
    release-table.csv's own claimed source — still reported, just via a
    distinctly-worded finding (never silently accepted just because it
    took a different resolution path than the plain text scan)."""
    monkeypatch.setattr(
        vrt,
        "primary_image_repositories",
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
        [dep],
        {},
        values_lines(CLAMAV_CURRENT_BLOCK),
        chart_dir=Path("/fake/chart/dir"),
        baseline_deps=[baseline_dep],
        baseline_values=CLAMAV_BASELINE_VALUES,
        baseline_lines=values_lines(CLAMAV_BASELINE_BLOCK),
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "source 1.5.9" in m and "baseline subchart-default values.yaml 1.5.2" in m
        for m in findings["mismatches"]
    )
    assert not any("wasn't pinned anywhere" in m for m in findings.get("mismatches", []))


def test_compare_image_source_vendored_subchart_default_resolution_failure_is_reported_honestly(vrt, monkeypatch):
    """A pull failure (no network, or the historical chart version
    genuinely no longer exists) must never be silently forced into
    "wasn't pinned anywhere" (actively wrong: something WAS pinned, this
    just couldn't confirm what) or crash — it's a distinct, honest
    "can't verify" finding instead."""
    monkeypatch.setattr(
        vrt,
        "primary_image_repositories",
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
        [dep],
        {},
        values_lines(CLAMAV_CURRENT_BLOCK),
        chart_dir=Path("/fake/chart/dir"),
        baseline_deps=[baseline_dep],
        baseline_values=CLAMAV_BASELINE_VALUES,
        baseline_lines=values_lines(CLAMAV_BASELINE_BLOCK),
    )
    assert any(
        "[IMAGE-SOURCE]" in m
        and "couldn't be resolved to verify" in m
        and "helm pull failed: no such chart version" in m
        for m in findings["ambiguous"]
    )
    assert not any("wasn't pinned anywhere" in m for m in findings.get("mismatches", []))


# omc's own "image:" tag has no ACTIVE "repository:" key at all (a
# commented-out sibling instead) — its subchart can't handle a digest,
# so export-confluence-release-table's own resolve_image_basenames now
# falls back to the digest-OPTIONAL scanner for it, and its release-
# table.csv row's image_basename column is a real, non-blank
# "notifynl-omc" (see export-confluence-release-table's own module
# docstring) — the exact same row shape every other component's row
# already has, no special-casing needed anywhere downstream any more.
# THIS script's own digest-OPTIONAL scanner (scan_version_pins, via
# resolve_pin_repo's own commented-out-sibling fallback) resolves the
# same basename regardless — real values.yaml shape, not a synthetic one.
OMC_BLOCK = 'omc:\n  image:\n    # repository: docker.io/worthnl/notifynl-omc\n    tag: "1.17.19"\n'


def test_compare_omc_image_matches_via_ordinary_basename_path(vrt):
    """omc's row now round-trips through the completely standard
    basename-matching path check_images already applies to every other
    component — no special-casing at all, just a real, non-blank
    image_basename column ("notifynl-omc")."""
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(OMC_BLOCK))
    assert findings == {}


def test_compare_omc_image_mismatch_via_ordinary_basename_path(vrt):
    """Same ordinary path, but the target version genuinely disagrees
    with what's actually pinned — must still be caught as a real
    [IMAGE] mismatch, exactly like any other component's row."""
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(OMC_BLOCK))
    assert any("[IMAGE]" in m and "target 1.17.20 != values.yaml 1.17.19" in m for m in findings["mismatches"])


def test_compare_omc_image_source_matches_via_ordinary_basename_path(vrt):
    """The baseline/source-side sibling (check_images_source) — omc's
    row round-trips there too, with no special-casing needed."""
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
        deps,
        {},
        values_lines(OMC_BLOCK),
        baseline_deps=baseline_deps,
        baseline_values={},
        baseline_lines=values_lines(OMC_BLOCK),
    )
    assert findings == {}


def test_compare_omc_image_source_mismatch_via_ordinary_basename_path(vrt):
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    baseline_deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.0"}]
    rows = [
        csv_row("OMC / Notify", "notifynl-omc-nodep", alias="omc", image_basename="notifynl-omc", source_app="1.17.18")
    ]
    omc_baseline_block = 'omc:\n  image:\n    # repository: docker.io/worthnl/notifynl-omc\n    tag: "1.17.19"\n'
    findings, _ = vrt.compare(
        rows,
        deps,
        {},
        values_lines(OMC_BLOCK),
        baseline_deps=baseline_deps,
        baseline_values={},
        baseline_lines=values_lines(omc_baseline_block),
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "source 1.17.18 != baseline values.yaml 1.17.19" in m for m in findings["mismatches"]
    )


def test_compare_omc_still_catches_genuinely_untracked_sibling_basename(vrt):
    """Negative case: a DIFFERENT, genuinely-untracked basename under
    the same component's own scope must still be reported as missing —
    unaffected by omc's own row now having a real, non-blank
    image_basename."""
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

    findings, _ = vrt.compare(rows, deps, {}, values_lines(omc_block_with_sidecar))
    assert any(
        "'some-other-image' is pinned in values.yaml but not tracked" in m
        for m in findings["missing_from_release_table"]
    )
