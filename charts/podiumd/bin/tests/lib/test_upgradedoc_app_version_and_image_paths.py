"""lib.upgradedoc -- actual app-version lookup and image/version
tag path discovery across values trees."""


# --- actual_app_version ---


def test_actual_app_version_single_image(libupgradedoc):
    assert libupgradedoc.actual_app_version({"zac": {"image": {"tag": "5.4.3@sha256:abc"}}}, "zac") == "5.4.3"


def test_actual_app_version_frontend_backend_lockstep(libupgradedoc):
    values = {"zgw-office-addin": {"frontend": {"image": {"tag": "v0.9.352@sha256:abc"}}}}
    assert libupgradedoc.actual_app_version(values, "zgw-office-addin") == "v0.9.352"


def test_actual_app_version_missing_returns_none(libupgradedoc):
    assert libupgradedoc.actual_app_version({}, "missing") is None


def test_actual_app_version_uses_component_for_aliased_registry_lookup(libupgradedoc):
    # keycloak-operator's own COMPONENT_IMAGE_PATHS entry only applies when
    # the registry is queried by the dependency's real name — pass it
    # explicitly whenever the values.yaml key (alias) differs.
    values = {"kc": {"operator": {"config": {"keycloakImage": {"tag": "26.7.2@sha256:abc"}}}}}
    assert libupgradedoc.actual_app_version(values, "kc", "keycloak-operator") == "26.7.2"
    assert libupgradedoc.actual_app_version(values, "kc") is None


def test_actual_app_version_falls_back_to_bare_version_field(libupgradedoc):
    """Regression test: eck-stack's own real app version isn't an
    "image: {tag: ...}" block at all — the ECK operator's own CRD
    convention is a bare "version:" field, which COMPONENT_VERSION_PATHS
    registers as a second-pass fallback (read directly, no ".tag"
    suffix). Without it this returned None, so a real 8.19.3 -> 8.19.19
    app-version change was invisible to every check that calls this."""
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    assert libupgradedoc.actual_app_version(values, "kiss-eck", "eck-stack") == "8.19.19"


def test_actual_app_version_falls_back_to_split_image_tag_field(libupgradedoc):
    """Regression test: redis-operator's own OPERATOR image (as opposed
    to redis-ha, the database instance it manages) uses the upstream
    chart's own "imageName:"/"imageTag:" convention — two sibling string
    fields, not one nested "image:" dict — also invisible without the
    COMPONENT_VERSION_PATHS fallback."""
    values = {
        "redis-operator": {"redisOperator": {"imageName": "quay.io/opstree/redis-operator", "imageTag": "v0.26.0"}}
    }
    assert libupgradedoc.actual_app_version(values, "redis-operator") == "v0.26.0"


def test_actual_app_version_image_tag_path_tried_before_version_path(libupgradedoc, monkeypatch):
    """The "image: {tag: ...}" pass always runs first — component_version_
    paths() is only ever a fallback for when NONE of a component's
    image_paths_for candidates resolved anything."""
    import lib.upgradedoc_app_version_and_image_paths as app_version_and_image_paths

    monkeypatch.setattr(
        app_version_and_image_paths,
        "version_paths_for",
        lambda component, chart_dir=None: {"widget": ["fallback.version"]}.get(component, []),
    )
    values = {"widget": {"image": {"tag": "1.0.0@sha256:abc"}, "fallback": {"version": "9.9.9"}}}
    assert libupgradedoc.actual_app_version(values, "widget") == "1.0.0"


def _make_vendored_tgz(charts_dir, name, version, values, chart_yaml):
    import io
    import tarfile

    import yaml

    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    with tarfile.open(tgz_path, "w:gz") as tar:
        for filename, content in ((f"{name}/values.yaml", values), (f"{name}/Chart.yaml", chart_yaml)):
            data = yaml.safe_dump(content).encode("utf-8")
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return tgz_path


