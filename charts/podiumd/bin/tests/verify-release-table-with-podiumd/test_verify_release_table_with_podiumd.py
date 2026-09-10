"""compare() (the pure comparison core) and main() for
verify-release-table-with-podiumd. compare() takes plain in-memory
deps/values/lines/rows, so these tests need neither a real Chart.yaml nor
network access; main()'s own tests just cover its file-loading/CLI glue."""
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


def csv_row(name, component, alias="", image_basename="", source_app="", source_helm="",
            target_app="", target_helm=""):
    return {
        "section": "Product", "vendor": "", "used_by": "", "name": name, "component": component,
        "alias": alias, "image_basename": image_basename, "source_version_app": source_app,
        "source_version_helm": source_helm, "target_version_app": target_app, "target_version_helm": target_helm,
    }


def values_lines(*blocks):
    return "\n".join(blocks).splitlines()


ZAC_BLOCK = (
    "zac:\n"
    "  image:\n"
    "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
    f'    tag: "5.4.3@sha256:{DIGEST}"\n'
)

# zac's own PRIMARY image (zac.image, matching lib.chart.
# DEFAULT_IMAGE_PATHS) plus a sidecar image nested elsewhere (zac.
# opentelemetry-collector.image) that is NEVER zac's primary image, no
# matter how deep or shallow the nesting -- see lib.chart.
# image_paths_for / COMPONENT_IMAGE_PATHS.
ZAC_WITH_SIDECAR_BLOCK = ZAC_BLOCK + (
    "  opentelemetry-collector:\n"
    "    image:\n"
    "      repository: otel/opentelemetry-collector-contrib\n"
    f'      tag: "0.158.0@sha256:{DIGEST}"\n'
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


# --- compare(): version mismatches ---

def test_compare_reports_chart_version_mismatch(vrt):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_app="5.4.3", target_helm="1.0.298")]
    findings, unresolved = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("target 1.0.298 != Chart.yaml 1.0.297" in m for m in findings["mismatches"])
    assert unresolved == []


def test_compare_reports_image_version_mismatch(vrt):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_app="5.4.4", target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("target 5.4.4 != values.yaml 5.4.3" in m for m in findings["mismatches"])


def test_compare_no_findings_when_everything_matches(vrt):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_app="5.4.3", target_helm="1.0.297")]
    findings, unresolved = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert findings == {}
    assert unresolved == []


# --- check_chart_version_source / check_images_source ---

ZAC_BASELINE_BLOCK = (
    "zac:\n"
    "  image:\n"
    "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
    f'    tag: "5.0.2@sha256:{DIGEST}"\n'
)


def test_compare_reports_chart_version_source_mismatch(vrt):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     source_helm="1.0.250", target_helm="1.0.297")]
    findings, unresolved = vrt.compare(
        rows, deps, {}, values_lines(ZAC_BLOCK),
        baseline_deps=baseline_deps, baseline_values={}, baseline_lines=values_lines(ZAC_BASELINE_BLOCK))
    assert any("[CHART-SOURCE]" in m and "source 1.0.250 != baseline Chart.yaml 1.0.251" in m
               for m in findings["mismatches"])
    assert unresolved == []


def test_compare_reports_image_version_source_mismatch(vrt):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     source_app="5.0.1")]
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(ZAC_BLOCK),
        baseline_deps=baseline_deps, baseline_values={}, baseline_lines=values_lines(ZAC_BASELINE_BLOCK))
    assert any("[IMAGE-SOURCE]" in m and "source 5.0.1 != baseline values.yaml 5.0.2" in m
               for m in findings["mismatches"])


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
    zaakbrug_current = (
        "zaakbrug:\n"
        "  image:\n"
        "    repository: wearefrank/zaakbrug\n"
        f'    tag: "1.26.18@sha256:{DIGEST}"\n'
    )
    zaakbrug_baseline_bare_tag = (
        "zaakbrug:\n"
        "  image:\n"
        "    repository: wearefrank/zaakbrug\n"
        '    tag: "1.26.15"\n'  # bare, no digest — the real 4.8.5 shape
    )
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(zaakbrug_current),
        baseline_deps=baseline_deps, baseline_values={}, baseline_lines=values_lines(zaakbrug_baseline_bare_tag))
    assert any("[IMAGE-SOURCE]" in m and "source 1.26.13 != baseline values.yaml 1.26.15" in m
               for m in findings["mismatches"])
    assert not any("wasn't pinned anywhere" in m for m in findings.get("mismatches", []))


