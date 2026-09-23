"""End-to-end check_docs_consistency against a small, realistic podiumd-like
chart inside a real (hermetic, temp) git repo — exercises the full baseline
resolution + all the precheck/content-check stages together.

Split from test_docs_consistency_integration.py (pylint too-many-lines): this
file covers the Component versions table/Changes section ordering, the
values-deltas.md section-ordering rules, and the Changes heading app-version
wording checks."""

import subprocess

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


# --- Component versions table / Changes section ordering ---

ORDER_CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: openzaak
    version: 1.14.2
    repository: "@maykinmedia"
  - name: openinwoner
    version: 2.4.0
    repository: "@maykinmedia"
"""

# openzaak's own block comes BEFORE openinwoner's -- this file order is
# the ordering signal values_key_order reads, so the doc is expected to
# list Open Zaak before Open Inwoner too.
ORDER_VALUES_YAML = (
    'openzaak:\n  image:\n    tag: "1.27.4@sha256:aaaa"\nopeninwoner:\n  image:\n    tag: "2.4.2@sha256:bbbb"\n'
)

ZAAK_ROW = "| Open Zaak | 1.27.4 | 1.14.2 | - |"
INWONER_ROW = "| Open Inwoner | 2.4.2 | 2.4.0 | - |"


def order_doc(table_rows, changes_headings):
    table = "\n".join(table_rows)
    changes = "\n\n".join(f"### {h}\n\nDetails.\n" for h in changes_headings)
    return (
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        f"{table}\n\n"
        "## Changes\n\n"
        f"{changes}\n"
    )


@pytest.fixture
def order_chart_dir(tmp_path):
    chart_dir = tmp_path / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    (chart_dir / "docs" / "images").mkdir(parents=True)
    doc_dir.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(ORDER_CHART_YAML)
    (chart_dir / "values.yaml").write_text(ORDER_VALUES_YAML)
    return chart_dir, doc_dir


def test_correctly_ordered_table_and_changes_pass(vp, order_chart_dir):
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump 1.27.4 → 1.27.4", "Open Inwoner bump 2.4.2 → 2.4.2"])
    )
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is True, detail


def test_out_of_order_table_row_is_caught(vp, order_chart_dir, capsys):
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([INWONER_ROW, ZAAK_ROW], ["Open Zaak bump", "Open Inwoner bump"])
    )
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert '"Component versions" table lists "Open Zaak" right after "Open Inwoner"' in out
    assert "should follow values.yaml's own component order" in out


def test_out_of_order_changes_block_is_caught(vp, order_chart_dir, capsys):
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Inwoner bump", "Open Zaak bump"])
    )
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert '"## Changes" section has "### Open Zaak bump" right after "### Open Inwoner bump"' in out
    assert "Changes blocks should follow values.yaml's own component order" in out


def test_unmatched_summary_row_never_flagged_against_real_components(vp, order_chart_dir, capsys):
    """A row that doesn't resolve to any Chart.yaml dependency (e.g. a
    shared-image summary row) sorts after every real component and must
    never itself trigger an ORDERING mismatch — it's now separately
    flagged as a wrong-phrasing mismatch (doesn't match a canonical
    sidecar/shared-image name either — see canonical_sidecar_row_names),
    but that's a different, unrelated finding from what this test is
    about."""
    chart_dir, doc_dir = order_chart_dir
    summary_row = "| nginx-unprivileged (shared sidecar) | 1.31.4 | — | - |"
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW, summary_row], ["Open Zaak bump", "Open Inwoner bump"])
    )
    vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert "own component order" not in capsys.readouterr().out


def test_table_row_with_no_changes_section_is_caught(vp, order_chart_dir, capsys):
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert 'table row "Open Inwoner" has no matching "### ..." section under "## Changes"' in out


def test_changes_section_with_no_table_row_is_caught(vp, order_chart_dir, capsys):
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(order_doc([ZAAK_ROW], ["Open Zaak bump", "Open Inwoner bump"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert '"## Changes" section "### Open Inwoner bump" has no matching row in the "Component versions" table' in out


def test_heading_naming_two_components_is_flagged_and_neither_row_is_credited(vp, order_chart_dir, capsys):
    """A single "### ..." heading naming two components at once (the
    real-world case: "### ECK Operator 3.4.0 → 3.5.0 + ECK Stack
    (kiss-eck) 0.19.0 → 0.20.0") is assessed as a whole, never split on
    "+" or any other separator — a heading either unambiguously names
    ONE component, or it's wrong. Here it names two, so it's reported as
    its own "no matching row" finding (exactly like an orphan heading
    naming zero would be — there's no special "combines" wording), AND
    neither Open Zaak's nor Open Inwoner's own row is credited by it —
    both are independently reported as having no matching section of
    their own, since a heading naming two components never satisfies
    either one's correspondence."""
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump + Open Inwoner bump"])
    )
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert (
        '"## Changes" section "### Open Zaak bump + Open Inwoner bump" has no matching row in the '
        '"Component versions" table' in out
    )
    assert 'table row "Open Zaak" has no matching "### ..." section under "## Changes"' in out
    assert 'table row "Open Inwoner" has no matching "### ..." section under "## Changes"' in out


def test_changes_heading_naming_no_real_component_is_caught_as_no_matching_row(vp, order_chart_dir, capsys):
    """A Changes heading that never actually names a real Chart.yaml
    dependency at all (the real-world case: "### Keycloak app image
    26.6.4 → 26.7.2" — never says "keycloak-operator" or even
    "operator") still has to be reported as having no matching table
    row, the same as a heading naming the wrong component would be —
    resolving to nothing is not itself a pass."""
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump", "Open Inwoner bump", "Unrelated release note"])
    )
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert (
        '"## Changes" section "### Unrelated release note" has no matching row in the "Component versions" table' in out
    )


