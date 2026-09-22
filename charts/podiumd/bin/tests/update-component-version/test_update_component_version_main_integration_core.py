"""main() integration (success paths, per-component regression coverage)
and main() handling already-current versions: split out of the former,
monolithic test_update_component_version.py for pylint's too-many-lines
check. block_real_subprocess_calls (used across nearly the whole original
file) now lives in conftest.py as a session-wide autouse fixture."""

import pytest

import lib.image.version as image_version

OLD_DIGEST = "a" * 64


# --- main() integration ---


def setup_repo(tmp_path, monkeypatch, ucv):
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    # written as raw text (not yaml.safe_dump, which alphabetizes keys) so
    # "name:" is the block's first key — same convention as the real
    # Chart.yaml, which update_chart_yaml's line-scan depends on.
    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.296\n"
        '    repository: "@example"\n'
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.0.2@sha256:{OLD_DIGEST}"\n',
        encoding="utf-8",
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)
    return chart_yaml, values_yaml


def mock_registry_passes(monkeypatch, ucv, digest_char="b"):
    """A component whose values.yaml image path has an explicit
    "repository:" (e.g. zac) delegates its tag update to
    lib.image.version.update_image_version, which resolves
    `registry_tag_exists` via ITS OWN globals — not ucv's — so a main()
    test mocking this avoids a real network call for the delegated-path
    write itself. The upfront verification gate (fallback-path digests
    included) is covered separately by mock_verify_passes."""
    digest = "sha256:" + digest_char * 64
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, digest))


def mock_verify_passes(monkeypatch, ucv, digest_char="b", calls=None):
    """Fakes update-component-version's own upfront verify_component_version
    step (a lib.chart.resolve_chart_values call + lib.chart.
    check_image_versions call) so main()'s tests don't need real
    helm/network access. resolve_chart_values/check_image_versions' own
    correctness is covered by tests/lib/test_chart.py — this only fakes
    "the chart version and its images exist", returning FOUND for every
    path passed in. If `calls` is given, each check_image_versions
    invocation's image_paths argument is appended to it — lets a test
    assert the upfront check ran exactly once (no second/fallback
    re-check)."""
    digest = "sha256:" + digest_char * 64

    def fake_check_image_versions(values, image_paths, app_version):
        if calls is not None:
            calls.append(image_paths)
        return [
            {
                "path": p,
                "repository": "ghcr.io/infonl/zaakafhandelcomponent",
                "host": "ghcr.io",
                "repo_path": "infonl/zaakafhandelcomponent",
                "exists": True,
                "digest": digest,
            }
            for p in image_paths
        ]

    monkeypatch.setattr(
        ucv, "resolve_chart_values", lambda chart_dir, dep, version, allow_pull=True: ({}, "vendored", None)
    )
    monkeypatch.setattr(ucv, "check_image_versions", fake_check_image_versions)


def test_main_writes_both_files_when_verify_passes(ucv, tmp_path, monkeypatch):
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()  # success path does not raise

    assert "version: 1.0.297" in chart_yaml.read_text(encoding="utf-8")
    assert f'"5.4.3@sha256:{"b" * 64}"' in values_yaml.read_text(encoding="utf-8")


