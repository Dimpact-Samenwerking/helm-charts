"""Name resolution and extract_release_rows, with fetch_page_html mocked."""

from pathlib import Path
from types import ModuleType

import pytest

from lib.release_table.component_resolution import name_candidates
from lib.upgradedoc.string_and_parsing_basics import normalize_name


def write_chart_yaml_with_dependencies(chart_dir, deps):
    """`deps`: [(name, alias_or_None), ...]."""
    lines = ["apiVersion: v2", "name: podiumd", "version: 1.0.0", "dependencies:"]
    for name, alias in deps:
        lines.append(f"  - name: {name}")
        if alias:
            lines.append(f"    alias: {alias}")
        lines += ["    version: 1.0.0", '    repository: "@x"']
    (chart_dir / "Chart.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_values_yaml(chart_dir, keys):
    """values.yaml with each of `keys` as an empty top-level block."""
    (chart_dir / "values.yaml").write_text(
        "".join(f"{key}: {{}}\n" for key in keys),
        encoding="utf-8",
    )


def write_values_yaml_with_global_images(chart_dir, image_keys):
    """values.yaml with a global.images map of `image_keys` (shared-image anchors)."""
    lines = ["global:", "  images:"] + [f"    {key}: {{}}" for key in image_keys]
    (chart_dir / "values.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


PRODUCT_TABLE_HTML = """
<h2>Product component versies</h2>
<table>
<tbody>
<tr>
<th rowspan="2"></th>
<th rowspan="2">Ontwikkelpartij</th>
<th colspan="2">Versie 4.8</th>
<th colspan="2">Versie 4.9</th>
</tr>
<tr>
<th>App</th>
<th>Helm</th>
<th>App</th>
<th>Helm</th>
</tr>
<tr>
<td>ZAC</td>
<td>Info(NL)</td>
<td>5.0.0</td>
<td>1.0.290</td>
<td>5.1.0</td>
<td>1.0.297</td>
</tr>
<tr>
<td>Open Zaak</td>
<td>Maykin</td>
<td>1.27.0</td>
<td>1.14.0</td>
<td>1.27.4</td>
<td>1.14.2</td>
</tr>
</tbody>
</table>
"""

# Technische tables have "Used by" (optional) instead of a vendor column.
TECHNISCHE_TABLE_HTML = """
<h2>Technische component versies</h2>
<table>
<tbody>
<tr>
<th rowspan="2"></th>
<th rowspan="2">Used by</th>
<th colspan="2">Versie 4.8</th>
<th colspan="2">Versie 4.9</th>
</tr>
<tr>
<th>App</th>
<th>Helm</th>
<th>App</th>
<th>Helm</th>
</tr>
<tr>
<td>Elastic operator</td>
<td>ZAC</td>
<td>3.4.0</td>
<td>3.4.0</td>
<td>3.5.0</td>
<td>3.5.0</td>
</tr>
</tbody>
</table>
"""

# Like TECHNISCHE_TABLE_HTML but without the Helm sub-column, as on the real
# page since 2026-09.
TECHNISCHE_TABLE_NO_HELM_HTML = """
<h2>Technische component versies</h2>
<table>
<tbody>
<tr>
<th></th>
<th>Used by</th>
<th>Versie 4.8</th>
<th>Versie 4.9</th>
</tr>
<tr>
<td>Elastic operator</td>
<td>ZAC</td>
<td>3.4.0</td>
<td>3.5.0</td>
</tr>
</tbody>
</table>
"""

# No heading above it: ignored outright, not reported as skipped.
UNRELATED_TABLE_HTML = "<table><tr><th>Legend</th></tr><tr><td>n/a</td></tr></table>"

# Under a target heading but missing App/Helm columns: reported as skipped.
INCOMPLETE_UNDER_TARGET_HEADING_HTML = (
    "<h2>Overige component versies</h2><table><tr><th>Naam</th></tr><tr><td>iets</td></tr></table>"
)


# --- chart_dependencies ---


def test_chart_dependencies_reads_chart_yaml(ecrt: ModuleType, tmp_path: Path):
    write_chart_yaml_with_dependencies(tmp_path, [("internetaakafhandeling", "ita"), ("openzaak", None)])
    assert ecrt.chart_dependencies(tmp_path) == [("internetaakafhandeling", "ita"), ("openzaak", "")]


def test_chart_dependencies_missing_chart_yaml_returns_empty(ecrt: ModuleType, tmp_path: Path):
    assert ecrt.chart_dependencies(tmp_path) == []


# --- normalize_name / name_candidates ---


def test_normalize_name_strips_all_punctuation():
    assert normalize_name("Zaak - ZAC") == "zaakzac"
    assert normalize_name("OMC / Notify") == "omcnotify"


def test_name_candidates_no_brackets_is_just_the_whole_name():
    assert name_candidates("Zaak - ZAC") == ["zaakzac"]


def test_name_candidates_splits_bracketed_part_from_the_rest():
    assert name_candidates("Contact (KISS)") == ["contactkiss", "contact", "kiss"]


def test_name_candidates_dedupes_and_drops_empties():
    """ "(KISS)" alone must not produce an empty "rest" candidate."""
    assert name_candidates("(KISS)") == ["kiss"]


# --- component_and_alias ---


def test_component_and_alias_exact_name_match(ecrt: ModuleType):
    deps = [("internetaakafhandeling", "ita")]
    assert ecrt.component_and_alias("Interne Taak Afhandeling", deps) == ("internetaakafhandeling", "ita")


def test_component_and_alias_case_insensitive(ecrt: ModuleType):
    deps = [("internetaakafhandeling", "ita")]
    assert ecrt.component_and_alias("INTERNE TAAK AFHANDELING", deps) == ("internetaakafhandeling", "ita")


def test_component_and_alias_alias_substring_no_longer_matches(ecrt: ModuleType):
    """Only exact matches: alias "zac" merely contained in "Zaak - ZAC"
    is UNKNOWN; either part of "Zaak - ZAC (zaakafhandelcomponent)" or
    "Zaak (ZAC)" names the dependency exactly."""
    deps = [("zaakafhandelcomponent", "zac")]
    assert ecrt.component_and_alias("Zaak - ZAC", deps) == ("UNKNOWN", "")
    assert ecrt.component_and_alias("Zaak - ZAC (zaakafhandelcomponent)", deps) == ("zaakafhandelcomponent", "zac")
    assert ecrt.component_and_alias("Zaak (ZAC)", deps) == ("zaakafhandelcomponent", "zac")


def test_component_and_alias_resolves_via_bracketed_alias_exact_match(ecrt: ModuleType):
    """The bracketed part alone ("PABC") exactly equals the alias."""
    deps = [("pabc", "pabc")]
    assert ecrt.component_and_alias("Platform Autorisatie Beheer Component (PABC)", deps) == ("pabc", "pabc")


def test_component_and_alias_name_relation_no_longer_matches(ecrt: ModuleType):
    """ "openinwoner" merely contained in "Open Inwoner platform" is
    UNKNOWN; "Open Inwoner (Portaal)" names it exactly."""
    deps = [("openinwoner", "")]
    assert ecrt.component_and_alias("Portaal (Open Inwoner platform)", deps) == ("UNKNOWN", "")
    assert ecrt.component_and_alias("Open Inwoner (Portaal)", deps) == ("openinwoner", "")


def test_component_and_alias_exact_match_takes_priority_over_alias_relation(ecrt: ModuleType):
    """An exact dependency-name match beats a merely related alias."""
    deps = [("kiss-chart", "kiss"), ("kiss", "k")]
    assert ecrt.component_and_alias("kiss", deps) == ("kiss", "k")


def test_component_and_alias_unresolved_is_unknown(ecrt: ModuleType):
    """No match: component is UNKNOWN, not guessed; alias stays empty."""
    assert ecrt.component_and_alias("Open Zaak", []) == ("UNKNOWN", "")


def test_component_and_alias_exact_alias_match_beats_substring_ambiguity(ecrt: ModuleType):
    """An exact alias match is its own tier ahead of substring relation, so
    "kiss-eck" also containing "kiss" is not an ambiguity."""
    deps = [("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")]
    assert ecrt.component_and_alias("kiss", deps) == ("kiss-chart", "kiss")


def test_component_and_alias_multiple_when_two_dependencies_share_exact_alias(ecrt: ModuleType):
    """Two dependencies sharing the same alias: ambiguous, no pick."""
    deps = [("foo-chart", "shared"), ("bar-chart", "shared")]
    assert ecrt.component_and_alias("shared", deps) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_two_exact_matches_is_multiple(ecrt: ModuleType):
    """Each part of "Foo (Bar)" exactly names a different dependency: an
    ambiguity, never a guess."""
    deps = [("foo", ""), ("bar", "")]
    assert ecrt.component_and_alias("Foo (Bar)", deps) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_shared_prefix_is_unknown_not_multiple(ecrt: ModuleType):
    """ "foo" is only a prefix of "foo-bar" and "foo-baz": no exact match
    at all."""
    deps = [("foo-bar", ""), ("foo-baz", "")]
    assert ecrt.component_and_alias("foo", deps) == ("UNKNOWN", "")


def test_component_and_alias_never_relates_mid_word(ecrt: ModuleType) -> None:
    """Loose matching is on whole words only (as word_contains): "Referentielijst"
    does not relate to "referentielijsten", nor "mi" to "ensurePodiumdAdminUser"."""
    assert ecrt.component_and_alias("Referentielijst", [("referentielijsten", "")]) == ("UNKNOWN", "")
    assert ecrt.component_and_alias("mi", [("ensurePodiumdAdminUser", "")]) == ("UNKNOWN", "")


def test_component_and_alias_clean_exact_match_short_circuits_ambiguous_lower_tier(ecrt: ModuleType):
    """A tier-1 exact-name match resolves before the alias-relation tier,
    which would be ambiguous here."""
    deps = [("kiss", "k"), ("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")]
    assert ecrt.component_and_alias("kiss", deps) == ("kiss", "k")


# --- orphan_values_yaml_keys ---


def test_orphan_values_yaml_keys_returns_keys_not_covered_by_any_dependency(ecrt: ModuleType, tmp_path: Path):
    write_values_yaml(tmp_path, ["frankgateway", "global", "zac"])
    deps = [("zaakafhandelcomponent", "zac")]
    assert sorted(ecrt.orphan_values_yaml_keys(tmp_path, deps)) == [("frankgateway", ""), ("global", "")]


def test_orphan_values_yaml_keys_excludes_keys_matching_a_dependency_name(ecrt: ModuleType, tmp_path: Path):
    """A values.yaml key equal to a dependency's name (not just its alias)
    is excluded too."""
    write_values_yaml(tmp_path, ["keycloak-operator", "frankgateway"])
    deps = [("keycloak-operator", "")]
    assert ecrt.orphan_values_yaml_keys(tmp_path, deps) == [("frankgateway", "")]


def test_orphan_values_yaml_keys_missing_values_yaml_returns_empty(ecrt: ModuleType, tmp_path: Path):
    assert ecrt.orphan_values_yaml_keys(tmp_path, []) == []


# --- component_and_alias: orphan key fallback ---


def test_component_and_alias_resolves_via_orphan_key(ecrt: ModuleType):
    """Last resort: an exact match on an orphan values.yaml key; alias stays
    empty since orphan keys aren't Chart.yaml aliases."""
    assert ecrt.component_and_alias("Frank Gateway", [], [("frankgateway", "")]) == ("frankgateway", "")


def test_component_and_alias_real_dependency_always_wins_over_orphan_key(ecrt: ModuleType):
    """An orphan key never hijacks a name that a real dependency also names
    exactly."""
    deps = [("widget-operator", "")]
    orphans = [("widget", "")]
    assert ecrt.component_and_alias("Widget operator (widget)", deps, orphans) == ("widget-operator", "")
    assert ecrt.component_and_alias("Widget", deps, orphans) == ("widget", "")


def test_component_and_alias_native_component_exact_match_beats_loose_dependency(ecrt: ModuleType):
    """Native components are matched in the exact tiers, so "Keycloak" never
    falls through to a loose relation with "keycloak-operator"."""
    deps = [("keycloak-operator", "")]
    orphans = [("keycloak", ""), ("frankgateway", "")]
    natives = [("frankgateway", ""), ("keycloak", "")]
    assert ecrt.component_and_alias("Keycloak", deps, orphans, (), natives) == ("keycloak", "")
    assert ecrt.component_and_alias("keycloak", deps, orphans, (), natives) == ("keycloak", "")
    assert ecrt.component_and_alias("Keycloak operator", deps, orphans, (), natives) == ("keycloak-operator", "")


def test_component_and_alias_orphan_key_multiple(ecrt: ModuleType):
    """Two orphan keys each named exactly is MULTIPLE, not a silent pick."""
    orphans = [("foo-bar", ""), ("foo-baz", "")]
    assert ecrt.component_and_alias("Foo Bar (foo baz)", [], orphans) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_still_unknown_when_no_orphan_key_relates_either(ecrt: ModuleType):
    assert ecrt.component_and_alias("Open Zaak", [], [("frankgateway", "")]) == ("UNKNOWN", "")


# --- global_image_names ---


def test_global_image_names_returns_keys_under_global_images(ecrt: ModuleType, tmp_path: Path):
    write_values_yaml_with_global_images(tmp_path, ["nginx", "curl", "busybox"])
    assert ecrt.global_image_names(tmp_path) == ["nginx", "curl", "busybox"]


def test_global_image_names_adds_each_image_basename(ecrt: ModuleType, tmp_path: Path):
    (tmp_path / "values.yaml").write_text(
        "global:\n  images:\n    nginx:\n      repository: nginxinc/nginx-unprivileged\n"
        "    curl:\n      repository: curlimages/curl\n",
        encoding="utf-8",
    )
    assert ecrt.global_image_names(tmp_path) == ["nginx", "curl", "nginx-unprivileged"]


def test_global_image_names_missing_values_yaml_returns_empty(ecrt: ModuleType, tmp_path: Path):
    assert ecrt.global_image_names(tmp_path) == []


def test_global_image_names_missing_global_images_returns_empty(ecrt: ModuleType, tmp_path: Path):
    write_values_yaml(tmp_path, ["frankgateway"])
    assert ecrt.global_image_names(tmp_path) == []


# --- component_and_alias: global image key fallback ---


def test_component_and_alias_global_image_key_is_always_multiple(ecrt: ModuleType):
    """An exact global image key match is MULTIPLE (the key is shared by
    several components via anchor); mere containment is UNKNOWN."""
    keys = ["nginx", "curl", "busybox"]
    assert ecrt.component_and_alias("Nginx (unprivileged)", [], [], keys) == ("MULTIPLE", "MULTIPLE")
    assert ecrt.component_and_alias("Nginx unprivileged", [], [], keys) == ("UNKNOWN", "")


def test_component_and_alias_real_dependency_always_wins_over_global_image_key(ecrt: ModuleType):
    """A global image key must never hijack a name that already resolves
    through a real dependency or an orphan key."""
    deps = [("nginx-ingress", "nginx")]
    assert ecrt.component_and_alias("nginx", deps, [], ["nginx"]) == ("nginx-ingress", "nginx")


def test_component_and_alias_orphan_key_wins_over_global_image_key(ecrt: ModuleType):
    orphans = [("nginx", "")]
    assert ecrt.component_and_alias("nginx", [], orphans, ["nginx"]) == ("nginx", "")


def test_component_and_alias_still_unknown_when_no_global_image_key_relates_either(ecrt: ModuleType):
    assert ecrt.component_and_alias("Solr", [], [], ["nginx", "curl", "busybox"]) == ("UNKNOWN", "")


def test_component_and_alias_global_image_key_overrides_coincidental_loose_dependency_match(ecrt: ModuleType):
    """Regression: "Redis" (global.images.redis) must be MULTIPLE, not
    hijacked by a loose substring relation to "redis-operator"."""
    deps = [("redis-operator", "")]
    assert ecrt.component_and_alias("Redis", deps, [], ["redis"]) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_exact_dependency_match_still_wins_despite_global_image_key(ecrt: ModuleType):
    """The override applies only to loose-relation resolutions, never an
    exact match."""
    deps = [("redis-operator", "redis")]
    assert ecrt.component_and_alias("redis", deps, [], ["redis"]) == ("redis-operator", "redis")


# --- extract_release_rows ---


def test_extract_release_rows_matches_and_reports(ecrt: ModuleType, capsys: pytest.CaptureFixture[str]):
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]
    out = capsys.readouterr().out
    assert "2 row(s) matched" in out


def test_extract_release_rows_resolves_component_and_alias_by_exact_match(ecrt: ModuleType, tmp_path: Path):
    """An exact dependency-name match resolves component/alias; "Open Zaak"
    stays UNKNOWN. The alias is chosen not to substring-match "Open Zaak"."""
    write_chart_yaml_with_dependencies(tmp_path, [("zac", "zacalias")])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "zac", "zacalias", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


def test_extract_release_rows_resolves_component_and_alias_by_alias_substring(ecrt: ModuleType, tmp_path: Path):
    """ "ZAC" resolves via the dependency's alias being a substring of it,
    the rule most real components rely on."""
    write_chart_yaml_with_dependencies(tmp_path, [("zaakafhandelcomponent", "zac")])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows[0] == [
        "Product",
        "Info(NL)",
        "",
        "ZAC",
        "zaakafhandelcomponent",
        "zac",
        "",
        "5.0.0",
        "1.0.290",
        "5.1.0",
        "1.0.297",
    ]


def test_extract_release_rows_resolves_component_without_alias_via_name_relation(ecrt: ModuleType, tmp_path: Path):
    """A name relation against an alias-less dependency sets component only;
    "ZAC" stays UNKNOWN."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", None)])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows[0][4] == "UNKNOWN"
    assert rows[1] == ["Product", "Maykin", "", "Open Zaak", "openzaak", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"]


def test_extract_release_rows_not_tied_to_specific_version_numbers(ecrt: ModuleType):
    """Versie headings are renamed every release: source/target come from
    column order, not the number."""
    html = PRODUCT_TABLE_HTML.replace("Versie 4.8", "Versie 5.0").replace("Versie 4.9", "Versie 5.1")
    rows = ecrt.extract_release_rows(html)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


def test_extract_release_rows_replaces_non_semver_version_with_unknown_and_reports_count(
    ecrt: ModuleType, capsys: pytest.CaptureFixture[str]
):
    html = PRODUCT_TABLE_HTML.replace("<td>5.1.0</td>", "<td>?</td>")
    rows = ecrt.extract_release_rows(html)
    assert rows[0] == ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "", "5.0.0", "1.0.290", "UNKNOWN", "1.0.297"]
    out = capsys.readouterr().out
    assert "1 version value(s) were not semver-compatible — replaced with UNKNOWN" in out
    assert 'WARNING: "ZAC": target_version_app is not semver-compatible — replaced with UNKNOWN' in out
    # No Chart.yaml/values.yaml under the isolated chart_dir, so ZAC is UNKNOWN.
    assert (
        'WARNING: "ZAC" did not resolve to any Chart.yaml dependency, orphan values.yaml key, or global image key'
    ) in out


def test_extract_release_rows_ignores_table_not_under_any_target_heading(
    ecrt: ModuleType, capsys: pytest.CaptureFixture[str]
):
    html = UNRELATED_TABLE_HTML + PRODUCT_TABLE_HTML
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2
    out = capsys.readouterr().out
    assert "Found 2 table(s) on the page, 1 under a matching heading" in out
    assert "Legend" not in out  # the unrelated table was never even reported on


def test_extract_release_rows_reports_skip_for_incomplete_table_under_target_heading(
    ecrt: ModuleType, capsys: pytest.CaptureFixture[str]
):
    html = INCOMPLETE_UNDER_TARGET_HEADING_HTML + PRODUCT_TABLE_HTML
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2
    out = capsys.readouterr().out
    assert '"Overige component versies": skipped (missing required column(s):' in out


def test_extract_release_rows_vendor_blank_used_by_populated_for_technische_table(
    ecrt: ModuleType, capsys: pytest.CaptureFixture[str]
):
    """Technische tables have "Used by" but no vendor column."""
    rows = ecrt.extract_release_rows(TECHNISCHE_TABLE_HTML)
    assert rows == [
        ["Technische", "", "ZAC", "Elastic operator", "UNKNOWN", "", "", "3.4.0", "3.4.0", "3.5.0", "3.5.0"]
    ]
    out = capsys.readouterr().out
    assert (
        'WARNING: "Elastic operator" (used_by "ZAC") did not resolve to any Chart.yaml '
        "dependency, orphan values.yaml key, or global image key"
    ) in out


def test_extract_release_rows_technische_table_without_helm_column(ecrt: ModuleType):
    """A Technische table without a Helm sub-column (real page since 2026-09)
    still exports rows, with blank helm cells."""
    rows = ecrt.extract_release_rows(TECHNISCHE_TABLE_NO_HELM_HTML)
    assert rows == [["Technische", "", "ZAC", "Elastic operator", "UNKNOWN", "", "", "3.4.0", "", "3.5.0", ""]]
