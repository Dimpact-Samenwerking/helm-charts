"""compare(): target-vs-chart version mismatches and their source-side
siblings (vs. the release_table baseline). In-memory inputs; no network."""

import io
import tarfile

from pathlib import Path
from types import ModuleType

import pytest
import yaml

DIGEST = "a" * 64


def make_vendored_tgz(chart_dir, name, version, values):
    """Minimal vendored <name>-<version>.tgz under chart_dir/charts/ with a
    values.yaml, for the subchart-default fallback."""
    charts_dir = chart_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump(values).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


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

# openbao's primary image is server.image: it has a "repository:" override
# but a blank "tag:" (appVersion default), so it is never digest-pinned and
# primary_image_basename falls back to the override branch. The two job
# images are digest-pinned sidecars, matching openbao's two CSV rows.
OPENBAO_BLOCK = (
    "openbao:\n"
    "  server:\n"
    "    image:\n"
    "      repository: openbao/openbao\n"
    '      tag: ""\n'
    "  configuration:\n"
    "    job:\n"
    "      image:\n"
    "        repository: quay.io/openbao/openbao\n"
    f'        tag: "2.5.5@sha256:{DIGEST}"\n'
    "  database:\n"
    "    schemaJob:\n"
    "      image:\n"
    "        repository: library/postgres\n"
    f'        tag: "16-alpine@sha256:{DIGEST}"\n'
)


def openbao_values(tag=""):
    """Parsed server.image block: primary_image_basename's override fallback
    reads "repository:" from `values`, not `lines`, so {} won't do here."""
    return {"openbao": {"server": {"image": {"repository": "openbao/openbao", "tag": tag}}}}


def run_main(vrt: ModuleType, monkeypatch: pytest.MonkeyPatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-release-table-with-podiumd", *argv])
    with pytest.raises(SystemExit) as exc_info:
        vrt.main()
    return exc_info.value.code


# --- compare(): version mismatches ---


def test_compare_reports_chart_version_mismatch(vrt: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            target_app="5.4.3",
            target_helm="1.0.298",
        )
    ]
    findings, unresolved = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    assert any("target 1.0.298 != Chart.yaml 1.0.297" in m for m in findings["mismatches"])
    assert unresolved == []


def test_compare_reports_image_version_mismatch(vrt: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            target_app="5.4.4",
            target_helm="1.0.297",
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    assert any("target 5.4.4 != values.yaml 5.4.3" in m for m in findings["mismatches"])


def test_compare_no_findings_when_everything_matches(vrt: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            target_app="5.4.3",
            target_helm="1.0.297",
        )
    ]
    findings, unresolved = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    assert findings == {}
    assert unresolved == []


# --- check_chart_version_source / check_images_source ---


def test_compare_reports_chart_version_source_mismatch(vrt: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            source_helm="1.0.250",
            target_helm="1.0.297",
        )
    ]
    findings, unresolved = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(ZAC_BASELINE_BLOCK)),
    )
    assert any(
        "[CHART-SOURCE]" in m and "source 1.0.250 != baseline Chart.yaml 1.0.251" in m for m in findings["mismatches"]
    )
    assert unresolved == []


def test_compare_reports_image_version_source_mismatch(vrt: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            source_app="5.0.1",
        )
    ]
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(ZAC_BASELINE_BLOCK)),
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "source 5.0.1 != baseline values.yaml 5.0.2" in m for m in findings["mismatches"]
    )


def test_compare_reports_image_version_source_mismatch_bare_baseline_tag(vrt: ModuleType):
    """podiumd-4.8.5 pinned some images with a bare tag (no digest);
    check_images_source must still compare them via the *_any_tag scans."""
    deps = [{"name": "zaakbrug", "version": "1.1.0"}]
    baseline_deps = [{"name": "zaakbrug", "version": "1.0.0"}]
    rows = [csv_row("Zaak Brug", "zaakbrug", image_basename="zaakbrug", source_app="1.26.13")]
    zaakbrug_current = f'zaakbrug:\n  image:\n    repository: wearefrank/zaakbrug\n    tag: "1.26.18@sha256:{DIGEST}"\n'
    zaakbrug_baseline_bare_tag = (
        "zaakbrug:\n"
        "  image:\n"
        "    repository: wearefrank/zaakbrug\n"
        '    tag: "1.26.15"\n'  # bare, no digest — the real 4.8.5 shape
    )
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(zaakbrug_current)),
        baseline=vrt.ChartState(None, baseline_deps, {}, values_lines(zaakbrug_baseline_bare_tag)),
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "source 1.26.13 != baseline values.yaml 1.26.15" in m for m in findings["mismatches"]
    )
    assert not any("wasn't pinned anywhere" in m for m in findings.get("mismatches", []))


