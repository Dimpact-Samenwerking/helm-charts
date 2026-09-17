"""lib.upgradedoc -- find_images_manifest_list_diff (missing/stale/
unmatched images-manifest entries, including digest-only repins)."""


# --- find_images_manifest_list_diff ---


def test_find_images_manifest_list_diff_exact_list_reports_nothing(libupgradedoc):
    """The manifest lists exactly the one image that actually changed —
    all three halves come back empty."""
    entries = [{"name": "zac"}]
    current_paths = {("zac",): "1.2.0@sha256:new"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_finds_missing_changed_image(libupgradedoc):
    """A path whose tag actually changed but has no manifest entry at all
    resolving to it is reported as missing."""
    entries = []
    current_paths = {("zac",): "1.2.0@sha256:new"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
    )
    assert missing == [("zac",)]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_finds_entry_for_unchanged_image(libupgradedoc):
    """An entry that resolves to a real path, but that path's tag is
    identical between baseline and current — listed without a real
    reason to be there. This is the "stale" bucket, distinct from an
    entry that doesn't resolve to a path at all (see ..._matching_
    nothing below) — the two need different fixes and different
    messages."""
    entries = [{"name": "zac"}]
    current_paths = {("zac",): "1.1.0@sha256:old"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
    )
    assert missing == []
    assert stale == ["zac"]
    assert unmatched == []


def test_find_images_manifest_list_diff_finds_entry_matching_nothing(libupgradedoc):
    """An entry whose name doesn't resolve to any values-tree path at
    all (typo, stale, or a component that's since been removed) lands
    in the SEPARATE "unmatched" bucket, not "stale" — it was never a
    real image to begin with, so "did not change" would be a misleading
    message for it (this is what the real "icatt-menselijk-digitaal/
    podiumd-adapter" case turned out to be — resolve_entry_image_path
    returns None for it, not a real-but-unchanged path)."""
    entries = [{"name": "does-not-exist"}]
    current_paths = {("zac",): "1.1.0@sha256:old"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
    )
    assert missing == []
    assert stale == []
    assert unmatched == ["does-not-exist"]


def test_find_images_manifest_list_diff_ignores_digest_only_repin_without_values(libupgradedoc):
    """Without values/baseline_values (the full trees resolved_digest_pin
    needs), the digest side of the comparison can never fire at all —
    collapsing back to the old, version-only behaviour. Every real
    caller (lib.docs_consistency.check_images_manifest_format) passes
    both; this is the "opt-out" shape for a caller that doesn't."""
    entries = []
    current_paths = {("zac",): "1.1.0@sha256:newdigest"}
    baseline_paths = {("zac",): "1.1.0@sha256:olddigest"}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_catches_digest_only_repin_when_both_sides_resolvable(libupgradedoc):
    """A tag whose VERSION is unchanged but whose embedded digest DOES
    differ IS now reported as missing, given values/baseline_values —
    real case confirmed live against the real chart (clamav 1.5.4:
    same version, digest re-pinned) — the images-manifest is about
    precise mirroring/tracking, where a digest-only re-pin is something
    worth recording, unlike -upgrade.md/-values-deltas.md (see lib.
    upgradedoc.compute_changed_components, deliberately unaffected by
    this — version-only there stays correct)."""
    entries = []
    current_paths = {("zac",): "1.1.0@sha256:" + "b" * 64}
    baseline_paths = {("zac",): "1.1.0@sha256:" + "a" * 64}
    values = {"zac": {"image": {"repository": "zac", "tag": "1.1.0@sha256:" + "b" * 64}}}
    baseline_values = {"zac": {"image": {"repository": "zac", "tag": "1.1.0@sha256:" + "a" * 64}}}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries,
        current_paths,
        baseline_paths,
        repo_map={},
        repo_groups={},
        unresolvable_paths=set(),
        values=values,
        baseline_values=baseline_values,
    )
    assert missing == [("zac",)]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_ignores_digest_only_repin_when_only_one_side_resolvable(libupgradedoc):
    """A bare (non-digest-embedding) tag on one side, with no stored
    digest to compare against on that side, is left alone even with
    values/baseline_values given — there is nothing to diff (the
    "sweep" a version-only image is resolved live against the registry
    each time, never something this local, git-history-only comparison
    can see), never treated as "changed" purely because one side
    happens to lack a recorded digest."""
    entries = []
    current_paths = {("zac",): "1.1.0"}
    baseline_paths = {("zac",): "1.1.0@sha256:" + "a" * 64}
    values = {"zac": {"image": {"repository": "zac", "tag": "1.1.0"}}}
    baseline_values = {"zac": {"image": {"repository": "zac", "tag": "1.1.0@sha256:" + "a" * 64}}}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries,
        current_paths,
        baseline_paths,
        repo_map={},
        repo_groups={},
        unresolvable_paths=set(),
        values=values,
        baseline_values=baseline_values,
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_catches_split_tag_sha_digest_repin(libupgradedoc, tmp_path):
    """keycloak-operator's own split tag:/sha: convention (see lib.
    settings.digest_pinning_exceptions/resolved_digest_pin) never embeds
    "@sha256" in the tag itself — the digest lives in a sibling "sha:"
    field instead. A same-version repin there (sha: changed, tag:
    unchanged) must be caught the exact same way an embedded-digest
    repin is, since resolved_digest_pin abstracts over both shapes
    identically. chart_dir is required here (no etc/settings.yaml under
    tmp_path, so digest_pinning_exceptions falls back to its own
    hard-coded default table, which includes ("keycloak", "image")) —
    without it, sibling_fields resolves to {} and this digest comparison
    can never fire at all (see find_images_manifest_list_diff's own
    None-safe chart_dir handling)."""
    entries = []
    path = ("keycloak", "image")
    current_paths = {path: "26.0.0"}
    baseline_paths = {path: "26.0.0"}
    values = {"keycloak": {"image": {"repository": "keycloak/keycloak", "tag": "26.0.0", "sha": "b" * 64}}}
    baseline_values = {"keycloak": {"image": {"repository": "keycloak/keycloak", "tag": "26.0.0", "sha": "a" * 64}}}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries,
        current_paths,
        baseline_paths,
        repo_map={},
        repo_groups={},
        unresolvable_paths=set(),
        chart_dir=tmp_path,
        values=values,
        baseline_values=baseline_values,
    )
    assert missing == [path]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_still_catches_a_real_version_change(libupgradedoc):
    """A real version bump — even one that ALSO changes the digest, the
    normal shape for any real tag bump — is still reported as missing,
    same as always. Only a version-IDENTICAL digest re-pin is ignored."""
    entries = []
    current_paths = {("zac",): "1.2.0@sha256:newdigest"}
    baseline_paths = {("zac",): "1.1.0@sha256:olddigest"}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
    )
    assert missing == [("zac",)]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_treats_brand_new_path_as_changed(libupgradedoc):
    """A path with no baseline entry at all (a genuinely new image, not
    in baseline_paths) is still reported as missing — there is no
    "version" to compare it against, so it can never be mistaken for a
    digest-only repin."""
    entries = []
    current_paths = {("newcomponent", "image"): "1.0.0@sha256:aaaa"}
    baseline_paths = {}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
    )
    assert missing == [("newcomponent", "image")]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_eck_operator_new_pin_still_reported_as_missing(libupgradedoc):
    """Non-regression test: eck-operator's own image path (target has an
    explicit split "tag:"/"digest:" override; baseline has NO "image:"
    key at all under eck-operator, same shape as the real 4.9.1
    baseline) is correctly reported as "missing" from images-<target>
    .yaml via plain path/version comparison -- independent of whether
    resolved_digest_pin can ALSO resolve its own sibling "digest:" field
    (a separate question, about whether a valid ENTRY can be auto-
    written — see lib.settings.digest_pinning_exceptions and add_missing_images_
    manifest_entries' own eck-operator test). This finding must keep
    firing even once that separate gap is fixed: a real new pin was
    added either way, and this function's own "missing" detection
    doesn't (and shouldn't) depend on the entry being writable."""
    path = ("eck-operator", "image")
    current_paths = {path: "3.5.0"}
    baseline_paths = {}
    values = {
        "eck-operator": {
            "image": {
                "repository": "docker.elastic.co/eck/eck-operator",
                "tag": "3.5.0",
                "digest": "sha256:" + "b" * 64,
            }
        }
    }
    baseline_values = {"eck-operator": {"enabled": True}}

    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        [],
        current_paths,
        baseline_paths,
        repo_map={},
        repo_groups={},
        unresolvable_paths=set(),
        values=values,
        baseline_values=baseline_values,
    )

    assert missing == [path]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_brand_new_path_always_changed_regardless_of_repo_match(libupgradedoc):
    """Regression test: a path with no baseline entry at all (a
    component that didn't exist in Chart.yaml/values.yaml until this
    release, e.g. brppersonenmock, added in 4.9.0) is ALWAYS reported as
    missing, even when its exact version+digest happens to already be
    pinned somewhere else via the same repository (repo_map/repo_groups
    resolve it) — images-baseline.yaml is never consulted as a
    substitute source of truth for "was this genuinely tracked at the
    real git baseline" (a different, unrelated question: ACR-mirror
    digest provenance)."""
    entries = []
    current_paths = {("brppersonenmock", "image"): "2.7.0@sha256:aaaa"}
    baseline_paths = {}
    repo_map = {"brp-api/personen-mock": ("brppersonenmock", "image")}
    repo_groups = {"brp-api/personen-mock": [("brppersonenmock", "image")]}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
    )
    assert missing == [("brppersonenmock", "image")]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_uses_repo_map_for_resolution(libupgradedoc):
    """Entry resolution goes through resolve_entry_image_path — a
    strip-registry-shaped name only matches via repo_map, same as that
    function's own exact-hit behavior."""
    entries = [{"name": "infonl/zaakafhandelcomponent"}]
    current_paths = {("zac",): "1.2.0@sha256:new"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    repo_groups = {"infonl/zaakafhandelcomponent": [("zac",)]}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_collapses_shared_repository_group(libupgradedoc):
    """Several paths sharing the same repository (e.g. every
    "<component>.nginx.image" sidecar aliasing the same shared
    global.images.nginx YAML anchor) are ONE image needing at most ONE
    entry between all of them — an entry covering the group's
    representative path (repo_map's own single survivor) satisfies
    every path in the group, not just that one."""
    entries = [{"name": "nginxinc/nginx-unprivileged"}]
    current_paths = {
        ("openzaak", "nginx", "image"): "1.31.4@sha256:new",
        ("openformulieren", "nginx", "image"): "1.31.4@sha256:new",
        ("openinwoner", "nginx", "image"): "1.31.4@sha256:new",
    }
    baseline_paths = {
        ("openzaak", "nginx", "image"): "1.31.3@sha256:old",
        ("openformulieren", "nginx", "image"): "1.31.3@sha256:old",
        ("openinwoner", "nginx", "image"): "1.31.3@sha256:old",
    }
    repo_groups = {"nginxinc/nginx-unprivileged": list(current_paths.keys())}
    repo_map = {"nginxinc/nginx-unprivileged": ("openinwoner", "nginx", "image")}

    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_reports_shared_group_missing_once(libupgradedoc):
    """The same shared-repository group, but with NO entry covering it
    at all — reported as missing exactly ONCE (the group's single
    representative path), never once per aliased usage site."""
    entries = []
    current_paths = {
        ("openzaak", "nginx", "image"): "1.31.4@sha256:new",
        ("openformulieren", "nginx", "image"): "1.31.4@sha256:new",
    }
    baseline_paths = {
        ("openzaak", "nginx", "image"): "1.31.3@sha256:old",
        ("openformulieren", "nginx", "image"): "1.31.3@sha256:old",
    }
    repo_groups = {"nginxinc/nginx-unprivileged": list(current_paths.keys())}
    repo_map = {"nginxinc/nginx-unprivileged": ("openformulieren", "nginx", "image")}

    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
    )
    assert missing == [("openformulieren", "nginx", "image")]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_ignores_non_representative_new_usage(libupgradedoc):
    """Real bug: kiss's own indexTemplateImage started aliasing curlimages/
    curl for the first time in 4.9.0 (no baseline value for THAT path at
    all — brand new usage, not a version bump), while global.images.curl
    itself (the group's own representative) has the exact same tag before
    and after. The group must NOT be flagged "changed" on the strength of
    kiss's own brand-new usage alone — the manifest lists images whose
    version or digest actually changed, never "is newly used somewhere"
    by itself."""
    entries = []
    current_paths = {
        ("kiss", "settings", "syncJobs", "indexTemplateImage"): "8.21.0@sha256:same",
        ("global", "images", "curl"): "8.21.0@sha256:same",
    }
    baseline_paths = {
        # kiss's own path has NO baseline entry at all — genuinely new usage
        ("global", "images", "curl"): "8.21.0@sha256:same",
    }
    repo_groups = {"curlimages/curl": list(current_paths.keys())}
    repo_map = {"curlimages/curl": ("global", "images", "curl")}

    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_representative_change_still_caught_despite_other_member(libupgradedoc):
    """The flip side of the above: the representative itself DID change,
    even though some OTHER group member (not the representative) happens
    to be unchanged — still correctly reported as missing."""
    entries = []
    current_paths = {
        ("frankgateway", "dashboard", "auth", "shim", "image"): "1.31.4@sha256:new",  # other member, unchanged
        ("global", "images", "nginx"): "1.31.4@sha256:new",
    }
    baseline_paths = {
        ("frankgateway", "dashboard", "auth", "shim", "image"): "1.31.4@sha256:new",
        ("global", "images", "nginx"): "1.31.3@sha256:old",
    }
    repo_groups = {"nginxinc/nginx-unprivileged": list(current_paths.keys())}
    repo_map = {"nginxinc/nginx-unprivileged": ("global", "images", "nginx")}

    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
    )
    assert missing == [("global", "images", "nginx")]