def test_compare_source_checks_skipped_when_baseline_not_given(vrt):
    """baseline_deps=None (the default) — never attempted at all, not
    'attempted and empty' — so a row with an otherwise-mismatching
    source is never flagged when no baseline was resolved."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     source_app="5.0.1", source_helm="1.0.250", target_app="5.4.3", target_helm="1.0.297")]
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
    rows = [csv_row("MI-data exports", "mi-data", alias="mi", image_basename="azure-cli",
                     target_app="2.90.0", target_helm="1.1.0")]
    mi_block = (
        "mi:\n"
        "  image:\n"
        "    repository: mcr.microsoft.com/azure-cli\n"
        f'    tag: "2.90.0@sha256:{DIGEST}"\n'
    )
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(mi_block),
        baseline_deps=baseline_deps, baseline_values={}, baseline_lines=[])
    assert not any("SOURCE" in m for m in findings.get("mismatches", []))


def test_compare_new_dependency_at_baseline_with_real_source_is_flagged(vrt):
    """The mirror-image case: a row DOES claim a real source chart/app
    version for a dependency that genuinely didn't exist at the
    release_table baseline at all — that claim can't be right no matter
    what it says, so it's flagged, distinct from the ordinary mismatch
    case (there's nothing to compare the claimed value AGAINST)."""
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    baseline_deps = []
    rows = [csv_row("MI-data exports", "mi-data", alias="mi", image_basename="azure-cli",
                     source_app="2.71.0", source_helm="1.0.0", target_app="2.90.0", target_helm="1.1.0")]
    mi_block = (
        "mi:\n"
        "  image:\n"
        "    repository: mcr.microsoft.com/azure-cli\n"
        f'    tag: "2.90.0@sha256:{DIGEST}"\n'
    )
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(mi_block),
        baseline_deps=baseline_deps, baseline_values={}, baseline_lines=[])
    assert any("[CHART-SOURCE]" in m and "didn't exist at the release_table baseline yet" in m
               for m in findings["mismatches"])
    assert any("[IMAGE-SOURCE]" in m and "wasn't pinned anywhere" in m and "release_table baseline yet" in m
               for m in findings["mismatches"])


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
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.298\n"
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(ZAC_BLOCK, encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(csv_row("x", "y").keys()))
        writer.writeheader()
        writer.writerow(csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac",
                                 image_basename="zaakafhandelcomponent", target_app="5.4.3", target_helm="1.0.297"))

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
        {**csv_row("OpenBao Schema Job (postgres)", "openbao", image_basename="postgres", target_app="UNKNOWN"),
         "section": "Technische"},
    ]
    findings, _ = vrt.compare(rows, deps, openbao_values(), values_lines(OPENBAO_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "'openbao' has release-table" in m)
    assert "[CHART] Chart.yaml dependency 'openbao' has release-table.csv row(s), but none records " \
           "a Helm chart version" in hint
    assert ('\n      Confluence: remove "OpenBao" from "Technische component versies" and add it instead '
            'to whichever of "Product/Common Ground/Overige component versies" fits — Name "OpenBao", '
            'Helm version 0.28.4, App version 2.5.5') in hint
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
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_app="5.4.3")]  # target_helm/source_helm both left blank
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert ('Confluence: fill in the Helm version cell on "Zaak - ZAC" ("Product component versies") '
            'with 1.0.297') in hint


def test_compare_chart_version_never_tracked_no_primary_row_yet(vrt):
    """Neither existing row claims the component's own primary basename
    yet (only a sidecar row exists so far) -- the hint must not guess
    which row to point at."""
    deps = [{"name": "openbao", "alias": "", "version": "0.28.4"}]
    rows = [{**csv_row("OpenBao Schema Job (postgres)", "openbao", image_basename="postgres", target_app="UNKNOWN"),
             "section": "Technische"}]
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
    openzaak_block = (
        "openzaak:\n"
        "  image:\n"
        f'    tag: "3.28.0@sha256:{DIGEST}"\n'
    )
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
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     source_app="5.4.3", source_helm="1.0.297", target_app=target_app, target_helm=target_helm)]
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
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     source_helm="1.0.297")]
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
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     source_app="5.4.2", source_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("target_version_app was never filled in" in m and "5.4.2" in m and "5.4.3" in m
               for m in findings["mismatches"])
    assert "missing_from_release_table" not in findings


def test_compare_blank_target_helm_but_source_now_stale_is_reported(vrt):
    """Same class of bug as the app-version case above, for the Helm
    chart version instead: target_version_helm blank ("no planned
    change") but source_version_helm has since drifted from Chart.
    yaml's real current dependency version."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     source_app="5.4.3", source_helm="1.0.296")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("target_version_helm was never filled in" in m and "1.0.296" in m and "1.0.297" in m
               for m in findings["mismatches"])


# --- is_primary_image ---

def test_is_primary_image_default_path(vrt):
    """DEFAULT_IMAGE_PATHS (["image"]) covers the common single-image
    component -- zac's own "zaakafhandelcomponent" pin, at zac.image.tag."""
    lines = values_lines(ZAC_BLOCK)
    pins = vrt.basenames_under_scope_any_tag(lines, "zac")["zaakafhandelcomponent"]
    assert vrt.is_primary_image("zaakafhandelcomponent", lines, pins[0]) is True


def test_is_primary_image_false_for_sidecar(vrt):
    """A sidecar image nested elsewhere is never the component's primary
    one, no matter how deep or shallow the nesting."""
    lines = values_lines(ZAC_WITH_SIDECAR_BLOCK)
    pins = vrt.basenames_under_scope_any_tag(lines, "zac")["opentelemetry-collector-contrib"]
    assert vrt.is_primary_image("zaakafhandelcomponent", lines, pins[0]) is False


def test_is_primary_image_multi_image_component_override(vrt):
    """COMPONENT_IMAGE_PATHS overrides DEFAULT_IMAGE_PATHS for a multi-
    image component -- zgw-office-addin's own frontend+backend are BOTH
    primary, per lib.chart.COMPONENT_IMAGE_PATHS."""
    lines = values_lines(
        "zgw-office-addin:\n"
        "  frontend:\n"
        "    image:\n"
        "      repository: ghcr.io/infonl/zgw-office-addin-frontend\n"
        f'      tag: "1.0.0@sha256:{DIGEST}"\n'
        "  backend:\n"
        "    image:\n"
        "      repository: ghcr.io/infonl/zgw-office-addin-backend\n"
        f'      tag: "1.0.0@sha256:{DIGEST}"\n'
    )
    available = vrt.basenames_under_scope_any_tag(lines, "zgw-office-addin")
    frontend_pin = available["zgw-office-addin-frontend"][0]
    backend_pin = available["zgw-office-addin-backend"][0]
    assert vrt.is_primary_image("zgw-office-addin", lines, frontend_pin) is True
    assert vrt.is_primary_image("zgw-office-addin", lines, backend_pin) is True


# --- compare(): missing from release-table.csv ---

def test_compare_reports_dependency_with_no_release_table_row(vrt):
    deps = [{"name": "openklant", "alias": "", "version": "1.11.0"}]
    findings, _ = vrt.compare([], deps, {}, [])
    assert any("Chart.yaml dependency 'openklant'" in m for m in findings["missing_from_release_table"])


