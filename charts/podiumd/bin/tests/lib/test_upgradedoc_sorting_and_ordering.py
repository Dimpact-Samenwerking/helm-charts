"""lib.upgradedoc -- values-tree/component ordering keys and
upgrade-doc row/changes-block/values-delta-section sorting."""


# --- values_key_order ---


def test_values_key_order_returns_top_level_keys_in_file_order(libupgradedocsorting):
    values = {"zac": {}, "openzaak": {}, "openinwoner": {}}
    assert libupgradedocsorting.values_key_order(values) == ["zac", "openzaak", "openinwoner"]


def test_values_key_order_non_dict_returns_empty(libupgradedocsorting):
    assert libupgradedocsorting.values_key_order(None) == []


# --- component_order_key ---

DEPS = [
    {"name": "openzaak", "version": "1.14.2"},
    {"name": "openinwoner", "version": "2.4.0"},
    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
]
KEY_ORDER = ["openzaak", "zac", "openinwoner"]


def test_component_order_key_matches_by_alias(libupgradedocsorting):
    assert libupgradedocsorting.component_order_key("ZAC", DEPS, KEY_ORDER) == (1, 0)


def test_component_order_key_matches_free_form_name(libupgradedocsorting):
    assert libupgradedocsorting.component_order_key("Open Zaak", DEPS, KEY_ORDER) == (0, 0)


def test_component_order_key_unmatched_name_sorts_after_every_real_component(libupgradedocsorting):
    assert libupgradedocsorting.component_order_key("nginx-unprivileged (shared sidecar)", DEPS, KEY_ORDER) == (
        len(KEY_ORDER),
        0,
    )


def test_component_order_key_global_shared_image_uses_its_own_values_position(libupgradedocsorting):
    """Real bug: a bare "global" shared-image name (e.g. "nginx-
    unprivileged") never embeds any dependency's own name/alias as a
    substring, so match_dependency finds nothing and this used to always
    fall to the "unmatched sorts last" sentinel — even though "global:"
    is values.yaml's own FIRST top-level key. Given canonical_names, it
    now resolves via its own real position instead."""
    key_order = ["global"] + KEY_ORDER
    canonical_names = {"nginx-unprivileged": ("global", "images", "nginx")}

    assert libupgradedocsorting.component_order_key("nginx-unprivileged", DEPS, key_order, canonical_names) == (0, 0)

    # A "### ..." Changes heading has version/arrow text after the name —
    # match_canonical_sidecar_name's own fuzzy word-span fallback still
    # finds it.
    assert libupgradedocsorting.component_order_key(
        "nginx-unprivileged 1.31.3 → 1.31.4", DEPS, key_order, canonical_names
    ) == (0, 0)


def test_component_order_key_no_canonical_names_given_is_unaffected(libupgradedocsorting):
    """Omitting canonical_names entirely behaves exactly as before — real
    dependency names and their own sidecars are never affected by this
    parameter either way."""
    assert libupgradedocsorting.component_order_key("nginx-unprivileged", DEPS, KEY_ORDER) == (len(KEY_ORDER), 0)


def test_component_order_key_native_component_uses_its_own_values_position(libupgradedocsorting):
    """frankgateway (see lib.chart.NATIVE_COMPONENTS) has no Chart.yaml
    dependency to match_dependency resolve at all — falls back to
    match_native_component, so its own row/section still sorts at its
    real values.yaml position instead of always last."""
    key_order = KEY_ORDER + ["frankgateway"]
    assert libupgradedocsorting.component_order_key("frankgateway", DEPS, key_order) == (len(KEY_ORDER), 0)

    # A "### ..." Changes heading has version/arrow text after the name —
    # match_native_component's own word-span matching still finds it.
    assert libupgradedocsorting.component_order_key("frankgateway 100 → 104", DEPS, key_order) == (len(KEY_ORDER), 0)


def test_component_order_key_matched_dep_not_in_key_order_sorts_last(libupgradedocsorting):
    """A dependency that resolves fine but isn't a top-level values.yaml key
    at all (e.g. removed from values.yaml but still in Chart.yaml) can't be
    placed meaningfully -- falls back to the same "sorts last" sentinel as
    an unmatched name."""
    deps = [{"name": "totallyabsent", "version": "1.0.0"}]
    assert libupgradedocsorting.component_order_key("TotallyAbsent", deps, KEY_ORDER) == (len(KEY_ORDER), 0)


