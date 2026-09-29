"""lib.upgradedoc -- resolve_component_row and changes-heading checks."""

from pathlib import Path
from types import ModuleType

DEPS = [
    {"name": "openzaak", "version": "1.14.2"},
    {"name": "openinwoner", "version": "2.4.0"},
    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
]


# --- resolve_component_row ---
# Shared by fix-doc-consistency's row rewriter and the docs_consistency checker.


def _redis_sidecar_deps_and_values(target_tag="8.6.6", baseline_tag="8.6.2"):
    target_deps = [{"name": "redis-operator", "version": "0.26.1"}]
    baseline_deps = [{"name": "redis-operator", "version": "0.25.0"}]
    target_values = {
        "redis-operator": {
            "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": f"{target_tag}@sha256:aaaa"}}
        }
    }
    baseline_values = {
        "redis-operator": {
            "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": f"{baseline_tag}@sha256:aaaa"}}
        }
    }
    return target_deps, target_values, baseline_deps, baseline_values


def _resolution(
    libupgradedocresolverow: ModuleType,
    chart_dir,
    deps,
    values,
    baseline_deps=None,
    baseline_values=None,
    upgrade_docs_baseline=None,
):
    return libupgradedocresolverow.ResolutionContext(
        chart_dir,
        libupgradedocresolverow.ComponentState(deps, values),
        libupgradedocresolverow.ComponentState(baseline_deps, baseline_values),
        upgrade_docs_baseline,
    )


def test_resolve_component_row_unmatched_name(libupgradedocresolverow: ModuleType):
    resolved = libupgradedocresolverow.resolve_component_row(
        "Totally Unknown Thing", {}, _resolution(libupgradedocresolverow, None, DEPS, {})
    )
    assert resolved == {"kind": "unmatched"}


def test_resolve_component_row_dependency_no_baseline_requested(libupgradedocresolverow: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}

    resolved = libupgradedocresolverow.resolve_component_row(
        "ZAC", {}, _resolution(libupgradedocresolverow, None, deps, values)
    )

    assert resolved["kind"] == "dependency"
    assert resolved["values_key"] == resolved["top_level_key"] == "zac"
    assert resolved["target_chart"] == "1.0.297"
    assert resolved["target_app"] == "5.4.4"
    assert resolved["baseline_resolved"] is None
    assert resolved["baseline_chart"] is None
    assert resolved["baseline_app"] is None


def test_resolve_component_row_dependency_baseline_resolved(libupgradedocresolverow: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    baseline_values = {"zac": {"image": {"tag": "5.1.0@sha256:bbbb"}}}

    resolved = libupgradedocresolverow.resolve_component_row(
        "ZAC", {}, _resolution(libupgradedocresolverow, None, deps, values, baseline_deps, baseline_values)
    )

    assert resolved["baseline_resolved"] is True
    assert resolved["baseline_chart"] == "1.0.257"
    assert resolved["baseline_app"] == "5.1.0"


def test_resolve_component_row_dependency_missing_from_baseline_is_unresolved(libupgradedocresolverow: ModuleType):
    """No baseline dependency gives baseline_resolved=False, so "failed" differs from "not asked"."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}

    resolved = libupgradedocresolverow.resolve_component_row(
        "ZAC", {}, _resolution(libupgradedocresolverow, None, deps, values, [], {})
    )

    assert resolved["kind"] == "dependency"
    assert resolved["baseline_resolved"] is False
    assert resolved["baseline_chart"] is None
    assert resolved["baseline_app"] is None


def test_resolve_component_row_dependency_baseline_dep_exists_values_entry_missing_renders_new(
    libupgradedocresolverow: ModuleType, tmp_path: Path
):
    """Baseline dependency exists but its values entry doesn't: baseline_app is None, no images-baseline fallback."""
    deps = [{"name": "brppersonenmock", "version": "1.2.9"}]
    baseline_deps = [{"name": "brppersonenmock", "version": "1.2.9"}]
    values = {
        "brppersonenmock": {
            "image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0-202606230850@sha256:aaaa"}
        }
    }
    baseline_values = {"zac": {"image": {"tag": "5.1.0@sha256:bbbb"}}}  # no "brppersonenmock" key

    resolved = libupgradedocresolverow.resolve_component_row(
        "brppersonenmock",
        {},
        _resolution(libupgradedocresolverow, tmp_path, deps, values, baseline_deps, baseline_values),
    )

    assert resolved["baseline_resolved"] is True
    assert resolved["baseline_chart"] == "1.2.9"
    assert resolved["baseline_app"] is None


