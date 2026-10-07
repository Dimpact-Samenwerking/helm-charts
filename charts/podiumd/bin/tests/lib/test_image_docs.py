"""lib.image.docs: doc updates for a shared image basename bumped across components."""

import io
import tarfile

from pathlib import Path
from types import ModuleType

import pytest
import yaml

from lib.component_docs.changes_section import DocContext

# --- add_missing_sidecar_rows ---


def test_add_missing_sidecar_rows_global_image_gets_one_row_not_per_alias(libimagedocs: ModuleType, tmp_path: Path):
    """A global image aliased by several deps' sidecars gets one bare row, not one row per dep."""
    deps = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
        {"name": "frankgateway", "alias": "", "version": "1.1.0"},
    ]
    target_values = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
        "zac": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
        "frankgateway": {
            "dashboard": {
                "auth": {"shim": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}}
            }
        },
    }
    baseline_values = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}},
        "zac": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}},
        "frankgateway": {
            "dashboard": {
                "auth": {"shim": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}}
            }
        },
    }
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
    )

    new_text, added = libimagedocs.add_missing_sidecar_rows(
        text,
        libimagedocs.DocContext(tmp_path, "4.9.0"),
        libimagedocs.ComponentState(deps, target_values),
        baseline_values,
    )

    assert added == ["nginx-unprivileged"]
    assert "| nginx-unprivileged | 1.31.3 → 1.31.4 | - | - |" in new_text
    assert "### nginx-unprivileged 1.31.3 → 1.31.4" in new_text
    assert "zac - nginx-unprivileged" not in new_text
    assert "frankgateway - nginx-unprivileged" not in new_text


def test_add_missing_sidecar_rows_digest_only_repin_is_not_a_row(libimagedocs: ModuleType, tmp_path: Path):
    """A digest-only re-pin (same version) gets no row/section; -upgrade.md documents versions only."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    target_values = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
        "zac": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
    }
    baseline_values = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:bbbb"}}},
        "zac": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:bbbb"}}},
    }
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
    )

    new_text, added = libimagedocs.add_missing_sidecar_rows(
        text,
        libimagedocs.DocContext(tmp_path, "4.9.0"),
        libimagedocs.ComponentState(deps, target_values),
        baseline_values,
    )

    assert added == []
    assert "nginx-unprivileged" not in new_text


def test_add_missing_sidecar_rows_global_row_inserted_at_its_own_position_not_last(
    libimagedocs: ModuleType, tmp_path: Path
):
    """A global row sorts first ("global:" is values.yaml's first key), not last as unmatched."""
    deps = [{"name": "openzaak", "alias": "", "version": "1.14.2"}]
    target_values = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
        "openzaak": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
    }
    baseline_values = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}},
        "openzaak": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}},
    }
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openzaak | 1.27.4 → 1.29.3 | 1.14.2 (unchanged) | - |\n"
    )

    new_text, added = libimagedocs.add_missing_sidecar_rows(
        text,
        libimagedocs.DocContext(tmp_path, "4.9.0"),
        libimagedocs.ComponentState(deps, target_values),
        baseline_values,
    )

    assert added == ["nginx-unprivileged"]
    rows = [line for line in new_text.splitlines() if line.startswith("|") and "---" not in line]
    assert rows[1].startswith("| nginx-unprivileged")
    assert rows[2].startswith("| openzaak")


def test_add_missing_sidecar_rows_same_repository_at_different_baseline_path_is_an_upgrade(
    libimagedocs: ModuleType, tmp_path: Path
):
    """A new path whose repository existed elsewhere in the baseline uses that path's tag as prior version.

    Case: 4.9.1 moved postgres pins into global.images.postgres; must render
    "16-alpine -> 16.15-alpine", not "(new)".
    """
    deps = [{"name": "openbao", "version": "2.0.0"}]
    target_values = {
        "global": {"images": {"postgres": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}},
        "openbao": {
            "database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}}
        },
    }
    baseline_values = {
        "openbao": {"database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16-alpine@sha256:bbbb"}}}},
    }
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
    )

    new_text, added = libimagedocs.add_missing_sidecar_rows(
        text,
        libimagedocs.DocContext(tmp_path, "4.9.1"),
        libimagedocs.ComponentState(deps, target_values),
        baseline_values,
    )

    assert added == ["postgres"]
    assert "| postgres | 16-alpine → 16.15-alpine | - | - |" in new_text
    assert "### postgres 16-alpine → 16.15-alpine" in new_text
    assert "(new)" not in new_text


