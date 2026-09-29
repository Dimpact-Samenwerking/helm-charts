"""print_report ordering, main() CLI glue, and --baseline-only
(strict_presence in check_chart_version_source/check_images_source)."""

from pathlib import Path
from types import ModuleType

import pytest

DIGEST = "a" * 64


def csv_row(name, component, alias="", image_basename="", source_app="", source_helm="", target_app="", target_helm=""):
    return {
        "section": "Product",
        "vendor": "",
        "used_by": "",
        "name": name,
        "component": component,
        "alias": alias,
        "image_basename": image_basename,
        "source_version_app": source_app,
        "source_version_helm": source_helm,
        "target_version_app": target_app,
        "target_version_helm": target_helm,
    }


def values_lines(*blocks):
    return "\n".join(blocks).splitlines()


ZAC_BLOCK = f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.4.3@sha256:{DIGEST}"\n'

ZAC_BASELINE_BLOCK = (
    f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.0.2@sha256:{DIGEST}"\n'
)

CLAMAV_CURRENT_BLOCK = (
    f'clamav:\n  image:\n    repository: docker.io/clamav/clamav\n    tag: "1.5.3@sha256:{"a" * 64}"\n'
)
CLAMAV_BASELINE_BLOCK = (
    "clamav:\n"
    "  image:\n"
    '    tag: "1.5.2"\n'  # no repository override at all — the real 4.8.5 shape
)
CLAMAV_BASELINE_VALUES = {"clamav": {"image": {"tag": "1.5.2"}}}


# --- print_report(): output is sorted per category ---


def test_print_report_sorts_findings_within_each_section(vrt: ModuleType, capsys: pytest.CaptureFixture[str]):
    findings = {
        "mismatches": [
            "[IMAGE] Zulu (zulu): release-table target 1 != values.yaml 2",
            "[CHART] Alpha (alpha): release-table target 1 != Chart.yaml 2",
        ],
    }
    vrt.print_report(findings, [])
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  [")]
    assert lines == [
        "  [CHART] Alpha (alpha): release-table target 1 != Chart.yaml 2",
        "  [IMAGE] Zulu (zulu): release-table target 1 != values.yaml 2",
    ]


def test_print_report_sorts_unresolved_rows_by_name(vrt: ModuleType, capsys: pytest.CaptureFixture[str]):
    unresolved = [csv_row("Zulu", "UNKNOWN"), csv_row("Alpha", ""), csv_row("Mike", "UNKNOWN")]
    vrt.print_report({}, unresolved)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip().startswith("- '")]
    assert lines == [
        "  - 'Alpha' (component=(blank))",
        "  - 'Mike' (component=UNKNOWN)",
        "  - 'Zulu' (component=UNKNOWN)",
    ]


# --- main() ---


