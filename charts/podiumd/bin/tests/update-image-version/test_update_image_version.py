"""update-image-version's main() — argument parsing and end-to-end
wiring into lib.image_version.update_image_version. No network needed:
lib.registry.registry_tag_exists is monkeypatched via the uiv module's own
imported binding (update_image_version lives in lib.image_version, which
resolves `registry_tag_exists` via ITS OWN globals — see
lib.image_version's import — so tests patch that module directly, same as
tests/lib/test_image_version.py does)."""
import io
import subprocess
import tarfile

import pytest
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


def test_help_flag_prints_docstring_and_exits_zero(uiv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["update-image-version", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        uiv.main()
    assert exc_info.value.code == 0
    assert "Bump every values.yaml image tag pin" in capsys.readouterr().out


def test_wrong_arg_count_prints_docstring_and_exits_one(uiv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["update-image-version", "only-one-arg"])
    with pytest.raises(SystemExit) as exc_info:
        uiv.main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


def test_main_updates_matching_pin(uiv, tmp_path, monkeypatch, capsys):
    values_path = write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "pabc", "pabc-api", "1.1.2"])

    uiv.main()

    out = capsys.readouterr().out
    assert "values.yaml:4" in out
    assert f'1.1.2@sha256:{"b" * 64}' in values_path.read_text(encoding="utf-8")


def test_main_reports_noop_when_already_at_target(uiv, tmp_path, monkeypatch, capsys):
    values_path = write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.2@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["update-image-version", "pabc", "pabc-api", "1.1.2"])

    uiv.main()

    assert "nothing to do" in capsys.readouterr().out


def test_main_resolves_given_component_key_and_basename(uiv, tmp_path, monkeypatch, capsys):
    """<key> "openklant" scopes the search to that component's own
    values.yaml subtree, where <basename> "open-klant" is pinned."""
    write_chart_yaml(tmp_path, [("openklant", None)])
    values_path = write_values(tmp_path, (
        "openklant:\n"
        "  image:\n"
        "    repository: maykinmedia/open-klant\n"
        f'    tag: "2.15.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "openklant", "open-klant", "2.15.1"])

    uiv.main()

    assert f'2.15.1@sha256:{"b" * 64}' in values_path.read_text(encoding="utf-8")


def test_main_raises_when_basename_not_unique_under_key(uiv, tmp_path, monkeypatch, capsys):
    """Two DISTINCT repositories sharing a basename under the same <key>
    can't be identified uniquely (see lib.image_version.
    resolve_scoped_matches) -- an error, never a guess."""
    write_chart_yaml(tmp_path, [("zaakafhandelcomponent", "zac")])
    values_path = write_values(tmp_path, (
        "zac:\n"
        "  image:\n"
        f'    repository: org-one/curl\n    tag: "1.0.0@sha256:{"a" * 64}"\n'
        "  sidecar:\n"
        "    image:\n"
        f'      repository: org-two/curl\n      tag: "1.0.0@sha256:{"b" * 64}"\n'
    ))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["update-image-version", "zac", "curl", "2.0.0"])

    with pytest.raises(SystemExit, match="'curl' under 'zac' is not unique"):
        uiv.main()


def test_main_exits_on_no_match(uiv, tmp_path, monkeypatch, capsys):
    values_path = write_values(tmp_path, "a:\n  image:\n    repository: org/repo\n    tag: \"1.0.0@sha256:" + "a" * 64 + "\"\n")
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["update-image-version", "a", "curl", "8.22.0"])

    with pytest.raises(SystemExit):
        uiv.main()


# --- doc updates: single component affected -> full lib.component_docs treatment ---

def write_doc(doc_dir, name, text):
    (doc_dir / name).write_text(text, encoding="utf-8")


