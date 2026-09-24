"""lib.upgradedoc -- string normalization, version-cell parsing,
fuzzy name/dependency matching, and changes-heading identity
resolution."""

from types import ModuleType

# --- normalize_version / normalize_name / words_of ---


def test_normalize_version_strips_v_prefix(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.normalize_version("v0.9.313") == "0.9.313"
    assert libupgradedocbasics.normalize_version("5.4.3") == "5.4.3"
    assert libupgradedocbasics.normalize_version(None) is None


def test_normalize_name_strips_punctuation(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.normalize_name("ZAC (Zaakafhandelcomponent)") == "zaczaakafhandelcomponent"


def test_words_of_splits_on_non_alnum(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.words_of("zgw-office-addin-frontend") == ["zgw", "office", "addin", "frontend"]


# --- extract_target_version / extract_source_version ---


def test_extract_versions_arrow_cell(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.extract_source_version("5.0.2 → 5.4.3") == "5.0.2"
    assert libupgradedocbasics.extract_target_version("5.0.2 → 5.4.3") == "5.4.3"


def test_extract_versions_unchanged_cell(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.extract_source_version("1.0.297 (unchanged)") == "1.0.297"
    assert libupgradedocbasics.extract_target_version("1.0.297 (unchanged)") == "1.0.297"


def test_extract_versions_backtick_cell(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.extract_target_version("`0.0.92`") == "0.0.92"


# --- parse_upgrade_doc_rows ---

TABLE = """\
# Upgrade guide

## Component versions (4.9.0 vs 4.8.5)

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | ACR mirror only |
| ZGW Office Add-in (frontend + backend) | v0.9.313 → 0.11.0 | 0.0.89 → 0.0.92 | ACR mirror only |
"""


def test_parse_upgrade_doc_rows_parses_all_rows(libupgradedocbasics: ModuleType):
    rows = libupgradedocbasics.parse_upgrade_doc_rows(TABLE)
    assert len(rows) == 2
    assert rows[0]["name"] == "ZAC (Zaakafhandelcomponent)"
    assert rows[0]["app_source"] == "5.0.2"
    assert rows[0]["app"] == "5.4.3"
    assert rows[0]["chart_source"] == "1.0.297"
    assert rows[0]["chart"] == "1.0.297"


def test_parse_upgrade_doc_rows_includes_line_index(libupgradedocbasics: ModuleType):
    rows = libupgradedocbasics.parse_upgrade_doc_rows(TABLE)
    lines = TABLE.splitlines()
    assert (
        lines[rows[0]["line_index"]]
        == "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | ACR mirror only |"
    )


def test_parse_upgrade_doc_rows_skips_header_and_separator(libupgradedocbasics: ModuleType):
    rows = libupgradedocbasics.parse_upgrade_doc_rows(TABLE)
    names = [r["name"] for r in rows]
    assert "Component" not in names
    assert not any(set(n) <= set("-: ") for n in names)


def test_parse_upgrade_doc_rows_no_table_returns_empty(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.parse_upgrade_doc_rows("# Upgrade guide\n\nJust prose.\n") == []


# --- _word_aligned_spans ---


def test_word_aligned_spans_includes_every_contiguous_word_run(libupgradedocbasics: ModuleType):
    spans = libupgradedocbasics._word_aligned_spans("ZGW Office Add-in")
    assert spans == {
        "zgw",
        "zgwoffice",
        "zgwofficeadd",
        "zgwofficeaddin",
        "office",
        "officeadd",
        "officeaddin",
        "add",
        "addin",
        "in",
    }


def test_word_aligned_spans_excludes_mid_word_fragments(libupgradedocbasics: ModuleType):
    """ "mi" never appears as its own span even though it's a literal
    substring of "admin" — spans only ever concatenate WHOLE words."""
    spans = libupgradedocbasics._word_aligned_spans("ensurePodiumdAdminUser")
    assert "mi" not in spans
    assert spans == {"ensurepodiumdadminuser"}


# --- match_dependency ---


def test_match_dependency_by_alias(libupgradedocbasics: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    dep = libupgradedocbasics.match_dependency("ZAC (Zaakafhandelcomponent)", deps)
    assert dep["alias"] == "zac"


def test_match_dependency_prefers_longest_match(libupgradedocbasics: ModuleType):
    deps = [{"name": "openzaak"}, {"name": "openzaak-notificaties"}]
    dep = libupgradedocbasics.match_dependency("OpenZaak Notificaties", deps)
    assert dep["name"] == "openzaak-notificaties"


def test_match_dependency_no_match_returns_none(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.match_dependency("Totally Unknown Thing", [{"name": "zac"}]) is None


def test_match_dependency_short_alias_does_not_match_mid_word(libupgradedocbasics: ModuleType):
    """ "mi" is a literal substring of "ensurePodiumdAdminUser" (inside
    "ad-mi-n") — must not match at all without a real word boundary."""
    deps = [{"name": "mi-data", "alias": "mi"}]
    assert libupgradedocbasics.match_dependency("Python (ensurePodiumdAdminUser init image)", deps) is None


# --- match_native_component ---


def test_match_native_component_matches_bare_name(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.match_native_component("frankgateway", {"frankgateway"}) == "frankgateway"


def test_match_native_component_matches_with_version_text(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.match_native_component("frankgateway 100 → 104", {"frankgateway"}) == "frankgateway"


def test_match_native_component_no_match_returns_none(libupgradedocbasics: ModuleType):
    assert libupgradedocbasics.match_native_component("Totally Unknown Thing", {"frankgateway"}) is None


def test_match_native_component_does_not_match_mid_word(libupgradedocbasics: ModuleType):
    """Same word-boundary protection as match_dependency — a native
    component name that happens to be a literal substring of an unrelated
    word must not match."""
    assert libupgradedocbasics.match_native_component("somefrankgatewayfoo", {"frankgateway"}) is None


# --- changes_heading_identities ---


def test_changes_heading_identities_single_component(libupgradedocbasics: ModuleType):
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    idents = libupgradedocbasics.changes_heading_identities(
        "ECK Stack (kiss-eck) 8.19.3 → 8.19.19 (chart 0.19.0 → 0.20.0)", deps, {}
    )
    assert idents == {("dep", "kiss-eck")}


def test_changes_heading_identities_two_real_components(libupgradedocbasics: ModuleType):
    deps = [
        {"name": "eck-operator", "version": "3.5.0"},
        {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"},
    ]
    idents = libupgradedocbasics.changes_heading_identities(
        "ECK Operator 3.4.0 → 3.5.0 + ECK Stack (kiss-eck) 0.19.0 → 0.20.0", deps, {}
    )
    assert idents == {("dep", "eck-operator"), ("dep", "kiss-eck")}


def test_changes_heading_identities_does_not_double_count_an_alias_nested_inside_another(
    libupgradedocbasics: ModuleType,
):
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
    idents = libupgradedocbasics.changes_heading_identities(
        "ECK Stack (kiss-eck) 8.19.3 → 8.19.19 (chart 0.19.0 → 0.20.0)", deps, {}
    )
    assert idents == {("dep", "kiss-eck")}


def test_changes_heading_identities_self_referential_sidecar_shape_resolves_to_nothing(libupgradedocbasics: ModuleType):
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
    idents = libupgradedocbasics.changes_heading_identities("openbao - openbao 2.5.5 → 2.5.5", deps, {})
    assert idents == set()


def test_changes_heading_identities_real_sidecar_still_resolves_despite_dash(libupgradedocbasics: ModuleType):
    """The " - " guard must never swallow a REAL canonical sidecar match
    — only applies once match_canonical_sidecar_name has already had its
    own shot and failed."""
    canonical_names = {"openbao - postgres": ("openbao", "database", "schemaJob", "image")}
    deps = [{"name": "openbao", "version": "0.28.4"}]
    idents = libupgradedocbasics.changes_heading_identities(
        "openbao - postgres 16-alpine → 16-alpine", deps, canonical_names
    )
    assert idents == {("sidecar", ("openbao", "database", "schemaJob", "image"))}
