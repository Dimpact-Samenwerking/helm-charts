"""lib.upgradedoc -- images-manifest entry ordering, grouping, and
faulty-header detection."""

from types import ModuleType

GLOBAL_IMAGES_VALUES = {
    "global": {
        "images": {
            "nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.5@sha256:" + "a" * 64},
            "curl": {"repository": "curlimages/curl", "tag": "8.22.0@sha256:" + "b" * 64},
            "busybox": {"repository": "library/busybox", "tag": "1.38.0-glibc@sha256:" + "c" * 64},
            "redis": {"repository": "redis", "tag": "8.10.1@sha256:" + "d" * 64},
        }
    },
    "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:" + "e" * 64}},
}
GLOBAL_IMAGES_CANONICAL_NAMES = {
    "nginx-unprivileged": ("global", "images", "nginx"),
    "curl": ("global", "images", "curl"),
    "busybox": ("global", "images", "busybox"),
    "redis": ("global", "images", "redis"),
}


# --- is_primary_image_path ---


def test_is_primary_image_path_default_image_key(libchartregisteredpaths: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0"}]
    assert libchartregisteredpaths.is_primary_image_path(("zac", "image"), deps) is True


def test_is_primary_image_path_multi_container_dependency(libchartregisteredpaths: ModuleType):
    """zgw-office-addin's frontend + backend are BOTH registered as
    primary images (lib.chart.COMPONENT_IMAGE_PATHS) — co-equal
    containers of one dependency, not one primary + a sidecar."""
    deps = [{"name": "zgw-office-addin", "version": "1.0.0"}]
    assert libchartregisteredpaths.is_primary_image_path(("zgw-office-addin", "frontend", "image"), deps) is True
    assert libchartregisteredpaths.is_primary_image_path(("zgw-office-addin", "backend", "image"), deps) is True


def test_is_primary_image_path_nested_sidecar_is_not_primary(libchartregisteredpaths: ModuleType):
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    assert libchartregisteredpaths.is_primary_image_path(("redis-operator", "redis-ha", "image"), deps) is False


def test_is_primary_image_path_version_paths_for_field_is_primary(libchartregisteredpaths: ModuleType):
    """redis-operator's own split "redisOperator.imageTag" field (lib.
    chart.version_paths_for's own bare-scalar fallback for a component
    with no "image: {tag}" block at all — actual_app_version's own
    second-pass lookup) is its primary, same as a "normal" image_paths_
    for match — real case: without this, redis-operator's OWN manifest
    entry was wrongly classified as an unrecognized sidecar of itself."""
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    assert libchartregisteredpaths.is_primary_image_path(("redis-operator", "redisOperator", "imageTag"), deps) is True


def test_is_primary_image_path_eck_stack_registered_version_fields_are_primary(libchartregisteredpaths: ModuleType):
    """eck-stack's own two COMPONENT_VERSION_PATHS entries (eck-
    elasticsearch + eck-kibana) are co-equal primaries, same "no single
    canonical one, list several" shape as zgw-office-addin's frontend +
    backend — eck-enterprise-search, deliberately NOT registered there
    (disabled by default), stays a real sidecar needing its own header."""
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "1.0.0"}]
    assert libchartregisteredpaths.is_primary_image_path(("kiss-eck", "eck-elasticsearch", "version"), deps) is True
    assert libchartregisteredpaths.is_primary_image_path(("kiss-eck", "eck-kibana", "version"), deps) is True
    assert (
        libchartregisteredpaths.is_primary_image_path(("kiss-eck", "eck-enterprise-search", "version"), deps) is False
    )


def test_is_primary_image_path_no_owning_dependency_is_primary(libchartregisteredpaths: ModuleType):
    """A path with no owning Chart.yaml dependency at all (podiumd's own
    directly-templated top-level block, or the shared "global" anchor)
    has no PARENT to be a sidecar of — treated as its own standalone/
    primary entity, never subject to sidecar-only rules."""
    deps = [{"name": "zac", "version": "1.0.0"}]
    assert libchartregisteredpaths.is_primary_image_path(("global", "images", "nginx"), deps) is True


def test_is_primary_image_path_empty_path_is_not_primary(libchartregisteredpaths: ModuleType):
    assert libchartregisteredpaths.is_primary_image_path(None, []) is False
    assert libchartregisteredpaths.is_primary_image_path((), []) is False


# --- header_name_segment ---


def test_header_name_segment_arrow_pair_isolates_name(libupgradedocmanifestordering: ModuleType):
    assert (
        libupgradedocmanifestordering.header_name_segment("keycloak-operator - operator 26.6.4 -> 26.7.3")
        == "keycloak-operator - operator"
    )


def test_header_name_segment_self_arrow_unchanged_isolates_name(libupgradedocmanifestordering: ModuleType):
    """A self-referential "X -> X" pair (unchanged value, still written
    with an arrow) is handled by the arrow path exactly like a real
    transition — never falls through to the bare-version branch."""
    assert (
        libupgradedocmanifestordering.header_name_segment("zac - opentelemetry-collector-contrib 0.158.0 -> 0.158.0")
        == "zac - opentelemetry-collector-contrib"
    )
    assert (
        libupgradedocmanifestordering.header_name_segment("openbao - openbao-csi-provider 2.0.2 -> 2.0.2")
        == "openbao - openbao-csi-provider"
    )


def test_header_name_segment_basename_ending_in_version_shaped_word_with_real_arrow(
    libupgradedocmanifestordering: ModuleType,
):
    """Regression guard: "openbao - vault-k8s" ends in "k8s", which is
    version-shaped on its own — but a real arrow pair IS present here
    ("1.7.2 -> 1.7.2"), so the arrow path must take priority and match
    at the actual version token, never at "k8s" itself."""
    assert (
        libupgradedocmanifestordering.header_name_segment("openbao - vault-k8s 1.7.2 -> 1.7.2") == "openbao - vault-k8s"
    )