def test_main_single_component_updates_upgrade_doc_table_and_changes(uiv, tmp_path, monkeypatch, capsys):
    """A basename that resolves to exactly one component (here via the
    "openklant" alias) gets the SAME full-fidelity treatment
    update-component-version itself uses -- a real (unchanged) Helm
    chart version shown, not "-"."""
    write_chart_yaml(tmp_path, [("openklant", None)])
    values_path = write_values(tmp_path, (
        "openklant:\n"
        "  image:\n"
        "    repository: maykinmedia/open-klant\n"
        f'    tag: "2.15.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "0.9.0"\n', encoding="utf-8")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-upgrade.md",
              "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
              "## Component versions (1.0.0 vs 0.9.0)\n\n"
              "| Component | App version | Helm chart | Notes |\n"
              "| --- | --- | --- | --- |\n\n"
              "## Changes\n")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md",
              "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n")
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
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


def test_main_resolves_baseline_app_version_via_vendored_subchart_when_chart_unchanged(
        uiv, tmp_path, monkeypatch):
    """Regression test (real bug, real doc): openbao's own "server.image.
    tag" is deliberately left blank at the baseline (see lib.chart.
    COMPONENT_IMAGE_PATHS["openbao"]'s own comment) — its real baseline
    app version only resolves via the vendored-.tgz subchart_app_version
    fallback, which the raw baseline_values.yaml tag read used to never
    attempt. lib.image_version.update_image_version can only ever bump
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
        "    repository: \"@openbao\"\n",
        encoding="utf-8",
    )
    values_path = write_values(tmp_path, (
        "openbao:\n"
        "  server:\n"
        "    image:\n"
        "      repository: quay.io/openbao/openbao\n"
        "      tag: \"\"\n"
    ))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    _make_vendored_tgz(tmp_path / "charts", "openbao", "0.28.4",
                        {"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.0"})
    commit_baseline_tag(tmp_path, "0.9.0")  # baseline: chart 0.28.4, app version blank (subchart-only v2.5.0)

    # Simulate "hand-pinned to v2.5.5 by some other means, chart untouched" --
    # real openbao's own actual history this session.
    write_values(tmp_path, (
        "openbao:\n"
        "  server:\n"
        "    image:\n"
        "      repository: quay.io/openbao/openbao\n"
        f'      tag: "v2.5.5@sha256:{"a" * 64}"\n'
    ))

    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-upgrade.md",
              "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
              "## Component versions (1.0.0 vs 0.9.0)\n\n"
              "| Component | App version | Helm chart | Notes |\n"
              "| --- | --- | --- | --- |\n\n"
              "## Changes\n")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md",
              "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n")
    write_doc(uiv.IMAGES_DIR, "images-1.0.0.yaml",
              "# Baseline: podiumd 0.9.0.\n#\n# Zero changes:\n#\n\n"
              "- name: openbao\n"
              "  url: quay.io/openbao/openbao\n"
              '  version: "v2.5.5"\n'
              f'  digest: "sha256:{"a" * 64}"\n')

    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
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


# --- doc updates: a sidecar bump (not the dependency's own primary image) ---
# gets a "<values_key> (<basename>)" disambiguated row/section name, since
# "<values_key>" alone would collide with the dependency's own primary-image
# row (or another sidecar's own row) -- see update-image-version's own
# update_docs_single_component docstring.

REDIS_VALUES_TMPL = (
    "redis-operator:\n"
    "  redis-ha:\n"
    "    image:\n"
    "      repository: quay.io/opstree/redis\n"
    '      tag: "{version}@sha256:{digest}"\n'
)


def test_main_sidecar_bump_gets_disambiguated_row_name(uiv, tmp_path, monkeypatch, capsys):
    """redis-ha's own image lives under "redis-operator" but isn't that
    dependency's own registered primary image (image_paths_for defaults
    to just "image", which doesn't exist here) -- the row/section must
    be named "redis-operator - redis", not bare "redis-operator"."""
    write_chart_yaml(tmp_path, [("redis-operator", None)])
    values_path = write_values(tmp_path, REDIS_VALUES_TMPL.format(version="8.6.2", digest="a" * 64))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "0.9.0"\n', encoding="utf-8")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-upgrade.md",
              "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
              "## Component versions (1.0.0 vs 0.9.0)\n\n"
              "| Component | App version | Helm chart | Notes |\n"
              "| --- | --- | --- | --- |\n\n"
              "## Changes\n")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md",
              "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n")
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "redis-operator", "redis", "8.6.6"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| redis-operator - redis | 8.6.2 → 8.6.6 | 1.0.0 (unchanged) | - |" in upgrade
    assert "### redis-operator - redis 8.6.2 → 8.6.6" in upgrade

    # No git repo at all here, so the baseline (and any schema diff) can
    # never be resolved — no values-deltas.md section gets written.
    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## redis-operator - redis" not in deltas

    out = capsys.readouterr().out
    assert "(re)wrote '### redis-operator - redis ...' Changes section" in out


def test_main_sidecar_bump_does_not_corrupt_dependencys_own_row(uiv, tmp_path, monkeypatch):
    """A pre-existing "redis-operator" row (the dependency's own,
    unrelated bump) must be left completely untouched by a redis-ha
    sidecar bump -- before the disambiguated name, find_component_row
    would have matched and overwritten THIS row instead of inserting a
    new one, since both normalize to "redisoperator"."""
    write_chart_yaml(tmp_path, [("redis-operator", None)])
    values_path = write_values(tmp_path, REDIS_VALUES_TMPL.format(version="8.6.2", digest="a" * 64))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "0.9.0"\n', encoding="utf-8")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-upgrade.md",
              "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
              "## Component versions (1.0.0 vs 0.9.0)\n\n"
              "| Component | App version | Helm chart | Notes |\n"
              "| --- | --- | --- | --- |\n"
              "| redis-operator | 0.25.0 → 0.26.0 | 0.25.0 → 0.26.1 | ACR mirror only |\n\n"
              "## Changes\n")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md",
              "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n")
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "redis-operator", "redis", "8.6.6"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| redis-operator | 0.25.0 → 0.26.0 | 0.25.0 → 0.26.1 | ACR mirror only |" in upgrade
    assert "| redis-operator - redis | 8.6.2 → 8.6.6 | 1.0.0 (unchanged) | - |" in upgrade


def test_main_sidecar_reset_to_baseline_uses_raw_values_key(uiv, tmp_path, monkeypatch):
    """Resetting the sidecar bump back to its exact baseline version must
    still correctly detect "nothing left to document" -- reset_to_baseline
    is computed from compute_changed_components' own top-level-key set,
    which never contains the disambiguated "values_key (basename)" form,
    so it must be checked against the raw values_key, not `friendly`."""
    write_chart_yaml(tmp_path, [("redis-operator", None)])
    write_values(tmp_path, REDIS_VALUES_TMPL.format(version="8.6.2", digest="a" * 64))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", tmp_path / "values.yaml")
    commit_baseline_tag(tmp_path, "0.9.0")  # baseline: redis-ha's redis image at 8.6.2

    write_values(tmp_path, REDIS_VALUES_TMPL.format(version="8.6.6", digest="a" * 64))
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-upgrade.md",
              "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
              "## Component versions (1.0.0 vs 0.9.0)\n\n"
              "| Component | App version | Helm chart | Notes |\n"
              "| --- | --- | --- | --- |\n"
              "| redis-operator - redis | 8.6.2 → 8.6.6 | 1.0.0 (unchanged) | - |\n\n"
              "## Changes\n\n"
              "### redis-operator - redis 8.6.2 → 8.6.6\n\nblah\n")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md",
              "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\n"
              "## redis-operator - redis 8.6.2 → 8.6.6 (chart 1.0.0, unchanged) — image tag only\n")

    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "a" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "redis-operator", "redis", "8.6.2"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "redis-operator - redis" not in upgrade

    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "redis-operator - redis" not in deltas


# --- doc updates: multiple components affected -> shared-image (lib.image_docs) treatment ---

def test_main_shared_image_creates_pseudo_component_row_and_changes_block(uiv, tmp_path, monkeypatch, capsys):
    """curl, shared via values.yaml's global.images anchor block and
    aliased into two unrelated components -- gets its own table row
    (Helm chart column "-") and a "### curl ..." Changes block, matching
    the 4.8.1-to-4.8.2-upgrade.md convention -- NOT a row/section for
    either aliasing component. key=MULTIPLE (see lib.image_version.
    MULTIPLE_KEY) is release-table.csv's own convention for this case."""
    write_chart_yaml(tmp_path, [("keycloak-operator", None), ("zac", None)])
    values_path = write_values(tmp_path, (
        "global:\n"
        "  images:\n"
        "    curl: &curlImage\n"
        "      repository: curlimages/curl\n"
        f'      tag: "8.20.0@sha256:{"a" * 64}"\n'
        "keycloak-operator:\n"
        "  jobs:\n"
        "    ensureOperatorSa:\n"
        "      image: *curlImage\n"
        "zac:\n"
        "  global:\n"
        "    curlImage: *curlImage\n"
    ))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "0.9.0"\n', encoding="utf-8")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-upgrade.md",
              "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
              "## Component versions (1.0.0 vs 0.9.0)\n\n"
              "| Component | App version | Helm chart | Notes |\n"
              "| --- | --- | --- | --- |\n\n"
              "## Changes\n")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md",
              "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n")
    write_doc(uiv.IMAGES_DIR, "images-1.0.0.yaml",
              "# Baseline: podiumd 0.9.0.\n#\n# One change:\n#   1. curl 8.20.0 -> 8.20.0.\n#\n\n"
              "# curl — 8.20.0 -> 8.20.0\n"
              "- name: curlimages/curl\n"
              "  url: docker.io/curlimages/curl\n"
              '  version: "8.20.0"\n'
              f'  digest: "sha256:{"a" * 64}"\n')
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "MULTIPLE", "curl", "8.21.0"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| curl | 8.20.0 → 8.21.0 | - | - |" in upgrade
    assert "### curl 8.20.0 → 8.21.0" in upgrade
    assert "`global.images.curl.tag` `8.20.0` → `8.21.0`" in upgrade

    # A shared image's own basename bump never touches any values.yaml
    # SCHEMA — there's nothing for a gemeente to react to, so it gets no
    # values-deltas.md section at all (see update_docs_shared_image's
    # own comment on this).
    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## curl" not in deltas

    manifest = (uiv.IMAGES_DIR / "images-1.0.0.yaml").read_text(encoding="utf-8")
    assert "#   1. curl 8.20.0 -> 8.21.0." in manifest
    assert "# curl — 8.20.0 -> 8.21.0" in manifest
    assert '"8.21.0"' in manifest

    out = capsys.readouterr().out
    assert "added table row" in out
    assert "(re)wrote '### curl ...' Changes section" in out
    assert "updated entry for curlimages/curl" in out


