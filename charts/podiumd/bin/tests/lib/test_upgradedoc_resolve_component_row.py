"""lib.upgradedoc -- resolve_component_row and changes-heading /
dependency-claim correspondence checks."""

DEPS = [
    {"name": "openzaak", "version": "1.14.2"},
    {"name": "openinwoner", "version": "2.4.0"},
    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
]


# --- resolve_component_row ---
# The one place fix-doc-consistency's row-rewriter and lib.docs_consistency's
# row-checker both resolve a "Component versions" table row — see its own
# docstring for the drift this closes.


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
    libupgradedocresolverow,
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


def test_resolve_component_row_unmatched_name(libupgradedocresolverow):
    resolved = libupgradedocresolverow.resolve_component_row(
        "Totally Unknown Thing", {}, _resolution(libupgradedocresolverow, None, DEPS, {})
    )
    assert resolved == {"kind": "unmatched"}


def test_resolve_component_row_dependency_no_baseline_requested(libupgradedocresolverow):
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


def test_resolve_component_row_dependency_baseline_resolved(libupgradedocresolverow):
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


def test_resolve_component_row_dependency_missing_from_baseline_is_unresolved(libupgradedocresolverow):
    """The component doesn't exist yet at the baseline ref (no matching
    Chart.yaml dependency there) — baseline_resolved is False, not just a
    None app/chart, so a caller can tell "asked and failed" apart from
    "never asked"."""
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
    libupgradedocresolverow, tmp_path
):
    """Regression test: brppersonenmock's own Chart.yaml dependency line
    predates 4.9.0 (baseline_dep IS found — baseline_resolved stays
    governed by that alone), but its "image:" block was only added to
    podiumd's own values.yaml this release — baseline_app is correctly
    None (the git baseline genuinely has nothing for it), never a
    fallback to images-baseline.yaml (ACR-mirror digest provenance, a
    genuinely different, unrelated question)."""
    deps = [{"name": "brppersonenmock", "version": "1.2.9"}]
    baseline_deps = [{"name": "brppersonenmock", "version": "1.2.9"}]
    values = {
        "brppersonenmock": {
            "image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0-202606230850@sha256:aaaa"}
        }
    }
    baseline_values = {"zac": {"image": {"tag": "5.1.0@sha256:bbbb"}}}  # no "brppersonenmock" key at all

    resolved = libupgradedocresolverow.resolve_component_row(
        "brppersonenmock",
        {},
        _resolution(libupgradedocresolverow, tmp_path, deps, values, baseline_deps, baseline_values),
    )

    assert resolved["baseline_resolved"] is True
    assert resolved["baseline_chart"] == "1.2.9"
    assert resolved["baseline_app"] is None


def test_resolve_component_row_dependency_missing_from_baseline_is_false(libupgradedocresolverow, tmp_path):
    """A genuinely brand-new Chart.yaml dependency (baseline_dep not
    found AT ALL) stays baseline_resolved=False."""
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


def test_resolve_component_row_native_component_no_baseline_requested(libupgradedocresolverow):
    """frankgateway (see lib.chart.NATIVE_COMPONENTS) has no Chart.yaml
    dependency at all — deps is empty on purpose."""
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


def test_resolve_component_row_native_component_baseline_resolved(libupgradedocresolverow):
    values = {"frankgateway": {"image": {"tag": "104@sha256:bbbb"}}}
    baseline_values = {"frankgateway": {"image": {"tag": "100@sha256:aaaa"}}}

    resolved = libupgradedocresolverow.resolve_component_row(
        "frankgateway", {}, _resolution(libupgradedocresolverow, None, [], values, [], baseline_values)
    )

    assert resolved["kind"] == "native"
    assert resolved["baseline_resolved"] is True
    assert resolved["baseline_chart"] is None
    assert resolved["baseline_app"] == "100"


def test_resolve_component_row_native_component_missing_from_baseline_is_unresolved(libupgradedocresolverow):
    """Mirrors a real dependency's own "missing from baseline" case — no
    frankgateway key at all at the baseline ref means baseline_app can't
    resolve, so baseline_resolved is False rather than a silent None."""
    values = {"frankgateway": {"image": {"tag": "104@sha256:bbbb"}}}

    resolved = libupgradedocresolverow.resolve_component_row(
        "frankgateway", {}, _resolution(libupgradedocresolverow, None, [], values, [], {})
    )

    assert resolved["kind"] == "native"
    assert resolved["baseline_resolved"] is False
    assert resolved["baseline_app"] is None