def test_header_name_segment_bare_version_before_parenthetical_no_arrow(libupgradedocmanifestordering: ModuleType):
    """Real bug, real doc: "keycloak-operator - python 3.14.7-slim
    (digest changed)" has NO arrow anywhere (fix-doc-consistency's own
    same-version/changed-digest wording) — VERSION_PAIR_RE finds
    nothing, so the trailing bare version token "3.14.7-slim" must be
    stripped separately, immediately before the "(...)" aside, to
    isolate "keycloak-operator - python" the same way the arrow path
    already isolates a name."""
    assert (
        libupgradedocmanifestordering.header_name_segment("keycloak-operator - python 3.14.7-slim (digest changed)")
        == "keycloak-operator - python"
    )


def test_header_name_segment_bare_version_no_arrow_generic_case(libupgradedocmanifestordering: ModuleType):
    assert libupgradedocmanifestordering.header_name_segment("clamav 1.5.4 (digest changed)") == "clamav"


def test_header_name_segment_name_with_its_own_embedded_parenthetical_no_arrow(
    libupgradedocmanifestordering: ModuleType,
):
    """Real bug, real docs: "mi-data (MI-data exports)" is a real
    component display name that embeds its OWN parenthetical, nowhere
    near the trailing "(new)"/"(chart ...)" asides — truncating at
    wherever the FIRST "(" happens to appear (a first version of this
    fix did exactly that) silently lost everything from "(MI-data" on,
    leaving just the bare "mi-data". Trailing asides must be stripped
    from the END of the string, never by finding the first "(" anywhere."""
    assert (
        libupgradedocmanifestordering.header_name_segment(
            "mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)"
        )
        == "mi-data (MI-data exports)"
    )


def test_header_name_segment_name_with_its_own_embedded_parenthetical_with_arrow(
    libupgradedocmanifestordering: ModuleType,
):
    """Same embedded-parenthetical concern, but for the arrow-present
    path this time — "Keycloak Operator (server)" is real, current doc
    text (4.9.0-to-4.9.1-upgrade.md's own heading)."""
    assert (
        libupgradedocmanifestordering.header_name_segment(
            "Keycloak Operator (server) 26.7.2 -> 26.7.3 (chart 1.12.1 -> 1.13.0)"
        )
        == "Keycloak Operator (server)"
    )


def test_header_name_segment_no_version_no_parenthetical_never_truncated(libupgradedocmanifestordering: ModuleType):
    """No arrow AND no "(...)" aside at all — nothing in this codebase
    ever actually produces this shape, but if it occurred, the whole
    text is the name: there's no trailing token to strip, and a real
    bare-name-only header's own last word (e.g. "python") must never be
    mistaken for a version token just because it matches the same bare
    "word-shaped" pattern."""
    assert (
        libupgradedocmanifestordering.header_name_segment("keycloak-operator - python") == "keycloak-operator - python"
    )


# --- find_images_manifest_faulty_headers ---

REDIS_OPERATOR_DEPS = [{"name": "redis-operator", "version": "1.0.0"}]


def _entry_line_indices(lines):
    return [i for i, line in enumerate(lines) if line.lstrip().startswith("- name:")]


def test_find_images_manifest_faulty_headers_correct_sidecar_header_is_not_flagged(
    libupgradedocmanifestordering: ModuleType,
):
    text = (
        "# redis-operator 0.25.0 -> 0.26.0 (chart 0.25.0 -> 0.26.1)\n"
        "- name: redis-operator\n"
        '  version: "0.26.0"\n'
        "\n"
        "#   sidecar: redis-operator - redis 8.6.2 -> 8.6.6\n"
        "- name: redis-ha\n"
        '  version: "8.6.6"\n'
    )
    lines = text.splitlines()
    entries = [{"name": "redis-operator", "version": "0.26.0"}, {"name": "redis-ha", "version": "8.6.6"}]
    entry_line_indices = _entry_line_indices(lines)
    current_paths = {("redis-operator", "image"): "0.26.0", ("redis-operator", "redis-ha", "image"): "8.6.6"}
    repo_map = {"redis-operator": ("redis-operator", "image"), "redis-ha": ("redis-operator", "redis-ha", "image")}
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}

    problems = libupgradedocmanifestordering.find_images_manifest_faulty_headers(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution(REDIS_OPERATOR_DEPS, current_paths, repo_map, canonical_names),
    )
    assert problems == []


def test_find_images_manifest_faulty_headers_sidecar_sharing_parents_plain_header_is_missing(
    libupgradedocmanifestordering: ModuleType,
):
    """The real kiss-elastic-sync case: a sidecar entry with NO comment
    of its own, sitting right after its parent's plain (unindented, no
    "sidecar:" keyword) header — flagged as "missing", not silently
    treated as covered by the parent's header."""
    text = (
        "# redis-operator 0.25.0 -> 0.26.0 (chart 0.25.0 -> 0.26.1)\n"
        "- name: redis-operator\n"
        '  version: "0.26.0"\n'
        "\n"
        "- name: redis-ha\n"
        '  version: "8.6.6"\n'
    )
    lines = text.splitlines()
    entries = [{"name": "redis-operator", "version": "0.26.0"}, {"name": "redis-ha", "version": "8.6.6"}]
    entry_line_indices = _entry_line_indices(lines)
    current_paths = {("redis-operator", "image"): "0.26.0", ("redis-operator", "redis-ha", "image"): "8.6.6"}
    repo_map = {"redis-operator": ("redis-operator", "image"), "redis-ha": ("redis-operator", "redis-ha", "image")}
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}

    problems = libupgradedocmanifestordering.find_images_manifest_faulty_headers(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution(REDIS_OPERATOR_DEPS, current_paths, repo_map, canonical_names),
    )
    assert problems == [("redis-ha", "redis-operator - redis", "missing")]


