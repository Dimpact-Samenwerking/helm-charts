"""find_component_row / update_component_table and make_changes_section /
insert_changes_section."""

from types import ModuleType

# --- find_component_row / update_component_table ---


def test_find_component_row_matches_by_substring(libcomponentdocschanges: ModuleType):
    rows = [{"name": "ZAC (Zaakafhandelcomponent)", "line_index": 0}]
    assert libcomponentdocschanges.find_component_row(rows, "zac")["line_index"] == 0


def test_find_component_row_no_match_returns_none(libcomponentdocschanges: ModuleType):
    rows = [{"name": "ZAC (Zaakafhandelcomponent)", "line_index": 0}]
    assert libcomponentdocschanges.find_component_row(rows, "openformulieren") is None


def test_find_component_row_plain_name_does_not_match_its_own_sidecar_rows(libcomponentdocschanges: ModuleType):
    """Regression: a "<key> - <image-basename>" sidecar row starts with its owner's
    name but must not match a lookup for the owner itself, or
    update_component_table overwrites the sidecar row."""
    rows = [
        {"name": "openbao - openbao-csi-provider", "line_index": 0},
        {"name": "openbao - openbao-snapshot-agent", "line_index": 1},
    ]
    assert libcomponentdocschanges.find_component_row(rows, "openbao") is None


def test_find_component_row_sidecar_name_still_matches_its_own_row(libcomponentdocschanges: ModuleType):
    """A lookup for the sidecar's full canonical name still finds its row."""
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


def test_update_component_table_without_new_app_keeps_the_rows_app_cell(libcomponentdocschanges: ModuleType):
    """Regression: no new app version left the cell None and join() raised
    TypeError; the app cell is now left as is."""
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac | 5.0.2 → 5.1.0 | 1.0.290 → 1.0.297 | - |\n"
    )
    new_text, action = libcomponentdocschanges.update_component_table(
        text,
        "zac",
        libcomponentdocschanges.VersionChange(None, None, "1.0.290", "1.0.300"),
        libcomponentdocschanges.OrderingContext(DEPS, VALUES),
    )
    assert action == "updated"
    assert "| zac | 5.0.2 → 5.1.0 | 1.0.290 → 1.0.300 | - |" in new_text


def test_update_component_table_new_row_without_app_version_writes_dash(libcomponentdocschanges: ModuleType):
    """Regression: a new row without an app version got the text "None"."""
    text = (
        COMPONENT_VERSIONS_HEADING + "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | - |\n"
    )
    new_text, _action = libcomponentdocschanges.update_component_table(
        text,
        "openformulieren",
        libcomponentdocschanges.VersionChange(None, None, "1.12.0", "1.12.0"),
        libcomponentdocschanges.OrderingContext(DEPS, VALUES),
    )
    assert "None" not in new_text
    assert "| openformulieren | - | 1.12.0 (unchanged) | - |" in new_text


def test_update_component_table_new_row_not_absorbed_by_own_sidecar_rows(libcomponentdocschanges: ModuleType):
    """Regression: with sidecar rows present but the owner's own row missing,
    the owner gets a new row instead of overwriting a sidecar row."""
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
    """New rows follow values.yaml key order, not always appended."""
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
    """A brand-new component (old versions None) gets "(new)" cells."""
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
    """An empty table's new row goes under its own separator, not the doc's
    last "| --- |" (which may belong to another table)."""
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
    """A sidecar row's chart cell stays the "-" placeholder, never "(new)"."""
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
    """old_app == new_app (e.g. only a sidecar in the subtree changed) renders
    "<app> (unchanged)", not "<app> → <app>"."""
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
    """old_app None (e.g. openbao: app version only resolvable via the
    subchart fallback, never tried for the baseline) renders "<app> (new)"."""
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
    """old_chart None (brand-new dependency) renders "(chart <new>, new)" and
    suppresses the "Helm chart ... bump" bullet."""
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
    """new_chart="-" (native component) drops the chart clause and bump bullet."""
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
    """With no block resolvable to a dependency, append at the section end."""
    text = "## Changes\n\n### zac ...\n\nblah\n\n## Per-environment checklist\n\nsteps\n"
    new_text = libcomponentdocschanges.insert_changes_section(
        text, "### openformulieren ...\n\n", "openformulieren", libcomponentdocschanges.OrderingContext([], {})
    )
    assert new_text.index("### openformulieren") < new_text.index("## Per-environment checklist")
    assert "### zac ..." in new_text


def test_insert_changes_section_inserted_in_values_yaml_order(libcomponentdocschanges: ModuleType):
    """New blocks follow values.yaml key order, not always appended."""
    text = "## Changes\n\n### zac 5.0.2 → 5.1.0 (chart 1.0.297, unchanged)\n\nblah\n"
    new_text = libcomponentdocschanges.insert_changes_section(
        text,
        "### openformulieren 3.4.10 → 3.5.6 (chart 1.12.0, unchanged)\n\n",
        "openformulieren",
        libcomponentdocschanges.OrderingContext(DEPS, VALUES),
    )
    assert new_text.index("### openformulieren") < new_text.index("### zac")


def test_insert_changes_section_no_changes_heading_adds_it_at_end(libcomponentdocschanges: ModuleType):
    """Without the heading, a later run would not find the block and add it again."""
    text = "# Doc\n\nno changes section here\n"
    new_text = libcomponentdocschanges.insert_changes_section(
        text, "### new section\n", "openformulieren", libcomponentdocschanges.OrderingContext([], {})
    )
    assert new_text == "# Doc\n\nno changes section here\n\n## Changes\n\n### new section\n"