def test_resolve_component_row_native_component_falls_back_to_historical_images_manifest(
    libupgradedocresolverow, tmp_path
):
    """frankgateway didn't exist at the baseline ref at all, but its own
    image repository already appeared in an earlier release's own
    images-<version>.yaml manifest — that release's own recorded
    version is the true prior app version, not images-baseline.yaml
    (removed)."""
    values = {"frankgateway": {"image": {"repository": "docker.io/infonl/frankgateway", "tag": "104@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"tag": "5.1.0@sha256:bbbb"}}}  # no "frankgateway" key at all
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


def test_resolve_component_row_sidecar_resolved(libupgradedocresolverow):
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


def test_resolve_component_row_sidecar_missing_baseline_tag_is_unresolved(libupgradedocresolverow):
    target_deps, target_values, baseline_deps, _ = _redis_sidecar_deps_and_values()
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}

    resolved = libupgradedocresolverow.resolve_component_row(
        "redis-operator - redis",
        canonical_names,
        _resolution(libupgradedocresolverow, None, target_deps, target_values, baseline_deps, {}),
    )

    assert resolved["baseline_resolved"] is False
    assert resolved["target_app"] == "8.6.6"  # target side resolves fine — this row IS new, not broken


def test_resolve_component_row_sidecar_falls_back_to_historical_images_manifest(libupgradedocresolverow, tmp_path):
    """Regression test: redis-operator's own "k8s" sidecar, added in
    4.9.0 — baseline_values has nothing for this path at all, but its
    repository already appeared in an earlier release's own images-
    <version>.yaml manifest — that release's own recorded version is
    the true prior app version (a real "X → Y" transition, not
    images-baseline.yaml, removed, and not forced to "(unchanged)")."""
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
    libupgradedocresolverow, tmp_path
):
    """Real case (podiumd 4.9.1): keycloak-operator's own
    ensurePodiumdAdminUser job and openbao's own schemaJob each pinned
    their own separate "postgres" image; both got consolidated into one
    new shared global.images.postgres anchor at 16.15-alpine. That exact
    path (global.images.postgres) never existed in baseline_values, so
    an exact-path lookup alone finds nothing — this used to make
    resolve_component_row's own sidecar branch resolve baseline_app to
    None (a real "(new)" heading) even though lib.image.docs.
    add_missing_sidecar_rows' own table row, using the SAME repository-
    moved fallback, already correctly resolved a real prior version
    ("16-alpine"). Both must now agree: baseline_app == "16-alpine"."""
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


def test_resolve_component_row_sidecar_genuinely_new_repository_stays_unresolved(libupgradedocresolverow, tmp_path):
    """The flip side of the postgres case above: a repository that truly
    never appeared anywhere in baseline_values (under ANY path) — no
    same-repository fallback match, no historical manifest entry either
    — must still resolve baseline_app to None (a real "(new)" heading),
    never mistaken for an upgrade just because SOME other path/repository
    exists in baseline_values."""
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


def test_resolve_component_row_sidecar_target_itself_unresolvable_also_baseline_resolved_false(libupgradedocresolverow):
    """canonical_names naming a path with no real tag in target_values at
    all can't happen via canonical_sidecar_row_names' own derivation (it
    only ever names paths find_image_tag_paths already found a tag at),
    but resolve_component_row itself doesn't assume that — a caller
    telling "new" (target resolves, baseline doesn't) apart from
    "broken" (target doesn't resolve either) needs target_app itself,
    not just this single boolean, which is exactly why fix-doc-
    consistency's own fix_component_version_table checks both."""
    target_deps, target_values, baseline_deps, baseline_values = _redis_sidecar_deps_and_values()
    canonical_names = {"redis-operator - ghost-sidecar": ("redis-operator", "redis-ha", "ghostImage")}

    resolved = libupgradedocresolverow.resolve_component_row(
        "redis-operator - ghost-sidecar",
        canonical_names,
        _resolution(libupgradedocresolverow, None, target_deps, target_values, baseline_deps, baseline_values),
    )

    assert resolved["baseline_resolved"] is False
    assert resolved["target_app"] is None


def test_resolve_component_row_sidecar_shaped_name_with_no_canonical_match_is_unmatched(libupgradedocresolverow):
    """ "redis-operator - ghost" isn't in canonical_names at all — must
    never fall through to a fuzzy match_dependency lookup against the
    real "redis-operator" dependency just because it shares a leading
    word; reported as unmatched, same as any other unresolvable name."""
    target_deps, target_values, baseline_deps, baseline_values = _redis_sidecar_deps_and_values()
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}

    resolved = libupgradedocresolverow.resolve_component_row(
        "redis-operator - ghost",
        canonical_names,
        _resolution(libupgradedocresolverow, None, target_deps, target_values, baseline_deps, baseline_values),
    )

    assert resolved == {"kind": "unmatched"}


# --- changes_heading_has_app_version ---


def test_changes_heading_has_app_version_arrow_shape(libupgradedocresolverow):
    assert libupgradedocresolverow.changes_heading_has_app_version("openzaak 1.27.4 → 1.29.3 (chart 1.0.0, unchanged)")


def test_changes_heading_has_app_version_new_shape(libupgradedocresolverow):
    """Regression test: a genuinely-new component's heading (see make_
    changes_section's own old_app is None case) shows "(new)" for the
    app version, no arrow at all — must still count as having one, or
    check_docs_consistency false-flags every such heading as missing
    its app version (real case: "### openbao v2.5.5 (new) (chart
    0.28.4, unchanged)")."""
    assert libupgradedocresolverow.changes_heading_has_app_version("openbao v2.5.5 (new) (chart 0.28.4, unchanged)")


def test_changes_heading_has_app_version_unchanged_shape(libupgradedocresolverow):
    """Same regression, for the "(unchanged)" app-version shape (see
    make_changes_section's old_app == new_app case) — must not be
    confused with the CHART clause's own unrelated "(..., unchanged)"
    that may follow it in the same heading."""
    assert libupgradedocresolverow.changes_heading_has_app_version(
        "mi-data (MI-data exports) 2.71.0 (unchanged) (chart 1.0.0 → 1.1.0)"
    )


def test_changes_heading_has_app_version_chart_only_unchanged_is_not_confused_for_app_side(libupgradedocresolverow):
    """The chart clause alone saying "(..., unchanged)" (or "(..., new)")
    must never be read as if it were the APP side's own version marker
    — only text OUTSIDE that clause counts."""
    assert not libupgradedocresolverow.changes_heading_has_app_version("openbao 0.28.4 (chart 0.28.4, unchanged)")


def test_changes_heading_has_app_version_chart_only_stub_has_none(libupgradedocresolverow):
    """add_missing_component_rows' own chart-only TODO-stub shape (no
    app version could be resolved at all, no "(chart ...)" clause
    either) reliably signals no app version was ever written."""
    assert not libupgradedocresolverow.changes_heading_has_app_version("openbao 0.28.4")
