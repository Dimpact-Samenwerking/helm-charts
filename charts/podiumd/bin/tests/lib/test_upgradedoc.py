"""lib.upgradedoc — table-row parsing, cell version extraction, fuzzy
dependency matching, and app-version lookup."""


# --- normalize_version / normalize_name / words_of ---

def test_normalize_version_strips_v_prefix(libupgradedoc):
    assert libupgradedoc.normalize_version("v0.9.313") == "0.9.313"
    assert libupgradedoc.normalize_version("5.4.3") == "5.4.3"
    assert libupgradedoc.normalize_version(None) is None


def test_normalize_name_strips_punctuation(libupgradedoc):
    assert libupgradedoc.normalize_name("ZAC (Zaakafhandelcomponent)") == "zaczaakafhandelcomponent"


def test_words_of_splits_on_non_alnum(libupgradedoc):
    assert libupgradedoc.words_of("zgw-office-addin-frontend") == ["zgw", "office", "addin", "frontend"]


# --- extract_target_version / extract_source_version ---

def test_extract_versions_arrow_cell(libupgradedoc):
    assert libupgradedoc.extract_source_version("5.0.2 → 5.4.3") == "5.0.2"
    assert libupgradedoc.extract_target_version("5.0.2 → 5.4.3") == "5.4.3"


def test_extract_versions_unchanged_cell(libupgradedoc):
    assert libupgradedoc.extract_source_version("1.0.297 (unchanged)") == "1.0.297"
    assert libupgradedoc.extract_target_version("1.0.297 (unchanged)") == "1.0.297"


def test_extract_versions_backtick_cell(libupgradedoc):
    assert libupgradedoc.extract_target_version("`0.0.92`") == "0.0.92"


# --- parse_upgrade_doc_rows ---

TABLE = """\
# Upgrade guide

## Component versions (4.9.0 vs 4.8.5)

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | ACR mirror only |
| ZGW Office Add-in (frontend + backend) | v0.9.313 → 0.11.0 | 0.0.89 → 0.0.92 | ACR mirror only |
"""


def test_parse_upgrade_doc_rows_parses_all_rows(libupgradedoc):
    rows = libupgradedoc.parse_upgrade_doc_rows(TABLE)
    assert len(rows) == 2
    assert rows[0]["name"] == "ZAC (Zaakafhandelcomponent)"
    assert rows[0]["app_source"] == "5.0.2"
    assert rows[0]["app"] == "5.4.3"
    assert rows[0]["chart_source"] == "1.0.297"
    assert rows[0]["chart"] == "1.0.297"


def test_parse_upgrade_doc_rows_includes_line_index(libupgradedoc):
    rows = libupgradedoc.parse_upgrade_doc_rows(TABLE)
    lines = TABLE.splitlines()
    assert lines[rows[0]["line_index"]] == \
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | ACR mirror only |"


def test_parse_upgrade_doc_rows_skips_header_and_separator(libupgradedoc):
    rows = libupgradedoc.parse_upgrade_doc_rows(TABLE)
    names = [r["name"] for r in rows]
    assert "Component" not in names
    assert not any(set(n) <= set("-: ") for n in names)


def test_parse_upgrade_doc_rows_no_table_returns_empty(libupgradedoc):
    assert libupgradedoc.parse_upgrade_doc_rows("# Upgrade guide\n\nJust prose.\n") == []


# --- _word_aligned_spans ---

def test_word_aligned_spans_includes_every_contiguous_word_run(libupgradedoc):
    spans = libupgradedoc._word_aligned_spans("ZGW Office Add-in")
    assert spans == {
        "zgw", "zgwoffice", "zgwofficeadd", "zgwofficeaddin",
        "office", "officeadd", "officeaddin",
        "add", "addin",
        "in",
    }


def test_word_aligned_spans_excludes_mid_word_fragments(libupgradedoc):
    """"mi" never appears as its own span even though it's a literal
    substring of "admin" — spans only ever concatenate WHOLE words."""
    spans = libupgradedoc._word_aligned_spans("ensurePodiumdAdminUser")
    assert "mi" not in spans
    assert spans == {"ensurepodiumdadminuser"}


# --- match_dependency ---

def test_match_dependency_by_alias(libupgradedoc):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    dep = libupgradedoc.match_dependency("ZAC (Zaakafhandelcomponent)", deps)
    assert dep["alias"] == "zac"


def test_match_dependency_prefers_longest_match(libupgradedoc):
    deps = [{"name": "openzaak"}, {"name": "openzaak-notificaties"}]
    dep = libupgradedoc.match_dependency("OpenZaak Notificaties", deps)
    assert dep["name"] == "openzaak-notificaties"


def test_match_dependency_no_match_returns_none(libupgradedoc):
    assert libupgradedoc.match_dependency("Totally Unknown Thing", [{"name": "zac"}]) is None


def test_match_dependency_short_alias_does_not_match_mid_word(libupgradedoc):
    """"mi" is a literal substring of "ensurePodiumdAdminUser" (inside
    "ad-mi-n") — must not match at all without a real word boundary."""
    deps = [{"name": "mi-data", "alias": "mi"}]
    assert libupgradedoc.match_dependency("Python (ensurePodiumdAdminUser init image)", deps) is None


# --- changes_heading_identities ---

def test_changes_heading_identities_single_component(libupgradedoc):
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    idents = libupgradedoc.changes_heading_identities(
        "ECK Stack (kiss-eck) 8.19.3 → 8.19.19 (chart 0.19.0 → 0.20.0)", deps, {})
    assert idents == {("dep", "kiss-eck")}


