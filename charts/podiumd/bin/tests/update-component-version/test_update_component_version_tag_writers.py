"""Per-strategy tag writers and the baseline comparison in
update-component-version, called directly with a minimal context."""

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

DIGEST = "sha256:" + "e" * 64


def _ctx(values: dict[str, object], **extra: object) -> SimpleNamespace:
    return SimpleNamespace(values=values, values_key="keycloak", app_version="26.7.3", **extra)


def test_write_split_tag_sha_pin_does_not_record_alias_skipped_tag(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """An alias-reference tag line keeps resolving to its anchor, so the
    new tag must not be recorded as written for that path."""
    monkeypatch.setattr(ucv, "registry_tag_exists", lambda host, repo, tag: (True, DIGEST))
    values_lines = [
        "keycloak:\n",
        "  image:\n",
        "    repository: quay.io/keycloak/keycloak\n",
        "    tag: *keycloakImageVersion\n",
        "    sha: *keycloakImageDigest\n",
    ]
    ctx = _ctx({"keycloak": {"image": {"repository": "quay.io/keycloak/keycloak"}}})
    acc = ucv.TagUpdateAccumulator({}, {})

    ucv._write_split_tag_sha_pin(ctx, values_lines, "image", "sha", acc)

    assert "image" not in acc.new_tags_by_path
    assert acc.repos["image"] == "quay.io/keycloak/keycloak"
    assert values_lines[3] == "    tag: *keycloakImageVersion\n"


def test_write_split_tag_sha_pin_records_written_tag(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ucv, "registry_tag_exists", lambda host, repo, tag: (True, DIGEST))
    values_lines = [
        "keycloak:\n",
        "  image:\n",
        "    repository: quay.io/keycloak/keycloak\n",
        '    tag: "26.7.2"\n',
    ]
    ctx = _ctx({"keycloak": {"image": {"repository": "quay.io/keycloak/keycloak"}}})
    acc = ucv.TagUpdateAccumulator({}, {})

    ucv._write_split_tag_sha_pin(ctx, values_lines, "image", "sha", acc)

    assert acc.new_tags_by_path["image"] == f"26.7.3@{DIGEST}"


def test_plan_delegated_tags_exits_cleanly_when_own_line_unchanged(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """No change at the path or anything sharing its value must raise SystemExit with a message."""
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text("zac:\n  image:\n    repository: ghcr.io/infonl/zac\n    tag: 5.4.3\n", encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "plan_image_version_update", lambda *args: [])
    ctx = SimpleNamespace(
        values={"zac": {"image": {"repository": "ghcr.io/infonl/zac"}}}, values_key="zac", app_version="5.4.3"
    )

    with pytest.raises(SystemExit, match=r"no pin to update for zac\.image\.tag"):
        ucv._plan_delegated_tags(ctx, ["image"], ucv.TagUpdateAccumulator({}, {}))


OLD_DIGEST = "a" * 64
NEW_DIGEST = "sha256:" + "b" * 64

# openbao in 4.9.3: server.image.tag is a bare alias of the job image's anchored literal.
OPENBAO_VALUES = f"""\
openbao:
  configuration:
    job:
      image:
        repository: quay.io/openbao/openbao
        tag: &openbaoImageTag "2.5.5@sha256:{OLD_DIGEST}"
  server:
    image:
      registry: quay.io
      repository: quay.io/openbao/openbao
      tag: *openbaoImageTag
"""

# redis-ha: preDeleteJob.image aliases the whole image mapping, so it has no tag: line.
REDIS_VALUES = f"""\
redis-operator:
  cron:
    image: &k8s
      repository: docker.io/alpine/k8s
      tag: "1.37.0@sha256:{OLD_DIGEST}"
  pre:
    image: *k8s
"""

# Two literal pins of one basename, no alias.
TWO_LITERALS_VALUES = f"""\
zac:
  a:
    image:
      repository: ghcr.io/x/tool
      tag: "1.0.0@sha256:{OLD_DIGEST}"
  b:
    image:
      repository: ghcr.io/x/tool
      tag: "1.0.0@sha256:{OLD_DIGEST}"
"""


def _bump_delegated(
    ucv: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    key: str,
    paths: list[str],
    version: str,
):
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text(text, encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr("lib.image.version.registry_tag_exists", lambda host, repo, tag: (True, NEW_DIGEST))
    ctx = SimpleNamespace(values=ucv.load_yaml_mapping(values_yaml), values_key=key, app_version=version)
    acc = ucv.TagUpdateAccumulator({}, {})
    ucv._write_delegated_tags(ctx, ucv._plan_delegated_tags(ctx, paths, acc))
    return values_yaml.read_text(encoding="utf-8"), acc


@pytest.mark.parametrize(
    "paths", [["server.image", "configuration.job.image"], ["configuration.job.image", "server.image"]]
)
def test_delegated_alias_and_anchor_paths_bump_once_in_either_order(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, paths: list[str]
):
    text, acc = _bump_delegated(ucv, tmp_path, monkeypatch, OPENBAO_VALUES, "openbao", paths, "2.6.3")
    assert text == OPENBAO_VALUES.replace(f"2.5.5@sha256:{OLD_DIGEST}", f"2.6.3@{NEW_DIGEST}")
    assert "tag: *openbaoImageTag" in text
    assert acc.new_tags_by_path == dict.fromkeys(paths, f"2.6.3@{NEW_DIGEST}")


def test_delegated_mapping_alias_path_is_written_through_its_anchor(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    text, acc = _bump_delegated(ucv, tmp_path, monkeypatch, REDIS_VALUES, "redis-operator", ["pre.image"], "1.37.1")
    assert f'tag: "1.37.1@{NEW_DIGEST}"' in text
    assert acc.new_tags_by_path == {"pre.image": f"1.37.1@{NEW_DIGEST}"}


def test_two_literal_delegated_pins_of_one_basename_are_both_recorded(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    text, acc = _bump_delegated(ucv, tmp_path, monkeypatch, TWO_LITERALS_VALUES, "zac", ["a.image", "b.image"], "1.1.0")
    assert text.count(f"1.1.0@{NEW_DIGEST}") == 2
    assert set(acc.new_tags_by_path) == {"a.image", "b.image"}


def test_resolve_error_leaves_values_yaml_untouched(ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The second basename's tag is missing upstream: nothing may be written for the first."""
    text = OPENBAO_VALUES + REDIS_VALUES.replace("redis-operator:\n", "  extra:\n").replace("\n  ", "\n    ")
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text(text, encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)

    def exists(host: str, repo: str, tag: str) -> tuple[bool, str | None]:
        return (repo.endswith("openbao"), NEW_DIGEST)

    monkeypatch.setattr("lib.image.version.registry_tag_exists", exists)
    ctx = SimpleNamespace(values=ucv.load_yaml_mapping(values_yaml), values_key="openbao", app_version="9.9.9")
    with pytest.raises(SystemExit, match="not found upstream"):
        ucv._plan_delegated_tags(ctx, ["server.image", "extra.cron.image"], ucv.TagUpdateAccumulator({}, {}))
    assert values_yaml.read_text(encoding="utf-8") == text


def _comparison_ctx() -> SimpleNamespace:
    return SimpleNamespace(
        values_key="openzaak",
        no_chart=True,
        image_paths=["image", "nginx.image"],
        chart_name="openzaak",
        new_chart="1.0.0",
    )


def test_resolve_baseline_comparison_fallback_uses_first_changed_path(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Without a resolvable baseline, old_app comes from the first path
    that actually changed, not always image_paths[0]."""
    monkeypatch.setattr(ucv, "_read_upgrade_docs_baseline", lambda chart_dir: None)
    old_app_by_path = {"image": "1.0.0", "nginx.image": "1.31.5"}

    comparison = ucv._resolve_baseline_comparison(_comparison_ctx(), "4.9.2", old_app_by_path, ["nginx.image"])

    assert comparison.old_app == "1.31.5"


def test_resolve_baseline_comparison_resolves_like_the_table_row(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """old_app/old_chart come from the component's row resolution, whichever path changed."""
    calls = []

    def fake_compare(resolution, values_key: str):
        calls.append((values_key, resolution.upgrade_docs_baseline))
        return "2.5.5", "0.28.4", False

    monkeypatch.setattr(ucv, "_read_upgrade_docs_baseline", lambda chart_dir: "4.9.2")
    monkeypatch.setattr(ucv, "baseline_doc_paths", lambda baseline, target: (None, None))
    monkeypatch.setattr(ucv, "load_baseline_state", lambda baseline: ([], {}))
    monkeypatch.setattr(ucv, "load_chart_dependencies", lambda path: [])
    monkeypatch.setattr(ucv, "load_yaml_mapping", lambda path: {})
    monkeypatch.setattr(ucv, "compare_component_to_baseline", fake_compare)
    ctx = _comparison_ctx()
    ctx.no_chart = False
    ctx.dep = {"name": "openzaak", "version": "1.0.0"}

    comparison = ucv._resolve_baseline_comparison(ctx, "4.9.3", {}, ["nginx.image"])

    assert calls == [("openzaak", "4.9.2")]
    assert (comparison.old_app, comparison.old_chart) == ("2.5.5", "0.28.4")


def test_documented_paths_come_from_the_baseline_not_from_this_run(ucv: ModuleType):
    """On a rerun nothing is written, but the section still lists every path that moved since the baseline.

    A blank baseline tag counts as the component's resolved baseline app version."""
    ctx = SimpleNamespace(
        values_key="openbao", app_version="2.6.3", image_paths=["server.image", "configuration.job.image", "ui.image"]
    )
    baseline_values = {
        "openbao": {
            "server": {"image": {"tag": ""}},
            "configuration": {"job": {"image": {"tag": "2.5.5@sha256:aaaa"}}},
            "ui": {"image": {"tag": "2.6.3@sha256:cccc"}},
        }
    }
    comparison = SimpleNamespace(baseline_values=baseline_values, old_app="2.5.5")

    assert ucv._documented_paths(ctx, comparison, []) == ["server.image", "configuration.job.image"]
    assert ucv._documented_paths(ctx, SimpleNamespace(baseline_values=None, old_app=None), ["ui.image"]) == ["ui.image"]
