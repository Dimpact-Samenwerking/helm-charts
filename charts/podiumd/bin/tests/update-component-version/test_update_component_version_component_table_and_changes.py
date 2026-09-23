"""find_component_row / update_component_table and make_changes_section /
insert_changes_section: split out of the former, monolithic
test_update_component_version.py for pylint's too-many-lines check. This
cluster doesn't use the git/subprocess helpers from the main()-integration
files — just its own local DEPS/VALUES/COMPONENT_VERSIONS_HEADING
constants."""

from types import ModuleType

# --- find_component_row / update_component_table ---


def test_find_component_row_matches_by_substring(libcomponentdocschanges: ModuleType):
    rows = [{"name": "ZAC (Zaakafhandelcomponent)", "line_index": 0}]
    assert libcomponentdocschanges.find_component_row(rows, "zac")["line_index"] == 0


def test_find_component_row_no_match_returns_none(libcomponentdocschanges: ModuleType):
    rows = [{"name": "ZAC (Zaakafhandelcomponent)", "line_index": 0}]
    assert libcomponentdocschanges.find_component_row(rows, "openformulieren") is None


def test_find_component_row_plain_name_does_not_match_its_own_sidecar_rows(libcomponentdocschanges: ModuleType):
    """Regression test: a canonical "<key> - <basename>" sidecar row
    (e.g. "openbao - openbao-csi-provider") legitimately starts with its
    owning dependency's own name as a leading word-aligned span — that
    must never satisfy a lookup for the dependency's OWN plain-name
    friendly ("openbao"), same class of collision lib.upgradedoc.
    match_dependency_excluding_sidecar_names already guards against on
    the read side. Real bug: update_component_table silently overwrote
    the "openbao - openbao-csi-provider" row with openbao's OWN
    chart/app values instead of inserting openbao's own new row, because
    this lookup used to return that sidecar row as a false match."""
    rows = [
        {"name": "openbao - openbao-csi-provider", "line_index": 0},
        {"name": "openbao - openbao-snapshot-agent", "line_index": 1},
    ]
    assert libcomponentdocschanges.find_component_row(rows, "openbao") is None


def test_find_component_row_sidecar_name_still_matches_its_own_row(libcomponentdocschanges: ModuleType):
    """The exact-whole-name exception in the fix above: a lookup for the
    sidecar's own full canonical name must still find its own row."""
    rows = [{"name": "openbao - openbao-csi-provider", "line_index": 0}]
    assert libcomponentdocschanges.find_component_row(rows, "openbao - openbao-csi-provider")["line_index"] == 0


DEPS = [
    {"name": "openformulieren", "version": "1.12.0"},
    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
]
VALUES = {"openformulieren": {}, "zac": {}}


COMPONENT_VERSIONS_HEADING = "## Component versions (4.9.0 vs 4.8.5)\n\n"


def test_update_component_table_adds_new_row(libcomponentdocschanges: ModuleType):
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | - |\n"
    )
    new_text, action = libcomponentdocschanges.update_component_table(
        text,
        "openformulieren",
        libcomponentdocschanges.VersionChange("3.4.10", "3.5.6", "1.12.0", "1.12.0"),
        libcomponentdocschanges.OrderingContext(DEPS, VALUES),
    )
    assert action == "added"
    assert "| openformulieren | 3.4.10 → 3.5.6 | 1.12.0 (unchanged) | - |" in new_text
    assert "| zac | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | - |" in new_text  # untouched


def test_update_component_table_new_row_not_absorbed_by_own_sidecar_rows(libcomponentdocschanges: ModuleType):
    """Regression test (real bug, real doc): when a dependency's own row
    doesn't exist yet but its sidecar rows already do (e.g. openbao,
    whose "openbao - openbao-csi-provider"/"...-snapshot-agent"/"...-
    vault-k8s" rows were added a prior run, before openbao's own app
    version became independently resolvable), inserting the dependency's
    own new row must never overwrite one of those sidecar rows instead —
    each keeps its own values, and the dependency gets its own new row."""
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openbao - openbao-csi-provider | 2.0.2 (new) | - | - |\n"
        "| openbao - openbao-snapshot-agent | 0.3.0 (new) | - | - |\n"
    )
    new_text, action = libcomponentdocschanges.update_component_table(
        text,
        "openbao",
        libcomponentdocschanges.VersionChange(None, "v2.5.5", "0.28.4", "0.28.4"),
        libcomponentdocschanges.OrderingContext(DEPS, VALUES),
    )
    assert action == "added"
    assert "| openbao | v2.5.5 (new) | 0.28.4 (unchanged) | - |" in new_text
    assert "| openbao - openbao-csi-provider | 2.0.2 (new) | - | - |" in new_text  # untouched
    assert "| openbao - openbao-snapshot-agent | 0.3.0 (new) | - | - |" in new_text  # untouched


