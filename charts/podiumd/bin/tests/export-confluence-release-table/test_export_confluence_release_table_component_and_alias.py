"""chart_dependencies, normalize_name, name_candidates, component_and_alias,
orphan_values_yaml_keys, global_image_keys, extract_release_rows — with
fetch_page_html mocked out, so no network access or real Confluence page
is needed."""

from lib.release_table.component_resolution import name_candidates
from lib.release_table.component_resolution import normalize_name


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
    """A minimal values.yaml with each of `keys` as a top-level key
    mapping to an empty block."""
    (chart_dir / "values.yaml").write_text(
        "".join(f"{key}: {{}}\n" for key in keys),
        encoding="utf-8",
    )


def write_values_yaml_with_global_images(chart_dir, image_keys):
    """A minimal values.yaml with a top-level global.images map holding
    each of `image_keys` — mirrors the real chart's
    global.images.nginx/curl/busybox shared-base-image anchors."""
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

# "Technische component versies" tables don't have a development-partner
# column at all — "Used by" instead (naming the product/Common Ground
# component that pulls this piece of tooling in), which isn't required.
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

# Same shape as TECHNISCHE_TABLE_HTML, but without the App/Helm
# sub-header split at all -- since 2026-09 the real page's "Technische
# component versies" table dropped its Helm sub-column entirely (its
# cells were always empty anyway), leaving one bare column per
# "Versie ..." group.
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

# A table with no heading at all above it — not under any of the target
# sections, so it's ignored outright, not merely "skipped for missing
# columns".
UNRELATED_TABLE_HTML = "<table><tr><th>Legend</th></tr><tr><td>n/a</td></tr></table>"

# Under a target heading, but genuinely missing the required App/Helm
# columns — this one SHOULD be reported as skipped.
INCOMPLETE_UNDER_TARGET_HEADING_HTML = (
    "<h2>Overige component versies</h2><table><tr><th>Naam</th></tr><tr><td>iets</td></tr></table>"
)


# --- chart_dependencies ---


def test_chart_dependencies_reads_chart_yaml(ecrt, tmp_path):
    write_chart_yaml_with_dependencies(tmp_path, [("internetaakafhandeling", "ita"), ("openzaak", None)])
    assert ecrt.chart_dependencies(tmp_path) == [("internetaakafhandeling", "ita"), ("openzaak", "")]


def test_chart_dependencies_missing_chart_yaml_returns_empty(ecrt, tmp_path):
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
    """ "(KISS)" alone, with nothing outside the brackets, must not
    produce a spurious empty "rest" candidate."""
    assert name_candidates("(KISS)") == ["kiss"]


# --- component_and_alias ---


def test_component_and_alias_exact_name_match(ecrt):
    deps = [("internetaakafhandeling", "ita")]
    assert ecrt.component_and_alias("Interne Taak Afhandeling", deps) == ("internetaakafhandeling", "ita")


def test_component_and_alias_case_insensitive(ecrt):
    deps = [("internetaakafhandeling", "ita")]
    assert ecrt.component_and_alias("INTERNE TAAK AFHANDELING", deps) == ("internetaakafhandeling", "ita")


def test_component_and_alias_resolves_via_alias_substring(ecrt):
    """ "Zaak - ZAC" doesn't equal dependency name "zaakafhandelcomponent"
    exactly, but its own alias "zac" is a literal substring of "Zaak -
    ZAC" (spaces/dash stripped: "zaakzac") — this is the rule that
    resolves most real components (the exact-match rule alone only ever
    fires for a name that's coincidentally identical to its Chart.yaml
    dependency name, like "Interne Taak Afhandeling")."""
    deps = [("zaakafhandelcomponent", "zac")]
    assert ecrt.component_and_alias("Zaak - ZAC", deps) == ("zaakafhandelcomponent", "zac")


def test_component_and_alias_resolves_via_bracketed_alias_exact_match(ecrt):
    """The bracketed part alone ("PABC") exactly equals the dependency's
    alias — resolved via name_candidates splitting it out, even though
    the whole name only contains it as a small piece of a much longer
    string."""
    deps = [("pabc", "pabc")]
    assert ecrt.component_and_alias("Platform Autorisatie Beheer Component (PABC)", deps) == ("pabc", "pabc")


def test_component_and_alias_resolves_via_name_relation_without_alias(ecrt):
    """A dependency with no alias at all can still resolve, purely by its
    own name relating to (here: being contained in) the bracketed part
    of the component's name."""
    deps = [("openinwoner", "")]
    assert ecrt.component_and_alias("Portaal (Open Inwoner platform)", deps) == ("openinwoner", "")


