"""compare() (the pure comparison core) for verify-release-table-with-podiumd:
version-mismatch checks (target vs. Chart.yaml/values.yaml) and their
source-side siblings (check_chart_version_source/check_images_source, target
vs. release_table baseline). compare() takes plain in-memory deps/values/
lines/rows, so these tests need neither a real Chart.yaml nor network access.

Split out of test_verify_release_table_with_podiumd.py (pylint
too-many-lines) -- purely a test reorganization, no behavior change. See the
sibling test_verify_release_table_with_podiumd_*.py files for the rest of
that suite."""

import io
import tarfile

import pytest
import yaml

DIGEST = "a" * 64


def make_vendored_tgz(chart_dir, name, version, values):
    """A minimal vendored <name>-<version>.tgz under chart_dir/charts/ --
    just enough for lib.chart.subchart_values (via primary_image_
    repositories's own subchart-default fallback, see
    primary_image_basename) to read a real values.yaml out of it,
    mirroring tests/lib/test_chart.py's own make_tgz helper."""
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

# openbao's own PRIMARY image is server.image (lib.chart.COMPONENT_IMAGE_
# PATHS["openbao"]) -- it has an explicit "repository:" override in the
# real chart but an intentionally blank "tag:" (relies on the chart's own
# appVersion default), so it's NEVER actually digest-pinned as text --
# is_primary_image's own text scan correctly finds nothing primary here,
# so primary_image_basename must fall back to its own-override branch of
# lib.chart.primary_image_repositories instead (see openbao_values() --
# server.image DOES have its own "repository:", just no digest-pinned
# "tag:", so no subchart pull/vendored-tgz lookup is ever needed for this
# particular fixture). configuration.job.image and database.schemaJob.
# image are real digest-pinned SIDECARS (openbao's own one-off bao-config
# Job and its postgres schema-migration Job) -- never primary, mirroring
# the real chart's own two separate "openbao" release-table.csv rows, one
# for each.
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
    """The parsed values.yaml equivalent of OPENBAO_BLOCK's own server.
    image block -- needed alongside OPENBAO_BLOCK (the `values` param of
    compare()/check_chart_version/check_images is otherwise only ever
    consulted for SPECIAL_CASE_*_TAG_PATHS lookups elsewhere in this
    suite, so most fixtures here just pass {} — this one can't, since
    primary_image_basename's own-override fallback reads podiumd's
    "repository:" override straight out of this parsed dict, not out of
    `lines`)."""
    return {"openbao": {"server": {"image": {"repository": "openbao/openbao", "tag": tag}}}}


def run_main(vrt, monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-release-table-with-podiumd", *argv])
    with pytest.raises(SystemExit) as exc_info:
        vrt.main()
    return exc_info.value.code


# --- compare(): version mismatches ---


def test_compare_reports_chart_version_mismatch(vrt):
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
    findings, unresolved = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("target 1.0.298 != Chart.yaml 1.0.297" in m for m in findings["mismatches"])
    assert unresolved == []


def test_compare_reports_image_version_mismatch(vrt):
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("target 5.4.4 != values.yaml 5.4.3" in m for m in findings["mismatches"])


def test_compare_no_findings_when_everything_matches(vrt):
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
    findings, unresolved = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert findings == {}
    assert unresolved == []


# --- check_chart_version_source / check_images_source ---


def test_compare_reports_chart_version_source_mismatch(vrt):
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
        deps,
        {},
        values_lines(ZAC_BLOCK),
        baseline_deps=baseline_deps,
        baseline_values={},
        baseline_lines=values_lines(ZAC_BASELINE_BLOCK),
    )
    assert any(
        "[CHART-SOURCE]" in m and "source 1.0.250 != baseline Chart.yaml 1.0.251" in m for m in findings["mismatches"]
    )
    assert unresolved == []


def test_compare_reports_image_version_source_mismatch(vrt):
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
        deps,
        {},
        values_lines(ZAC_BLOCK),
        baseline_deps=baseline_deps,
        baseline_values={},
        baseline_lines=values_lines(ZAC_BASELINE_BLOCK),
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "source 5.0.1 != baseline values.yaml 5.0.2" in m for m in findings["mismatches"]
    )


def test_compare_reports_image_version_source_mismatch_bare_baseline_tag(vrt):
    """Real bug, real chart: podiumd-4.8.5 (this chart's own actual
    release_table baseline) pinned zaakbrug/pabc/ita with a BARE
    (non-digest-pinned) tag — invisible to the plain digest-required
    scanner, silently skipping every such image instead of comparing it.
    check_images_source must still find and compare it (via lib.
    image_version's own *_any_tag siblings)."""
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
        deps,
        {},
        values_lines(zaakbrug_current),
        baseline_deps=baseline_deps,
        baseline_values={},
        baseline_lines=values_lines(zaakbrug_baseline_bare_tag),
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "source 1.26.13 != baseline values.yaml 1.26.15" in m for m in findings["mismatches"]
    )
    assert not any("wasn't pinned anywhere" in m for m in findings.get("mismatches", []))


