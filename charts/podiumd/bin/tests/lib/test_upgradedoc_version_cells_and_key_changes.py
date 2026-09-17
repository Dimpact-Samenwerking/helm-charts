"""lib.upgradedoc -- version-cell rendering, version-spec/pair
replacement, changed-component computation, and key-change
descriptions."""


# --- canonical_version_cell ---


def test_canonical_version_cell_arrow_form(libupgradedocversioncells):
    assert libupgradedocversioncells.canonical_version_cell("5.0.2", "5.1.0") == "5.0.2 → 5.1.0"


def test_canonical_version_cell_unchanged_form(libupgradedocversioncells):
    assert libupgradedocversioncells.canonical_version_cell("1.0.297", "1.0.297") == "1.0.297 (unchanged)"


# --- new_component_version_cell / component_version_cell ---


def test_new_component_version_cell(libupgradedocversioncells):
    assert libupgradedocversioncells.new_component_version_cell("2.15.0") == "2.15.0 (new)"


def test_component_version_cell_with_baseline_delegates_to_canonical(libupgradedocversioncells):
    assert libupgradedocversioncells.component_version_cell("5.0.2", "5.1.0") == "5.0.2 → 5.1.0"
    assert libupgradedocversioncells.component_version_cell("1.0.297", "1.0.297") == "1.0.297 (unchanged)"


def test_component_version_cell_no_baseline_real_version_is_new(libupgradedocversioncells):
    assert libupgradedocversioncells.component_version_cell(None, "2.15.0") == "2.15.0 (new)"


def test_component_version_cell_no_baseline_placeholder_stays_bare(libupgradedocversioncells):
    """The "-" not-applicable placeholder a sidecar row's own Helm-chart
    cell already legitimately uses must never get annotated "(new)" —
    that would misread "no chart version of its own to compare" as
    "brand new"."""
    assert libupgradedocversioncells.component_version_cell(None, "-") == "-"


def test_component_version_cell_no_baseline_no_target_either(libupgradedocversioncells):
    assert libupgradedocversioncells.component_version_cell(None, None) is None


# --- find_preceding_comment_line / replace_version_pair ---


def test_find_preceding_comment_line_finds_arrow_comment(libupgradedoccomments):
    lines = ["# ZAC — 5.0.1 -> 5.1.0\n", "- name: zac\n"]
    assert libupgradedoccomments.find_preceding_comment_line(lines, 1) == 0


def test_find_preceding_comment_line_none_when_no_arrow(libupgradedoccomments):
    lines = ["#repository:\n", "- name: zac\n"]
    assert libupgradedoccomments.find_preceding_comment_line(lines, 1) is None


def test_replace_version_pair_preserves_prefix_and_arrow_style(libupgradedocversioncells):
    assert (
        libupgradedocversioncells.replace_version_pair("# ZAC — 5.0.1 -> 5.1.0\n", "5.0.2", "5.1.0")
        == "# ZAC — 5.0.2 -> 5.1.0\n"
    )
    assert (
        libupgradedocversioncells.replace_version_pair("# ZAC — 5.0.1 → 5.1.0\n", "5.0.2", "5.1.0")
        == "# ZAC — 5.0.2 → 5.1.0\n"
    )


def test_replace_version_pair_no_match_returns_unchanged(libupgradedocversioncells):
    line = "# no version pair here\n"
    assert libupgradedocversioncells.replace_version_pair(line, "1.0.0", "2.0.0") == line


# --- version_change_suffix / image_manifest_version_text ---


def test_version_change_suffix_no_baseline_is_new(libupgradedocversioncells):
    assert libupgradedocversioncells.version_change_suffix(None, "8.10.1") == "(new)"


def test_version_change_suffix_equal_versions_is_unchanged(libupgradedocversioncells):
    assert libupgradedocversioncells.version_change_suffix("1.5.4", "1.5.4") == "(unchanged)"


def test_version_change_suffix_equal_versions_digest_only_change(libupgradedocversioncells):
    assert (
        libupgradedocversioncells.version_change_suffix("1.5.4", "1.5.4", digest_only_change=True) == "(digest changed)"
    )