def test_compare_dependency_missing_hint_names_resolvable_identifier(vrt):
    """The finding's own second line must tell a human exactly what text
    to write on the Confluence page so the NEXT export resolves this row
    back to the same dependency (see lib.export's component_and_alias) —
    the dependency's own alias when it has one (a real Chart.yaml
    dependency's alias always wins an exact-match tier on its own)."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    findings, _ = vrt.compare([], deps, {}, [])
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert "\n      Confluence: add row to whichever table fits" in hint
    assert 'Name or "Used by": "zac"' in hint


def test_compare_reports_image_pinned_but_not_tracked(vrt):
    """values.yaml pins an image under zac's own scope that no
    release-table.csv row mentions at all."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="",
                     target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("'zaakafhandelcomponent' is pinned in values.yaml but not tracked" in m
               for m in findings["missing_from_release_table"])


def test_compare_missing_image_hint_names_table_and_resolvable_row_text(vrt):
    """The finding's own second line must name the exact Confluence table
    (read off this component's own existing row) and exactly what a new
    row needs to say — a Name containing the missing basename — so
    resolve_image_basenames/component_and_alias resolve it on the next
    export, not just a vague pointer to "add it somewhere". No "Used by"
    mentioned: "Product component versies" (like Common Ground/Overige)
    has no such column at all -- only "Technische component versies"
    does (see missing_image_hint). The version is explicitly labeled
    "App" since this table still splits its "Versie ..." column into
    separate App/Helm sub-columns — a human needs to know which one to
    fill in."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="",
                     target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert '\n      Confluence: add row to "Product component versies"' in hint
    assert 'Name containing "zaakafhandelcomponent"' in hint
    assert "Used by" not in hint
    assert "App version (currently) 5.4.3" in hint


def test_compare_missing_primary_image_uses_own_table_without_used_by(vrt):
    """A component's own PRIMARY application image (see lib.chart.
    image_paths_for/DEFAULT_IMAGE_PATHS -- zac.image, here) never needs
    "Used by", even when its only tracked row happens to live on
    "Technische component versies": it's this row's own identity, not a
    sibling image being attributed to some other consuming component."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [{**csv_row("Elastic operator", "zaakafhandelcomponent", alias="zac", image_basename="",
                       target_helm="1.0.297"), "section": "Technische"}]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert '\n      Confluence: add row to "Technische component versies"' in hint
    assert 'Name containing "zaakafhandelcomponent"' in hint
    assert "Used by" not in hint