def test_add_missing_sidecar_rows_genuinely_new_repository_still_renders_new(libimagedocs: ModuleType, tmp_path: Path):
    """A repository absent from the baseline and historical manifests still renders "(new)"."""
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    target_values = {
        "redis-operator": {"image": {"repository": "quay.io/opstree/redis-operator", "tag": "1.0.0"}},
        "global": {"images": {"redis": {"repository": "redis", "tag": "8.0@sha256:aaaa"}}},
    }
    baseline_values = {
        "redis-operator": {"image": {"repository": "quay.io/opstree/redis-operator", "tag": "1.0.0"}},
    }
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
    )

    new_text, added = libimagedocs.add_missing_sidecar_rows(
        text,
        libimagedocs.DocContext(tmp_path, "4.9.1"),
        libimagedocs.ComponentState(deps, target_values),
        baseline_values,
    )

    assert added == ["redis"]
    assert "### redis 8.0 (new)" in new_text


# --- make_image_changes_section ---


@pytest.mark.parametrize("app", [None, "-"])
def test_build_changes_section_for_row_without_app_version_is_a_todo_stub(libimagedocs: ModuleType, app: str | None):
    """A row whose app cell is empty or "-" has no target version, so it
    gets the TODO stub, never a section built from "-"."""
    row = {"name": "curl", "app_source": None, "app": app, "chart_source": None, "chart": "-"}

    section = libimagedocs.build_changes_section_for_row(
        row, ("sidecar", ("global", "images", "curl")), [], DocContext(Path(), "4.9.2")
    )

    assert section == (
        "### curl -\n\nTODO: describe this component's changes — its app version could not be "
        "resolved from the table row.\n\n"
    )


def test_make_image_changes_section_lists_every_pinned_path(libimagedocs: ModuleType):
    pinned = [("keycloak-operator.jobs.ensureOperatorSa.image.tag", "8.20.0"), ("zac.global.curlImage.tag", "8.20.0")]
    section = libimagedocs.make_image_changes_section("curl", "4.9.0", "8.20.0", "8.21.0", pinned)
    assert section.startswith("### curl 8.20.0 → 8.21.0")
    assert "- `keycloak-operator.jobs.ensureOperatorSa.image.tag` `8.20.0` → `8.21.0`" in section
    assert "- `zac.global.curlImage.tag` `8.20.0` → `8.21.0`" in section
    assert "images-4.9.0.yaml" in section


def test_make_image_changes_section_per_path_old_version_differs(libimagedocs: ModuleType):
    """Each path shows its own old version; pins need not share one."""
    pinned = [("a.image.tag", "8.19.0"), ("b.image.tag", "8.20.0")]
    section = libimagedocs.make_image_changes_section("curl", "4.9.0", "8.19.0", "8.21.0", pinned)
    assert "- `a.image.tag` `8.19.0` → `8.21.0`" in section
    assert "- `b.image.tag` `8.20.0` → `8.21.0`" in section


def test_make_image_changes_section_old_version_none_renders_new(libimagedocs: ModuleType):
    """old_version None (never pinned before) renders "(new)", not "None → 8.0"."""
    pinned = [("global.images.redis.tag", None)]
    section = libimagedocs.make_image_changes_section("redis", "4.9.1", None, "8.0", pinned)
    assert section.startswith("### redis 8.0 (new)")
    assert "None" not in section
    assert "→" not in section.split("\n\n")[0]
    assert "- `global.images.redis.tag` `8.0` (new)" in section
    assert "introduces the shared **redis** image" in section


def test_make_image_changes_section_old_equals_new_renders_unchanged(libimagedocs: ModuleType):
    """old_version equal to new_version renders "(unchanged)", not "8.0 → 8.0"."""
    pinned = [("global.images.redis.tag", "8.0")]
    section = libimagedocs.make_image_changes_section("redis", "4.9.1", "8.0", "8.0", pinned)
    assert section.startswith("### redis 8.0 (unchanged)")
    assert "8.0 → 8.0" not in section
    assert "- `global.images.redis.tag` `8.0` (unchanged)" in section
    assert "keeps the shared **redis** image" in section


def test_make_image_changes_section_component_sidecar_is_not_called_shared(libimagedocs: ModuleType):
    """Only a global.images pin is a shared image: a component's own
    sidecar (keycloak's keycloak-config-cli) is just "the ... image"."""
    pinned = [("keycloak.keycloakConfigCli.image.tag", "6.5.1-26")]
    section = libimagedocs.make_image_changes_section(
        "keycloak - keycloak-config-cli", "4.9.3", "6.5.1-26", "6.5.1-26.5.5", pinned
    )
    assert "upgrades the **keycloak - keycloak-config-cli** image to 6.5.1-26.5.5" in section
    assert "shared" not in section