def test_changes_heading_identities_two_real_components(libupgradedoc):
    deps = [
        {"name": "eck-operator", "version": "3.5.0"},
        {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"},
    ]
    idents = libupgradedoc.changes_heading_identities(
        "ECK Operator 3.4.0 → 3.5.0 + ECK Stack (kiss-eck) 0.19.0 → 0.20.0", deps, {})
    assert idents == {("dep", "eck-operator"), ("dep", "kiss-eck")}


def test_changes_heading_identities_does_not_double_count_an_alias_nested_inside_another(libupgradedoc):
    """Regression test: eck-stack's own alias "kiss-eck" tokenizes to the
    words "kiss"+"eck" — the standalone "kiss" word inside it is ALSO,
    coincidentally, the real KISS dependency's own alias. Without a
    containment filter, this heading would wrongly resolve to BOTH
    "kiss-eck" and "kiss" (two identities), when it only ever names one
    real component — the same class of bug find_changes_row_
    correspondence_gaps exists to catch would then wrongly flag this
    heading as ambiguous and its row as missing a section."""
    deps = [
        {"name": "kiss", "alias": "KISS", "version": "3.0.0"},
        {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"},
    ]
    idents = libupgradedoc.changes_heading_identities(
        "ECK Stack (kiss-eck) 8.19.3 → 8.19.19 (chart 0.19.0 → 0.20.0)", deps, {})
    assert idents == {("dep", "kiss-eck")}


def test_changes_heading_identities_self_referential_sidecar_shape_resolves_to_nothing(libupgradedoc):
    """Regression test: a heading shaped like a canonical sidecar
    reference ("<parent> - <basename>", " - " being the shape's own
    literal delimiter) that doesn't actually match any REAL canonical
    sidecar name (real case: "### openbao - openbao 2.5.5 → 2.5.5" —
    self-referential, canonical_sidecar_row_names refuses to name a
    sidecar after its own parent) must resolve to NO identity at all —
    never fall through to a coincidental plain word match against the
    real "openbao" dependency just because the word "openbao" happens
    to appear in the broken heading's own text too."""
    deps = [{"name": "openbao", "version": "0.28.4"}]
    idents = libupgradedoc.changes_heading_identities("openbao - openbao 2.5.5 → 2.5.5", deps, {})
    assert idents == set()


def test_changes_heading_identities_real_sidecar_still_resolves_despite_dash(libupgradedoc):
    """The " - " guard must never swallow a REAL canonical sidecar match
    — only applies once match_canonical_sidecar_name has already had its
    own shot and failed."""
    canonical_names = {"openbao - postgres": ("openbao", "database", "schemaJob", "image")}
    deps = [{"name": "openbao", "version": "0.28.4"}]
    idents = libupgradedoc.changes_heading_identities(
        "openbao - postgres 16-alpine → 16-alpine", deps, canonical_names)
    assert idents == {("sidecar", ("openbao", "database", "schemaJob", "image"))}


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
    values = {"redis-operator": {"redisOperator": {
        "imageName": "quay.io/opstree/redis-operator", "imageTag": "v0.26.0"}}}
    assert libupgradedoc.actual_app_version(values, "redis-operator") == "v0.26.0"


def test_actual_app_version_image_tag_path_tried_before_version_path(libupgradedoc, monkeypatch):
    """The "image: {tag: ...}" pass always runs first — COMPONENT_
    VERSION_PATHS is only ever a fallback for when NONE of a
    component's image_paths_for candidates resolved anything."""
    monkeypatch.setitem(libupgradedoc.version_paths_for.__globals__["COMPONENT_VERSION_PATHS"],
                         "widget", ["fallback.version"])
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


def test_actual_app_version_falls_back_to_vendored_subchart_app_version(libupgradedoc, tmp_path, monkeypatch):
    """Regression test: openbao's own "server.image.tag" is explicitly
    overridden in values.yaml but deliberately left blank (see
    lib.chart.COMPONENT_IMAGE_PATHS["openbao"]'s own comment) — relies
    on the vendored chart's own Chart.yaml "appVersion" instead, which
    nothing but this third fallback pass can see. Without chart_dir/dep,
    behavior is unchanged (still returns None) — this fallback is opt-in
    per caller."""
    monkeypatch.setitem(libupgradedoc.image_paths_for.__globals__["COMPONENT_IMAGE_PATHS"],
                         "openbao", ["server.image"])
    _make_vendored_tgz(tmp_path / "charts", "openbao", "0.28.4",
                        {"server": {"image": {"tag": ""}}},
                        {"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.5"})
    values = {"openbao": {"server": {"image": {"repository": "quay.io/openbao/openbao", "tag": ""}}}}
    dep = {"name": "openbao", "version": "0.28.4"}

    assert libupgradedoc.actual_app_version(values, "openbao", "openbao") is None
    assert libupgradedoc.actual_app_version(
        values, "openbao", "openbao", chart_dir=tmp_path, dep=dep) == "v2.5.5"


def test_actual_app_version_subchart_fallback_only_for_registered_components(libupgradedoc, tmp_path):
    """The vendored-appVersion fallback never applies to a component with
    no COMPONENT_IMAGE_PATHS entry of its own (e.g. eck-operator, which
    also floats on its own chart's appVersion but is deliberately left
    unresolved — already documented in images-manifest prose, not a
    gap) — a blank/missing tag on an unregistered component could just
    as easily mean "not actually running this image," which nothing
    here can tell apart from openbao's own deliberate design."""
    _make_vendored_tgz(tmp_path / "charts", "eck-operator", "3.5.0",
                        {"image": {"tag": ""}},
                        {"apiVersion": "v2", "version": "3.5.0", "appVersion": "3.5.0"})
    values = {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": ""}}}
    dep = {"name": "eck-operator", "version": "3.5.0"}

    assert libupgradedoc.actual_app_version(
        values, "eck-operator", "eck-operator", chart_dir=tmp_path, dep=dep) is None


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
    """"images" (plural, a container of several named templates, e.g.
    global.images.nginx/curl/busybox/redis) must NOT itself be treated as
    an image block — it doesn't end in "Image" (capital I), only its own
    children (if literally keyed "image"/"...Image") would be."""
    values = {"global": {"images": {"nginx": {"tag": "1.31.4@sha256:aaaa"}}}}
    assert dict(libupgradedoc.find_image_tag_paths(values)) == {}


# --- resolve_entry_path ---

def test_resolve_entry_path_exact_match(libupgradedoc):
    paths = [("zac",), ("zgw-office-addin", "frontend"), ("zgw-office-addin", "backend")]
    assert libupgradedoc.resolve_entry_path("zgw-office-addin-frontend", paths) == \
        ("zgw-office-addin", "frontend")


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
    assert libupgradedoc.resolve_entry_path("python", paths) == \
        ("keycloak-operator", "python", "initImage")


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


# --- find_images_manifest_list_diff ---

def test_find_images_manifest_list_diff_exact_list_reports_nothing(libupgradedoc):
    """The manifest lists exactly the one image that actually changed —
    both halves come back empty."""
    entries = [{"name": "zac"}]
    current_paths = {("zac",): "1.2.0@sha256:new"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, extra = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={})
    assert missing == []
    assert extra == []


def test_find_images_manifest_list_diff_finds_missing_changed_image(libupgradedoc):
    """A path whose tag actually changed but has no manifest entry at all
    resolving to it is reported as missing."""
    entries = []
    current_paths = {("zac",): "1.2.0@sha256:new"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, extra = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={})
    assert missing == [("zac",)]
    assert extra == []


def test_find_images_manifest_list_diff_finds_entry_for_unchanged_image(libupgradedoc):
    """An entry that resolves to a real path, but that path's tag is
    identical between baseline and current — listed without a real
    reason to be there."""
    entries = [{"name": "zac"}]
    current_paths = {("zac",): "1.1.0@sha256:old"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, extra = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={})
    assert missing == []
    assert extra == ["zac"]


def test_find_images_manifest_list_diff_finds_entry_matching_nothing(libupgradedoc):
    """An entry whose name doesn't resolve to any values-tree path at
    all (typo, stale, or a component that's since been removed) is also
    reported as extra."""
    entries = [{"name": "does-not-exist"}]
    current_paths = {("zac",): "1.1.0@sha256:old"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    missing, extra = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={})
    assert missing == []
    assert extra == ["does-not-exist"]


def test_find_images_manifest_list_diff_catches_digest_only_repin(libupgradedoc):
    """A tag whose version number is unchanged but whose digest was
    re-pinned still counts as "changed" — matches this manifest's own
    "newly digest-pinned... tag unchanged" convention."""
    entries = []
    current_paths = {("zac",): "1.1.0@sha256:newdigest"}
    baseline_paths = {("zac",): "1.1.0@sha256:olddigest"}
    missing, extra = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map={})
    assert missing == [("zac",)]
    assert extra == []


def test_find_images_manifest_list_diff_uses_repo_map_for_resolution(libupgradedoc):
    """Entry resolution goes through resolve_entry_image_path — a
    strip-registry-shaped name only matches via repo_map, same as that
    function's own exact-hit behavior."""
    entries = [{"name": "infonl/zaakafhandelcomponent"}]
    current_paths = {("zac",): "1.2.0@sha256:new"}
    baseline_paths = {("zac",): "1.1.0@sha256:old"}
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    missing, extra = libupgradedoc.find_images_manifest_list_diff(
        entries, current_paths, baseline_paths, repo_map)
    assert missing == []
    assert extra == []


# --- find_preceding_comment ---

def test_find_preceding_comment_joins_consecutive_comment_lines(libupgradedoc):
    lines = [
        "# ZAC OPA sidecar\n",
        "# 1.17.1-static -> 1.19.0-static\n",
        "- name: opa\n",
    ]
    assert libupgradedoc.find_preceding_comment(lines, 2) == \
        "# ZAC OPA sidecar # 1.17.1-static -> 1.19.0-static"


def test_find_preceding_comment_stops_at_blank_line(libupgradedoc):
    lines = [
        "# unrelated previous entry's comment\n",
        "\n",
        "# ZAC — 5.0.1 -> 5.1.0\n",
        "- name: zac\n",
    ]
    assert libupgradedoc.find_preceding_comment(lines, 3) == "# ZAC — 5.0.1 -> 5.1.0"


def test_find_preceding_comment_none_when_absent(libupgradedoc):
    lines = ["- name: zac\n"]
    assert libupgradedoc.find_preceding_comment(lines, 0) == ""


# --- find_grouped_preceding_comment / find_grouped_preceding_comment_line ---

ZGW_GROUPED_LINES = [
    "# ZGW Office Add-in — v0.9.313 -> v0.9.352\n",
    "- name: zgw-office-addin-frontend\n",
    '  version: "v0.9.352"\n',
    "\n",
    "- name: zgw-office-addin-backend\n",
    '  version: "v0.9.352"\n',
]
ZGW_ENTRIES = [{"name": "zgw-office-addin-frontend", "version": "v0.9.352"},
               {"name": "zgw-office-addin-backend", "version": "v0.9.352"}]
ZGW_ENTRY_LINE_INDICES = [1, 4]


def component_of(entry):
    if "zgw-office-addin" in entry["name"]:
        return "zgw-office-addin"
    if entry["name"] in ("zac", "opa"):
        return "zac"
    return None


def same_group(entry_a, entry_b):
    """The grouping predicate check_images_manifest_format and friends
    actually use: same top-level component AND same declared version —
    matching declared versions is what tells a lockstep multi-image bump
    (zgw-office-addin frontend/backend, always identical) apart from two
    independently-versioned images that just share a values-tree prefix
    (zac vs. its zac.opa sidecar)."""
    return (component_of(entry_a) is not None
            and component_of(entry_a) == component_of(entry_b)
            and entry_a.get("version") == entry_b.get("version"))


def test_find_grouped_preceding_comment_uses_own_comment_when_present(libupgradedoc):
    comment = libupgradedoc.find_grouped_preceding_comment(
        ZGW_GROUPED_LINES, ZGW_ENTRIES, ZGW_ENTRY_LINE_INDICES, 0, same_group)
    assert comment == "# ZGW Office Add-in — v0.9.313 -> v0.9.352"


def test_find_grouped_preceding_comment_inherits_sibling_comment_across_blank_line(libupgradedoc):
    comment = libupgradedoc.find_grouped_preceding_comment(
        ZGW_GROUPED_LINES, ZGW_ENTRIES, ZGW_ENTRY_LINE_INDICES, 1, same_group)
    assert comment == "# ZGW Office Add-in — v0.9.313 -> v0.9.352"


def test_find_grouped_preceding_comment_does_not_inherit_across_different_component(libupgradedoc):
    """A ZAC entry right after ZGW's group, with no comment of its own, must
    NOT inherit ZGW's comment just because it's the immediately preceding
    entry — they resolve to different components."""
    lines = ZGW_GROUPED_LINES + ["\n", "- name: zac\n", '  version: "5.1.0"\n']
    entries = ZGW_ENTRIES + [{"name": "zac", "version": "5.1.0"}]
    entry_line_indices = ZGW_ENTRY_LINE_INDICES + [7]

    comment = libupgradedoc.find_grouped_preceding_comment(
        lines, entries, entry_line_indices, 2, same_group)
    assert comment == ""


def test_find_grouped_preceding_comment_does_not_override_own_distinct_comment(libupgradedoc):
    """ZAC's OPA sidecar has its own comment despite resolving to the same
    top-level component ("zac") as ZAC's main entry — its own comment must
    win, never be replaced by the main entry's comment."""
    lines = [
        "# ZAC — 5.0.1 -> 5.1.0\n",
        "- name: zac\n",
        '  version: "5.1.0"\n',
        "# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static\n",
        "- name: opa\n",
        '  version: "1.19.0-static"\n',
    ]
    entries = [{"name": "zac", "version": "5.1.0"}, {"name": "opa", "version": "1.19.0-static"}]
    entry_line_indices = [1, 4]

    comment = libupgradedoc.find_grouped_preceding_comment(
        lines, entries, entry_line_indices, 1, same_group)
    assert comment == "# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static"


def test_find_grouped_preceding_comment_does_not_inherit_when_versions_differ(libupgradedoc):
    """Same top-level component ("zac") is not enough on its own — the
    OPA sidecar's version differs from ZAC's own, so even with no comment
    of its own it must NOT inherit ZAC's comment (they're independently
    versioned, not one lockstep bump)."""
    lines = [
        "# ZAC — 5.0.1 -> 5.1.0\n",
        "- name: zac\n",
        '  version: "5.1.0"\n',
        "\n",
        "- name: opa\n",
        '  version: "1.19.0-static"\n',
    ]
    entries = [{"name": "zac", "version": "5.1.0"}, {"name": "opa", "version": "1.19.0-static"}]
    entry_line_indices = [1, 4]

    comment = libupgradedoc.find_grouped_preceding_comment(
        lines, entries, entry_line_indices, 1, same_group)
    assert comment == ""


def test_find_grouped_preceding_comment_line_uses_own_line_when_present(libupgradedoc):
    idx = libupgradedoc.find_grouped_preceding_comment_line(
        ZGW_GROUPED_LINES, ZGW_ENTRIES, ZGW_ENTRY_LINE_INDICES, 0, same_group)
    assert idx == 0


def test_find_grouped_preceding_comment_line_inherits_sibling_line_across_blank_line(libupgradedoc):
    idx = libupgradedoc.find_grouped_preceding_comment_line(
        ZGW_GROUPED_LINES, ZGW_ENTRIES, ZGW_ENTRY_LINE_INDICES, 1, same_group)
    assert idx == 0


def test_find_grouped_preceding_comment_line_none_for_different_component(libupgradedoc):
    lines = ZGW_GROUPED_LINES + ["\n", "- name: zac\n", '  version: "5.1.0"\n']
    entries = ZGW_ENTRIES + [{"name": "zac", "version": "5.1.0"}]
    entry_line_indices = ZGW_ENTRY_LINE_INDICES + [7]

    idx = libupgradedoc.find_grouped_preceding_comment_line(
        lines, entries, entry_line_indices, 2, same_group)
    assert idx is None


# --- diff_keys / flatten_leaf_keys / pair_renames ---

def test_diff_keys_finds_added_and_removed(libupgradedoc):
    baseline = {"a": 1, "b": {"x": 1}}
    current = {"a": 1, "c": {"y": 1}}
    diffs = sorted(libupgradedoc.diff_keys(baseline, current))
    assert ("added", ("c",)) in diffs
    assert ("removed", ("b",)) in diffs


def test_diff_keys_ignores_scalar_value_changes(libupgradedoc):
    baseline = {"a": 1}
    current = {"a": 2}
    assert list(libupgradedoc.diff_keys(baseline, current)) == []


def test_diff_keys_recurses_into_shared_keys(libupgradedoc):
    baseline = {"a": {"x": 1}}
    current = {"a": {"x": 1, "y": 2}}
    assert list(libupgradedoc.diff_keys(baseline, current)) == [("added", ("a", "y"))]


def test_flatten_leaf_keys_collects_all_nested_names(libupgradedoc):
    node = {"host": "h", "auth": {"user": "u", "password": "p"}}
    assert libupgradedoc.flatten_leaf_keys(node) == {"host", "auth", "user", "password"}


def test_flatten_leaf_keys_walks_lists(libupgradedoc):
    node = [{"a": 1}, {"b": 2}]
    assert libupgradedoc.flatten_leaf_keys(node) == {"a", "b"}


def test_pair_renames_pairs_similar_subtrees(libupgradedoc):
    baseline = {"mi": {"sftp": {"host": "h", "user": "u", "password": "p"}}}
    current = {"mi": {"transfer": {"host": "h", "user": "u", "password": "p"}}}
    added = [("mi", "transfer")]
    removed = [("mi", "sftp")]
    renamed, added_left, removed_left = libupgradedoc.pair_renames(added, removed, baseline, current)
    assert renamed == [(("mi", "sftp"), ("mi", "transfer"))]
    assert added_left == [] and removed_left == []


def test_pair_renames_leaves_unrelated_add_remove_alone(libupgradedoc):
    baseline = {"a": {"x": 1}}
    current = {"b": {"totally": "different", "shape": True}}
    added = [("b",)]
    removed = [("a",)]
    renamed, added_left, removed_left = libupgradedoc.pair_renames(added, removed, baseline, current)
    assert renamed == []
    assert added_left == [("b",)] and removed_left == [("a",)]


# --- parse_changes_block ---

def test_parse_changes_block_parses_numbered_items(libupgradedoc):
    text = (
        "# Baseline: podiumd 4.8.5.\n"
        "#\n"
        "# Changes:\n"
        "#   1. ZAC 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).\n"
        "#   2. ZGW Office Add-in v0.9.313 -> 0.11.0 (chart 0.0.89 -> 0.0.92).\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/...\n"
    )
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 2
    assert items[0]["name"] == "ZAC"
    assert items[0]["app_source"] == "5.0.2"
    assert items[0]["app"] == "5.4.3"
    assert items[1]["chart_source"] == "0.0.89"
    assert items[1]["chart"] == "0.0.92"


def test_parse_changes_block_no_header_returns_empty(libupgradedoc):
    assert libupgradedoc.parse_changes_block("# just a header\n# no changes block\n") == []


def test_parse_changes_block_version_with_dot_not_mistaken_for_new_item(libupgradedoc):
    text = (
        "# Changes:\n"
        "#   1. OPA 1.17.1-static -> 1.19.0-static\n"
        "#   2. ZAC 5.0.2 -> 5.4.3\n"
    )
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 2
    assert items[0]["app"] == "1.19.0-static"
    assert items[1]["app"] == "5.4.3"


def test_parse_changes_block_joins_a_wrapped_version_pair(libupgradedoc):
    """Regression test: an item whose own "<source> -> <target>" pair
    sits on a WRAPPED continuation line (not the numbered line itself)
    used to be silently unparseable — extract_source_version/
    extract_target_version's own "no arrow found" fallback grabbed the
    item's own leading word ("nginx-unprivileged") as a fake version,
    since the numbered line alone never had an arrow in it at all."""
    text = (
        "# Changes:\n"
        "#   21. nginx-unprivileged (shared global.images.nginx anchor, used by every\n"
        "#      nginx sidecar in the chart) 1.31.3 -> 1.31.4.\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/...\n"
    )
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["name"] == (
        "nginx-unprivileged (shared global.images.nginx anchor, used by every "
        "nginx sidecar in the chart)"
    )
    assert items[0]["app_source"] == "1.31.3"
    assert items[0]["app"] == "1.31.4"  # not "1.31.4." — trailing sentence period stripped


def test_parse_changes_block_joins_a_wrapped_chart_version(libupgradedoc):
    """The same continuation-joining fixes a second, previously silent
    gap: a "(chart ...)" span whose own closing paren is on the wrapped
    line never matched at all before (chart_source/chart just stayed
    None, so the chart comparison was silently skipped rather than
    actually verified)."""
    text = (
        "# Changes:\n"
        "#   1. ZAC 5.0.2 -> 5.4.4 (chart 1.0.297, unchanged — the chart line was\n"
        "#      already bumped ahead of the image in the 4.8.5 hop).\n"
    )
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["chart_source"] == "1.0.297"
    assert items[0]["chart"] == "1.0.297"


def test_parse_changes_block_chart_only_item_with_no_parens_has_no_fake_app_version(libupgradedoc):
    """Regression test: a chart-only item that states its version pair as
    a bare "chart <source> -> <target>" clause (no "(chart ...)" parens
    at all) must never have that pair mistaken for the item's own APP
    version — the real-world case this was found from: "ECK Stack
    (kiss-eck) chart 0.19.0 -> 0.20.0 (no image change of its own)."
    used to grab "0.19.0 -> 0.20.0" as a fake app version once eck-stack
    became resolvable via COMPONENT_VERSION_PATHS, silently comparing it
    against the real (unrelated) app version and reporting a bogus
    mismatch."""
    text = (
        "# Changes:\n"
        "#   6. ECK Stack (kiss-eck) chart 0.19.0 -> 0.20.0 (no image change of\n"
        "#      its own).\n"
    )
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["chart_source"] == "0.19.0"
    assert items[0]["chart"] == "0.20.0"
    assert items[0]["app_source"] is None
    assert items[0]["app"] is None


def test_parse_changes_block_chart_pair_before_app_pair_both_extracted_correctly(libupgradedoc):
    """The real-world redis-operator case: BOTH a bare chart clause and a
    real app-version pair appear in the same sentence, chart first — the
    chart pair must not be mistaken for the app pair, and the real app
    pair (the second one) must still be found correctly."""
    text = (
        "# Changes:\n"
        "#   15. redis-operator chart 0.25.0 -> 0.26.1, operator image 0.25.0 ->\n"
        "#      0.26.0 (quay.io/opstree/redis-operator, digest-pinned).\n"
    )
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["chart_source"] == "0.25.0"
    assert items[0]["chart"] == "0.26.1"
    assert items[0]["app_source"] == "0.25.0"
    assert items[0]["app"] == "0.26.0"


def test_parse_changes_block_strips_trailing_sentence_period_even_on_a_single_line(libupgradedoc):
    """The trailing-period fix isn't specific to wrapped items — any
    Changes item whose version is the last thing before its own
    sentence-ending period, single-line or not, must have it stripped."""
    text = "# Changes:\n#   1. curl 8.20.0 -> 8.21.0.\n"
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["app_source"] == "8.20.0"
    assert items[0]["app"] == "8.21.0"


def test_parse_changes_block_trailing_remark_does_not_get_absorbed_into_last_item(libupgradedoc):
    """A trailing "# See docs/..." remark right after the last item, with
    no blank "#" line separating them, must never be swallowed into that
    item's own text — it's indented with the ordinary single-space
    comment convention, not the 2+-space continuation indent, so it's
    distinguishable from a real wrapped continuation line."""
    text = (
        "# Changes:\n"
        "#   1. ZAC 5.0.2 -> 5.4.3\n"
        "# See docs/_UPGRADE_PATHS/...\n"
    )
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["name"] == "ZAC"
    assert "See docs" not in items[0]["name"]


def test_parse_changes_block_last_item_with_no_trailing_hash_line_still_finalizes(libupgradedoc):
    """The very last item in the block, with nothing at all following it
    (no blank "#" line, no trailing remark, file just ends) must still
    be finalized — not silently dropped because there was no later line
    to trigger it."""
    text = "# Changes:\n#   1. ZAC 5.0.2 -> 5.4.3"
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["name"] == "ZAC"


# --- canonical_version_cell ---

def test_canonical_version_cell_arrow_form(libupgradedoc):
    assert libupgradedoc.canonical_version_cell("5.0.2", "5.1.0") == "5.0.2 → 5.1.0"


def test_canonical_version_cell_unchanged_form(libupgradedoc):
    assert libupgradedoc.canonical_version_cell("1.0.297", "1.0.297") == "1.0.297 (unchanged)"


# --- find_preceding_comment_line / replace_version_pair ---

def test_find_preceding_comment_line_finds_arrow_comment(libupgradedoc):
    lines = ["# ZAC — 5.0.1 -> 5.1.0\n", "- name: zac\n"]
    assert libupgradedoc.find_preceding_comment_line(lines, 1) == 0


def test_find_preceding_comment_line_none_when_no_arrow(libupgradedoc):
    lines = ["#repository:\n", "- name: zac\n"]
    assert libupgradedoc.find_preceding_comment_line(lines, 1) is None


def test_replace_version_pair_preserves_prefix_and_arrow_style(libupgradedoc):
    assert libupgradedoc.replace_version_pair("# ZAC — 5.0.1 -> 5.1.0\n", "5.0.2", "5.1.0") == \
        "# ZAC — 5.0.2 -> 5.1.0\n"
    assert libupgradedoc.replace_version_pair("# ZAC — 5.0.1 → 5.1.0\n", "5.0.2", "5.1.0") == \
        "# ZAC — 5.0.2 → 5.1.0\n"


def test_replace_version_pair_no_match_returns_unchanged(libupgradedoc):
    line = "# no version pair here\n"
    assert libupgradedoc.replace_version_pair(line, "1.0.0", "2.0.0") == line


# --- compute_changed_components ---

def test_compute_changed_components_detects_chart_version_bump(libupgradedoc):
    deps = [{"name": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zac", "version": "1.0.251"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    assert libupgradedoc.compute_changed_components(deps, baseline_deps, values, values) == {"zac"}


def test_compute_changed_components_detects_image_tag_change(libupgradedoc):
    deps = [{"name": "zac", "version": "1.0.297"}]
    current = {"zac": {"image": {"tag": "5.4.3@sha256:bbbb"}}}
    baseline = {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}
    assert libupgradedoc.compute_changed_components(deps, deps, current, baseline) == {"zac"}


def test_compute_changed_components_detects_added_dependency(libupgradedoc):
    deps = [{"name": "zac", "version": "1.0.297"}, {"name": "openformulieren", "version": "1.12.0"}]
    baseline_deps = [{"name": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}},
              "openformulieren": {"image": {"tag": "3.5.6@sha256:cccc"}}}
    assert libupgradedoc.compute_changed_components(deps, baseline_deps, values, values) == {"openformulieren"}


def test_compute_changed_components_detects_removed_dependency(libupgradedoc):
    deps = [{"name": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zac", "version": "1.0.297"}, {"name": "old-component", "version": "1.0.0"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}},
                        "old-component": {"image": {"tag": "1.0.0@sha256:dddd"}}}
    assert libupgradedoc.compute_changed_components(deps, baseline_deps, values, baseline_values) == \
        {"old-component"}


def test_compute_changed_components_uses_alias_as_key(libupgradedoc):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    assert libupgradedoc.compute_changed_components(deps, baseline_deps, values, values) == {"zac"}


def test_compute_changed_components_no_change_is_empty(libupgradedoc):
    deps = [{"name": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}, "other": {"a": 1}}
    assert libupgradedoc.compute_changed_components(deps, deps, values, values) == set()


def test_compute_changed_components_ignores_unrelated_key_changes(libupgradedoc):
    """A values.yaml key change under a component NOT in Chart.yaml's
    dependencies (e.g. a plain feature flag) must not be reported — this
    function is scoped to actual Chart.yaml dependency changes."""
    deps = [{"name": "zac", "version": "1.0.297"}]
    current = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}, "global": {"flag": True}}
    baseline = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}, "global": {"flag": False}}
    assert libupgradedoc.compute_changed_components(deps, deps, current, baseline) == set()