def test_compare_source_checks_skipped_when_baseline_not_given(vrt: ModuleType):
    """baseline_deps=None means "not attempted", so source is never flagged."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            source_app="5.0.1",
            source_helm="1.0.250",
            target_app="5.4.3",
            target_helm="1.0.297",
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    assert not any("SOURCE" in m for m in findings.get("mismatches", []))


def test_compare_new_dependency_at_baseline_with_blank_source_not_flagged(vrt: ModuleType):
    """A new dependency with a blank source is not flagged; only a claimed
    source is checked (see is_verifiable_target)."""
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    baseline_deps = []  # mi-data didn't exist at the release_table baseline yet
    rows = [
        csv_row(
            "MI-data exports",
            "mi-data",
            alias="mi",
            image_basename="azure-cli",
            target_app="2.90.0",
            target_helm="1.1.0",
        )
    ]
    mi_block = f'mi:\n  image:\n    repository: mcr.microsoft.com/azure-cli\n    tag: "2.90.0@sha256:{DIGEST}"\n'
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(mi_block)),
        baseline=vrt.ChartState(None, baseline_deps, {}, []),
    )
    assert not any("SOURCE" in m for m in findings.get("mismatches", []))


def test_compare_new_dependency_at_baseline_with_real_source_is_flagged(vrt: ModuleType):
    """A claimed source for a dependency absent at the baseline is flagged,
    distinctly from a mismatch (nothing to compare against)."""
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    baseline_deps = []
    rows = [
        csv_row(
            "MI-data exports",
            "mi-data",
            alias="mi",
            image_basename="azure-cli",
            source_app="2.71.0",
            source_helm="1.0.0",
            target_app="2.90.0",
            target_helm="1.1.0",
        )
    ]
    mi_block = f'mi:\n  image:\n    repository: mcr.microsoft.com/azure-cli\n    tag: "2.90.0@sha256:{DIGEST}"\n'
    findings, _ = vrt.compare(
        rows,
        vrt.ChartState(None, deps, {}, values_lines(mi_block)),
        baseline=vrt.ChartState(None, baseline_deps, {}, []),
    )
    assert any(
        "[CHART-SOURCE]" in m and "didn't exist at the release_table baseline yet" in m for m in findings["mismatches"]
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "wasn't pinned anywhere" in m and "release_table baseline yet" in m
        for m in findings["mismatches"]
    )


def test_main_unresolvable_release_table_baseline_warns_and_keeps_target_checks(
    vrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A baseline-resolution failure skips only the source checks, with one
    warning; target checks still run."""
    import csv as csv_module

    chart_dir = tmp_path / "chart"
    chart_dir.mkdir()
    chart_yaml = chart_dir / "Chart.yaml"
    values_yaml = chart_dir / "values.yaml"
    release_table = chart_dir / "etc" / "release-table.csv"
    release_table.parent.mkdir()

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

    monkeypatch.setattr(vrt, "CHART_DIR", chart_dir)
    monkeypatch.setattr(vrt, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(vrt, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", release_table)
    monkeypatch.setattr(vrt, "release_table_baseline", lambda chart_dir: "9.9.9")

    code = run_main(vrt, monkeypatch, [])
    out = capsys.readouterr().out
    assert 'WARNING: release_table baseline "9.9.9"' in out
    assert out.count("WARNING:") == 1
    assert code == 1
    assert "Version mismatches" in out
    assert "1.0.297 != Chart.yaml 1.0.298" in out


def test_compare_reports_chart_version_never_tracked(vrt: ModuleType):
    """No row ever recorded a Helm version: the hint must name the primary
    "OpenBao" row (not the sidecar row, both on the Helm-less Technische
    table) and give exact remove/add instructions and field values."""
    deps = [{"name": "openbao", "alias": "", "version": "0.28.4"}]
    rows = [
        {**csv_row("OpenBao", "openbao", image_basename="openbao", target_app="2.5.5"), "section": "Technische"},
        {
            **csv_row("OpenBao Schema Job (postgres)", "openbao", image_basename="postgres", target_app="UNKNOWN"),
            "section": "Technische",
        },
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, openbao_values(), values_lines(OPENBAO_BLOCK)))
    hint = next(m for m in findings["missing_from_release_table"] if "'openbao' has release-table" in m)
    assert (
        "[CHART] Chart.yaml dependency 'openbao' has release-table.csv row(s), but none records "
        "a Helm chart version" in hint
    )
    assert (
        '\n      Confluence: remove "OpenBao" from "Technische component versies" and add it instead '
        'to whichever of "Product/Common Ground/Overige component versies" fits — Name "OpenBao", '
        "Helm version 0.28.4, App version 2.5.5"
    ) in hint
    assert "postgres" not in hint


def test_compare_chart_version_never_tracked_omits_app_version_when_unknown(vrt: ModuleType):
    """An unknown App version is left out of the hint, not fabricated."""
    deps = [{"name": "openbao", "alias": "", "version": "0.28.4"}]
    rows = [{**csv_row("OpenBao", "openbao", image_basename="openbao"), "section": "Technische"}]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, openbao_values(), values_lines(OPENBAO_BLOCK)))
    hint = next(m for m in findings["missing_from_release_table"] if "'openbao' has release-table" in m)
    assert 'Name "OpenBao", Helm version 0.28.4' in hint
    assert "App version" not in hint


