"""lib.upgradedoc -- version cells, version-spec replacement, changed components, key-change text."""

from types import ModuleType

# --- canonical_version_cell ---


def test_canonical_version_cell_arrow_form(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.canonical_version_cell("5.0.2", "5.1.0") == "5.0.2 → 5.1.0"


def test_canonical_version_cell_unchanged_form(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.canonical_version_cell("1.0.297", "1.0.297") == "1.0.297 (unchanged)"


# --- new_component_version_cell / component_version_cell ---


def test_new_component_version_cell(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.new_component_version_cell("2.15.0") == "2.15.0 (new)"


def test_component_version_cell_without_target_is_none(libupgradedocversioncells: ModuleType):
    """Regression: no new version rendered as "<old> → None"."""
    assert libupgradedocversioncells.component_version_cell("5.0.2", None) is None
    assert libupgradedocversioncells.component_version_cell(None, None) is None


def test_component_version_cell_with_baseline_delegates_to_canonical(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.component_version_cell("5.0.2", "5.1.0") == "5.0.2 → 5.1.0"
    assert libupgradedocversioncells.component_version_cell("1.0.297", "1.0.297") == "1.0.297 (unchanged)"


def test_component_version_cell_no_baseline_real_version_is_new(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.component_version_cell(None, "2.15.0") == "2.15.0 (new)"


def test_component_version_cell_no_baseline_placeholder_stays_bare(libupgradedocversioncells: ModuleType):
    """The "-" not-applicable placeholder is never annotated "(new)"."""
    assert libupgradedocversioncells.component_version_cell(None, "-") == "-"


def test_component_version_cell_no_baseline_no_target_either(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.component_version_cell(None, None) is None


# --- find_preceding_comment_line ---


def test_find_preceding_comment_line_finds_arrow_comment(libupgradedoccomments: ModuleType):
    lines = ["# ZAC — 5.0.1 -> 5.1.0\n", "- name: zac\n"]
    assert libupgradedoccomments.find_preceding_comment_line(lines, 1) == 0


def test_find_preceding_comment_line_none_when_no_arrow(libupgradedoccomments: ModuleType):
    lines = ["#repository:\n", "- name: zac\n"]
    assert libupgradedoccomments.find_preceding_comment_line(lines, 1) is None


# --- version_change_suffix / image_manifest_version_text ---


def test_version_change_suffix_no_baseline_is_new(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.version_change_suffix(None, "8.10.1") == "(new)"


def test_version_change_suffix_equal_versions_is_unchanged(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.version_change_suffix("1.5.4", "1.5.4") == "(unchanged)"


def test_version_change_suffix_equal_versions_digest_only_change(libupgradedocversioncells: ModuleType):
    assert (
        libupgradedocversioncells.version_change_suffix("1.5.4", "1.5.4", digest_only_change=True) == "(digest changed)"
    )


def test_version_change_suffix_real_transition_is_none(libupgradedocversioncells: ModuleType):
    """A real transition returns None; the caller renders it."""
    assert libupgradedocversioncells.version_change_suffix("5.0.2", "5.1.0") is None


def test_image_manifest_version_text_new(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.image_manifest_version_text(None, "0.158.0") == "0.158.0 (new)"


def test_image_manifest_version_text_transition_uses_ascii_arrow(libupgradedocversioncells: ModuleType):
    """Regression: a new image rendered as "X -> X" instead of "X (new)"."""
    assert libupgradedocversioncells.image_manifest_version_text("8.20.0", "8.21.0") == "8.20.0 -> 8.21.0"


def test_image_manifest_version_text_digest_changed(libupgradedocversioncells: ModuleType):
    assert (
        libupgradedocversioncells.image_manifest_version_text("1.5.4", "1.5.4", digest_only_change=True)
        == "1.5.4 (digest changed)"
    )


# --- replace_version_spec ---


def test_replace_version_spec_replaces_arrow_pair(libupgradedocversioncells: ModuleType):
    assert (
        libupgradedocversioncells.replace_version_spec(
            "#   sidecar: zac - opentelemetry-collector-contrib 0.158.0 -> 0.158.0\n", "0.158.0 (new)"
        )
        == "#   sidecar: zac - opentelemetry-collector-contrib 0.158.0 (new)\n"
    )


def test_replace_version_spec_replaces_bracketed_suffix(libupgradedocversioncells: ModuleType):
    assert (
        libupgradedocversioncells.replace_version_spec("# redis 8.0 (new)\n", "8.10.1 (new)")
        == "# redis 8.10.1 (new)\n"
    )


def test_replace_version_spec_preserves_em_dash_prefix(libupgradedocversioncells: ModuleType):
    assert (
        libupgradedocversioncells.replace_version_spec("# ZAC — 5.0.1 -> 5.1.0\n", "5.0.2 -> 5.1.0")
        == "# ZAC — 5.0.2 -> 5.1.0\n"
    )


def test_replace_version_spec_no_match_returns_unchanged(libupgradedocversioncells: ModuleType):
    line = "# no version spec here\n"
    assert libupgradedocversioncells.replace_version_spec(line, "1.0.0 (new)") == line


def test_replace_version_spec_literal_replacement_not_backslash_processed(libupgradedocversioncells: ModuleType):
    """new_spec is inserted literally, not as an re.sub replacement pattern."""
    assert (
        libupgradedocversioncells.replace_version_spec("# name 1.0.0 -> 2.0.0\n", r"\1.0.0 (new)")
        == "# name \\1.0.0 (new)\n"
    )


# --- compute_changed_components ---


def test_compute_changed_components_detects_chart_version_bump(libupgradedocmanifestdiff: ModuleType):
    deps = [{"name": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zac", "version": "1.0.251"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, baseline_deps, values, values) == {"zac"}


def test_compute_changed_components_detects_image_tag_change(libupgradedocmanifestdiff: ModuleType):
    deps = [{"name": "zac", "version": "1.0.297"}]
    current = {"zac": {"image": {"tag": "5.4.3@sha256:bbbb"}}}
    baseline = {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, deps, current, baseline) == {"zac"}


def test_compute_changed_components_detects_added_dependency(libupgradedocmanifestdiff: ModuleType):
    deps = [{"name": "zac", "version": "1.0.297"}, {"name": "openformulieren", "version": "1.12.0"}]
    baseline_deps = [{"name": "zac", "version": "1.0.297"}]
    values = {
        "zac": {"image": {"tag": "5.1.0@sha256:aaaa"}},
        "openformulieren": {"image": {"tag": "3.5.6@sha256:cccc"}},
    }
    assert libupgradedocmanifestdiff.compute_changed_components(deps, baseline_deps, values, values) == {
        "openformulieren"
    }


def test_compute_changed_components_detects_removed_dependency(libupgradedocmanifestdiff: ModuleType):
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


def test_compute_changed_components_uses_alias_as_key(libupgradedocmanifestdiff: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, baseline_deps, values, values) == {"zac"}


def test_compute_changed_components_no_change_is_empty(libupgradedocmanifestdiff: ModuleType):
    deps = [{"name": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}, "other": {"a": 1}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, deps, values, values) == set()


def test_compute_changed_components_detects_native_component_image_change(libupgradedocmanifestdiff: ModuleType):
    """A native component's image change counts without any Chart.yaml dependency."""
    current = {"frankgateway": {"image": {"tag": "104@sha256:bbbb"}}}
    baseline = {"frankgateway": {"image": {"tag": "100@sha256:aaaa"}}}
    assert libupgradedocmanifestdiff.compute_changed_components([], [], current, baseline) == {"frankgateway"}


def test_compute_changed_components_native_component_no_change_is_empty(libupgradedocmanifestdiff: ModuleType):
    values = {"frankgateway": {"image": {"tag": "104@sha256:bbbb"}}}
    assert libupgradedocmanifestdiff.compute_changed_components([], [], values, values) == set()


def test_compute_changed_components_ignores_unrelated_key_changes(libupgradedocmanifestdiff: ModuleType):
    """Key changes under non-dependency keys are not reported."""
    deps = [{"name": "zac", "version": "1.0.297"}]
    current = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}, "global": {"flag": True}}
    baseline = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}, "global": {"flag": False}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, deps, current, baseline) == set()


def test_compute_changed_components_new_shared_global_sidecar_does_not_flag_every_consumer(
    libupgradedocmanifestdiff: ModuleType,
):
    """A new shared global image aliased into many components doesn't flag each of them as changed.

    The shared image gets its own row; flagging consumers added spurious "(unchanged)" rows.
    """
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
    libupgradedocmanifestdiff: ModuleType,
):
    """Excluding the shared path still detects a component's own image change."""
    deps = [{"name": "zac", "version": "1.0.297"}]
    redis_image = {"repository": "redis", "tag": "8.0@sha256:aaaa"}
    current = {
        "global": {"images": {"redis": redis_image}},
        "zac": {"image": {"tag": "5.4.4@sha256:bbbb"}, "redis": {"image": redis_image}},
    }
    baseline = {"zac": {"image": {"tag": "5.0.2@sha256:dddd"}}}
    assert libupgradedocmanifestdiff.compute_changed_components(deps, deps, current, baseline) == {"zac"}


# --- chart_version_suffix ---


def test_chart_version_suffix_changed(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.chart_version_suffix("0.28.4", "0.29.6") == " (chart 0.28.4 → 0.29.6)"


def test_chart_version_suffix_unchanged(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.chart_version_suffix("1.0.0", "1.0.0") == " (chart 1.0.0, unchanged)"


def test_chart_version_suffix_new_without_old_chart(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.chart_version_suffix(None, "3.5.0") == " (chart 3.5.0, new)"


def test_chart_version_suffix_native_component_is_empty(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.chart_version_suffix("-", "-") == ""


# --- describe_key_changes / append_to_doc ---


def test_describe_key_changes_reports_added_removed_renamed(libupgradedocversioncells: ModuleType):
    baseline = {"sftp": {"host": "x", "user": "y", "password": "z"}, "old": 1}
    current = {"transfer": {"mode": "sftp-password", "host": "x", "user": "y", "password": "z"}, "new": 2}
    lines = libupgradedocversioncells.describe_key_changes("mi", baseline, current)
    joined = "".join(lines)
    assert "- Key `mi.sftp` was renamed to `mi.transfer`.\n" in joined
    assert "- Key `mi.old` was removed.\n" in joined
    assert "- Key `mi.new` was added.\n" in joined


def test_describe_key_changes_empty_when_nothing_changed(libupgradedocversioncells: ModuleType):
    assert libupgradedocversioncells.describe_key_changes("comp", {"a": 1}, {"a": 1}) == []


def test_append_to_doc_adds_blank_line_separator(libupgradedocversioncells: ModuleType):
    text = "# Values deltas\n\nSome existing content.\n"
    result = libupgradedocversioncells.append_to_doc(text, ["- new bullet\n"])
    assert result == "# Values deltas\n\nSome existing content.\n\n- new bullet\n"


def test_append_to_doc_no_new_lines_returns_unchanged(libupgradedocversioncells: ModuleType):
    text = "# Values deltas\n\nSome existing content.\n"
    assert libupgradedocversioncells.append_to_doc(text, []) == text


# --- key_change_lines / missing_key_change_lines ---


def test_key_change_lines_diffs_the_component_subtree(libupgradedocversioncells: ModuleType):
    baseline_values = {"zac": {"brpApi": {}}, "unrelated": {"a": 1}}
    values = {"zac": {"brpApi": {"logLevel": "OFF"}}, "unrelated": {"b": 2}}
    assert libupgradedocversioncells.key_change_lines("zac", baseline_values, values) == [
        "- Key `zac.brpApi.logLevel` was added.\n"
    ]


def test_key_change_lines_missing_baseline_subtree_counts_as_empty(libupgradedocversioncells: ModuleType):
    values = {"eck-operator": {"image": {"tag": "3.5.0"}}}
    assert libupgradedocversioncells.key_change_lines("eck-operator", None, values) == [
        "- Key `eck-operator.image` was added.\n"
    ]


def test_missing_key_change_lines_skips_line_present_verbatim(libupgradedocversioncells: ModuleType):
    lines = ["- Key `zac.brpApi.logLevel` was added.\n", "- Key `zac.old` was removed.\n"]
    text = "## zac 1.0 → 1.1\n\n- Key `zac.brpApi.logLevel` was added.\n"
    assert libupgradedocversioncells.missing_key_change_lines(text, lines) == ["- Key `zac.old` was removed.\n"]


def test_missing_key_change_lines_line_inside_a_fenced_code_block_does_not_count(
    libupgradedocversioncells: ModuleType,
):
    lines = ["- Key `zac.brpApi.logLevel` was added.\n"]
    text = "## zac 1.0 → 1.1\n\n```markdown\n- Key `zac.brpApi.logLevel` was added.\n```\n"
    assert libupgradedocversioncells.missing_key_change_lines(text, lines) == lines


def test_missing_key_change_lines_prose_mention_does_not_count(libupgradedocversioncells: ModuleType):
    """A key named in user prose still needs its generated line, so every section has the same format."""
    lines = ["- Key `zac.brpApi.logLevel` was added.\n"]
    text = "New field `zac.brpApi.logLevel`, defaults to `OFF`.\n"
    assert libupgradedocversioncells.missing_key_change_lines(text, lines) == lines


def test_missing_key_change_lines_user_extended_line_does_not_count(libupgradedocversioncells: ModuleType):
    lines = ["- Key `zac.foo` was added.\n"]
    text = "- Key `zac.foo` was added (`foo.bar`, `foo.baz`).\n"
    assert libupgradedocversioncells.missing_key_change_lines(text, lines) == lines
