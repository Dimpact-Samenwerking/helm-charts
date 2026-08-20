"""find_block_end, find_child_key_line, locate_dotted_key_line,
replace_scalar_value, update_chart_yaml, update_values_yaml, main — pure
logic plus a mocked-subprocess/mocked-registry integration test. No git,
helm, or network access needed."""
import subprocess

import pytest
import yaml


# --- parse_repo ---

def test_parse_repo_bare_docker_hub_official_image(ucv):
    assert ucv.parse_repo("python") == ("docker.io", "library/python")


def test_parse_repo_explicit_host(ucv):
    assert ucv.parse_repo("ghcr.io/infonl/zaakafhandelcomponent") == ("ghcr.io", "infonl/zaakafhandelcomponent")


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
        '    tag: "5.0.2@sha256:aaaa"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    return chart_yaml, values_yaml


def test_main_writes_both_files_when_verify_passes(ucv, tmp_path, monkeypatch):
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0),
    )
    monkeypatch.setattr(ucv, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-component-version.py", "zac", "5.4.3", "1.0.297"])

    ucv.main()  # success path does not raise

    assert "version: 1.0.297" in chart_yaml.read_text(encoding="utf-8")
    assert f'"5.4.3@sha256:{"b" * 64}"' in values_yaml.read_text(encoding="utf-8")


def test_main_refuses_to_write_when_verify_fails(ucv, tmp_path, monkeypatch):
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    original_chart = chart_yaml.read_text(encoding="utf-8")
    original_values = values_yaml.read_text(encoding="utf-8")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1),
    )
    monkeypatch.setattr("sys.argv", ["update-component-version.py", "zac", "5.4.3", "1.0.297"])

    with pytest.raises(SystemExit) as exc_info:
        ucv.main()
    assert exc_info.value.code == 1
    assert chart_yaml.read_text(encoding="utf-8") == original_chart
    assert values_yaml.read_text(encoding="utf-8") == original_values


def test_main_requires_exactly_three_arguments(ucv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["update-component-version.py", "zac"])
    with pytest.raises(SystemExit) as exc_info:
        ucv.main()
    assert exc_info.value.code == 1