def test_main_shared_image_sorts_at_its_real_values_yaml_position_not_last(uiv, tmp_path, monkeypatch):
    """Regression test (real bug, real doc): a MULTIPLE/shared-image bump
    (curl, global.images-anchored) used to always land at the very END of
    both the table and the "## Changes" section — canonical_names (which
    lets a bare "global"-anchored name sort at its own real values.yaml
    position, index 0 here since "global:" is the first top-level key)
    was computed by update_docs() but never actually passed through to
    update_component_table/insert_changes_section from
    update_docs_shared_image. keycloak-operator sorts AFTER "global" in
    values.yaml key order, so curl's row/section must land BEFORE it, not
    after."""
    write_chart_yaml(tmp_path, [("keycloak-operator", None)])
    values_path = write_values(tmp_path, (
        "global:\n"
        "  images:\n"
        "    curl: &curlImage\n"
        "      repository: curlimages/curl\n"
        f'      tag: "8.20.0@sha256:{"a" * 64}"\n'
        "keycloak-operator:\n"
        "  jobs:\n"
        "    ensureOperatorSa:\n"
        "      image: *curlImage\n"
    ))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "0.9.0"\n', encoding="utf-8")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-upgrade.md",
              "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
              "## Component versions (1.0.0 vs 0.9.0)\n\n"
              "| Component | App version | Helm chart | Notes |\n"
              "| --- | --- | --- | --- |\n"
              "| keycloak-operator | 1.0.0 (unchanged) | 1.0.0 (unchanged) | - |\n\n"
              "## Changes\n\n"
              "### keycloak-operator 1.0.0 (unchanged)\n\n"
              "Some existing prose about keycloak-operator.\n\n"
              "- Image / digest: see [`images-1.0.0.yaml`](../images/images-1.0.0.yaml).\n")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md",
              "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n")
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "MULTIPLE", "curl", "8.21.0"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert upgrade.index("| curl |") < upgrade.index("| keycloak-operator |")
    assert upgrade.index("### curl") < upgrade.index("### keycloak-operator")


