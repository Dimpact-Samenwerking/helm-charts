"""check_oidc_url_coverage — every Keycloak client in
templates/keycloak-podiumd-realm-config.yaml that builds its redirectUris
from a `.Values.<path>` must have that path as the "oidcUrl" of some
`$oidcClients` entry (helm-charts PR #461's review finding, PR #490)."""

from pathlib import Path
from types import ModuleType

import pytest

OIDC_CLIENTS = """\
{{- $oidcClients := list
  (dict "name" "openzaak" "enabled" .Values.openzaak.enabled "oidcUrl" .Values.openzaak.configuration.oidcUrl)
  (dict "name" "zac"      "enabled" .Values.zac.enabled      "oidcUrl" .Values.zac.contextUrl "field" "zac.contextUrl")
-}}
{{- range $oidcClients }}
{{- end }}
"""

OPENZAAK_CLIENT = """\
      - clientId: openzaak
        enabled: true
        redirectUris:
          - "{{ .Values.openzaak.configuration.oidcUrl | trimSuffix "/" }}/*"
        webOrigins:
          - "{{ .Values.openzaak.configuration.oidcUrl | trimSuffix "/" }}/*"
"""

KISS_CLIENT = """\
      - clientId: kiss
        enabled: true
        redirectUris:
          - "{{ .Values.kiss.configuration.oidcUrl | trimSuffix "/" }}/*"
"""

SERVICE_ACCOUNT_CLIENT = """\
      - clientId: admin-cli
        serviceAccountsEnabled: true
"""


def write_realm_config(chart_dir: Path, text: str):
    templates_dir = chart_dir / "templates"
    templates_dir.mkdir(exist_ok=True)
    (templates_dir / "keycloak-podiumd-realm-config.yaml").write_text(text, encoding="utf-8")


def realm(*clients: str, header: str = OIDC_CLIENTS) -> str:
    return header + "data:\n  realm.yaml: |\n    clients:\n" + "".join(clients)


def test_covered_client_passes(vp: ModuleType, tmp_path: Path):
    write_realm_config(tmp_path, realm(OPENZAAK_CLIENT, SERVICE_ACCOUNT_CLIENT))
    ok, detail = vp.check_oidc_url_coverage(tmp_path)
    assert ok is True
    assert "0 uncovered" in detail