def test_make_image_changes_section_global_image_is_called_shared(libimagedocs: ModuleType):
    pinned = [("global.images.curl.tag", "8.21.0")]
    section = libimagedocs.make_image_changes_section("curl", "4.9.3", "8.21.0", "8.22.0", pinned)
    assert "upgrades the shared **curl** image to 8.22.0" in section


# --- regenerate_images_baseline_manifest ---


def test_regenerate_images_baseline_manifest_full_enumeration_and_sort_order(libimagedocs: ModuleType, tmp_path: Path):
    """Every primary and sidecar image is written, one per repository, in values.yaml component order."""
    deps = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
        {"name": "openbao", "version": "2.0.0"},
    ]
    values = {
        "zac": {
            "image": {"repository": "infonl/zaakafhandelcomponent", "tag": "1.0.297@sha256:" + "a" * 64},
            "opa": {"image": {"repository": "openpolicyagent/opa", "tag": "0.60.0@sha256:" + "b" * 64}},
        },
        "openbao": {
            "image": {"repository": "openbao/openbao", "tag": "2.0.0@sha256:" + "c" * 64},
        },
    }
    images_baseline_path = tmp_path / "images-baseline.yaml"

    written, skipped, _changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, set()
    )

    assert skipped == []
    assert written == 3
    text = images_baseline_path.read_text(encoding="utf-8")
    names_in_order = [line.split("name: ", 1)[1].strip() for line in text.splitlines() if line.startswith("- name:")]
    assert names_in_order == [
        "infonl/zaakafhandelcomponent",
        "openpolicyagent/opa",
        "openbao/openbao",
    ]
    assert "url: docker.io/infonl/zaakafhandelcomponent" in text
    assert 'version: "1.0.297"' in text
    assert f'digest: "sha256:{"a" * 64}"' in text


def test_regenerate_images_baseline_manifest_global_images_use_their_own_real_suborder(
    libimagedocs: ModuleType, tmp_path: Path
):
    """Peers under global.images.* keep values.yaml's own sub-order instead of tying on "global"."""
    deps = []
    values = {
        "global": {
            "images": {
                "nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.5@sha256:" + "a" * 64},
                "curl": {"repository": "curlimages/curl", "tag": "8.22.0@sha256:" + "b" * 64},
                "busybox": {"repository": "library/busybox", "tag": "1.38.0-glibc@sha256:" + "c" * 64},
                "redis": {"repository": "redis", "tag": "8.10.1@sha256:" + "d" * 64},
            }
        }
    }
    images_baseline_path = tmp_path / "images-baseline.yaml"

    written, skipped, _changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, set()
    )

    assert skipped == []
    assert written == 4
    text = images_baseline_path.read_text(encoding="utf-8")
    names_in_order = [line.split("name: ", 1)[1].strip() for line in text.splitlines() if line.startswith("- name:")]
    assert names_in_order == [
        "nginxinc/nginx-unprivileged",
        "curlimages/curl",
        "library/busybox",
        "library/redis",
    ]


def test_regenerate_images_baseline_manifest_collapses_shared_repository(libimagedocs: ModuleType, tmp_path: Path):
    """A repository shared by several paths collapses to one entry."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {
        "zac": {
            "image": {"repository": "infonl/zaakafhandelcomponent", "tag": "1.0.297@sha256:" + "a" * 64},
            "nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.25.0@sha256:" + "d" * 64}},
        },
        "global": {
            "images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.25.0@sha256:" + "d" * 64}},
        },
    }
    images_baseline_path = tmp_path / "images-baseline.yaml"

    written, skipped, _changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, set()
    )

    assert skipped == []
    assert written == 2
    text = images_baseline_path.read_text(encoding="utf-8")
    assert text.count("- name: nginxinc/nginx-unprivileged") == 1


def test_regenerate_images_baseline_manifest_embedded_digest_used_directly(
    libimagedocs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A tag with an embedded "@sha256:" digest is used directly, without registry lookup."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"repository": "infonl/zaakafhandelcomponent", "tag": "1.0.297@sha256:" + "a" * 64}}}
    images_baseline_path = tmp_path / "images-baseline.yaml"

    def fail_if_called(chart_dir, repository, version, timeout=None):
        msg = "cached_tag_exists must not be called for an already-digest-pinned tag"
        raise AssertionError(msg)

    monkeypatch.setattr(libimagedocs, "cached_tag_exists", fail_if_called)

    written, skipped, _changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, set()
    )

    assert skipped == []
    assert written == 1
    assert f'digest: "sha256:{"a" * 64}"' in images_baseline_path.read_text(encoding="utf-8")


def test_regenerate_images_baseline_manifest_live_lookup_for_bare_tag(
    libimagedocs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A bare tag gets its digest from a live registry lookup."""
    deps = [{"name": "openbao", "version": "2.0.0"}]
    values = {"openbao": {"image": {"repository": "openbao/openbao", "tag": "2.0.0"}}}
    images_baseline_path = tmp_path / "images-baseline.yaml"

    calls = []

    def fake_cached_tag_exists(chart_dir, repository, version, timeout=None):
        calls.append((repository, version))
        return True, "sha256:" + "e" * 64

    monkeypatch.setattr(libimagedocs, "cached_tag_exists", fake_cached_tag_exists)

    written, skipped, _changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, set()
    )

    assert skipped == []
    assert written == 1
    assert calls == [("docker.io/openbao/openbao", "2.0.0")]
    assert f'digest: "sha256:{"e" * 64}"' in images_baseline_path.read_text(encoding="utf-8")


