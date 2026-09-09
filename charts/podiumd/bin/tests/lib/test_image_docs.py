"""lib.image_docs — the "shared image basename as its own pseudo-component"
doc-update helpers used by update-image-version when a basename bump
touches more than one Chart.yaml component. Convention confirmed against
docs/_UPGRADE_PATHS/4.8.1-to-4.8.2-upgrade.md (curl/nginx-unprivileged/
busybox each got their own table row + "### <name> ..." Changes block)."""


# --- add_missing_sidecar_rows ---

def test_add_missing_sidecar_rows_global_image_gets_one_row_not_per_alias(libimagedocs, tmp_path):
    """Real bug: nginx-unprivileged is aliased by zac's own nginx sidecar
    AND frankgateway's own nginx sidecar (the same global.images.nginx
    anchor) — before global_image_paths was folded into current_paths
    here, canonical_sidecar_row_names never saw a "global"-rooted path
    at all, so each real dependency's own sidecar independently
    qualified for its own "<dep> - nginx-unprivileged" row, giving the
    SAME version bump two separate rows. Must be exactly one, bare
    "nginx-unprivileged" row instead."""
    deps = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
        {"name": "frankgateway", "alias": "", "version": "1.1.0"},
    ]
    target_values = {
        "global": {"images": {"nginx": {
            "repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
        "zac": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
        "frankgateway": {"dashboard": {"auth": {"shim": {"image": {
            "repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}}}},
    }
    baseline_values = {
        "global": {"images": {"nginx": {
            "repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}},
        "zac": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}},
        "frankgateway": {"dashboard": {"auth": {"shim": {"image": {
            "repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}}}},
    }
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
    )

    new_text, added = libimagedocs.add_missing_sidecar_rows(
        text, tmp_path, deps, target_values, baseline_values, "4.9.0")

    assert added == ["nginx-unprivileged"]
    assert "| nginx-unprivileged | 1.31.3 → 1.31.4 | - | - |" in new_text
    assert "### nginx-unprivileged 1.31.3 → 1.31.4" in new_text
    assert "zac - nginx-unprivileged" not in new_text
    assert "frankgateway - nginx-unprivileged" not in new_text


def test_add_missing_sidecar_rows_digest_only_repin_is_not_a_row(libimagedocs, tmp_path):
    """Regression test: a shared image whose VERSION is unchanged but
    whose DIGEST was re-pinned (real case: nginx-unprivileged) must NOT
    get a row/section of its own — -upgrade.md documents version
    changes, never a digest re-pin alone (that's the images-manifest's
    own concern; see find_images_manifest_list_diff's docstring). Before
    this fix, ANY digest difference (even with the exact same version)
    added a nonsensical "1.31.4 → 1.31.4" row/section."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    target_values = {
        "global": {"images": {"nginx": {
            "repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
        "zac": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
    }
    baseline_values = {
        "global": {"images": {"nginx": {
            "repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:bbbb"}}},
        "zac": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:bbbb"}}},
    }
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
    )

    new_text, added = libimagedocs.add_missing_sidecar_rows(
        text, tmp_path, deps, target_values, baseline_values, "4.9.0")

    assert added == []
    assert "nginx-unprivileged" not in new_text


def test_add_missing_sidecar_rows_global_row_inserted_at_its_own_position_not_last(libimagedocs, tmp_path):
    """Real bug reported live: re-running the fix script placed the new
    "nginx-unprivileged" row at the very END of the table (component_
    order_key's own "unmatched sorts last" fallback), when it should sort
    to the TOP — "global:" is values.yaml's own FIRST key, and the
    images-manifest's own equivalent entry already sorts there."""
    deps = [{"name": "openzaak", "alias": "", "version": "1.14.2"}]
    target_values = {
        "global": {"images": {"nginx": {
            "repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
        "openzaak": {"nginx": {"image": {
            "repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
    }
    baseline_values = {
        "global": {"images": {"nginx": {
            "repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}},
        "openzaak": {"nginx": {"image": {
            "repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}},
    }
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openzaak | 1.27.4 → 1.29.3 | 1.14.2 (unchanged) | - |\n"
    )

    new_text, added = libimagedocs.add_missing_sidecar_rows(
        text, tmp_path, deps, target_values, baseline_values, "4.9.0")

    assert added == ["nginx-unprivileged"]
    rows = [line for line in new_text.splitlines() if line.startswith("|") and "---" not in line]
    assert rows[1].startswith("| nginx-unprivileged")
    assert rows[2].startswith("| openzaak")


# --- make_image_changes_section ---

def test_make_image_changes_section_lists_every_pinned_path(libimagedocs):
    pinned = [("keycloak-operator.jobs.ensureOperatorSa.image.tag", "8.20.0"),
              ("zac.global.curlImage.tag", "8.20.0")]
    section = libimagedocs.make_image_changes_section("curl", "4.9.0", "8.20.0", "8.21.0", pinned)
    assert section.startswith("### curl 8.20.0 → 8.21.0")
    assert "- `keycloak-operator.jobs.ensureOperatorSa.image.tag` `8.20.0` → `8.21.0`" in section
    assert "- `zac.global.curlImage.tag` `8.20.0` → `8.21.0`" in section
    assert "images-4.9.0.yaml" in section


def test_make_image_changes_section_per_path_old_version_differs(libimagedocs):
    """A basename's various pins aren't guaranteed to have all started at
    the exact same version -- each path's own old version is shown, not
    one assumed-uniform value."""
    pinned = [("a.image.tag", "8.19.0"), ("b.image.tag", "8.20.0")]
    section = libimagedocs.make_image_changes_section("curl", "4.9.0", "8.19.0", "8.21.0", pinned)
    assert "- `a.image.tag` `8.19.0` → `8.21.0`" in section
    assert "- `b.image.tag` `8.20.0` → `8.21.0`" in section


def test_make_image_changes_section_old_version_none_renders_new(libimagedocs):
    """Regression test: old_version is None when this image never had a
    prior pin at all (genuinely new — real case: a brand-new shared
    "redis" cache sidecar aliased into a dozen components at once) —
    must render "(new)", not a nonsensical "None → 8.0"."""
    pinned = [("global.images.redis.tag", None)]
    section = libimagedocs.make_image_changes_section("redis", "4.9.1", None, "8.0", pinned)
    assert section.startswith("### redis 8.0 (new)")
    assert "None" not in section
    assert "→" not in section.split("\n\n")[0]
    assert "- `global.images.redis.tag` `8.0` (new)" in section
    assert "introduces the shared **redis** image" in section


def test_make_image_changes_section_old_equals_new_renders_unchanged(libimagedocs):
    """Regression test: old_version already resolved equal to new_version
    (e.g. the images-baseline.yaml fallback matching a digest-only
    re-pin, or a genuinely new path pinned to an already-known image)
    must render "(unchanged)", not a nonsensical "8.0 → 8.0"
    self-transition."""
    pinned = [("global.images.redis.tag", "8.0")]
    section = libimagedocs.make_image_changes_section("redis", "4.9.1", "8.0", "8.0", pinned)
    assert section.startswith("### redis 8.0 (unchanged)")
    assert "8.0 → 8.0" not in section
    assert "- `global.images.redis.tag` `8.0` (unchanged)" in section
    assert "keeps the shared **redis** image" in section


# --- update_image_manifest ---

def write_manifest(path, text):
    path.write_text(text, encoding="utf-8")


def test_update_image_manifest_updates_existing_entry_and_comment(libimagedocs, tmp_path):
    path = tmp_path / "images-4.9.0.yaml"
    write_manifest(path, (
        "# Baseline: podiumd 4.8.5.\n"
        "#\n"
        "# One change:\n"
        "#   1. curl 8.20.0 -> 8.20.0.\n"
        "#\n\n"
        "# curl — 8.20.0 -> 8.20.0\n"
        "- name: curlimages/curl\n"
        "  url: docker.io/curlimages/curl\n"
        '  version: "8.20.0"\n'
        '  digest: "sha256:aaaa"\n'
    ))
    changes_action, entry_updated = libimagedocs.update_image_manifest(
        path, "curl", "curlimages/curl", "8.20.0", "8.21.0", "sha256:bbbb")
    assert changes_action == "updated"
    assert entry_updated is True
    text = path.read_text(encoding="utf-8")
    assert "#   1. curl 8.20.0 -> 8.21.0." in text
    assert "# curl — 8.20.0 -> 8.21.0" in text
    assert '"8.21.0"' in text
    assert '"sha256:bbbb"' in text


def test_update_image_manifest_adds_new_changes_item_when_absent(libimagedocs, tmp_path):
    path = tmp_path / "images-4.9.0.yaml"
    write_manifest(path, (
        "# Baseline: podiumd 4.8.5.\n"
        "#\n"
        "# One change:\n"
        "#   1. ZAC 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).\n"
        "#\n\n"
        "- name: zac\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.4.3"\n'
        '  digest: "sha256:aaaa"\n'
    ))
    changes_action, entry_updated = libimagedocs.update_image_manifest(
        path, "curl", "curlimages/curl", "8.20.0", "8.21.0", "sha256:bbbb")
    assert changes_action == "added"
    assert entry_updated is False
    text = path.read_text(encoding="utf-8")
    # The header's own wording is never rewritten into a counted form —
    # same convention lib.component_docs.update_images_manifest already
    # uses; the real manifest's own header stays whatever it already was.
    assert "# One change:" in text
    assert "#   2. curl 8.20.0 -> 8.21.0." in text


def test_update_image_manifest_new_item_uses_values_yaml_order_not_append(libimagedocs, tmp_path):
    """Regression test (real bug, real doc): update_image_manifest used to
    always APPEND a brand-new header item at the very end of the
    existing "# Changes:" list regardless of values.yaml's own top-level
    component order, while its sibling lib.component_docs.update_images_
    manifest (used for a real Chart.yaml dependency's own bump, e.g.
    "mi") already positions ITS new items by that same order — the two
    disagreeing meant a shared/global image (e.g. "redis", handled by
    THIS function) bumped in the same run as a real dependency could
    land its own header item out of order relative to the other's,
    confirmed live: images-4.9.1.yaml's own "redis 8.0 (new)." item
    (always appended last) ended up AFTER "mi ... unchanged."'s own
    values.yaml-order-positioned item even though redis's real entry
    sits earlier in values.yaml (under "global:", values.yaml's own
    FIRST top-level key) than "mi"'s. Passing deps/values now positions
    a brand-new item here the SAME way, via lib.upgradedoc.
    component_order_key — the exact convention update-image-version's
    own update_docs_shared_image already uses to position this SAME
    basename's "Component versions" table row/"### ..." Changes section
    in the upgrade doc, so the two docs can never disagree on order."""
    path = tmp_path / "images-4.9.1.yaml"
    write_manifest(path, (
        "# One change:\n"
        "#   1. mi 2.90.0 (new) (chart 1.1.0, new).\n"
        "#\n\n"
        "- name: mi-data\n"
        "  url: example/mi-data\n"
        '  version: "2.90.0"\n'
        '  digest: "sha256:aaaa"\n'
    ))
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    values = {
        "global": {"images": {"redis": {"repository": "bitnami/redis", "tag": "8.0@sha256:bbbb"}}},
        "mi": {"enabled": False, "image": {"repository": "example/mi-data", "tag": "2.90.0@sha256:aaaa"}},
    }
    canonical_names = {"redis": ("global", "images", "redis")}

    changes_action, entry_updated = libimagedocs.update_image_manifest(
        path, "redis", "bitnami/redis", "7.4", "8.0", "sha256:bbbb",
        deps=deps, values=values, canonical_names=canonical_names)

    assert changes_action == "added"
    assert entry_updated is False
    text = path.read_text(encoding="utf-8")
    # redis (values.yaml's own FIRST top-level key, "global:") must land
    # BEFORE mi's own item, not appended after it.
    assert "#   1. redis 7.4 -> 8.0.\n" in text
    assert "#   2. mi 2.90.0 (new) (chart 1.1.0, new).\n" in text
    assert text.index("1. redis") < text.index("2. mi")


def test_update_image_manifest_recognizes_bare_changes_header(libimagedocs, tmp_path):
    """Regression test (real bug, real doc: nginx-unprivileged): the real,
    hand-curated images-manifest header is the plain "# Changes:" form
    with no count word at all — CHANGES_HEADER_RE alone never matches
    that (it requires a leading count word), so this used to silently
    find no header at all and skip the "changes:" list item outright for
    EVERY MULTIPLE-scope basename bump against a real manifest, never
    even reaching the "no existing entry" case a human could act on
    (confirmed live: nginx-unprivileged's own bump against images-
    4.9.1.yaml left zero trace of "nginx" anywhere in the header list).
    find_images_manifest_changes_header (tried here instead) falls back
    to BARE_CHANGES_HEADER_RE for exactly this bare form."""
    path = tmp_path / "images-4.9.1.yaml"
    write_manifest(path, (
        "# Baseline: podiumd 4.9.0.\n"
        "#\n"
        "# Changes:\n"
        "#\n\n"
        "- name: zac\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.4.3"\n'
        '  digest: "sha256:aaaa"\n'
    ))
    changes_action, entry_updated = libimagedocs.update_image_manifest(
        path, "nginx-unprivileged", "nginxinc/nginx-unprivileged", "1.31.3", "1.31.4", "sha256:bbbb")
    assert changes_action == "added"
    assert entry_updated is False
    text = path.read_text(encoding="utf-8")
    assert "#   1. nginx-unprivileged 1.31.3 -> 1.31.4." in text


def test_remove_image_manifest_entry_recognizes_bare_changes_header(libimagedocs, tmp_path):
    """Same bare-"# Changes:"-header gap as update_image_manifest above,
    for its counterpart remove_image_manifest_entry (the reset-to-
    baseline path) — must find the real header and remove the matching
    item, not silently no-op because CHANGES_HEADER_RE alone never
    matched it."""
    path = tmp_path / "images-4.9.1.yaml"
    write_manifest(path, (
        "# Baseline: podiumd 4.9.0.\n"
        "#\n"
        "# Changes:\n"
        "#   1. nginx-unprivileged 1.31.3 -> 1.31.4.\n"
        "#\n\n"
        "# nginx-unprivileged — 1.31.3 -> 1.31.4\n"
        "- name: nginx-unprivileged\n"
        "  url: docker.io/nginxinc/nginx-unprivileged\n"
        '  version: "1.31.4"\n'
        '  digest: "sha256:bbbb"\n'
    ))
    changes_action, entry_updated = libimagedocs.remove_image_manifest_entry(
        path, "nginx-unprivileged", "nginxinc/nginx-unprivileged", "1.31.3", "sha256:aaaa")
    assert changes_action == "removed"
    assert entry_updated is True
    text = path.read_text(encoding="utf-8")
    assert "nginx-unprivileged 1.31.3 -> 1.31.4." not in text
    assert '"1.31.3"' in text  # entry reset back to the baseline version


def test_update_image_manifest_no_matching_entry_reports_not_updated(libimagedocs, tmp_path):
    path = tmp_path / "images-4.9.0.yaml"
    write_manifest(path, (
        "# One change:\n"
        "#   1. ZAC 5.0.2 -> 5.4.3.\n\n"
        "- name: zac\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.4.3"\n'
        '  digest: "sha256:aaaa"\n'
    ))
    changes_action, entry_updated = libimagedocs.update_image_manifest(
        path, "curl", "curlimages/curl", "8.20.0", "8.21.0", "sha256:bbbb")
    assert entry_updated is False


def test_update_image_manifest_matches_entry_by_url_repository(libimagedocs, tmp_path):
    """The entry is matched by its "url:" resolving to `repository`, not
    by "name:" (which may be a short ACR-mirror slug, not the repository
    itself)."""
    path = tmp_path / "images-4.9.0.yaml"
    write_manifest(path, (
        "# One change:\n"
        "#   1. curl 8.20.0 -> 8.20.0.\n\n"
        "# curl — 8.20.0 -> 8.20.0\n"
        "- name: curl\n"
        "  url: docker.io/curlimages/curl\n"
        '  version: "8.20.0"\n'
        '  digest: "sha256:aaaa"\n'
    ))
    changes_action, entry_updated = libimagedocs.update_image_manifest(
        path, "curl", "curlimages/curl", "8.20.0", "8.21.0", "sha256:bbbb")
    assert entry_updated is True
    assert '"8.21.0"' in path.read_text(encoding="utf-8")