def test_find_images_manifest_faulty_headers_sidecar_header_naming_wrong_component(
    libupgradedocmanifestordering: ModuleType,
):
    text = '#   sidecar: redis-operator - redis-exporter 1.82.0 -> 1.89.0\n- name: redis-ha\n  version: "8.6.6"\n'
    lines = text.splitlines()
    entries = [{"name": "redis-ha", "version": "8.6.6"}]
    entry_line_indices = _entry_line_indices(lines)
    current_paths = {("redis-operator", "redis-ha", "image"): "8.6.6"}
    repo_map = {"redis-ha": ("redis-operator", "redis-ha", "image")}
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}

    problems = libupgradedocmanifestordering.find_images_manifest_faulty_headers(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution(REDIS_OPERATOR_DEPS, current_paths, repo_map, canonical_names),
    )
    assert problems == [("redis-ha", "redis-operator - redis", "wrong_name")]


def test_find_images_manifest_faulty_headers_digest_changed_sidecar_not_flagged(
    libupgradedocmanifestordering: ModuleType,
):
    """Real bug, real doc (keycloak-operator's own python init image):
    a correct "#   sidecar: <parent> - <basename> <version> (digest
    changed)" header — the wording fix-doc-consistency now writes for a
    same-version/changed-digest re-pin, with no arrow at all — must NOT
    be flagged as "wrong_name" just because header_name_segment can't
    find a version pair to search for."""
    text = '#   sidecar: redis-operator - redis 8.6.6 (digest changed)\n- name: redis-ha\n  version: "8.6.6"\n'
    lines = text.splitlines()
    entries = [{"name": "redis-ha", "version": "8.6.6"}]
    entry_line_indices = _entry_line_indices(lines)
    current_paths = {("redis-operator", "redis-ha", "image"): "8.6.6"}
    repo_map = {"redis-ha": ("redis-operator", "redis-ha", "image")}
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}

    problems = libupgradedocmanifestordering.find_images_manifest_faulty_headers(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution(REDIS_OPERATOR_DEPS, current_paths, repo_map, canonical_names),
    )
    assert problems == []


def test_find_images_manifest_faulty_headers_primary_entry_never_checked(libupgradedocmanifestordering: ModuleType):
    """A dependency's own primary image is exempt — including a
    multi-container dependency's second co-equal primary sharing the
    first's plain header (zgw-office-addin frontend + backend), which
    is expected and correct, not a sidecar needing its own header."""
    text = (
        "# ZGW Office Add-in -> 0.11.0\n"
        "- name: infonl/zgw-office-addin-frontend\n"
        '  version: "0.11.0"\n'
        "\n"
        "- name: infonl/zgw-office-addin-backend\n"
        '  version: "0.11.0"\n'
    )
    lines = text.splitlines()
    entries = [
        {"name": "infonl/zgw-office-addin-frontend", "version": "0.11.0"},
        {"name": "infonl/zgw-office-addin-backend", "version": "0.11.0"},
    ]
    entry_line_indices = _entry_line_indices(lines)
    deps = [{"name": "zgw-office-addin", "version": "1.0.0"}]
    current_paths = {
        ("zgw-office-addin", "frontend", "image"): "0.11.0",
        ("zgw-office-addin", "backend", "image"): "0.11.0",
    }
    repo_map = {}

    problems = libupgradedocmanifestordering.find_images_manifest_faulty_headers(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution(deps, current_paths, repo_map, {}),
    )
    assert problems == []


def test_find_images_manifest_faulty_headers_unresolvable_entry_skipped(libupgradedocmanifestordering: ModuleType):
    """An entry that doesn't resolve to any values-tree path at all is
    skipped — find_images_manifest_list_diff's unmatched_entry_names
    already reports it; there's no "expected name" to validate a header
    against for something that isn't a real image."""
    text = '- name: does-not-exist\n  version: "1.0.0"\n'
    lines = text.splitlines()
    entries = [{"name": "does-not-exist", "version": "1.0.0"}]
    entry_line_indices = _entry_line_indices(lines)

    problems = libupgradedocmanifestordering.find_images_manifest_faulty_headers(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution([], {}, {}, {}),
    )
    assert problems == []


def test_find_images_manifest_faulty_headers_orphan_top_level_block_is_exempt(
    libupgradedocmanifestordering: ModuleType,
):
    """A path rooted at podiumd's own directly-templated top-level block
    with no Chart.yaml dependency of its own at all (real cases:
    "keycloak", "apiproxy", "frankgateway" — see lib.image.repository_
    check's own docstring) has no PARENT to be a "sidecar OF", so it's
    never subject to the "#   sidecar: <parent> - ..." shape — its own
    free-form header (explaining why it's listed) is correct as-is."""
    text = '# Keycloak server -> 26.7.2 (app image only)\n- name: keycloak/keycloak\n  version: "26.7.2"\n'
    lines = text.splitlines()
    entries = [{"name": "keycloak/keycloak", "version": "26.7.2"}]
    entry_line_indices = _entry_line_indices(lines)
    current_paths = {("keycloak", "image"): "26.7.2"}
    repo_map = {"keycloak/keycloak": ("keycloak", "image")}

    problems = libupgradedocmanifestordering.find_images_manifest_faulty_headers(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution(
            [{"name": "keycloak-operator", "version": "1.0.0"}], current_paths, repo_map, {}
        ),
    )
    assert problems == []


