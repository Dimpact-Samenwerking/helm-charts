"""main() integration: success paths, per-component regressions, and
already-current versions."""

import subprocess

from pathlib import Path
from types import ModuleType

import pytest

import lib.image.version as image_version

from lib.chart import values_tag_sha_lines as tag_sha_lines

OLD_DIGEST = "a" * 64


# --- main() integration ---


def setup_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ucv: ModuleType):
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    # Raw text, not yaml.safe_dump (alphabetizes keys): update_chart_yaml's
    # line-scan needs "name:" first, as in the real Chart.yaml.
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


def mock_registry_passes(monkeypatch: pytest.MonkeyPatch, ucv: ModuleType, digest_char="b"):
    """Mock registry_tag_exists in lib.image.version: the delegated tag update
    for explicit-repository images resolves it via that module's globals."""
    digest = "sha256:" + digest_char * 64
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, digest))


def mock_verify_passes(monkeypatch: pytest.MonkeyPatch, ucv: ModuleType, digest_char="b", calls=None):
    """Fake the upfront verify_component_version step (FOUND for every path)
    so tests need no helm/network. If `calls` is given, each
    check_image_versions image_paths argument is appended, to assert the
    check ran exactly once."""
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


def test_main_writes_both_files_when_verify_passes(ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()  # success path does not raise

    assert "version: 1.0.297" in chart_yaml.read_text(encoding="utf-8")
    assert f'"5.4.3@sha256:{"b" * 64}"' in values_yaml.read_text(encoding="utf-8")


def test_main_alias_component_argument_bumps_all_registered_lockstep_paths(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: image_paths_for is keyed by Chart.yaml name, not alias, so
    the alias argument ("kiss") must be resolved first; otherwise it falls
    back to ["image"] and silently skips the lockstep syncJobs image tag."""
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


def test_main_invokes_fix_helm_doc(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, block_real_subprocess_calls
):
    """values.yaml changed, so fix-helm-doc must run or README.md goes stale."""
    calls = block_real_subprocess_calls
    _chart_yaml, _values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    assert any(str(ucv.FIX_HELM_DOC_SCRIPT) in cmd for cmd in calls)


def test_main_fails_when_fix_helm_doc_fails(ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A failing fix-helm-doc leaves README.md stale, so main() must stop."""
    setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "git":
            return real_run(cmd, *args, **kwargs)
        return subprocess.CompletedProcess(cmd, 3 if str(ucv.FIX_HELM_DOC_SCRIPT) in cmd else 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    with pytest.raises(SystemExit, match=r"fix-helm-doc failed \(exit 3\)"):
        ucv.main()


def test_main_re_vendors_after_writing_chart_yaml(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, block_real_subprocess_calls
):
    """The Chart.yaml bump leaves charts/ and Chart.lock stale: main() must
    re-vendor last (after fix-helm-doc) so the next script starts in sync."""
    calls = block_real_subprocess_calls
    chart_yaml, _values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])
    ensured = []

    def record_ensure(chart_dir):
        ensured.append((len(calls), "version: 1.0.297" in chart_yaml.read_text(encoding="utf-8")))

    monkeypatch.setattr(ucv, "ensure_vendored_dependencies", record_ensure)

    ucv.main()

    fix_helm_doc_index = next(i for i, cmd in enumerate(calls) if str(ucv.FIX_HELM_DOC_SCRIPT) in cmd)
    assert len(ensured) == 2
    calls_before_last_ensure, chart_yaml_bumped = ensured[-1]
    assert chart_yaml_bumped
    assert calls_before_last_ensure > fix_helm_doc_index


def test_main_runs_fix_doc_consistency_after_re_vendoring(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bump ends with fix-doc-consistency, after the re-vendor its
    images-baseline.yaml render needs."""
    setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])
    order: list[str] = []

    def record_ensure(_chart_dir: Path) -> None:
        order.append("ensure")

    def record_fix_doc() -> None:
        order.append("fix-doc")

    monkeypatch.setattr(ucv, "ensure_vendored_dependencies", record_ensure)
    monkeypatch.setattr(ucv, "complete_docs_and_finish", record_fix_doc)

    ucv.main()

    assert order[-2:] == ["ensure", "fix-doc"]


def setup_native_component_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ucv: ModuleType):
    """frankgateway: a native component (own values.yaml key and image, no
    Chart.yaml dependency). zac is present to assert Chart.yaml is untouched."""
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


def test_main_native_component_bumps_values_yaml_never_touches_chart_yaml(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """chart-version "native" skips the Chart.yaml bump and resolves the image
    repository from values.yaml (frankgateway end-to-end)."""
    chart_yaml, values_yaml = setup_native_component_repo(tmp_path, monkeypatch, ucv)
    original_chart_yaml = chart_yaml.read_text(encoding="utf-8")
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "frankgateway", "104", "NATIVE"])

    ucv.main()  # success path does not raise

    assert chart_yaml.read_text(encoding="utf-8") == original_chart_yaml
    assert f'"104@sha256:{"b" * 64}"' in values_yaml.read_text(encoding="utf-8")


def test_main_native_component_name_ignores_case(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _chart_yaml, values_yaml = setup_native_component_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "FrankGateway", "104", "native"])

    ucv.main()

    assert f'"104@sha256:{"b" * 64}"' in values_yaml.read_text(encoding="utf-8")


def test_main_native_component_rejects_unregistered_component(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """ "native" is rejected for a real Chart.yaml dependency rather than
    silently skipping its chart bump."""
    setup_native_component_repo(tmp_path, monkeypatch, ucv)
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "native"])

    with pytest.raises(SystemExit, match="native_components"):
        ucv.main()


NEW_KEYCLOAK_DIGEST = "d" * 64
KEYCLOAK_OLD_DIGEST = "c" * 64


def setup_keycloak_operator_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ucv: ModuleType):
    """Real values.yaml shape: keycloak.image (native server image) holds the
    &keycloakImage* anchors; keycloak-operator.operator.image is pinned
    explicitly; operator.config.keycloakImage aliases the anchors. Both use
    split "tag:" + "sha:", and versions move independently."""
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
        "keycloak:\n"
        "  image:\n"
        "    repository: &keycloakImageRepo quay.io/keycloak/keycloak\n"
        '    tag: &keycloakImageVersion "26.7.2"\n'
        f'    sha: &keycloakImageDigest "{KEYCLOAK_OLD_DIGEST}"\n'
        "keycloak-operator:\n"
        "  enabled: true\n"
        "  operator:\n"
        "    image:\n"
        "      repository: quay.io/keycloak/keycloak-operator\n"
        '      tag: "26.7.2"\n'
        f'      sha: "{OLD_DIGEST}"\n'
        "    config:\n"
        "      keycloakImage:\n"
        "        repository: *keycloakImageRepo\n"
        "        tag: *keycloakImageVersion\n"
        "        sha: *keycloakImageDigest\n",
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


KEYCLOAK_ALIAS_BLOCK = (
    "    config:\n"
    "      keycloakImage:\n"
    "        repository: *keycloakImageRepo\n"
    "        tag: *keycloakImageVersion\n"
    "        sha: *keycloakImageDigest\n"
)


def test_main_keycloak_operator_bumps_only_operator_image_not_server_image(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Bumping keycloak-operator writes only operator.image as tag + separate
    sha (a combined @sha256 would double-digest the adfinis template); the
    server image is left untouched."""
    _chart_yaml, values_yaml = setup_keycloak_operator_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv, "b")

    monkeypatch.setattr(ucv, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + NEW_KEYCLOAK_DIGEST))
    monkeypatch.setattr("sys.argv", ["update-component-version", "keycloak-operator", "26.7.3", "1.12.1"])

    ucv.main()  # success path does not raise

    updated = values_yaml.read_text(encoding="utf-8")
    assert (
        "    image:\n"
        "      repository: quay.io/keycloak/keycloak-operator\n"
        '      tag: "26.7.3"\n'
        f'      sha: "{NEW_KEYCLOAK_DIGEST}"\n'
    ) in updated
    assert OLD_DIGEST not in updated
    assert "@sha256" not in updated  # never embedded -- would double-digest this chart's template
    # the server image: anchors and aliases untouched
    assert '    tag: &keycloakImageVersion "26.7.2"\n' in updated
    assert f'    sha: &keycloakImageDigest "{KEYCLOAK_OLD_DIGEST}"\n' in updated
    assert KEYCLOAK_ALIAS_BLOCK in updated


