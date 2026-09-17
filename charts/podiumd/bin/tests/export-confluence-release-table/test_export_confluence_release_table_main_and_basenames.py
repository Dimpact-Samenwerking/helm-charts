"""main() integration tests, and basenames_under_scope / _match_one /
resolve_image_basenames — with fetch_page_html mocked out, so no network
access or real Confluence page is needed."""

import csv


def write_chart_yaml_with_dependencies(chart_dir, deps):
    """`deps`: [(name, alias_or_None), ...]."""
    lines = ["apiVersion: v2", "name: podiumd", "version: 1.0.0", "dependencies:"]
    for name, alias in deps:
        lines.append(f"  - name: {name}")
        if alias:
            lines.append(f"    alias: {alias}")
        lines += ["    version: 1.0.0", '    repository: "@x"']
    (chart_dir / "Chart.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


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


# --- main() integration ---


def test_main_writes_csv(ecrt, tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "release-table.csv"
    monkeypatch.setattr(
        ecrt.sys,
        "argv",
        [
            "export-confluence-release-table",
            "--url",
            "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
            "--user",
            "kees@info.nl",
            "--token",
            "s3cr3t",
            "--output",
            str(output_path),
        ],
    )
    monkeypatch.setattr(ecrt, "fetch_page_html", lambda url, user, token: PRODUCT_TABLE_HTML)

    ecrt.main()

    with output_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == [
        "section",
        "vendor",
        "used_by",
        "name",
        "component",
        "alias",
        "image_basename",
        "source_version_app",
        "source_version_helm",
        "target_version_app",
        "target_version_helm",
    ]
    assert rows[1] == ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"]
    assert rows[2] == ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"]
    out = capsys.readouterr().out
    assert f"Wrote 2 row(s) to {output_path}" in out


def test_main_passes_resolved_token_and_url_user_through(ecrt, tmp_path, monkeypatch):
    output_path = tmp_path / "out.csv"
    monkeypatch.setattr(
        ecrt.sys,
        "argv",
        [
            "export-confluence-release-table",
            "--url",
            "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
            "--user",
            "kees@info.nl",
            "--token",
            "s3cr3t",
            "--output",
            str(output_path),
        ],
    )
    captured = {}

    def fake_fetch(url, user, token):
        captured.update(url=url, user=user, token=token)
        return PRODUCT_TABLE_HTML

    monkeypatch.setattr(ecrt, "fetch_page_html", fake_fetch)
    ecrt.main()
    assert captured == {
        "url": "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "user": "kees@info.nl",
        "token": "s3cr3t",
    }


def test_main_passes_custom_heading_flags_through(ecrt, tmp_path, monkeypatch):
    output_path = tmp_path / "out.csv"
    monkeypatch.setattr(
        ecrt.sys,
        "argv",
        [
            "export-confluence-release-table",
            "--url",
            "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
            "--user",
            "kees@info.nl",
            "--token",
            "s3cr3t",
            "--output",
            str(output_path),
            "--heading",
            "Technische component versies",
        ],
    )
    monkeypatch.setattr(ecrt, "fetch_page_html", lambda url, user, token: PRODUCT_TABLE_HTML + TECHNISCHE_TABLE_HTML)

    ecrt.main()

    with output_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2  # header + the one Technische row only
    assert rows[1][0] == "Technische"


def test_main_writes_lf_line_endings(ecrt, tmp_path, monkeypatch):
    """csv's own "excel" dialect defaults to CRLF regardless of platform —
    every other file in this repo (and git) is LF, so a CRLF write would
    diff on every single re-export even when nothing actually changed."""
    output_path = tmp_path / "out.csv"
    monkeypatch.setattr(
        ecrt.sys,
        "argv",
        [
            "export-confluence-release-table",
            "--url",
            "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
            "--user",
            "kees@info.nl",
            "--token",
            "s3cr3t",
            "--output",
            str(output_path),
        ],
    )
    monkeypatch.setattr(ecrt, "fetch_page_html", lambda url, user, token: PRODUCT_TABLE_HTML)

    ecrt.main()

    raw = output_path.read_bytes()
    assert b"\r\n" not in raw
    assert b"\n" in raw


# --- basenames_under_scope / _match_one / resolve_image_basenames ---

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def write_values_yaml_raw(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def test_match_one_exact_beats_containment(ecrt):
    """ "Solr" exactly equals candidate "solr", so it must win outright —
    even though "solr" also relates to "solr-operator" by containment."""
    assert ecrt._match_one("Solr", {"solr", "solr-operator"}) == "solr"


def test_match_one_falls_back_to_unambiguous_containment(ecrt):
    """ "Redis-ha" doesn't exactly equal any candidate, but relates to
    exactly one ("redis", contained in "redisha") — resolved via the
    fallback tier."""
    assert ecrt._match_one("Redis-ha", {"redis-operator", "redis", "redis-exporter"}) == "redis"


def test_match_one_bracket_content_resolves_a_role_named_row(ecrt):
    """ "Zookeeper operator hooks (k8s-kubectl)" shares no text at all with
    "k8s-kubectl" as a whole string, but name_candidates' bracket
    extraction tries the bracket content on its own, which matches
    exactly."""
    assert ecrt._match_one("Zookeeper operator hooks (k8s-kubectl)", {"k8s-kubectl", "solr"}) == "k8s-kubectl"


def test_match_one_ambiguous_exact_match_is_none(ecrt):
    """ "Foo (Bar)" yields candidates "foobar", "foo", AND "bar" (see
    name_candidates) — two DIFFERENT options each exactly matching a
    different one of those candidates is still an ambiguity, never a
    guess."""
    assert ecrt._match_one("Foo (Bar)", {"foo", "bar"}) is None


def test_match_one_no_relation_is_none(ecrt):
    assert ecrt._match_one("ITA Poller", {"internetaakafhandeling.poller"}) is None


def test_basenames_under_scope_finds_nested_pins(ecrt, tmp_path):
    write_values_yaml_raw(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
  solr-operator:
    image:
      repository: apache/solr-operator
      tag: "0.9.1@sha256:{DIGEST_B}"
""",
    )
    lines = (tmp_path / "values.yaml").read_text(encoding="utf-8").splitlines()
    available = ecrt.basenames_under_scope(lines, "zac")
    assert set(available) == {"zaakafhandelcomponent", "solr-operator"}


def test_basenames_under_scope_ignores_other_components(ecrt, tmp_path):
    write_values_yaml_raw(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
openzaak:
  image:
    repository: openzaak/open-zaak
    tag: "1.0.0@sha256:{DIGEST_B}"
""",
    )
    lines = (tmp_path / "values.yaml").read_text(encoding="utf-8").splitlines()
    assert set(ecrt.basenames_under_scope(lines, "zac")) == {"zaakafhandelcomponent"}


def test_resolve_image_basenames_missing_values_yaml_is_blank(ecrt, tmp_path):
    rows = [["Product", "", "", "ZAC", "zaakafhandelcomponent", "zac", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == [""]


def test_resolve_image_basenames_technische_row_matches_its_own_image(ecrt, tmp_path):
    write_values_yaml_raw(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
  solr-operator:
    image:
      repository: apache/solr-operator
      tag: "0.9.1@sha256:{DIGEST_B}"
""",
    )
    rows = [
        ["Product", "", "", "Zaak - ZAC", "zaakafhandelcomponent", "zac", "1", "1", "1", "1"],
        ["Technische", "", "zac", "Solr operator", "zaakafhandelcomponent", "zac", "1", "1", "1", "1"],
    ]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["zaakafhandelcomponent", "solr-operator"]


def test_resolve_image_basenames_role_named_row_resolves_via_bracket_hint(ecrt, tmp_path):
    write_values_yaml_raw(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
  solr-operator:
    zookeeper-operator:
      hooks:
        image:
          repository: lachlanevenson/k8s-kubectl
          tag: "v1.25.4@sha256:{DIGEST_C}"
""",
    )
    rows = [
        ["Product", "", "", "Zaak - ZAC", "zaakafhandelcomponent", "zac", "1", "1", "1", "1"],
        [
            "Technische",
            "",
            "zac",
            "Zookeeper operator hooks (k8s-kubectl)",
            "zaakafhandelcomponent",
            "zac",
            "1",
            "1",
            "1",
            "1",
        ],
    ]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["zaakafhandelcomponent", "k8s-kubectl"]


def test_resolve_image_basenames_primary_row_gets_leftover_after_technische_claims(ecrt, tmp_path):
    """Once every "used_by"-tagged sibling has claimed its own basename,
    whatever's left under that component's scope — here, just its own
    top-level image — goes to the primary (used_by-blank) row."""
    write_values_yaml_raw(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
  solr-operator:
    image:
      repository: apache/solr-operator
      tag: "0.9.1@sha256:{DIGEST_B}"
""",
    )
    rows = [
        ["Product", "", "", "Zaak - ZAC", "zaakafhandelcomponent", "zac", "1", "1", "1", "1"],
        ["Technische", "", "zac", "Solr operator", "zaakafhandelcomponent", "zac", "1", "1", "1", "1"],
    ]
    basenames = ecrt.resolve_image_basenames(rows, tmp_path)
    assert basenames[0] == "zaakafhandelcomponent"


def test_resolve_image_basenames_primary_claims_its_own_name_before_siblings(ecrt, tmp_path):
    """frankgateway's own default image is literally named "frank-gateway"
    (same as the component's own plain display name) — every sibling
    "Frank Gateway <Role>" row's name trivially CONTAINS that same
    "frankgateway" prefix too, so if a sibling got first refusal it would
    wrongly claim "frank-gateway" for itself (verified bug: "Frank Gateway
    Dashboard" claiming "frank-gateway", leaving the real "Frank Gateway"
    row stuck with "apisix-dashboard" as its only leftover). The primary
    row's own unambiguous exact match must be claimed FIRST so this can't
    happen; "Dashboard" itself shares no text with "apisix-dashboard" at
    all, so it's correctly left blank rather than guessed (same
    never-guess policy as test_resolve_image_basenames_unresolvable_technische_row_is_blank)."""
    write_values_yaml_raw(
        tmp_path,
        f"""\
frankgateway:
  image:
    repository: ghcr.io/wearefrank/frank-gateway
    tag: "104@sha256:{DIGEST_A}"
  dashboard:
    image:
      repository: apache/apisix-dashboard
      tag: "3.0.1-alpine@sha256:{DIGEST_B}"
""",
    )
    rows = [
        ["Common Ground", "WeAreFrank", "", "Frank Gateway", "frankgateway", "", "1", "1", "1", "1"],
        ["Technische", "", "frankgateway", "Frank Gateway Dashboard", "frankgateway", "", "1", "1", "1", "1"],
    ]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["frank-gateway", ""]


def test_resolve_image_basenames_primary_row_first_refusal_is_exact_match_only(ecrt, tmp_path):
    """redis-operator's own primary row name ("Redis Operator") merely
    CONTAINS basename "redis" as a substring ("redisoperator") — a much
    weaker signal than frankgateway's EXACT match. Letting primary claim
    on this fuzzy tier too regressed this real case: "redis" (the actual
    Redis server image) belongs to the more specific "Redis-ha" sibling
    row, not the generic "Redis Operator" umbrella row (whose own target
    version is the operator CHART's own release number, not any single
    image's version at all — it correctly stays blank, exactly as before
    this whole fix)."""
    write_values_yaml_raw(
        tmp_path,
        f"""\
redis-operator:
  redis:
    image:
      repository: quay.io/opstree/redis
      tag: "v8.6.6@sha256:{DIGEST_A}"
    exporter:
      image:
        repository: quay.io/opstree/redis-exporter
        tag: "v1.89.0@sha256:{DIGEST_B}"
""",
    )
    rows = [
        ["Overige", "", "", "Redis Operator", "redis-operator", "", "1", "1", "1", "1"],
        ["Technische", "", "redis-operator", "Redis-ha", "redis-operator", "", "1", "1", "1", "1"],
        ["Technische", "", "redis-operator", "Redis Exporter", "redis-operator", "", "1", "1", "1", "1"],
    ]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["", "redis", "redis-exporter"]


def test_resolve_image_basenames_primary_row_gets_multiple_leftover_basenames(ecrt, tmp_path):
    """A component with no Technische breakdown at all (e.g.
    zgw-office-addin, whose frontend and backend always move in
    lockstep and share one row/version) gets every leftover basename
    comma-joined onto its single primary row."""
    write_values_yaml_raw(
        tmp_path,
        f"""\
zgw-office-addin:
  frontend:
    image:
      repository: ghcr.io/infonl/zgw-office-addin-frontend
      tag: "0.11.0@sha256:{DIGEST_A}"
  backend:
    image:
      repository: ghcr.io/infonl/zgw-office-addin-backend
      tag: "0.11.0@sha256:{DIGEST_B}"
""",
    )
    rows = [["Product", "", "", "Office Add-in", "zgw-office-addin", "", "1", "1", "1", "1"]]
    basenames = ecrt.resolve_image_basenames(rows, tmp_path)
    assert set(basenames[0].split(",")) == {"zgw-office-addin-frontend", "zgw-office-addin-backend"}


def test_resolve_image_basenames_unresolvable_technische_row_is_blank(ecrt, tmp_path):
    """ "ITA Poller" shares no text at all with the actual repository
    basename ("internetaakafhandeling.poller") — left blank rather than
    guessed."""
    write_values_yaml_raw(
        tmp_path,
        f"""\
ita:
  poller:
    image:
      repository: ghcr.io/interne-taak-afhandeling/internetaakafhandeling.poller
      tag: "3.2.0@sha256:{DIGEST_A}"
""",
    )
    rows = [["Technische", "", "ita", "ITA Poller", "internetaakafhandeling", "ita", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == [""]


def test_resolve_image_basenames_multiple_row_resolves_via_global_image_key(ecrt, tmp_path):
    write_values_yaml_raw(
        tmp_path,
        f"""\
global:
  images:
    curl:
      repository: curlimages/curl
      tag: "8.21.0@sha256:{DIGEST_A}"
""",
    )
    rows = [["Overige", "", "", "curl", "MULTIPLE", "MULTIPLE", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["curl"]


def test_resolve_image_basenames_multiple_row_no_repository_is_blank(ecrt, tmp_path):
    write_values_yaml_raw(tmp_path, "global:\n  images:\n    curl: {}\n")
    rows = [["Overige", "", "", "curl", "MULTIPLE", "MULTIPLE", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == [""]


def test_resolve_image_basenames_unknown_component_is_blank(ecrt, tmp_path):
    write_values_yaml_raw(tmp_path, "")
    rows = [["Technische", "", "", "python image", "UNKNOWN", "", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == [""]


def test_resolve_image_basenames_finds_image_under_a_related_orphan_key(ecrt, tmp_path):
    """keycloak-operator's real app image lives under the separate
    "keycloak" values.yaml block (podiumd's own Keycloak instance
    config), not under "keycloak-operator" itself — an orphan key that
    itself relates to the dependency (see _extra_scope_keys_by_component)
    must be scanned too, not just the dependency's own top-level key."""
    write_chart_yaml_with_dependencies(tmp_path, [("keycloak-operator", None)])
    write_values_yaml_raw(
        tmp_path,
        f"""\
keycloak-operator:
  jobs:
    ensurePodiumdAdminUser:
      initImage:
        repository: python
        tag: "3.14.7-slim@sha256:{DIGEST_A}"
keycloak:
  image:
    repository: quay.io/keycloak/keycloak
    tag: "26.7.2@sha256:{DIGEST_B}"
""",
    )
    rows = [
        ["Overige", "", "", "Keycloak", "keycloak-operator", "", "1", "1", "1", "1"],
        ["Technische", "", "keycloak-operator", "Python", "keycloak-operator", "", "1", "1", "1", "1"],
    ]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["keycloak", "python"]


def test_extra_scope_keys_by_component_ignores_multiple_and_unrelated_orphan_keys(ecrt, tmp_path):
    write_chart_yaml_with_dependencies(tmp_path, [("keycloak-operator", None), ("frankgateway", None)])
    write_values_yaml_raw(tmp_path, "keycloak: {}\nunrelated: {}\n")
    extra = ecrt._extra_scope_keys_by_component(tmp_path)
    assert extra == {"keycloak-operator": ["keycloak"]}


def test_extract_release_rows_end_to_end_populates_image_basename(ecrt, tmp_path):
    """extract_release_rows itself, not just resolve_image_basenames in
    isolation, must insert the resolved basename at the right column."""
    write_chart_yaml_with_dependencies(tmp_path, [("zaakafhandelcomponent", "zac")])
    values_path = tmp_path / "values.yaml"
    values_path.write_text(
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
""",
        encoding="utf-8",
    )
    html = PRODUCT_TABLE_HTML.replace("<td>ZAC</td>", "<td>ZAC</td>")
    rows = ecrt.extract_release_rows(html, chart_dir=tmp_path)
    assert rows[0] == [
        "Product",
        "Info(NL)",
        "",
        "ZAC",
        "zaakafhandelcomponent",
        "zac",
        "zaakafhandelcomponent",
        "5.0.0",
        "1.0.290",
        "5.1.0",
        "1.0.297",
    ]


def test_resolve_image_basenames_falls_back_to_any_tag_when_digest_required_scan_is_empty(ecrt, tmp_path):
    """omc's real shape: its own image.tag has NO digest at all (its
    subchart can't handle one) — the digest-required basenames_under_
    scope finds nothing under "omc" at all, so resolve_image_basenames
    must fall back to the digest-optional basenames_under_scope_any_tag
    instead of leaving the row blank."""
    write_values_yaml_raw(
        tmp_path,
        """\
omc:
  image:
    # repository: docker.io/worthnl/notifynl-omc
    tag: "1.17.19"
""",
    )
    rows = [["Product", "", "", "OMC / Notify", "notifynl-omc-nodep", "omc", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["notifynl-omc"]


def test_resolve_image_basenames_any_tag_fallback_does_not_override_digest_scan_result(ecrt, tmp_path):
    """A basename the digest-required scan already found is never
    replaced by the any_tag fallback (the fallback is strictly additive,
    per-basename — see test_resolve_image_basenames_any_tag_fallback_
    supplements_a_partially_digest_pinned_component below for the case
    where it genuinely adds something new): a component that's fully
    digest-pinned is completely unaffected by the fallback existing at
    all."""
    write_values_yaml_raw(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
""",
    )
    rows = [["Product", "", "", "Zaak - ZAC", "zaakafhandelcomponent", "zac", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["zaakafhandelcomponent"]


def test_resolve_image_basenames_any_tag_fallback_supplements_a_partially_digest_pinned_component(ecrt, tmp_path):
    """Regression test (real bug, real chart): keycloak-operator's own
    operator.config.keycloakImage pins its digest as a separate sibling
    "sha:" field (never embedded in "tag:"), so the digest-required scan
    can never see it — but keycloak-operator's OTHER image (its own
    admin-user init container) IS fully digest-pinned, so the whole-
    component's own digest-required scan is NOT empty. Before this fix,
    the any_tag fallback only ever fired when a component's ENTIRE scope
    came up empty (see the omc case above) — a component that's only
    PARTIALLY resolvable via the digest-required scan silently kept its
    own unresolvable basename blank forever, exactly the real gap behind
    verify-release-table-with-podiumd's own former special_case_tag_path
    workaround. The fallback must now be tried per-basename: "keycloak"
    (only resolvable via any_tag) gets added, "python" (already resolved
    via the digest-required scan) is untouched by it."""
    write_values_yaml_raw(
        tmp_path,
        f"""\
keycloak-operator:
  operator:
    config:
      keycloakImage:
        repository: &keycloakImageRepo quay.io/keycloak/keycloak
        tag: &keycloakImageVersion "26.7.3"
        sha: &keycloakImageDigest "{DIGEST_A}"
  jobs:
    ensurePodiumdAdminUser:
      initImage:
        repository: python
        tag: "3.14-slim@sha256:{DIGEST_A}"
""",
    )
    rows = [["Overige", "", "", "Keycloak", "keycloak-operator", "", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["keycloak"]