def test_find_images_manifest_faulty_headers_version_paths_for_primary_is_exempt(
    libupgradedocmanifestordering: ModuleType,
):
    """redis-operator's OWN manifest entry (its real app version comes
    from version_paths_for's "redisOperator.imageTag" field, not an
    "image: {tag}" block) is a PRIMARY, not a sidecar — same real case
    -upgrade.md's own "### redis-operator ..." heading already names
    plain "redis-operator", not "redis-operator - <something>"."""
    text = (
        "# redis-operator 0.25.0 -> 0.26.0 (chart 0.25.0 -> 0.26.1)\n"
        "- name: opstree/redis-operator\n"
        '  version: "0.26.0"\n'
    )
    lines = text.splitlines()
    entries = [{"name": "opstree/redis-operator", "version": "0.26.0"}]
    entry_line_indices = _entry_line_indices(lines)
    current_paths = {("redis-operator", "redisOperator", "imageTag"): "0.26.0"}
    repo_map = {"opstree/redis-operator": ("redis-operator", "redisOperator", "imageTag")}

    problems = libupgradedocmanifestordering.find_images_manifest_faulty_headers(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution(REDIS_OPERATOR_DEPS, current_paths, repo_map, {}),
    )
    assert problems == []


# --- images_manifest_entry_order_key ---


def test_images_manifest_entry_order_key_primary_uses_values_key_index(libupgradedocmanifestordering: ModuleType):
    deps = [{"name": "zac", "version": "1.0.0"}]
    key_order = ["redis-operator", "zac"]
    assert libupgradedocmanifestordering.images_manifest_entry_order_key(("zac", "image"), deps, key_order) == (1, 0)


def test_images_manifest_entry_order_key_sidecar_sorts_after_primary(libupgradedocmanifestordering: ModuleType):
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    key_order = ["redis-operator", "zac"]
    assert libupgradedocmanifestordering.images_manifest_entry_order_key(
        ("redis-operator", "redis-ha", "image"), deps, key_order
    ) == (
        0,
        1,
    )


def test_images_manifest_entry_order_key_unresolved_path_sorts_last(libupgradedocmanifestordering: ModuleType):
    """path=None (an entry that doesn't resolve to any real values-tree
    path at all) sorts after every real component — same sentinel
    component_order_key uses for a name matching no dependency."""
    key_order = ["redis-operator", "zac"]
    assert libupgradedocmanifestordering.images_manifest_entry_order_key(None, deps=[], key_order=key_order) == (2, 1)


def test_images_manifest_entry_order_key_unknown_values_key_sorts_last(libupgradedocmanifestordering: ModuleType):
    """path[0] not in key_order at all (shouldn't happen for a real
    resolved path, but stays a sane sentinel rather than crashing)."""
    deps = [{"name": "mystery", "version": "1.0.0"}]
    key_order = ["redis-operator", "zac"]
    assert libupgradedocmanifestordering.images_manifest_entry_order_key(("mystery", "image"), deps, key_order) == (
        2,
        0,
    )


# --- find_images_manifest_out_of_order_names / sort_images_manifest_entries ---


def _images_manifest_two_component_fixture():
    """zac then redis-operator, in that order — own comments, no shared
    groups. `values` has real "image: {tag: ...}" blocks for both, so
    resolve_entry_image_path (used internally by sort_images_manifest_
    entries) actually resolves each entry, not just the standalone
    current_paths/repo_map handed to the out-of-order check directly."""
    text = (
        "# zac 5.0.2 -> 5.4.4\n"
        "- name: infonl/zaakafhandelcomponent\n"
        '  version: "5.4.4"\n'
        "\n"
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        '  version: "0.26.0"\n'
    )
    entries = [
        {"name": "infonl/zaakafhandelcomponent", "version": "5.4.4"},
        {"name": "opstree/redis-operator", "version": "0.26.0"},
    ]
    deps = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0"},
        {"name": "redis-operator", "version": "1.0.0"},
    ]
    values = {"redis-operator": {"image": {"tag": "0.26.0"}}, "zac": {"image": {"tag": "5.4.4"}}}
    current_paths = {("zac", "image"): "5.4.4", ("redis-operator", "image"): "0.26.0"}
    repo_map = {"infonl/zaakafhandelcomponent": ("zac", "image"), "opstree/redis-operator": ("redis-operator", "image")}
    key_order = ["redis-operator", "zac"]
    return text, entries, deps, values, current_paths, repo_map, key_order


def test_find_images_manifest_out_of_order_names_detects_violation(libupgradedocmanifestordering: ModuleType):
    text, entries, deps, _values, current_paths, repo_map, key_order = _images_manifest_two_component_fixture()
    lines = text.splitlines()
    entry_line_indices = _entry_line_indices(lines)

    violations = libupgradedocmanifestordering.find_images_manifest_out_of_order_names(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution(deps, current_paths, repo_map, {}),
        key_order,
    )
    assert violations == [("zac", "redis-operator")]


def test_find_images_manifest_out_of_order_names_correctly_ordered_reports_nothing(
    libupgradedocmanifestordering: ModuleType,
):
    text, entries, deps, _values, current_paths, repo_map, key_order = _images_manifest_two_component_fixture()
    lines = text.splitlines()
    entry_line_indices = _entry_line_indices(lines)
    key_order = ["zac", "redis-operator"]  # now matches the manifest's actual order

    violations = libupgradedocmanifestordering.find_images_manifest_out_of_order_names(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution(deps, current_paths, repo_map, {}),
        key_order,
    )
    assert violations == []


def test_sort_images_manifest_entries_reorders_to_match_values_yaml(libupgradedocmanifestordering: ModuleType):
    text, _entries, deps, values, _current_paths, repo_map, _key_order = _images_manifest_two_component_fixture()
    # values' own dict insertion order (redis-operator, zac) IS values_key_order's source.

    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, {})
    )

    assert moved == [("redis-operator", 2, 1), ("zac", 1, 2)]
    assert new_text.index("redis-operator") < new_text.index("zaakafhandelcomponent")
    # Each entry's own comment travels WITH it, never left behind.
    assert new_text.index("# redis-operator") < new_text.index("- name: opstree/redis-operator")
    assert new_text.index("# zac") < new_text.index("- name: infonl/zaakafhandelcomponent")


def test_sort_images_manifest_entries_already_ordered_reports_nothing(libupgradedocmanifestordering: ModuleType):
    text, _entries, deps, values, _current_paths, repo_map, _key_order = _images_manifest_two_component_fixture()
    values = {"zac": values["zac"], "redis-operator": values["redis-operator"]}  # matches manifest's actual order

    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, {})
    )
    assert moved == []
    assert new_text == text