def test_resolve_component_row_dependency_chart_renamed_under_same_alias_uses_baseline_chart_name(
    libupgradedocresolverow: ModuleType,
):
    """A chart renamed under the same alias reads the baseline app version via the baseline chart's image paths."""
    deps = [{"name": "renamed-vault", "alias": "vault", "version": "0.20.0"}]
    values = {"vault": {"image": {"tag": "2.2.0@sha256:aaaa"}}}
    baseline_deps = [{"name": "openbao", "alias": "vault", "version": "0.19.0"}]
    baseline_values = {"vault": {"server": {"image": {"tag": "2.1.0@sha256:bbbb"}}}}

    resolved = libupgradedocresolverow.resolve_component_row(
        "vault", {}, _resolution(libupgradedocresolverow, None, deps, values, baseline_deps, baseline_values)
    )

    assert resolved["kind"] == "dependency"
    assert resolved["target_app"] == "2.2.0"
    assert resolved["baseline_resolved"] is True
    assert resolved["baseline_chart"] == "0.19.0"
    assert resolved["baseline_app"] == "2.1.0"


def test_resolve_component_row_dependency_missing_from_baseline_is_false(
    libupgradedocresolverow: ModuleType, tmp_path: Path
):
    """A dependency absent from the baseline gives baseline_resolved=False."""
    deps = [{"name": "brppersonenmock", "version": "1.2.9"}]
    values = {
        "brppersonenmock": {
            "image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0-202606230850@sha256:aaaa"}
        }
    }

    resolved = libupgradedocresolverow.resolve_component_row(
        "brppersonenmock", {}, _resolution(libupgradedocresolverow, tmp_path, deps, values, [], {})
    )

    assert resolved["baseline_resolved"] is False


def test_resolve_component_row_native_component_no_baseline_requested(libupgradedocresolverow: ModuleType):
    """frankgateway (native component) has no Chart.yaml dependency, so deps is empty."""
    values = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}

    resolved = libupgradedocresolverow.resolve_component_row(
        "frankgateway", {}, _resolution(libupgradedocresolverow, None, [], values)
    )

    assert resolved["kind"] == "native"
    assert resolved["dep"] is None
    assert resolved["sidecar_path"] is None
    assert resolved["values_key"] == resolved["top_level_key"] == "frankgateway"
    assert resolved["target_chart"] is None  # no chart at all to verify against
    assert resolved["target_app"] == "104"
    assert resolved["baseline_resolved"] is None


def test_resolve_component_row_native_component_baseline_resolved(libupgradedocresolverow: ModuleType):
    values = {"frankgateway": {"image": {"tag": "104@sha256:bbbb"}}}
    baseline_values = {"frankgateway": {"image": {"tag": "100@sha256:aaaa"}}}

    resolved = libupgradedocresolverow.resolve_component_row(
        "frankgateway", {}, _resolution(libupgradedocresolverow, None, [], values, [], baseline_values)
    )

    assert resolved["kind"] == "native"
    assert resolved["baseline_resolved"] is True
    assert resolved["baseline_chart"] is None
    assert resolved["baseline_app"] == "100"


def test_resolve_component_row_native_component_missing_from_baseline_is_unresolved(
    libupgradedocresolverow: ModuleType,
):
    """A native component absent from the baseline gives baseline_resolved=False."""
    values = {"frankgateway": {"image": {"tag": "104@sha256:bbbb"}}}

    resolved = libupgradedocresolverow.resolve_component_row(
        "frankgateway", {}, _resolution(libupgradedocresolverow, None, [], values, [], {})
    )

    assert resolved["kind"] == "native"
    assert resolved["baseline_resolved"] is False
    assert resolved["baseline_app"] is None


