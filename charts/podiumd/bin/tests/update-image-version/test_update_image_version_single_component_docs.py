"""update-image-version's main() doc-update path for a basename that
resolves to exactly one component — the full lib.component_docs
treatment (upgrade.md table row + Changes section, images-manifest
entry). No network needed: lib.registry.registry_tag_exists is
monkeypatched via the uiv module's own imported binding
(update_image_version lives in lib.image.version, which resolves
`registry_tag_exists` via ITS OWN globals — see lib.image.version's
import — so tests patch that module directly, same as
tests/lib/test_image_version.py does)."""

import io
import subprocess
import tarfile

import yaml


def write_values(tmp_path, text):
    path = tmp_path / "values.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def write_chart_yaml(chart_dir, deps):
    """`deps`: [(name, alias_or_none), ...]."""
    lines = ["apiVersion: v2", "name: podiumd", "version: 1.0.0", "dependencies:"]
    for name, alias in deps:
        lines.append(f"  - name: {name}")
        if alias:
            lines.append(f"    alias: {alias}")
        lines += ["    version: 1.0.0", '    repository: "@x"']
    (chart_dir / "Chart.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_doc(doc_dir, name, text):
    (doc_dir / name).write_text(text, encoding="utf-8")


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def commit_baseline_tag(tmp_path, baseline):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", f"podiumd-{baseline}", cwd=tmp_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text(f'upgrade_docs: "{baseline}"\n', encoding="utf-8")


def test_main_single_component_updates_upgrade_doc_table_and_changes(uiv, tmp_path, monkeypatch, capsys):
    """A basename that resolves to exactly one component (here via the
    "openklant" alias) gets the SAME full-fidelity treatment
    update-component-version itself uses -- a real (unchanged) Helm
    chart version shown, not "-"."""
    write_chart_yaml(tmp_path, [("openklant", None)])
    values_path = write_values(
        tmp_path,
        (f'openklant:\n  image:\n    repository: maykinmedia/open-klant\n    tag: "2.15.0@sha256:{"a" * 64}"\n'),
    )
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "0.9.0"\n', encoding="utf-8")
    write_doc(
        uiv.DOC_DIR,
        "0.9.0-to-1.0.0-upgrade.md",
        "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
        "## Component versions (1.0.0 vs 0.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n",
    )
    write_doc(
        uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md", "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n"
    )
    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "openklant", "open-klant", "2.15.1"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| openklant | 2.15.0 → 2.15.1 | 1.0.0 (unchanged) | - |" in upgrade
    assert "### openklant 2.15.0 → 2.15.1 (chart 1.0.0, unchanged)" in upgrade

    # No git repo at all here, so the baseline (and any schema diff) can
    # never be resolved — no values-deltas.md section gets written (see
    # sync_values_delta_sections' own docstring).
    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## openklant" not in deltas

    out = capsys.readouterr().out
    assert "added table row" in out
    assert "(re)wrote '### openklant ...' Changes section" in out


def _make_vendored_tgz(charts_dir, name, version, chart_yaml):
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    with tarfile.open(tgz_path, "w:gz") as tar:
        data = yaml.safe_dump(chart_yaml).encode("utf-8")
        info = tarfile.TarInfo(name=f"{name}/Chart.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return tgz_path


def test_main_resolves_baseline_app_version_via_vendored_subchart_when_chart_unchanged(uiv, tmp_path, monkeypatch):
    """Regression test (real bug, real doc): openbao's own "server.image.
    tag" is deliberately left blank at the baseline (see lib.chart.
    COMPONENT_IMAGE_PATHS["openbao"]'s own comment) — its real baseline
    app version only resolves via the vendored-.tgz subchart_app_version
    fallback, which the raw baseline_values.yaml tag read used to never
    attempt. lib.image.version.update_image_version can only ever bump
    an ALREADY digest-pinned tag (scan_digest_pins never matches a blank
    one), so the real sequence is: baseline ships blank (subchart-only
    v2.5.0), values.yaml gets hand-pinned to v2.5.5 by some OTHER means
    (exactly the real openbao doc's own actual history this session),
    then THIS run bumps v2.5.5 -> v2.6.0 via update-image-version. A
    basename bump never touches Chart.yaml (old_chart == new_chart
    always here — see update_docs_single_component's own docstring), so
    the SAME vendored .tgz backs both baseline and target — old_app
    must resolve to the real "v2.5.0" baked into that file, not None,
    collapsing to a real "v2.5.0 -> v2.6.0" transition (never showing
    the intermediate v2.5.5 hop, same as any other repeated-bump case)
    instead of a false "(new)" one purely because of this resolution
    gap (the same fix already made in lib.component_docs.resolve_
    component_own_version_change for fix-doc-consistency's own doc-sync
    path — this is the same gap in update-image-version's own doc-
    writing path)."""
    (tmp_path / "Chart.yaml").write_text(
        "apiVersion: v2\n"
        "name: podiumd\n"
        "version: 1.0.0\n"
        "dependencies:\n"
        "  - name: openbao\n"
        "    version: 0.28.4\n"
        '    repository: "@openbao"\n',
        encoding="utf-8",
    )
    values_path = write_values(
        tmp_path, ('openbao:\n  server:\n    image:\n      repository: quay.io/openbao/openbao\n      tag: ""\n')
    )
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    _make_vendored_tgz(
        tmp_path / "charts", "openbao", "0.28.4", {"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.0"}
    )
    commit_baseline_tag(tmp_path, "0.9.0")  # baseline: chart 0.28.4, app version blank (subchart-only v2.5.0)

    # Simulate "hand-pinned to v2.5.5 by some other means, chart untouched" --
    # real openbao's own actual history this session.
    write_values(
        tmp_path,
        (
            "openbao:\n"
            "  server:\n"
            "    image:\n"
            "      repository: quay.io/openbao/openbao\n"
            f'      tag: "v2.5.5@sha256:{"a" * 64}"\n'
        ),
    )

    write_doc(
        uiv.DOC_DIR,
        "0.9.0-to-1.0.0-upgrade.md",
        "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
        "## Component versions (1.0.0 vs 0.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n",
    )
    write_doc(
        uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md", "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n"
    )
    write_doc(
        uiv.IMAGES_DIR,
        "images-1.0.0.yaml",
        "# Baseline: podiumd 0.9.0.\n#\n# Zero changes:\n#\n\n"
        "- name: openbao\n"
        "  url: quay.io/openbao/openbao\n"
        '  version: "v2.5.5"\n'
        f'  digest: "sha256:{"a" * 64}"\n',
    )

    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "openbao", "openbao", "v2.6.0"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "None" not in upgrade
    assert "(new)" not in upgrade
    assert "| openbao | v2.5.0 → v2.6.0 | 0.28.4 (unchanged) | - |" in upgrade
    assert "### openbao v2.5.0 → v2.6.0 (chart 0.28.4, unchanged)" in upgrade

    manifest = (uiv.IMAGES_DIR / "images-1.0.0.yaml").read_text(encoding="utf-8")
    assert "None" not in manifest
    assert "1. openbao v2.5.0 -> v2.6.0 (chart 0.28.4, unchanged)." in manifest


def test_main_renders_new_for_both_app_and_chart_version_when_never_baselined(uiv, tmp_path, monkeypatch):
    """Regression test (real bug, real doc, mi-data): mi-data's own chart
    version (1.0.0 -> 1.1.0) AND app version (blank -> 2.71.0) both moved
    WITHIN this same release cycle, via an earlier separate run, before
    ever being genuinely captured in any prior baseline doc -- values.yaml
    had no "mi.image" override at all at the true baseline, just an
    "enabled: false" stub. A later run bumping mi's own image tag further
    (2.71.0 -> 2.90.0) must show BOTH its Helm-chart cell AND its Changes-
    heading app version as "(new)" -- not a "1.0.0 -> 1.1.0" /
    "2.71.0 -> 2.90.0" transition (implying a real prior baseline value
    existed and moved, which no doc thread across this whole cycle ever
    recorded), and not "(unchanged)" either. See update_docs_single_
    component's own old_chart_str comment for why old_chart is gated by
    the SAME baseline_app-is-None signal as old_app, not by a raw
    baseline_dep["version"] git-history read (which would give the
    real-per-git-history-but-wrong-to-show "1.0.0")."""
    (tmp_path / "Chart.yaml").write_text(
        "apiVersion: v2\n"
        "name: podiumd\n"
        "version: 4.9.1\n"
        "dependencies:\n"
        "  - name: mi-data\n"
        "    alias: mi\n"
        "    version: 1.0.0\n"
        '    repository: "@mi"\n',
        encoding="utf-8",
    )
    write_values(tmp_path, "mi:\n  enabled: false\n")
    commit_baseline_tag(tmp_path, "4.9.0")  # baseline: chart 1.0.0, no image override at all

    # Simulate the earlier, separate in-cycle bump that first introduced
    # mi's own image override -- chart AND app version both moved, never
    # captured in any prior doc.
    (tmp_path / "Chart.yaml").write_text(
        "apiVersion: v2\n"
        "name: podiumd\n"
        "version: 4.9.1\n"
        "dependencies:\n"
        "  - name: mi-data\n"
        "    alias: mi\n"
        "    version: 1.1.0\n"
        '    repository: "@mi"\n',
        encoding="utf-8",
    )
    write_values(
        tmp_path,
        (f'mi:\n  enabled: false\n  image:\n    repository: example/mi-data\n    tag: "2.71.0@sha256:{"a" * 64}"\n'),
    )

    write_doc(
        uiv.DOC_DIR,
        "4.9.0-to-4.9.1-upgrade.md",
        "# Upgrade guide: PodiumD 4.9.0 → 4.9.1\n\n"
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n",
    )
    write_doc(
        uiv.DOC_DIR, "4.9.0-to-4.9.1-values-deltas.md", "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\nNo changes.\n"
    )

    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "mi", "mi-data", "2.90.0"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "4.9.0-to-4.9.1-upgrade.md").read_text(encoding="utf-8")
    assert "None" not in upgrade
    assert "1.0.0" not in upgrade
    assert "2.71.0" not in upgrade
    assert "| mi | 2.90.0 (new) | 1.1.0 (new) | - |" in upgrade
    assert "### mi 2.90.0 (new) (chart 1.1.0, new)" in upgrade


def test_main_shows_real_baseline_chart_transition_when_genuinely_tracked(uiv, tmp_path, monkeypatch):
    """Counterpart to the mi-data test above: a component that WAS
    genuinely tracked at the true baseline (a real app version resolves
    there) gets its real baseline Chart.yaml dependency version as
    old_chart, same as ever -- only a component with NO real baseline
    app version at all (see the mi-data test) gets old_chart forced to
    None too. Here zac's own chart version genuinely moved (1.0.296 ->
    1.0.297) since the baseline -- must still render that real
    transition, not "(new)"."""
    (tmp_path / "Chart.yaml").write_text(
        "apiVersion: v2\n"
        "name: podiumd\n"
        "version: 4.9.1\n"
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    alias: zac\n"
        "    version: 1.0.296\n"
        '    repository: "@zac"\n',
        encoding="utf-8",
    )
    write_values(
        tmp_path,
        (f'zac:\n  image:\n    repository: infonl/zaakafhandelcomponent\n    tag: "5.0.2@sha256:{"a" * 64}"\n'),
    )
    commit_baseline_tag(tmp_path, "4.9.0")  # baseline: chart 1.0.296, app 5.0.2

    # Chart bumped (unrelated to this basename bump) since baseline.
    (tmp_path / "Chart.yaml").write_text(
        "apiVersion: v2\n"
        "name: podiumd\n"
        "version: 4.9.1\n"
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    alias: zac\n"
        "    version: 1.0.297\n"
        '    repository: "@zac"\n',
        encoding="utf-8",
    )
    write_values(
        tmp_path,
        (f'zac:\n  image:\n    repository: infonl/zaakafhandelcomponent\n    tag: "5.0.2@sha256:{"a" * 64}"\n'),
    )

    write_doc(
        uiv.DOC_DIR,
        "4.9.0-to-4.9.1-upgrade.md",
        "# Upgrade guide: PodiumD 4.9.0 → 4.9.1\n\n"
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n",
    )
    write_doc(
        uiv.DOC_DIR, "4.9.0-to-4.9.1-values-deltas.md", "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\nNo changes.\n"
    )

    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "zac", "zaakafhandelcomponent", "5.4.3"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "4.9.0-to-4.9.1-upgrade.md").read_text(encoding="utf-8")
    assert "None" not in upgrade
    assert "(new)" not in upgrade
    assert "| zac | 5.0.2 → 5.4.3 | 1.0.296 → 1.0.297 | - |" in upgrade
    assert "### zac 5.0.2 → 5.4.3 (chart 1.0.296 → 1.0.297)" in upgrade