def test_sort_images_manifest_entries_inserts_missing_blank_line_between_groups(
    libupgradedocmanifestordering: ModuleType,
):
    """Regression test (real bug, real doc): a group's own captured span
    never includes a LEADING blank line (that's the PRECEDING group's
    own trailing space instead) — a pre-existing "zero blank lines
    between these two groups" formatting defect therefore survived
    forever once spliced next to a new neighbor, since this function
    only ever COLLAPSED an excess, never inserted a missing one.
    Confirmed live: images-4.9.1.yaml had no blank line at all between
    its own redis entry and keycloak-operator's, and between
    frankgateway's and zaakbrug's — already in the CORRECT relative
    order here (no `moved` at all), proving this is a pure formatting
    fix, independent of reordering."""
    text = (
        "# zac 5.0.2 -> 5.4.4\n"
        "- name: infonl/zaakafhandelcomponent\n"
        '  version: "5.4.4"\n'
        "# redis-operator 0.25.0 -> 0.26.0\n"  # no blank line above this comment
        "- name: opstree/redis-operator\n"
        '  version: "0.26.0"\n'
    )
    deps = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0"},
        {"name": "redis-operator", "version": "1.0.0"},
    ]
    values = {"zac": {"image": {"tag": "5.4.4"}}, "redis-operator": {"image": {"tag": "0.26.0"}}}
    repo_map = {"infonl/zaakafhandelcomponent": ("zac", "image"), "opstree/redis-operator": ("redis-operator", "image")}

    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, {})
    )

    assert moved == []
    assert '  version: "5.4.4"\n\n# redis-operator 0.25.0 -> 0.26.0\n' in new_text
    assert '"5.4.4"\n# redis-operator' not in new_text  # the original, separator-less join is gone


def test_sort_images_manifest_entries_moves_shared_group_as_one_unit(libupgradedocmanifestordering: ModuleType):
    """A group of entries sharing ONE header (e.g. zgw-office-addin's
    frontend + backend, both primaries of the same dependency) moves
    together — the shared header is never left behind or split from
    only some of the entries it covers."""
    text = (
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        '  version: "0.26.0"\n'
        "\n"
        "# ZGW Office Add-in -> 0.11.0\n"
        "- name: infonl/zgw-office-addin-frontend\n"
        '  version: "0.11.0"\n'
        "\n"
        "- name: infonl/zgw-office-addin-backend\n"
        '  version: "0.11.0"\n'
    )
    deps = [{"name": "redis-operator", "version": "1.0.0"}, {"name": "zgw-office-addin", "version": "1.0.0"}]
    values = {
        "zgw-office-addin": {"frontend": {"image": {"tag": "0.11.0"}}, "backend": {"image": {"tag": "0.11.0"}}},
        "redis-operator": {"image": {"tag": "0.26.0"}},
    }
    repo_map = {
        "opstree/redis-operator": ("redis-operator", "image"),
        "infonl/zgw-office-addin-frontend": ("zgw-office-addin", "frontend", "image"),
        "infonl/zgw-office-addin-backend": ("zgw-office-addin", "backend", "image"),
    }

    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, {})
    )

    assert moved == [("zgw-office-addin", 2, 1), ("redis-operator", 1, 2)]
    assert (
        new_text.index("zgw-office-addin-frontend")
        < new_text.index("zgw-office-addin-backend")
        < new_text.index("opstree/redis-operator")
    )
    assert new_text.index("# ZGW Office Add-in") < new_text.index("zgw-office-addin-frontend")
    # The blank line the fixture had WITHIN the frontend/backend group is
    # gone — entries sharing one header sit directly below each other.
    assert '0.11.0"\n\n- name: infonl/zgw-office-addin-backend' not in new_text
    assert '0.11.0"\n- name: infonl/zgw-office-addin-backend' in new_text


def test_sort_images_manifest_entries_collapses_internal_blank_lines_even_without_reordering(
    libupgradedocmanifestordering: ModuleType,
):
    """A group with a blank line between its own entries gets tidied
    even when NO group actually changes position — this is a separate
    formatting concern from ordering, not conditional on it."""
    text = (
        "# ZGW Office Add-in -> 0.11.0\n"
        "- name: infonl/zgw-office-addin-frontend\n"
        '  version: "0.11.0"\n'
        "\n"
        "- name: infonl/zgw-office-addin-backend\n"
        '  version: "0.11.0"\n'
        "\n"
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        '  version: "0.26.0"\n'
    )
    deps = [{"name": "zgw-office-addin", "version": "1.0.0"}, {"name": "redis-operator", "version": "1.0.0"}]
    values = {
        "zgw-office-addin": {"frontend": {"image": {"tag": "0.11.0"}}, "backend": {"image": {"tag": "0.11.0"}}},
        "redis-operator": {"image": {"tag": "0.26.0"}},
    }
    repo_map = {
        "infonl/zgw-office-addin-frontend": ("zgw-office-addin", "frontend", "image"),
        "infonl/zgw-office-addin-backend": ("zgw-office-addin", "backend", "image"),
        "opstree/redis-operator": ("redis-operator", "image"),
    }

    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, {})
    )

    assert moved == []  # already in the correct order — nothing repositioned
    assert new_text != text  # but the internal blank line was still tidied
    assert '0.11.0"\n\n- name: infonl/zgw-office-addin-backend' not in new_text
    assert '0.11.0"\n- name: infonl/zgw-office-addin-backend' in new_text