def test_update_component_table_new_row_inserted_in_values_yaml_order(libcomponentdocschanges: ModuleType):
    """openformulieren comes BEFORE zac in VALUES's own top-level key
    order -- the new row must land above the existing zac row, not always
    appended at the end."""
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | - |\n"
    )
    new_text, action = libcomponentdocschanges.update_component_table(
        text,
        "openformulieren",
        libcomponentdocschanges.VersionChange("3.4.10", "3.5.6", "1.12.0", "1.12.0"),
        libcomponentdocschanges.OrderingContext(DEPS, VALUES),
    )
    assert action == "added"
    lines = [line for line in new_text.splitlines() if line.startswith(("| zac", "| openformulieren"))]
    assert lines == [
        "| openformulieren | 3.4.10 → 3.5.6 | 1.12.0 (unchanged) | - |",
        "| zac | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | - |",
    ]


def test_update_component_table_updates_existing_row(libcomponentdocschanges: ModuleType):
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openformulieren | 3.4.9 → 3.4.10 | 1.12.0 (unchanged) | - |\n"
    )
    new_text, action = libcomponentdocschanges.update_component_table(
        text,
        "openformulieren",
        libcomponentdocschanges.VersionChange("3.4.10", "3.5.6", "1.12.0", "1.12.0"),
        libcomponentdocschanges.OrderingContext([], {}),
    )
    assert action == "updated"
    assert "| openformulieren | 3.4.10 → 3.5.6 | 1.12.0 (unchanged) | - |" in new_text
    assert "3.4.9" not in new_text


def test_update_component_table_no_table_returns_none_action(libcomponentdocschanges: ModuleType):
    text = "# Upgrade guide\n\nJust prose, no table.\n"
    _new_text, action = libcomponentdocschanges.update_component_table(
        text,
        "openformulieren",
        libcomponentdocschanges.VersionChange("3.4.10", "3.5.6", "1.12.0", "1.12.0"),
        libcomponentdocschanges.OrderingContext([], {}),
    )
    assert action is None


def test_update_component_table_new_component_no_baseline_is_annotated_new(libcomponentdocschanges: ModuleType):
    """A brand-new component (no baseline app/chart version at all — the
    old_app/old_chart args are None) gets "(new)" cells, not a bare
    version indistinguishable from a row whose baseline just wasn't
    passed in."""
    text = COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart | Notes |\n| --- | --- | --- | --- |\n"
    new_text, action = libcomponentdocschanges.update_component_table(
        text,
        "openklant",
        libcomponentdocschanges.VersionChange(None, "2.15.0", None, "1.11.0"),
        libcomponentdocschanges.OrderingContext([], {}),
    )
    assert action == "added"
    assert "| openklant | 2.15.0 (new) | 1.11.0 (new) | - |" in new_text


def test_update_component_table_empty_table_ignores_unrelated_lower_pipe_table(libcomponentdocschanges: ModuleType):
    """When the "Component versions" table is empty (header + separator
    only), the new row must be inserted right under THAT separator — not
    under the last "| --- |" in the whole doc, which would splice it into
    an unrelated settings-migration table in a "## Changes" subsection."""
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "\n"
        "## Changes\n\n"
        "### openformulieren 3.4.10 -> 3.5.6\n\n"
        "Settings migration:\n\n"
        "| Old setting | New setting |\n"
        "| --- | --- |\n"
        "| FOO | BAR |\n"
    )
    new_text, action = libcomponentdocschanges.update_component_table(
        text,
        "openformulieren",
        libcomponentdocschanges.VersionChange("3.4.10", "3.5.6", "1.12.0", "1.12.0"),
        libcomponentdocschanges.OrderingContext(DEPS, VALUES),
    )
    assert action == "added"
    lines = new_text.splitlines()
    sep_idx = lines.index("| --- | --- | --- | --- |")
    assert lines[sep_idx + 1] == "| openformulieren | 3.4.10 → 3.5.6 | 1.12.0 (unchanged) | - |"
    assert lines[-3:] == ["| Old setting | New setting |", "| --- | --- |", "| FOO | BAR |"]