def test_actual_app_version_falls_back_to_vendored_subchart_app_version(libupgradedoc, tmp_path):
    """Regression test: openbao's own "server.image.tag" is explicitly
    overridden in values.yaml but deliberately left blank (see settings.
    yaml's own component_resolution.image_paths["openbao"] comment) —
    relies on the vendored chart's own Chart.yaml "appVersion" instead,
    which nothing but this third fallback pass can see. Without chart_dir/
    dep, behavior is unchanged (still returns None) — this fallback is
    opt-in per caller. No monkeypatch needed — openbao is already
    registered in the real component_resolution.image_paths."""
    _make_vendored_tgz(
        tmp_path / "charts",
        "openbao",
        "0.28.4",
        {"server": {"image": {"tag": ""}}},
        {"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.5"},
    )
    values = {"openbao": {"server": {"image": {"repository": "quay.io/openbao/openbao", "tag": ""}}}}
    dep = {"name": "openbao", "version": "0.28.4"}

    assert libupgradedoc.actual_app_version(values, "openbao", "openbao") is None
    assert libupgradedoc.actual_app_version(values, "openbao", "openbao", chart_dir=tmp_path, dep=dep) == "v2.5.5"


def test_actual_app_version_subchart_fallback_only_for_registered_components(libupgradedoc, tmp_path):
    """The vendored-appVersion fallback never applies to a component with
    no COMPONENT_IMAGE_PATHS entry of its own — a blank/missing tag on an
    unregistered component could just as easily mean "not actually
    running this image," which nothing here can tell apart from
    openbao's own deliberate design. (Not eck-operator as the example
    here anymore — it's now registered, precisely so this fallback DOES
    apply to it; see test_actual_app_version_eck_operator_vendored_
    fallback_resolves_correctly below. A clearly-synthetic name is used
    instead so this test can't go stale again the next time some other
    real component gets registered.)"""
    _make_vendored_tgz(
        tmp_path / "charts",
        "totally-unregistered-component",
        "3.5.0",
        {"image": {"tag": ""}},
        {"apiVersion": "v2", "version": "3.5.0", "appVersion": "3.5.0"},
    )
    values = {
        "totally-unregistered-component": {
            "image": {"repository": "example.invalid/totally-unregistered-component", "tag": ""}
        }
    }
    dep = {"name": "totally-unregistered-component", "version": "3.5.0"}

    assert (
        libupgradedoc.actual_app_version(
            values, "totally-unregistered-component", "totally-unregistered-component", chart_dir=tmp_path, dep=dep
        )
        is None
    )


def test_actual_app_version_eck_operator_vendored_fallback_resolves_correctly(libupgradedoc, tmp_path):
    """Regression test (real bug, real doc): eck-operator existed, enabled,
    at the podiumd-4.9.1 baseline with NO explicit values.yaml "image:"
    override at all (chart version 3.5.0, unchanged from target) — its
    real baseline app version is only ever resolvable via the vendored
    eck-operator-3.5.0.tgz's own default appVersion. Before eck-operator
    was registered in COMPONENT_IMAGE_PATHS, this always resolved to
    None (indistinguishable from "genuinely didn't exist yet"), which
    every upgrade.md-side caller then rendered as "(new)" instead of the
    correct "(unchanged)"."""
    _make_vendored_tgz(
        tmp_path / "charts",
        "eck-operator",
        "3.5.0",
        {"image": {"tag": ""}},
        {"apiVersion": "v2", "version": "3.5.0", "appVersion": "3.5.0"},
    )
    values = {"eck-operator": {}}  # no explicit "image:" override at all, same as the real 4.9.1 baseline
    dep = {"name": "eck-operator", "version": "3.5.0"}

    assert (
        libupgradedoc.actual_app_version(values, "eck-operator", "eck-operator", chart_dir=tmp_path, dep=dep) == "3.5.0"
    )


# --- find_image_tag_paths ---


