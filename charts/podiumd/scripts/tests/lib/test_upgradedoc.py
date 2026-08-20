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


# --- image_tag / actual_app_version ---

def test_image_tag_nested_lookup(libupgradedoc):
    values = {"zac": {"image": {"tag": "5.4.3@sha256:abc"}}}
    assert libupgradedoc.image_tag(values, "zac", "image", "tag") == "5.4.3@sha256:abc"
    assert libupgradedoc.image_tag(values, "zac", "missing", "tag") is None
    assert libupgradedoc.image_tag("not-a-dict", "x") is None


def test_actual_app_version_single_image(libupgradedoc):
    assert libupgradedoc.actual_app_version({"zac": {"image": {"tag": "5.4.3@sha256:abc"}}}, "zac") == "5.4.3"


def test_actual_app_version_frontend_backend_lockstep(libupgradedoc):
    values = {"zgw-office-addin": {"frontend": {"image": {"tag": "v0.9.352@sha256:abc"}}}}
    assert libupgradedoc.actual_app_version(values, "zgw-office-addin") == "v0.9.352"


def test_actual_app_version_missing_returns_none(libupgradedoc):
    assert libupgradedoc.actual_app_version({}, "missing") is None
