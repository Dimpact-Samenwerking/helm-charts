"""fix-oidc-url-coverage — appends a `$oidcClients` entry for every
redirect URI path verify-podiumd's "OIDC URL coverage" step reports."""

from pathlib import Path
from types import ModuleType

import pytest

from lib.checks.oidc_url_coverage import scan_oidc_url_coverage

OIDC_CLIENTS_HEAD = """\
{{- $oidcClients := list
  (dict "name" "openzaak"          "enabled" .Values.openzaak.enabled          "oidcUrl" .Values.openzaak.configuration.oidcUrl)
"""
OIDC_CLIENTS_TAIL = """\
-}}
{{- range $oidcClients }}
{{- end }}
"""

CLIENTS = """\
      - clientId: openzaak
        redirectUris:
          - "{{ .Values.openzaak.configuration.oidcUrl }}/*"
      - clientId: ita
        redirectUris:
          - "{{ .Values.ita.web.oidc.frontendUrl }}/*"
      - clientId: monitoring
        redirectUris:
          - "{{ .Values.keycloak.config.clients.monitoring.oidcUrl }}/*"
          - "{{ .Values.keycloak.config.clients.monitoring.oidcUrl }}/callback"
"""

ITA_ENTRY = (
    '  (dict "name" "ita"               "enabled" .Values.ita.enabled               '
    '"oidcUrl" .Values.ita.web.oidc.frontendUrl "field" "ita.web.oidc.frontendUrl")\n'
)
MONITORING_ENTRY = (
    '  (dict "name" "monitoring"        "enabled" .Values.keycloak.config.clients.monitoring.enabled '
    '"oidcUrl" .Values.keycloak.config.clients.monitoring.oidcUrl '
    '"field" "keycloak.config.clients.monitoring.oidcUrl")\n'
)

UNCOVERED = OIDC_CLIENTS_HEAD + OIDC_CLIENTS_TAIL + CLIENTS
FIXED = OIDC_CLIENTS_HEAD + ITA_ENTRY + MONITORING_ENTRY + OIDC_CLIENTS_TAIL + CLIENTS

VALUES = """\
ita:
  enabled: true
keycloak:
  config:
    clients:
      monitoring:
        enabled: false
"""

CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 1.0.0
dependencies:
  - name: openzaak
    version: 1.0.0
    condition: openzaak.enabled
"""


def make_chart(tmp_path: Path, template: str, values: str = VALUES) -> Path:
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "keycloak-podiumd-realm-config.yaml").write_text(template, encoding="utf-8")
    (tmp_path / "values.yaml").write_text(values, encoding="utf-8")
    (tmp_path / "Chart.yaml").write_text(CHART_YAML, encoding="utf-8")
    return tmp_path


def template_text(chart_dir: Path) -> str:
    return (chart_dir / "templates" / "keycloak-podiumd-realm-config.yaml").read_text(encoding="utf-8")


def run_main(sub: ModuleType, chart_dir: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> int | str | None:
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-oidc-url-coverage", *args])
    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    return exc_info.value.code


@pytest.mark.parametrize(
    ("values_path", "expected"),
    [
        ("ita.web.oidc.frontendUrl", ("ita", "ita")),
        ("openzaak.configuration.oidcUrl", ("openzaak", "openzaak")),
        ("keycloak.config.clients.monitoring.oidcUrl", ("monitoring", "keycloak.config.clients.monitoring")),
    ],
)
def test_client_block(sub: ModuleType, values_path: str, expected: tuple[str, str]):
    assert sub.client_block(values_path) == expected


def test_has_enabled_switch_accepts_values_key_or_dependency_condition(sub: ModuleType):
    values = {"ita": {"enabled": True}, "keycloak": {"config": {"clients": {"monitoring": {"enabled": False}}}}}
    deps = [{"name": "openzaak", "version": "1.0.0", "condition": "openzaak.enabled"}]
    assert sub.has_enabled_switch("ita", values, deps)
    assert sub.has_enabled_switch("keycloak.config.clients.monitoring", values, deps)
    assert sub.has_enabled_switch("openzaak", values, deps)
    assert not sub.has_enabled_switch("frankgateway", values, deps)


def test_entry_line_leaves_out_default_field(sub: ModuleType):
    first = OIDC_CLIENTS_HEAD.splitlines()[1]
    assert sub.entry_line("openzaak.configuration.oidcUrl", first) == first


def test_main_appends_entries_that_pass_the_check(
    sub: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    chart_dir = make_chart(tmp_path, UNCOVERED)
    assert run_main(sub, chart_dir, monkeypatch) == 0
    assert template_text(chart_dir) == FIXED
    result = scan_oidc_url_coverage(template_text(chart_dir))
    assert result is not None
    assert result[0] == []
    assert "Added 2 $oidcClients entry(ies)" in capsys.readouterr().out


def test_main_is_idempotent(
    sub: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    chart_dir = make_chart(tmp_path, FIXED)
    assert run_main(sub, chart_dir, monkeypatch) == 0
    assert template_text(chart_dir) == FIXED
    assert "OK:" in capsys.readouterr().out


def test_main_dry_run_reports_but_does_not_write(
    sub: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    chart_dir = make_chart(tmp_path, UNCOVERED)
    assert run_main(sub, chart_dir, monkeypatch, "--dry-run") == 1
    assert template_text(chart_dir) == UNCOVERED
    out = capsys.readouterr().out
    assert 'would add (dict "name" "ita"' in out
    assert "dry-run" in out


def test_main_without_enabled_switch_leaves_path_for_review(
    sub: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    chart_dir = make_chart(tmp_path, UNCOVERED, values="keycloak:\n  config:\n    clients:\n      monitoring: {}\n")
    assert run_main(sub, chart_dir, monkeypatch) == 1
    assert template_text(chart_dir) == UNCOVERED
    out = capsys.readouterr().out
    assert ".Values.ita.web.oidc.frontendUrl: no enabled switch found" in out
    assert "2 left unresolved" in out


def test_main_without_oidc_clients_list_fails(
    sub: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    chart_dir = make_chart(tmp_path, CLIENTS)
    assert run_main(sub, chart_dir, monkeypatch) == 1
    assert "no `$oidcClients := list ...` entries found" in capsys.readouterr().out


def test_main_help_flag_prints_usage_and_exits_zero(
    sub: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    chart_dir = make_chart(tmp_path, UNCOVERED)
    assert run_main(sub, chart_dir, monkeypatch, "--help") == 0
    assert capsys.readouterr().out == f"{sub.__doc__}\n"
    assert template_text(chart_dir) == UNCOVERED


def test_main_rejects_unknown_argument(sub: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    chart_dir = make_chart(tmp_path, UNCOVERED)
    assert run_main(sub, chart_dir, monkeypatch, "--force") == 1
    assert template_text(chart_dir) == UNCOVERED
