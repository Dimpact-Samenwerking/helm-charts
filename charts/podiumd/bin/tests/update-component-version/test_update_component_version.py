"""find_block_end, find_child_key_line, locate_dotted_key_line,
replace_scalar_value, update_chart_yaml, update_values_yaml, main — mostly
pure logic plus a mocked-subprocess/mocked-registry integration test (no
helm or network access needed). load_baseline_values and the values-deltas
key-change tests use a real, hermetic temp git repo."""
import subprocess

import pytest
import yaml

import lib.image_version as image_version

OLD_DIGEST = "a" * 64


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def block_real_subprocess_calls(monkeypatch):
    """main() shells out to fix-helm-doc via subprocess.run — fake
    that (and anything else) here so a test can't accidentally run the real
    script against the real repo. git commands still run for real, since
    the hermetic tmp-repo tests (git() helper, init_git_repo) need them.
    Returns the list of commands seen, for tests that want to assert what
    main() invoked."""
    calls = []
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if cmd and cmd[0] == "git":
            return real_run(cmd, *args, **kwargs)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


# --- parse_repo ---

# --- find_block_end / find_child_key_line ---

def test_find_block_end_stops_at_dedent(ucv):
    lines = [
        "a:\n",
        "  b: 1\n",
        "  c: 2\n",
        "d: 3\n",
    ]
    assert ucv.find_block_end(lines, 0, 0) == 3


def test_find_child_key_line_ignores_deeper_nested_same_name(ucv):
    lines = [
        "image:\n",
        "  tag: outer\n",
        "  nested:\n",
        "    tag: inner\n",
    ]
    idx = ucv.find_child_key_line(lines, "tag", 0, 0, len(lines))
    assert idx == 1


# --- locate_dotted_key_line ---

def test_locate_dotted_key_line_walks_nested_path(ucv):
    lines = [
        "zac:\n",
        "  opa:\n",
        "    image:\n",
        "      tag: 1.17.1-static@sha256:aaaa\n",
        "  solr:\n",
        "    image:\n",
        "      tag: 9.10.1-slim@sha256:bbbb\n",
    ]
    idx, indent = ucv.locate_dotted_key_line(lines, "zac.opa.image.tag")
    assert idx == 3
    assert indent == 6


def test_locate_dotted_key_line_missing_segment_returns_none(ucv):
    lines = ["zac:\n", "  image:\n", "    tag: 1.0.0\n"]
    assert ucv.locate_dotted_key_line(lines, "zac.frontend.image.tag") is None


# --- locate_parent_block / locate_tag_and_sha / write_tag_and_sha ---

KEYCLOAK_OPERATOR_LINES = [
    "keycloak-operator:\n",
    "  operator:\n",
    "    image:\n",
    "      repository: quay.io/keycloak/keycloak-operator\n",
    '      tag: "26.6.4"\n',
    "    config:\n",
    "      keycloakImage:\n",
    "        repository: quay.io/keycloak/keycloak\n",
    '        tag: "26.7.2"\n',
    '        sha: "831330513f55695572286e521f94fcd3c7e285250ed5b848090265a33192f669"\n',
]


def test_locate_parent_block_returns_own_indent_and_child_range(ucv):
    indent, start, end = ucv.locate_parent_block(KEYCLOAK_OPERATOR_LINES, "keycloak-operator.operator.image")
    assert indent == 4  # "    image:" itself
    assert (start, end) == (3, 5)  # its own children: repository + tag lines


def test_locate_parent_block_missing_segment_returns_none(ucv):
    assert ucv.locate_parent_block(KEYCLOAK_OPERATOR_LINES, "keycloak-operator.nope.image") is None


def test_locate_tag_and_sha_no_existing_sha_override(ucv):
    """operator.image today: podiumd doesn't override "sha" -- the
    vendored subchart's own default applies as-is."""
    tag_idx, tag_indent, sha_idx = ucv.locate_tag_and_sha(
        KEYCLOAK_OPERATOR_LINES, "keycloak-operator", "operator.image")
    assert tag_idx == 4
    assert tag_indent == 6
    assert sha_idx is None


def test_locate_tag_and_sha_existing_sha_override(ucv):
    """operator.config.keycloakImage today: podiumd already overrides
    "sha" explicitly."""
    tag_idx, tag_indent, sha_idx = ucv.locate_tag_and_sha(
        KEYCLOAK_OPERATOR_LINES, "keycloak-operator", "operator.config.keycloakImage")
    assert tag_idx == 8
    assert tag_indent == 8
    assert sha_idx == 9


def test_locate_tag_and_sha_missing_tag_returns_none(ucv):
    lines = ["a:\n", "  image:\n", "    repository: org/repo\n"]
    assert ucv.locate_tag_and_sha(lines, "a", "image") is None


def test_write_tag_and_sha_inserts_new_sha_line_when_absent(ucv):
    lines = list(KEYCLOAK_OPERATOR_LINES)
    tag_idx, tag_indent, sha_idx = ucv.locate_tag_and_sha(lines, "keycloak-operator", "operator.image")
    ucv.write_tag_and_sha(lines, tag_idx, tag_indent, sha_idx, "26.7.2", "b" * 64)
    assert lines[tag_idx] == '      tag: "26.7.2"\n'
    assert lines[tag_idx + 1] == f'      sha: "{"b" * 64}"\n'
    # nothing else shifted/corrupted
    assert lines[tag_idx + 2] == "    config:\n"