def test_version_change_suffix_real_transition_is_none(libupgradedocversioncells):
    """None (never a bracketed suffix) when the version genuinely
    differs — the caller renders the transition itself."""
    assert libupgradedocversioncells.version_change_suffix("5.0.2", "5.1.0") is None


def test_image_manifest_version_text_new(libupgradedocversioncells):
    assert libupgradedocversioncells.image_manifest_version_text(None, "0.158.0") == "0.158.0 (new)"


def test_image_manifest_version_text_transition_uses_ascii_arrow(libupgradedocversioncells):
    """Real bug this guards against: images-4.9.1.yaml's own zac otel
    sidecar comment read "0.158.0 -> 0.158.0" (a same-value fake "old"
    fallback masking a genuinely-new image) instead of "0.158.0 (new)"
    — see fix-doc-consistency's own add_missing_images_manifest_
    entries/fix_images_manifest_entries, both migrated onto this exact
    function."""
    assert libupgradedocversioncells.image_manifest_version_text("8.20.0", "8.21.0") == "8.20.0 -> 8.21.0"


def test_image_manifest_version_text_digest_changed(libupgradedocversioncells):
    assert (
        libupgradedocversioncells.image_manifest_version_text("1.5.4", "1.5.4", digest_only_change=True)
        == "1.5.4 (digest changed)"
    )


# --- replace_version_spec ---


def test_replace_version_spec_replaces_arrow_pair(libupgradedocversioncells):
    assert (
        libupgradedocversioncells.replace_version_spec(
            "#   sidecar: zac - opentelemetry-collector-contrib 0.158.0 -> 0.158.0\n", "0.158.0 (new)"
        )
        == "#   sidecar: zac - opentelemetry-collector-contrib 0.158.0 (new)\n"
    )


def test_replace_version_spec_replaces_bracketed_suffix(libupgradedocversioncells):
    assert (
        libupgradedocversioncells.replace_version_spec("# redis 8.0 (new)\n", "8.10.1 (new)")
        == "# redis 8.10.1 (new)\n"
    )


def test_replace_version_spec_preserves_em_dash_prefix(libupgradedocversioncells):
    assert (
        libupgradedocversioncells.replace_version_spec("# ZAC — 5.0.1 -> 5.1.0\n", "5.0.2 -> 5.1.0")
        == "# ZAC — 5.0.2 -> 5.1.0\n"
    )


def test_replace_version_spec_no_match_returns_unchanged(libupgradedocversioncells):
    line = "# no version spec here\n"
    assert libupgradedocversioncells.replace_version_spec(line, "1.0.0 (new)") == line


def test_replace_version_spec_literal_replacement_not_backslash_processed(libupgradedocversioncells):
    """new_spec is substituted as a literal string, never interpreted as
    a regex backreference/escape (re.sub's own replacement-string
    quirk) — matters if a version string ever contained a backslash-
    like sequence."""
    assert (
        libupgradedocversioncells.replace_version_spec("# name 1.0.0 -> 2.0.0\n", r"\1.0.0 (new)")
        == "# name \\1.0.0 (new)\n"
    )


# --- compute_changed_components ---