def test_find_images_manifest_list_diff_excludes_unresolvable_path_from_missing(libupgradedoc):
    """A path with no resolvable repository at all (real case:
    kiss.adapter.image — see lib.image_repository_check.
    find_images_without_repository's own docstring) isn't a real,
    referenceable image the manifest could ever meaningfully document —
    never reported as missing just because its tag happens to differ
    from baseline."""
    entries = []
    current_paths = {("kiss", "adapter", "image"): "0.6.7@sha256:new"}
    baseline_paths = {("kiss", "adapter", "image"): "0.6.6@sha256:old"}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries,
        current_paths,
        baseline_paths,
        repo_map={},
        repo_groups={},
        unresolvable_paths={("kiss", "adapter", "image")},
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_flags_entry_for_unresolvable_path_as_stale(libupgradedoc):
    """An entry that DOES resolve to a real path, but that path has no
    resolvable repository, is flagged too — such a path isn't a real
    image the manifest has any reason to list at all. It lands in
    "stale" rather than "unmatched" because resolve_entry_image_path
    DID find a real path for it; only the repository resolution failed,
    a distinct concern find_images_without_repository already reports
    on its own."""
    entries = [{"name": "adapter"}]
    current_paths = {("kiss", "adapter", "image"): "0.6.7@sha256:new"}
    baseline_paths = {("kiss", "adapter", "image"): "0.6.6@sha256:old"}
    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries,
        current_paths,
        baseline_paths,
        repo_map={},
        repo_groups={},
        unresolvable_paths={("kiss", "adapter", "image")},
    )
    assert missing == []
    assert stale == ["adapter"]
    assert unmatched == []