def test_component_order_key_sidecar_sorts_after_its_own_parent_row(libupgradedocsorting):
    """A canonical sidecar name ("<parent> - <basename>") always resolves
    to the SAME values_key_index as its owning dependency's own row via
    match_dependency's fuzzy word-containment — the " - " secondary bit
    is what keeps the sidecar from sorting before (or, without any
    tie-break, merely wherever it already happened to be — Python's sort
    is stable) its own parent."""
    assert libupgradedocsorting.component_order_key(
        "redis-operator", DEPS + [{"name": "redis-operator", "version": "0.26.0"}], KEY_ORDER + ["redis-operator"]
    ) == (3, 0)
    assert libupgradedocsorting.component_order_key(
        "redis-operator - redis",
        DEPS + [{"name": "redis-operator", "version": "0.26.0"}],
        KEY_ORDER + ["redis-operator"],
    ) == (3, 1)


# --- values_tree_position ---

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


def test_values_tree_position_walks_full_nested_structure(libupgradedocsorting):
    """Real bug this closes: nginx/curl/busybox/redis are all genuinely
    different, independently-orderable images sharing the exact same
    "global.images.*" prefix — every existing sort-key function only
    ever resolved a path down to its TOP-LEVEL key, tying all four at
    the same index and leaving their own relative order to whatever a
    stable sort happened to preserve (confirmed live: four documents,
    four different, individually wrong orderings). This walks the FULL
    path, one index per level."""
    assert libupgradedocsorting.values_tree_position(GLOBAL_IMAGES_VALUES, ("global", "images", "nginx")) == (0, 0, 0)
    assert libupgradedocsorting.values_tree_position(GLOBAL_IMAGES_VALUES, ("global", "images", "curl")) == (0, 0, 1)
    assert libupgradedocsorting.values_tree_position(GLOBAL_IMAGES_VALUES, ("global", "images", "busybox")) == (0, 0, 2)
    assert libupgradedocsorting.values_tree_position(GLOBAL_IMAGES_VALUES, ("global", "images", "redis")) == (0, 0, 3)
    assert libupgradedocsorting.values_tree_position(GLOBAL_IMAGES_VALUES, ("zac", "image")) == (1, 0)


def test_values_tree_position_shorter_prefix_always_sorts_first(libupgradedocsorting):
    """A dependency's own bare 1-tuple identity (never resolved down
    into whichever specific image path its app version came from) is a
    genuine PREFIX of any of its own nested sidecar paths — Python's own
    tuple-comparison rule makes it sort first regardless of what the
    sidecar's own deeper indices happen to be, with no separate is-
    sidecar bit needed at this level."""
    assert libupgradedocsorting.values_tree_position(
        GLOBAL_IMAGES_VALUES, ("zac",)
    ) < libupgradedocsorting.values_tree_position(GLOBAL_IMAGES_VALUES, ("zac", "image"))


def test_values_tree_position_unresolvable_segment_sorts_last_never_crashes(libupgradedocsorting):
    assert libupgradedocsorting.values_tree_position(GLOBAL_IMAGES_VALUES, ("global", "images", "mystery")) == (0, 0, 4)
    assert libupgradedocsorting.values_tree_position(GLOBAL_IMAGES_VALUES, ("totally", "absent")) == (2,)


def test_component_order_key_distinguishes_multiple_global_images_given_values(libupgradedocsorting):
    """Regression test: the real redis/nginx/curl/busybox bug. Without
    `values`, all four canonical "global" shared-image names tie at the
    exact same (index, is_sidecar) key (see test_component_order_key_
    global_shared_image_uses_its_own_values_position — the pre-existing
    behavior this must never change). Given `values`, they resolve to
    their own real, distinct sub-positions instead, matching values.
    yaml's own true nginx/curl/busybox/redis order."""
    key_order = ["global", "zac"]
    without_values = [
        libupgradedocsorting.component_order_key(name, [], key_order, GLOBAL_IMAGES_CANONICAL_NAMES)
        for name in ("nginx-unprivileged", "curl", "busybox", "redis")
    ]
    assert without_values == [(0, 0)] * 4  # the pre-existing, now-fixed tie

    with_values = [
        libupgradedocsorting.component_order_key(
            name, [], key_order, GLOBAL_IMAGES_CANONICAL_NAMES, GLOBAL_IMAGES_VALUES
        )
        for name in ("nginx-unprivileged", "curl", "busybox", "redis")
    ]
    assert with_values == sorted(with_values)  # already in the correct order
    assert len(set(with_values)) == 4  # no longer tied