def test_changes_heading_missing_app_version_is_caught(vp, order_chart_dir, capsys):
    """A "### ..." heading naming a real, resolvable component but never
    showing its app version at all (real case: "### openbao 0.28.4" —
    add_missing_component_rows' own chart-only TODO-stub shape, written
    back when actual_app_version couldn't resolve anything yet) must be
    flagged once that version DOES become resolvable — a stale heading
    like this is never rewritten automatically (fix-doc-consistency
    never touches an EXISTING section's own text), so nothing else would
    ever catch it going stale."""
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump", "Open Inwoner bump 2.4.2 → 2.4.2"])
    )
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert (
        '"## Changes" section "### Open Zaak bump" is missing the primary-image app version '
        'in its own heading — values.yaml shows "1.27.4"' in out
    )
    assert 'section "### Open Inwoner bump 2.4.2 → 2.4.2" is missing the primary-image app version' not in out


NEW_DEP_CHART_YAML_BASELINE = """\
apiVersion: v2
name: podiumd
version: 4.8.5
dependencies:
  - name: zaakafhandelcomponent
    alias: zac
    version: 1.0.297
    repository: "@zac"
"""
NEW_DEP_CHART_YAML_TARGET = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: zaakafhandelcomponent
    alias: zac
    version: 1.0.297
    repository: "@zac"
  - name: openklant
    version: 2.15.0
    repository: "@openklant"
"""
NEW_DEP_UPGRADE_DOC = """\
# Upgrade guide: PodiumD {baseline} → 4.9.0

## Component versions (4.9.0 vs {baseline})

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| ZAC (Zaakafhandelcomponent) | 5.0.2 (unchanged) | 1.0.297 (unchanged) | n/a |
| openklant | 2.15.0 (new) | 2.15.0 (new) | - |

See [`{baseline}-to-4.9.0-values-deltas.md`]({baseline}-to-4.9.0-values-deltas.md).
"""
NEW_DEP_GEMEENTE_DOC = "# Gemeente-specific notes — PodiumD {baseline} → 4.9.0\n\nNone.\n"
NEW_DEP_VALUES_DELTAS_DOC = (
    "# Values deltas — PodiumD {baseline} → 4.9.0\n\n"
    "## openklant newly added (`openklant.image`)\n\n"
    "No gemeente podiumd.yml changes are required for this hop.\n"
)
NEW_DEP_IMAGES_MANIFEST = """\
# Baseline: podiumd {baseline} (test @ 0000000).
#
# Images new or changed in podiumd 4.9.0 vs {baseline}.
#
# Changes:
#   1. openklant 2.15.0.
#
# See docs/_UPGRADE_PATHS/{baseline}-to-4.9.0-upgrade.md for the operator upgrade notes.

# openklant — 2.15.0
- name: openklant/open-klant
  url: openklant/open-klant
  version: "2.15.0"
  digest: "sha256:abc"
