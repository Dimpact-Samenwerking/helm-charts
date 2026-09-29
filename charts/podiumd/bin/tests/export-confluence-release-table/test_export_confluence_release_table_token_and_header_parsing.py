"""Version/token/header parsing and check_target_matches_chart_version."""

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
    """A missing patch and a stray "." after "v" are allowed (see SEMVER_RE)."""
    assert ecrt.normalize_version("3.20") == "3.20"
    assert ecrt.normalize_version("3.14-slim") == "3.14-slim"
    assert ecrt.normalize_version("v.1.25.4") == "v.1.25.4"


def test_normalize_version_leaves_bare_discrete_version_number_untouched(ecrt: ModuleType):
    """A dot-less build number (frankgateway's "104") is a real version, not UNKNOWN."""
    assert ecrt.normalize_version("104") == "104"


def test_normalize_version_leaves_empty_value_untouched(ecrt: ModuleType):
    """An empty cell is not a malformed version."""
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


def test_resolve_token_missing_token_file_exits_with_message(ecrt: ModuleType, tmp_path: Path):
    args = make_args(token_file=str(tmp_path / "missing.txt"))
    with pytest.raises(SystemExit, match=r"missing\.txt does not exist or is not a file"):
        ecrt.resolve_token(args)


def test_resolve_token_directory_token_file_exits_with_message(ecrt: ModuleType, tmp_path: Path):
    args = make_args(token_file=str(tmp_path))
    with pytest.raises(SystemExit, match="does not exist or is not a file"):
        ecrt.resolve_token(args)


def test_resolve_token_empty_token_file_exits_with_message(ecrt: ModuleType, tmp_path: Path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("  \n", encoding="utf-8")
    args = make_args(token_file=str(token_file))
    with pytest.raises(SystemExit, match="is empty"):
        ecrt.resolve_token(args)


def test_resolve_token_aborted_prompt_exits_with_message(ecrt: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)

    def abort(prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(ecrt.getpass, "getpass", abort)
    with pytest.raises(SystemExit, match="no Confluence API token given"):
        ecrt.resolve_token(make_args())


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


# App/Helm sub-header as <td>: Confluence tags header rows inconsistently.
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


# "Used by" in its own second header row (the real page's shape). With one
# column per Versie group, required columns already resolve at
# header_row_count=1, so resolve_header_row_count must prefer the deeper
# count that also finds optional columns, or every row loses used_by.
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
    """A <td>-tagged sub-header row still resolves every required column."""
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
    """Only major.minor is compared: 4.9.3 vs "Versie 4.9" doesn't warn."""
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