def test_compare_missing_sidecar_image_always_goes_to_technische_with_used_by(vrt):
    """A component's own sidecar/init-container image -- NOT its primary
    application image, see lib.chart.image_paths_for -- always goes to
    "Technische component versies" with "Used by" naming the component,
    regardless of which table the component's own primary row actually
    lives on (here, "Product")."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac",
                     image_basename="zaakafhandelcomponent", target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_WITH_SIDECAR_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"]
                if "opentelemetry-collector-contrib" in m)
    assert '\n      Confluence: add row to "Technische component versies"' in hint
    assert '"Used by": "zac", Name containing "opentelemetry-collector-contrib"' in hint


# --- compare(): missing from Chart.yaml / values.yaml ---

def test_compare_reports_row_component_no_longer_a_dependency(vrt):
    rows = [csv_row("Long Gone", "longgone")]
    findings, _ = vrt.compare(rows, [], {}, [])
    assert any("resolves to component 'longgone', which is not a Chart.yaml dependency" in m
               for m in findings["missing_from_chart"])


def test_compare_reports_tracked_image_no_longer_pinned(vrt):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_helm="1.0.297"),
            csv_row("Zaak - ZAC OPA", "zaakafhandelcomponent", alias="zac", image_basename="opa",
                     target_app="1.17.1", target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("release-table image 'opa' for component 'zaakafhandelcomponent'" in m
               for m in findings["missing_from_chart"])


# --- compare(): orphan components (no separate Chart.yaml dependency) ---

def test_compare_checks_images_for_orphan_values_yaml_component(vrt):
    """frankgateway-style: no Chart.yaml dependency, but a real top-level
    values.yaml key — its own image(s) are still checked, just without a
    chart-version comparison (no Chart.yaml "version:" to compare against)."""
    frank_block = (
        "frankgateway:\n"
        "  image:\n"
        "    repository: ghcr.io/wearefrank/frank-gateway\n"
        f'    tag: "1.1.0@sha256:{DIGEST}"\n'
    )
    rows = [csv_row("Frank Gateway", "frankgateway", image_basename="frank-gateway", target_app="1.1.1")]
    findings, unresolved = vrt.compare(rows, [], {"frankgateway": {}}, values_lines(frank_block))
    assert any("target 1.1.1 != values.yaml 1.1.0" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings
    assert unresolved == []


def test_compare_orphan_component_absent_from_values_yaml_is_missing_from_chart(vrt):
    rows = [csv_row("Frank Gateway", "frankgateway")]
    findings, _ = vrt.compare(rows, [], {}, [])
    assert any("component 'frankgateway'" in m for m in findings["missing_from_chart"])


# --- compare(): ambiguous pins ---

def test_compare_reports_ambiguous_when_basename_pinned_at_multiple_versions(vrt):
    block = (
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
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="curl", target_app="8.22.0")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(block))
    assert any("pinned at 2 different versions" in m for m in findings["ambiguous"])
    assert "mismatches" not in findings


# --- compare(): unresolved components ---

@pytest.mark.parametrize("component", ["", "UNKNOWN"])
def test_compare_lists_unresolved_rows_separately(vrt, component):
    rows = [csv_row("Solr", component)]
    findings, unresolved = vrt.compare(rows, [], {}, [])
    assert findings == {}
    assert unresolved == rows


# --- compare(): MULTIPLE (global.images) rows ---

GLOBAL_CURL_BLOCK = (
    "global:\n"
    "  images:\n"
    "    curl:\n"
    "      repository: docker.io/curlimages/curl\n"
    f'      tag: "8.22.0@sha256:{DIGEST}"\n'
)


def test_compare_checks_multiple_row_against_global_images(vrt):
    """A "MULTIPLE" row (a shared base image like curl, hoisted into
    values.yaml's global.images map) is checked against the "global"
    scope, not skipped as unresolved."""
    rows = [csv_row("Curl", "MULTIPLE", alias="MULTIPLE", image_basename="curl", target_app="8.23.0")]
    findings, unresolved = vrt.compare(rows, [], {}, values_lines(GLOBAL_CURL_BLOCK))
    assert any("target 8.23.0 != values.yaml 8.22.0" in m for m in findings["mismatches"])
    assert unresolved == []


def test_compare_multiple_row_matching_global_image_passes(vrt):
    rows = [csv_row("Curl", "MULTIPLE", alias="MULTIPLE", image_basename="curl", target_app="8.22.0")]
    findings, unresolved = vrt.compare(rows, [], {}, values_lines(GLOBAL_CURL_BLOCK))
    assert findings == {}
    assert unresolved == []


def test_compare_multiple_row_with_no_image_basename_is_silently_skipped(vrt):
    """A "MULTIPLE" row export-confluence-release-table couldn't even
    resolve an image_basename for (an ambiguous plain dependency-name
    collision, not a global image) has nothing to check — not an error."""
    rows = [csv_row("Something Ambiguous", "MULTIPLE", alias="MULTIPLE", image_basename="")]
    findings, unresolved = vrt.compare(rows, [], {}, [])
    assert findings == {}
    assert unresolved == []


def test_compare_reports_global_image_with_no_release_table_row(vrt):
    findings, _ = vrt.compare([], [], {}, values_lines(GLOBAL_CURL_BLOCK))
    assert any("'global' image 'curl' is pinned in values.yaml but not tracked" in m
               for m in findings["missing_from_release_table"])


def test_compare_missing_multiple_image_hint_has_no_used_by_and_guesses_technische(vrt):
    """A MULTIPLE row resolves purely from its own Name relating to the
    global image key -- no "Used by" needed (see
    resolve_image_basenames). With zero existing "MULTIPLE" rows to read
    a section from at all, "Technische" is still a safe guess (every
    global.images entry is, by convention, exported there)."""
    findings, _ = vrt.compare([], [], {}, values_lines(GLOBAL_CURL_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "'global' image 'curl'" in m)
    assert '\n      Confluence: add row to "Technische component versies"' in hint
    assert 'Name containing "curl"' in hint
    assert "Used by" not in hint
    assert "App version (currently) 8.22.0" in hint


# --- multi-image component (e.g. zgw-office-addin) ---

def test_compare_multi_image_component_checks_every_basename(vrt):
    block = (
        "zgw-office-addin:\n"
        "  frontend:\n"
        "    image:\n"
        "      repository: ghcr.io/infonl/zgw-office-addin-frontend\n"
        f'      tag: "0.11.0@sha256:{"a" * 64}"\n'
        "  backend:\n"
        "    image:\n"
        "      repository: ghcr.io/infonl/zgw-office-addin-backend\n"
        f'      tag: "0.11.0@sha256:{"b" * 64}"\n'
    )
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.0.92"}]
    rows = [csv_row("Office Add-in", "zgw-office-addin",
                     image_basename="zgw-office-addin-frontend,zgw-office-addin-backend",
                     target_app="0.12.0", target_helm="0.0.92")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(block))
    assert len(findings["mismatches"]) == 2
    assert any("zgw-office-addin-frontend" in m for m in findings["mismatches"])
    assert any("zgw-office-addin-backend" in m for m in findings["mismatches"])


# --- compare(): special-case images (not seen by the normal digest-pin scan) ---

def keycloak_values(tag="26.7.2"):
    return {"keycloak-operator": {"operator": {"config": {"keycloakImage": {
        "repository": "quay.io/keycloak/keycloak", "tag": tag, "sha": "deadbeef",
    }}}}}


def test_compare_checks_keycloak_special_case_image(vrt):
    """keycloak-operator's own actual Keycloak SERVER image lives as a
    split "tag:"/"sha:" field pair, not a plain "image:" block — invisible
    to the normal digest-pin scan regardless of scope, so its plain tag is
    read directly instead (see SPECIAL_CASE_BASENAME_TAG_PATHS)."""
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [csv_row("Keycloak", "keycloak-operator", image_basename="keycloak", target_app="26.7.3")]
    findings, _ = vrt.compare(rows, deps, keycloak_values(), [])
    assert any("target 26.7.3 != values.yaml 26.7.2" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings


def test_compare_keycloak_special_case_image_matching_passes(vrt):
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [csv_row("Keycloak", "keycloak-operator", image_basename="keycloak",
                     source_helm="1.12.1", target_app="26.7.2")]
    findings, _ = vrt.compare(rows, deps, keycloak_values(), [])
    assert findings == {}


def test_compare_finds_basename_pinned_under_a_sibling_scope(vrt):
    """keycloak-config-cli lives under top-level "keycloak" (a values.yaml
    sibling block, separate from keycloak-operator's own scope) — a
    basename is a real repository identity, not a values.yaml path, so it
    can be pinned somewhere other than its own component's scope. Found
    via the same whole-file find_matches fallback update-image-version's
    own <target> resolution uses (lib.image_version.resolve_basename)."""
    keycloak_config_cli_block = (
        "keycloak:\n"
        "  keycloakConfigCli:\n"
        "    image:\n"
        "      repository: adorsys/keycloak-config-cli\n"
        f'      tag: "6.5.1-26@sha256:{"c" * 64}"\n'
    )
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [csv_row("Keycloak Config CLI", "keycloak-operator", image_basename="keycloak-config-cli",
                     target_app="6.5.2-27")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(keycloak_config_cli_block))
    assert any("target 6.5.2-27 != values.yaml 6.5.1-26" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings


def test_compare_sibling_scope_basename_matching_passes(vrt):
    keycloak_config_cli_block = (
        "keycloak:\n"
        "  keycloakConfigCli:\n"
        "    image:\n"
        "      repository: adorsys/keycloak-config-cli\n"
        f'      tag: "6.5.1-26@sha256:{"c" * 64}"\n'
    )
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [csv_row("Keycloak Config CLI", "keycloak-operator", image_basename="keycloak-config-cli",
                     source_helm="1.12.1", target_app="6.5.1-26")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(keycloak_config_cli_block))
    assert findings == {}


def test_compare_image_source_sibling_scope_basename_still_matches(vrt):
    """The EXISTING working case (keycloak-config-cli, a real image
    pinned under a SIBLING scope — see test_compare_finds_basename_
    pinned_under_a_sibling_scope) must still resolve correctly once the
    baseline-side unscoped fallback gets its own cross-check against the
    CURRENT chart's own real repository for the same <scope, basename>:
    this is the legitimate case the fallback exists for, and must never
    regress just because a DIFFERENT, coincidental collision (see below)
    now gets rejected."""
    current_block = (
        "keycloak:\n"
        "  keycloakConfigCli:\n"
        "    image:\n"
        "      repository: adorsys/keycloak-config-cli\n"
        f'      tag: "6.5.2-27@sha256:{"c" * 64}"\n'
    )
    baseline_block = (
        "keycloak:\n"
        "  keycloakConfigCli:\n"
        "    image:\n"
        "      repository: adorsys/keycloak-config-cli\n"
        f'      tag: "6.5.1-26@sha256:{"c" * 64}"\n'
    )
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    baseline_deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.0"}]
    rows = [csv_row("Keycloak Config CLI", "keycloak-operator", image_basename="keycloak-config-cli",
                     source_app="6.5.1-26", target_app="6.5.2-27",
                     source_helm="1.12.0", target_helm="1.12.1")]
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(current_block),
        baseline_deps=baseline_deps, baseline_values={}, baseline_lines=values_lines(baseline_block))
    assert findings == {}


def test_compare_image_source_rejects_stripped_name_collision(vrt):
    """Regression test: the same real redis/redis-operator basename
    collision fixed twice already today (lib.chart.historical_app_
    version_for_repository/find_images_manifest_list_diff, commits
    c3b27bed/9b9680c1) applies equally to THIS function's own unscoped
    find_matches_any_tag fallback. global.images.redis genuinely doesn't
    exist yet at this baseline; redis-operator's own, completely
    unrelated quay.io/opstree/redis pin (which also reduces to bare
    basename "redis") must never be accepted as if it were global.
    images.redis's own baseline value — the baseline is correctly
    reported as never having had this image pinned at all, not silently
    matched to the wrong one."""
    current_block = (
        "global:\n"
        "  images:\n"
        "    redis:\n"
        "      repository: redis\n"
        f'      tag: "8.0@sha256:{"d" * 64}"\n'
    )
    baseline_block = (
        "redis-operator:\n"
        "  redis-ha:\n"
        "    image:\n"
        "      repository: quay.io/opstree/redis\n"
        f'      tag: "v8.6.2@sha256:{"e" * 64}"\n'
    )
    rows = [csv_row("Redis", "MULTIPLE", alias="MULTIPLE", image_basename="redis", source_app="8.0")]
    findings, _ = vrt.compare(
        rows, [], {}, values_lines(current_block),
        baseline_deps=[], baseline_values={}, baseline_lines=values_lines(baseline_block))
    assert any("[IMAGE-SOURCE]" in m and "wasn't pinned anywhere" in m and "release_table baseline yet" in m
               for m in findings["mismatches"])
    assert not any("8.6.2" in m for m in findings["mismatches"])


# --- check_images_source: vendored-subchart-default fallback ---
# Real bug, real chart: at podiumd-4.8.5, brp-personen-mock/clamav/kiss's own
# crawler/objecten/open-klant/zaakbrug each had only an explicit "tag:" for
# their own primary image, no "repository:" override at all — relying
# entirely on their vendored subchart's own default repository, exactly like
# primary_image_basename's own CURRENT-side fallback already handles (see
# lib.chart.primary_image_repositories). primary_image_repositories itself
# is monkeypatched here (rather than vendoring a real .tgz or hitting the
# network) — its own pull/vendored-tgz resolution already has its own test
# coverage elsewhere; these tests are purely about check_images_source's own
# NEW consumption of it (matching a resolved repository to `basename`,
# reading the ACTUAL pinned tag from baseline_values, and degrading
# gracefully on failure).

CLAMAV_CURRENT_BLOCK = (
    "clamav:\n"
    "  image:\n"
    "    repository: docker.io/clamav/clamav\n"
    f'    tag: "1.5.3@sha256:{"a" * 64}"\n'
)
CLAMAV_BASELINE_BLOCK = (
    "clamav:\n"
    "  image:\n"
    '    tag: "1.5.2"\n'  # no repository override at all — the real 4.8.5 shape
)
CLAMAV_BASELINE_VALUES = {"clamav": {"image": {"tag": "1.5.2"}}}


def test_compare_image_source_falls_back_to_vendored_subchart_default(vrt, monkeypatch):
    """Regression test: the vendored-subchart-default fallback resolves a
    real, comparable baseline version instead of reporting "wasn't pinned
    anywhere" — the matching source_app must be accepted as OK."""
    monkeypatch.setattr(vrt, "primary_image_repositories",
                         lambda chart_dir, dep, values, allow_pull=True: ({"image": "docker.io/clamav/clamav"},
                                                                           None))
    dep = {"name": "clamav", "version": "3.9.0"}
    baseline_dep = {"name": "clamav", "version": "3.7.1"}
    rows = [csv_row("ClamAV", "clamav", image_basename="clamav", source_app="1.5.2", target_app="1.5.3",
                     source_helm="3.7.1", target_helm="3.9.0")]
    findings, _ = vrt.compare(
        rows, [dep], {}, values_lines(CLAMAV_CURRENT_BLOCK), chart_dir="/fake/chart/dir",
        baseline_deps=[baseline_dep], baseline_values=CLAMAV_BASELINE_VALUES,
        baseline_lines=values_lines(CLAMAV_BASELINE_BLOCK))
    assert findings == {}


def test_compare_image_source_vendored_subchart_default_still_catches_mismatch(vrt, monkeypatch):
    """The mirror-image case: the vendored-subchart-default fallback DOES
    resolve a real baseline version, and it genuinely disagrees with
    release-table.csv's own claimed source — still reported, just via a
    distinctly-worded finding (never silently accepted just because it
    took a different resolution path than the plain text scan)."""
    monkeypatch.setattr(vrt, "primary_image_repositories",
                         lambda chart_dir, dep, values, allow_pull=True: ({"image": "docker.io/clamav/clamav"},
                                                                           None))
    dep = {"name": "clamav", "version": "3.9.0"}
    baseline_dep = {"name": "clamav", "version": "3.7.1"}
    rows = [csv_row("ClamAV", "clamav", image_basename="clamav", source_app="1.5.9", target_app="1.5.3",
                     source_helm="3.7.1", target_helm="3.9.0")]
    findings, _ = vrt.compare(
        rows, [dep], {}, values_lines(CLAMAV_CURRENT_BLOCK), chart_dir="/fake/chart/dir",
        baseline_deps=[baseline_dep], baseline_values=CLAMAV_BASELINE_VALUES,
        baseline_lines=values_lines(CLAMAV_BASELINE_BLOCK))
    assert any("[IMAGE-SOURCE]" in m and "source 1.5.9" in m and "baseline subchart-default values.yaml 1.5.2" in m
               for m in findings["mismatches"])
    assert not any("wasn't pinned anywhere" in m for m in findings.get("mismatches", []))


def test_compare_image_source_vendored_subchart_default_resolution_failure_is_reported_honestly(vrt, monkeypatch):
    """A pull failure (no network, or the historical chart version
    genuinely no longer exists) must never be silently forced into
    "wasn't pinned anywhere" (actively wrong: something WAS pinned, this
    just couldn't confirm what) or crash — it's a distinct, honest
    "can't verify" finding instead."""
    monkeypatch.setattr(vrt, "primary_image_repositories",
                         lambda chart_dir, dep, values, allow_pull=True:
                             ({"image": None}, "helm pull failed: no such chart version"))
    dep = {"name": "clamav", "version": "3.9.0"}
    baseline_dep = {"name": "clamav", "version": "3.7.1"}
    rows = [csv_row("ClamAV", "clamav", image_basename="clamav", source_app="1.5.2", target_app="1.5.3",
                     source_helm="3.7.1", target_helm="3.9.0")]
    findings, _ = vrt.compare(
        rows, [dep], {}, values_lines(CLAMAV_CURRENT_BLOCK), chart_dir="/fake/chart/dir",
        baseline_deps=[baseline_dep], baseline_values=CLAMAV_BASELINE_VALUES,
        baseline_lines=values_lines(CLAMAV_BASELINE_BLOCK))
    assert any("[IMAGE-SOURCE]" in m and "couldn't be resolved to verify" in m and
               "helm pull failed: no such chart version" in m for m in findings["ambiguous"])
    assert not any("wasn't pinned anywhere" in m for m in findings.get("mismatches", []))


# omc's own "image:" tag has no ACTIVE "repository:" key at all (a
# commented-out sibling instead) — its subchart can't handle a digest,
# so export-confluence-release-table's own resolve_image_basenames now
# falls back to the digest-OPTIONAL scanner for it, and its release-
# table.csv row's image_basename column is a real, non-blank
# "notifynl-omc" (see export-confluence-release-table's own module
# docstring) — the exact same row shape every other component's row
# already has, no special-casing needed anywhere downstream any more.
# THIS script's own digest-OPTIONAL scanner (scan_version_pins, via
# resolve_pin_repo's own commented-out-sibling fallback) resolves the
# same basename regardless — real values.yaml shape, not a synthetic one.
OMC_BLOCK = (
    "omc:\n"
    "  image:\n"
    "    # repository: docker.io/worthnl/notifynl-omc\n"
    '    tag: "1.17.19"\n'
)


def test_compare_omc_image_matches_via_ordinary_basename_path(vrt):
    """omc's row now round-trips through the completely standard
    basename-matching path check_images already applies to every other
    component — no special-casing at all, just a real, non-blank
    image_basename column ("notifynl-omc")."""
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    rows = [csv_row("OMC / Notify", "notifynl-omc-nodep", alias="omc", image_basename="notifynl-omc",
                     target_app="1.17.19", target_helm="0.14.1")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(OMC_BLOCK))
    assert findings == {}


def test_compare_omc_image_mismatch_via_ordinary_basename_path(vrt):
    """Same ordinary path, but the target version genuinely disagrees
    with what's actually pinned — must still be caught as a real
    [IMAGE] mismatch, exactly like any other component's row."""
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    rows = [csv_row("OMC / Notify", "notifynl-omc-nodep", alias="omc", image_basename="notifynl-omc",
                     target_app="1.17.20", target_helm="0.14.1")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(OMC_BLOCK))
    assert any("[IMAGE]" in m and "target 1.17.20 != values.yaml 1.17.19" in m for m in findings["mismatches"])


def test_compare_omc_image_source_matches_via_ordinary_basename_path(vrt):
    """The baseline/source-side sibling (check_images_source) — omc's
    row round-trips there too, with no special-casing needed."""
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    baseline_deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.0"}]
    rows = [csv_row("OMC / Notify", "notifynl-omc-nodep", alias="omc", image_basename="notifynl-omc",
                     source_app="1.17.19", target_helm="0.14.1")]
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(OMC_BLOCK),
        baseline_deps=baseline_deps, baseline_values={}, baseline_lines=values_lines(OMC_BLOCK))
    assert findings == {}


def test_compare_omc_image_source_mismatch_via_ordinary_basename_path(vrt):
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    baseline_deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.0"}]
    rows = [csv_row("OMC / Notify", "notifynl-omc-nodep", alias="omc", image_basename="notifynl-omc",
                     source_app="1.17.18")]
    omc_baseline_block = (
        "omc:\n"
        "  image:\n"
        "    # repository: docker.io/worthnl/notifynl-omc\n"
        '    tag: "1.17.19"\n'
    )
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(OMC_BLOCK),
        baseline_deps=baseline_deps, baseline_values={}, baseline_lines=values_lines(omc_baseline_block))
    assert any("[IMAGE-SOURCE]" in m and "source 1.17.18 != baseline values.yaml 1.17.19" in m
               for m in findings["mismatches"])


