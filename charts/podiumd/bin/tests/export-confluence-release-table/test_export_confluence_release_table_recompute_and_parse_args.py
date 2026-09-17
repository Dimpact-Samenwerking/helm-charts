"""recompute_image_basenames, the main() --recompute-basenames flag, and
parse_args — with fetch_page_html mocked out, so no network access or
real Confluence page is needed."""

import csv

import pytest

DIGEST_A = "a" * 64


def write_values_yaml_raw(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def test_recompute_image_basenames_updates_only_the_changed_row(ecrt, tmp_path):
    write_values_yaml_raw(
        tmp_path,
        """\
omc:
  image:
    # repository: docker.io/worthnl/notifynl-omc
    tag: "1.17.19"
""",
    )
    csv_path = tmp_path / "release-table.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(ecrt.CSV_HEADER)
        writer.writerow(
            [
                "Common Ground",
                "Worth",
                "",
                "OMC / Notify",
                "notifynl-omc-nodep",
                "omc",
                "",
                "1.17.19",
                "0.14.1",
                "1.17.19",
                "0.14.1",
            ]
        )
        writer.writerow(["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"])

    changes = ecrt.recompute_image_basenames(csv_path, tmp_path)

    assert changes == [("OMC / Notify", "notifynl-omc-nodep", "", "notifynl-omc")]
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[1] == [
        "Common Ground",
        "Worth",
        "",
        "OMC / Notify",
        "notifynl-omc-nodep",
        "omc",
        "notifynl-omc",
        "1.17.19",
        "0.14.1",
        "1.17.19",
        "0.14.1",
    ]
    assert rows[2] == ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"]


def test_recompute_image_basenames_no_changes_returns_empty_and_leaves_file_untouched(ecrt, tmp_path):
    write_values_yaml_raw(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
""",
    )
    csv_path = tmp_path / "release-table.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(ecrt.CSV_HEADER)
        writer.writerow(
            [
                "Product",
                "",
                "",
                "Zaak - ZAC",
                "zaakafhandelcomponent",
                "zac",
                "zaakafhandelcomponent",
                "5.0.0",
                "1.0.290",
                "5.1.0",
                "1.0.297",
            ]
        )
    before = csv_path.read_text(encoding="utf-8")

    changes = ecrt.recompute_image_basenames(csv_path, tmp_path)

    assert changes == []
    assert csv_path.read_text(encoding="utf-8") == before


def test_recompute_image_basenames_missing_file_raises(ecrt, tmp_path):
    with pytest.raises(SystemExit, match="does not exist"):
        ecrt.recompute_image_basenames(tmp_path / "nope.csv", tmp_path)


def test_recompute_image_basenames_wrong_header_raises(ecrt, tmp_path):
    csv_path = tmp_path / "release-table.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f, lineterminator="\n").writerow(["not", "the", "right", "header"])
    with pytest.raises(SystemExit, match="header doesn't match"):
        ecrt.recompute_image_basenames(csv_path, tmp_path)


def test_main_recompute_basenames_flag_skips_confluence_fetch(ecrt, tmp_path, monkeypatch, capsys):
    write_values_yaml_raw(
        tmp_path,
        """\
omc:
  image:
    # repository: docker.io/worthnl/notifynl-omc
    tag: "1.17.19"
""",
    )
    output_path = tmp_path / "release-table.csv"
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(ecrt.CSV_HEADER)
        writer.writerow(
            [
                "Common Ground",
                "Worth",
                "",
                "OMC / Notify",
                "notifynl-omc-nodep",
                "omc",
                "",
                "1.17.19",
                "0.14.1",
                "1.17.19",
                "0.14.1",
            ]
        )
    monkeypatch.setattr(ecrt, "CHART_DIR", tmp_path)

    def fail_fetch(*a, **kw):
        raise AssertionError("must not fetch Confluence when --recompute-basenames is set")

    monkeypatch.setattr(ecrt, "fetch_page_html", fail_fetch)
    monkeypatch.setattr(
        ecrt.sys,
        "argv",
        [
            "export-confluence-release-table",
            "--recompute-basenames",
            "--output",
            str(output_path),
        ],
    )

    ecrt.main()

    out = capsys.readouterr().out
    assert "Recomputed image_basename for 1 row(s)" in out
    assert "'' -> 'notifynl-omc'" in out
    with output_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[1][6] == "notifynl-omc"


def test_parse_args_requires_url_and_user_unless_recompute_basenames(ecrt, monkeypatch):
    monkeypatch.setattr(ecrt.sys, "argv", ["export-confluence-release-table", "--output", "out.csv"])
    with pytest.raises(SystemExit):
        ecrt.parse_args()


def test_parse_args_recompute_basenames_does_not_require_url_and_user(ecrt, monkeypatch):
    monkeypatch.setattr(
        ecrt.sys,
        "argv",
        [
            "export-confluence-release-table",
            "--recompute-basenames",
            "--output",
            "out.csv",
        ],
    )
    args = ecrt.parse_args()
    assert args.recompute_basenames is True
