"""normalize_version, resolve_token, resolve_header_row_count,
check_target_matches_chart_version — with fetch_page_html mocked out, so
no network access or real Confluence page is needed."""

from pathlib import Path
from types import ModuleType

import pytest


def write_chart_yaml(chart_dir, version):
    (chart_dir / "Chart.yaml").write_text(f"apiVersion: v2\nname: podiumd\nversion: {version}\n", encoding="utf-8")


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


# --- normalize_version ---


def test_normalize_version_leaves_valid_semver_untouched(ecrt: ModuleType):
    assert ecrt.normalize_version("1.27.4") == "1.27.4"
    assert ecrt.normalize_version("9.10.1-slim") == "9.10.1-slim"


def test_normalize_version_leaves_allowed_variations_untouched(ecrt: ModuleType):
    """Missing patch component and a stray "." after a leading "v" are
    allowed variations, not something to flag — see
    lib.confluence_tables.SEMVER_RE."""
    assert ecrt.normalize_version("3.20") == "3.20"
    assert ecrt.normalize_version("3.14-slim") == "3.14-slim"
    assert ecrt.normalize_version("v.1.25.4") == "v.1.25.4"


def test_normalize_version_leaves_bare_discrete_version_number_untouched(ecrt: ModuleType):
    """A bare, dot-less incrementing build number (e.g. frankgateway's
    own real app version, "104") is a real, discrete version, never
    semver in the first place — must not be flagged as UNKNOWN."""
    assert ecrt.normalize_version("104") == "104"


def test_normalize_version_leaves_empty_value_untouched(ecrt: ModuleType):
    """No data at all for that cell isn't a malformed version — nothing
    to flag."""
    assert ecrt.normalize_version("") == ""


def test_normalize_version_replaces_non_semver_with_unknown(ecrt: ModuleType):
    assert ecrt.normalize_version("5.4.3 5.4.4") == "UNKNOWN"
    assert ecrt.normalize_version("?") == "UNKNOWN"


# --- resolve_token ---