def test_regenerate_images_baseline_manifest_skips_when_live_lookup_fails(
    libimagedocs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A bare tag whose lookup fails is reported in `skipped`, not written without a digest."""
    deps = [{"name": "openbao", "version": "2.0.0"}]
    values = {"openbao": {"image": {"repository": "openbao/openbao", "tag": "2.0.0"}}}
    images_baseline_path = tmp_path / "images-baseline.yaml"

    monkeypatch.setattr(libimagedocs, "cached_tag_exists", lambda chart_dir, repository, version: (False, None))

    written, skipped, _changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, set()
    )

    assert written == 0
    assert skipped == ["openbao/openbao"]
    assert (
        images_baseline_path.read_text(encoding="utf-8").strip().endswith(libimagedocs.IMAGES_BASELINE_HEADER.strip())
    )


def test_regenerate_images_baseline_manifest_wholesale_overwrite(libimagedocs: ModuleType, tmp_path: Path):
    """A second run replaces the file wholesale; no leftover entries from removed components."""
    images_baseline_path = tmp_path / "images-baseline.yaml"
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"repository": "infonl/zaakafhandelcomponent", "tag": "1.0.297@sha256:" + "a" * 64}}}
    libimagedocs.regenerate_images_baseline_manifest(tmp_path, deps, values, images_baseline_path, set())
    assert "infonl/zaakafhandelcomponent" in images_baseline_path.read_text(encoding="utf-8")

    new_deps = [{"name": "openbao", "version": "2.0.0"}]
    new_values = {"openbao": {"image": {"repository": "openbao/openbao", "tag": "2.0.0@sha256:" + "f" * 64}}}
    written, skipped, changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, new_deps, new_values, images_baseline_path, set()
    )

    assert skipped == []
    assert written == 1
    assert changed is True
    text = images_baseline_path.read_text(encoding="utf-8")
    assert "infonl/zaakafhandelcomponent" not in text
    assert "openbao/openbao" in text


def test_regenerate_images_baseline_manifest_second_identical_run_does_not_rewrite(
    libimagedocs: ModuleType, tmp_path: Path
):
    """An identical second run leaves the file untouched and reports changed=False (no git churn)."""
    images_baseline_path = tmp_path / "images-baseline.yaml"
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"repository": "infonl/zaakafhandelcomponent", "tag": "1.0.297@sha256:" + "a" * 64}}}

    written1, _skipped1, changed1 = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, set()
    )
    assert changed1 is True
    text_after_first = images_baseline_path.read_text(encoding="utf-8")
    mtime_after_first = images_baseline_path.stat().st_mtime_ns

    written2, skipped2, changed2 = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, set()
    )

    assert written2 == written1 == 1
    assert skipped2 == []
    assert changed2 is False
    assert images_baseline_path.read_text(encoding="utf-8") == text_after_first
    assert images_baseline_path.stat().st_mtime_ns == mtime_after_first


def test_regenerate_images_baseline_manifest_blank_line_between_entries_not_at_eof(
    libimagedocs: ModuleType, tmp_path: Path
):
    """Entries are blank-line separated, but the file ends in exactly one newline."""
    deps = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
        {"name": "openbao", "version": "2.0.0"},
    ]
    values = {
        "zac": {"image": {"repository": "infonl/zaakafhandelcomponent", "tag": "1.0.297@sha256:" + "a" * 64}},
        "openbao": {"image": {"repository": "openbao/openbao", "tag": "2.0.0@sha256:" + "c" * 64}},
    }
    images_baseline_path = tmp_path / "images-baseline.yaml"

    written, skipped, _changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, set()
    )

    assert skipped == []
    assert written == 2
    text = images_baseline_path.read_text(encoding="utf-8")
    assert '  digest: "sha256:' + "a" * 64 + '"\n\n- name: openbao/openbao\n' in text
    assert not text.endswith("\n\n")
    assert text.endswith("\n")


# --- regenerate_images_baseline_manifest — subchart-default-only images (render-gate) ---
#
# A dependency image relying only on its vendored default (e.g. eck-operator, null
# tag) is invisible to find_all_image_and_version_paths; these tests cover the
# find_unresolved_subchart_images augmentation, gated on rendered_paths.


def make_subchart_tgz(charts_dir, name, version, values, chart_yaml=None):
    """Build a minimal vendored <name>-<version>.tgz with values.yaml and optional Chart.yaml."""
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump(values).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        if chart_yaml is not None:
            cy_data = yaml.safe_dump(chart_yaml).encode("utf-8")
            cy_info = tarfile.TarInfo(name=f"{name}/Chart.yaml")
            cy_info.size = len(cy_data)
            tar.addfile(cy_info, io.BytesIO(cy_data))


def test_regenerate_images_baseline_manifest_includes_subchart_default_only_image_when_rendered(
    libimagedocs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A rendered dependency image with only a vendored null-tag default gets an entry (appVersion)."""
    deps = [{"name": "eck-operator", "version": "3.5.0"}]
    values = {}
    make_subchart_tgz(
        tmp_path / "charts",
        "eck-operator",
        "3.5.0",
        {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}},
        chart_yaml={"name": "eck-operator", "version": "3.5.0", "appVersion": "3.5.0"},
    )
    images_baseline_path = tmp_path / "images-baseline.yaml"
    monkeypatch.setattr(
        libimagedocs, "cached_tag_exists", lambda chart_dir, repository, version: (True, "sha256:" + "a" * 64)
    )

    written, skipped, _changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, {"podiumd/charts/eck-operator"}
    )

    assert skipped == []
    assert written == 1
    text = images_baseline_path.read_text(encoding="utf-8")
    assert "- name: eck/eck-operator" in text
    assert "url: docker.elastic.co/eck/eck-operator" in text
    assert 'version: "3.5.0"' in text