def test_find_image_tag_paths_finds_nested_images(libupgradedoc):
    values = {
        "zac": {
            "image": {"tag": "5.1.0@sha256:aaaa"},
            "opa": {"image": {"tag": "1.19.0-static@sha256:bbbb"}},
        },
    }
    paths = dict(libupgradedoc.find_image_tag_paths(values))
    assert paths[("zac", "image")] == "5.1.0@sha256:aaaa"
    assert paths[("zac", "opa", "image")] == "1.19.0-static@sha256:bbbb"


def test_find_image_tag_paths_ignores_tagless_image_blocks(libupgradedoc):
    values = {"zac": {"image": {"repository": "x"}}}
    assert dict(libupgradedoc.find_image_tag_paths(values)) == {}


def test_find_image_tag_paths_walks_lists(libupgradedoc):
    values = {"items": [{"image": {"tag": "1.0@sha256:aaaa"}}]}
    paths = dict(libupgradedoc.find_image_tag_paths(values))
    assert paths[("items", "0", "image")] == "1.0@sha256:aaaa"


def test_find_image_tag_paths_finds_suffixed_image_key(libupgradedoc):
    """A component needing more than one distinctly-named image (e.g. a
    job's main "image" plus a separate "initImage") can't use the same
    bare "image" key for both — any key ending in "Image" counts too."""
    values = {
        "keycloak-operator": {
            "jobs": {
                "ensurePodiumdAdminUser": {
                    "image": {"tag": "16-alpine@sha256:aaaa"},
                    "initImage": {"tag": "3.14.7-slim@sha256:bbbb"},
                }
            }
        }
    }
    paths = dict(libupgradedoc.find_image_tag_paths(values))
    assert paths[("keycloak-operator", "jobs", "ensurePodiumdAdminUser", "image")] == "16-alpine@sha256:aaaa"
    assert paths[("keycloak-operator", "jobs", "ensurePodiumdAdminUser", "initImage")] == "3.14.7-slim@sha256:bbbb"


def test_find_image_tag_paths_excludes_plural_images_container(libupgradedoc):
    """ "images" (plural, a container of several named templates, e.g.
    global.images.nginx/curl/busybox/redis) must NOT itself be treated as
    an image block — it doesn't end in "Image" (capital I), only its own
    children (if literally keyed "image"/"...Image") would be."""
    values = {"global": {"images": {"nginx": {"tag": "1.31.4@sha256:aaaa"}}}}
    assert dict(libupgradedoc.find_image_tag_paths(values)) == {}


# --- find_image_tag_paths: include_null_tags ---


def test_find_image_tag_paths_default_still_ignores_null_tag(libupgradedoc):
    """include_null_tags defaults False -- every existing caller (find_
    all_image_and_version_paths, find_unresolved_subchart_images before
    this task) must see EXACTLY the same result as before."""
    values = {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}}}
    assert dict(libupgradedoc.find_image_tag_paths(values)) == {}


def test_find_image_tag_paths_include_null_tags_yields_none_for_null_tag_with_repository(libupgradedoc):
    values = {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}}}
    paths = dict(libupgradedoc.find_image_tag_paths(values, include_null_tags=True))
    assert paths == {("eck-operator", "image"): None}