def test_compute_changed_components_detects_chart_version_bump(libupgradedocmanifestdiff):
    deps = [{"name": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zac", "version": "1.0.251"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, baseline_deps, values, values) == {"zac"}


def test_compute_changed_components_detects_image_tag_change(libupgradedocmanifestdiff):
    deps = [{"name": "zac", "version": "1.0.297"}]
    current = {"zac": {"image": {"tag": "5.4.3@sha256:bbbb"}}}
    baseline = {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, deps, current, baseline) == {"zac"}


def test_compute_changed_components_detects_added_dependency(libupgradedocmanifestdiff):
    deps = [{"name": "zac", "version": "1.0.297"}, {"name": "openformulieren", "version": "1.12.0"}]
    baseline_deps = [{"name": "zac", "version": "1.0.297"}]
    values = {
        "zac": {"image": {"tag": "5.1.0@sha256:aaaa"}},
        "openformulieren": {"image": {"tag": "3.5.6@sha256:cccc"}},
    }
    assert libupgradedocmanifestdiff.compute_changed_components(deps, baseline_deps, values, values) == {
        "openformulieren"
    }


def test_compute_changed_components_detects_removed_dependency(libupgradedocmanifestdiff):
    deps = [{"name": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zac", "version": "1.0.297"}, {"name": "old-component", "version": "1.0.0"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    baseline_values = {
        "zac": {"image": {"tag": "5.1.0@sha256:aaaa"}},
        "old-component": {"image": {"tag": "1.0.0@sha256:dddd"}},
    }
    assert libupgradedocmanifestdiff.compute_changed_components(deps, baseline_deps, values, baseline_values) == {
        "old-component"
    }


def test_compute_changed_components_uses_alias_as_key(libupgradedocmanifestdiff):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, baseline_deps, values, values) == {"zac"}


def test_compute_changed_components_no_change_is_empty(libupgradedocmanifestdiff):
    deps = [{"name": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}, "other": {"a": 1}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, deps, values, values) == set()


def test_compute_changed_components_detects_native_component_image_change(libupgradedocmanifestdiff):
    """frankgateway (see lib.chart.NATIVE_COMPONENTS) has no Chart.yaml
    dependency at all — its own image-tag change must still register as
    changed, or it could never be documented. deps/baseline_deps are
    empty on purpose: this must work with no matching dependency at all,
    real or otherwise."""
    current = {"frankgateway": {"image": {"tag": "104@sha256:bbbb"}}}
    baseline = {"frankgateway": {"image": {"tag": "100@sha256:aaaa"}}}
    assert libupgradedocmanifestdiff.compute_changed_components([], [], current, baseline) == {"frankgateway"}


def test_compute_changed_components_native_component_no_change_is_empty(libupgradedocmanifestdiff):
    values = {"frankgateway": {"image": {"tag": "104@sha256:bbbb"}}}
    assert libupgradedocmanifestdiff.compute_changed_components([], [], values, values) == set()


def test_compute_changed_components_ignores_unrelated_key_changes(libupgradedocmanifestdiff):
    """A values.yaml key change under a component NOT in Chart.yaml's
    dependencies (e.g. a plain feature flag) must not be reported — this
    function is scoped to actual Chart.yaml dependency changes."""
    deps = [{"name": "zac", "version": "1.0.297"}]
    current = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}, "global": {"flag": True}}
    baseline = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}, "global": {"flag": False}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, deps, current, baseline) == set()


def test_compute_changed_components_new_shared_global_sidecar_does_not_flag_every_consumer(libupgradedocmanifestdiff):
    """Regression test: a brand-new "global.images.redis" YAML anchor
    aliased into many unrelated components' own sidecar blocks in the
    same release (real case) must not make EVERY one of those
    components register as "changed" — the shared image is its own
    concern (see lib.image_docs.add_missing_sidecar_rows' own bare-
    basename row), never something specific to a component whose own
    app/chart is otherwise untouched. Before this fix, gaining that one
    shared path alone flagged openzaak/opennotificaties/objecten/... —
    every consumer at once — each getting a spurious, fully
    "(unchanged)" table row added to -upgrade.md."""
    deps = [{"name": "zac", "version": "1.0.297"}, {"name": "openzaak", "version": "1.14.2"}]
    redis_image = {"repository": "redis", "tag": "8.0@sha256:aaaa"}
    current = {
        "global": {"images": {"redis": redis_image}},
        "zac": {"image": {"tag": "5.4.4@sha256:bbbb"}, "redis": {"image": redis_image}},
        "openzaak": {"image": {"tag": "1.29.3@sha256:cccc"}, "redis": {"image": redis_image}},
    }
    baseline = {
        "zac": {"image": {"tag": "5.4.4@sha256:bbbb"}},
        "openzaak": {"image": {"tag": "1.29.3@sha256:cccc"}},
    }
    assert libupgradedocmanifestdiff.compute_changed_components(deps, deps, current, baseline) == set()


