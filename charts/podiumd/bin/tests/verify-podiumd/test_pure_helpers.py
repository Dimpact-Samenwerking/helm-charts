"""normalize_version, normalize_name, words_of, extract_target_version,
extract_source_version, image_tag, actual_app_version, find_image_tag_paths,
baseline_ref_candidates."""
import pytest


def test_normalize_version_strips_leading_v(libupgradedoc):
    assert libupgradedoc.normalize_version("v0.9.313") == "0.9.313"
    assert libupgradedoc.normalize_version("0.11.0") == "0.11.0"
    assert libupgradedoc.normalize_version("") == ""
    assert libupgradedoc.normalize_version(None) is None


def test_normalize_name_strips_punctuation_and_lowercases(libupgradedoc):
    assert libupgradedoc.normalize_name("ZAC (Zaakafhandelcomponent)") == "zaczaakafhandelcomponent"
    assert libupgradedoc.normalize_name("zgw-office-addin-frontend") == "zgwofficeaddinfrontend"


def test_words_of_splits_on_non_alnum(libupgradedoc):
    assert libupgradedoc.words_of("zgw-office-addin-frontend") == ["zgw", "office", "addin", "frontend"]
    assert libupgradedoc.words_of("ZAC (Zaakafhandelcomponent)") == ["zac", "zaakafhandelcomponent"]
    assert libupgradedoc.words_of("") == []


@pytest.mark.parametrize("cell,expected", [
    ("5.0.2 → 5.4.3", "5.4.3"),
    ("5.0.2 -> 5.4.3", "5.4.3"),
    ("1.0.297 (unchanged)", "1.0.297"),
    ("`0.0.92`", "0.0.92"),
    ("v0.9.313 → 0.11.0", "0.11.0"),
])
def test_extract_target_version(libupgradedoc, cell, expected):
    assert libupgradedoc.extract_target_version(cell) == expected


@pytest.mark.parametrize("cell,expected", [
    ("5.0.2 → 5.4.3", "5.0.2"),
    ("5.0.2 -> 5.4.3", "5.0.2"),
    ("1.0.297 (unchanged)", "1.0.297"),
    ("v0.9.313 → 0.11.0", "v0.9.313"),
])
def test_extract_source_version(libupgradedoc, cell, expected):
    assert libupgradedoc.extract_source_version(cell) == expected


def test_extract_version_handles_no_match(libupgradedoc):
    assert libupgradedoc.extract_target_version("") is None
    assert libupgradedoc.extract_source_version("") is None
    # no word-like token at all -- the fallback regex has nothing to grab
    assert libupgradedoc.extract_target_version("!!!") is None
    assert libupgradedoc.extract_source_version("!!!") is None


def test_image_tag_walks_nested_path(libupgradedoc):
    values = {"zac": {"image": {"tag": "5.4.3@sha256:abc"}}}
    assert libupgradedoc.image_tag(values, "zac", "image", "tag") == "5.4.3@sha256:abc"
    assert libupgradedoc.image_tag(values, "zac", "missing", "tag") is None
    assert libupgradedoc.image_tag(values, "missing") is None
    assert libupgradedoc.image_tag("not-a-dict", "x") is None


def test_actual_app_version_tries_plain_frontend_backend(libupgradedoc):
    assert libupgradedoc.actual_app_version({"zac": {"image": {"tag": "5.4.3@sha256:abc"}}}, "zac") == "5.4.3"
    assert libupgradedoc.actual_app_version(
        {"addin": {"frontend": {"image": {"tag": "0.11.0@sha256:abc"}}}}, "addin") == "0.11.0"
    assert libupgradedoc.actual_app_version(
        {"addin": {"backend": {"image": {"tag": "0.11.0@sha256:abc"}}}}, "addin") == "0.11.0"
    assert libupgradedoc.actual_app_version({}, "missing") is None


def test_find_image_tag_paths_finds_sidecars(libupgradedoc):
    values = {
        "zac": {
            "image": {"tag": "5.4.3@sha256:a"},
            "opa": {"image": {"tag": "1.19.0-static@sha256:b"}},
            "solr-operator": {"solr": {"image": {"tag": "9.10.1-slim@sha256:c"}}},
        }
    }
    paths = dict(libupgradedoc.find_image_tag_paths(values))
    assert paths[("zac",)] == "5.4.3@sha256:a"
    assert paths[("zac", "opa")] == "1.19.0-static@sha256:b"
    assert paths[("zac", "solr-operator", "solr")] == "9.10.1-slim@sha256:c"


def test_find_image_tag_paths_skips_empty_tag(libupgradedoc):
    values = {"zac": {"image": {"tag": ""}}}
    assert dict(libupgradedoc.find_image_tag_paths(values)) == {}


def test_find_image_tag_paths_walks_lists(libupgradedoc):
    values = {"items": [{"image": {"tag": "1.0@sha256:a"}}]}
    paths = dict(libupgradedoc.find_image_tag_paths(values))
    assert paths[("items", "0")] == "1.0@sha256:a"


def test_baseline_ref_candidates_bare_version(libgitutil):
    assert libgitutil.baseline_ref_candidates("4.8.5") == [
        "podiumd-4.8.5", "origin/feature/podiumd-4.8.5", "feature/podiumd-4.8.5"
    ]


def test_baseline_ref_candidates_explicit_ref(libgitutil):
    assert libgitutil.baseline_ref_candidates("origin/some-branch") == ["origin/some-branch"]
    assert libgitutil.baseline_ref_candidates("abc1234") == ["abc1234"]