def test_sort_images_manifest_entries_collapses_between_separately_headered_sidecars(
    libupgradedocmanifestordering: ModuleType,
):
    """Real bug: a component's own primary image and its sidecars almost
    always have their OWN separate comment header each (different
    versions bumped independently — e.g. keycloak-operator's own
    postgres/python job images never share ITS "26.6.4 -> 26.7.2" header)
    — so they're three separate _images_manifest_groups, not one shared-
    header group. Blank lines must still collapse across all three, not
    just within a single literal shared header — the whole family reads
    as ONE visual block, blank-line-separated only from the NEXT
    component."""
    text = (
        "# keycloak-operator 26.6.4 -> 26.7.2\n"
        "- name: keycloak/keycloak\n"
        '  version: "26.7.2"\n'
        "\n"
        "#   sidecar: keycloak-operator - postgres 16 -> 16.15\n"
        "- name: postgres\n"
        '  version: "16.15"\n'
        "\n"
        "#   sidecar: keycloak-operator - python 3.14-slim -> 3.14.7-slim\n"
        "- name: python\n"
        '  version: "3.14.7-slim"\n'
        "\n"
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        '  version: "0.26.0"\n'
    )
    deps = [{"name": "keycloak-operator", "version": "1.0.0"}, {"name": "redis-operator", "version": "1.0.0"}]
    values = {
        "keycloak-operator": {
            "operator": {"config": {"keycloakImage": {"tag": "26.7.2"}}},
            "job": {"postgres": {"image": {"tag": "16.15"}}, "python": {"image": {"tag": "3.14.7-slim"}}},
        },
        "redis-operator": {"image": {"tag": "0.26.0"}},
    }
    repo_map = {
        "keycloak/keycloak": ("keycloak-operator", "operator", "config", "keycloakImage"),
        "postgres": ("keycloak-operator", "job", "postgres", "image"),
        "python": ("keycloak-operator", "job", "python", "image"),
        "opstree/redis-operator": ("redis-operator", "image"),
    }

    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, {})
    )

    assert moved == []
    # No blank line between the primary and either sidecar, or between
    # the two sidecars — one unbroken block for the whole component.
    assert '26.7.2"\n#   sidecar: keycloak-operator - postgres' in new_text
    assert '16.15"\n#   sidecar: keycloak-operator - python' in new_text
    # The blank line separating this component from the NEXT one (a
    # genuinely different top-level component) is preserved.
    assert '3.14.7-slim"\n\n# redis-operator' in new_text


def test_sort_images_manifest_entries_never_merges_two_unresolved_entries(libupgradedocmanifestordering: ModuleType):
    """Two entries that each fail to resolve to any real values-tree path
    at all must never be merged into one block just because they happen
    to sit next to each other — only a real, matching component
    identifies one family, not "both unknown"."""
    text = (
        "# mystery one\n"
        "- name: totally/unknown-one\n"
        '  version: "1.0.0"\n'
        "\n"
        "# mystery two\n"
        "- name: totally/unknown-two\n"
        '  version: "2.0.0"\n'
    )
    deps = []
    values = {}
    repo_map = {}

    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, {})
    )

    assert new_text == text
    assert moved == []


def test_sort_images_manifest_entries_global_entry_sorts_first_not_last(libupgradedocmanifestordering: ModuleType):
    """Real bug: an entry naming a shared global.images.* anchor (e.g.
    "curlimages/curl") couldn't resolve its own repo_map hit at all
    during sorting — _images_manifest_sorted_groups computed its OWN
    current_paths internally via find_all_image_and_version_paths alone,
    which never includes global_image_paths, so resolve_entry_image_
    path's "path in paths" guard failed and the entry fell through to
    fuzzy name-word matching, landing at the very END of the manifest
    instead of under "global" 's own values.yaml position (first, since
    "global:" is the file's own first top-level key)."""
    text = (
        "# curl 8.21.0 -> 8.21.0\n"
        "- name: curlimages/curl\n"
        '  version: "8.21.0"\n'
        "\n"
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        '  version: "0.26.0"\n'
    )
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    values = {
        "global": {"images": {"curl": {"repository": "curlimages/curl", "tag": "8.21.0@sha256:aaaa"}}},
        "redis-operator": {"image": {"tag": "0.26.0"}},
    }
    repo_map = {"curlimages/curl": ("global", "images", "curl"), "opstree/redis-operator": ("redis-operator", "image")}

    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, {})
    )

    assert moved == []  # already correctly positioned — global sorts before redis-operator
    assert new_text.index("curlimages/curl") < new_text.index("opstree/redis-operator")


def test_sort_images_manifest_entries_multiple_global_images_use_their_own_real_suborder(
    libupgradedocmanifestordering: ModuleType,
):
    """Regression test: the real redis/nginx/curl/busybox bug, for
    images-<version>.yaml's own ENTRY list. FOUR "global.images.*" peers,
    scrambled — must reorder to values.yaml's own true nginx/curl/
    busybox/redis order, not just "global sorts before everything
    else" (already covered by the test above)."""
    text = (
        "# redis 8.0 -> 8.10.1\n"
        "- name: redis\n"
        '  version: "8.10.1"\n'
        "\n"
        "# curl 8.21.0 -> 8.22.0\n"
        "- name: curlimages/curl\n"
        '  version: "8.22.0"\n'
        "\n"
        "# nginx-unprivileged 1.31.4 -> 1.31.5\n"
        "- name: nginxinc/nginx-unprivileged\n"
        '  version: "1.31.5"\n'
        "\n"
        "# busybox 1.37.0 -> 1.38.0-glibc\n"
        "- name: library/busybox\n"
        '  version: "1.38.0-glibc"\n'
    )
    repo_map = {
        "redis": ("global", "images", "redis"),
        "curlimages/curl": ("global", "images", "curl"),
        "nginxinc/nginx-unprivileged": ("global", "images", "nginx"),
        "library/busybox": ("global", "images", "busybox"),
    }

    new_text, _moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text,
        libupgradedocmanifestordering.ManifestSortContext(
            [], GLOBAL_IMAGES_VALUES, repo_map, GLOBAL_IMAGES_CANONICAL_NAMES
        ),
    )

    names_in_order = [
        line.split("name: ", 1)[1].strip() for line in new_text.splitlines() if line.startswith("- name:")
    ]
    assert names_in_order == [
        "nginxinc/nginx-unprivileged",
        "curlimages/curl",
        "library/busybox",
        "redis",
    ]