def test_compare_chart_version_never_tracked_names_primary_row_on_other_table(vrt: ModuleType):
    """On a table with a Helm column the hint says to fill in the named
    primary row's cell with the exact version."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            target_app="5.4.3",
        )
    ]  # target_helm/source_helm both left blank
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert (
        'Confluence: fill in the Helm version cell on "Zaak - ZAC" ("Product component versies") with 1.0.297'
    ) in hint


def test_compare_chart_version_never_tracked_no_primary_row_yet(vrt: ModuleType):
    """With only a sidecar row, the hint doesn't guess which row to name."""
    deps = [{"name": "openbao", "alias": "", "version": "0.28.4"}]
    rows = [
        {
            **csv_row("OpenBao Schema Job (postgres)", "openbao", image_basename="postgres", target_app="UNKNOWN"),
            "section": "Technische",
        }
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, openbao_values(), values_lines(OPENBAO_BLOCK)))
    hint = next(m for m in findings["missing_from_release_table"] if "'openbao' has release-table" in m)
    assert "none of the existing row(s) is this chart's own primary-image row yet" in hint


def test_compare_chart_version_never_tracked_resolves_primary_via_vendored_subchart(vrt: ModuleType, tmp_path: Path):
    """A digest pin with no own "repository:" (openzaak-style) is identified
    as primary via the vendored subchart default, without network."""
    make_vendored_tgz(tmp_path, "openzaak", "4.9.1", {"image": {"repository": "openzaak/open-zaak"}})
    openzaak_block = f'openzaak:\n  image:\n    tag: "3.28.0@sha256:{DIGEST}"\n'
    deps = [{"name": "openzaak", "alias": "", "version": "4.9.1"}]
    rows = [csv_row("Open Zaak", "openzaak", image_basename="open-zaak", target_app="3.28.0")]
    findings, _ = vrt.compare(rows, vrt.ChartState(tmp_path, deps, {}, values_lines(openzaak_block)))
    hint = next(m for m in findings["missing_from_release_table"] if "'openzaak' has release-table" in m)
    assert 'Confluence: fill in the Helm version cell on "Open Zaak" ("Product component versies")' in hint