def test_resolve_component_row_native_component_falls_back_to_historical_images_manifest(
    libupgradedocresolverow: ModuleType, tmp_path: Path
):
    """A native component absent from the baseline uses the version in an earlier images-<version>.yaml."""
    values = {"frankgateway": {"image": {"repository": "docker.io/infonl/frankgateway", "tag": "104@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"tag": "5.1.0@sha256:bbbb"}}}  # no "frankgateway" key
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "images-4.8.0.yaml").write_text(
        "- name: infonl/frankgateway\n"
        "  url: docker.io/infonl/frankgateway\n"
        '  version: "100"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )

    resolved = libupgradedocresolverow.resolve_component_row(
        "frankgateway",
        {},
        _resolution(libupgradedocresolverow, tmp_path, [], values, [], baseline_values, "4.8.5"),
    )

    assert resolved["baseline_resolved"] is True
    assert resolved["baseline_app"] == "100"


def test_resolve_component_row_sidecar_resolved(libupgradedocresolverow: ModuleType):
    target_deps, target_values, baseline_deps, baseline_values = _redis_sidecar_deps_and_values()
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}

    resolved = libupgradedocresolverow.resolve_component_row(
        "redis-operator - redis",
        canonical_names,
        _resolution(libupgradedocresolverow, None, target_deps, target_values, baseline_deps, baseline_values),
    )

    assert resolved["kind"] == "sidecar"
    assert resolved["dep"] is None
    assert resolved["values_key"] == "redis-operator.redis-ha.image"
    assert resolved["top_level_key"] == "redis-operator"
    assert resolved["target_chart"] is None  # a sidecar has no chart version of its own
    assert resolved["target_app"] == "8.6.6"
    assert resolved["baseline_resolved"] is True
    assert resolved["baseline_chart"] is None
    assert resolved["baseline_app"] == "8.6.2"


def test_resolve_component_row_sidecar_missing_baseline_tag_is_unresolved(libupgradedocresolverow: ModuleType):
    target_deps, target_values, baseline_deps, _ = _redis_sidecar_deps_and_values()
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}

    resolved = libupgradedocresolverow.resolve_component_row(
        "redis-operator - redis",
        canonical_names,
        _resolution(libupgradedocresolverow, None, target_deps, target_values, baseline_deps, {}),
    )

    assert resolved["baseline_resolved"] is False
    assert resolved["target_app"] == "8.6.6"  # new, not broken


def test_resolve_component_row_sidecar_falls_back_to_historical_images_manifest(
    libupgradedocresolverow: ModuleType, tmp_path: Path
):
    """A sidecar absent from the baseline uses the version in an earlier images-<version>.yaml."""
    target_deps = [{"name": "redis-operator", "version": "1.36.2"}]
    baseline_deps = [{"name": "redis-operator", "version": "1.36.1"}]
    target_values = {
        "redis-operator": {"k8s": {"image": {"repository": "quay.io/alpine/k8s", "tag": "1.36.2@sha256:cccc"}}}
    }
    baseline_values = {"redis-operator": {"redis-ha": {"image": {"tag": "7.4.2@sha256:dddd"}}}}
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "images-4.8.0.yaml").write_text(
        '- name: alpine/k8s\n  url: quay.io/alpine/k8s\n  version: "1.36.0"\n  digest: "sha256:cccc"\n',
        encoding="utf-8",
    )
    canonical_names = {"redis-operator - k8s": ("redis-operator", "k8s", "image")}

    resolved = libupgradedocresolverow.resolve_component_row(
        "redis-operator - k8s",
        canonical_names,
        _resolution(
            libupgradedocresolverow, tmp_path, target_deps, target_values, baseline_deps, baseline_values, "4.8.5"
        ),
    )

    assert resolved["baseline_resolved"] is True
    assert resolved["baseline_app"] == "1.36.0"
    assert resolved["target_app"] == "1.36.2"