# --- find_out_of_order_names ---


def test_find_out_of_order_names_correctly_ordered_is_empty(libupgradedocsorting):
    names = ["Open Zaak", "ZAC", "Open Inwoner"]
    assert libupgradedocsorting.find_out_of_order_names(names, DEPS, KEY_ORDER) == []


def test_find_out_of_order_names_flags_a_swapped_pair(libupgradedocsorting):
    names = ["ZAC", "Open Zaak", "Open Inwoner"]
    assert libupgradedocsorting.find_out_of_order_names(names, DEPS, KEY_ORDER) == [("ZAC", "Open Zaak")]


def test_find_out_of_order_names_two_unmatched_names_never_conflict(libupgradedocsorting):
    names = ["Some Shared Sidecar", "Another Shared Thing"]
    assert libupgradedocsorting.find_out_of_order_names(names, DEPS, KEY_ORDER) == []


def test_find_out_of_order_names_unmatched_before_a_real_component_is_flagged(libupgradedocsorting):
    """An unmatched row/heading sorts after every real component -- one
    appearing BEFORE a real component earlier in values.yaml's own order is
    still a genuine violation."""
    names = ["Some Shared Sidecar", "Open Zaak"]
    assert libupgradedocsorting.find_out_of_order_names(names, DEPS, KEY_ORDER) == [
        ("Some Shared Sidecar", "Open Zaak")
    ]


# --- insertion_index ---


def test_insertion_index_middle(libupgradedocsorting):
    assert libupgradedocsorting.insertion_index(1, [0, 2, 3]) == 1


def test_insertion_index_start(libupgradedocsorting):
    assert libupgradedocsorting.insertion_index(-1, [0, 2, 3]) == 0


def test_insertion_index_end(libupgradedocsorting):
    assert libupgradedocsorting.insertion_index(5, [0, 2, 3]) == 3


def test_insertion_index_empty_existing(libupgradedocsorting):
    assert libupgradedocsorting.insertion_index(0, []) == 0


def test_insertion_index_real_component_goes_before_unmatched_ones(libupgradedocsorting):
    """A genuinely new, resolvable component (a real, early key) inserted
    where every existing item is an unmatched/sentinel-keyed row belongs
    BEFORE all of them -- matches how a real component is expected to sort
    ahead of a generic/unmatched summary row."""
    assert libupgradedocsorting.insertion_index(0, [3, 3, 3]) == 0


def test_insertion_index_new_unmatched_item_among_unmatched_ones_goes_last(libupgradedocsorting):
    """A new item that itself carries the sentinel key (unmatched) is never
    inserted ahead of other unmatched items without evidence it belongs
    there -- it goes after all of them, preserving their relative order."""
    assert libupgradedocsorting.insertion_index(3, [3, 3, 3]) == 3


# --- parse_upgrade_doc_changes_blocks ---


def test_parse_upgrade_doc_changes_blocks_basic(libupgradedocsorting):
    text = (
        "# Title\n\n"
        "## Changes\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "Some prose.\n\n"
        "### Open Inwoner 2.3.1 → 2.4.2\n\n"
        "More prose.\n"
    )
    blocks = libupgradedocsorting.parse_upgrade_doc_changes_blocks(text)
    assert [b["heading"] for b in blocks] == ["Open Zaak 1.27.3 → 1.27.4", "Open Inwoner 2.3.1 → 2.4.2"]


def test_parse_upgrade_doc_changes_blocks_h4_subheading_is_not_a_separate_block(libupgradedocsorting):
    text = "## Changes\n\n### Open Zaak 1.27.3 → 1.27.4\n\n#### Action required\n\nNo action required.\n"
    blocks = libupgradedocsorting.parse_upgrade_doc_changes_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["heading"] == "Open Zaak 1.27.3 → 1.27.4"


def test_parse_upgrade_doc_changes_blocks_no_changes_section_is_empty(libupgradedocsorting):
    assert libupgradedocsorting.parse_upgrade_doc_changes_blocks("# Title\n\nJust prose.\n") == []


