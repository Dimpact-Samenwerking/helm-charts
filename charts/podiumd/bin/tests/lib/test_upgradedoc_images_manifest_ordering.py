"""lib.upgradedoc -- images-manifest entry ordering, grouping, and faulty-header detection."""

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
    """zgw-office-addin frontend and backend are co-equal primaries, not primary plus sidecar."""
    deps = [{"name": "zgw-office-addin", "version": "1.0.0"}]
    assert libchartregisteredpaths.is_primary_image_path(("zgw-office-addin", "frontend", "image"), deps) is True
    assert libchartregisteredpaths.is_primary_image_path(("zgw-office-addin", "backend", "image"), deps) is True


def test_is_primary_image_path_nested_sidecar_is_not_primary(libchartregisteredpaths: ModuleType):
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    assert libchartregisteredpaths.is_primary_image_path(("redis-operator", "redis-ha", "image"), deps) is False


def test_is_primary_image_path_version_paths_for_field_is_primary(libchartregisteredpaths: ModuleType):
    """redis-operator's bare-scalar "redisOperator.imageTag" (version_paths_for) is its primary, so
    its own manifest entry is not a sidecar of itself."""
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    assert libchartregisteredpaths.is_primary_image_path(("redis-operator", "redisOperator", "imageTag"), deps) is True


def test_is_primary_image_path_eck_stack_registered_version_fields_are_primary(libchartregisteredpaths: ModuleType):
    """eck-stack's registered eck-elasticsearch and eck-kibana are co-equal primaries; unregistered
    eck-enterprise-search stays a sidecar needing its own header."""
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "1.0.0"}]
    assert libchartregisteredpaths.is_primary_image_path(("kiss-eck", "eck-elasticsearch", "version"), deps) is True
    assert libchartregisteredpaths.is_primary_image_path(("kiss-eck", "eck-kibana", "version"), deps) is True
    assert (
        libchartregisteredpaths.is_primary_image_path(("kiss-eck", "eck-enterprise-search", "version"), deps) is False
    )


def test_is_primary_image_path_no_owning_dependency_is_primary(libchartregisteredpaths: ModuleType):
    """A path with no owning dependency (top-level block, "global") has no parent, so it is primary."""
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
    """A self-referential "X -> X" pair takes the arrow path, not the bare-version branch."""
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
    """Regression: with a real arrow pair, "openbao - vault-k8s" splits at the version, not at "k8s"."""
    assert (
        libupgradedocmanifestordering.header_name_segment("openbao - vault-k8s 1.7.2 -> 1.7.2") == "openbao - vault-k8s"
    )


def test_header_name_segment_bare_version_before_parenthetical_no_arrow(libupgradedocmanifestordering: ModuleType):
    """Regression: with no arrow ("keycloak-operator - python 3.14.7-slim (digest changed)"), the bare
    version before the aside is stripped to isolate the name."""
    assert (
        libupgradedocmanifestordering.header_name_segment("keycloak-operator - python 3.14.7-slim (digest changed)")
        == "keycloak-operator - python"
    )


def test_header_name_segment_bare_version_no_arrow_generic_case(libupgradedocmanifestordering: ModuleType):
    assert libupgradedocmanifestordering.header_name_segment("clamav 1.5.4 (digest changed)") == "clamav"


def test_header_name_segment_name_with_its_own_embedded_parenthetical_no_arrow(
    libupgradedocmanifestordering: ModuleType,
):
    """Regression: a name with its own parenthetical ("mi-data (MI-data exports)") keeps it; asides are
    stripped from the end, not at the first "("."""
    assert (
        libupgradedocmanifestordering.header_name_segment(
            "mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)"
        )
        == "mi-data (MI-data exports)"
    )


def test_header_name_segment_name_with_its_own_embedded_parenthetical_with_arrow(
    libupgradedocmanifestordering: ModuleType,
):
    """Embedded-parenthetical name ("Keycloak Operator (server)") with an arrow present."""
    assert (
        libupgradedocmanifestordering.header_name_segment(
            "Keycloak Operator (server) 26.7.2 -> 26.7.3 (chart 1.12.1 -> 1.13.0)"
        )
        == "Keycloak Operator (server)"
    )


def test_header_name_segment_no_version_no_parenthetical_never_truncated(libupgradedocmanifestordering: ModuleType):
    """No arrow and no aside: the whole text is the name; a last word like "python" is not taken as a
    version."""
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
    """kiss-elastic-sync: an uncommented sidecar after its parent's plain header is "missing", not
    covered by the parent's header."""
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
    """Regression: a same-version "sidecar: <parent> - <image-basename> <version> (digest changed)" header
    has no arrow but is not "wrong_name"."""
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


def test_find_images_manifest_faulty_headers_primary_entry_never_checked(
    libupgradedocmanifestordering: ModuleType,
    libupgradedocappversion: ModuleType,
    libchartregisteredpaths: ModuleType,
):
    """Primary images are exempt, including a second co-equal primary sharing the first's plain header
    (zgw-office-addin)."""
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
    repo_map = {
        "infonl/zgw-office-addin-frontend": ("zgw-office-addin", "frontend", "image"),
        "infonl/zgw-office-addin-backend": ("zgw-office-addin", "backend", "image"),
    }
    # Both entries resolve via repo_map, so the empty result proves the primary exemption, not a skip.
    for entry in entries:
        path = libupgradedocappversion.resolve_entry_image_path(entry["name"], current_paths, repo_map)
        assert path is not None
        assert path == repo_map[entry["name"]]
        assert libchartregisteredpaths.is_primary_image_path(path, deps) is True

    problems = libupgradedocmanifestordering.find_images_manifest_faulty_headers(
        libupgradedocmanifestordering.ParsedManifest(entries, entry_line_indices, lines),
        libupgradedocmanifestordering.EntryResolution(deps, current_paths, repo_map, {}),
    )
    assert problems == []