def test_compare_omc_still_catches_genuinely_untracked_sibling_basename(vrt):
    """Negative case: a DIFFERENT, genuinely-untracked basename under
    the same component's own scope must still be reported as missing —
    unaffected by omc's own row now having a real, non-blank
    image_basename."""
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    rows = [csv_row("OMC / Notify", "notifynl-omc-nodep", alias="omc", image_basename="notifynl-omc",
                     target_app="1.17.19", target_helm="0.14.1")]
    omc_block_with_sidecar = OMC_BLOCK + (
        "  sidecar:\n"
        "    image:\n"
        "      repository: example/some-other-image\n"
        f'      tag: "2.0.0@sha256:{"a" * 64}"\n'
    )

    findings, _ = vrt.compare(rows, deps, {}, values_lines(omc_block_with_sidecar))
    assert any("'some-other-image' is pinned in values.yaml but not tracked" in m
               for m in findings["missing_from_release_table"])


# --- print_report(): output is sorted per category ---

def test_print_report_sorts_findings_within_each_section(vrt, capsys):
    findings = {
        "mismatches": [
            "[IMAGE] Zulu (zulu): release-table target 1 != values.yaml 2",
            "[CHART] Alpha (alpha): release-table target 1 != Chart.yaml 2",
        ],
    }
    vrt.print_report(findings, [])
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("  [")]
    assert lines == [
        "  [CHART] Alpha (alpha): release-table target 1 != Chart.yaml 2",
        "  [IMAGE] Zulu (zulu): release-table target 1 != values.yaml 2",
    ]


