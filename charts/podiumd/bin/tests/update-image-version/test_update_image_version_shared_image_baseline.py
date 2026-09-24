"""update-image-version's main() doc-update path for a shared image
(key=MULTIPLE) resolved against the TRUE git baseline -- reset-to-
baseline removal, and collapsing more than one in-cycle bump into a
single baseline-to-final entry. No network needed: lib.registry.
registry_tag_exists is monkeypatched via the uiv module's own imported
binding (update_image_version lives in lib.image.version, which resolves
`registry_tag_exists` via ITS OWN globals — see lib.image.version's
import — so tests patch that module directly, same as
tests/lib/test_image_version.py does)."""

import subprocess

from pathlib import Path
from types import ModuleType

import pytest


def write_values(tmp_path: Path, text):
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


def commit_baseline_tag(tmp_path: Path, baseline):
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


def test_main_removes_shared_image_docs_when_reset_back_to_baseline(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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
    write_doc(
        uiv.DOC_DIR,
        "0.9.0-to-1.0.0-upgrade.md",
        "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
        "## Component versions (1.0.0 vs 0.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| curl | 8.20.0 → 8.21.0 | - | - |\n\n"
        "## Changes\n\n"
        "### curl 8.20.0 → 8.21.0\n\nblah\n",
    )
    write_doc(
        uiv.DOC_DIR,
        "0.9.0-to-1.0.0-values-deltas.md",
        "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\n## curl 8.20.0 → 8.21.0 — pinned at 1 place in `values.yaml`\n",
    )
    write_doc(
        uiv.IMAGES_DIR,
        "images-1.0.0.yaml",
        "# Baseline: podiumd 0.9.0.\n#\n# One change:\n#   1. curl 8.20.0 -> 8.21.0.\n#\n\n"
        "# curl — 8.20.0 -> 8.21.0\n"
        "- name: curlimages/curl\n"
        "  url: docker.io/curlimages/curl\n"
        '  version: "8.21.0"\n'
        f'  digest: "sha256:{"a" * 64}"\n',
    )

    import lib.image.version as image_version

    # Same digest baseline already recorded -- re-resolving 8.20.0 (a real,
    # immutable released version) from the registry always returns this
    # same digest, exactly like it would outside this mocked test.
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "a" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "MULTIPLE", "curl", "8.20.0"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| curl |" not in upgrade
    assert "### curl" not in upgrade

    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## curl" not in deltas

    manifest = (uiv.IMAGES_DIR / "images-1.0.0.yaml").read_text(encoding="utf-8")
    # The header's own wording is never rewritten into a counted form —
    # same convention lib.component_docs.update_images_manifest already
    # uses; the fixture's own "# One change:" header stays exactly as it
    # already was, never rewritten to a false "Zero changes:".
    assert "# One change:" in manifest
    assert "Zero changes:" not in manifest
    assert "curl 8.20.0" not in manifest  # the numbered "changes:" list item is gone
    assert "# curl —" not in manifest  # the entry's now-stale source comment is gone too
    assert '"8.20.0"' in manifest  # the entry itself still lists the correct (reset) version


def test_main_collapses_repeated_shared_image_bump_into_single_baseline_entry(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Bumping curl to 8.21.0 and then, within the same release cycle,
    reconsidering to 8.22.0 instead must leave exactly ONE entry in each
    doc showing baseline -> final (8.20.0 -> 8.22.0) -- never two entries,
    and never an intermediate-hop transition like "8.21.0 -> 8.22.0"."""
    write_chart_yaml(tmp_path, [("keycloak-operator", None), ("zac", None)])
    write_values(tmp_path, CURL_VALUES_TMPL.format(version="8.20.0", digest="a" * 64))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", tmp_path / "values.yaml")
    commit_baseline_tag(tmp_path, "0.9.0")  # baseline: curl 8.20.0@sha256:aaaa... everywhere
    write_doc(
        uiv.DOC_DIR,
        "0.9.0-to-1.0.0-upgrade.md",
        "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
        "## Component versions (1.0.0 vs 0.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n",
    )
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md", "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\n")
    write_doc(
        uiv.IMAGES_DIR,
        "images-1.0.0.yaml",
        "# Baseline: podiumd 0.9.0.\n#\n# Zero changes:\n#\n\n"
        "- name: curlimages/curl\n"
        "  url: docker.io/curlimages/curl\n"
        '  version: "8.20.0"\n'
        f'  digest: "sha256:{"a" * 64}"\n',
    )

    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "MULTIPLE", "curl", "8.21.0"])
    uiv.main()

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "c" * 64))
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


def test_main_renders_new_when_shared_image_never_existed_at_baseline(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression test (same root-cause family as #1/#5, in the MULTIPLE-
    scope basename path): resolve_basename_baseline_version's own None
    ("didn't all agree, or any of them isn't found there" -- see its own
    docstring) used to get silently overridden by update_docs_shared_
    image with changes[0]["old_version"] -- whatever this basename
    happened to be pinned at immediately BEFORE this specific run, not
    the true upgrade_docs_baseline -- exactly the same conflation #1's
    fix already closed for a real Chart.yaml dependency's own app
    version. Here the shared "global.images.curl" anchor genuinely
    didn't exist at all at the true baseline (introduced mid-cycle at
    8.21.0, then bumped again this run to 8.22.0) -- with the bug,
    old_version fell back to the pre-run "8.21.0", showing a misleading
    "8.21.0 -> 8.22.0" transition implying curl was already tracked at
    the baseline and simply moved, instead of "(new)" (the same
    convention old_app=None already uses elsewhere for a component with
    no real baseline value at all)."""
    write_chart_yaml(tmp_path, [("keycloak-operator", None)])
    write_values(
        tmp_path,
        (f'keycloak-operator:\n  image:\n    repository: keycloak/keycloak\n    tag: "26.0.0@sha256:{"a" * 64}"\n'),
    )
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", tmp_path / "values.yaml")
    commit_baseline_tag(tmp_path, "0.9.0")  # baseline: no shared curl anchor at all yet

    # Mid-cycle, before this run: curl introduced as a brand-new shared
    # anchor at 8.21.0 -- never went through THIS run.
    write_values(
        tmp_path,
        (
            "global:\n"
            "  images:\n"
            "    curl: &curlImage\n"
            "      repository: curlimages/curl\n"
            '      tag: "8.21.0@sha256:{digest}"\n'
            "keycloak-operator:\n"
            "  image:\n"
            "    repository: keycloak/keycloak\n"
            f'    tag: "26.0.0@sha256:{"a" * 64}"\n'
            "  jobs:\n"
            "    ensureOperatorSa:\n"
            "      image: *curlImage\n"
        ).format(digest="b" * 64),
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
    write_doc(uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md", "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\n")

    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "c" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "MULTIPLE", "curl", "8.22.0"])
    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "8.21.0" not in upgrade
    assert "None" not in upgrade
    assert "| curl | 8.22.0 (new) | - | - |" in upgrade
    assert "### curl 8.22.0 (new)" in upgrade