def test_main_native_keycloak_bumps_server_image_anchor_site_only(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Bumping native keycloak writes the server image at its anchor site as
    tag + sha; the aliases follow; operator.image and Chart.yaml untouched."""
    chart_yaml, values_yaml = setup_keycloak_operator_repo(tmp_path, monkeypatch, ucv)
    original_chart_yaml = chart_yaml.read_text(encoding="utf-8")
    mock_verify_passes(monkeypatch, ucv, "b")

    monkeypatch.setattr(ucv, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + NEW_KEYCLOAK_DIGEST))
    monkeypatch.setattr("sys.argv", ["update-component-version", "keycloak", "26.7.3", "native"])

    ucv.main()  # success path does not raise

    updated = values_yaml.read_text(encoding="utf-8")
    assert chart_yaml.read_text(encoding="utf-8") == original_chart_yaml
    assert '    tag: &keycloakImageVersion "26.7.3"\n' in updated
    assert f'    sha: &keycloakImageDigest "{NEW_KEYCLOAK_DIGEST}"\n' in updated
    assert KEYCLOAK_OLD_DIGEST not in updated
    assert "@sha256" not in updated
    assert KEYCLOAK_ALIAS_BLOCK in updated
    # operator.image: untouched
    assert f'      tag: "26.7.2"\n      sha: "{OLD_DIGEST}"\n' in updated


def setup_eck_operator_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ucv: ModuleType):
    """eck-operator uses split "tag:"/"digest:", and its _helpers.tpl fails
    the render unless image.digest starts with "sha256:"."""
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


def test_main_eck_operator_writes_digest_field_correctly_regression(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: eck-operator's sibling field is "digest:", not "sha:";
    it must be updated in place (no bogus "sha:" inserted) and keep the
    "sha256:" prefix its chart requires."""
    _chart_yaml, values_yaml = setup_eck_operator_repo(tmp_path, monkeypatch, ucv)
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


def setup_keycloak_operator_repo_with_operator_image_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ucv: ModuleType
):
    """Like setup_keycloak_operator_repo, but operator.image also has its own
    tag/sha override (pinned ahead of the chart default for a CVE fix) with
    its own repository, distinct from config.keycloakImage's."""
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