def test_write_tag_and_sha_replaces_existing_sha_line(ucv):
    lines = list(KEYCLOAK_OPERATOR_LINES)
    tag_idx, tag_indent, sha_idx = ucv.locate_tag_and_sha(
        lines, "keycloak-operator", "operator.config.keycloakImage")
    ucv.write_tag_and_sha(lines, tag_idx, tag_indent, sha_idx, "26.7.3", "c" * 64)
    assert lines[tag_idx] == '        tag: "26.7.3"\n'
    assert lines[sha_idx] == f'        sha: "{"c" * 64}"\n'
    assert len(lines) == len(KEYCLOAK_OPERATOR_LINES)  # replaced in place, no line added
    assert "831330513f55695572286e521f94fcd3c7e285250ed5b848090265a33192f669" not in "".join(lines)


# --- replace_scalar_value ---

def test_replace_scalar_value_preserves_quotes(ucv):
    assert ucv.replace_scalar_value('      tag: "1.0.0@sha256:aaaa"\n', "2.0.0@sha256:bbbb") == \
        '      tag: "2.0.0@sha256:bbbb"\n'


def test_replace_scalar_value_preserves_bare_style(ucv):
    assert ucv.replace_scalar_value("    version: 1.0.297\n", "1.0.298") == "    version: 1.0.298\n"


def test_replace_scalar_value_preserves_trailing_comment(ucv):
    result = ucv.replace_scalar_value('    version: 1.0.297  # pinned\n', "1.0.298")
    assert result == '    version: 1.0.298  # pinned\n'


# --- update_chart_yaml ---

def write_chart_yaml(path, deps):
    path.write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")