def test_main_alias_component_argument_bumps_all_registered_lockstep_paths(ucv, tmp_path, monkeypatch):
    """Regression test (real bug, confirmed live against the real chart):
    image_paths_for is keyed by the dependency's own Chart.yaml "name",
    never its alias (see settings.yaml's component_resolution.image_
    paths) — this used to pass the raw <component> CLI argument
    straight through to image_paths_for(component) instead of the
    already-resolved chart_name, so the ALIAS form ("kiss", the shorter,
    more natural one every doc/script elsewhere in this chart uses)
    silently fell back to the generic default_image_paths = ["image"],
    bumping only kiss.image.tag and leaving kiss.settings.syncJobs.
    image.tag — registered as a co-equal lockstep path — completely
    untouched, with no error at all. No settings.yaml override needed
    here — kiss-chart is already registered this way in the real
    component_resolution.image_paths, which lib.settings falls back to
    even with CHART_DIR pointed at this tmp_path (no etc/settings.yaml
    under it)."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: kiss-chart\n"
        "    version: 3.0.0\n"
        '    repository: "@example"\n'
        "    alias: kiss\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        "kiss:\n"
        "  image:\n"
        "    repository: ghcr.io/klantinteractie-servicesysteem/kiss-frontend\n"
        f'    tag: "3.0.0@sha256:{OLD_DIGEST}"\n'
        "  settings:\n"
        "    syncJobs:\n"
        "      image:\n"
        "        repository: ghcr.io/klantinteractie-servicesysteem/kiss-elastic-sync\n"
        f'        tag: "3.0.0@sha256:{OLD_DIGEST}"\n',
        encoding="utf-8",
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "kiss", "3.1.1", "3.1.1"])

    ucv.main()

    written = values_yaml.read_text(encoding="utf-8")
    assert written.count(f'"3.1.1@sha256:{"b" * 64}"') == 2


def test_main_invokes_fix_helm_doc(ucv, tmp_path, monkeypatch, block_real_subprocess_calls):
    """The version/tag bump above changes values.yaml, so README.md's
    helm-docs-generated table can go stale in the same commit if this
    doesn't run — see fix-helm-doc."""
    calls = block_real_subprocess_calls
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    assert any(str(ucv.FIX_HELM_DOC_SCRIPT) in cmd for cmd in calls)


def setup_native_component_repo(tmp_path, monkeypatch, ucv):
    """frankgateway (see lib.chart.NATIVE_COMPONENTS): a real component
    with its own top-level values.yaml key and image, but no Chart.yaml
    dependency at all — implemented via podiumd's own templates instead
    of a vendored sub-chart. Chart.yaml still has a real, unrelated
    dependency (zac) so a test can assert it's left completely
    untouched, not just absent an entry for frankgateway."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.297\n"
        '    repository: "@example"\n'
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        "frankgateway:\n"
        "  image:\n"
        "    repository: ghcr.io/wearefrank/frank-gateway\n"
        f'    tag: "100@sha256:{OLD_DIGEST}"\n',
        encoding="utf-8",
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)
    return chart_yaml, values_yaml


def test_main_native_component_bumps_values_yaml_never_touches_chart_yaml(ucv, tmp_path, monkeypatch):
    """chart-version "native" (case-insensitive) skips find_dependency/
    update_chart_yaml entirely and resolves the image repository straight
    from values.yaml instead of pulling a chart — real end-to-end
    regression coverage for frankgateway, alongside the unit-level
    make_changes_section/values_delta_bullet/update_images_manifest tests
    above."""
    chart_yaml, values_yaml = setup_native_component_repo(tmp_path, monkeypatch, ucv)
    original_chart_yaml = chart_yaml.read_text(encoding="utf-8")
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "frankgateway", "104", "NATIVE"])

    ucv.main()  # success path does not raise

    assert chart_yaml.read_text(encoding="utf-8") == original_chart_yaml
    assert f'"104@sha256:{"b" * 64}"' in values_yaml.read_text(encoding="utf-8")


def test_main_native_component_rejects_unregistered_component(ucv, tmp_path, monkeypatch):
    """ "native" is only valid for a settings.yaml component_resolution.
    native_components component — a real Chart.yaml dependency like zac
    must be rejected with a clear error rather than silently skipping
    its own chart-version bump."""
    setup_native_component_repo(tmp_path, monkeypatch, ucv)
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "native"])

    with pytest.raises(SystemExit, match="native_components"):
        ucv.main()


def setup_keycloak_operator_repo(tmp_path, monkeypatch, ucv):
    """The real values.yaml structure: operator.image has NO override at
    all (relies entirely on the vendored adfinis chart's own
    "{{ .Values.operator.image.tag | default .Chart.AppVersion }}" +
    matching "sha:" default — deliberately not managed by
    update-component-version or settings.yaml's component_resolution.
    image_paths, since an explicit override here would only reintroduce
    a way for tag and digest to drift apart). operator.config.
    keycloakImage IS an explicit, intentional override (a Keycloak
    server version ahead of this operator chart version's own
    appVersion) — the one path this component's component_resolution.
    image_paths entry actually manages."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: keycloak-operator\n"
        "    version: 1.12.1\n"
        '    repository: "@adfinis"\n'
        "    condition: keycloak-operator.enabled\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        "keycloak-operator:\n"
        "  enabled: true\n"
        "  operator:\n"
        "    image:\n"
        "      repository: quay.io/keycloak/keycloak-operator\n"
        "    config:\n"
        "      keycloakImage:\n"
        "        repository: quay.io/keycloak/keycloak\n"
        '        tag: "26.7.2"\n'
        f'        sha: "{OLD_DIGEST}"\n',
        encoding="utf-8",
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)
    return chart_yaml, values_yaml