def make_args(**overrides):
    from types import SimpleNamespace

    defaults = {"token_file": None, "token": None}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_resolve_token_prefers_token_file(ecrt: ModuleType, tmp_path: Path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("  s3cr3t-from-file  \n", encoding="utf-8")
    args = make_args(token_file=str(token_file), token="ignored-since-file-wins")
    assert ecrt.resolve_token(args) == "s3cr3t-from-file"


def test_resolve_token_falls_back_to_token_arg(ecrt: ModuleType):
    args = make_args(token="s3cr3t-from-arg")
    assert ecrt.resolve_token(args) == "s3cr3t-from-arg"


def test_resolve_token_falls_back_to_env_var(ecrt: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "s3cr3t-from-env")
    args = make_args()
    assert ecrt.resolve_token(args) == "s3cr3t-from-env"


def test_resolve_token_prompts_as_last_resort(ecrt: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    monkeypatch.setattr(ecrt.getpass, "getpass", lambda prompt: "s3cr3t-from-prompt")
    args = make_args()
    assert ecrt.resolve_token(args) == "s3cr3t-from-prompt"


# Same shape as PRODUCT_TABLE_HTML, but the "App"/"Helm" sub-header row
# is plain <td>, not <th> — seen on the real podiumd page, where
# Confluence's own <th> tagging is inconsistent between a table's header
# rows.
PRODUCT_TABLE_INCONSISTENT_TH_HTML = PRODUCT_TABLE_HTML.replace(
    "<tr>\n<th>App</th>\n<th>Helm</th>\n<th>App</th>\n<th>Helm</th>\n</tr>",
    "<tr>\n<td>App</td>\n<td>Helm</td>\n<td>App</td>\n<td>Helm</td>\n</tr>",
)


# --- resolve_header_row_count ---


def test_resolve_header_row_count_extends_past_inconsistent_th_tagging(ecrt: ModuleType):
    from lib.confluence_tables import expand_grid
    from lib.confluence_tables import extract_tables

    _heading, rows = extract_tables(PRODUCT_TABLE_INCONSISTENT_TH_HTML)[0]
    grid = expand_grid(rows)
    assert ecrt.resolve_header_row_count(rows, grid) == 2


# Same shape as TECHNISCHE_TABLE_NO_HELM_HTML (no App/Helm sub-column at
# all under either "Versie ..." group), but "Used by" lives in its OWN
# second header row instead of alongside the table's other top-level
# headers — the real podiumd page's current shape, confirmed live: with
# exactly one column per "Versie ..." group, source_app/target_app
# already resolve by POSITION at header_row_count=1 (see
# select_release_columns), satisfying missing_required_release_columns
# before the probe ever reaches row 1, where "Used by" actually is —
# silently losing every row's used_by (and, downstream, its component
# resolution) without resolve_header_row_count's own preference for a
# deeper, still-valid count that resolves MORE optional columns.
TECHNISCHE_TABLE_TWO_HEADER_ROWS_NO_HELM_HTML = """
<h2>Technische component versies</h2>
<table>
<tbody>
<tr>
<th rowspan="2">Image</th>
<th></th>
<th>Versie 4.8</th>
<th>Versie 4.9</th>
</tr>
<tr>
<th>Used by</th>
<th>App</th>
<th>App</th>
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


def test_resolve_header_row_count_prefers_deeper_count_for_used_by_when_versie_groups_are_single_column(
    ecrt: ModuleType,
):
    from lib.confluence_tables import expand_grid
    from lib.confluence_tables import extract_tables

    _heading, rows = extract_tables(TECHNISCHE_TABLE_TWO_HEADER_ROWS_NO_HELM_HTML)[0]
    grid = expand_grid(rows)
    assert ecrt.resolve_header_row_count(rows, grid) == 2


def test_extract_release_rows_technische_table_two_header_rows_still_resolves_used_by(ecrt: ModuleType):
    rows = ecrt.extract_release_rows(TECHNISCHE_TABLE_TWO_HEADER_ROWS_NO_HELM_HTML)
    assert rows == [["Technische", "", "ZAC", "Elastic operator", "UNKNOWN", "", "", "3.4.0", "", "3.5.0", ""]]


def test_extract_release_rows_handles_inconsistent_th_tagging(ecrt: ModuleType):
    """End-to-end: the same table with a <td>-tagged sub-header row must
    still resolve every required column, not just the ones a strict
    <th>-only header count would catch."""
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_INCONSISTENT_TH_HTML)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


# --- check_target_matches_chart_version ---


def test_check_target_matches_chart_version_silent_when_major_minor_matches(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version(["Versie 4.9"], tmp_path)
    assert capsys.readouterr().err == ""


def test_check_target_matches_chart_version_warns_on_mismatch(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version(["Versie 5.0"], tmp_path)
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "Chart.yaml version:        4.9.0" in err
    assert "'Versie 5.0'" in err


def test_check_target_matches_chart_version_ignores_patch(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Chart.yaml at 4.9.3 (a patch release) must not warn just because
    the page still says "Versie 4.9" — only major.minor is compared."""
    write_chart_yaml(tmp_path, "4.9.3")
    ecrt.check_target_matches_chart_version(["Versie 4.9"], tmp_path)
    assert capsys.readouterr().err == ""


def test_check_target_matches_chart_version_dedupes_repeated_labels(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version(["Versie 5.0", "Versie 5.0", "Versie 5.0"], tmp_path)
    err = capsys.readouterr().err
    assert err.count("'Versie 5.0'") == 1


def test_check_target_matches_chart_version_no_labels_is_silent(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version([], tmp_path)
    assert capsys.readouterr().err == ""


def test_check_target_matches_chart_version_missing_chart_yaml_is_silent(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    ecrt.check_target_matches_chart_version(["Versie 5.0"], tmp_path)
    assert capsys.readouterr().err == ""
