"""main() and image-basename resolution, with fetch_page_html mocked."""

import csv

from pathlib import Path
from types import ModuleType

import pytest

from lib.image.version import basenames_under_scope
from lib.release_table.component_resolution import exact_match


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


# --- main() integration ---


def test_main_writes_csv(
    ecrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
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
    captured = capsys.readouterr()
    assert f"Wrote 2 row(s) to {output_path}" in captured.out
    assert f"WARNING: 2 line(s) in {output_path} contain UNKNOWN:" in captured.err
    assert '  line 2: "ZAC" (component)' in captured.err
    assert '  line 3: "Open Zaak" (component)' in captured.err


def test_main_passes_resolved_token_and_url_user_through(
    ecrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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


def test_main_passes_custom_heading_flags_through(ecrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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


def test_main_writes_lf_line_endings(ecrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """csv's "excel" dialect writes CRLF; the repo is LF, so every re-export
    would otherwise show a diff."""
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


# --- basenames_under_scope / exact_match / resolve_image_basenames ---

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def write_values_yaml_raw(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def test_exact_match_whole_name():
    assert exact_match("Solr", {"solr", "solr-operator"}) == "solr"


def test_exact_match_never_falls_back_to_containment():
    """Containment is not a match: the Confluence name must say "Redis HA (redis)"."""
    assert exact_match("Redis-ha", {"redis-operator", "redis", "redis-exporter"}) is None
    assert exact_match("Redis HA (redis)", {"redis-operator", "redis", "redis-exporter"}) == "redis"


def test_exact_match_bracket_content_resolves_a_role_named_row():
    """The bracket content alone is tried as a candidate and matches exactly."""
    assert exact_match("Zookeeper operator hooks (k8s-kubectl)", {"k8s-kubectl", "solr"}) == "k8s-kubectl"


def test_exact_match_ambiguous_is_none():
    """Different options exactly matching different candidates of "Foo (Bar)"
    is an ambiguity, never a guess."""
    assert exact_match("Foo (Bar)", {"foo", "bar"}) is None


def test_exact_match_no_match_is_none():
    assert exact_match("ITA Poller", {"internetaakafhandeling.poller"}) is None


def test_basenames_under_scope_finds_nested_pins(tmp_path: Path):
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
    available = basenames_under_scope(lines, "zac")
    assert set(available) == {"zaakafhandelcomponent", "solr-operator"}


def test_basenames_under_scope_ignores_other_components(tmp_path: Path):
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
    assert set(basenames_under_scope(lines, "zac")) == {"zaakafhandelcomponent"}


def test_resolve_image_basenames_missing_values_yaml_is_blank(ecrt: ModuleType, tmp_path: Path):
    rows = [["Product", "", "", "ZAC", "zaakafhandelcomponent", "zac", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == [""]


def test_resolve_image_basenames_technische_row_matches_its_own_image(ecrt: ModuleType, tmp_path: Path):
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


def test_resolve_image_basenames_role_named_row_resolves_via_bracket_hint(ecrt: ModuleType, tmp_path: Path):
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


def test_resolve_image_basenames_primary_row_gets_leftover_after_technische_claims(ecrt: ModuleType, tmp_path: Path):
    """After used_by siblings claim theirs, the registered primary image goes
    to the primary (used_by-blank) row."""
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


def test_resolve_image_basenames_primary_claims_its_own_name_before_siblings(ecrt: ModuleType, tmp_path: Path):
    """The primary row's exact match is claimed first: every "Frank Gateway
    <Role>" sibling also contains "frankgateway" and would otherwise steal
    "frank-gateway". An unmatched sibling stays blank, never guessed."""
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


def test_resolve_image_basenames_primary_row_first_refusal_is_exact_match_only(ecrt: ModuleType, tmp_path: Path):
    """ "Redis Operator" merely contains "redis": "redis" goes to the sibling
    naming it exactly, and the operator row (versioned by its chart) stays
    blank."""
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
        ["Technische", "", "redis-operator", "Redis HA (redis)", "redis-operator", "", "1", "1", "1", "1"],
        ["Technische", "", "redis-operator", "Redis Exporter", "redis-operator", "", "1", "1", "1", "1"],
    ]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["", "redis", "redis-exporter"]
    rows[1][3] = "Redis-ha"  # only contains "redis": no exact match
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["", "", "redis-exporter"]


def test_resolve_image_basenames_primary_row_gets_multiple_leftover_basenames(ecrt: ModuleType, tmp_path: Path):
    """Several registered primary images (zgw-office-addin frontend/backend,
    one shared version) are comma-joined on the primary row."""
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


def test_resolve_image_basenames_unresolvable_technische_row_is_blank(ecrt: ModuleType, tmp_path: Path):
    """No shared text with the actual basename: left blank, not guessed."""
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


def test_resolve_image_basenames_multiple_row_resolves_via_global_image_key(ecrt: ModuleType, tmp_path: Path):
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


def test_resolve_image_basenames_multiple_row_no_repository_is_blank(ecrt: ModuleType, tmp_path: Path):
    write_values_yaml_raw(tmp_path, "global:\n  images:\n    curl: {}\n")
    rows = [["Overige", "", "", "curl", "MULTIPLE", "MULTIPLE", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == [""]


def test_resolve_image_basenames_unknown_component_is_blank(ecrt: ModuleType, tmp_path: Path):
    write_values_yaml_raw(tmp_path, "")
    rows = [["Technische", "", "", "python image", "UNKNOWN", "", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == [""]


def test_resolve_image_basenames_native_component_scans_its_own_key(ecrt: ModuleType, tmp_path: Path):
    """Native keycloak is its own component: its server and config-cli images
    resolve under "keycloak", not keycloak-operator."""
    write_chart_yaml_with_dependencies(tmp_path, [("keycloak-operator", None)])
    write_values_yaml_raw(
        tmp_path,
        f"""\
keycloak:
  image:
    repository: quay.io/keycloak/keycloak
    tag: "26.7.3@sha256:{DIGEST_A}"
  keycloakConfigCli:
    image:
      repository: adorsys/keycloak-config-cli
      tag: "6.5.1-26.5.5@sha256:{DIGEST_B}"
keycloak-operator:
  operator:
    image:
      repository: quay.io/keycloak/keycloak-operator
      tag: "26.7.3@sha256:{DIGEST_A}"
""",
    )
    rows = [
        ["Overige", "", "", "Keycloak", "keycloak", "", "1", "NATIVE", "1", "NATIVE"],
        ["Overige", "", "", "Keycloak operator", "keycloak-operator", "", "1", "1", "1", "1"],
        ["Technische", "", "keycloak", "Keycloak Config CLI", "keycloak", "", "", "", "1", ""],
    ]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["keycloak", "keycloak-operator", "keycloak-config-cli"]


def test_extract_release_rows_end_to_end_populates_image_basename(ecrt: ModuleType, tmp_path: Path):
    """extract_release_rows inserts the resolved basename at the right column."""
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


def test_resolve_image_basenames_falls_back_to_any_tag_when_digest_required_scan_is_empty(
    ecrt: ModuleType, tmp_path: Path
):
    """omc's tag has no digest (its subchart can't handle one), so resolution
    must fall back to basenames_under_scope_any_tag."""
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


def test_resolve_image_basenames_any_tag_fallback_does_not_override_digest_scan_result(
    ecrt: ModuleType, tmp_path: Path
):
    """The any_tag fallback is per-basename additive: it never replaces a
    basename the digest-required scan already found."""
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


def test_resolve_image_basenames_any_tag_fallback_supplements_a_partially_digest_pinned_component(
    ecrt: ModuleType, tmp_path: Path
):
    """Regression: keycloak-operator's keycloakImage keeps its digest in a
    sibling "sha:" field, invisible to the digest-required scan, while its
    other image is digest-pinned. The any_tag fallback must run per-basename,
    not only when the whole scope is empty."""
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


def test_resolve_image_basenames_unclaimed_sidecar_is_not_given_to_the_primary_row(ecrt: ModuleType, tmp_path: Path):
    """An unclaimed image off the registered primary paths stays unassigned;
    verify-release-table-with-podiumd reports it."""
    write_values_yaml_raw(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
  opentelemetry-collector:
    image:
      repository: otel/opentelemetry-collector-contrib
      tag: "0.158.0@sha256:{DIGEST_B}"
""",
    )
    rows = [["Product", "", "", "ZAC (zaakafhandelcomponent)", "zaakafhandelcomponent", "zac", "1", "1", "1", "1"]]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == ["zaakafhandelcomponent"]


def test_resolve_image_basenames_multiple_row_resolves_via_global_image_basename(ecrt: ModuleType, tmp_path: Path):
    """A MULTIPLE row may name the global.images entry by its image
    basename instead of its key: "Nginx (nginx-unprivileged)"."""
    write_values_yaml_raw(
        tmp_path,
        f"""\
global:
  images:
    nginx:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.6@sha256:{DIGEST_A}"
""",
    )
    rows = [
        ["Overige", "", "", "Nginx (unprivileged)", "MULTIPLE", "MULTIPLE", "1", "", "1", ""],
        ["Overige", "", "", "Nginx (nginx-unprivileged)", "MULTIPLE", "MULTIPLE", "1", "", "1", ""],
        ["Overige", "", "", "Nginx unprivileged", "MULTIPLE", "MULTIPLE", "1", "", "1", ""],
        ["Overige", "", "", "Nginx proxy", "MULTIPLE", "MULTIPLE", "1", "", "1", ""],
    ]
    assert ecrt.resolve_image_basenames(rows, tmp_path) == [
        "nginx-unprivileged",
        "nginx-unprivileged",
        "nginx-unprivileged",
        "",
    ]


def test_main_missing_output_directory_exits_before_fetching(
    ecrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    output_path = tmp_path / "missing" / "out.csv"
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

    def fail_if_called(*args: object) -> str:
        msg = "must not fetch"
        raise AssertionError(msg)

    monkeypatch.setattr(ecrt, "fetch_page_html", fail_if_called)
    with pytest.raises(SystemExit, match="does not exist"):
        ecrt.main()