def test_main_keycloak_operator_operator_image_gets_independent_digest_regression(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: with both operator.image and operator.config.keycloakImage
    registered (via a tmp etc/settings.yaml), one run bumps both, each
    resolving its digest against its own repository, never swapped."""
    _chart_yaml, values_yaml, operator_old_digest = setup_keycloak_operator_repo_with_operator_image_tag(
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
        msg = f"unexpected repo {host}/{repo}"
        raise AssertionError(msg)

    monkeypatch.setattr(ucv, "registry_tag_exists", fake_registry_tag_exists)
    monkeypatch.setattr("sys.argv", ["update-component-version", "keycloak-operator", "26.7.3", "1.12.1"])

    ucv.main()  # success path does not raise

    updated = values_yaml.read_text(encoding="utf-8")
    assert updated.count('tag: "26.7.3"') == 2
    # Each path gets its own repository's digest, never swapped.
    assert (
        f'      repository: quay.io/keycloak/keycloak-operator\n      tag: "26.7.3"\n      sha: "{operator_digest}"\n'
    ) in updated
    assert (
        f'        repository: quay.io/keycloak/keycloak\n        tag: "26.7.3"\n        sha: "{server_digest}"\n'
    ) in updated
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


def test_write_tag_and_sha_alias_reference_left_untouched_anchor_still_updated_regression():
    """Regression: keycloak.image's tag/sha are aliases of the anchors on
    operator.config.keycloakImage. The alias site must stay untouched and
    the anchor site be written with its "&anchor" kept; dropping it would
    leave a dangling alias (YAML parse error)."""
    lines = list(KEYCLOAK_ALIAS_LINES)

    # The anchor's own site: keycloak-operator.operator.config.keycloakImage
    located = tag_sha_lines.locate_tag_and_sha(lines, "keycloak-operator", "operator.config.keycloakImage", "sha")
    assert located is not None
    anchor_tag_idx, anchor_tag_indent, anchor_sha_idx = located
    assert anchor_sha_idx is not None
    assert tag_sha_lines.write_tag_and_sha(
        lines,
        (anchor_tag_idx, anchor_tag_indent, anchor_sha_idx),
        tag_sha_lines.SiblingWrite("26.7.3", "d" * 64, "sha", "keycloak-operator.operator.config.keycloakImage"),
    )

    assert lines[anchor_tag_idx] == '        tag: &keycloakImageVersion "26.7.3"\n'
    assert lines[anchor_sha_idx] == f'        sha: &keycloakImageDigest "{"d" * 64}"\n'

    # The alias site: keycloak.image — same split shape, different values_key
    located = tag_sha_lines.locate_tag_and_sha(lines, "keycloak", "image", "sha")
    assert located is not None
    alias_tag_idx, alias_tag_indent, alias_sha_idx = located
    assert alias_sha_idx is not None
    original_alias_tag_line = lines[alias_tag_idx]
    original_alias_sha_line = lines[alias_sha_idx]

    tag_written = tag_sha_lines.write_tag_and_sha(
        lines,
        (alias_tag_idx, alias_tag_indent, alias_sha_idx),
        tag_sha_lines.SiblingWrite("26.7.3", "d" * 64, "sha", "keycloak.image"),
    )

    assert tag_written is False

    # never clobbered into a literal
    assert lines[alias_tag_idx] == original_alias_tag_line == "    tag: *keycloakImageVersion\n"
    assert lines[alias_sha_idx] == original_alias_sha_line == "    sha: *keycloakImageDigest\n"


def test_main_refuses_to_write_when_verify_fails(ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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


def test_main_requires_exactly_three_arguments(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac"])
    with pytest.raises(SystemExit) as exc_info:
        ucv.main()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(
    ucv: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag
):
    monkeypatch.setattr("sys.argv", ["update-component-version", flag])
    with pytest.raises(SystemExit) as exc_info:
        ucv.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"{ucv.__doc__}\n"


# --- main() handling already-current versions ---


def test_main_skips_chart_write_when_chart_version_unchanged(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
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


def test_main_skips_values_write_when_app_version_unchanged(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
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


def test_main_writes_no_versions_but_completes_docs_when_both_unchanged(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A rerun after a half-finished run: versions already at target, docs still completed."""
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    original_chart = chart_yaml.read_text(encoding="utf-8")
    original_values = values_yaml.read_text(encoding="utf-8")
    mock_verify_passes(monkeypatch, ucv)
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.0.2", "1.0.296"])

    ucv.main()

    assert chart_yaml.read_text(encoding="utf-8") == original_chart
    assert values_yaml.read_text(encoding="utf-8") == original_values
    out = capsys.readouterr().out
    assert "already at the requested versions; completing docs" in out
    assert "Regenerating README.md (fix-helm-doc)" in out