def test_find_image_tag_paths_include_null_tags_yields_none_for_missing_tag_key(libupgradedoc):
    """A missing "tag:" key entirely is the same "rely on chart default"
    case as an explicit null -- dict.get("tag") returns None either
    way, and Helm's own template treats them identically."""
    values = {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator"}}}
    paths = dict(libupgradedoc.find_image_tag_paths(values, include_null_tags=True))
    assert paths == {("eck-operator", "image"): None}


def test_find_image_tag_paths_include_null_tags_skips_block_with_no_repository(libupgradedoc):
    """A null tag with no repository at all has nothing to resolve a
    basename from either way -- never worth yielding as a candidate."""
    values = {"eck-operator": {"image": {"tag": None}}}
    assert dict(libupgradedoc.find_image_tag_paths(values, include_null_tags=True)) == {}


def test_find_image_tag_paths_include_null_tags_still_excludes_blank_string_tag(libupgradedoc):
    """A DIFFERENT, already-handled case (e.g. openbao's own "server.
    image.tag") -- must stay excluded even with include_null_tags=True,
    never conflated with a genuinely null/missing tag."""
    values = {"openbao": {"server": {"image": {"repository": "openbao/openbao", "tag": ""}}}}
    assert dict(libupgradedoc.find_image_tag_paths(values, include_null_tags=True)) == {}


def test_find_image_tag_paths_include_null_tags_does_not_affect_real_tags(libupgradedoc):
    """A real, explicit tag elsewhere in the SAME tree must still come
    through as itself, unaffected by include_null_tags."""
    values = {
        "eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}},
        "zac": {"image": {"tag": "5.1.0@sha256:aaaa"}},
    }
    paths = dict(libupgradedoc.find_image_tag_paths(values, include_null_tags=True))
    assert paths[("zac", "image")] == "5.1.0@sha256:aaaa"
    assert paths[("eck-operator", "image")] is None


# --- find_component_version_tags / find_all_image_and_version_paths ---
# Real bug this closes: redis-operator's own image is pinned as flat
# sibling scalars ("redisOperator.imageTag"/"imageName", registered in
# lib.chart.COMPONENT_VERSION_PATHS), never nested under an "image:"/
# "...Image:" dict at all — find_image_tag_paths' generic structural
# scan can never see it, so the images-manifest list-diff check
# (lib.docs_consistency.check_images_manifest_format) silently treated
# a real version bump as "did not change vs baseline".


def test_find_component_version_tags_finds_registered_bare_field(libupgradedoc):
    deps = [{"name": "redis-operator", "version": "0.26.1"}]
    values = {
        "redis-operator": {
            "redisOperator": {
                "imageName": "quay.io/opstree/redis-operator",
                "imageTag": "v0.26.0@sha256:aaaa",
            }
        }
    }
    paths = dict(libupgradedoc.find_component_version_tags(values, deps))
    assert paths[("redis-operator", "redisOperator", "imageTag")] == "v0.26.0@sha256:aaaa"


def test_find_component_version_tags_uses_alias_not_name_for_the_values_key(libupgradedoc):
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}, "eck-kibana": {"version": "8.19.19"}}}
    paths = dict(libupgradedoc.find_component_version_tags(values, deps))
    assert paths[("kiss-eck", "eck-elasticsearch", "version")] == "8.19.19"
    assert paths[("kiss-eck", "eck-kibana", "version")] == "8.19.19"


def test_find_component_version_tags_skips_unset_field(libupgradedoc):
    deps = [{"name": "redis-operator", "version": "0.26.1"}]
    values = {"redis-operator": {}}
    assert dict(libupgradedoc.find_component_version_tags(values, deps)) == {}


def test_find_component_version_tags_includes_nested_subchart_registered_field(libupgradedoc):
    """eck-enterprise-search.version is registered in COMPONENT_VERSION_
    PATH_NESTED_SUBCHARTS but deliberately excluded from COMPONENT_
    VERSION_PATHS itself (disabled by default, not the "pick ONE app
    version" candidate) — still a real, discoverable image here."""
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    values = {"kiss-eck": {"eck-enterprise-search": {"version": "8.19.19"}}}
    paths = dict(libupgradedoc.find_component_version_tags(values, deps))
    assert paths[("kiss-eck", "eck-enterprise-search", "version")] == "8.19.19"


def test_find_component_version_tags_ignores_unregistered_dependency(libupgradedoc):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    assert dict(libupgradedoc.find_component_version_tags(values, deps)) == {}


def test_find_all_image_and_version_paths_combines_both(libupgradedoc):
    deps = [{"name": "redis-operator", "version": "0.26.1"}]
    values = {
        "redis-operator": {
            "redisOperator": {"imageName": "quay.io/opstree/redis-operator", "imageTag": "v0.26.0@sha256:aaaa"},
            "redis-ha": {"image": {"tag": "8.6.6@sha256:bbbb"}},
        }
    }
    paths = dict(libupgradedoc.find_all_image_and_version_paths(values, deps))
    assert paths[("redis-operator", "redisOperator", "imageTag")] == "v0.26.0@sha256:aaaa"
    assert paths[("redis-operator", "redis-ha", "image")] == "8.6.6@sha256:bbbb"