def test_main_bumps_only_config_keycloak_image_not_operator_image(ucv, tmp_path, monkeypatch):
    """update-component-version keycloak-operator 26.7.3 1.12.1 must
    bump ONLY operator.config.keycloakImage, written as tag + separate
    sha (never a combined @sha256 pin, which would be an invalid double
    digest for the adfinis chart's own template) — operator.image is
    deliberately left completely untouched, with no override added."""
    chart_yaml, values_yaml = setup_keycloak_operator_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv, "b")

    monkeypatch.setattr(ucv, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "d" * 64))
    monkeypatch.setattr("sys.argv", ["update-component-version", "keycloak-operator", "26.7.3", "1.12.1"])

    ucv.main()  # success path does not raise

    updated = values_yaml.read_text(encoding="utf-8")
    assert updated.count('tag: "26.7.3"') == 1
    assert f'sha: "{"d" * 64}"' in updated  # config.keycloakImage's own new sha, replaced
    assert OLD_DIGEST not in updated
    assert "26.7.2" not in updated
    assert "@sha256" not in updated  # never embedded -- would double-digest this chart's template
    # operator.image itself: untouched, still no tag/sha override at all
    assert "  operator:\n    image:\n      repository: quay.io/keycloak/keycloak-operator\n    config:\n" in updated