def test_resolve_component_row_sidecar_same_repository_at_different_baseline_path_is_an_upgrade(
    libupgradedocresolverow: ModuleType, tmp_path: Path
):
    """A repository moved to a new path in the target (postgres -> global.images.postgres) is an upgrade.

    Must agree with add_missing_sidecar_rows, which uses the same repository fallback.
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
    canonical_names = {"postgres": ("global", "images", "postgres")}

    resolved = libupgradedocresolverow.resolve_component_row(
        "postgres",
        canonical_names,
        _resolution(libupgradedocresolverow, tmp_path, deps, target_values, deps, baseline_values),
    )

    assert resolved["kind"] == "sidecar"
    assert resolved["target_app"] == "16.15-alpine"
    assert resolved["baseline_app"] == "16-alpine"
    assert resolved["baseline_resolved"] is True


def test_resolve_component_row_sidecar_genuinely_new_repository_stays_unresolved(
    libupgradedocresolverow: ModuleType, tmp_path: Path
):
    """A repository absent from the baseline under any path stays new (baseline_app None)."""
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    target_values = {
        "redis-operator": {"image": {"repository": "quay.io/opstree/redis-operator", "tag": "1.0.0"}},
        "global": {"images": {"redis": {"repository": "redis", "tag": "8.0@sha256:aaaa"}}},
    }
    baseline_values = {
        "redis-operator": {"image": {"repository": "quay.io/opstree/redis-operator", "tag": "1.0.0"}},
    }
    canonical_names = {"redis": ("global", "images", "redis")}

    resolved = libupgradedocresolverow.resolve_component_row(
        "redis",
        canonical_names,
        _resolution(libupgradedocresolverow, tmp_path, deps, target_values, deps, baseline_values),
    )

    assert resolved["kind"] == "sidecar"
    assert resolved["target_app"] == "8.0"
    assert resolved["baseline_app"] is None
    assert resolved["baseline_resolved"] is False


def test_resolve_component_row_sidecar_target_itself_unresolvable_also_baseline_resolved_false(
    libupgradedocresolverow: ModuleType,
):
    """An unresolvable target path gives target_app None, so callers can tell "broken" from "new"."""
    target_deps, target_values, baseline_deps, baseline_values = _redis_sidecar_deps_and_values()
    canonical_names = {"redis-operator - ghost-sidecar": ("redis-operator", "redis-ha", "ghostImage")}

    resolved = libupgradedocresolverow.resolve_component_row(
        "redis-operator - ghost-sidecar",
        canonical_names,
        _resolution(libupgradedocresolverow, None, target_deps, target_values, baseline_deps, baseline_values),
    )

    assert resolved["baseline_resolved"] is False
    assert resolved["target_app"] is None


def test_resolve_component_row_sidecar_shaped_name_with_no_canonical_match_is_unmatched(
    libupgradedocresolverow: ModuleType,
):
    """A sidecar-shaped name not in canonical_names is unmatched, never fuzzy-matched to its parent."""
    target_deps, target_values, baseline_deps, baseline_values = _redis_sidecar_deps_and_values()
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}

    resolved = libupgradedocresolverow.resolve_component_row(
        "redis-operator - ghost",
        canonical_names,
        _resolution(libupgradedocresolverow, None, target_deps, target_values, baseline_deps, baseline_values),
    )

    assert resolved == {"kind": "unmatched"}


# --- changes_heading_has_app_version ---


def test_changes_heading_has_app_version_arrow_shape(libupgradedocresolverow: ModuleType):
    assert libupgradedocresolverow.changes_heading_has_app_version("openzaak 1.27.4 → 1.29.3 (chart 1.0.0, unchanged)")


def test_changes_heading_has_app_version_new_shape(libupgradedocresolverow: ModuleType):
    """A "(new)" app version without an arrow counts as having one."""
    assert libupgradedocresolverow.changes_heading_has_app_version("openbao v2.5.5 (new) (chart 0.28.4, unchanged)")


def test_changes_heading_has_app_version_unchanged_shape(libupgradedocresolverow: ModuleType):
    """An "(unchanged)" app version counts, not confused with the chart clause's "unchanged"."""
    assert libupgradedocresolverow.changes_heading_has_app_version(
        "mi-data (MI-data exports) 2.71.0 (unchanged) (chart 1.0.0 → 1.1.0)"
    )


def test_changes_heading_has_app_version_chart_only_unchanged_is_not_confused_for_app_side(
    libupgradedocresolverow: ModuleType,
):
    """Only text outside the "(chart ...)" clause counts as the app version."""
    assert not libupgradedocresolverow.changes_heading_has_app_version("openbao 0.28.4 (chart 0.28.4, unchanged)")


def test_changes_heading_has_app_version_chart_only_stub_has_none(libupgradedocresolverow: ModuleType):
    """The chart-only TODO stub has no app version."""
    assert not libupgradedocresolverow.changes_heading_has_app_version("openbao 0.28.4")


# --- resolved_row_unchanged ---


def test_resolved_row_unchanged_true_when_app_and_chart_equal_baseline(libupgradedocresolverow: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    resolved = libupgradedocresolverow.resolve_component_row(
        "ZAC", {}, _resolution(libupgradedocresolverow, None, deps, values, deps, values)
    )
    assert libupgradedocresolverow.resolved_row_unchanged(resolved) is True


def test_resolved_row_unchanged_false_when_only_chart_equals_baseline(libupgradedocresolverow: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"tag": "5.4.3@sha256:bbbb"}}}
    resolved = libupgradedocresolverow.resolve_component_row(
        "ZAC", {}, _resolution(libupgradedocresolverow, None, deps, values, deps, baseline_values)
    )
    assert libupgradedocresolverow.resolved_row_unchanged(resolved) is False


def test_resolved_row_unchanged_false_without_baseline(libupgradedocresolverow: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    resolved = libupgradedocresolverow.resolve_component_row(
        "ZAC", {}, _resolution(libupgradedocresolverow, None, deps, values)
    )
    assert libupgradedocresolverow.resolved_row_unchanged(resolved) is False
