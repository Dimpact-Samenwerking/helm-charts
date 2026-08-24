"""resolve_token, extract_release_rows, main — with fetch_page_html
mocked out, so no network access or real Confluence page is needed."""
import csv

import pytest

RELEASE_TABLE_HTML = """
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

UNRELATED_TABLE_HTML = "<table><tr><th>Legend</th></tr><tr><td>n/a</td></tr></table>"


# --- resolve_token ---

def make_args(**overrides):
    from types import SimpleNamespace
    defaults = {"token_file": None, "token": None}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_resolve_token_prefers_token_file(ecrt, tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("  s3cr3t-from-file  \n", encoding="utf-8")
    args = make_args(token_file=str(token_file), token="ignored-since-file-wins")
    assert ecrt.resolve_token(args) == "s3cr3t-from-file"


def test_resolve_token_falls_back_to_token_arg(ecrt):
    args = make_args(token="s3cr3t-from-arg")
    assert ecrt.resolve_token(args) == "s3cr3t-from-arg"


def test_resolve_token_falls_back_to_env_var(ecrt, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "s3cr3t-from-env")
    args = make_args()
    assert ecrt.resolve_token(args) == "s3cr3t-from-env"


def test_resolve_token_prompts_as_last_resort(ecrt, monkeypatch):
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    monkeypatch.setattr(ecrt.getpass, "getpass", lambda prompt: "s3cr3t-from-prompt")
    args = make_args()
    assert ecrt.resolve_token(args) == "s3cr3t-from-prompt"


# --- extract_release_rows ---

def test_extract_release_rows_matches_and_reports(ecrt, capsys):
    first_label, rows = ecrt.extract_release_rows(RELEASE_TABLE_HTML)
    assert first_label == "component"  # RELEASE_TABLE_HTML's own first column has no header text
    assert rows == [
        ["ZAC", "Info(NL)", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Open Zaak", "Maykin", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]
    out = capsys.readouterr().out
    assert "2 row(s) matched" in out


def test_extract_release_rows_skips_unrelated_table_and_keeps_matching_one(ecrt, capsys):
    html = UNRELATED_TABLE_HTML + RELEASE_TABLE_HTML
    first_label, rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2
    out = capsys.readouterr().out
    assert "skipped (missing column(s):" in out
    assert "2 row(s) matched" in out


def test_extract_release_rows_no_tables_raises(ecrt):
    with pytest.raises(SystemExit, match="no <table> found"):
        ecrt.extract_release_rows("<p>no tables here</p>")


def test_extract_release_rows_no_matching_table_raises(ecrt):
    with pytest.raises(SystemExit, match="no table on that page had all the expected columns"):
        ecrt.extract_release_rows(UNRELATED_TABLE_HTML)


def test_extract_release_rows_skips_fully_blank_rows(ecrt):
    html = RELEASE_TABLE_HTML.replace(
        "<tr>\n<td>Open Zaak</td>",
        "<tr><td></td><td></td><td></td><td></td><td></td><td></td></tr>\n<tr>\n<td>Open Zaak</td>",
    )
    _, rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2  # the all-blank row was skipped, not counted


# --- main() integration ---

def test_main_writes_csv(ecrt, tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "release-changes.csv"
    monkeypatch.setattr(ecrt.sys, "argv", [
        "export-confluence-release-table.py",
        "--url", "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "--user", "kees@info.nl",
        "--token", "s3cr3t",
        "--output", str(output_path),
    ])
    monkeypatch.setattr(ecrt, "fetch_page_html", lambda url, user, token: RELEASE_TABLE_HTML)

    ecrt.main()

    with output_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["component", "ontwikkelpartij", "versie 4.8 app", "versie 4.8 helm",
                        "versie 4.9 app", "versie 4.9 helm"]
    assert rows[1] == ["ZAC", "Info(NL)", "5.0.0", "1.0.290", "5.1.0", "1.0.297"]
    assert rows[2] == ["Open Zaak", "Maykin", "1.27.0", "1.14.0", "1.27.4", "1.14.2"]
    out = capsys.readouterr().out
    assert f"Wrote 2 row(s) to {output_path}" in out


def test_main_passes_resolved_token_and_url_user_through(ecrt, tmp_path, monkeypatch):
    output_path = tmp_path / "out.csv"
    monkeypatch.setattr(ecrt.sys, "argv", [
        "export-confluence-release-table.py",
        "--url", "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "--user", "kees@info.nl",
        "--token", "s3cr3t",
        "--output", str(output_path),
    ])
    captured = {}

    def fake_fetch(url, user, token):
        captured.update(url=url, user=user, token=token)
        return RELEASE_TABLE_HTML

    monkeypatch.setattr(ecrt, "fetch_page_html", fake_fetch)
    ecrt.main()
    assert captured == {
        "url": "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "user": "kees@info.nl",
        "token": "s3cr3t",
    }