def setup_eck_operator_repo(tmp_path, monkeypatch, ucv):
    """eck-operator's own upstream chart uses a split "tag:"/"digest:"
    convention (see lib.settings.digest_pinning_exceptions) — confirmed
    against the vendored eck-operator chart's own templates/_helpers.tpl,
    which literally FAILS the render if "image.digest" doesn't start
    with "sha256:" — a stricter requirement than the adfinis keycloak-
    operator chart's own bare-hex "sha:" convention."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: eck-operator\n"
        "    version: 3.5.0\n"
        '    repository: "@example"\n'
        "    condition: eck-operator.enabled\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        "eck-operator:\n"
        "  enabled: true\n"
        "  image:\n"
        "    repository: docker.elastic.co/eck/eck-operator\n"
        '    tag: "3.5.0"\n'
        f'    digest: "sha256:{OLD_DIGEST}"\n',
        encoding="utf-8",
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)
    return chart_yaml, values_yaml


def test_main_eck_operator_writes_digest_field_correctly_regression(ucv, tmp_path, monkeypatch):
    """Regression test for real bug #2 (this iteration's plan): eck-
    operator.image's own sibling field is "digest:", not "sha:" — before
    this fix, locate_tag_and_sha/write_tag_and_sha hardcoded "sha",
    which would have searched for a nonexistent "sha:" line and
    INSERTED a bogus, unused one while leaving the real "digest:" field
    stale (never even reachable in practice before this fix — eck-
    operator wasn't in the write-side allowlist at all). Also confirms
    the WRITTEN value keeps its own "sha256:" prefix — eck-operator's
    own vendored chart literally fails the render if image.digest
    doesn't start with "sha256:" (unlike keycloak's bare-hex "sha:"),
    so writing bare hex here would produce a broken chart, not merely a
    stylistic mismatch."""
    chart_yaml, values_yaml = setup_eck_operator_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    monkeypatch.setattr(ucv, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "e" * 64))
    monkeypatch.setattr("sys.argv", ["update-component-version", "eck-operator", "3.6.0", "3.6.0"])

    ucv.main()  # success path does not raise

    updated = values_yaml.read_text(encoding="utf-8")
    assert 'tag: "3.6.0"' in updated
    assert f'digest: "sha256:{"e" * 64}"' in updated  # correct field, correct sha256: prefix
    assert OLD_DIGEST not in updated
    assert "3.5.0" not in updated
    assert "sha:" not in updated  # never a bogus inserted "sha:" line


def setup_keycloak_operator_repo_with_operator_image_tag(tmp_path, monkeypatch, ucv):
    """Same repo shape as setup_keycloak_operator_repo, but operator.
    image ALSO has an explicit "tag:"/"sha:" override of its own — the
    real, corrected picture confirmed directly against values.yaml for
    real bug #1 (this iteration's plan): operator.image is NOT "left
    with no override at all" as update-component-version's own stale
    comment used to claim; it's pinned ahead of the vendored chart's own
    default for a CVE fix, with its own independent repository (quay.io/
    keycloak/keycloak-operator, distinct from config.keycloakImage's own
    quay.io/keycloak/keycloak)."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: keycloak-operator\n"
        "    version: 1.12.1\n"
        '    repository: "@adfinis"\n'
        "    condition: keycloak-operator.enabled\n",
        encoding="utf-8",
    )
    operator_old_digest = "c" * 64
    values_yaml.write_text(
        "keycloak-operator:\n"
        "  enabled: true\n"
        "  operator:\n"
        "    image:\n"
        "      repository: quay.io/keycloak/keycloak-operator\n"
        '      tag: "26.6.4"\n'
        f'      sha: "{operator_old_digest}"\n'
        "    config:\n"
        "      keycloakImage:\n"
        "        repository: quay.io/keycloak/keycloak\n"
        '        tag: "26.7.2"\n'
        f'        sha: "{OLD_DIGEST}"\n',
        encoding="utf-8",
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)
    return chart_yaml, values_yaml, operator_old_digest