def test_print_report_sorts_unresolved_rows_by_name(vrt, capsys):
    unresolved = [csv_row("Zulu", "UNKNOWN"), csv_row("Alpha", ""), csv_row("Mike", "UNKNOWN")]
    vrt.print_report({}, unresolved)
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("- '")]
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
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.297\n"
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(ZAC_BLOCK, encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(csv_row("x", "y").keys()))
        writer.writeheader()
        writer.writerow(csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac",
                                 image_basename="zaakafhandelcomponent", target_app="5.4.3", target_helm="1.0.297"))

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
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.298\n"
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(ZAC_BLOCK, encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(csv_row("x", "y").keys()))
        writer.writeheader()
        writer.writerow(csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac",
                                 image_basename="zaakafhandelcomponent", target_app="5.4.3", target_helm="1.0.297"))

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
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     source_app="5.0.2", source_helm="1.0.297", target_app="9.9.9", target_helm="1.0.297")]

    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(ZAC_BLOCK), baseline_deps=baseline_deps, baseline_values={},
        baseline_lines=values_lines(ZAC_BASELINE_BLOCK), baseline_only=True)
    assert findings == {}

    findings_normal, _ = vrt.compare(
        rows, deps, {}, values_lines(ZAC_BLOCK), baseline_deps=baseline_deps, baseline_values={},
        baseline_lines=values_lines(ZAC_BASELINE_BLOCK))
    assert any("[IMAGE]" in m and "target 9.9.9" in m for m in findings_normal["mismatches"])
    assert any("[CHART]" in m and "target 1.0.297 != Chart.yaml 1.0.298" in m for m in findings_normal["mismatches"])