# --- extract_mentioned_dependency_keys ---

def test_extract_mentioned_dependency_keys_finds_bold_bullet(libupgradedoc):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    text = "- **ZAC** app `5.0.2 → 5.4.3` (chart `1.0.297`, unchanged) — image tag only.\n"
    assert libupgradedoc.extract_mentioned_dependency_keys(text, deps) == {"zac"}


def test_extract_mentioned_dependency_keys_ignores_unmatched_bold_text(libupgradedoc):
    deps = [{"name": "zac", "version": "1.0.297"}]
    text = "This is **not a component** and neither is **this**.\n"
    assert libupgradedoc.extract_mentioned_dependency_keys(text, deps) == set()


def test_extract_mentioned_dependency_keys_no_bold_spans_is_empty(libupgradedoc):
    deps = [{"name": "zac", "version": "1.0.297"}]
    assert libupgradedoc.extract_mentioned_dependency_keys("plain text, no bold at all", deps) == set()


def test_extract_mentioned_dependency_keys_ignores_fenced_code_block(libupgradedoc):
    """A single "**" pair used inside a fenced code block (e.g. Python's
    own `**kwargs`) must never desync bold-span pairing for the REST of
    the document — see strip_fenced_code_blocks."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    text = (
        "```python\n"
        "def f(**kwargs): pass\n"
        "```\n\n"
        "- **ZAC** app `5.0.2 → 5.4.3` (chart `1.0.297`, unchanged) — image tag only.\n"
    )
    assert libupgradedoc.extract_mentioned_dependency_keys(text, deps) == {"zac"}


# --- describe_key_changes / append_to_doc ---

def test_describe_key_changes_reports_added_removed_renamed(libupgradedoc):
    baseline = {"sftp": {"host": "x", "user": "y", "password": "z"}, "old": 1}
    current = {"transfer": {"mode": "sftp-password", "host": "x", "user": "y", "password": "z"}, "new": 2}
    lines = libupgradedoc.describe_key_changes("mi", baseline, current)
    joined = "".join(lines)
    assert "- Key `mi.sftp` was renamed to `mi.transfer`.\n" in joined
    assert "- Key `mi.old` was removed.\n" in joined
    assert "- Key `mi.new` was added.\n" in joined


def test_describe_key_changes_empty_when_nothing_changed(libupgradedoc):
    assert libupgradedoc.describe_key_changes("comp", {"a": 1}, {"a": 1}) == []


def test_append_to_doc_adds_blank_line_separator(libupgradedoc):
    text = "# Values deltas\n\nSome existing content.\n"
    result = libupgradedoc.append_to_doc(text, ["- new bullet\n"])
    assert result == "# Values deltas\n\nSome existing content.\n\n- new bullet\n"


def test_append_to_doc_no_new_lines_returns_unchanged(libupgradedoc):
    text = "# Values deltas\n\nSome existing content.\n"
    assert libupgradedoc.append_to_doc(text, []) == text


# --- missing_key_change_lines ---

def test_missing_key_change_lines_reports_unmentioned_addition(libupgradedoc):
    baseline_values = {"zac": {"brpApi": {}}}
    values = {"zac": {"brpApi": {"logLevel": "OFF"}}}
    text = "Nothing relevant mentioned.\n"
    lines = libupgradedoc.missing_key_change_lines(text, {"zac"}, baseline_values, values)
    assert lines == ["- Key `zac.brpApi.logLevel` was added.\n"]


def test_missing_key_change_lines_skips_already_mentioned_addition(libupgradedoc):
    baseline_values = {"zac": {"brpApi": {}}}
    values = {"zac": {"brpApi": {"logLevel": "OFF"}}}
    text = "New field `zac.brpApi.logLevel`, defaults to `OFF`.\n"
    assert libupgradedoc.missing_key_change_lines(text, {"zac"}, baseline_values, values) == []


def test_missing_key_change_lines_rename_needs_both_sides_mentioned(libupgradedoc):
    baseline_values = {"mi": {"sftp": {"host": "x", "user": "y", "password": "z"}}}
    values = {"mi": {"transfer": {"mode": "sftp-password", "host": "x", "user": "y", "password": "z"}}}
    # only the OLD side is mentioned — the rename isn't fully documented
    text = "Removed `mi.sftp` in favor of something else.\n"
    lines = libupgradedoc.missing_key_change_lines(text, {"mi"}, baseline_values, values)
    assert lines == ["- Key `mi.sftp` was renamed to `mi.transfer`.\n"]


def test_missing_key_change_lines_ignores_unrelated_component(libupgradedoc):
    baseline_values = {"zac": {"a": 1}, "unrelated": {"a": 1}}
    values = {"zac": {"a": 1}, "unrelated": {"b": 2}}
    # "unrelated" isn't in changed_component_keys, so its diff must be ignored
    assert libupgradedoc.missing_key_change_lines("no mentions", {"zac"}, baseline_values, values) == []


def test_missing_key_change_lines_empty_when_nothing_changed(libupgradedoc):
    values = {"zac": {"a": 1}}
    assert libupgradedoc.missing_key_change_lines("", {"zac"}, values, values) == []


def test_missing_key_change_lines_ignores_mention_inside_fenced_code_block(libupgradedoc):
    """A key mentioned only inside an unrelated fenced code block (an odd
    number of backticks there desyncs regex pairing for the rest of the
    doc) must not be treated as "already mentioned" for a real bullet —
    see strip_fenced_code_blocks. Real-world case: a values-deltas.md
    with 5 fenced snippets caused this to silently re-add nearly its
    entire existing bullet list as "missing"."""
    baseline_values = {"zac": {"brpApi": {}}}
    values = {"zac": {"brpApi": {"logLevel": "OFF"}}}
    text = (
        "```yaml\n"
        "some: `unbalanced backtick example\n"
        "```\n\n"
        "New field `zac.brpApi.logLevel`, defaults to `OFF`.\n"
    )
    assert libupgradedoc.missing_key_change_lines(text, {"zac"}, baseline_values, values) == []


def test_missing_key_change_lines_never_reports_a_line_already_present_verbatim(libupgradedoc):
    """A second, independent backstop alongside the "mentioned" check
    above: a generated line whose exact text is already in the doc is
    never re-added, regardless of whether "mentioned" itself would also
    have caught it."""
    baseline_values = {"zac": {"brpApi": {}}}
    values = {"zac": {"brpApi": {"logLevel": "OFF"}}}
    text = "- Key `zac.brpApi.logLevel` was added.\n"
    assert libupgradedoc.missing_key_change_lines(text, {"zac"}, baseline_values, values) == []


# --- values_key_order ---

def test_values_key_order_returns_top_level_keys_in_file_order(libupgradedoc):
    values = {"zac": {}, "openzaak": {}, "openinwoner": {}}
    assert libupgradedoc.values_key_order(values) == ["zac", "openzaak", "openinwoner"]


def test_values_key_order_non_dict_returns_empty(libupgradedoc):
    assert libupgradedoc.values_key_order(None) == []


# --- component_order_key ---

DEPS = [
    {"name": "openzaak", "version": "1.14.2"},
    {"name": "openinwoner", "version": "2.4.0"},
    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
]
KEY_ORDER = ["openzaak", "zac", "openinwoner"]


def test_component_order_key_matches_by_alias(libupgradedoc):
    assert libupgradedoc.component_order_key("ZAC", DEPS, KEY_ORDER) == (1, 0)


def test_component_order_key_matches_free_form_name(libupgradedoc):
    assert libupgradedoc.component_order_key("Open Zaak", DEPS, KEY_ORDER) == (0, 0)


def test_component_order_key_unmatched_name_sorts_after_every_real_component(libupgradedoc):
    assert libupgradedoc.component_order_key("nginx-unprivileged (shared sidecar)", DEPS, KEY_ORDER) \
        == (len(KEY_ORDER), 0)


def test_component_order_key_matched_dep_not_in_key_order_sorts_last(libupgradedoc):
    """A dependency that resolves fine but isn't a top-level values.yaml key
    at all (e.g. removed from values.yaml but still in Chart.yaml) can't be
    placed meaningfully -- falls back to the same "sorts last" sentinel as
    an unmatched name."""
    deps = [{"name": "totallyabsent", "version": "1.0.0"}]
    assert libupgradedoc.component_order_key("TotallyAbsent", deps, KEY_ORDER) == (len(KEY_ORDER), 0)


def test_component_order_key_sidecar_sorts_after_its_own_parent_row(libupgradedoc):
    """A canonical sidecar name ("<parent> - <basename>") always resolves
    to the SAME values_key_index as its owning dependency's own row via
    match_dependency's fuzzy word-containment — the " - " secondary bit
    is what keeps the sidecar from sorting before (or, without any
    tie-break, merely wherever it already happened to be — Python's sort
    is stable) its own parent."""
    assert libupgradedoc.component_order_key("redis-operator", DEPS + [
        {"name": "redis-operator", "version": "0.26.0"}], KEY_ORDER + ["redis-operator"]) == (3, 0)
    assert libupgradedoc.component_order_key("redis-operator - redis", DEPS + [
        {"name": "redis-operator", "version": "0.26.0"}], KEY_ORDER + ["redis-operator"]) == (3, 1)


# --- find_out_of_order_names ---

def test_find_out_of_order_names_correctly_ordered_is_empty(libupgradedoc):
    names = ["Open Zaak", "ZAC", "Open Inwoner"]
    assert libupgradedoc.find_out_of_order_names(names, DEPS, KEY_ORDER) == []


def test_find_out_of_order_names_flags_a_swapped_pair(libupgradedoc):
    names = ["ZAC", "Open Zaak", "Open Inwoner"]
    assert libupgradedoc.find_out_of_order_names(names, DEPS, KEY_ORDER) == [("ZAC", "Open Zaak")]


def test_find_out_of_order_names_two_unmatched_names_never_conflict(libupgradedoc):
    names = ["Some Shared Sidecar", "Another Shared Thing"]
    assert libupgradedoc.find_out_of_order_names(names, DEPS, KEY_ORDER) == []


def test_find_out_of_order_names_unmatched_before_a_real_component_is_flagged(libupgradedoc):
    """An unmatched row/heading sorts after every real component -- one
    appearing BEFORE a real component earlier in values.yaml's own order is
    still a genuine violation."""
    names = ["Some Shared Sidecar", "Open Zaak"]
    assert libupgradedoc.find_out_of_order_names(names, DEPS, KEY_ORDER) == [("Some Shared Sidecar", "Open Zaak")]


# --- insertion_index ---

def test_insertion_index_middle(libupgradedoc):
    assert libupgradedoc.insertion_index(1, [0, 2, 3]) == 1


def test_insertion_index_start(libupgradedoc):
    assert libupgradedoc.insertion_index(-1, [0, 2, 3]) == 0


def test_insertion_index_end(libupgradedoc):
    assert libupgradedoc.insertion_index(5, [0, 2, 3]) == 3


def test_insertion_index_empty_existing(libupgradedoc):
    assert libupgradedoc.insertion_index(0, []) == 0


def test_insertion_index_real_component_goes_before_unmatched_ones(libupgradedoc):
    """A genuinely new, resolvable component (a real, early key) inserted
    where every existing item is an unmatched/sentinel-keyed row belongs
    BEFORE all of them -- matches how a real component is expected to sort
    ahead of a generic/unmatched summary row."""
    assert libupgradedoc.insertion_index(0, [3, 3, 3]) == 0


def test_insertion_index_new_unmatched_item_among_unmatched_ones_goes_last(libupgradedoc):
    """A new item that itself carries the sentinel key (unmatched) is never
    inserted ahead of other unmatched items without evidence it belongs
    there -- it goes after all of them, preserving their relative order."""
    assert libupgradedoc.insertion_index(3, [3, 3, 3]) == 3


# --- parse_upgrade_doc_changes_blocks ---

def test_parse_upgrade_doc_changes_blocks_basic(libupgradedoc):
    text = (
        "# Title\n\n"
        "## Changes\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "Some prose.\n\n"
        "### Open Inwoner 2.3.1 → 2.4.2\n\n"
        "More prose.\n"
    )
    blocks = libupgradedoc.parse_upgrade_doc_changes_blocks(text)
    assert [b["heading"] for b in blocks] == ["Open Zaak 1.27.3 → 1.27.4", "Open Inwoner 2.3.1 → 2.4.2"]


def test_parse_upgrade_doc_changes_blocks_h4_subheading_is_not_a_separate_block(libupgradedoc):
    text = (
        "## Changes\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "#### Action required\n\n"
        "No action required.\n"
    )
    blocks = libupgradedoc.parse_upgrade_doc_changes_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["heading"] == "Open Zaak 1.27.3 → 1.27.4"


def test_parse_upgrade_doc_changes_blocks_no_changes_section_is_empty(libupgradedoc):
    assert libupgradedoc.parse_upgrade_doc_changes_blocks("# Title\n\nJust prose.\n") == []


def test_parse_upgrade_doc_changes_blocks_stops_at_next_h2(libupgradedoc):
    text = (
        "## Changes\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "Some prose.\n\n"
        "## Per-environment checklist\n\n"
        "### A. Prepare\n\n"
        "- [ ] Do the thing.\n"
    )
    blocks = libupgradedoc.parse_upgrade_doc_changes_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["heading"] == "Open Zaak 1.27.3 → 1.27.4"


# --- sort_upgrade_doc_rows ---

COMPONENT_VERSIONS_HEADING = "## Component versions (4.9.0 vs 4.8.5)\n\n"


def test_sort_upgrade_doc_rows_reorders_out_of_order_rows(libupgradedoc):
    text = (
        COMPONENT_VERSIONS_HEADING +
        "| Component | App version | Helm chart |\n"
        "| --- | --- | --- |\n"
        "| Open Inwoner | 2.4.2 | 2.4.0 |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 |\n"
    )
    new_text, moved = libupgradedoc.sort_upgrade_doc_rows(text, DEPS, {"openzaak": {}, "zac": {}, "openinwoner": {}})
    assert moved == [("Open Zaak", 2, 1), ("Open Inwoner", 1, 2)]
    lines = new_text.splitlines()
    assert lines[4].startswith("| Open Zaak")
    assert lines[5].startswith("| Open Inwoner")


def test_sort_upgrade_doc_rows_already_in_order_is_unchanged(libupgradedoc):
    text = (
        COMPONENT_VERSIONS_HEADING +
        "| Component | App version | Helm chart |\n"
        "| --- | --- | --- |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 |\n"
        "| Open Inwoner | 2.4.2 | 2.4.0 |\n"
    )
    values = {"openzaak": {}, "zac": {}, "openinwoner": {}}
    new_text, moved = libupgradedoc.sort_upgrade_doc_rows(text, DEPS, values)
    assert moved == []
    assert new_text == text


def test_sort_upgrade_doc_rows_fewer_than_two_rows_is_unchanged(libupgradedoc):
    text = (
        COMPONENT_VERSIONS_HEADING +
        "| Component | App version | Helm chart |\n"
        "| --- | --- | --- |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 |\n"
    )
    new_text, moved = libupgradedoc.sort_upgrade_doc_rows(text, DEPS, {"openzaak": {}})
    assert moved == []
    assert new_text == text


def test_sort_upgrade_doc_rows_unmatched_row_stays_last(libupgradedoc):
    text = (
        COMPONENT_VERSIONS_HEADING +
        "| Component | App version | Helm chart |\n"
        "| --- | --- | --- |\n"
        "| nginx-unprivileged (shared sidecar) | 1.31.4 | — |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 |\n"
    )
    values = {"openzaak": {}, "zac": {}, "openinwoner": {}}
    new_text, moved = libupgradedoc.sort_upgrade_doc_rows(text, DEPS, values)
    lines = new_text.splitlines()
    assert lines[4].startswith("| Open Zaak")
    assert lines[5].startswith("| nginx-unprivileged")


# --- sort_changes_blocks ---

def test_sort_changes_blocks_reorders_and_preserves_block_content(libupgradedoc):
    text = (
        "## Changes\n\n"
        "### Open Inwoner 2.3.1 → 2.4.2\n\n"
        "Inwoner details here.\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "Zaak details here.\n"
    )
    values = {"openzaak": {}, "zac": {}, "openinwoner": {}}
    new_text, moved = libupgradedoc.sort_changes_blocks(text, DEPS, values)
    assert moved == [("Open Zaak 1.27.3 → 1.27.4", 2, 1), ("Open Inwoner 2.3.1 → 2.4.2", 1, 2)]
    assert "### Open Zaak 1.27.3 → 1.27.4\n\nZaak details here.\n" in new_text
    assert new_text.index("### Open Zaak") < new_text.index("### Open Inwoner")


def test_sort_changes_blocks_already_in_order_is_unchanged(libupgradedoc):
    text = (
        "## Changes\n\n"
        "### Open Zaak 1.27.3 → 1.27.4\n\n"
        "Zaak details.\n\n"
        "### Open Inwoner 2.3.1 → 2.4.2\n\n"
        "Inwoner details.\n"
    )
    values = {"openzaak": {}, "zac": {}, "openinwoner": {}}
    new_text, moved = libupgradedoc.sort_changes_blocks(text, DEPS, values)
    assert moved == []
    assert new_text == text


def test_sort_changes_blocks_unmatched_block_stays_last_and_later_h2_untouched(libupgradedoc):
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
    new_text, moved = libupgradedoc.sort_changes_blocks(text, DEPS, values)
    assert new_text.index("### Open Zaak") < new_text.index("### Fix: something unrelated")
    assert "## Per-environment checklist\n\n### A. Prepare\n\n- [ ] Do the thing.\n" in new_text


def test_sort_changes_blocks_fewer_than_two_blocks_is_unchanged(libupgradedoc):
    text = "## Changes\n\n### Open Zaak 1.27.3 → 1.27.4\n\nZaak details.\n"
    new_text, moved = libupgradedoc.sort_changes_blocks(text, DEPS, {"openzaak": {}})
    assert moved == []
    assert new_text == text
