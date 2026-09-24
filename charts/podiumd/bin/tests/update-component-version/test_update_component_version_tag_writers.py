"""The per-strategy tag writers and the baseline comparison inside
update-component-version, called directly with a minimal context: the
split tag/sha writer skips alias references, the delegated writer
fails cleanly when its own line didn't change, the old app version
follows the path that actually changed."""

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


def test_write_delegated_tags_exits_cleanly_when_own_line_unchanged(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """update_image_version reporting no change at the path's own line
    (already at the target, or another path sharing the basename changed)
    must raise SystemExit with a message, not a bare StopIteration."""
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text("zac:\n  image:\n    repository: ghcr.io/infonl/zac\n    tag: 5.4.3\n", encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "update_image_version", lambda *args: [])
    ctx = SimpleNamespace(
        values={"zac": {"image": {"repository": "ghcr.io/infonl/zac"}}}, values_key="zac", app_version="5.4.3"
    )

    with pytest.raises(SystemExit, match=r"no change at values\.yaml:4 \(zac\.image\)"):
        ucv._write_delegated_tags(ctx, ["image"], ucv.TagUpdateAccumulator({}, {}))


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


def test_resolve_baseline_comparison_baseline_lookup_uses_first_changed_path(
    ucv: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    queries = []

    def fake_resolve(query):
        queries.append(query)
        return "1.31.4", None

    monkeypatch.setattr(ucv, "_read_upgrade_docs_baseline", lambda chart_dir: "4.9.1")
    monkeypatch.setattr(ucv, "baseline_doc_paths", lambda baseline, target: (None, None))
    monkeypatch.setattr(ucv, "load_baseline_state", lambda baseline: ([], {}))
    monkeypatch.setattr(ucv, "load_chart_dependencies", lambda path: [])
    monkeypatch.setattr(ucv, "load_yaml_mapping", lambda path: {})
    monkeypatch.setattr(ucv, "compute_changed_components", lambda *args: {"openzaak"})
    monkeypatch.setattr(ucv, "resolve_baseline_component_versions", fake_resolve)

    comparison = ucv._resolve_baseline_comparison(_comparison_ctx(), "4.9.2", {}, ["nginx.image"])

    assert [q.image_path for q in queries] == ["nginx.image"]
    assert comparison.old_app == "1.31.4"