@pytest.mark.parametrize(("target_app", "target_helm"), [("", ""), ("UNKNOWN", "UNKNOWN")])
def test_compare_skips_blank_or_unknown_targets(vrt: ModuleType, target_app, target_helm):
    """A blank/UNKNOWN target means "nothing planned", not a mismatch, when
    the source matches the current version."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            source_app="5.4.3",
            source_helm="1.0.297",
            target_app=target_app,
            target_helm=target_helm,
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    assert findings == {}


def test_compare_blank_source_and_target_app_version_never_recorded_is_reported(vrt: ModuleType):
    """Regression: an app version never recorded (source and target blank)
    was reported OK regardless of the pin; a resolvable pin must now be
    checked against source and reported as "never recorded"."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            source_helm="1.0.297",
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    assert any("has never recorded an app version" in m for m in findings["missing_from_release_table"])
    assert "mismatches" not in findings


def test_compare_blank_target_but_source_now_stale_is_reported(vrt: ModuleType):
    """A blank target with a source that drifted from the current pin is
    reported: the CSV's "unchanged" claim went stale."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            source_app="5.4.2",
            source_helm="1.0.297",
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    assert any(
        "target_version_app was never filled in" in m and "5.4.2" in m and "5.4.3" in m for m in findings["mismatches"]
    )
    assert "missing_from_release_table" not in findings


def test_compare_blank_target_helm_but_source_now_stale_is_reported(vrt: ModuleType):
    """Same as above for the Helm version vs. Chart.yaml."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            source_app="5.4.3",
            source_helm="1.0.296",
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    assert any(
        "target_version_helm was never filled in" in m and "1.0.296" in m and "1.0.297" in m
        for m in findings["mismatches"]
    )


# --- compare(): primary row with a blank image_basename ---

OPENFORMS_DEPS = [{"name": "openforms", "alias": "openformulieren", "version": "1.12.0"}]


def _openforms_state(vrt: ModuleType, tag: str):
    values = {"openformulieren": {"image": {"tag": f"{tag}@sha256:{DIGEST}"}}}
    block = f'openformulieren:\n  image:\n    tag: "{tag}@sha256:{DIGEST}"\n'
    return vrt.ChartState(None, OPENFORMS_DEPS, values, values_lines(block))


def _openforms_row(**versions: str):
    return csv_row("Formulier (Open Formulieren)", "openforms", alias="openformulieren", **versions)


def test_compare_checks_primary_row_without_image_basename(vrt: ModuleType):
    """Regression (PR #461): a primary row with blank image_basename was never
    checked, so a values.yaml bump past its version reported OK."""
    findings, _ = vrt.compare([_openforms_row(source_app="3.4.10", target_app="3.5.6")], _openforms_state(vrt, "3.5.8"))
    assert any("3.5.6" in m and "3.5.8" in m for m in findings["mismatches"])


def test_compare_primary_row_without_image_basename_matching_is_clean(vrt: ModuleType):
    findings, _ = vrt.compare([_openforms_row(source_app="3.4.10", target_app="3.5.8")], _openforms_state(vrt, "3.5.8"))
    assert "mismatches" not in findings


def test_compare_primary_row_without_image_basename_ignores_v_prefix(vrt: ModuleType):
    findings, _ = vrt.compare([_openforms_row(target_app="3.5.8")], _openforms_state(vrt, "v3.5.8"))
    assert "mismatches" not in findings


def test_compare_primary_row_without_image_basename_blank_target_uses_source(vrt: ModuleType):
    findings, _ = vrt.compare([_openforms_row(source_app="3.5.6")], _openforms_state(vrt, "3.5.8"))
    assert any("target_version_app was never filled in" in m for m in findings["mismatches"])


def test_compare_two_rows_without_image_basename_are_not_guessed_between(vrt: ModuleType):
    """With two blank rows there is no telling which one is primary."""
    rows = [_openforms_row(target_app="1.0.0"), _openforms_row(target_app="2.0.0")]
    findings, _ = vrt.compare(rows, _openforms_state(vrt, "3.5.8"))
    assert "mismatches" not in findings
