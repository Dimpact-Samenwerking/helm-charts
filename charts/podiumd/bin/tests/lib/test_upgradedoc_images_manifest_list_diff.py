"""lib.upgradedoc -- find_images_manifest_list_diff (missing/stale/unmatched entries, digest-only repins)."""

from pathlib import Path
from types import ModuleType

# --- find_images_manifest_list_diff ---


def test_find_images_manifest_list_diff_exact_list_reports_nothing(libupgradedocmanifestdiff: ModuleType):
    """A manifest listing exactly the changed image reports nothing."""
    entries = [{"name": "zac"}]
    current_paths = {("zac",): "1.2.0@sha256:new"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
        )
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_finds_missing_changed_image(libupgradedocmanifestdiff: ModuleType):
    """A changed path with no resolving entry is reported missing."""
    entries = []
    current_paths = {("zac",): "1.2.0@sha256:new"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
        )
    )
    assert missing == [("zac",)]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_finds_entry_for_unchanged_image(libupgradedocmanifestdiff: ModuleType):
    """An entry resolving to an unchanged path is "stale", distinct from "unmatched": they need
    different fixes and messages."""
    entries = [{"name": "zac"}]
    current_paths = {("zac",): "1.1.0@sha256:old"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
        )
    )
    assert missing == []
    assert stale == ["zac"]
    assert unmatched == []


def test_find_images_manifest_list_diff_finds_entry_matching_nothing(libupgradedocmanifestdiff: ModuleType):
    """An entry resolving to no path (typo, removed component) is "unmatched", not "stale":
    "did not change" would mislead for something that was never an image."""
    entries = [{"name": "does-not-exist"}]
    current_paths = {("zac",): "1.1.0@sha256:old"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
        )
    )
    assert missing == []
    assert stale == []
    assert unmatched == ["does-not-exist"]