def test_parse_upgrade_doc_changes_blocks_stops_at_next_h2(libupgradedocsorting):
    text = (
        "## Changes\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "Some prose.\n\n"
        "## Per-environment checklist\n\n"
        "### A. Prepare\n\n"
        "- [ ] Do the thing.\n"
    )
    blocks = libupgradedocsorting.parse_upgrade_doc_changes_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["heading"] == "Open Zaak 1.27.3 → 1.27.4"


# --- sort_upgrade_doc_rows ---

COMPONENT_VERSIONS_HEADING = "## Component versions (4.9.0 vs 4.8.5)\n\n"


def test_sort_upgrade_doc_rows_reorders_out_of_order_rows(libupgradedocsorting):
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart |\n"
        "| --- | --- | --- |\n"
        "| Open Inwoner | 2.4.2 | 2.4.0 |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 |\n"
    )
    new_text, moved = libupgradedocsorting.sort_upgrade_doc_rows(
        text, DEPS, {"openzaak": {}, "zac": {}, "openinwoner": {}}
    )
    assert moved == [("Open Zaak", 2, 1), ("Open Inwoner", 1, 2)]
    lines = new_text.splitlines()
    assert lines[4].startswith("| Open Zaak")
    assert lines[5].startswith("| Open Inwoner")


def test_sort_upgrade_doc_rows_already_in_order_is_unchanged(libupgradedocsorting):
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart |\n"
        "| --- | --- | --- |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 |\n"
        "| Open Inwoner | 2.4.2 | 2.4.0 |\n"
    )
    values = {"openzaak": {}, "zac": {}, "openinwoner": {}}
    new_text, moved = libupgradedocsorting.sort_upgrade_doc_rows(text, DEPS, values)
    assert moved == []
    assert new_text == text


def test_sort_upgrade_doc_rows_fewer_than_two_rows_is_unchanged(libupgradedocsorting):
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart |\n"
        "| --- | --- | --- |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 |\n"
    )
    new_text, moved = libupgradedocsorting.sort_upgrade_doc_rows(text, DEPS, {"openzaak": {}})
    assert moved == []
    assert new_text == text


def test_sort_upgrade_doc_rows_unmatched_row_stays_last(libupgradedocsorting):
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart |\n"
        "| --- | --- | --- |\n"
        "| nginx-unprivileged (shared sidecar) | 1.31.4 | — |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 |\n"
    )
    values = {"openzaak": {}, "zac": {}, "openinwoner": {}}
    new_text, moved = libupgradedocsorting.sort_upgrade_doc_rows(text, DEPS, values)
    lines = new_text.splitlines()
    assert lines[4].startswith("| Open Zaak")
    assert lines[5].startswith("| nginx-unprivileged")


def test_sort_upgrade_doc_rows_global_row_sorts_to_its_own_real_position(libupgradedocsorting):
    """Real bug: "nginx-unprivileged" (a canonical "global" shared-image
    row — see canonical_sidecar_row_names) always sorted LAST, even
    though "global:" is values.yaml's own FIRST top-level key and the
    images-manifest's own equivalent sort already places it there. Given
    canonical_names, it now sorts to the front, matching images-v2.yaml's
    own order."""
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart |\n"
        "| --- | --- | --- |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 |\n"
        "| nginx-unprivileged | 1.31.3 → 1.31.4 | - |\n"
        "| Open Inwoner | 2.4.2 | 2.4.0 |\n"
    )
    values = {"global": {}, "openzaak": {}, "zac": {}, "openinwoner": {}}
    canonical_names = {"nginx-unprivileged": ("global", "images", "nginx")}

    new_text, moved = libupgradedocsorting.sort_upgrade_doc_rows(text, DEPS, values, canonical_names)

    lines = new_text.splitlines()
    assert lines[4].startswith("| nginx-unprivileged")
    assert lines[5].startswith("| Open Zaak")
    assert lines[6].startswith("| Open Inwoner")