def test_component_and_alias_exact_match_takes_priority_over_alias_relation(ecrt):
    """ "kiss" exactly equals one dependency's own name — that wins over a
    *different* dependency whose alias merely relates to it."""
    deps = [("kiss-chart", "kiss"), ("kiss", "k")]
    assert ecrt.component_and_alias("kiss", deps) == ("kiss", "k")


def test_component_and_alias_unresolved_is_unknown(ecrt):
    """ "Open Zaak" doesn't match any dependency at all — "component"
    becomes UNKNOWN rather than left blank or guessed at, and "alias"
    stays empty."""
    assert ecrt.component_and_alias("Open Zaak", []) == ("UNKNOWN", "")


def test_component_and_alias_exact_alias_match_beats_substring_ambiguity(ecrt):
    """ "kiss" exactly equals "kiss-chart"'s own alias "kiss" — that must
    resolve outright, even though "eck-stack"'s alias "kiss-eck" also
    happens to *contain* "kiss" as a substring. An exact alias match is
    its own tier, ahead of the looser substring-relation tier, precisely
    so this isn't treated as an ambiguity."""
    deps = [("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")]
    assert ecrt.component_and_alias("kiss", deps) == ("kiss-chart", "kiss")


def test_component_and_alias_multiple_when_two_dependencies_share_exact_alias(ecrt):
    """A genuine ambiguity at the exact-alias tier: two dependencies
    that (however unusually) share the literal same alias — there's no
    principled way to prefer one over the other."""
    deps = [("foo-chart", "shared"), ("bar-chart", "shared")]
    assert ecrt.component_and_alias("shared", deps) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_multiple_alias_relation_matches_is_multiple(ecrt):
    """A genuine ambiguity at the (looser, substring) alias-relation
    tier: "somekisseck" isn't an exact alias match for either dependency
    (ruling out tier 2), but contains both "kiss-chart"'s alias "kiss"
    and "eck-stack"'s alias "kiss-eck" as substrings."""
    deps = [("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")]
    assert ecrt.component_and_alias("somekisseck", deps) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_multiple_name_relation_matches_is_multiple(ecrt):
    """Same ambiguity, but at the (alias-less) name-relation tier: "foo"
    relates to both dependency names "foobar" and "foobaz"."""
    deps = [("foobar", ""), ("foobaz", "")]
    assert ecrt.component_and_alias("foo", deps) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_clean_exact_match_short_circuits_ambiguous_lower_tier(ecrt):
    """A single exact-name match at tier 1 resolves immediately —
    without ever reaching the looser alias-relation tier, which would
    otherwise have been ambiguous between "kiss-chart" and "eck-stack"
    for this same text."""
    deps = [("kiss", "k"), ("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")]
    assert ecrt.component_and_alias("kiss", deps) == ("kiss", "k")


# --- orphan_values_yaml_keys ---


def test_orphan_values_yaml_keys_returns_keys_not_covered_by_any_dependency(ecrt, tmp_path):
    write_values_yaml(tmp_path, ["frankgateway", "global", "zac"])
    deps = [("zaakafhandelcomponent", "zac")]
    assert sorted(ecrt.orphan_values_yaml_keys(tmp_path, deps)) == [("frankgateway", ""), ("global", "")]


def test_orphan_values_yaml_keys_excludes_keys_matching_a_dependency_name(ecrt, tmp_path):
    """A values.yaml key equal to a dependency's own name (not just its
    alias) is also excluded — e.g. "keycloak-operator" itself, not just
    the alias-style keys."""
    write_values_yaml(tmp_path, ["keycloak-operator", "frankgateway"])
    deps = [("keycloak-operator", "")]
    assert ecrt.orphan_values_yaml_keys(tmp_path, deps) == [("frankgateway", "")]


def test_orphan_values_yaml_keys_missing_values_yaml_returns_empty(ecrt, tmp_path):
    assert ecrt.orphan_values_yaml_keys(tmp_path, []) == []


# --- component_and_alias: orphan key fallback ---


def test_component_and_alias_resolves_via_orphan_key(ecrt):
    """ "Frank Gateway" matches no real dependency at all, but exactly
    equals the orphan values.yaml key "frankgateway" — resolved as a
    last resort, with alias left empty (orphan keys aren't Chart.yaml
    aliases)."""
    assert ecrt.component_and_alias("Frank Gateway", [], [("frankgateway", "")]) == ("frankgateway", "")