"""


def new_dep_values():
    return (
        "zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        '    tag: "5.0.2@sha256:aaaa"\n'
        'openklant:\n  image:\n    repository: openklant/open-klant\n    tag: "2.15.0@sha256:abc"\n'
    )


@pytest.fixture
def new_dependency_chart_repo(tmp_path):
    """ "openklant" doesn't exist at all at the baseline ref — added as a
    brand-new Chart.yaml dependency in this release. Its doc row's
    source (baseline) version can never be verified against a baseline
    that has no such dependency at all — this is the exact real-world
    gap fix-doc-consistency's own fix_component_version_table already
    tracks as "unresolved" (left uncorrected, and now written as
    "2.15.0 (new)" rather than left blank), which check_docs_consistency
    used to silently treat as clean, since it never had anything to
    compare the row's claimed source version against. Otherwise a fully
    clean, complete doc set — nothing else here should surface any
    mismatch, so the row-source warning's own severity (warning, not
    failure) can be checked in isolation."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    images_dir = chart_dir / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(NEW_DEP_CHART_YAML_BASELINE)
    (chart_dir / "values.yaml").write_text(
        'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.0.2@sha256:aaaa"\n'
    )
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(NEW_DEP_CHART_YAML_TARGET)
    (chart_dir / "values.yaml").write_text(new_dep_values())
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(NEW_DEP_UPGRADE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(NEW_DEP_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(NEW_DEP_VALUES_DELTAS_DOC.format(baseline="4.8.5"))
    (images_dir / "images-4.9.0.yaml").write_text(NEW_DEP_IMAGES_MANIFEST.format(baseline="4.8.5"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "add openklant, a brand-new dependency", cwd=repo_root)

    return chart_dir


def test_new_dependency_unresolvable_baseline_row_is_a_warning_not_a_failure(vp, new_dependency_chart_repo, capsys):
    """A doc row for a component that didn't exist at the baseline ref at
    all must be surfaced (never silently treated as clean, since its
    source cells were never actually compared against anything) — but
    only as a warning, not a mismatch: there's nothing wrong with the
    doc here, a brand-new component simply has no baseline to compare
    against, same reason fix-doc-consistency's own fix_component_
    version_table doesn't treat it as an error either (writes "(new)"
    cells for it instead of reporting it for manual review)."""
    ok, detail = vp.check_docs_consistency(new_dependency_chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is True, detail
    assert (
        'WARNING: 4.8.5-to-4.9.0-upgrade.md: doc row "openklant" source version could not be verified against'
    ) in out
    assert 'openklant" target app' not in out  # target side still resolves fine, no false mismatch there


def test_plus_in_heading_not_naming_two_real_components_still_resolves_normally(vp, order_chart_dir, capsys):
    """A literal "+" in a heading isn't itself the signal — assessment
    never splits on it at all. Here only "Open Zaak" names a real
    component; the rest of the text ("+ misc cleanup") is plain prose
    that names nothing, so the heading as a whole still resolves to
    exactly one identity and must pass normally, same as any other
    single-component heading."""
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc(
            [ZAAK_ROW, INWONER_ROW],
            ["Open Zaak bump 1.27.4 → 1.27.4 + misc cleanup", "Open Inwoner bump 2.4.2 → 2.4.2"],
        )
    )
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is True, detail
    out = capsys.readouterr().out
    assert "has no matching" not in out


# --- values-deltas.md: "## ..." sections must follow values.yaml's own order ---

TWO_DEP_CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: zaakafhandelcomponent
    alias: zac
    version: 1.0.297
    repository: "@zac"
  - name: openformulieren
    version: 1.12.0
    repository: "@openformulieren"
"""


def two_dep_values(zac_app, openformulieren_app, *, with_schema_changes=False):
    zac_extra = "  newFeature:\n    enabled: true\n" if with_schema_changes else ""
    openformulieren_extra = "  clamavConfigJob:\n    enabled: true\n" if with_schema_changes else ""
    return (
        f"zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        f'    tag: "{zac_app}@sha256:abc"\n{zac_extra}'
        f"openformulieren:\n  image:\n    repository: openformulieren/open-forms\n"
        f'    tag: "{openformulieren_app}@sha256:def"\n{openformulieren_extra}'
    )


@pytest.fixture
def two_dep_chart_repo(tmp_path):
    """zac and openformulieren both already exist at the baseline ref
    (podiumd-4.8.5) and both bump their app version AND add a real
    values.yaml schema key at HEAD — values.yaml lists zac first,
    openformulieren second, so that's the order their own values-
    deltas.md sections must follow. The schema change matters here (not
    just the version bump): a pure version-only bump gets no values-
    deltas.md section at all (see lib.component_docs.sync_values_delta_
    sections' own docstring), so these tests need real "- Key ..."
    content to exercise section ordering meaningfully."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    images_dir = chart_dir / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(TWO_DEP_CHART_YAML)
    (chart_dir / "values.yaml").write_text(two_dep_values("5.0.2", "3.4.10"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "values.yaml").write_text(two_dep_values("5.4.3", "3.5.6", with_schema_changes=True))
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | n/a |\n"
        "| openformulieren | 3.4.10 → 3.5.6 | 1.12.0 (unchanged) | n/a |\n\n"
        "See [`4.8.5-to-4.9.0-values-deltas.md`](4.8.5-to-4.9.0-values-deltas.md).\n"
    )
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(
        "# Gemeente-specific notes — PodiumD 4.8.5 → 4.9.0\n\nNone.\n"
    )
    # sections deliberately in the WRONG order: openformulieren (values.yaml's
    # SECOND key) comes before zac (values.yaml's FIRST key)
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
        "## openformulieren 3.4.10 → 3.5.6 (chart 1.12.0, unchanged)\n\n"
        "- Key `openformulieren.clamavConfigJob` was added.\n\n"
        "## ZAC 5.0.2 → 5.4.3 (chart 1.0.297, unchanged)\n\n"
        "- Key `zac.newFeature` was added.\n"
    )
    (images_dir / "images-4.9.0.yaml").write_text(
        "# Baseline: podiumd 4.8.5 (test @ 0000000).\n#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n#\n"
        "# Changes:\n"
        "#   1. ZAC (Zaakafhandelcomponent) 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).\n"
        "#   2. openformulieren 3.4.10 -> 3.5.6 (chart 1.12.0, unchanged).\n#\n"
        "# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.\n\n"
        "# ZAC — 5.0.2 -> 5.4.3\n"
        "- name: zac\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.4.3"\n'
        '  digest: "sha256:abc"\n\n'
        "# openformulieren — 3.4.10 -> 3.5.6\n"
        "- name: openformulieren\n"
        "  url: openformulieren/open-forms\n"
        '  version: "3.5.6"\n'
        '  digest: "sha256:def"\n'
    )
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "bump both zac and openformulieren", cwd=repo_root)

    return chart_dir


def test_values_deltas_sections_out_of_order_is_caught(vp, two_dep_chart_repo, capsys):
    ok, _detail = vp.check_docs_consistency(two_dep_chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    out = capsys.readouterr().out
    assert (
        '4.8.5-to-4.9.0-values-deltas.md: "## ZAC' in out
        and 'section comes right after "## openformulieren' in out
        and "sections should follow values.yaml's own component order" in out
    )


def test_values_deltas_sections_correctly_ordered_passes(vp, two_dep_chart_repo):
    doc = two_dep_chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
        "## ZAC 5.0.2 → 5.4.3 (chart 1.0.297, unchanged)\n\n"
        "- Key `zac.newFeature` was added.\n\n"
        "## openformulieren 3.4.10 → 3.5.6 (chart 1.12.0, unchanged)\n\n"
        "- Key `openformulieren.clamavConfigJob` was added.\n"
    )
    ok, detail = vp.check_docs_consistency(two_dep_chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is True, detail


# --- Changes heading app-version wording vs. its own row (regression:
# a heading can show the CORRECT current version yet the WRONG
# transition wording, e.g. "(unchanged)" for a component that's really
# "(new)" to this doc — real case: openbao's own Changes heading said
# "(unchanged)" while its table row correctly said "(new)", because its
# baseline app version was only resolvable via a vendored-.tgz fallback
# the OLD code never attempted for the baseline side) ---


def test_changes_heading_wrong_transition_wording_is_caught(vp, chart_repo, capsys):
    """zac really changed 5.0.2 -> 5.4.3 (see chart_repo's own docstring),
    but its own Changes heading wrongly claims "(unchanged)" — the table
    row itself is untouched/correct, only the heading's own wording is
    stale/wrong. changes_heading_has_app_version alone would pass this
    (SOME version marker is shown) — this needs the wording ITSELF
    checked against the real baseline -> target transition."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | n/a |\n\n"
        "## Changes\n\n"
        "### ZAC (Zaakafhandelcomponent) 5.4.3 (unchanged) (chart 1.0.297, unchanged)\n\n"
        "blah\n"
    )
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert (
        '"## Changes" section "### ZAC (Zaakafhandelcomponent) 5.4.3 (unchanged) (chart 1.0.297, '
        'unchanged)" shows the wrong app-version transition in its own heading — expected '
        "\"5.0.2 → 5.4.3\" (values.yaml/podiumd-4.8.5 show '5.0.2' -> '5.4.3')"
    ) in out


def test_changes_heading_correct_transition_wording_passes(vp, chart_repo):
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | n/a |\n\n"
        "## Changes\n\n"
        "### ZAC (Zaakafhandelcomponent) 5.0.2 → 5.4.3 (chart 1.0.297, unchanged)\n\n"
        "blah\n"
    )
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is True, detail
    assert ok is True, detail