def test_find_images_manifest_list_diff_ignores_digest_only_repin_without_values(libupgradedocmanifestdiff: ModuleType):
    """Without values/baseline_values the digest comparison cannot fire: version-only behaviour."""
    entries = []
    current_paths = {("zac",): "1.1.0@sha256:newdigest"}
    baseline_paths = {("zac",): "1.1.0@sha256:olddigest"}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
        )
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_catches_digest_only_repin_when_both_sides_resolvable(
    libupgradedocmanifestdiff: ModuleType,
):
    """Same version, different digest is reported missing: the manifest tracks exact mirroring
    (unlike compute_changed_components, which stays version-only)."""
    entries = []
    current_paths = {("zac",): "1.1.0@sha256:" + "b" * 64}
    baseline_paths = {("zac",): "1.1.0@sha256:" + "a" * 64}
    values = {"zac": {"image": {"repository": "zac", "tag": "1.1.0@sha256:" + "b" * 64}}}
    baseline_values = {"zac": {"image": {"repository": "zac", "tag": "1.1.0@sha256:" + "a" * 64}}}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries,
            current_paths,
            baseline_paths,
            repo_map={},
            repo_groups={},
            unresolvable_paths=set(),
            context=libupgradedocmanifestdiff.ManifestDiffContext(
                values=values,
                baseline_values=baseline_values,
            ),
        )
    )
    assert missing == [("zac",)]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_ignores_digest_only_repin_when_only_one_side_resolvable(
    libupgradedocmanifestdiff: ModuleType,
):
    """A digest missing on one side is nothing to diff, so it is not treated as changed."""
    entries = []
    current_paths = {("zac",): "1.1.0"}
    baseline_paths = {("zac",): "1.1.0@sha256:" + "a" * 64}
    values = {"zac": {"image": {"repository": "zac", "tag": "1.1.0"}}}
    baseline_values = {"zac": {"image": {"repository": "zac", "tag": "1.1.0@sha256:" + "a" * 64}}}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries,
            current_paths,
            baseline_paths,
            repo_map={},
            repo_groups={},
            unresolvable_paths=set(),
            context=libupgradedocmanifestdiff.ManifestDiffContext(
                values=values,
                baseline_values=baseline_values,
            ),
        )
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_catches_split_tag_sha_digest_repin(
    libupgradedocmanifestdiff: ModuleType, tmp_path: Path
):
    """keycloak-operator's split tag:/sha: repin is caught like an embedded-digest repin.

    chart_dir is required: without it sibling_fields is {} and the digest comparison never fires."""
    entries = []
    path = ("keycloak", "image")
    current_paths = {path: "26.0.0"}
    baseline_paths = {path: "26.0.0"}
    values = {"keycloak": {"image": {"repository": "keycloak/keycloak", "tag": "26.0.0", "sha": "b" * 64}}}
    baseline_values = {"keycloak": {"image": {"repository": "keycloak/keycloak", "tag": "26.0.0", "sha": "a" * 64}}}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries,
            current_paths,
            baseline_paths,
            repo_map={},
            repo_groups={},
            unresolvable_paths=set(),
            context=libupgradedocmanifestdiff.ManifestDiffContext(
                chart_dir=tmp_path,
                values=values,
                baseline_values=baseline_values,
            ),
        )
    )
    assert missing == [path]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_still_catches_a_real_version_change(libupgradedocmanifestdiff: ModuleType):
    """A version bump (usually with a new digest) is still reported missing."""
    entries = []
    current_paths = {("zac",): "1.2.0@sha256:newdigest"}
    baseline_paths = {("zac",): "1.1.0@sha256:olddigest"}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
        )
    )
    assert missing == [("zac",)]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_treats_brand_new_path_as_changed(libupgradedocmanifestdiff: ModuleType):
    """A path with no baseline entry is reported missing; it cannot be a digest-only repin."""
    entries = []
    current_paths = {("newcomponent", "image"): "1.0.0@sha256:aaaa"}
    baseline_paths = {}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map={}, repo_groups={}, unresolvable_paths=set()
        )
    )
    assert missing == [("newcomponent", "image")]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_eck_operator_new_pin_still_reported_as_missing(
    libupgradedocmanifestdiff: ModuleType,
):
    """A new split tag:/digest: pin with no baseline image key (eck-operator) is reported missing
    by path/version comparison alone, independent of whether the entry is auto-writable."""
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

    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            [],
            current_paths,
            baseline_paths,
            repo_map={},
            repo_groups={},
            unresolvable_paths=set(),
            context=libupgradedocmanifestdiff.ManifestDiffContext(
                values=values,
                baseline_values=baseline_values,
            ),
        )
    )

    assert missing == [path]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_brand_new_path_always_changed_regardless_of_repo_match(
    libupgradedocmanifestdiff: ModuleType,
):
    """Regression: a path new this release (brppersonenmock) is always missing, even if its
    version+digest is pinned elsewhere via the same repository; images-baseline.yaml is not consulted."""
    entries = []
    current_paths = {("brppersonenmock", "image"): "2.7.0@sha256:aaaa"}
    baseline_paths = {}
    repo_map = {"brp-api/personen-mock": ("brppersonenmock", "image")}
    repo_groups = {"brp-api/personen-mock": [("brppersonenmock", "image")]}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
        )
    )
    assert missing == [("brppersonenmock", "image")]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_uses_repo_map_for_resolution(libupgradedocmanifestdiff: ModuleType):
    """A strip-registry-shaped entry name resolves via repo_map."""
    entries = [{"name": "infonl/zaakafhandelcomponent"}]
    current_paths = {("zac",): "1.2.0@sha256:new"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    repo_groups = {"infonl/zaakafhandelcomponent": [("zac",)]}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
        )
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_collapses_shared_repository_group(libupgradedocmanifestdiff: ModuleType):
    """Paths sharing one repository (aliased global.images.nginx) are one image: an entry for the
    representative path covers the whole group."""
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

    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
        )
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_reports_shared_group_missing_once(libupgradedocmanifestdiff: ModuleType):
    """An uncovered shared-repository group is reported missing once, not per usage site."""
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

    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
        )
    )
    assert missing == [("openformulieren", "nginx", "image")]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_ignores_non_representative_new_usage(libupgradedocmanifestdiff: ModuleType):
    """Regression: a brand-new usage of an unchanged shared image (kiss indexTemplateImage aliasing
    global.images.curl) does not mark the group changed."""
    entries = []
    current_paths = {
        ("kiss", "settings", "syncJobs", "indexTemplateImage"): "8.21.0@sha256:same",
        ("global", "images", "curl"): "8.21.0@sha256:same",
    }
    baseline_paths = {
        # no baseline entry: new usage, not a version bump
        ("global", "images", "curl"): "8.21.0@sha256:same",
    }
    repo_groups = {"curlimages/curl": list(current_paths.keys())}
    repo_map = {"curlimages/curl": ("global", "images", "curl")}

    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
        )
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_representative_change_still_caught_despite_other_member(
    libupgradedocmanifestdiff: ModuleType,
):
    """A changed representative is reported even when another group member is unchanged."""
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

    missing, _stale, _unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths=set()
        )
    )
    assert missing == [("global", "images", "nginx")]