def test_component_and_alias_real_dependency_always_wins_over_orphan_key(ecrt):
    """An orphan key must never hijack a name that already resolves
    through a real dependency, even if the orphan key would also
    relate — e.g. values.yaml's own "keycloak" block (the Keycloak
    instance's own config) must not steal "Keycloak" away from
    correctly resolving to dependency "keycloak-operator" via the
    name-relation tier."""
    deps = [("keycloak-operator", "")]
    orphans = [("keycloak", "")]
    assert ecrt.component_and_alias("Keycloak", deps, orphans) == ("keycloak-operator", "")


def test_component_and_alias_orphan_key_multiple(ecrt):
    """The same ambiguity detection applies to the orphan-key fallback
    pool: two orphan keys relating to the same text is MULTIPLE, not a
    silent pick."""
    orphans = [("foobar", ""), ("foobaz", "")]
    assert ecrt.component_and_alias("foo", [], orphans) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_still_unknown_when_no_orphan_key_relates_either(ecrt):
    assert ecrt.component_and_alias("Open Zaak", [], [("frankgateway", "")]) == ("UNKNOWN", "")


# --- global_image_keys ---


def test_global_image_keys_returns_keys_under_global_images(ecrt, tmp_path):
    write_values_yaml_with_global_images(tmp_path, ["nginx", "curl", "busybox"])
    assert ecrt.global_image_keys(tmp_path) == ["nginx", "curl", "busybox"]


def test_global_image_keys_missing_values_yaml_returns_empty(ecrt, tmp_path):
    assert ecrt.global_image_keys(tmp_path) == []


def test_global_image_keys_missing_global_images_returns_empty(ecrt, tmp_path):
    write_values_yaml(tmp_path, ["frankgateway"])
    assert ecrt.global_image_keys(tmp_path) == []


# --- component_and_alias: global image key fallback ---


def test_component_and_alias_global_image_key_is_always_multiple(ecrt):
    """ "Nginx unprivileged" relates to nothing else at all, but does
    relate to global image key "nginx" — a key that exists specifically
    because it's shared, via YAML anchor, across multiple unrelated
    components, so it's reported as MULTIPLE rather than a single
    component, even though only one key matched."""
    assert ecrt.component_and_alias("Nginx unprivileged", [], [], ["nginx", "curl", "busybox"]) == (
        "MULTIPLE",
        "MULTIPLE",
    )


def test_component_and_alias_real_dependency_always_wins_over_global_image_key(ecrt):
    """A global image key must never hijack a name that already resolves
    through a real dependency or an orphan key."""
    deps = [("nginx-ingress", "nginx")]
    assert ecrt.component_and_alias("nginx", deps, [], ["nginx"]) == ("nginx-ingress", "nginx")


def test_component_and_alias_orphan_key_wins_over_global_image_key(ecrt):
    orphans = [("nginx", "")]
    assert ecrt.component_and_alias("nginx", [], orphans, ["nginx"]) == ("nginx", "")


def test_component_and_alias_still_unknown_when_no_global_image_key_relates_either(ecrt):
    assert ecrt.component_and_alias("Solr", [], [], ["nginx", "curl", "busybox"]) == ("UNKNOWN", "")


def test_component_and_alias_global_image_key_overrides_coincidental_loose_dependency_match(ecrt):
    """Regression test (real bug, real export): "Redis" (the shared
    global.images.redis anchor) must resolve MULTIPLE, not hijacked by
    the wholly unrelated "redis-operator" dependency just because "redis"
    happens to be a substring of "redisoperator" (redis-operator has no
    alias, so this can only ever be a loose tier-4 name relation, never
    an exact match) — a global image key is a much stronger "genuinely
    shared" signal than that coincidence."""
    deps = [("redis-operator", "")]
    assert ecrt.component_and_alias("Redis", deps, [], ["redis"]) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_exact_dependency_match_still_wins_despite_global_image_key(ecrt):
    """The override above must never fire for an EXACT match — only a
    loose-relation-only resolution is at risk of being a coincidental
    false positive."""
    deps = [("redis-operator", "redis")]
    assert ecrt.component_and_alias("redis", deps, [], ["redis"]) == ("redis-operator", "redis")


# --- extract_release_rows ---


def test_extract_release_rows_matches_and_reports(ecrt, capsys):
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]
    out = capsys.readouterr().out
    assert "2 row(s) matched" in out


def test_extract_release_rows_resolves_component_and_alias_by_exact_match(ecrt, tmp_path):
    """A Chart.yaml dependency named exactly "zac" (with spaces stripped,
    identical to the row's own "ZAC") that also has an alias resolves
    "component"/"alias" for that row; "Open Zaak" doesn't match any
    dependency name this way and stays UNKNOWN. Uses a deliberately
    non-colliding alias ("zacalias") — a too-short one (e.g. "z") would
    spuriously substring-match "Open Zaak" too and defeat the point of
    this test."""
    write_chart_yaml_with_dependencies(tmp_path, [("zac", "zacalias")])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "zac", "zacalias", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