def test_compare_chart_version_source_blank_but_justified_no_finding(vrt):
    """A blank source_version_helm IS justified here: the dependency
    genuinely didn't exist at the release_table baseline yet -- must stay
    silent under --baseline-only too, not just by default."""
    deps = [{"name": "newthing", "alias": "", "version": "1.0.0"}]
    rows = [csv_row("New Thing", "newthing", target_helm="1.0.0")]  # source_helm blank
    findings, _ = vrt.compare(
        rows, deps, {}, [], baseline_deps=[], baseline_values={}, baseline_lines=[], baseline_only=True)
    assert findings == {}


def test_compare_chart_version_source_blank_but_unjustified_reports_presence_finding(vrt):
    """The dependency DID already exist at the release_table baseline --
    the blank source_version_helm was never justified, only ever
    checked under --baseline-only (strict_presence)."""
    deps = [{"name": "existingthing", "alias": "", "version": "1.1.0"}]
    baseline_deps = [{"name": "existingthing", "alias": "", "version": "1.0.0"}]
    rows = [csv_row("Existing Thing", "existingthing", target_helm="1.1.0")]  # source_helm blank
    findings, _ = vrt.compare(
        rows, deps, {}, [], baseline_deps=baseline_deps, baseline_values={}, baseline_lines=[], baseline_only=True)
    assert any("[CHART-SOURCE-PRESENCE]" in m and "already existed at the release_table baseline (version 1.0.0)" in m
               for m in findings["mismatches"])


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
        csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                 target_app="5.4.3", target_helm="1.0.297"),  # primary row, source_helm blank too
        {**csv_row("Gotenberg", "zaakafhandelcomponent", alias="zac", image_basename="gotenberg"),
         "section": "Technische"},
        {**csv_row("Solr", "zaakafhandelcomponent", alias="zac", image_basename="solr"), "section": "Technische"},
    ]
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(ZAC_BLOCK), baseline_deps=baseline_deps, baseline_values={}, baseline_lines=[],
        baseline_only=True)
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
        rows, deps, {}, [], baseline_deps=baseline_deps, baseline_values={}, baseline_lines=[])
    assert findings == {}


