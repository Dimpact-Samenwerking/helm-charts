"""print_report()'s own output ordering, main() (the file-loading/CLI glue
around compare()), and --baseline-only/strict_presence for
verify-release-table-with-podiumd. main()'s own tests cover its
file-loading/CLI glue; the --baseline-only tests cover compare()'s own
baseline_only param (threaded through to check_chart_version_source/
check_images_source as strict_presence).

Split out of test_verify_release_table_with_podiumd.py (pylint
too-many-lines) -- purely a test reorganization, no behavior change. See the
sibling test_verify_release_table_with_podiumd_*.py files for the rest of
that suite."""

from pathlib import Path

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


def test_print_report_sorts_findings_within_each_section(vrt, capsys):
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


def test_print_report_sorts_unresolved_rows_by_name(vrt, capsys):
    unresolved = [csv_row("Zulu", "UNKNOWN"), csv_row("Alpha", ""), csv_row("Mike", "UNKNOWN")]
    vrt.print_report({}, unresolved)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip().startswith("- '")]
    assert lines == [
        "  - 'Alpha' (component=(blank))",
        "  - 'Mike' (component=UNKNOWN)",
        "  - 'Zulu' (component=UNKNOWN)",
    ]


# --- main() ---


def run_main(vrt, monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-release-table-with-podiumd", *argv])
    with pytest.raises(SystemExit) as exc_info:
        vrt.main()
    return exc_info.value.code


def test_main_missing_release_table_csv_fails(vrt, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", tmp_path / "release-table.csv")
    code = run_main(vrt, monkeypatch, [])
    assert code == 1
    assert "not found" in capsys.readouterr().out


def test_main_exits_zero_when_everything_matches(vrt, tmp_path, monkeypatch, capsys):
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


def test_main_exits_one_when_mismatch_found(vrt, tmp_path, monkeypatch, capsys):
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


def test_main_requires_no_arguments(vrt, monkeypatch):
    code = run_main(vrt, monkeypatch, ["extra-arg"])
    assert code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(vrt, monkeypatch, capsys, flag):
    code = run_main(vrt, monkeypatch, [flag])
    assert code == 0
    assert capsys.readouterr().out == vrt.__doc__ + "\n"


def test_main_rejects_unknown_flag(vrt, monkeypatch):
    code = run_main(vrt, monkeypatch, ["--nonsense"])
    assert code == 1


# --- --baseline-only / strict_presence ---
#
# The blank-source short-circuit ("nothing recorded yet at the release_table
# baseline" is assumed, never verified) stays completely untouched by
# default; --baseline-only (compare()'s own baseline_only, threaded through
# to check_chart_version_source/check_images_source as strict_presence)
# additionally verifies that assumption, and skips every target-side check
# entirely. See module docstring.


def test_compare_baseline_only_skips_target_side_checks(vrt):
    """Real target-side mismatches (both [CHART] and [IMAGE]) exist here —
    proven by the second, non-baseline_only call below — but must never
    appear when baseline_only=True; only the source side is checked, and
    it's clean here."""
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


def test_compare_chart_version_source_blank_but_justified_no_finding(vrt):
    """A blank source_version_helm IS justified here: the dependency
    genuinely didn't exist at the release_table baseline yet -- must stay
    silent under --baseline-only too, not just by default."""
    deps = [{"name": "newthing", "alias": "", "version": "1.0.0"}]
    rows = [csv_row("New Thing", "newthing", target_helm="1.0.0")]  # source_helm blank
    findings, _ = vrt.compare(
        rows, vrt.ChartState(None, deps, {}, []), baseline=vrt.ChartState(None, [], {}, []), baseline_only=True
    )
    assert findings == {}


def test_compare_chart_version_source_blank_but_unjustified_reports_presence_finding(vrt):
    """The dependency DID already exist at the release_table baseline --
    the blank source_version_helm was never justified, only ever
    checked under --baseline-only (strict_presence)."""
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


def test_compare_chart_version_source_presence_finding_fires_once_per_dependency_not_per_sidecar_row(vrt):
    """Real bug caught live against the actual chart: a Helm chart
    version only ever belongs on ONE of a dependency's own rows (its
    primary row -- structurally, a sidecar row's own source_version_helm
    is ALWAYS blank, by design, same as chart_version_ever_tracked's own
    target-side check already assumes) -- the presence check must mirror
    that per-DEPENDENCY granularity, never fire once per sidecar row."""
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


def test_compare_chart_version_source_blank_unjustified_case_silent_by_default(vrt):
    """Same fixture as the presence finding above, but WITHOUT
    baseline_only -- default behavior is completely unaffected: the blank
    source is silently skipped even though the dependency demonstrably
    did exist at the release_table baseline."""
    deps = [{"name": "existingthing", "alias": "", "version": "1.1.0"}]
    baseline_deps = [{"name": "existingthing", "alias": "", "version": "1.0.0"}]
    rows = [csv_row("Existing Thing", "existingthing", target_helm="1.1.0")]  # source_helm blank
    findings, _ = vrt.compare(
        rows, vrt.ChartState(None, deps, {}, []), baseline=vrt.ChartState(None, baseline_deps, {}, [])
    )
    assert findings == {}


def test_compare_image_source_blank_but_justified_no_finding(vrt):
    """The image genuinely wasn't pinned anywhere at the release_table
    baseline (baseline_lines is empty, and the dependency itself didn't
    exist at baseline either, so the subchart-default fallback has
    nothing to resolve against) -- the blank source_version_app is
    justified, silent under --baseline-only too."""
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


def test_compare_image_source_blank_but_unjustified_reports_presence_finding_scoped_tier(vrt):
    """The image DID already exist at the release_table baseline (found
    via the plain scoped scan, the common tier) -- the blank
    source_version_app was never justified."""
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


def test_compare_image_source_blank_unjustified_case_silent_by_default(vrt):
    """Same fixture as the scoped-tier presence finding above (plus a
    matching target_app, so the EXISTING target-side "app version never
    recorded" check -- an orthogonal, already-covered gap -- doesn't
    also fire and muddy this assertion), but WITHOUT baseline_only:
    default behavior completely unaffected."""
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


def test_compare_image_source_blank_but_unjustified_reports_presence_finding_subchart_fallback_tier(vrt, monkeypatch):
    """Same real-world gap as test_compare_image_source_falls_back_to_
    vendored_subchart_default, but for the blank-source presence check:
    the image only resolves at baseline via the subchart-default
    fallback tier -- must still be caught, not just the plain scoped
    tier."""
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


def test_compare_baseline_only_image_source_ambiguous_stays_ambiguous_not_a_presence_finding(vrt):
    """An ambiguous baseline pin (more than one distinct version) is
    "can't verify", not "confirmed present" -- must never be reported as
    a -PRESENCE finding, even under strict_presence."""
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


def test_main_baseline_only_end_to_end(vrt, tmp_path, monkeypatch, capsys):
    """Full CLI path: target-side mismatches that would otherwise fire
    (a wrong Chart.yaml version, a wrong app version) never appear under
    --baseline-only; the blank-source presence check does."""
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
        # image_basename left blank -- isolates this end-to-end test to the
        # chart-version presence check alone, no subchart/network mocking needed.
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


def test_main_baseline_only_errors_when_baseline_cannot_be_resolved(vrt, tmp_path, monkeypatch, capsys):
    """--baseline-only has nothing left to check at all if the
    release_table baseline itself can't be resolved -- must error out
    loudly (exit 1) rather than silently reporting "OK"."""
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


def test_main_plain_invocation_still_reports_ok_when_baseline_unresolvable(vrt, tmp_path, monkeypatch, capsys):
    """The new hard-error is scoped to --baseline-only only -- a plain
    invocation with an unresolvable baseline keeps warning-and-continuing
    exactly as before (see test_main_unresolvable_release_table_baseline_
    warns_and_keeps_target_checks)."""
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
def test_main_guards_vendored_dependencies_unless_baseline_only(vrt, tmp_path, monkeypatch, argv, expect_guard):
    """The target-side checks read this checkout's own charts/*.tgz, so a
    normal run checks them first; --baseline-only skips every target-side
    check, so it must not be blocked by a stale charts/. The missing
    release-table.csv ends main() right after the guard either way."""
    calls = []
    monkeypatch.setattr(vrt, "require_vendored_dependencies", calls.append)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", tmp_path / "release-table.csv")
    monkeypatch.setattr(vrt.sys, "argv", ["verify-release-table-with-podiumd", *argv])
    with pytest.raises(SystemExit):
        vrt.main()
    assert calls == ([vrt.CHART_DIR] if expect_guard else [])