def test_update_chart_yaml_bumps_only_matching_dependency(ucv, tmp_path, monkeypatch):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text(
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.296\n"
        "    repository: \"@zac\"\n"
        "    alias: zac\n"
        "  - name: openzaak\n"
        "    version: 1.14.2\n"
        "    repository: \"@maykinmedia\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    old_line, new_line = ucv.update_chart_yaml("zaakafhandelcomponent", "1.0.297")
    assert "1.0.296" in old_line
    assert "1.0.297" in new_line
    updated = chart_yaml.read_text(encoding="utf-8")
    assert "version: 1.0.297" in updated
    assert "version: 1.14.2" in updated  # untouched


def test_update_chart_yaml_missing_dependency_raises(ucv, tmp_path, monkeypatch):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("dependencies:\n  - name: openzaak\n    version: 1.14.2\n", encoding="utf-8")
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    with pytest.raises(SystemExit):
        ucv.update_chart_yaml("totally-unknown", "9.9.9")


# --- update_values_yaml ---

def test_update_values_yaml_single_image(ucv, tmp_path, monkeypatch):
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text(
        "zac:\n"
        "  image:\n"
        '    tag: "5.0.2@sha256:aaaa"\n'
        "  opa:\n"
        "    image:\n"
        '      tag: "1.17.1-static@sha256:bbbb"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    changes = ucv.update_values_yaml("zac", ["image"], {"image": "5.4.3@sha256:cccc"})
    assert len(changes) == 1
    updated = values_yaml.read_text(encoding="utf-8")
    assert '"5.4.3@sha256:cccc"' in updated
    assert '"1.17.1-static@sha256:bbbb"' in updated  # sidecar untouched


def test_update_values_yaml_multi_image_lockstep(ucv, tmp_path, monkeypatch):
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text(
        "zgw-office-addin:\n"
        "  frontend:\n"
        "    image:\n"
        '      tag: "v0.9.313@sha256:aaaa"\n'
        "  backend:\n"
        "    image:\n"
        '      tag: "v0.9.313@sha256:bbbb"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    changes = ucv.update_values_yaml(
        "zgw-office-addin", ["frontend.image", "backend.image"],
        {"frontend.image": "v0.9.352@sha256:cccc", "backend.image": "v0.9.352@sha256:dddd"},
    )
    assert len(changes) == 2
    updated = values_yaml.read_text(encoding="utf-8")
    assert '"v0.9.352@sha256:cccc"' in updated
    assert '"v0.9.352@sha256:dddd"' in updated
    assert "v0.9.313" not in updated


def test_update_values_yaml_missing_path_raises(ucv, tmp_path, monkeypatch):
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text("zac:\n  image:\n    tag: \"5.0.2@sha256:aaaa\"\n", encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    with pytest.raises(SystemExit):
        ucv.update_values_yaml("zac", ["frontend.image"], {"frontend.image": "1.0.0@sha256:zzzz"})


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
        "    repository: \"@example\"\n"
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        f'    tag: "5.0.2@sha256:{OLD_DIGEST}"\n',
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
    lib.image_version.update_image_version, which resolves
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
        return [{"path": p, "repository": "ghcr.io/infonl/zaakafhandelcomponent", "host": "ghcr.io",
                 "repo_path": "infonl/zaakafhandelcomponent", "exists": True, "digest": digest}
                for p in image_paths]

    monkeypatch.setattr(ucv, "resolve_chart_values", lambda chart_dir, dep, version, allow_pull=True: ({}, "vendored", None))
    monkeypatch.setattr(ucv, "check_image_versions", fake_check_image_versions)


def test_main_writes_both_files_when_verify_passes(ucv, tmp_path, monkeypatch):
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()  # success path does not raise

    assert "version: 1.0.297" in chart_yaml.read_text(encoding="utf-8")
    assert f'"5.4.3@sha256:{"b" * 64}"' in values_yaml.read_text(encoding="utf-8")


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


def setup_keycloak_operator_repo(tmp_path, monkeypatch, ucv):
    """The real values.yaml structure: operator.image has NO override at
    all (relies entirely on the vendored adfinis chart's own
    "{{ .Values.operator.image.tag | default .Chart.AppVersion }}" +
    matching "sha:" default — deliberately not managed by
    update-component-version or lib.chart.COMPONENT_IMAGE_PATHS, since
    an explicit override here would only reintroduce a way for tag and
    digest to drift apart). operator.config.keycloakImage IS an explicit,
    intentional override (a Keycloak server version ahead of this operator
    chart version's own appVersion) — the one path this component's
    COMPONENT_IMAGE_PATHS entry actually manages."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: keycloak-operator\n"
        "    version: 1.12.1\n"
        "    repository: \"@adfinis\"\n"
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


def test_main_refuses_to_write_when_verify_fails(ucv, tmp_path, monkeypatch):
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    original_chart = chart_yaml.read_text(encoding="utf-8")
    original_values = values_yaml.read_text(encoding="utf-8")
    monkeypatch.setattr(ucv, "resolve_chart_values",
                         lambda chart_dir, dep, version, allow_pull=True: (None, None, "version not found"))
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


# --- verify_component_version ---

def test_verify_component_version_returns_upstream_image_results(ucv, monkeypatch):
    dep = {"name": "openforms", "alias": "openformulieren", "version": "1.11.0", "repository": "@maykinmedia"}
    digest = "sha256:" + "c" * 64

    monkeypatch.setattr(
        ucv, "resolve_chart_values",
        lambda chart_dir, dep_arg, version, allow_pull=True: (
            {"image": {"repository": "maykinmedia/open-forms"}}, "pulled", None),
    )
    monkeypatch.setattr(
        ucv, "check_image_versions",
        lambda values, image_paths, app_version: [
            {"path": "image", "repository": "maykinmedia/open-forms", "host": "docker.io",
             "repo_path": "maykinmedia/open-forms", "exists": True, "digest": digest}
        ],
    )
    result = ucv.verify_component_version(dep, ["image"], "3.5.6", "1.12.0")
    assert result == {"image": {"path": "image", "repository": "maykinmedia/open-forms", "host": "docker.io",
                                 "repo_path": "maykinmedia/open-forms", "exists": True, "digest": digest}}


def test_verify_component_version_exits_on_pull_failure(ucv, monkeypatch):
    dep = {"name": "openforms", "repository": "@maykinmedia"}
    monkeypatch.setattr(ucv, "resolve_chart_values",
                         lambda chart_dir, dep_arg, version, allow_pull=True: (None, None, "chart version not found"))
    with pytest.raises(SystemExit):
        ucv.verify_component_version(dep, ["image"], "3.5.6", "9.9.9")


def test_verify_component_version_exits_when_image_does_not_exist(ucv, monkeypatch):
    dep = {"name": "openforms", "repository": "@maykinmedia"}

    monkeypatch.setattr(
        ucv, "resolve_chart_values",
        lambda chart_dir, dep_arg, version, allow_pull=True: (
            {"image": {"repository": "maykinmedia/open-forms"}}, "pulled", None),
    )
    monkeypatch.setattr(
        ucv, "check_image_versions",
        lambda values, image_paths, app_version: [
            {"path": "image", "repository": "maykinmedia/open-forms", "host": "docker.io",
             "repo_path": "maykinmedia/open-forms", "exists": False, "digest": None}
        ],
    )
    with pytest.raises(SystemExit):
        ucv.verify_component_version(dep, ["image"], "9.9.9", "1.12.0")


# --- baseline_doc_paths ---

def test_baseline_doc_paths_finds_pair(ucv, tmp_path, monkeypatch):
    monkeypatch.setattr(ucv, "DOC_DIR", tmp_path)
    write(tmp_path / "4.8.5-to-4.9.0-upgrade.md", "x")
    write(tmp_path / "4.8.5-to-4.9.0-values-deltas.md", "x")
    upgrade_path, values_deltas_path = ucv.baseline_doc_paths("4.8.5", "4.9.0")
    assert upgrade_path == tmp_path / "4.8.5-to-4.9.0-upgrade.md"
    assert values_deltas_path == tmp_path / "4.8.5-to-4.9.0-values-deltas.md"


def test_baseline_doc_paths_missing_values_deltas_is_none(ucv, tmp_path, monkeypatch):
    monkeypatch.setattr(ucv, "DOC_DIR", tmp_path)
    write(tmp_path / "4.8.5-to-4.9.0-upgrade.md", "x")
    upgrade_path, values_deltas_path = ucv.baseline_doc_paths("4.8.5", "4.9.0")
    assert upgrade_path == tmp_path / "4.8.5-to-4.9.0-upgrade.md"
    assert values_deltas_path is None


def test_baseline_doc_paths_no_upgrade_doc_returns_none_none(ucv, tmp_path, monkeypatch):
    monkeypatch.setattr(ucv, "DOC_DIR", tmp_path)
    assert ucv.baseline_doc_paths("4.8.5", "4.9.0") == (None, None)


def test_baseline_doc_paths_no_baseline_returns_none_none(ucv, tmp_path, monkeypatch):
    monkeypatch.setattr(ucv, "DOC_DIR", tmp_path)
    write(tmp_path / "4.8.5-to-4.9.0-upgrade.md", "x")
    assert ucv.baseline_doc_paths(None, "4.9.0") == (None, None)


def write(path, text):
    path.write_text(text, encoding="utf-8")


# --- load_baseline_values ---

def init_git_repo(root):
    git("init", "-q", cwd=root)
    git("config", "user.email", "test@example.com", cwd=root)
    git("config", "user.name", "Test", cwd=root)


def test_load_baseline_values_resolves_real_baseline(ucv, tmp_path, monkeypatch):
    values_yaml = tmp_path / "values.yaml"
    init_git_repo(tmp_path)
    values_yaml.write_text('zac:\n  image:\n    tag: "5.0.2@sha256:aaaa"\n', encoding="utf-8")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    assert ucv.load_baseline_values("4.8.5") == {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}


def test_load_baseline_values_none_when_baseline_tag_missing(ucv, tmp_path, monkeypatch):
    values_yaml = tmp_path / "values.yaml"
    init_git_repo(tmp_path)
    values_yaml.write_text("zac: {}\n", encoding="utf-8")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "only commit, no baseline tag", cwd=tmp_path)

    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    assert ucv.load_baseline_values("9.9.9") is None


def test_load_baseline_values_none_outside_git_repo(ucv, tmp_path, monkeypatch):
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text("zac: {}\n", encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    assert ucv.load_baseline_values("4.8.5") is None


# --- find_component_row / update_component_table ---

def test_find_component_row_matches_by_substring(libcomponentdocs):
    rows = [{"name": "ZAC (Zaakafhandelcomponent)", "line_index": 0}]
    assert libcomponentdocs.find_component_row(rows, "zac")["line_index"] == 0


def test_find_component_row_no_match_returns_none(libcomponentdocs):
    rows = [{"name": "ZAC (Zaakafhandelcomponent)", "line_index": 0}]
    assert libcomponentdocs.find_component_row(rows, "openformulieren") is None


DEPS = [
    {"name": "openformulieren", "version": "1.12.0"},
    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
]
VALUES = {"openformulieren": {}, "zac": {}}


def test_update_component_table_adds_new_row(ucv):
    text = (
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | - |\n"
    )
    new_text, action = ucv.update_component_table(text, "openformulieren", "3.4.10", "3.5.6", "1.12.0", "1.12.0",
                                                    DEPS, VALUES)
    assert action == "added"
    assert "| openformulieren | 3.4.10 → 3.5.6 | 1.12.0 (unchanged) | - |" in new_text
    assert "| zac | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | - |" in new_text  # untouched


def test_update_component_table_new_row_inserted_in_values_yaml_order(ucv):
    """openformulieren comes BEFORE zac in VALUES's own top-level key
    order -- the new row must land above the existing zac row, not always
    appended at the end."""
    text = (
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | - |\n"
    )
    new_text, action = ucv.update_component_table(text, "openformulieren", "3.4.10", "3.5.6", "1.12.0", "1.12.0",
                                                    DEPS, VALUES)
    assert action == "added"
    lines = [l for l in new_text.splitlines() if l.startswith("| zac") or l.startswith("| openformulieren")]
    assert lines == [
        "| openformulieren | 3.4.10 → 3.5.6 | 1.12.0 (unchanged) | - |",
        "| zac | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | - |",
    ]


def test_update_component_table_updates_existing_row(ucv):
    text = (
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openformulieren | 3.4.9 → 3.4.10 | 1.12.0 (unchanged) | - |\n"
    )
    new_text, action = ucv.update_component_table(text, "openformulieren", "3.4.10", "3.5.6", "1.12.0", "1.12.0",
                                                    [], {})
    assert action == "updated"
    assert "| openformulieren | 3.4.10 → 3.5.6 | 1.12.0 (unchanged) | - |" in new_text
    assert "3.4.9" not in new_text


def test_update_component_table_no_table_returns_none_action(ucv):
    text = "# Upgrade guide\n\nJust prose, no table.\n"
    new_text, action = ucv.update_component_table(text, "openformulieren", "3.4.10", "3.5.6", "1.12.0", "1.12.0",
                                                    [], {})
    assert action is None
    assert new_text == text


# --- make_changes_section / insert_changes_section ---

def test_make_changes_section_includes_bullets(ucv):
    section = ucv.make_changes_section(
        "openformulieren", "4.9.0", "openforms", "openformulieren",
        "3.4.10", "3.5.6", "1.12.0", "1.12.0", ["image"],
    )
    assert section.startswith("### openformulieren 3.4.10 → 3.5.6 (chart 1.12.0, unchanged)")
    assert "Image tag pin `openformulieren.image.tag` `3.4.10` → `3.5.6`" in section
    assert "Helm chart" not in section  # chart unchanged, no chart bullet
    assert "images-4.9.0.yaml" in section


def test_make_changes_section_includes_chart_bullet_when_changed(ucv):
    section = ucv.make_changes_section(
        "zac", "4.9.0", "zaakafhandelcomponent", "zac",
        "5.0.2", "5.1.0", "1.0.297", "1.0.257", ["image"],
    )
    assert "Helm chart `zaakafhandelcomponent` `1.0.297` → `1.0.257`" in section


def test_insert_changes_section_appends_before_next_heading(ucv):
    """No existing block resolves to any dependency here ("zac ..." has no
    real version text to anchor match_dependency, and DEPS/VALUES aren't
    supplied) -- falls back to appending at the section end, right before
    the next "## " heading."""
    text = "## Changes\n\n### zac ...\n\nblah\n\n## Per-environment checklist\n\nsteps\n"
    new_text = ucv.insert_changes_section(text, "### openformulieren ...\n\n", "openformulieren", [], {})
    assert new_text.index("### openformulieren") < new_text.index("## Per-environment checklist")
    assert "### zac ..." in new_text


def test_insert_changes_section_inserted_in_values_yaml_order(ucv):
    """openformulieren comes BEFORE zac in VALUES's own top-level key
    order -- the new block must land above the existing zac block, not
    always appended at the end."""
    text = "## Changes\n\n### zac 5.0.2 → 5.1.0 (chart 1.0.297, unchanged)\n\nblah\n"
    new_text = ucv.insert_changes_section(
        text, "### openformulieren 3.4.10 → 3.5.6 (chart 1.12.0, unchanged)\n\n", "openformulieren", DEPS, VALUES)
    assert new_text.index("### openformulieren") < new_text.index("### zac")


def test_insert_changes_section_no_changes_heading_appends_at_end(ucv):
    text = "# Doc\n\nno changes section here\n"
    new_text = ucv.insert_changes_section(text, "### new section\n", "openformulieren", [], {})
    assert new_text.endswith("### new section\n")


# --- values_delta_bullet / describe_key_changes / append_to_doc ---

def test_values_delta_bullet_app_and_chart_changed(ucv):
    bullet = ucv.values_delta_bullet("openformulieren", "3.4.10", "3.5.6", "1.12.0", "1.13.0")
    assert bullet == "- **openformulieren** app `3.4.10 → 3.5.6` (chart `1.12.0 → 1.13.0`) — chart + image tag.\n"


def test_values_delta_bullet_chart_unchanged(ucv):
    bullet = ucv.values_delta_bullet("openformulieren", "3.4.10", "3.5.6", "1.12.0", "1.12.0")
    assert bullet == "- **openformulieren** app `3.4.10 → 3.5.6` (chart `1.12.0`, unchanged) — image tag only.\n"


def test_describe_key_changes_reports_added_removed_renamed(ucv):
    baseline = {"a": 1, "old_name": {"x": 1}}
    current = {"a": 1, "new_name": {"x": 1}, "brand_new": 2}
    lines = ucv.describe_key_changes("comp", baseline, current)
    joined = "".join(lines)
    assert "`comp.brand_new` was added" in joined
    assert "`comp.old_name` was renamed to `comp.new_name`" in joined


def test_describe_key_changes_empty_when_nothing_changed(ucv):
    assert ucv.describe_key_changes("comp", {"a": 1}, {"a": 1}) == []


def test_append_to_doc_adds_blank_line_separator(ucv):
    text = "existing content\n"
    result = ucv.append_to_doc(text, ["- new bullet\n"])
    assert result == "existing content\n\n- new bullet\n"


def test_append_to_doc_no_new_lines_returns_unchanged(ucv):
    text = "existing\n"
    assert ucv.append_to_doc(text, []) == text


# --- values_tree_path_for / find_matching_images_entry / update_images_manifest_entry ---

def test_values_tree_path_for_single_image(libcomponentdocs):
    assert libcomponentdocs.values_tree_path_for("zac", "image") == ("zac",)


def test_values_tree_path_for_nested_image(libcomponentdocs):
    assert libcomponentdocs.values_tree_path_for("zgw-office-addin", "frontend.image") == ("zgw-office-addin", "frontend")


def test_find_matching_images_entry_matches_by_path(libcomponentdocs):
    entries = [{"name": "zac"}, {"name": "zgw-office-addin-frontend"}]
    entry, idx, index = libcomponentdocs.find_matching_images_entry(entries, [0, 1], ("zgw-office-addin", "frontend"))
    assert entry["name"] == "zgw-office-addin-frontend"
    assert idx == 1
    assert index == 1


def test_find_matching_images_entry_none_when_unmatched(libcomponentdocs):
    entries = [{"name": "zac"}]
    entry, idx, index = libcomponentdocs.find_matching_images_entry(entries, [0], ("openformulieren",))
    assert entry is None and idx is None and index is None


def test_update_images_manifest_entry_updates_version_digest_and_comment(libcomponentdocs):
    lines = [
        "# ZAC — 5.0.1 -> 5.1.0\n",
        "- name: zac\n",
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n",
        '  version: "5.1.0"\n',
        '  digest: "sha256:aaaa"\n',
    ]
    entries = [{"name": "zac"}]
    changed = libcomponentdocs.update_images_manifest_entry(lines, entries, [1], 0, "5.4.3@sha256:bbbb", "zac")
    assert changed is True
    assert lines[0] == "# ZAC — 5.0.1 -> 5.4.3\n"
    assert '"5.4.3"' in lines[3]
    assert '"sha256:bbbb"' in lines[4]


def test_update_images_manifest_entry_updates_shared_group_comment(libcomponentdocs):
    """A second entry (backend) sharing the first entry's (frontend)
    comment, separated by a blank line, must still have that shared
    comment's version pair updated — not skipped as "no comment"."""
    lines = [
        "# ZGW Office Add-in — v0.9.313 -> v0.9.352\n",
        "- name: zgw-office-addin-frontend\n",
        '  version: "v0.9.352"\n',
        '  digest: "sha256:aaaa"\n',
        "\n",
        "- name: zgw-office-addin-backend\n",
        '  version: "v0.9.352"\n',
        '  digest: "sha256:bbbb"\n',
    ]
    entries = [{"name": "zgw-office-addin-frontend"}, {"name": "zgw-office-addin-backend"}]
    changed = libcomponentdocs.update_images_manifest_entry(
        lines, entries, [1, 5], 1, "v0.9.400@sha256:cccc", "zgw-office-addin")
    assert changed is True
    assert lines[0] == "# ZGW Office Add-in — v0.9.313 -> v0.9.400\n"
    assert '"v0.9.400"' in lines[6]
    assert '"sha256:cccc"' in lines[7]


# --- update_images_manifest ---

def test_update_images_manifest_updates_existing_entry(ucv, tmp_path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Two changes:\n"
        "#   1. zac 5.0.2 -> 5.1.0 (chart 1.0.297, unchanged).\n"
        "#   2. other 1.0.0 -> 1.0.1 (chart 1.0.0, unchanged).\n"
        "#\n"
        "# ZAC — 5.0.2 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, entry_updates, missing = ucv.update_images_manifest(
        images_path, "zac", "zac", "5.1.0", "5.4.3", "1.0.297", "1.0.297",
        ["image"], {"image": "ghcr.io/infonl/zaakafhandelcomponent"}, {"image": "5.4.3@sha256:cccc"},
    )
    assert changes_action == "updated"
    assert entry_updates == ["zac"]
    assert missing == []
    text = images_path.read_text(encoding="utf-8")
    assert "1. zac 5.1.0 -> 5.4.3 (chart 1.0.297, unchanged)." in text
    assert '"5.4.3"' in text
    assert '"sha256:cccc"' in text


def test_update_images_manifest_reports_missing_entry(ucv, tmp_path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# One change:\n"
        "#   1. zac 5.0.2 -> 5.1.0 (chart 1.0.297, unchanged).\n"
        "#\n"
        "# ZAC — 5.0.2 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, entry_updates, missing = ucv.update_images_manifest(
        images_path, "openformulieren", "openformulieren", "3.4.10", "3.5.6", "1.12.0", "1.12.0",
        ["image"], {"image": "openformulieren/open-forms"}, {"image": "3.5.6@sha256:dddd"},
    )
    assert changes_action == "added"
    assert entry_updates == []
    assert missing == [("image", "openformulieren/open-forms", "3.5.6@sha256:dddd")]
    text = images_path.read_text(encoding="utf-8")
    assert "Two changes:" in text
    assert "2. openformulieren 3.4.10 -> 3.5.6 (chart 1.12.0, unchanged)." in text


def test_update_images_manifest_new_item_lands_after_continuation_line(ucv, tmp_path):
    """A new item must be appended after the LAST item's continuation
    comment line, not immediately after its numbered line — otherwise it
    gets spliced in the middle of the previous item's own comment block."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Two changes:\n"
        "#   1. zac 5.0.1 -> 5.1.0 (chart 1.0.251 -> 1.0.257).\n"
        "#   2. zgw-office-addin v0.9.313 -> v0.9.352 (chart 0.0.89, unchanged).\n"
        "#      Repository names (zgw-office-addin-{frontend,backend}) unchanged from 4.8.5.\n"
        "#\n"
        "# ZAC — 5.0.1 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, entry_updates, missing = ucv.update_images_manifest(
        images_path, "openformulieren", "openformulieren", "3.4.10", "3.5.6", "1.12.0", "1.12.0",
        ["image"], {"image": "openformulieren/open-forms"}, {"image": "3.5.6@sha256:dddd"},
    )
    assert changes_action == "added"
    lines = images_path.read_text(encoding="utf-8").splitlines()
    assert lines[3] == "#      Repository names (zgw-office-addin-{frontend,backend}) unchanged from 4.8.5."
    assert lines[4] == "#   3. openformulieren 3.4.10 -> 3.5.6 (chart 1.12.0, unchanged)."
    assert lines[5] == "#"


# --- main() integration: doc updates end-to-end ---

def setup_docs(ucv, monkeypatch, upgrade_text, values_deltas_text=None, images_text=None):
    write(ucv.CHART_DIR / "release-baseline.yaml", 'upgrade_docs: "4.8.5"\n')
    doc_dir = ucv.DOC_DIR
    write(doc_dir / "4.8.5-to-4.9.0-upgrade.md", upgrade_text)
    if values_deltas_text is not None:
        write(doc_dir / "4.8.5-to-4.9.0-values-deltas.md", values_deltas_text)
    if images_text is not None:
        write(ucv.IMAGES_DIR / "images-4.9.0.yaml", images_text)


def test_main_adds_new_component_mention_end_to_end(ucv, tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch, ucv)
    setup_docs(
        ucv, monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n\n"
            "## Changes\n\n"
            "## Per-environment checklist\n\nsteps\n"
        ),
        values_deltas_text=(
            "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
            "**No gemeente `podiumd.yml` changes are required for this hop.**\n"
        ),
        images_text=(
            "# One change:\n"
            "#   1. zac 5.0.2 -> 5.1.0 (chart 1.0.297, unchanged).\n"
            "#\n"
            "# ZAC — 5.0.2 -> 5.1.0\n"
            "- name: zac\n"
            '  version: "5.1.0"\n'
            '  digest: "sha256:aaaa"\n'
        ),
    )
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "c")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| zac | 5.0.2 → 5.4.3 | 1.0.296 → 1.0.297 | - |" in upgrade
    assert "### zac 5.0.2 → 5.4.3 (chart 1.0.296 → 1.0.297)" in upgrade
    assert "Helm chart `zaakafhandelcomponent` `1.0.296` → `1.0.297`" in upgrade
    assert "Image tag pin `zac.image.tag` `5.0.2` → `5.4.3`" in upgrade
    # inserted before the next "## " heading, not after it
    assert upgrade.index("### zac") < upgrade.index("## Per-environment checklist")

    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "**zac** app `5.0.2 → 5.4.3` (chart `1.0.296 → 1.0.297`) — chart + image tag." in deltas

    images = (ucv.IMAGES_DIR / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "1. zac 5.0.2 -> 5.4.3 (chart 1.0.296 -> 1.0.297)." in images
    assert '"5.4.3"' in images
    assert f'"sha256:{"c" * 64}"' in images


def test_main_updates_existing_component_mention_end_to_end(ucv, tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch, ucv)
    setup_docs(
        ucv, monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n"
            "| zac | 5.0.1 → 5.0.2 | 1.0.296 (unchanged) | - |\n\n"
            "## Changes\n\n"
            "### zac 5.0.1 → 5.0.2 (chart 1.0.296, unchanged)\n\nblah\n"
        ),
    )
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "d")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| zac | 5.0.2 → 5.4.3 | 1.0.296 → 1.0.297 | - |" in upgrade
    assert "| zac | 5.0.1 → 5.0.2 |" not in upgrade  # old row content is gone
    # the existing Changes section is rewritten from scratch (not left
    # stale, not duplicated) to match the table row's own new transition —
    # the old "5.0.1 → 5.0.2" heading is gone entirely
    assert upgrade.count("### zac") == 1
    assert "### zac 5.0.1 → 5.0.2" not in upgrade
    assert "### zac 5.0.2 → 5.4.3 (chart 1.0.296 → 1.0.297)" in upgrade


# --- main() vs the TRUE git baseline: reset-to-baseline removal, and
# collapsing more than one bump in a release cycle into a single entry ---

def commit_baseline_tag(tmp_path):
    init_git_repo(tmp_path)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)


def test_main_removes_all_docs_when_reset_back_to_baseline(ucv, tmp_path, monkeypatch):
    """A component bumped once (baseline 5.0.2 -> 5.5.0, already fully
    documented) and then reset all the way back to its baseline version
    has nothing left to report: the table row, Changes section,
    values-delta bullet, and images-manifest 'changes:' entry/comment
    must all be removed, not left describing a transition that no longer
    happened net of baseline. The manifest ENTRY itself must still show
    the correct (baseline) version/digest -- it lists every image
    regardless of change-tracking."""
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    commit_baseline_tag(tmp_path)  # baseline: chart 1.0.296, zac 5.0.2@sha256:aaaa...

    # Simulate "already bumped to 5.5.0 earlier in this release cycle" --
    # chart version stays at baseline (1.0.296), only the app tag moved.
    values_yaml.write_text(
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        f'    tag: "5.5.0@sha256:{OLD_DIGEST}"\n',
        encoding="utf-8",
    )
    setup_docs(
        ucv, monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n"
            "| zac | 5.0.2 → 5.5.0 | 1.0.296 (unchanged) | - |\n\n"
            "## Changes\n\n"
            "### zac 5.0.2 → 5.5.0 (chart 1.0.296, unchanged)\n\nblah\n"
        ),
        values_deltas_text=(
            "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
            "- **zac** app `5.0.2 → 5.5.0` (chart `1.0.296`, unchanged) — image tag only.\n"
        ),
        images_text=(
            "# One change:\n"
            "#   1. zac 5.0.2 -> 5.5.0 (chart 1.0.296, unchanged).\n"
            "#\n\n"
            "# zac — 5.0.2 -> 5.5.0\n"
            "- name: zac\n"
            "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
            '  version: "5.5.0"\n'
            f'  digest: "sha256:{OLD_DIGEST}"\n'
        ),
    )
    mock_verify_passes(monkeypatch, ucv)
    # Same digest baseline already recorded -- re-resolving 5.0.2 (a real,
    # immutable released version) from the registry always returns this
    # same digest, exactly like it would outside this mocked test.
    mock_registry_passes(monkeypatch, ucv, "a")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.0.2", "1.0.296"])

    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| zac |" not in upgrade
    assert "### zac" not in upgrade

    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "**zac**" not in deltas

    images = (ucv.IMAGES_DIR / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "Zero changes:" in images
    assert "zac 5.0.2" not in images  # the numbered "changes:" list item is gone
    assert "# zac —" not in images  # the entry's now-stale source comment is gone too
    assert '"5.0.2"' in images  # the entry itself still lists the correct (reset) version


def test_main_collapses_repeated_bump_into_single_baseline_entry(ucv, tmp_path, monkeypatch):
    """Bumping zac to 5.4.3 and then, within the same release cycle,
    reconsidering to 5.5.0 instead must leave exactly ONE entry in each
    doc showing baseline -> final (5.0.2 -> 5.5.0) -- never two entries,
    and never an intermediate-hop transition like "5.4.3 -> 5.5.0"."""
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    commit_baseline_tag(tmp_path)  # baseline: chart 1.0.296, zac 5.0.2@sha256:aaaa...
    setup_docs(
        ucv, monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n\n"
            "## Changes\n\n"
        ),
        values_deltas_text="# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n",
        images_text=(
            "# Baseline: podiumd 4.8.5.\n"
            "#\n"
            "# Zero changes:\n"
            "#\n\n"
            "- name: zac\n"
            "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
            '  version: "5.0.2"\n'
            f'  digest: "sha256:{OLD_DIGEST}"\n'
        ),
    )
    mock_verify_passes(monkeypatch, ucv)

    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])
    ucv.main()

    mock_registry_passes(monkeypatch, ucv, "c")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.5.0", "1.0.297"])
    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert upgrade.count("| zac |") == 1
    assert "| zac | 5.0.2 → 5.5.0 | 1.0.296 → 1.0.297 | - |" in upgrade
    assert "5.4.3" not in upgrade
    assert upgrade.count("### zac") == 1
    assert "### zac 5.0.2 → 5.5.0 (chart 1.0.296 → 1.0.297)" in upgrade

    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert deltas.count("**zac**") == 1
    assert "5.4.3" not in deltas
    assert "**zac** app `5.0.2 → 5.5.0` (chart `1.0.296 → 1.0.297`) — chart + image tag." in deltas

    images = (ucv.IMAGES_DIR / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "One change:" in images
    assert "5.4.3" not in images
    assert "1. zac 5.0.2 -> 5.5.0 (chart 1.0.296 -> 1.0.297)." in images
    assert '"5.5.0"' in images
    assert f'"sha256:{"c" * 64}"' in images


def test_main_skips_doc_updates_when_no_upgrade_doc_exists(ucv, tmp_path, monkeypatch, capsys):
    setup_repo(tmp_path, monkeypatch, ucv)
    write(tmp_path / "release-baseline.yaml", 'upgrade_docs: "4.8.5"\n')  # baseline known, doc itself just missing
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "e")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()  # must not raise even though no docs exist

    out = capsys.readouterr().out
    assert "No upgrade doc found for target 4.9.0" in out


def test_main_skips_doc_updates_when_no_release_baseline(ucv, tmp_path, monkeypatch, capsys):
    setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "e")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()  # must not raise even though release-baseline.yaml doesn't exist

    out = capsys.readouterr().out
    assert "No release-baseline.yaml upgrade_docs key found" in out


# --- main(): values-deltas key-change detection against the real baseline ---

def setup_git_repo_for_baseline_test(tmp_path, monkeypatch, ucv):
    """A real git repo with a baseline commit tagged podiumd-4.8.5, then a
    values.yaml schema key added on top — as if someone hand-edited it to
    prepare this hop, BEFORE running update-component-version. That
    ordering is exactly what the old before/after-this-script-run comparison
    could never see (the key was already present on both sides of that
    comparison); comparing against the real git baseline must catch it."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    images_dir = tmp_path / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    init_git_repo(tmp_path)
    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.296\n"
        "    repository: \"@example\"\n"
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        '    tag: "5.0.2@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n',
        encoding="utf-8",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    # the schema edit, made BEFORE update-component-version ever runs
    values_yaml.write_text(
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        '    tag: "5.0.2@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n'
        "  newFeature:\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    (tmp_path / "release-baseline.yaml").write_text('upgrade_docs: "4.8.5"\n', encoding="utf-8")

    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)


def test_main_detects_key_added_before_running_against_real_baseline(ucv, tmp_path, monkeypatch):
    setup_git_repo_for_baseline_test(tmp_path, monkeypatch, ucv)
    write(ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n\n"
          "## Changes\n\n")
    write(ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md",
          "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
          "**No gemeente `podiumd.yml` changes are required for this hop.**\n")

    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "e")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "Key `zac.newFeature` was added." in deltas


def test_main_notes_when_baseline_unresolvable_for_key_detection(ucv, tmp_path, monkeypatch, capsys):
    """setup_repo's plain tmp_path (no git init) can't resolve any baseline —
    main() must say so and continue (still write the version bullet), not
    silently skip the note or crash."""
    setup_repo(tmp_path, monkeypatch, ucv)
    write(tmp_path / "release-baseline.yaml", 'upgrade_docs: "4.8.5"\n')
    write(ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n\n"
          "## Changes\n\n")
    write(ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md",
          "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
          "**No gemeente `podiumd.yml` changes are required for this hop.**\n")

    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "f")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    out = capsys.readouterr().out
    assert "could not resolve upgrade_docs_baseline 4.8.5" in out
    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "**zac** app" in deltas  # version bullet still written


def test_main_touches_only_the_target_component_end_to_end(ucv, tmp_path, monkeypatch):
    """Bumping zac must not modify anything belonging to a different
    component (openformulieren here) — its Chart.yaml entry, values.yaml
    subtree, upgrade.md row + Changes section, values-deltas.md mention,
    and images-manifest entry must all be byte-for-byte unchanged."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    images_dir = tmp_path / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.296\n"
        "    repository: \"@example\"\n"
        "    alias: zac\n"
        "  - name: openforms\n"
        "    version: 1.12.0\n"
        "    repository: \"@maykinmedia\"\n"
        "    alias: openformulieren\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        f'    tag: "5.0.2@sha256:{OLD_DIGEST}"\n'
        "openformulieren:\n"
        "  someFeature:\n"
        "    enabled: true\n"
        "  image:\n"
        "    repository: maykinmedia/open-forms\n"
        '    tag: "3.4.10@sha256:bbbb"\n',
        encoding="utf-8",
    )
    upgrade_text = (
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openformulieren | 3.4.9 → 3.4.10 | 1.12.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### openformulieren 3.4.9 → 3.4.10 (chart 1.12.0, unchanged)\n\nblah\n"
    )
    values_deltas_text = (
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
        "- **openformulieren** app `3.4.9 → 3.4.10` (chart `1.12.0`, unchanged) — image tag only.\n"
    )
    images_text = (
        "# One change:\n"
        "#   1. openformulieren 3.4.9 -> 3.4.10 (chart 1.12.0, unchanged).\n"
        "#\n"
        "# Open Formulieren — 3.4.9 -> 3.4.10\n"
        "- name: openformulieren\n"
        '  version: "3.4.10"\n'
        '  digest: "sha256:bbbb"\n'
    )
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(upgrade_text, encoding="utf-8")
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(values_deltas_text, encoding="utf-8")
    (images_dir / "images-4.9.0.yaml").write_text(images_text, encoding="utf-8")
    (tmp_path / "release-baseline.yaml").write_text('upgrade_docs: "4.8.5"\n', encoding="utf-8")

    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)

    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "c")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    # zac itself changed, as expected
    assert "version: 1.0.297" in chart_yaml.read_text(encoding="utf-8")

    # openformulieren: untouched everywhere
    chart_after = chart_yaml.read_text(encoding="utf-8")
    assert "name: openforms" in chart_after
    assert "version: 1.12.0" in chart_after

    values_after = values_yaml.read_text(encoding="utf-8")
    assert "someFeature" in values_after
    assert '"3.4.10@sha256:bbbb"' in values_after

    upgrade_after = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| openformulieren | 3.4.9 → 3.4.10 | 1.12.0 (unchanged) | - |" in upgrade_after
    assert "### openformulieren 3.4.9 → 3.4.10 (chart 1.12.0, unchanged)" in upgrade_after
    assert upgrade_after.count("### openformulieren") == 1

    deltas_after = (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert values_deltas_text in deltas_after  # openformulieren's own line, verbatim, still there

    images_after = (images_dir / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "1. openformulieren 3.4.9 -> 3.4.10 (chart 1.12.0, unchanged)." in images_after
    assert '"3.4.10"' in images_after
    assert "sha256:bbbb" in images_after