def test_compare_image_source_blank_but_justified_no_finding(vrt):
    """The image genuinely wasn't pinned anywhere at the release_table
    baseline (baseline_lines is empty, and the dependency itself didn't
    exist at baseline either, so the subchart-default fallback has
    nothing to resolve against) -- the blank source_version_app is
    justified, silent under --baseline-only too."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_helm="1.0.297")]  # source_app AND source_helm both blank
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(ZAC_BLOCK), baseline_deps=[], baseline_values={}, baseline_lines=[],
        baseline_only=True)
    assert findings == {}


def test_compare_image_source_blank_but_unjustified_reports_presence_finding_scoped_tier(vrt):
    """The image DID already exist at the release_table baseline (found
    via the plain scoped scan, the common tier) -- the blank
    source_version_app was never justified."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     source_helm="1.0.251", target_helm="1.0.297")]  # source_app blank
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(ZAC_BLOCK), baseline_deps=baseline_deps, baseline_values={},
        baseline_lines=values_lines(ZAC_BASELINE_BLOCK), baseline_only=True)
    assert any("[IMAGE-SOURCE-PRESENCE]" in m and "already existed at the release_table baseline (values.yaml 5.0.2)"
               in m for m in findings["mismatches"])


def test_compare_image_source_blank_unjustified_case_silent_by_default(vrt):
    """Same fixture as the scoped-tier presence finding above (plus a
    matching target_app, so the EXISTING target-side "app version never
    recorded" check -- an orthogonal, already-covered gap -- doesn't
    also fire and muddy this assertion), but WITHOUT baseline_only:
    default behavior completely unaffected."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     source_helm="1.0.251", target_app="5.4.3", target_helm="1.0.297")]  # source_app blank
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(ZAC_BLOCK), baseline_deps=baseline_deps, baseline_values={},
        baseline_lines=values_lines(ZAC_BASELINE_BLOCK))
    assert findings == {}


def test_compare_image_source_blank_but_unjustified_reports_presence_finding_subchart_fallback_tier(vrt, monkeypatch):
    """Same real-world gap as test_compare_image_source_falls_back_to_
    vendored_subchart_default, but for the blank-source presence check:
    the image only resolves at baseline via the subchart-default
    fallback tier -- must still be caught, not just the plain scoped
    tier."""
    monkeypatch.setattr(vrt, "primary_image_repositories",
                         lambda chart_dir, dep, values, allow_pull=True: ({"image": "docker.io/clamav/clamav"},
                                                                           None))
    dep = {"name": "clamav", "version": "3.9.0"}
    baseline_dep = {"name": "clamav", "version": "3.7.1"}
    rows = [csv_row("ClamAV", "clamav", image_basename="clamav", source_helm="3.7.1", target_app="1.5.3",
                     target_helm="3.9.0")]  # source_app blank
    findings, _ = vrt.compare(
        rows, [dep], {}, values_lines(CLAMAV_CURRENT_BLOCK), chart_dir="/fake/chart/dir",
        baseline_deps=[baseline_dep], baseline_values=CLAMAV_BASELINE_VALUES,
        baseline_lines=values_lines(CLAMAV_BASELINE_BLOCK), baseline_only=True)
    assert any("[IMAGE-SOURCE-PRESENCE]" in m and "subchart-default values.yaml 1.5.2" in m
               for m in findings["mismatches"])


def test_compare_image_source_blank_stays_silent_when_special_case_has_no_baseline_value(vrt):
    """keycloak's own basename is special-cased (SPECIAL_CASE_BASENAME_
    TAG_PATHS) -- when get_path finds nothing there at the release_table
    baseline, that's "can't verify", never "confirmed absent": the
    strict_presence blank-source check must stay silent, exactly like
    the plain (non-blank-source) compare direction already does for this
    same case."""
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    baseline_deps = [{"name": "keycloak-operator", "alias": "", "version": "1.10.0"}]
    rows = [csv_row("Keycloak", "keycloak-operator", image_basename="keycloak",
                     source_helm="1.10.0", target_app="26.7.3")]  # source_app blank
    findings, _ = vrt.compare(
        rows, deps, keycloak_values(), [], baseline_deps=baseline_deps, baseline_values={}, baseline_lines=[],
        baseline_only=True)
    assert findings == {}


def test_compare_image_source_blank_but_unjustified_reports_presence_finding_special_case(vrt):
    """Mirror image of the above: the special-cased path DOES resolve a
    real value at the release_table baseline -- the blank source was
    never justified."""
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    baseline_deps = [{"name": "keycloak-operator", "alias": "", "version": "1.10.0"}]
    rows = [csv_row("Keycloak", "keycloak-operator", image_basename="keycloak",
                     source_helm="1.10.0", target_app="26.7.3")]  # source_app blank
    findings, _ = vrt.compare(
        rows, deps, keycloak_values(), [], baseline_deps=baseline_deps, baseline_values=keycloak_values(tag="26.7.1"),
        baseline_lines=[], baseline_only=True)
    assert any("[IMAGE-SOURCE-PRESENCE]" in m and "keycloak-operator.keycloak" in m and "26.7.1" in m
               for m in findings["mismatches"])


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
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="curl",
                     source_helm="1.0.251", target_helm="1.0.297")]  # source_app blank
    findings, _ = vrt.compare(
        rows, deps, {}, values_lines(ZAC_BLOCK), baseline_deps=baseline_deps, baseline_values={},
        baseline_lines=values_lines(two_versions_block), baseline_only=True)
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
        writer.writerow(csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac",
                                 target_app="9.9.9", target_helm="1.0.297"))

    monkeypatch.setattr(vrt, "CHART_DIR", chart_dir)
    monkeypatch.setattr(vrt, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(vrt, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", release_table)
    monkeypatch.setattr(vrt, "release_table_baseline", lambda chart_dir: "1.0.0")
    monkeypatch.setattr(
        vrt, "resolve_baseline_chart_state",
        lambda chart_dir, baseline: (
            baseline, [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.290"}], {}, [], None))

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