def test_find_images_manifest_list_diff_excludes_unresolvable_path_from_missing(libupgradedocmanifestdiff: ModuleType):
    """A path with no resolvable repository (kiss.adapter.image) is never reported missing."""
    entries = []
    current_paths = {("kiss", "adapter", "image"): "0.6.7@sha256:new"}
    baseline_paths = {("kiss", "adapter", "image"): "0.6.6@sha256:old"}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries,
            current_paths,
            baseline_paths,
            repo_map={},
            repo_groups={},
            unresolvable_paths={("kiss", "adapter", "image")},
        )
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_flags_entry_for_unresolvable_path_as_stale(
    libupgradedocmanifestdiff: ModuleType,
):
    """An entry resolving to a path without a resolvable repository is "stale" (not "unmatched":
    the path was found; find_images_without_repository reports the repository gap)."""
    entries = [{"name": "adapter"}]
    current_paths = {("kiss", "adapter", "image"): "0.6.7@sha256:new"}
    baseline_paths = {("kiss", "adapter", "image"): "0.6.6@sha256:old"}
    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries,
            current_paths,
            baseline_paths,
            repo_map={},
            repo_groups={},
            unresolvable_paths={("kiss", "adapter", "image")},
        )
    )
    assert missing == []
    assert stale == ["adapter"]
    assert unmatched == []


def test_find_images_manifest_list_diff_deps_given_rejects_stripped_name_collision(
    libupgradedocmanifestdiff: ModuleType, tmp_path: Path
):
    """Regression: the redis/redis-operator stripped-name collision in the historical-manifest fallback.

    global.images.redis and images-4.6.4.yaml's legacy "name: redis" (quay.io/opstree/redis) strip to
    the same name with a matching version; passing deps cross-checks the entry url against the full
    repository, so the path is still reported missing."""
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

    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries,
            current_paths,
            baseline_paths,
            repo_map,
            repo_groups,
            unresolvable_paths=set(),
            context=libupgradedocmanifestdiff.ManifestDiffContext(
                chart_dir=tmp_path,
                deps=[],
                upgrade_docs_baseline="4.9.0",
                values=values,
                baseline_values={},
            ),
        )
    )
    assert missing == [("global", "images", "redis")]
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_without_deps_keeps_old_name_only_behavior(
    libupgradedocmanifestdiff: ModuleType, tmp_path: Path
):
    """Without deps the unsafe name-only fallback remains: the collision above is accepted and the
    path is not reported missing."""
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

    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries,
            current_paths,
            baseline_paths,
            repo_map,
            repo_groups,
            unresolvable_paths=set(),
            context=libupgradedocmanifestdiff.ManifestDiffContext(
                chart_dir=tmp_path,
                upgrade_docs_baseline="4.9.0",
                values=values,
                baseline_values={},
            ),
        )
    )
    assert missing == []
    assert stale == []
    assert unmatched == []


def test_find_images_manifest_list_diff_deps_given_preserves_real_historical_match(
    libupgradedocmanifestdiff: ModuleType, tmp_path: Path
):
    """With deps, a genuine historical match (same name and url, mi/brppersonenmock) is still unchanged."""
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

    missing, stale, unmatched = libupgradedocmanifestdiff.find_images_manifest_list_diff(
        libupgradedocmanifestdiff.ManifestDiffInputs(
            entries,
            current_paths,
            baseline_paths,
            repo_map,
            repo_groups,
            unresolvable_paths=set(),
            context=libupgradedocmanifestdiff.ManifestDiffContext(
                chart_dir=tmp_path,
                deps=[],
                upgrade_docs_baseline="4.8.5",
                values=values,
                baseline_values={},
            ),
        )
    )
    assert missing == []
    assert stale == []
    assert unmatched == []