def test_main_shared_image_insertion_gets_blank_line_when_preceding_content_has_none(
        uiv, tmp_path, monkeypatch):
    """Regression test (real bug, real doc): insert_changes_section used
    to assume a blank line already separated the insertion point from
    whatever precedes it — true only by accident. Real case: aaa-dep's
    own section here ends with no trailing blank line before EOF (e.g.
    already collapsed by an earlier fix-doc-consistency run's own EOF-
    blank-line handling); zzz-dep sorts after it in values.yaml key
    order, so its new section lands right there — and used to butt
    straight up against aaa-dep's last line with zero blank lines
    between them (MD022/MD032), since neither side of the insertion
    point supplies one on its own (section_text always starts directly
    with "### ", never a leading blank)."""
    write_chart_yaml(tmp_path, [("aaa-dep", None), ("zzz-dep", None)])
    values_path = write_values(tmp_path, (
        "aaa-dep:\n"
        "  image:\n"
        "    repository: example/aaa-dep\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
        "zzz-dep:\n"
        "  image:\n"
        "    repository: example/zzz-dep\n"
        f'    tag: "1.0.0@sha256:{"b" * 64}"\n'
    ))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "0.9.0"\n', encoding="utf-8")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-upgrade.md",
              "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
              "## Component versions (1.0.0 vs 0.9.0)\n\n"
              "| Component | App version | Helm chart | Notes |\n"
              "| --- | --- | --- | --- |\n"
              "| aaa-dep | 1.0.0 (unchanged) | 1.0.0 (unchanged) | - |\n\n"
              "## Changes\n\n"
              "### aaa-dep 1.0.0 (unchanged)\n\n"
              "Some existing prose about aaa-dep.\n\n"
              "- Image / digest: see [`images-1.0.0.yaml`](../images/images-1.0.0.yaml).\n")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md",
              "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n")
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "c" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "zzz-dep", "zzz-dep", "1.0.1"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "- Image / digest: see [`images-1.0.0.yaml`](../images/images-1.0.0.yaml).\n\n### zzz-dep" in upgrade
    assert "\n\n\n" not in upgrade


