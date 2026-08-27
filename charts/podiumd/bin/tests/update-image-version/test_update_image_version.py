"""update-image-version.py's main() — argument parsing and end-to-end
wiring into lib.image_version.update_image_version. No network needed:
lib.registry.registry_tag_exists is monkeypatched via the uiv module's own
imported binding (update_image_version lives in lib.image_version, which
resolves `registry_tag_exists` via ITS OWN globals — see
lib.image_version's import — so tests patch that module directly, same as
tests/lib/test_image_version.py does)."""
import pytest


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
    monkeypatch.setattr("sys.argv", ["update-image-version.py", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        uiv.main()
    assert exc_info.value.code == 0
    assert "Bump every values.yaml image tag pin" in capsys.readouterr().out


def test_wrong_arg_count_prints_docstring_and_exits_one(uiv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["update-image-version.py", "only-one-arg"])
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
    monkeypatch.setattr("sys.argv", ["update-image-version.py", "pabc-api", "1.1.2"])

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
    monkeypatch.setattr("sys.argv", ["update-image-version.py", "pabc-api", "1.1.2"])

    uiv.main()

    assert "nothing to do" in capsys.readouterr().out


def test_main_resolves_component_alias_to_its_one_image(uiv, tmp_path, monkeypatch, capsys):
    """"openklant" isn't a basename -- resolved as a Chart.yaml dependency
    whose own values.yaml scope pins exactly one image ("open-klant")."""
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
    monkeypatch.setattr("sys.argv", ["update-image-version.py", "openklant", "2.15.1"])

    uiv.main()

    out = capsys.readouterr().out
    assert "'openklant' resolved to image basename 'open-klant'" in out
    assert f'2.15.1@sha256:{"b" * 64}' in values_path.read_text(encoding="utf-8")


def test_main_raises_on_component_alias_with_multiple_images(uiv, tmp_path, monkeypatch, capsys):
    write_chart_yaml(tmp_path, [("zaakafhandelcomponent", "zac")])
    values_path = write_values(tmp_path, (
        "zac:\n"
        "  image:\n"
        f'    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.0.0@sha256:{"a" * 64}"\n'
        "  solr-operator:\n"
        "    image:\n"
        f'      repository: apache/solr-operator\n      tag: "0.9.1@sha256:{"b" * 64}"\n'
    ))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["update-image-version.py", "zac", "5.4.4"])

    with pytest.raises(SystemExit, match="which pins 2 distinct images"):
        uiv.main()


def test_main_exits_on_no_match(uiv, tmp_path, monkeypatch, capsys):
    values_path = write_values(tmp_path, "a:\n  image:\n    repository: org/repo\n    tag: \"1.0.0@sha256:" + "a" * 64 + "\"\n")
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["update-image-version.py", "curl", "8.22.0"])

    with pytest.raises(SystemExit):
        uiv.main()


# --- doc updates: single component affected -> full lib.component_docs treatment ---

def write_doc(doc_dir, name, text):
    (doc_dir / name).write_text(text, encoding="utf-8")


def test_main_single_component_updates_upgrade_doc_table_and_changes(uiv, tmp_path, monkeypatch, capsys):
    """A basename that resolves to exactly one component (here via the
    "openklant" alias) gets the SAME full-fidelity treatment
    update-component-version.py itself uses -- a real (unchanged) Helm
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
    monkeypatch.setattr("sys.argv", ["update-image-version.py", "openklant", "2.15.1"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| openklant | 2.15.0 → 2.15.1 | 1.0.0 (unchanged) | - |" in upgrade
    assert "### openklant 2.15.0 → 2.15.1 (chart 1.0.0, unchanged)" in upgrade

    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "- **openklant** app `2.15.0 → 2.15.1` (chart `1.0.0`, unchanged) — image tag only." in deltas

    out = capsys.readouterr().out
    assert "added table row" in out
    assert "added '### openklant ...' Changes section" in out


# --- doc updates: multiple components affected -> shared-image (lib.image_docs) treatment ---

def test_main_shared_image_creates_pseudo_component_row_and_changes_block(uiv, tmp_path, monkeypatch, capsys):
    """curl pinned under two unrelated components -- gets its own table
    row (Helm chart column "-") and a "### curl ..." Changes block
    listing every place it's pinned, matching the
    4.8.1-to-4.8.2-upgrade.md convention -- NOT one row/section per
    affected component."""
    write_chart_yaml(tmp_path, [("keycloak-operator", None), ("zac", None)])
    values_path = write_values(tmp_path, (
        "keycloak-operator:\n"
        "  jobs:\n"
        "    ensureOperatorSa:\n"
        "      image:\n"
        "        repository: curlimages/curl\n"
        f'        tag: "8.20.0@sha256:{"a" * 64}"\n'
        "zac:\n"
        "  global:\n"
        "    curlImage:\n"
        "      repository: curlimages/curl\n"
        f'      tag: "8.20.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
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
    monkeypatch.setattr("sys.argv", ["update-image-version.py", "curl", "8.21.0"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| curl | 8.20.0 → 8.21.0 | - | - |" in upgrade
    assert "### curl 8.20.0 → 8.21.0" in upgrade
    assert "`keycloak-operator.jobs.ensureOperatorSa.image.tag` `8.20.0` → `8.21.0`" in upgrade
    assert "`zac.global.curlImage.tag` `8.20.0` → `8.21.0`" in upgrade

    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "- **curl** image `8.20.0 → 8.21.0` — pinned at 2 places in `values.yaml`." in deltas

    manifest = (uiv.IMAGES_DIR / "images-1.0.0.yaml").read_text(encoding="utf-8")
    assert "#   1. curl 8.20.0 -> 8.21.0." in manifest
    assert "# curl — 8.20.0 -> 8.21.0" in manifest
    assert '"8.21.0"' in manifest

    out = capsys.readouterr().out
    assert "added table row" in out
    assert "added '### curl ...' Changes section" in out
    assert "updated entry for curlimages/curl" in out