def test_extract_release_rows_resolves_component_and_alias_by_alias_substring(ecrt, tmp_path):
    """ "ZAC" doesn't equal dependency name "zaakafhandelcomponent"
    exactly, but the dependency's own alias "zac" is a substring of it —
    this is the rule that resolves most real components (see
    component_and_alias)."""
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


def test_extract_release_rows_resolves_component_without_alias_via_name_relation(ecrt, tmp_path):
    """ "Open Zaak" resolves purely via a name relation against a
    dependency that has no alias at all — "component" gets that
    dependency's name and "alias" stays empty. "ZAC" doesn't relate to
    "openzaak" at all and stays UNKNOWN."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", None)])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows[0][4] == "UNKNOWN"
    assert rows[1] == ["Product", "Maykin", "", "Open Zaak", "openzaak", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"]


def test_extract_release_rows_not_tied_to_specific_version_numbers(ecrt):
    """The page renames "Versie 4.8"/"Versie 4.9" every release — a table
    headed "Versie 5.0"/"Versie 5.1" instead must resolve exactly the
    same way, into "source"/"target" by column order, not by number."""
    html = PRODUCT_TABLE_HTML.replace("Versie 4.8", "Versie 5.0").replace("Versie 4.9", "Versie 5.1")
    rows = ecrt.extract_release_rows(html)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


def test_extract_release_rows_replaces_non_semver_version_with_unknown_and_reports_count(ecrt, capsys):
    html = PRODUCT_TABLE_HTML.replace("<td>5.1.0</td>", "<td>?</td>")
    rows = ecrt.extract_release_rows(html)
    assert rows[0] == ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "", "5.0.0", "1.0.290", "UNKNOWN", "1.0.297"]
    out = capsys.readouterr().out
    assert "1 version value(s) were not semver-compatible — replaced with UNKNOWN" in out
    assert 'WARNING: "ZAC": target_version_app is not semver-compatible — replaced with UNKNOWN' in out
    # "ZAC" also resolves to component UNKNOWN here (no Chart.yaml/values.yaml
    # at all under the isolated chart_dir this test runs against).
    assert (
        'WARNING: "ZAC" did not resolve to any Chart.yaml dependency, orphan values.yaml key, or global image key'
    ) in out


def test_extract_release_rows_ignores_table_not_under_any_target_heading(ecrt, capsys):
    html = UNRELATED_TABLE_HTML + PRODUCT_TABLE_HTML
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2
    out = capsys.readouterr().out
    assert "Found 2 table(s) on the page, 1 under a matching heading" in out
    assert "Legend" not in out  # the unrelated table was never even reported on


def test_extract_release_rows_reports_skip_for_incomplete_table_under_target_heading(ecrt, capsys):
    html = INCOMPLETE_UNDER_TARGET_HEADING_HTML + PRODUCT_TABLE_HTML
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2
    out = capsys.readouterr().out
    assert '"Overige component versies": skipped (missing required column(s):' in out


def test_extract_release_rows_vendor_blank_used_by_populated_for_technische_table(ecrt, capsys):
    """A "Technische component versies" table has no Ontwikkelpartij
    column (vendor blank) but does have "Used by" — the reverse of a
    Product table."""
    rows = ecrt.extract_release_rows(TECHNISCHE_TABLE_HTML)
    assert rows == [
        ["Technische", "", "ZAC", "Elastic operator", "UNKNOWN", "", "", "3.4.0", "3.4.0", "3.5.0", "3.5.0"]
    ]
    out = capsys.readouterr().out
    assert (
        'WARNING: "Elastic operator" (used_by "ZAC") did not resolve to any Chart.yaml '
        "dependency, orphan values.yaml key, or global image key"
    ) in out


def test_extract_release_rows_technische_table_without_helm_column(ecrt):
    """Since 2026-09 the real page's "Technische component versies" table
    has no Helm sub-column at all (it was always empty) -- the row must
    still be exported, with blank source/target_version_helm cells
    instead of being skipped as missing a required column."""
    rows = ecrt.extract_release_rows(TECHNISCHE_TABLE_NO_HELM_HTML)
    assert rows == [["Technische", "", "ZAC", "Elastic operator", "UNKNOWN", "", "", "3.4.0", "", "3.5.0", ""]]