def test_images_manifest_display_name_positions_matches_entry_positions_order(
    libupgradedocmanifestordering: ModuleType,
):
    """Real bug scenario: "kiss"'s own image basename ("kiss-frontend")
    shares no word with its display name ("kiss"), and "kiss-eck"'s two
    primaries' basenames ("elasticsearch"/"kibana") share no word with
    theirs either — match_changes_item_to_entry can never resolve these
    by fuzzy basename-in-text search. images_manifest_display_name_
    positions must still expose their TRUE position (matching the
    already-correct YAML entry order) keyed by display name so callers
    can match Changes items by exact display-name prefix instead."""
    text = (
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        '  version: "0.26.0"\n'
        "\n"
        "# kiss-eck 8.19.3 -> 8.19.19\n"
        "- name: elasticsearch/elasticsearch\n"
        '  version: "8.19.19"\n'
        "# kiss-eck 8.19.3 -> 8.19.19\n"
        "- name: kibana/kibana\n"
        '  version: "8.19.19"\n'
        "#   sidecar: kiss-eck - enterprise-search 8.19.3 -> 8.19.19\n"
        "- name: enterprise-search/enterprise-search\n"
        '  version: "8.19.19"\n'
        "\n"
        "# kiss 2.2.4 -> 3.0.0\n"
        "- name: klantinteractie-servicesysteem/kiss-frontend\n"
        '  version: "3.0.0"\n'
        "#   sidecar: kiss - crawler 1.0.0 -> 1.0.0\n"
        "- name: integrations/crawler\n"
        '  version: "1.0.0"\n'
    )
    deps = [
        {"name": "redis-operator", "version": "1.0.0"},
        {"name": "eck-stack", "alias": "kiss-eck", "version": "1.0.0"},
        {"name": "klantinteractie-servicesysteem", "alias": "kiss", "version": "1.0.0"},
    ]
    values = {
        "redis-operator": {"redisOperator": {"imageTag": "0.26.0"}},
        "kiss-eck": {
            "eck-elasticsearch": {"version": "8.19.19"},
            "eck-kibana": {"version": "8.19.19"},
            "eck-enterprise-search": {"version": "8.19.19"},
        },
        "kiss": {"image": {"tag": "3.0.0"}, "crawler": {"image": {"tag": "1.0.0"}}},
    }
    repo_map = {
        "opstree/redis-operator": ("redis-operator", "redisOperator", "imageTag"),
        "elasticsearch/elasticsearch": ("kiss-eck", "eck-elasticsearch", "version"),
        "kibana/kibana": ("kiss-eck", "eck-kibana", "version"),
        "enterprise-search/enterprise-search": ("kiss-eck", "eck-enterprise-search", "version"),
        "klantinteractie-servicesysteem/kiss-frontend": ("kiss", "image"),
        "integrations/crawler": ("kiss", "crawler", "image"),
    }
    canonical_names = {
        "kiss - crawler": ("kiss", "crawler", "image"),
        "kiss-eck - enterprise-search": ("kiss-eck", "eck-enterprise-search", "version"),
    }

    display_positions = libupgradedocmanifestordering.images_manifest_display_name_positions(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, canonical_names)
    )

    assert display_positions["kiss"] < display_positions["kiss - crawler"]
    assert display_positions["kiss-eck"] < display_positions["kiss-eck - enterprise-search"]
    assert display_positions["redis-operator"] < display_positions["kiss-eck"]
    assert display_positions["kiss-eck - enterprise-search"] < display_positions["kiss"]


def test_images_manifest_display_name_positions_ambiguous_name_keeps_first_position(
    libupgradedocmanifestordering: ModuleType,
):
    """Two separate groups can legitimately share one display name (e.g.
    two "kiss-eck" primaries for elasticsearch/kibana) — the map must
    keep the FIRST (lowest) position for that name, not the last one it
    happens to see."""
    text = (
        "# kiss-eck 8.19.3 -> 8.19.19\n"
        "- name: elasticsearch/elasticsearch\n"
        '  version: "8.19.19"\n'
        "# kiss-eck 8.19.3 -> 8.19.19\n"
        "- name: kibana/kibana\n"
        '  version: "8.19.19"\n'
    )
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "1.0.0"}]
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}, "eck-kibana": {"version": "8.19.19"}}}
    repo_map = {
        "elasticsearch/elasticsearch": ("kiss-eck", "eck-elasticsearch", "version"),
        "kibana/kibana": ("kiss-eck", "eck-kibana", "version"),
    }

    display_positions = libupgradedocmanifestordering.images_manifest_display_name_positions(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, {})
    )
    assert display_positions == {"kiss-eck": 0}


def test_sort_images_manifest_entries_no_blank_lines_no_reorder_is_truly_unchanged(
    libupgradedocmanifestordering: ModuleType,
):
    """Nothing to tidy and nothing to reorder — text comes back byte-
    identical, matching the function's own "unchanged" convention."""
    text = (
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        '  version: "0.26.0"\n'
        "\n"
        "# zac 5.0.2 -> 5.4.4\n"
        "- name: infonl/zaakafhandelcomponent\n"
        '  version: "5.4.4"\n'
    )
    deps = [
        {"name": "redis-operator", "version": "1.0.0"},
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0"},
    ]
    values = {"redis-operator": {"image": {"tag": "0.26.0"}}, "zac": {"image": {"tag": "5.4.4"}}}
    repo_map = {"opstree/redis-operator": ("redis-operator", "image"), "infonl/zaakafhandelcomponent": ("zac", "image")}

    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext(deps, values, repo_map, {})
    )
    assert new_text == text
    assert moved == []