def test_main_keycloak_operator_operator_image_gets_independent_digest_regression(ucv, tmp_path, monkeypatch):
    """Regression test for real bug #1 (this iteration's plan): keycloak-
    operator.operator.image is now included in the write-side allowlist
    (settings.yaml's digest_pinning.exceptions, writable: true) — this
    test registers it via a real tmp_path/etc/settings.yaml override of
    component_resolution.image_paths (the SEPARATE registry controlling
    which paths update-component-version's own <app-version> argument
    actually targets for this component; not itself part of this
    iteration's fix, see the plan's own "no fix needed" note there) so
    both operator.image and operator.config.keycloakImage are bumped in
    the SAME run, each resolving its digest against its OWN, independent
    repository (quay.io/keycloak/keycloak-operator vs. quay.io/keycloak/
    keycloak) — mocking two DIFFERENT registry responses and asserting
    each path gets its own correct digest, never one bleeding into the
    other. A real settings.yaml file is used (not a monkeypatch of a raw
    dict — that constant no longer exists); CHART_DIR is already
    monkeypatched to this tmp_path by the setup helper above, so
    image_paths_for(chart_name, CHART_DIR) picks it up."""
    chart_yaml, values_yaml, operator_old_digest = setup_keycloak_operator_repo_with_operator_image_tag(
        tmp_path, monkeypatch, ucv
    )
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "settings.yaml").write_text(
        "component_resolution:\n"
        "  image_paths:\n"
        '    keycloak-operator: ["operator.image", "operator.config.keycloakImage"]\n',
        encoding="utf-8",
    )
    mock_verify_passes(monkeypatch, ucv)

    operator_digest = "e" * 64
    server_digest = "f" * 64

    def fake_registry_tag_exists(host, repo, tag):
        if repo == "keycloak/keycloak-operator":
            return True, f"sha256:{operator_digest}"
        if repo == "keycloak/keycloak":
            return True, f"sha256:{server_digest}"
        raise AssertionError(f"unexpected repo {host}/{repo}")

    monkeypatch.setattr(ucv, "registry_tag_exists", fake_registry_tag_exists)
    monkeypatch.setattr("sys.argv", ["update-component-version", "keycloak-operator", "26.7.3", "1.12.1"])

    ucv.main()  # success path does not raise

    updated = values_yaml.read_text(encoding="utf-8")
    assert updated.count('tag: "26.7.3"') == 2
    assert f'sha: "{operator_digest}"' in updated  # operator.image's OWN digest
    assert f'sha: "{server_digest}"' in updated  # config.keycloakImage's OWN digest
    assert operator_old_digest not in updated
    assert OLD_DIGEST not in updated
    assert "26.6.4" not in updated
    assert "26.7.2" not in updated


KEYCLOAK_ALIAS_LINES = [
    "keycloak-operator:\n",
    "  operator:\n",
    "    config:\n",
    "      keycloakImage:\n",
    "        repository: quay.io/keycloak/keycloak\n",
    '        tag: &keycloakImageVersion "26.7.2"\n',
    f'        sha: &keycloakImageDigest "{OLD_DIGEST}"\n',
    "keycloak:\n",
    "  image:\n",
    "    repository: quay.io/keycloak/keycloak\n",
    "    tag: *keycloakImageVersion\n",
    "    sha: *keycloakImageDigest\n",
]


def test_write_tag_and_sha_alias_reference_left_untouched_anchor_still_updated_regression(ucv):
    """Regression test for real bug #3 (this iteration's plan): keycloak.
    image's own "tag:"/"sha:" fields are bare YAML alias references
    (*keycloakImageVersion/*keycloakImageDigest) to the anchor keycloak-
    operator.operator.config.keycloakImage defines on its OWN "tag:"/
    "sha:" lines — not independent literals. Before this fix, write_tag_
    and_sha had no alias-awareness at all and would have happily
    clobbered "tag: *keycloakImageVersion" into a literal new value,
    permanently severing the anchor/alias link.

    Confirms: (1) the alias site is left completely untouched (2) the
    ANCHOR's own site DOES get written for real in the same run, with
    its own "&anchor" tag preserved (see lib.chart.replace_scalar_
    value's own anchor-preservation fix — without THAT fix, this would
    silently strip the anchor too, turning the still-untouched "*anchor"
    alias into a dangling reference: a YAML parse error on the very
    next load)."""
    lines = list(KEYCLOAK_ALIAS_LINES)

    # The anchor's own site: keycloak-operator.operator.config.keycloakImage
    anchor_tag_idx, anchor_tag_indent, anchor_sha_idx = ucv.locate_tag_and_sha(
        lines, "keycloak-operator", "operator.config.keycloakImage", "sha"
    )
    ucv.write_tag_and_sha(
        lines,
        (anchor_tag_idx, anchor_tag_indent, anchor_sha_idx),
        ucv.SiblingWrite("26.7.3", "d" * 64, "sha", "keycloak-operator.operator.config.keycloakImage"),
    )

    assert lines[anchor_tag_idx] == '        tag: &keycloakImageVersion "26.7.3"\n'
    assert lines[anchor_sha_idx] == f'        sha: &keycloakImageDigest "{"d" * 64}"\n'

    # The alias site: keycloak.image — same split shape, different values_key
    alias_tag_idx, alias_tag_indent, alias_sha_idx = ucv.locate_tag_and_sha(lines, "keycloak", "image", "sha")
    original_alias_tag_line = lines[alias_tag_idx]
    original_alias_sha_line = lines[alias_sha_idx]

    ucv.write_tag_and_sha(
        lines,
        (alias_tag_idx, alias_tag_indent, alias_sha_idx),
        ucv.SiblingWrite("26.7.3", "d" * 64, "sha", "keycloak.image"),
    )

    # left completely untouched — never clobbered into a literal
    assert lines[alias_tag_idx] == original_alias_tag_line == "    tag: *keycloakImageVersion\n"
    assert lines[alias_sha_idx] == original_alias_sha_line == "    sha: *keycloakImageDigest\n"