# --- resolve_entry_path ---


def test_resolve_entry_path_exact_match(libupgradedoc):
    paths = [("zac",), ("zgw-office-addin", "frontend"), ("zgw-office-addin", "backend")]
    assert libupgradedoc.resolve_entry_path("zgw-office-addin-frontend", paths) == ("zgw-office-addin", "frontend")


def test_resolve_entry_path_last_word_must_match(libupgradedoc):
    paths = [("zac", "solr-operator", "solr"), ("zac", "solr-operator", "zookeeper-operator", "zookeeper")]
    assert libupgradedoc.resolve_entry_path("zac-solr", paths) == ("zac", "solr-operator", "solr")


def test_resolve_entry_path_no_match_returns_none(libupgradedoc):
    assert libupgradedoc.resolve_entry_path("totally-unrelated", [("zac",)]) is None


def test_resolve_entry_path_ignores_trailing_image_key_for_matching(libupgradedoc):
    """A path from find_image_tag_paths always ends in the image key
    itself ("image", or an "...Image"-suffixed sibling) — that trailing
    segment is a structural marker, not a meaningful descriptor, so it
    must not be what "last word must match" is checked against (every
    such path would otherwise end in the word "image" and never match
    any real entry name again). The FULL path — trailing segment
    included — is still what gets returned."""
    paths = [("zac", "opa", "image")]
    assert libupgradedoc.resolve_entry_path("opa", paths) == ("zac", "opa", "image")


def test_resolve_entry_path_ignores_trailing_suffixed_image_key(libupgradedoc):
    paths = [("keycloak-operator", "python", "initImage")]
    assert libupgradedoc.resolve_entry_path("python", paths) == ("keycloak-operator", "python", "initImage")


# --- resolve_entry_image_path ---


def test_resolve_entry_image_path_exact_repo_map_hit(libupgradedoc):
    """A strip-registry-shaped manifest name ("infonl/zaakafhandelcomponent")
    doesn't fuzzy-word-match the values.yaml key ("zac") at all — repo_map
    is what makes it resolve, via an exact dict lookup rather than a guess."""
    paths = [("zac",)]
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    entry = {"name": "infonl/zaakafhandelcomponent", "url": "ghcr.io/infonl/zaakafhandelcomponent"}
    assert libupgradedoc.resolve_entry_image_path(entry, paths, repo_map) == ("zac",)


def test_resolve_entry_image_path_falls_back_without_repo_map(libupgradedoc):
    """No repo_map at all (e.g. a caller that never built one) — same
    fuzzy name-word matching as resolve_entry_path alone."""
    paths = [("zac",)]
    entry = {"name": "zac"}
    assert libupgradedoc.resolve_entry_image_path(entry, paths) == ("zac",)


def test_resolve_entry_image_path_falls_back_when_repo_map_has_no_hit(libupgradedoc):
    """repo_map given but this entry's name isn't in it (e.g. a nested
    sidecar with no Chart.yaml dependency of its own) — falls back to
    fuzzy name-word matching rather than giving up."""
    paths = [("zac", "opa", "image")]
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    entry = {"name": "opa", "url": "docker.io/openpolicyagent/opa"}
    assert libupgradedoc.resolve_entry_image_path(entry, paths, repo_map) == ("zac", "opa", "image")


def test_resolve_entry_image_path_ignores_repo_map_hit_not_in_paths(libupgradedoc):
    """A repo_map hit pointing at a path that isn't actually in this
    call's own paths (e.g. the component didn't exist yet at baseline)
    is not trusted blindly — falls back to fuzzy matching, which
    correctly finds nothing either."""
    paths = [("unrelated",)]
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    entry = {"name": "infonl/zaakafhandelcomponent"}
    assert libupgradedoc.resolve_entry_image_path(entry, paths, repo_map) is None