# --- shared-image doc updates vs the TRUE git baseline: reset-to-baseline
# removal, and collapsing more than one bump into a single entry ---

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


CURL_VALUES_TMPL = (
    "global:\n"
    "  images:\n"
    "    curl: &curlImage\n"
    "      repository: curlimages/curl\n"
    '      tag: "{version}@sha256:{digest}"\n'
    "keycloak-operator:\n"
    "  jobs:\n"
    "    ensureOperatorSa:\n"
    "      image: *curlImage\n"
    "zac:\n"
    "  global:\n"
    "    curlImage: *curlImage\n"
)


def test_main_removes_shared_image_docs_when_reset_back_to_baseline(uiv, tmp_path, monkeypatch):
    """curl bumped to 8.21.0 (already fully documented as a shared-image
    pseudo-component) and then reset back to its baseline version has
    nothing left to report: the table row, Changes section,
    values-delta bullet, and images-manifest 'changes:' entry/comment
    must all be removed -- the manifest ENTRY itself still lists the
    correct (baseline) version/digest."""
    write_chart_yaml(tmp_path, [("keycloak-operator", None), ("zac", None)])
    write_values(tmp_path, CURL_VALUES_TMPL.format(version="8.20.0", digest="a" * 64))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", tmp_path / "values.yaml")
    commit_baseline_tag(tmp_path, "0.9.0")  # baseline: curl 8.20.0@sha256:aaaa... everywhere

    # Simulate "already bumped to 8.21.0 earlier in this release cycle".
    write_values(tmp_path, CURL_VALUES_TMPL.format(version="8.21.0", digest="a" * 64))
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-upgrade.md",
              "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
              "## Component versions (1.0.0 vs 0.9.0)\n\n"
              "| Component | App version | Helm chart | Notes |\n"
              "| --- | --- | --- | --- |\n"
              "| curl | 8.20.0 → 8.21.0 | - | - |\n\n"
              "## Changes\n\n"
              "### curl 8.20.0 → 8.21.0\n\nblah\n")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md",
              "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\n"
              "## curl 8.20.0 → 8.21.0 — pinned at 1 place in `values.yaml`\n")
    write_doc(uiv.IMAGES_DIR, "images-1.0.0.yaml",
              "# Baseline: podiumd 0.9.0.\n#\n# One change:\n#   1. curl 8.20.0 -> 8.21.0.\n#\n\n"
              "# curl — 8.20.0 -> 8.21.0\n"
              "- name: curlimages/curl\n"
              "  url: docker.io/curlimages/curl\n"
              '  version: "8.21.0"\n'
              f'  digest: "sha256:{"a" * 64}"\n')

    import lib.image_version as image_version
    # Same digest baseline already recorded -- re-resolving 8.20.0 (a real,
    # immutable released version) from the registry always returns this
    # same digest, exactly like it would outside this mocked test.
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "a" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "MULTIPLE", "curl", "8.20.0"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| curl |" not in upgrade
    assert "### curl" not in upgrade

    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## curl" not in deltas

    manifest = (uiv.IMAGES_DIR / "images-1.0.0.yaml").read_text(encoding="utf-8")
    assert "Zero changes:" in manifest
    assert "curl 8.20.0" not in manifest  # the numbered "changes:" list item is gone
    assert "# curl —" not in manifest  # the entry's now-stale source comment is gone too
    assert '"8.20.0"' in manifest  # the entry itself still lists the correct (reset) version