def run_main(vrt: ModuleType, monkeypatch: pytest.MonkeyPatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-release-table-with-podiumd", *argv])
    with pytest.raises(SystemExit) as exc_info:
        vrt.main()
    return exc_info.value.code


def test_main_missing_release_table_csv_fails(
    vrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", tmp_path / "release-table.csv")
    code = run_main(vrt, monkeypatch, [])
    assert code == 1
    assert "not found" in capsys.readouterr().out


def test_main_exits_zero_when_everything_matches(
    vrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    import csv as csv_module

    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    release_table = tmp_path / "release-table.csv"

    chart_yaml.write_text(
        "dependencies:\n  - name: zaakafhandelcomponent\n    version: 1.0.297\n    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(ZAC_BLOCK, encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(csv_row("x", "y").keys()))
        writer.writeheader()
        writer.writerow(
            csv_row(
                "Zaak - ZAC",
                "zaakafhandelcomponent",
                alias="zac",
                image_basename="zaakafhandelcomponent",
                target_app="5.4.3",
                target_helm="1.0.297",
            )
        )

    monkeypatch.setattr(vrt, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(vrt, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", release_table)

    code = run_main(vrt, monkeypatch, [])
    assert code == 0
    assert "OK: release-table.csv matches" in capsys.readouterr().out


def test_main_exits_one_when_mismatch_found(
    vrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    import csv as csv_module

    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    release_table = tmp_path / "release-table.csv"

    chart_yaml.write_text(
        "dependencies:\n  - name: zaakafhandelcomponent\n    version: 1.0.298\n    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(ZAC_BLOCK, encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(csv_row("x", "y").keys()))
        writer.writeheader()
        writer.writerow(
            csv_row(
                "Zaak - ZAC",
                "zaakafhandelcomponent",
                alias="zac",
                image_basename="zaakafhandelcomponent",
                target_app="5.4.3",
                target_helm="1.0.297",
            )
        )

    monkeypatch.setattr(vrt, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(vrt, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", release_table)

    code = run_main(vrt, monkeypatch, [])
    assert code == 1
    out = capsys.readouterr().out
    assert "Version mismatches" in out
    assert "1.0.297 != Chart.yaml 1.0.298" in out


def test_main_requires_no_arguments(vrt: ModuleType, monkeypatch: pytest.MonkeyPatch):
    code = run_main(vrt, monkeypatch, ["extra-arg"])
    assert code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(
    vrt: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag
):
    code = run_main(vrt, monkeypatch, [flag])
    assert code == 0
    assert capsys.readouterr().out == f"{vrt.__doc__}\n"


def test_main_rejects_unknown_flag(vrt: ModuleType, monkeypatch: pytest.MonkeyPatch):
    code = run_main(vrt, monkeypatch, ["--nonsense"])
    assert code == 1


# --- --baseline-only / strict_presence ---
# By default a blank source is assumed "nothing recorded at the baseline";
# --baseline-only verifies that and skips all target-side checks.


def test_compare_baseline_only_skips_target_side_checks(vrt: ModuleType):
    """Under baseline_only, target-side mismatches (present, see the second
    call) are not reported; only the clean source side is checked."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.298"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            source_app="5.0.2",
            source_helm="1.0.297",
            target_app="9.9.9",
            target_helm="1.0.297",
        )
    ]

    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(ZAC_BASELINE_BLOCK)),
        baseline_only=True,
    )
    assert findings == {}

    findings_normal, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(ZAC_BASELINE_BLOCK)),
    )
    assert any("[IMAGE]" in m and "target 9.9.9" in m for m in findings_normal["mismatches"])
    assert any("[CHART]" in m and "target 1.0.297 != Chart.yaml 1.0.298" in m for m in findings_normal["mismatches"])


def test_compare_chart_version_source_blank_but_justified_no_finding(vrt: ModuleType):
    """A blank source_version_helm is justified when the dependency didn't
    exist at the release_table baseline."""
    deps = [{"name": "newthing", "alias": "", "version": "1.0.0"}]
    rows = [csv_row("New Thing", "newthing", target_helm="1.0.0")]  # source_helm blank
    findings, _ = vrt.compare(
        rows, vrt.ChartState(None, deps, {}, []), baseline=vrt.ChartState(None, [], {}, []), baseline_only=True
    )
    assert findings == {}


def test_compare_chart_version_source_blank_but_unjustified_reports_presence_finding(vrt: ModuleType):
    """A blank source_version_helm for a dependency that existed at the
    baseline is reported under strict_presence."""
    deps = [{"name": "existingthing", "alias": "", "version": "1.1.0"}]
    baseline_deps = [{"name": "existingthing", "alias": "", "version": "1.0.0"}]
    rows = [csv_row("Existing Thing", "existingthing", target_helm="1.1.0")]  # source_helm blank
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, []),
        baseline=vrt.ChartState(None, baseline_deps, {}, []),
        baseline_only=True,
    )
    assert any(
        "[CHART-SOURCE-PRESENCE]" in m and "already existed at the release_table baseline (version 1.0.0)" in m
        for m in findings["mismatches"]
    )


def test_compare_chart_version_source_presence_finding_fires_once_per_dependency_not_per_sidecar_row(vrt: ModuleType):
    """Only the primary row carries a Helm version (sidecar rows are always
    blank), so the presence check fires once per dependency, not per row."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            target_app="5.4.3",
            target_helm="1.0.297",
        ),  # primary row, source_helm blank too
        {
            **csv_row("Gotenberg", "zaakafhandelcomponent", alias="zac", image_basename="gotenberg"),
            "section": "Technische",
        },
        {**csv_row("Solr", "zaakafhandelcomponent", alias="zac", image_basename="solr"), "section": "Technische"},
    ]
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)),
        baseline=vrt.ChartState(None, baseline_deps, {}, []),
        baseline_only=True,
    )
    presence_findings = [m for m in findings["mismatches"] if "[CHART-SOURCE-PRESENCE]" in m]
    assert len(presence_findings) == 1
    assert "zaakafhandelcomponent" in presence_findings[0]


def test_compare_chart_version_source_blank_unjustified_case_silent_by_default(vrt: ModuleType):
    """Without baseline_only the blank source is silently skipped."""
    deps = [{"name": "existingthing", "alias": "", "version": "1.1.0"}]
    baseline_deps = [{"name": "existingthing", "alias": "", "version": "1.0.0"}]
    rows = [csv_row("Existing Thing", "existingthing", target_helm="1.1.0")]  # source_helm blank
    findings, _ = vrt.compare(
        rows, vrt.ChartState(None, deps, {}, []), baseline=vrt.ChartState(None, baseline_deps, {}, [])
    )
    assert findings == {}


def test_compare_image_source_blank_but_justified_no_finding(vrt: ModuleType):
    """An image not pinned at the baseline (and no dependency for the
    subchart fallback) justifies a blank source_version_app."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            target_helm="1.0.297",
        )
    ]  # source_app AND source_helm both blank
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)),
        baseline=vrt.ChartState(None, [], {}, []),
        baseline_only=True,
    )
    assert findings == {}


def test_compare_image_source_blank_but_unjustified_reports_presence_finding_scoped_tier(vrt: ModuleType):
    """An image found at the baseline by the scoped scan makes a blank
    source_version_app a finding."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            source_helm="1.0.251",
            target_helm="1.0.297",
        )
    ]  # source_app blank
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(ZAC_BASELINE_BLOCK)),
        baseline_only=True,
    )
    assert any(
        "[IMAGE-SOURCE-PRESENCE]" in m and "already existed at the release_table baseline (values.yaml 5.0.2)" in m
        for m in findings["mismatches"]
    )


def test_compare_image_source_blank_unjustified_case_silent_by_default(vrt: ModuleType):
    """Without baseline_only the blank source is skipped. target_app is set
    so the unrelated "never recorded" check doesn't fire."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            source_helm="1.0.251",
            target_app="5.4.3",
            target_helm="1.0.297",
        )
    ]  # source_app blank
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(ZAC_BASELINE_BLOCK)),
    )
    assert findings == {}


def test_compare_image_source_blank_but_unjustified_reports_presence_finding_subchart_fallback_tier(
    vrt: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    """An image resolved at the baseline only via the subchart-default
    fallback is caught too."""
    monkeypatch.setattr(
        "lib.release_table_verification.primary_image_repositories",
        lambda chart_dir, dep, values, allow_pull=True: ({"image": "docker.io/clamav/clamav"}, None),
    )
    dep = {"name": "clamav", "version": "3.9.0"}
    baseline_dep = {"name": "clamav", "version": "3.7.1"}
    rows = [
        csv_row(
            "ClamAV", "clamav", image_basename="clamav", source_helm="3.7.1", target_app="1.5.3", target_helm="3.9.0"
        )
    ]  # source_app blank
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(Path("/fake/chart/dir"), [dep], {}, values_lines(CLAMAV_CURRENT_BLOCK)),
        baseline=vrt.ChartState(
            Path("/fake/chart/dir"), [baseline_dep], CLAMAV_BASELINE_VALUES, values_lines(CLAMAV_BASELINE_BLOCK)
        ),
        baseline_only=True,
    )
    assert any(
        "[IMAGE-SOURCE-PRESENCE]" in m and "subchart-default values.yaml 1.5.2" in m for m in findings["mismatches"]
    )


def test_compare_baseline_only_image_source_ambiguous_stays_ambiguous_not_a_presence_finding(vrt: ModuleType):
    """An ambiguous baseline pin is "can't verify", never a -PRESENCE finding."""
    two_versions_block = (
        "zac:\n"
        "  a:\n"
        "    image:\n"
        "      repository: docker.io/curlimages/curl\n"
        f'      tag: "8.21.0@sha256:{"a" * 64}"\n'
        "  b:\n"
        "    image:\n"
        "      repository: docker.io/curlimages/curl\n"
        f'      tag: "8.22.0@sha256:{"b" * 64}"\n'
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="curl",
            source_helm="1.0.251",
            target_helm="1.0.297",
        )
    ]  # source_app blank
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(two_versions_block)),
        baseline_only=True,
    )
    assert findings.get("mismatches", []) == []
    assert any("pinned at 2 different versions" in m for m in findings["ambiguous"])


def test_main_baseline_only_end_to_end(
    vrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Full CLI: --baseline-only hides target-side mismatches and reports the
    blank-source presence finding."""
    import csv as csv_module

    chart_dir = tmp_path / "chart"
    chart_dir.mkdir()
    chart_yaml = chart_dir / "Chart.yaml"
    values_yaml = chart_dir / "values.yaml"
    release_table = chart_dir / "etc" / "release-table.csv"
    release_table.parent.mkdir()

    chart_yaml.write_text(
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.298\n"  # would mismatch target_helm below if target-side ran
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(ZAC_BLOCK, encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(csv_row("x", "y").keys()))
        writer.writeheader()
        # Blank image_basename isolates the chart-version presence check.
        writer.writerow(
            csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", target_app="9.9.9", target_helm="1.0.297")
        )

    monkeypatch.setattr(vrt, "CHART_DIR", chart_dir)
    monkeypatch.setattr(vrt, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(vrt, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", release_table)
    monkeypatch.setattr(vrt, "release_table_baseline", lambda chart_dir: "1.0.0")
    monkeypatch.setattr(
        vrt,
        "resolve_baseline_chart_state",
        lambda chart_dir, baseline: (
            baseline,
            [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.290"}],
            {},
            [],
            None,
        ),
    )

    code = run_main(vrt, monkeypatch, ["--baseline-only"])
    out = capsys.readouterr().out
    assert "9.9.9" not in out
    assert "1.0.298" not in out
    assert code == 1
    assert "[CHART-SOURCE-PRESENCE]" in out
    assert "already existed at the release_table baseline (version 1.0.290)" in out


def test_main_baseline_only_errors_when_baseline_cannot_be_resolved(
    vrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """--baseline-only with an unresolvable baseline has nothing to check:
    exit 1 rather than report OK."""
    import csv as csv_module

    chart_dir = tmp_path / "chart"
    chart_dir.mkdir()
    chart_yaml = chart_dir / "Chart.yaml"
    values_yaml = chart_dir / "values.yaml"
    release_table = chart_dir / "etc" / "release-table.csv"
    release_table.parent.mkdir()
    chart_yaml.write_text("dependencies: []\n", encoding="utf-8")
    values_yaml.write_text("", encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as f:
        csv_module.DictWriter(f, fieldnames=list(csv_row("x", "y").keys())).writeheader()

    monkeypatch.setattr(vrt, "CHART_DIR", chart_dir)
    monkeypatch.setattr(vrt, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(vrt, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", release_table)
    monkeypatch.setattr(vrt, "release_table_baseline", lambda chart_dir: None)

    code = run_main(vrt, monkeypatch, ["--baseline-only"])
    out = capsys.readouterr().out
    assert code == 1
    assert "nothing to check" in out


def test_main_plain_invocation_still_reports_ok_when_baseline_unresolvable(
    vrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Without --baseline-only an unresolvable baseline only warns."""
    import csv as csv_module

    chart_dir = tmp_path / "chart"
    chart_dir.mkdir()
    chart_yaml = chart_dir / "Chart.yaml"
    values_yaml = chart_dir / "values.yaml"
    release_table = chart_dir / "etc" / "release-table.csv"
    release_table.parent.mkdir()
    chart_yaml.write_text("dependencies: []\n", encoding="utf-8")
    values_yaml.write_text("", encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as f:
        csv_module.DictWriter(f, fieldnames=list(csv_row("x", "y").keys())).writeheader()

    monkeypatch.setattr(vrt, "CHART_DIR", chart_dir)
    monkeypatch.setattr(vrt, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(vrt, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", release_table)
    monkeypatch.setattr(vrt, "release_table_baseline", lambda chart_dir: None)

    code = run_main(vrt, monkeypatch, [])
    out = capsys.readouterr().out
    assert code == 0
    assert "OK: release-table.csv matches" in out


# --- stale vendored sub-charts guard ---


@pytest.mark.parametrize(("argv", "expect_guard"), [([], True), (["--baseline-only"], False)])
def test_main_guards_vendored_dependencies_unless_baseline_only(
    vrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv, expect_guard
):
    """Target-side checks read charts/*.tgz, so a normal run guards staleness
    first; --baseline-only must not be blocked by it. The missing CSV ends
    main() right after the guard."""
    calls = []
    monkeypatch.setattr(vrt, "ensure_vendored_dependencies", calls.append)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", tmp_path / "release-table.csv")
    monkeypatch.setattr(vrt.sys, "argv", ["verify-release-table-with-podiumd", *argv])
    with pytest.raises(SystemExit):
        vrt.main()
    assert calls == ([vrt.CHART_DIR] if expect_guard else [])