def test_compute_changed_components_still_detects_a_components_own_change_alongside_a_shared_sidecar(
    libupgradedocmanifestdiff,
):
    """The shared-image exclusion only ever removes THAT one path from
    the comparison — a component's own, genuinely different image still
    registers as changed even when it ALSO happens to gain the same
    shared sidecar in the same hop."""
    deps = [{"name": "zac", "version": "1.0.297"}]
    redis_image = {"repository": "redis", "tag": "8.0@sha256:aaaa"}
    current = {
        "global": {"images": {"redis": redis_image}},
        "zac": {"image": {"tag": "5.4.4@sha256:bbbb"}, "redis": {"image": redis_image}},
    }
    baseline = {"zac": {"image": {"tag": "5.0.2@sha256:dddd"}}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, deps, current, baseline) == {"zac"}


# --- describe_key_changes / append_to_doc ---


def test_describe_key_changes_reports_added_removed_renamed(libupgradedocversioncells):
    baseline = {"sftp": {"host": "x", "user": "y", "password": "z"}, "old": 1}
    current = {"transfer": {"mode": "sftp-password", "host": "x", "user": "y", "password": "z"}, "new": 2}
    lines = libupgradedocversioncells.describe_key_changes("mi", baseline, current)
    joined = "".join(lines)
    assert "- Key `mi.sftp` was renamed to `mi.transfer`.\n" in joined
    assert "- Key `mi.old` was removed.\n" in joined
    assert "- Key `mi.new` was added.\n" in joined


def test_describe_key_changes_empty_when_nothing_changed(libupgradedocversioncells):
    assert libupgradedocversioncells.describe_key_changes("comp", {"a": 1}, {"a": 1}) == []


def test_append_to_doc_adds_blank_line_separator(libupgradedocversioncells):
    text = "# Values deltas\n\nSome existing content.\n"
    result = libupgradedocversioncells.append_to_doc(text, ["- new bullet\n"])
    assert result == "# Values deltas\n\nSome existing content.\n\n- new bullet\n"


def test_append_to_doc_no_new_lines_returns_unchanged(libupgradedocversioncells):
    text = "# Values deltas\n\nSome existing content.\n"
    assert libupgradedocversioncells.append_to_doc(text, []) == text


# --- missing_key_change_lines_by_key ---


def test_missing_key_change_lines_by_key_reports_unmentioned_addition(libupgradedocversioncells):
    baseline_values = {"zac": {"brpApi": {}}}
    values = {"zac": {"brpApi": {"logLevel": "OFF"}}}
    text = "Nothing relevant mentioned.\n"
    by_key = libupgradedocversioncells.missing_key_change_lines_by_key(text, {"zac"}, baseline_values, values)
    assert by_key == {"zac": ["- Key `zac.brpApi.logLevel` was added.\n"]}


def test_missing_key_change_lines_by_key_skips_already_mentioned_addition(libupgradedocversioncells):
    baseline_values = {"zac": {"brpApi": {}}}
    values = {"zac": {"brpApi": {"logLevel": "OFF"}}}
    text = "New field `zac.brpApi.logLevel`, defaults to `OFF`.\n"
    assert libupgradedocversioncells.missing_key_change_lines_by_key(text, {"zac"}, baseline_values, values) == {}


def test_missing_key_change_lines_by_key_rename_needs_both_sides_mentioned(libupgradedocversioncells):
    baseline_values = {"mi": {"sftp": {"host": "x", "user": "y", "password": "z"}}}
    values = {"mi": {"transfer": {"mode": "sftp-password", "host": "x", "user": "y", "password": "z"}}}
    # only the OLD side is mentioned — the rename isn't fully documented
    text = "Removed `mi.sftp` in favor of something else.\n"
    by_key = libupgradedocversioncells.missing_key_change_lines_by_key(text, {"mi"}, baseline_values, values)
    assert by_key == {"mi": ["- Key `mi.sftp` was renamed to `mi.transfer`.\n"]}


def test_missing_key_change_lines_by_key_ignores_unrelated_component(libupgradedocversioncells):
    baseline_values = {"zac": {"a": 1}, "unrelated": {"a": 1}}
    values = {"zac": {"a": 1}, "unrelated": {"b": 2}}
    # "unrelated" isn't in changed_component_keys, so its diff must be ignored
    assert (
        libupgradedocversioncells.missing_key_change_lines_by_key("no mentions", {"zac"}, baseline_values, values) == {}
    )


