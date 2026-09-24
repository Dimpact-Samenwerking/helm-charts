"""parse_repo through update_values_yaml: pure YAML/text helper functions,
no main() integration tests (split out of the former, monolithic
test_update_component_version.py for pylint's too-many-lines check)."""

from pathlib import Path
from types import ModuleType

import pytest
import yaml

from lib.chart import values_tag_sha_lines as tag_sha_lines

# --- parse_repo ---

# --- find_block_end / find_child_key_line ---


def test_find_block_end_stops_at_dedent():
    lines = [
        "a:\n",
        "  b: 1\n",
        "  c: 2\n",
        "d: 3\n",
    ]
    assert tag_sha_lines.find_block_end(lines, 0, 0) == 3


def test_find_child_key_line_ignores_deeper_nested_same_name():
    lines = [
        "image:\n",
        "  tag: outer\n",
        "  nested:\n",
        "    tag: inner\n",
    ]
    idx = tag_sha_lines.find_child_key_line(lines, "tag", 0, 0, len(lines))
    assert idx == 1


def test_find_child_key_line_returns_none_when_only_a_deeper_nested_match_exists():
    """No direct "tag:" child: the grandchild's "tag:" under a sibling
    sub-block must not be returned as if it were one."""
    lines = [
        "image:\n",
        "  other: 1\n",
        "  nested:\n",
        "    tag: inner\n",
    ]
    assert tag_sha_lines.find_child_key_line(lines, "tag", 0, 0, len(lines)) is None


# --- locate_dotted_key_line ---


def test_locate_dotted_key_line_walks_nested_path():
    lines = [
        "zac:\n",
        "  opa:\n",
        "    image:\n",
        "      tag: 1.17.1-static@sha256:aaaa\n",
        "  solr:\n",
        "    image:\n",
        "      tag: 9.10.1-slim@sha256:bbbb\n",
    ]
    located = tag_sha_lines.locate_dotted_key_line(lines, "zac.opa.image.tag")
    assert located is not None
    idx, indent = located
    assert idx == 3
    assert indent == 6


def test_locate_dotted_key_line_missing_segment_returns_none():
    lines = ["zac:\n", "  image:\n", "    tag: 1.0.0\n"]
    assert tag_sha_lines.locate_dotted_key_line(lines, "zac.frontend.image.tag") is None


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


def test_locate_parent_block_returns_own_indent_and_child_range():
    located = tag_sha_lines.locate_parent_block(KEYCLOAK_OPERATOR_LINES, "keycloak-operator.operator.image")
    assert located is not None
    indent, start, end = located
    assert indent == 4  # "    image:" itself
    assert (start, end) == (3, 5)  # its own children: repository + tag lines


def test_locate_parent_block_missing_segment_returns_none():
    assert tag_sha_lines.locate_parent_block(KEYCLOAK_OPERATOR_LINES, "keycloak-operator.nope.image") is None


def test_locate_tag_and_sha_no_existing_sha_override():
    """operator.image today: podiumd doesn't override "sha" -- the
    vendored subchart's own default applies as-is."""
    located = tag_sha_lines.locate_tag_and_sha(KEYCLOAK_OPERATOR_LINES, "keycloak-operator", "operator.image", "sha")
    assert located is not None
    tag_idx, tag_indent, sha_idx = located
    assert tag_idx == 4
    assert tag_indent == 6
    assert sha_idx is None


def test_locate_tag_and_sha_existing_sha_override():
    """operator.config.keycloakImage today: podiumd already overrides
    "sha" explicitly."""
    located = tag_sha_lines.locate_tag_and_sha(
        KEYCLOAK_OPERATOR_LINES, "keycloak-operator", "operator.config.keycloakImage", "sha"
    )
    assert located is not None
    tag_idx, tag_indent, sha_idx = located
    assert tag_idx == 8
    assert tag_indent == 8
    assert sha_idx == 9


def test_locate_tag_and_sha_missing_tag_returns_none():
    lines = ["a:\n", "  image:\n", "    repository: org/repo\n"]
    assert tag_sha_lines.locate_tag_and_sha(lines, "a", "image", "sha") is None


def test_write_tag_and_sha_inserts_new_sha_line_when_absent():
    lines = list(KEYCLOAK_OPERATOR_LINES)
    located = tag_sha_lines.locate_tag_and_sha(lines, "keycloak-operator", "operator.image", "sha")
    assert located is not None
    tag_idx, tag_indent, sha_idx = located
    tag_sha_lines.write_tag_and_sha(
        lines,
        (tag_idx, tag_indent, sha_idx),
        tag_sha_lines.SiblingWrite("26.7.2", "b" * 64, "sha", "keycloak-operator.operator.image"),
    )
    assert lines[tag_idx] == '      tag: "26.7.2"\n'
    assert lines[tag_idx + 1] == f'      sha: "{"b" * 64}"\n'
    # nothing else shifted/corrupted
    assert lines[tag_idx + 2] == "    config:\n"


