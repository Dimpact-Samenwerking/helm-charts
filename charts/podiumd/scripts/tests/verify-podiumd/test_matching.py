"""match_dependency and resolve_entry_path — including the two disambiguation
bugs found (and fixed) during development: resolve_entry_path picking the
wrong sibling path via naive longest-substring matching."""
from conftest import make_dep


def test_match_dependency_by_name(vp):
    deps = [make_dep("zaakafhandelcomponent", "1.0.297", alias="zac")]
    assert vp.match_dependency("ZAC (Zaakafhandelcomponent)", deps) == deps[0]


def test_match_dependency_by_alias(vp):
    deps = [make_dep("zgw-office-addin", "0.0.92")]
    assert vp.match_dependency("ZGW Office Add-in (frontend + backend)", deps) == deps[0]


def test_match_dependency_no_match_returns_none(vp):
    deps = [make_dep("zaakafhandelcomponent", "1.0.297", alias="zac")]
    assert vp.match_dependency("Totally Fictitious Component", deps) is None


def test_match_dependency_prefers_longer_more_specific_match(vp):
    deps = [
        make_dep("zac", "1.0.297"),
        make_dep("zac-extended-thing", "1.0.0", alias="zacx"),
    ]
    # "zac" is a substring of "zacx" too, but the plain "zac" dep is the
    # better (exact) match for a doc row literally named "ZAC"
    assert vp.match_dependency("ZAC", deps)["name"] == "zac"


def test_resolve_entry_path_exact_match(vp):
    paths = [("zac",), ("zac", "opa")]
    assert vp.resolve_entry_path("opa", paths) == ("zac", "opa")


def test_resolve_entry_path_multi_word_entry(vp):
    paths = [("zgw-office-addin", "frontend"), ("zgw-office-addin", "backend")]
    assert vp.resolve_entry_path("zgw-office-addin-frontend", paths) == ("zgw-office-addin", "frontend")
    assert vp.resolve_entry_path("zgw-office-addin-backend", paths) == ("zgw-office-addin", "backend")


def test_resolve_entry_path_disambiguates_sibling_paths_by_last_word(vp):
    """Regression test: zac-solr must resolve to zac.solr-operator.solr, not
    zac.solr-operator.zookeeper-operator.zookeeper, even though both paths
    start with the same "zac"+"solr"+"operator" prefix. Naive
    longest-substring-wins matching picked the wrong (longer) one."""
    paths = [
        ("zac",),
        ("zac", "solr-operator", "solr"),
        ("zac", "solr-operator", "zookeeper-operator", "zookeeper"),
    ]
    assert vp.resolve_entry_path("zac-solr", paths) == ("zac", "solr-operator", "solr")


def test_resolve_entry_path_no_match_returns_none(vp):
    paths = [("zac", "opa")]
    assert vp.resolve_entry_path("totally-unrelated", paths) is None


def test_resolve_entry_path_empty_entry_name(vp):
    assert vp.resolve_entry_path("", [("zac",)]) is None