def test_find_images_manifest_list_diff_deps_given_rejects_stripped_name_collision(libupgradedoc, tmp_path):
    """Regression test: the same real redis/redis-operator collision
    lib.chart.historical_app_version_for_path already guards against
    (see its own docstring) applies equally to this function's OWN
    historical-manifest fallback (pin_changed, for a brand-new path with
    no baseline entry at all). global.images.redis (repository bare
    "redis") strips to the same name as images-4.6.4.yaml's own legacy
    "name: redis" entry (redis-operator's unrelated quay.io/opstree/
    redis) — whose recorded version ("8.0") is deliberately made to
    match the current tag here, so a wrongly-accepted collision would
    mask this path as "unchanged" and it would never end up in
    missing_paths, even though there is no manifest entry for it at all.
    Passing deps (as both real callers now do) cross-checks the
    historical entry's own "url:" against the CURRENT path's fully-
    qualified repository (lib.chart.full_repository_for_path) and
    correctly rejects it, so the path is still reported missing."""
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "images-4.6.4.yaml").write_text(
        '- name: redis\n  url: quay.io/opstree/redis\n  version: "8.0"\n  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    entries = []
    current_paths = {("global", "images", "redis"): "8.0@sha256:bbbb"}
    baseline_paths = {}
    repo_map = {"redis": ("global", "images", "redis")}
    repo_groups = {"redis": [("global", "images", "redis")]}
    values = {"global": {"images": {"redis": {"repository": "redis", "tag": "8.0@sha256:bbbb"}}}}

    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries,
        current_paths,
        baseline_paths,
        repo_map,
        repo_groups,
        unresolvable_paths=set(),
        chart_dir=tmp_path,
        deps=[],
        upgrade_docs_baseline="4.9.0",
        values=values,
        baseline_values={},
    )
    assert missing == [("global", "images", "redis")]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_without_deps_keeps_old_name_only_behavior(libupgradedoc, tmp_path):
    """The exact same fixture as the collision test above, but WITHOUT
    passing deps — this is deliberately preserved old (unsafe) name-only
    behavior for a caller with no Chart.yaml dependencies of its own to
    give (see this function's own docstring); both of this function's
    real callers now always pass deps, so this path is only ever taken
    by a caller that hasn't been updated. Demonstrates the bug this
    function's docstring describes really did exist before deps was
    threaded through: the collision is wrongly accepted and the path is
    never reported missing at all."""
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "images-4.6.4.yaml").write_text(
        '- name: redis\n  url: quay.io/opstree/redis\n  version: "8.0"\n  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    entries = []
    current_paths = {("global", "images", "redis"): "8.0@sha256:bbbb"}
    baseline_paths = {}
    repo_map = {"redis": ("global", "images", "redis")}
    repo_groups = {"redis": [("global", "images", "redis")]}
    values = {"global": {"images": {"redis": {"repository": "redis", "tag": "8.0@sha256:bbbb"}}}}

    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries,
        current_paths,
        baseline_paths,
        repo_map,
        repo_groups,
        unresolvable_paths=set(),
        chart_dir=tmp_path,
        upgrade_docs_baseline="4.9.0",
        values=values,
        baseline_values={},
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_deps_given_preserves_real_historical_match(libupgradedoc, tmp_path):
    """The EXISTING working case (mi/brppersonenmock — same name AND
    same url, a genuine historical match) must still work unchanged once
    deps/expected_url cross-checking is active: a brand-new path whose
    repository genuinely was already recorded, at the same version, in
    an earlier release's own images-<version>.yaml is correctly treated
    as unchanged and never reported missing."""
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "images-4.8.0.yaml").write_text(
        "- name: brp-api/personen-mock\n"
        "  url: ghcr.io/brp-api/personen-mock\n"
        '  version: "2.7.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    entries = []
    current_paths = {("brppersonenmock", "image"): "2.7.0@sha256:aaaa"}
    baseline_paths = {}
    repo_map = {"brp-api/personen-mock": ("brppersonenmock", "image")}
    repo_groups = {"brp-api/personen-mock": [("brppersonenmock", "image")]}
    values = {"brppersonenmock": {"image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0@sha256:aaaa"}}}

    missing, stale, unmatched = libupgradedoc.find_images_manifest_list_diff(
        entries,
        current_paths,
        baseline_paths,
        repo_map,
        repo_groups,
        unresolvable_paths=set(),
        chart_dir=tmp_path,
        deps=[],
        upgrade_docs_baseline="4.8.5",
        values=values,
        baseline_values={},
    )
    assert missing == []
    assert stale == []
    assert unmatched == []
