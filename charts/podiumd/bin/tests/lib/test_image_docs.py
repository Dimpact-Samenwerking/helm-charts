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


# --- image_delta_bullet ---

def test_image_delta_bullet_pin_count_singular(libimagedocs):
    bullet = libimagedocs.image_delta_bullet("curl", "8.20.0", "8.21.0", 1)
    assert bullet == "- **curl** image `8.20.0 → 8.21.0` — pinned at 1 place in `values.yaml`.\n"


def test_image_delta_bullet_pin_count_plural(libimagedocs):
    bullet = libimagedocs.image_delta_bullet("curl", "8.20.0", "8.21.0", 3)
    assert bullet == "- **curl** image `8.20.0 → 8.21.0` — pinned at 3 places in `values.yaml`.\n"


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
    assert "Two changes:" in text
    assert "#   2. curl 8.20.0 -> 8.21.0." in text


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