def test_missing_key_change_lines_by_key_empty_when_nothing_changed(libupgradedocversioncells):
    values = {"zac": {"a": 1}}
    assert libupgradedocversioncells.missing_key_change_lines_by_key("", {"zac"}, values, values) == {}


def test_missing_key_change_lines_by_key_ignores_mention_inside_fenced_code_block(libupgradedocversioncells):
    """A key mentioned only inside an unrelated fenced code block (an odd
    number of backticks there desyncs regex pairing for the rest of the
    doc) must not be treated as "already mentioned" for a real bullet —
    see strip_fenced_code_blocks. Real-world case: a values-deltas.md
    with 5 fenced snippets caused this to silently re-add nearly its
    entire existing bullet list as "missing"."""
    baseline_values = {"zac": {"brpApi": {}}}
    values = {"zac": {"brpApi": {"logLevel": "OFF"}}}
    text = "```yaml\nsome: `unbalanced backtick example\n```\n\nNew field `zac.brpApi.logLevel`, defaults to `OFF`.\n"
    assert libupgradedocversioncells.missing_key_change_lines_by_key(text, {"zac"}, baseline_values, values) == {}


def test_missing_key_change_lines_by_key_never_reports_a_line_already_present_verbatim(libupgradedocversioncells):
    """A second, independent backstop alongside the "mentioned" check
    above: a generated line whose exact text is already in the doc is
    never re-added, regardless of whether "mentioned" itself would also
    have caught it."""
    baseline_values = {"zac": {"brpApi": {}}}
    values = {"zac": {"brpApi": {"logLevel": "OFF"}}}
    text = "- Key `zac.brpApi.logLevel` was added.\n"
    assert libupgradedocversioncells.missing_key_change_lines_by_key(text, {"zac"}, baseline_values, values) == {}


def test_missing_key_change_lines_by_key_generic_backtick_word_elsewhere_is_not_a_match(libupgradedocversioncells):
    """Real bug this guards against: ordinary prose using a short, generic
    word in backticks elsewhere in the doc (describing a general
    convention, not any one specific key) must never be mistaken for a
    mention of an unrelated key path that merely CONTAINS that word as
    its own trailing segment — "mentioned" used to be a substring check
    either direction, so a sentence like "environments override
    `registry`/`repository` ... but never `tag`" silently marked EVERY
    key path containing "repository" as already covered, dropping real
    additions with no trace (confirmed live: objecten.image.repository,
    keycloak-operator.operator.image.tag, and 8 other real, distinct
    key changes across the actual 4.9.0 upgrade all vanished this way)."""
    baseline_values = {"objecten": {"image": {}}}
    values = {"objecten": {"image": {"repository": "ghcr.io/maykinmedia/objects-api"}}}
    text = "Every environment checked overrides `registry`/`repository` for these images but never `tag`.\n"
    by_key = libupgradedocversioncells.missing_key_change_lines_by_key(text, {"objecten"}, baseline_values, values)
    assert by_key == {"objecten": ["- Key `objecten.image.repository` was added.\n"]}


def test_missing_key_change_lines_by_key_bare_leaf_mention_is_not_enough(libupgradedocversioncells):
    """The flip side of the fix above: a key's own bare trailing segment,
    mentioned in prose WITHOUT its full dotted prefix, is the exact same
    string shape as the bug case (an existing short span that's a
    substring of the full path) — there's no mechanical way to tell
    them apart, so this is now, deliberately, also reported as missing
    rather than silently trusted. The safe direction to err in: an
    occasional harmless duplicate bullet beats a real omission with no
    trace."""
    baseline_values = {"ita": {}}
    values = {"ita": {"verlopenContactverzoekHerinneringNotificatie": {"schedule": "0 7 * * 1-5"}}}
    text = "The new `verlopenContactverzoekHerinneringNotificatie` CronJob is enabled by default.\n"
    by_key = libupgradedocversioncells.missing_key_change_lines_by_key(text, {"ita"}, baseline_values, values)
    assert by_key == {"ita": ["- Key `ita.verlopenContactverzoekHerinneringNotificatie` was added.\n"]}