def test_sort_images_manifest_entries_invalid_yaml_returns_unchanged(libupgradedocmanifestordering: ModuleType):
    text = "not: valid: yaml: at: all: [\n"
    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext([], {}, {}, {})
    )
    assert new_text == text
    assert moved == []


def test_sort_images_manifest_entries_single_entry_reports_nothing(libupgradedocmanifestordering: ModuleType):
    text = '- name: opstree/redis-operator\n  version: "0.26.0"\n'
    new_text, moved = libupgradedocmanifestordering.sort_images_manifest_entries(
        text, libupgradedocmanifestordering.ManifestSortContext([], {}, {}, {})
    )
    assert new_text == text
    assert moved == []


# --- delete_images_manifest_entry ---

TWO_ENTRY_MANIFEST: str = (
    "# Changes:\n"
    "#   1. curl 8.20.0 -> 8.21.0.\n"
    "\n"
    "# curl 8.20.0 -> 8.21.0\n"
    "- name: curlimages/curl\n"
    "  url: docker.io/curlimages/curl\n"
    '  version: "8.21.0"\n'
    "\n"
    "# Applicaties\n"
    "- name: openformulieren/open-forms\n"
    "  url: docker.io/openformulieren/open-forms\n"
    '  version: "3.5.6"\n'
    "\n"
    "# zac 5.4.2 -> 5.4.3\n"
    "- name: infonl/zaakafhandelcomponent\n"
    '  version: "5.4.3"\n'
)


def _entry_line(lines: list[str], name: str) -> int:
    return next(i for i, line in enumerate(lines) if line == f"- name: {name}\n")


def test_delete_images_manifest_entry_removes_entry_and_its_version_comment(
    libupgradedocmanifestordering: ModuleType,
):
    lines = TWO_ENTRY_MANIFEST.splitlines(keepends=True)
    libupgradedocmanifestordering.delete_images_manifest_entry(lines, _entry_line(lines, "curlimages/curl"))
    text = "".join(lines)
    assert "curlimages/curl" not in text
    assert "# curl 8.20.0 -> 8.21.0\n" not in text
    assert "#   1. curl 8.20.0 -> 8.21.0.\n" in text  # the "# Changes:" item is the caller's job
    assert "\n\n\n" not in text  # no doubled blank line left behind


def test_delete_images_manifest_entry_keeps_group_divider_on_next_entry(
    libupgradedocmanifestordering: ModuleType,
):
    """An entry without a version comment of its own, right below a
    "# Applicaties" divider: the divider stays and ends up directly on
    top of the next entry's own comment."""
    lines = TWO_ENTRY_MANIFEST.splitlines(keepends=True)
    libupgradedocmanifestordering.delete_images_manifest_entry(lines, _entry_line(lines, "openformulieren/open-forms"))
    text = "".join(lines)
    assert "open-forms" not in text
    assert "\n\n# Applicaties\n# zac 5.4.2 -> 5.4.3\n- name: infonl/zaakafhandelcomponent\n" in text


def test_delete_images_manifest_entry_keeps_comment_shared_with_next_entry(
    libupgradedocmanifestordering: ModuleType,
):
    """zgw-office-addin-shaped lockstep pair under one comment: deleting
    the first entry keeps the comment for the second."""
    lines = (
        "# zgw-office-addin 0.0.91 -> 0.0.92\n"
        "- name: frontend\n"
        '  version: "0.0.92"\n'
        "- name: backend\n"
        '  version: "0.0.92"\n'
    ).splitlines(keepends=True)
    libupgradedocmanifestordering.delete_images_manifest_entry(lines, 1)
    assert "".join(lines) == ('# zgw-office-addin 0.0.91 -> 0.0.92\n- name: backend\n  version: "0.0.92"\n')


def test_delete_images_manifest_entry_last_entry_leaves_no_trailing_blank(
    libupgradedocmanifestordering: ModuleType,
):
    lines = TWO_ENTRY_MANIFEST.splitlines(keepends=True)
    libupgradedocmanifestordering.delete_images_manifest_entry(
        lines, _entry_line(lines, "infonl/zaakafhandelcomponent")
    )
    text = "".join(lines)
    assert "zaakafhandelcomponent" not in text
    assert text.endswith('  version: "3.5.6"\n')


# --- repository_group_key ---


def test_repository_group_key_uses_the_docker_hub_library_namespace(libchartrepoandpathresolution: ModuleType):
    """The images-manifest "name:" is the url minus its registry host, so
    a bare official Docker Hub image gets its implicit "library/"."""
    key = libchartrepoandpathresolution.repository_group_key
    assert key("python") == "library/python"
    assert key("docker.io/library/python") == "library/python"
    assert key("wearefrank/zaakbrug") == "wearefrank/zaakbrug"
    assert key("ghcr.io/infonl/zaakafhandelcomponent") == "infonl/zaakafhandelcomponent"
    assert key("mcr.microsoft.com/azure-cli") == "azure-cli"


def test_paths_by_repository_joins_a_namespace_only_registry_field(libchartrepoandpathresolution: ModuleType):
    """zaakbrug's "registry: wearefrank" is a Docker Hub namespace, not a
    host: the group key keeps it, same as full_repository_for_path's url."""
    values = {
        "zaakbrug": {"image": {"registry": "wearefrank", "repository": "zaakbrug", "tag": "1.26.18"}},
        "mi": {"image": {"registry": "mcr.microsoft.com", "repository": "azure-cli", "tag": "2.0"}},
        "keycloak-operator": {"initImage": {"registry": "", "repository": "python", "tag": "3.14"}},
    }
    groups = libchartrepoandpathresolution.paths_by_repository(
        None, [], values, [("zaakbrug", "image"), ("mi", "image"), ("keycloak-operator", "initImage")]
    )
    assert groups == {
        "wearefrank/zaakbrug": [("zaakbrug", "image")],
        "azure-cli": [("mi", "image")],
        "library/python": [("keycloak-operator", "initImage")],
    }