def test_compare_source_checks_skipped_when_baseline_not_given(vrt):
    """baseline_deps=None (the default) — never attempted at all, not
    'attempted and empty' — so a row with an otherwise-mismatching
    source is never flagged when no baseline was resolved."""
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert not any("SOURCE" in m for m in findings.get("mismatches", []))


def test_compare_new_dependency_at_baseline_with_blank_source_not_flagged(vrt):
    """A brand-new Chart.yaml dependency this release (not in baseline_deps
    at all) with a BLANK source (nothing recorded yet, the normal case for
    something genuinely new) must NOT be flagged — only a row that
    actually CLAIMS a real source version is ever checked against the
    baseline at all (see is_verifiable_target)."""
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
        rows, deps, {}, values_lines(mi_block), baseline_deps=baseline_deps, baseline_values={}, baseline_lines=[]
    )
    assert not any("SOURCE" in m for m in findings.get("mismatches", []))


def test_compare_new_dependency_at_baseline_with_real_source_is_flagged(vrt):
    """The mirror-image case: a row DOES claim a real source chart/app
    version for a dependency that genuinely didn't exist at the
    release_table baseline at all — that claim can't be right no matter
    what it says, so it's flagged, distinct from the ordinary mismatch
    case (there's nothing to compare the claimed value AGAINST)."""
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
        rows, deps, {}, values_lines(mi_block), baseline_deps=baseline_deps, baseline_values={}, baseline_lines=[]
    )
    assert any(
        "[CHART-SOURCE]" in m and "didn't exist at the release_table baseline yet" in m for m in findings["mismatches"]
    )
    assert any(
        "[IMAGE-SOURCE]" in m and "wasn't pinned anywhere" in m and "release_table baseline yet" in m
        for m in findings["mismatches"]
    )


def test_main_unresolvable_release_table_baseline_warns_and_keeps_target_checks(vrt, tmp_path, monkeypatch, capsys):
    """A baseline-resolution failure must never suppress the EXISTING
    target-checks — only the new source-checks are skipped, with exactly
    one clear warning, no crash."""
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


def test_compare_reports_chart_version_never_tracked(vrt):
    """openbao's real-world case: its own Chart.yaml dependency has TWO
    rows in release-table.csv (its own "OpenBao" row, plus a sibling
    "OpenBao Schema Job (postgres)" row for a sidecar image), but
    NEITHER ever recorded a Helm chart version (both source_version_helm
    and target_version_helm blank on every row) -- silently treated as
    "nothing changed" by the plain mismatch check alone, even though the
    chart version was never tracked at all. The hint must name openbao's
    own "OpenBao" row specifically -- NOT the sidecar "postgres" row,
    even though both are on "Technische component versies", which has no
    Helm column at all -- and give the exact remove/add instructions and
    field values (Name, Helm version, App version), not just point at
    "the other three tables" and leave the rest to be worked out by
    hand."""
    deps = [{"name": "openbao", "alias": "", "version": "0.28.4"}]
    rows = [
        {**csv_row("OpenBao", "openbao", image_basename="openbao", target_app="2.5.5"), "section": "Technische"},
        {
            **csv_row("OpenBao Schema Job (postgres)", "openbao", image_basename="postgres", target_app="UNKNOWN"),
            "section": "Technische",
        },
    ]
    findings, _ = vrt.compare(rows, deps, openbao_values(), values_lines(OPENBAO_BLOCK))
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