def test_sort_upgrade_doc_rows_multiple_global_images_use_their_own_real_suborder(libupgradedocsorting):
    """Regression test: the real redis/nginx/curl/busybox bug. FOUR
    canonical "global" shared-image rows (all peers under values.yaml's
    own "global.images.*") plus one real dependency ("zac") — given
    `values`, they must reorder to values.yaml's own true order
    (nginx-unprivileged, curl, busybox, redis), with "zac" still
    correctly sorting after "global" as a whole (its own top-level key
    comes second in values.yaml)."""
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart |\n"
        "| --- | --- | --- |\n"
        "| redis | 8.0 → 8.10.1 | - |\n"
        "| Zaak - ZAC | 5.4.2 → 5.4.3 | - |\n"
        "| curl | 8.21.0 → 8.22.0 | - |\n"
        "| nginx-unprivileged | 1.31.4 → 1.31.5 | - |\n"
        "| busybox | 1.37.0 → 1.38.0-glibc | - |\n"
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]

    new_text, moved = libupgradedocsorting.sort_upgrade_doc_rows(
        text, deps, GLOBAL_IMAGES_VALUES, GLOBAL_IMAGES_CANONICAL_NAMES
    )

    lines = [
        line for line in new_text.splitlines() if line.startswith("|") and "Component" not in line and "---" not in line
    ]
    assert lines == [
        "| nginx-unprivileged | 1.31.4 → 1.31.5 | - |",
        "| curl | 8.21.0 → 8.22.0 | - |",
        "| busybox | 1.37.0 → 1.38.0-glibc | - |",
        "| redis | 8.0 → 8.10.1 | - |",
        "| Zaak - ZAC | 5.4.2 → 5.4.3 | - |",
    ]


# --- sort_changes_blocks ---


def test_sort_changes_blocks_reorders_and_preserves_block_content(libupgradedocsorting):
    text = (
        "## Changes\n\n"
        "### Open Inwoner 2.3.1 → 2.4.2\n\n"
        "Inwoner details here.\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "Zaak details here.\n"
    )
    values = {"openzaak": {}, "zac": {}, "openinwoner": {}}
    new_text, moved = libupgradedocsorting.sort_changes_blocks(text, DEPS, values)
    assert moved == [("Open Zaak 1.27.3 → 1.27.4", 2, 1), ("Open Inwoner 2.3.1 → 2.4.2", 1, 2)]
    assert "### Open Zaak 1.27.3 → 1.27.4\n\nZaak details here.\n" in new_text
    assert new_text.index("### Open Zaak") < new_text.index("### Open Inwoner")


def test_sort_changes_blocks_already_in_order_is_unchanged(libupgradedocsorting):
    text = (
        "## Changes\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "Zaak details.\n\n"
        "### Open Inwoner 2.3.1 → 2.4.2\n\n"
        "Inwoner details.\n"
    )
    values = {"openzaak": {}, "zac": {}, "openinwoner": {}}
    new_text, moved = libupgradedocsorting.sort_changes_blocks(text, DEPS, values)
    assert moved == []
    assert new_text == text


def test_sort_changes_blocks_unmatched_block_stays_last_and_later_h2_untouched(libupgradedocsorting):
    text = (
        "## Changes\n\n"
        "### Fix: something unrelated to any component\n\n"
        "Generic prose.\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "Zaak details.\n\n"
        "## Per-environment checklist\n\n"
        "### A. Prepare\n\n"
        "- [ ] Do the thing.\n"
    )
    values = {"openzaak": {}, "zac": {}, "openinwoner": {}}
    new_text, moved = libupgradedocsorting.sort_changes_blocks(text, DEPS, values)
    assert new_text.index("### Open Zaak") < new_text.index("### Fix: something unrelated")
    assert "## Per-environment checklist\n\n### A. Prepare\n\n- [ ] Do the thing.\n" in new_text


def test_sort_changes_blocks_global_block_sorts_to_its_own_real_position(libupgradedocsorting):
    """Same real bug as sort_upgrade_doc_rows, for the "### ..." Changes
    heading shape — the heading text has version/arrow text after the
    canonical name (match_canonical_sidecar_name's own fuzzy word-span
    fallback handles that, unlike an exact dict-key lookup)."""
    text = (
        "## Changes\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "Zaak details.\n\n"
        "### nginx-unprivileged 1.31.3 → 1.31.4\n\n"
        "Shared image details.\n\n"
        "### Open Inwoner 2.4.2 → 2.4.3\n\n"
        "Inwoner details.\n"
    )
    values = {"global": {}, "openzaak": {}, "zac": {}, "openinwoner": {}}
    canonical_names = {"nginx-unprivileged": ("global", "images", "nginx")}

    new_text, moved = libupgradedocsorting.sort_changes_blocks(text, DEPS, values, canonical_names)

    assert (
        new_text.index("### nginx-unprivileged") < new_text.index("### Open Zaak") < new_text.index("### Open Inwoner")
    )