def test_update_component_table_new_sidecar_chart_placeholder_stays_bare(libcomponentdocschanges: ModuleType):
    """A sidecar row's own Helm-chart cell is always the literal "-"
    not-applicable placeholder (see add_missing_sidecar_rows) — it must
    never get annotated "(new)" just because old_chart is None too, the
    same way it's never rewritten with a real chart version either."""
    text = COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart | Notes |\n| --- | --- | --- | --- |\n"
    new_text, action = libcomponentdocschanges.update_component_table(
        text,
        "kiss - crawler",
        libcomponentdocschanges.VersionChange(None, "1.0.0", None, "-"),
        libcomponentdocschanges.OrderingContext([], {}),
    )
    assert action == "added"
    assert "| kiss - crawler | 1.0.0 (new) | - | - |" in new_text


# --- make_changes_section / insert_changes_section ---


def test_make_changes_section_includes_bullets(libcomponentdocschanges: ModuleType):
    section = libcomponentdocschanges.make_changes_section(
        libcomponentdocschanges.ComponentIdentity("openformulieren", "openforms", "openformulieren"),
        "4.9.0",
        libcomponentdocschanges.VersionChange("3.4.10", "3.5.6", "1.12.0", "1.12.0"),
        ["image"],
    )
    assert section.startswith("### openformulieren 3.4.10 → 3.5.6 (chart 1.12.0, unchanged)")
    assert "Image tag pin `openformulieren.image.tag` `3.4.10` → `3.5.6`" in section
    assert "Helm chart" not in section  # chart unchanged, no chart bullet
    assert "images-4.9.0.yaml" in section


def test_make_changes_section_unchanged_app_version_renders_no_transition(libcomponentdocschanges: ModuleType):
    """Regression test: old_app == new_app (real case: a component whose
    own PRIMARY image is untouched but still qualifies for a row/
    section because some OTHER path in its subtree changed — e.g. a
    brand-new sidecar of its own) renders "<app> (unchanged)", matching
    chart_suffix's own existing "(chart ..., unchanged)" convention,
    instead of a meaningless "<app> → <app>" self-transition."""
    section = libcomponentdocschanges.make_changes_section(
        libcomponentdocschanges.ComponentIdentity("zac", "zaakafhandelcomponent", "zac"),
        "4.9.0",
        libcomponentdocschanges.VersionChange("5.4.4", "5.4.4", "1.0.297", "1.0.297"),
        ["image"],
    )
    assert section.startswith("### zac 5.4.4 (unchanged) (chart 1.0.297, unchanged)")
    assert "5.4.4 → 5.4.4" not in section
    assert "is unchanged this hop" in section


def test_make_changes_section_old_app_none_renders_new_not_none_arrow(libcomponentdocschanges: ModuleType):
    """Regression test: old_app is None (real case: openbao — its own
    app version only ever resolves via the subchart_app_version
    fallback, which is never attempted for the baseline side) renders
    "<app> (new)", matching component_version_cell's own "(new)"
    convention for exactly this case — never a nonsensical "None →
    <app>", and the chart side (unchanged here) keeps its ordinary
    "(chart ..., unchanged)" clause."""
    section = libcomponentdocschanges.make_changes_section(
        libcomponentdocschanges.ComponentIdentity("openbao", "openbao", "openbao"),
        "4.9.1",
        libcomponentdocschanges.VersionChange(None, "v2.5.5", "0.28.4", "0.28.4"),
        ["server.image"],
    )
    assert section.startswith("### openbao v2.5.5 (new) (chart 0.28.4, unchanged)")
    assert "None" not in section
    assert "introduces **openbao** at app version v2.5.5" in section
    assert "Image tag pin `openbao.server.image.tag` `v2.5.5` (new)" in section