def test_compare_chart_version_never_tracked_omits_app_version_when_unknown(vrt):
    """If the existing row's own App version isn't known yet either (no
    target, no source), the hint doesn't fabricate one -- it just leaves
    that part out rather than printing a blank or misleading value."""
    deps = [{"name": "openbao", "alias": "", "version": "0.28.4"}]
    rows = [{**csv_row("OpenBao", "openbao", image_basename="openbao"), "section": "Technische"}]
    findings, _ = vrt.compare(rows, deps, openbao_values(), values_lines(OPENBAO_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "'openbao' has release-table" in m)
    assert 'Name "OpenBao", Helm version 0.28.4' in hint
    assert "App version" not in hint


def test_compare_chart_version_never_tracked_names_primary_row_on_other_table(vrt):
    """On a table that DOES have a Helm sub-column (anything but
    "Technische component versies"), the fix is just to fill in the
    existing cell on the component's own primary row -- named
    specifically, not just "this row" or "the table" -- with the exact
    Helm version to write there."""
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert (
        'Confluence: fill in the Helm version cell on "Zaak - ZAC" ("Product component versies") with 1.0.297'
    ) in hint


def test_compare_chart_version_never_tracked_no_primary_row_yet(vrt):
    """Neither existing row claims the component's own primary basename
    yet (only a sidecar row exists so far) -- the hint must not guess
    which row to point at."""
    deps = [{"name": "openbao", "alias": "", "version": "0.28.4"}]
    rows = [
        {
            **csv_row("OpenBao Schema Job (postgres)", "openbao", image_basename="postgres", target_app="UNKNOWN"),
            "section": "Technische",
        }
    ]
    findings, _ = vrt.compare(rows, deps, openbao_values(), values_lines(OPENBAO_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "'openbao' has release-table" in m)
    assert "none of the existing row(s) is this chart's own primary-image row yet" in hint


def test_compare_chart_version_never_tracked_resolves_primary_via_vendored_subchart(vrt, tmp_path):
    """openzaak-style: values.yaml pins a real digest for its own primary
    image but with NO "repository:" of its own at all -- relies entirely
    on the vendored openzaak subchart's own default repository. The plain
    digest-pin text scan (basenames_under_scope) can't compute a basename
    for a pin with no repository, so before this fix the primary row for
    a component shaped like this could never be identified at all --
    primary_image_basename's own subchart-default fallback (lib.chart.
    primary_image_repositories) now resolves it from the vendored .tgz
    instead, with no network access, correctly naming the ONE row that
    claims the resolved "open-zaak" basename."""
    make_vendored_tgz(tmp_path, "openzaak", "4.9.1", {"image": {"repository": "openzaak/open-zaak"}})
    openzaak_block = f'openzaak:\n  image:\n    tag: "3.28.0@sha256:{DIGEST}"\n'
    deps = [{"name": "openzaak", "alias": "", "version": "4.9.1"}]
    rows = [csv_row("Open Zaak", "openzaak", image_basename="open-zaak", target_app="3.28.0")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(openzaak_block), tmp_path)
    hint = next(m for m in findings["missing_from_release_table"] if "'openzaak' has release-table" in m)
    assert 'Confluence: fill in the Helm version cell on "Open Zaak" ("Product component versies")' in hint


@pytest.mark.parametrize("target_app,target_helm", [("", ""), ("UNKNOWN", "UNKNOWN")])
def test_compare_skips_blank_or_unknown_targets(vrt, target_app, target_helm):
    """A blank/UNKNOWN target means "nothing planned to compare" (see
    query-release-table's own UNCHANGED display logic) — not a
    mismatch just because it differs textually from the actual version.
    source_app/source_helm here already match the real, current version
    (see ZAC_BLOCK/deps) — this is the genuinely "already tracked and
    unchanged" case; see the blank-source tests below for what happens
    when neither source nor target has ever recorded a real value."""
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert findings == {}


def test_compare_blank_source_and_target_app_version_never_recorded_is_reported(vrt):
    """Regression test (real bug, confirmed live against the real chart
    and demonstrated by the user manually blanking mi-data's own
    target_version_app in release-table.csv): a row whose app version
    was NEVER recorded at all — source AND target both blank — used to
    report "OK: matches" regardless of what values.yaml actually pins,
    since the whole comparison was gated on is_verifiable_target(target)
    alone. A real, resolvable pin must now be checked against source
    even when target is blank, and reported as "never recorded" when
    source is blank too."""
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("has never recorded an app version" in m for m in findings["missing_from_release_table"])
    assert "mismatches" not in findings


def test_compare_blank_target_but_source_now_stale_is_reported(vrt):
    """A row whose target_version_app is blank ("no planned change") but
    whose own previously-recorded SOURCE has since drifted from the real
    current values.yaml pin — release-table.csv's own "unchanged" claim
    silently went stale and was never caught up. Same class of bug as
    the "never recorded at all" case above, just with a real (now wrong)
    source on file instead of nothing."""
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any(
        "target_version_app was never filled in" in m and "5.4.2" in m and "5.4.3" in m for m in findings["mismatches"]
    )
    assert "missing_from_release_table" not in findings


def test_compare_blank_target_helm_but_source_now_stale_is_reported(vrt):
    """Same class of bug as the app-version case above, for the Helm
    chart version instead: target_version_helm blank ("no planned
    change") but source_version_helm has since drifted from Chart.
    yaml's real current dependency version."""
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any(
        "target_version_helm was never filled in" in m and "1.0.296" in m and "1.0.297" in m
        for m in findings["mismatches"]
    )