def test_sort_changes_blocks_multiple_global_images_use_their_own_real_suborder(libupgradedocsorting):
    """The Changes-heading shape of the same real redis/nginx/curl/
    busybox regression test above."""
    text = (
        "## Changes\n\n"
        "### redis 8.0 → 8.10.1\n\nRedis details.\n\n"
        "### Zaak - ZAC 5.4.2 → 5.4.3\n\nZaak details.\n\n"
        "### curl 8.21.0 → 8.22.0\n\nCurl details.\n\n"
        "### nginx-unprivileged 1.31.4 → 1.31.5\n\nNginx details.\n\n"
        "### busybox 1.37.0 → 1.38.0-glibc\n\nBusybox details.\n"
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]

    new_text, moved = libupgradedocsorting.sort_changes_blocks(
        text, deps, GLOBAL_IMAGES_VALUES, GLOBAL_IMAGES_CANONICAL_NAMES
    )

    headings = [line for line in new_text.splitlines() if line.startswith("### ")]
    assert headings == [
        "### nginx-unprivileged 1.31.4 → 1.31.5",
        "### curl 8.21.0 → 8.22.0",
        "### busybox 1.37.0 → 1.38.0-glibc",
        "### redis 8.0 → 8.10.1",
        "### Zaak - ZAC 5.4.2 → 5.4.3",
    ]


def test_sort_changes_blocks_fewer_than_two_blocks_is_unchanged(libupgradedocsorting):
    text = "## Changes\n\n### Open Zaak 1.27.3 → 1.27.4\n\nZaak details.\n"
    new_text, moved = libupgradedocsorting.sort_changes_blocks(text, DEPS, {"openzaak": {}})
    assert moved == []
    assert new_text == text


# --- parse_values_delta_sections ---


def test_parse_values_delta_sections_finds_top_level_headings(libupgradedocsorting):
    text = (
        "# Values deltas\n\n"
        "Intro prose, not part of any section.\n\n"
        "## KISS 2.2.4 → 3.0.0 — required edits\n\n"
        "Some required edits.\n\n"
        "### 1. A sub-heading\n\n"
        "Still part of the KISS section.\n\n"
        "## PABC 1.1.0 → 1.1.1 no values changes\n\n"
        "PABC app and chart bump only.\n"
    )
    sections = libupgradedocsorting.parse_values_delta_sections(text)
    assert [s["heading"] for s in sections] == [
        "KISS 2.2.4 → 3.0.0 — required edits",
        "PABC 1.1.0 → 1.1.1 no values changes",
    ]
    lines = text.splitlines(keepends=True)
    assert "".join(lines[sections[0]["start"] : sections[0]["end"]]).count("### 1. A sub-heading") == 1
    assert lines[sections[1]["start"]].strip() == "## PABC 1.1.0 → 1.1.1 no values changes"


def test_parse_values_delta_sections_no_headings_is_empty(libupgradedocsorting):
    assert libupgradedocsorting.parse_values_delta_sections("# Values deltas\n\nTODO.\n") == []


# --- sort_values_delta_sections ---


def test_sort_values_delta_sections_reorders_out_of_order_sections(libupgradedocsorting):
    text = (
        "## openinwoner 2.4.2 → 2.4.3\n\n"
        "- Key `openinwoner.a` was added.\n\n"
        "## openzaak 1.27.4 → 1.29.3\n\n"
        "- Key `openzaak.b` was added.\n"
    )
    new_text, moved = libupgradedocsorting.sort_values_delta_sections(text, DEPS, {"openzaak": {}, "openinwoner": {}})
    assert moved == [("openzaak 1.27.4 → 1.29.3", 2, 1), ("openinwoner 2.4.2 → 2.4.3", 1, 2)]
    assert new_text == (
        "## openzaak 1.27.4 → 1.29.3\n\n"
        "- Key `openzaak.b` was added.\n\n"
        "## openinwoner 2.4.2 → 2.4.3\n\n"
        "- Key `openinwoner.a` was added.\n"
    )