def test_make_changes_section_old_chart_none_renders_new_not_none_arrow(libcomponentdocschanges: ModuleType):
    """Regression test: old_chart is None (a component with no baseline
    Chart.yaml dependency at all — genuinely brand new this hop) renders
    "(chart <new_chart>, new)", the chart-side sibling of the old_app is
    None case above — never a nonsensical "chart None → <new_chart>",
    and the "Helm chart `...` bump" bullet (which needs a real old_chart
    to describe a transition) is suppressed."""
    section = libcomponentdocschanges.make_changes_section(
        libcomponentdocschanges.ComponentIdentity("openbao", "openbao", "openbao"),
        "4.9.1",
        libcomponentdocschanges.VersionChange("v2.5.5", "v2.5.5", None, "0.28.4"),
        ["server.image"],
    )
    assert section.startswith("### openbao v2.5.5 (unchanged) (chart 0.28.4, new)")
    assert "None" not in section
    assert "Helm chart" not in section


def test_make_changes_section_includes_chart_bullet_when_changed(libcomponentdocschanges: ModuleType):
    section = libcomponentdocschanges.make_changes_section(
        libcomponentdocschanges.ComponentIdentity("zac", "zaakafhandelcomponent", "zac"),
        "4.9.0",
        libcomponentdocschanges.VersionChange("5.0.2", "5.1.0", "1.0.297", "1.0.257"),
        ["image"],
    )
    assert "Helm chart `zaakafhandelcomponent` `1.0.297` → `1.0.257`" in section


def test_make_changes_section_native_component_omits_chart_clause(libcomponentdocschanges: ModuleType):
    """new_chart="-" (the literal not-applicable placeholder — see lib.
    chart.NATIVE_COMPONENTS) drops the "(chart ...)" heading clause and
    the "Helm chart" bump bullet entirely, rather than rendering the
    misleading "(chart None, unchanged)"."""
    section = libcomponentdocschanges.make_changes_section(
        libcomponentdocschanges.ComponentIdentity("frankgateway", "frankgateway", "frankgateway"),
        "4.9.0",
        libcomponentdocschanges.VersionChange("100", "104", None, "-"),
        ["image"],
    )
    assert section.startswith("### frankgateway 100 → 104\n\n")
    assert "chart" not in section.split("\n\n", 1)[0].lower()
    assert "Helm chart" not in section
    assert "Image tag pin `frankgateway.image.tag` `100` → `104`" in section


def test_insert_changes_section_appends_before_next_heading(libcomponentdocschanges: ModuleType):
    """No existing block resolves to any dependency here ("zac ..." has no
    real version text to anchor match_dependency, and DEPS/VALUES aren't
    supplied) -- falls back to appending at the section end, right before
    the next "## " heading."""
    text = "## Changes\n\n### zac ...\n\nblah\n\n## Per-environment checklist\n\nsteps\n"
    new_text = libcomponentdocschanges.insert_changes_section(
        text, "### openformulieren ...\n\n", "openformulieren", libcomponentdocschanges.OrderingContext([], {})
    )
    assert new_text.index("### openformulieren") < new_text.index("## Per-environment checklist")
    assert "### zac ..." in new_text


def test_insert_changes_section_inserted_in_values_yaml_order(libcomponentdocschanges: ModuleType):
    """openformulieren comes BEFORE zac in VALUES's own top-level key
    order -- the new block must land above the existing zac block, not
    always appended at the end."""
    text = "## Changes\n\n### zac 5.0.2 → 5.1.0 (chart 1.0.297, unchanged)\n\nblah\n"
    new_text = libcomponentdocschanges.insert_changes_section(
        text,
        "### openformulieren 3.4.10 → 3.5.6 (chart 1.12.0, unchanged)\n\n",
        "openformulieren",
        libcomponentdocschanges.OrderingContext(DEPS, VALUES),
    )
    assert new_text.index("### openformulieren") < new_text.index("### zac")


def test_insert_changes_section_no_changes_heading_appends_at_end(libcomponentdocschanges: ModuleType):
    text = "# Doc\n\nno changes section here\n"
    new_text = libcomponentdocschanges.insert_changes_section(
        text, "### new section\n", "openformulieren", libcomponentdocschanges.OrderingContext([], {})
    )
    assert new_text.endswith("### new section\n")