def test_find_images_manifest_faulty_headers_unresolvable_entry_skipped(libupgradedocmanifestordering: ModuleType):
    """An unresolvable entry is skipped: list_diff reports it and there is no expected name."""
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
    """A top-level block without a dependency (keycloak, apiproxy, frankgateway) has no parent, so its
    free-form header is not checked against the sidecar shape."""
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
    """redis-operator's version_paths_for entry is a primary, matching its plain -upgrade.md heading."""
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


# --- path_order_key ---


def test_path_order_key_primary_uses_values_key_index(libupgradedocmanifestordering: ModuleType):
    deps = [{"name": "zac", "version": "1.0.0"}]
    key_order = ["redis-operator", "zac"]
    assert libupgradedocmanifestordering.path_order_key(("zac", "image"), deps, key_order) == (1, 0)


def test_path_order_key_sidecar_sorts_after_primary(libupgradedocmanifestordering: ModuleType):
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    key_order = ["redis-operator", "zac"]
    assert libupgradedocmanifestordering.path_order_key(("redis-operator", "redis-ha", "image"), deps, key_order) == (
        0,
        1,
    )


def test_path_order_key_unresolved_path_sorts_last(libupgradedocmanifestordering: ModuleType):
    """An unresolved entry sorts last, like component_order_key's no-dependency sentinel."""
    key_order = ["redis-operator", "zac"]
    assert libupgradedocmanifestordering.path_order_key(None, deps=[], key_order=key_order) == (2, 1)


def test_path_order_key_unknown_values_key_sorts_last(libupgradedocmanifestordering: ModuleType):
    """A path[0] missing from key_order sorts last instead of crashing."""
    deps = [{"name": "mystery", "version": "1.0.0"}]
    key_order = ["redis-operator", "zac"]
    assert libupgradedocmanifestordering.path_order_key(("mystery", "image"), deps, key_order) == (
        2,
        0,
    )


# --- sort_images_manifest_entries ---


def _images_manifest_two_component_fixture():
    """zac then redis-operator, each with its own comment; `values` has real image blocks so
    sort_images_manifest_entries can resolve the entries itself."""
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
    """Regression: a missing blank line between groups is inserted, not only excess ones collapsed.

    A group's span never includes a leading blank line, so the defect survived without reordering
    (seen in images-4.9.1.yaml)."""
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
    """Entries sharing one header move together with it."""
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
    # Entries sharing one header lose the blank line between them.
    assert '0.11.0"\n\n- name: infonl/zgw-office-addin-backend' not in new_text
    assert '0.11.0"\n- name: infonl/zgw-office-addin-backend' in new_text


def test_sort_images_manifest_entries_collapses_internal_blank_lines_even_without_reordering(
    libupgradedocmanifestordering: ModuleType,
):
    """Internal blank lines are tidied even when no group moves."""
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
    """Regression: a primary and its separately-headered sidecars (keycloak-operator's postgres/python
    job images) form one blank-line-free block, separated only from the next component."""
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
    # One unbroken block for the whole component.
    assert '26.7.2"\n#   sidecar: keycloak-operator - postgres' in new_text
    assert '16.15"\n#   sidecar: keycloak-operator - python' in new_text
    # The separator before the next component is kept.
    assert '3.14.7-slim"\n\n# redis-operator' in new_text


def test_sort_images_manifest_entries_never_merges_two_unresolved_entries(libupgradedocmanifestordering: ModuleType):
    """Two adjacent unresolved entries are never merged into one family."""
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
    """Regression: a global.images.* entry resolves via repo_map during sorting (global_image_paths
    included), so it sorts first instead of falling to the end via fuzzy matching."""
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
    """Regression: several global.images.* entries follow values.yaml's own sub-order."""
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
    """Display names sharing no word with their basenames (kiss, kiss-eck) still map to their true
    entry position, so Changes items can match by exact display-name prefix."""
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
    """A display name shared by two groups (kiss-eck) keeps its first position."""
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
    """Nothing to tidy or reorder: text is returned byte-identical."""
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
    """Deleting an uncommented entry below a divider keeps the divider on the next entry."""
    lines = TWO_ENTRY_MANIFEST.splitlines(keepends=True)
    libupgradedocmanifestordering.delete_images_manifest_entry(lines, _entry_line(lines, "openformulieren/open-forms"))
    text = "".join(lines)
    assert "open-forms" not in text
    assert "\n\n# Applicaties\n# zac 5.4.2 -> 5.4.3\n- name: infonl/zaakafhandelcomponent\n" in text


def test_delete_images_manifest_entry_keeps_comment_shared_with_next_entry(
    libupgradedocmanifestordering: ModuleType,
):
    """Deleting the first of a lockstep pair keeps the shared comment for the second."""
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
    """The manifest name is the url minus the registry host, so official images get "library/"."""
    key = libchartrepoandpathresolution.repository_group_key
    assert key("python") == "library/python"
    assert key("docker.io/library/python") == "library/python"
    assert key("wearefrank/zaakbrug") == "wearefrank/zaakbrug"
    assert key("ghcr.io/infonl/zaakafhandelcomponent") == "infonl/zaakafhandelcomponent"
    assert key("mcr.microsoft.com/azure-cli") == "azure-cli"


def test_paths_by_repository_joins_a_namespace_only_registry_field(libchartrepoandpathresolution: ModuleType):
    """A namespace-only "registry: wearefrank" is kept in the key, as in full_repository_for_path."""
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