def test_sort_values_delta_sections_already_in_order_is_unchanged(libupgradedocsorting):
    text = (
        "## openzaak 1.27.4 → 1.29.3\n\n- Key `openzaak.b` was added.\n\n"
        "## openinwoner 2.4.2 → 2.4.3\n\n- Key `openinwoner.a` was added.\n"
    )
    new_text, moved = libupgradedocsorting.sort_values_delta_sections(text, DEPS, {"openzaak": {}, "openinwoner": {}})
    assert moved == []
    assert new_text == text


def test_sort_values_delta_sections_fewer_than_two_is_unchanged(libupgradedocsorting):
    text = "## openzaak 1.27.4 → 1.29.3\n\n- Key `openzaak.b` was added.\n"
    new_text, moved = libupgradedocsorting.sort_values_delta_sections(text, DEPS, {"openzaak": {}})
    assert moved == []
    assert new_text == text


def test_sort_values_delta_sections_never_touches_intro_prose_above(libupgradedocsorting):
    """Content before the very first "## " heading (the doc's own H1
    title, and any intro prose) is never part of any section — see
    parse_values_delta_sections — so it's never moved even when every
    real section below it is."""
    text = (
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
        "Some intro prose.\n\n"
        "## openinwoner 2.4.2 → 2.4.3\n\n- Key `openinwoner.a` was added.\n\n"
        "## openzaak 1.27.4 → 1.29.3\n\n- Key `openzaak.b` was added.\n"
    )
    new_text, moved = libupgradedocsorting.sort_values_delta_sections(text, DEPS, {"openzaak": {}, "openinwoner": {}})
    assert moved
    assert new_text.startswith("# Values deltas — PodiumD 4.8.5 → 4.9.0\n\nSome intro prose.\n\n")


def test_sort_values_delta_sections_reorders_hand_written_sections_too(libupgradedocsorting):
    """A hand-written section (no different from an auto-generated one
    as far as this function is concerned) is reordered exactly like any
    other — its own CONTENT is never touched, only its physical
    position, the same guarantee sort_changes_blocks already gives
    -upgrade.md's own hand-written "### ..." blocks."""
    text = (
        "## openinwoner 2.4.2 → 2.4.3\n\n- Key `openinwoner.a` was added.\n\n"
        "## ZAC 5.0.2 → 5.4.4 — required edits\n\nSome hand-written prose.\n\n"
    )
    values = {"zac": {}, "openinwoner": {}}
    new_text, moved = libupgradedocsorting.sort_values_delta_sections(text, DEPS, values)
    assert moved == [("ZAC 5.0.2 → 5.4.4 — required edits", 2, 1), ("openinwoner 2.4.2 → 2.4.3", 1, 2)]
    assert new_text == (
        "## ZAC 5.0.2 → 5.4.4 — required edits\n\nSome hand-written prose.\n\n"
        "## openinwoner 2.4.2 → 2.4.3\n\n- Key `openinwoner.a` was added.\n"
    )


def test_sort_values_delta_sections_multiple_global_images_use_their_own_real_suborder(libupgradedocsorting):
    """The values-deltas.md shape of the same real redis/nginx/curl/
    busybox regression test above — confirms the identical fix applies
    to this THIRD consumer too, not just -upgrade.md's own table/
    Changes shapes."""
    text = (
        "## redis 8.0 → 8.10.1\n\n- `global.images.redis.tag` bumped.\n\n"
        "## curl 8.21.0 → 8.22.0\n\n- `global.images.curl.tag` bumped.\n\n"
        "## nginx-unprivileged 1.31.4 → 1.31.5\n\n- `global.images.nginx.tag` bumped.\n\n"
        "## busybox 1.37.0 → 1.38.0-glibc\n\n- `global.images.busybox.tag` bumped.\n"
    )

    new_text, moved = libupgradedocsorting.sort_values_delta_sections(
        text, [], GLOBAL_IMAGES_VALUES, GLOBAL_IMAGES_CANONICAL_NAMES
    )

    headings = [line for line in new_text.splitlines() if line.startswith("## ")]
    assert headings == [
        "## nginx-unprivileged 1.31.4 → 1.31.5",
        "## curl 8.21.0 → 8.22.0",
        "## busybox 1.37.0 → 1.38.0-glibc",
        "## redis 8.0 → 8.10.1",
    ]