def test_main_refuses_to_write_when_verify_fails(ucv, tmp_path, monkeypatch):
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    original_chart = chart_yaml.read_text(encoding="utf-8")
    original_values = values_yaml.read_text(encoding="utf-8")
    monkeypatch.setattr(
        ucv, "resolve_chart_values", lambda chart_dir, dep, version, allow_pull=True: (None, None, "version not found")
    )
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    with pytest.raises(SystemExit) as exc_info:
        ucv.main()
    assert exc_info.value.code == 1
    assert chart_yaml.read_text(encoding="utf-8") == original_chart
    assert values_yaml.read_text(encoding="utf-8") == original_values


def test_main_requires_exactly_three_arguments(ucv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac"])
    with pytest.raises(SystemExit) as exc_info:
        ucv.main()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(ucv, monkeypatch, capsys, flag):
    monkeypatch.setattr("sys.argv", ["update-component-version", flag])
    with pytest.raises(SystemExit) as exc_info:
        ucv.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ucv.__doc__ + "\n"


# --- main() handling already-current versions ---


def test_main_skips_chart_write_when_chart_version_unchanged(ucv, tmp_path, monkeypatch, capsys):
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    original_chart = chart_yaml.read_text(encoding="utf-8")
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    # chart_version matches what's already in Chart.yaml (1.0.296); only app version bumps
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.296"])

    ucv.main()

    assert chart_yaml.read_text(encoding="utf-8") == original_chart  # untouched
    assert f'"5.4.3@sha256:{"b" * 64}"' in values_yaml.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "Chart version already 1.0.296 — unchanged" in out


def test_main_skips_values_write_when_app_version_unchanged(ucv, tmp_path, monkeypatch, capsys):
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    original_values = values_yaml.read_text(encoding="utf-8")
    calls = []
    mock_verify_passes(monkeypatch, ucv, calls=calls)
    # app_version matches the pinned tag's version (5.0.2); only chart version bumps
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.0.2", "1.0.297"])

    ucv.main()

    assert values_yaml.read_text(encoding="utf-8") == original_values  # untouched
    assert "version: 1.0.297" in chart_yaml.read_text(encoding="utf-8")
    assert len(calls) == 1  # only the upfront verify check — no second/fallback re-check
    out = capsys.readouterr().out
    assert "app version already 5.0.2 — unchanged" in out


def test_main_exits_zero_and_writes_nothing_when_both_unchanged(ucv, tmp_path, monkeypatch, capsys):
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    original_chart = chart_yaml.read_text(encoding="utf-8")
    original_values = values_yaml.read_text(encoding="utf-8")
    mock_verify_passes(monkeypatch, ucv)
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.0.2", "1.0.296"])

    with pytest.raises(SystemExit) as exc_info:
        ucv.main()

    assert exc_info.value.code == 0
    assert chart_yaml.read_text(encoding="utf-8") == original_chart
    assert values_yaml.read_text(encoding="utf-8") == original_values
    out = capsys.readouterr().out
    assert "Nothing to update" in out