def test_regenerate_images_baseline_manifest_excludes_subchart_default_only_image_when_not_rendered(
    libimagedocs: ModuleType, tmp_path: Path
):
    """The same vendored default gets no entry when its chart-tree path did not render (disabled dep)."""
    deps = [{"name": "eck-operator", "version": "3.5.0"}]
    values = {}
    make_subchart_tgz(
        tmp_path / "charts",
        "eck-operator",
        "3.5.0",
        {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}},
        chart_yaml={"name": "eck-operator", "version": "3.5.0", "appVersion": "3.5.0"},
    )
    images_baseline_path = tmp_path / "images-baseline.yaml"

    written, skipped, _changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, set()
    )

    assert skipped == []
    assert written == 0


def test_regenerate_images_baseline_manifest_blank_tag_override_not_treated_as_subchart_default_finding(
    libimagedocs: ModuleType, tmp_path: Path
):
    """An explicit blank tag override (openbao.server.image) is an override, not a subchart-default entry."""
    deps = [{"name": "openbao", "version": "0.28.4"}]
    values = {"openbao": {"server": {"image": {"repository": "openbao/openbao", "tag": ""}}}}
    make_subchart_tgz(
        tmp_path / "charts",
        "openbao",
        "0.28.4",
        {"server": {"image": {"repository": "openbao/openbao", "tag": "2.5.5"}}},
        chart_yaml={"name": "openbao", "version": "0.28.4", "appVersion": "2.5.5"},
    )
    images_baseline_path = tmp_path / "images-baseline.yaml"

    written, skipped, _changed = libimagedocs.regenerate_images_baseline_manifest(
        tmp_path, deps, values, images_baseline_path, {"podiumd/charts/openbao"}
    )

    assert skipped == []
    assert written == 0


def test_historical_lookup_matches_an_older_bare_name_by_its_url(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
    """images-<ver>.yaml files written before names used the "library/"
    form still match "library/python" through their url."""
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "images-4.9.2.yaml").write_text(
        '- name: python\n  url: docker.io/library/python\n  version: "3.14.7-slim"\n  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    version = libcharthistoricalbaselines.historical_app_version_for_repository(tmp_path, "library/python")
    assert version == "3.14.7-slim"