def test_main_collapses_repeated_shared_image_bump_into_single_baseline_entry(uiv, tmp_path, monkeypatch):
    """Bumping curl to 8.21.0 and then, within the same release cycle,
    reconsidering to 8.22.0 instead must leave exactly ONE entry in each
    doc showing baseline -> final (8.20.0 -> 8.22.0) -- never two entries,
    and never an intermediate-hop transition like "8.21.0 -> 8.22.0"."""
    write_chart_yaml(tmp_path, [("keycloak-operator", None), ("zac", None)])
    write_values(tmp_path, CURL_VALUES_TMPL.format(version="8.20.0", digest="a" * 64))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", tmp_path / "values.yaml")
    commit_baseline_tag(tmp_path, "0.9.0")  # baseline: curl 8.20.0@sha256:aaaa... everywhere
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-upgrade.md",
              "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
              "## Component versions (1.0.0 vs 0.9.0)\n\n"
              "| Component | App version | Helm chart | Notes |\n"
              "| --- | --- | --- | --- |\n\n"
              "## Changes\n")
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md",
              "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\n")
    write_doc(uiv.IMAGES_DIR, "images-1.0.0.yaml",
              "# Baseline: podiumd 0.9.0.\n#\n# Zero changes:\n#\n\n"
              "- name: curlimages/curl\n"
              "  url: docker.io/curlimages/curl\n"
              '  version: "8.20.0"\n'
              f'  digest: "sha256:{"a" * 64}"\n')

    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "MULTIPLE", "curl", "8.21.0"])
    uiv.main()

    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "c" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "MULTIPLE", "curl", "8.22.0"])
    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert upgrade.count("| curl |") == 1
    assert "| curl | 8.20.0 → 8.22.0 | - | - |" in upgrade
    assert "8.21.0" not in upgrade
    assert upgrade.count("### curl") == 1
    assert "### curl 8.20.0 → 8.22.0" in upgrade

    # A shared image's own basename bump never touches any values.yaml
    # SCHEMA — no values-deltas.md section at all, whether bumped once
    # or (as here) reconsidered mid-cycle.
    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## curl" not in deltas
    assert "8.21.0" not in deltas

    manifest = (uiv.IMAGES_DIR / "images-1.0.0.yaml").read_text(encoding="utf-8")
    assert "One change:" in manifest
    assert "8.21.0" not in manifest
    assert "#   1. curl 8.20.0 -> 8.22.0." in manifest
    assert '"8.22.0"' in manifest
    assert f'"sha256:{"c" * 64}"' in manifest