def test_write_tag_and_sha_replaces_existing_sha_line():
    lines = list(KEYCLOAK_OPERATOR_LINES)
    located = tag_sha_lines.locate_tag_and_sha(lines, "keycloak-operator", "operator.config.keycloakImage", "sha")
    assert located is not None
    tag_idx, tag_indent, sha_idx = located
    tag_sha_lines.write_tag_and_sha(
        lines,
        (tag_idx, tag_indent, sha_idx),
        tag_sha_lines.SiblingWrite("26.7.3", "c" * 64, "sha", "keycloak-operator.operator.config.keycloakImage"),
    )
    assert lines[tag_idx] == '        tag: "26.7.3"\n'
    assert sha_idx is not None
    assert lines[sha_idx] == f'        sha: "{"c" * 64}"\n'
    assert len(lines) == len(KEYCLOAK_OPERATOR_LINES)  # replaced in place, no line added
    assert "831330513f55695572286e521f94fcd3c7e285250ed5b848090265a33192f669" not in "".join(lines)


# --- replace_scalar_value ---


def test_replace_scalar_value_preserves_quotes(ucv: ModuleType):
    assert (
        ucv.replace_scalar_value('      tag: "1.0.0@sha256:aaaa"\n', "2.0.0@sha256:bbbb")
        == '      tag: "2.0.0@sha256:bbbb"\n'
    )


def test_replace_scalar_value_preserves_bare_style(ucv: ModuleType):
    assert ucv.replace_scalar_value("    version: 1.0.297\n", "1.0.298") == "    version: 1.0.298\n"


def test_replace_scalar_value_preserves_trailing_comment(ucv: ModuleType):
    result = ucv.replace_scalar_value("    version: 1.0.297  # pinned\n", "1.0.298")
    assert result == "    version: 1.0.298  # pinned\n"


# --- update_chart_yaml ---


def write_chart_yaml(path, deps):
    path.write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")


def test_update_chart_yaml_bumps_only_matching_dependency(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text(
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.296\n"
        '    repository: "@zac"\n'
        "    alias: zac\n"
        "  - name: openzaak\n"
        "    version: 1.14.2\n"
        '    repository: "@maykinmedia"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    old_line, new_line = ucv.update_chart_yaml("zaakafhandelcomponent", "1.0.297")
    assert "1.0.296" in old_line
    assert "1.0.297" in new_line
    updated = chart_yaml.read_text(encoding="utf-8")
    assert "version: 1.0.297" in updated
    assert "version: 1.14.2" in updated  # untouched


def test_update_chart_yaml_missing_dependency_raises(ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("dependencies:\n  - name: openzaak\n    version: 1.14.2\n", encoding="utf-8")
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    with pytest.raises(SystemExit):
        ucv.update_chart_yaml("totally-unknown", "9.9.9")


# --- update_values_yaml ---


def test_update_values_yaml_single_image(ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text(
        'zac:\n  image:\n    tag: "5.0.2@sha256:aaaa"\n  opa:\n    image:\n      tag: "1.17.1-static@sha256:bbbb"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    changes = ucv.update_values_yaml("zac", ["image"], {"image": "5.4.3@sha256:cccc"})
    assert len(changes) == 1
    updated = values_yaml.read_text(encoding="utf-8")
    assert '"5.4.3@sha256:cccc"' in updated
    assert '"1.17.1-static@sha256:bbbb"' in updated  # sidecar untouched


def test_update_values_yaml_multi_image_lockstep(ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
        "zgw-office-addin",
        ["frontend.image", "backend.image"],
        {"frontend.image": "v0.9.352@sha256:cccc", "backend.image": "v0.9.352@sha256:dddd"},
    )
    assert len(changes) == 2
    updated = values_yaml.read_text(encoding="utf-8")
    assert '"v0.9.352@sha256:cccc"' in updated
    assert '"v0.9.352@sha256:dddd"' in updated
    assert "v0.9.313" not in updated


def test_update_values_yaml_missing_path_raises(ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text('zac:\n  image:\n    tag: "5.0.2@sha256:aaaa"\n', encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    with pytest.raises(SystemExit):
        ucv.update_values_yaml("zac", ["frontend.image"], {"frontend.image": "1.0.0@sha256:zzzz"})


# --- _load_split_tag_sha_paths ---


def test_load_split_tag_sha_paths_skips_writable_entry_without_sibling_field(
    ucv: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    # A writable entry naming no sibling_field has no split pin to write;
    # it used to be kept with a None sibling field, which would have
    # written a literal "None:" key next to its tag.
    monkeypatch.setattr(
        ucv,
        "digest_pinning_exceptions",
        lambda _chart_dir: {
            ("keycloak", "image"): {"sibling_field": "sha", "writable": True},
            ("zac", "image"): {"sibling_field": None, "writable": True},
            ("omc", "image"): {"sibling_field": "digest", "writable": False},
        },
    )
    assert ucv._load_split_tag_sha_paths() == {("keycloak", "image"): "sha"}