def test_uncovered_values_path_fails_naming_client_and_path(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """The PR #461 shape: kiss builds its redirectUris from a value that
    $oidcClients never lists, so an example.nl default renders silently."""
    write_realm_config(tmp_path, realm(OPENZAAK_CLIENT, KISS_CLIENT))
    ok, detail = vp.check_oidc_url_coverage(tmp_path)
    assert ok is False
    assert "1 uncovered" in detail
    out = capsys.readouterr().out
    assert "clientId kiss: .Values.kiss.configuration.oidcUrl" in out
    assert "openzaak" not in out


def test_templated_client_id_is_reported_verbatim(vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """zac/pabc's clientId is itself a template expression — the finding
    still names it (as written) together with the uncovered path."""
    client = """\
      - clientId: {{ .Values.pabc.settings.oidc.clientId }}
        redirectUris:
          - "{{ .Values.pabc.settings.oidc.oidcUrl | trimSuffix "/" }}/*"
"""
    write_realm_config(tmp_path, realm(client))
    ok, _ = vp.check_oidc_url_coverage(tmp_path)
    assert ok is False
    out = capsys.readouterr().out
    assert "clientId {{ .Values.pabc.settings.oidc.clientId }}: .Values.pabc.settings.oidc.oidcUrl" in out


def test_non_values_redirect_expression_is_informational_only(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """frankgateway's dashboard clients build their redirect URI from a
    `range` variable, which can't be mapped to a .Values path statically;
    a literal (OpenBao's CLI callback) can't either. Neither fails."""
    client = """\
{{- range $fgKey, $fgOverride := .Values.frankgateway.instances }}
      - clientId: {{ include "podiumd.frankgateway.oidcClientId" (dict "key" $fgKey) }}
        redirectUris:
          - "https://{{ $fgInst.dashboard.auth.hostname }}/oauth2/callback"
          - "http://localhost:8080/oauth2/callback"
        webOrigins:
          - "+"
{{- end }}
"""
    write_realm_config(tmp_path, realm(OPENZAAK_CLIENT, client))
    ok, detail = vp.check_oidc_url_coverage(tmp_path)
    assert ok is True
    assert "2 unmapped (informational)" in detail
    out = capsys.readouterr().out
    assert "$fgInst.dashboard.auth.hostname" in out
    assert "localhost:8080" in out
    assert "not a .Values path" in out


def test_missing_oidc_clients_list_fails(vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    write_realm_config(tmp_path, realm(OPENZAAK_CLIENT, header=""))
    ok, detail = vp.check_oidc_url_coverage(tmp_path)
    assert ok is False
    assert "$oidcClients list missing" in detail
    assert "no `$oidcClients := list ...` assignment found" in capsys.readouterr().out


def test_missing_template_fails(vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    ok, detail = vp.check_oidc_url_coverage(tmp_path)
    assert ok is False
    assert "realm config template missing" in detail
    assert "keycloak-podiumd-realm-config.yaml not found" in capsys.readouterr().out


def test_multiple_redirect_uri_lines_in_one_client_each_checked(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """OpenBao's shape: a covered value, a comment, a literal, and (here)
    a second, uncovered value — every item is read, not just the first,
    and the comment line between them doesn't end the list."""
    client = """\
      - clientId: openbao
        redirectUris:
          - "{{ .Values.openzaak.configuration.oidcUrl | trimSuffix "/" }}/*"
          # OpenBao CLI OIDC login callback.
          - "http://localhost:8250/*"
          - "{{ .Values.openbao.configuration.oidcUrl | trimSuffix "/" }}/*"
        webOrigins:
          - "{{ .Values.openbao.configuration.oidcUrl | trimSuffix "/" }}/*"
"""
    write_realm_config(tmp_path, realm(client))
    ok, detail = vp.check_oidc_url_coverage(tmp_path)
    assert ok is False
    assert detail == "1 uncovered"
    out = capsys.readouterr().out
    assert "clientId openbao: .Values.openbao.configuration.oidcUrl" in out
    assert "clientId openbao: .Values.openzaak" not in out
    assert "localhost:8250" in out


def test_web_origins_are_not_checked(vp: ModuleType, tmp_path: Path):
    """webOrigins is not part of the coverage rule: an uncovered path
    there (with covered redirectUris) is harmless, and a client with
    only webOrigins and no redirectUris is ignored entirely."""
    covered_redirect = """\
      - clientId: mixed
        redirectUris:
          - "{{ .Values.zac.contextUrl | trimSuffix "/" }}/*"
        webOrigins:
          - "{{ .Values.not.listed.anywhere }}"
"""
    web_origins_only = """\
      - clientId: origins-only
        webOrigins:
          - "{{ .Values.also.not.listed }}"
"""
    write_realm_config(tmp_path, realm(covered_redirect, web_origins_only))
    ok, detail = vp.check_oidc_url_coverage(tmp_path)
    assert ok is True
    assert detail == "0 uncovered, 0 unmapped (informational)"


def test_root_scoped_values_path_is_matched(vp: ModuleType, tmp_path: Path):
    """Inside a `range`, a client has to write `$.Values.x` — that's the
    same .Values path as a plain `.Values.x` $oidcClients entry."""
    client = """\
      - clientId: openzaak
        redirectUris:
          - "{{ $.Values.openzaak.configuration.oidcUrl | trimSuffix "/" }}/*"
"""
    write_realm_config(tmp_path, realm(client))
    ok, _ = vp.check_oidc_url_coverage(tmp_path)
    assert ok is True
