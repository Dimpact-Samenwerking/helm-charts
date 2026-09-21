"""Loads fix-doc-consistency (a hyphenated filename, not importable
normally) as a module named `cdb` so tests can call its functions directly."""

import importlib.util
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "fix-doc-consistency"


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write(path, text):
    path.write_text(text, encoding="utf-8")


@pytest.fixture(scope="session")
def cdb():
    loader = SourceFileLoader("fix_doc_consistency", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("fix_doc_consistency", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_registry_tag_exists(cdb, monkeypatch):
    """cdb.main()'s own final step (lib.image.docs.regenerate_images_
    baseline_manifest) resolves a live registry digest for any pin whose
    tag has no embedded "@sha256:..." of its own — most test fixtures
    always embed one (never actually reaching this), but a fixture that
    doesn't would otherwise make every `cdb.main()`-calling test attempt
    a REAL network call, with no default timeout (lib.registry.
    registry_tag_exists's own `timeout` param) — real slowdown observed
    live (fix-doc-consistency's own suite: ~13s -> ~130s) once this step
    was wired in unconditionally. Stubbed safe by default, same
    convention tests/update-image-version/conftest.py's own stub_fix_
    helm_doc uses — patched on lib.image.docs's own module globals
    (where regenerate_images_baseline_manifest actually calls it from,
    not cdb's own binding, which is a SEPARATE name in a different
    module — see that module's own import). A test needing different
    registry behavior overrides this via its own monkeypatch.setattr,
    same as any other autouse default."""
    import lib.image.docs as image_docs

    monkeypatch.setattr(image_docs, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "0" * 64))


@pytest.fixture(autouse=True)
def stub_render_chart(cdb, monkeypatch):
    """cdb.main()'s own new render_chart() call (feeding regenerate_
    images_baseline_manifest's own render-gate for subchart-default-only
    images — see lib.digest_pinning_check.find_unresolved_subchart_
    images) would otherwise invoke a REAL `helm template` against
    whatever CHART_YAML/VALUES_YAML a given test has monkeypatched —
    usually a synthetic tmp_path fixture with no real vendored chart
    structure behind it at all. Stubbed to a successful, EMPTY render by
    default (no chart-tree path "rendered" — so no subchart-default
    image is ever pulled into images-baseline.yaml this way, exactly the
    same as this render-gate's behavior before it existed): a test that
    specifically wants to exercise the new subchart-default augmentation
    overrides this via its own monkeypatch.setattr, same convention
    stub_registry_tag_exists above already uses — patched on cdb's own
    module globals (where main() actually calls it from)."""
    monkeypatch.setattr(
        cdb, "render_chart", lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="", stderr="")
    )


@pytest.fixture
def repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    write(
        doc_dir / "4.8.2-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n"
        "This is the upgrade guide for environments already on **4.8.2**.\n\n"
        "## Component versions (4.9.0 vs 4.8.2)\n",
    )
    write(doc_dir / "4.8.2-to-4.9.0-values-deltas.md", "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\nNo changes.\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed docs", cwd=tmp_path)
    return doc_dir


@pytest.fixture
def repo_with_baseline_tag(tmp_path):
    """A repo whose git history has a real "podiumd-4.8.5" tag at an older
    ZAC version, so load_baseline_state can resolve it for real."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}))
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | ACR mirror only |\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac, stale doc table", cwd=tmp_path)
    return doc_dir


@pytest.fixture
def repo_with_undocumented_component_bumps(tmp_path):
    """Three dependencies changed between the baseline tag and HEAD but
    none of them ever got a row in the upgrade doc's "Component
    versions" table at all — the real gap add_missing_component_rows
    exists to fill in. "openformulieren" and "keycloak-operator" both
    have a resolvable app image (the former via actual_app_version's
    default "<key>.image.tag" shape, the latter via its own registered
    lib.chart.COMPONENT_IMAGE_PATHS split-path entry); "redis-operator"
    is chart-only — no matching values.yaml image at all — the genuine
    case that forces a TODO-stub Changes section instead of full
    prose."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                    {
                        "name": "openforms",
                        "alias": "openformulieren",
                        "version": "1.11.0",
                        "repository": "@maykinmedia",
                    },
                    {"name": "keycloak-operator", "version": "1.12.1", "repository": "@adfinis"},
                    {"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
                "openformulieren": {"image": {"tag": "3.4.10@sha256:cccc"}},
                "keycloak-operator": {"operator": {"config": {"keycloakImage": {"tag": "26.6.4", "sha": "eeee"}}}},
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                    {
                        "name": "openforms",
                        "alias": "openformulieren",
                        "version": "1.12.0",
                        "repository": "@maykinmedia",
                    },
                    {"name": "keycloak-operator", "version": "1.13.0", "repository": "@adfinis"},
                    {"name": "redis-operator", "version": "0.27.0", "repository": "@opstree"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
                "openformulieren": {"image": {"tag": "3.5.6@sha256:dddd"}},
                "keycloak-operator": {"operator": {"config": {"keycloakImage": {"tag": "26.7.3", "sha": "ffff"}}}},
            }
        ),
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 (unchanged) | 1.0.297 (unchanged) | n/a |\n\n"
        "## Changes\n\n",
    )
    git("add", "-A", cwd=tmp_path)
    git(
        "commit",
        "-q",
        "-m",
        "bump openformulieren + keycloak-operator + redis-operator, no doc rows added",
        cwd=tmp_path,
    )
    return doc_dir


@pytest.fixture
def repo_with_undocumented_sidecar_bump(tmp_path):
    """redis-operator's own row already exists (unchanged, correct) —
    add_missing_component_rows has nothing to do at the top level. Its
    nested redis-ha sidecar image DID change vs baseline, but has no row
    of its own at all — the real gap add_missing_sidecar_rows exists to
    fill, mirroring the actual keycloak-operator/postgres case this
    feature was built for (a resolvable sidecar bumped alongside its
    already-documented parent, never given its own canonical row).
    "curl" lives under the shared "global.images" anchor — no owning
    Chart.yaml dependency at all — to exercise add_missing_sidecar_rows'
    OTHER shape (bare basename, no "<component> - " prefix) in the same
    fixture."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                    {"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
                "redis-operator": {
                    "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}}
                },
                "global": {"images": {"curlImage": {"repository": "curlimages/curl", "tag": "8.10.1@sha256:cccc"}}},
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
                "redis-operator": {
                    "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.6@sha256:aaaa"}}
                },
                "global": {"images": {"curlImage": {"repository": "curlimages/curl", "tag": "8.11.0@sha256:dddd"}}},
            }
        ),
    )
    write(
        doc_dir / "4.8.5-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 (unchanged) | 1.0.297 (unchanged) | n/a |\n"
        "| redis-operator | - | 0.26.1 (unchanged) | n/a |\n\n"
        "## Changes\n\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump redis-ha's redis image + shared curl, no sidecar rows added", cwd=tmp_path)
    return doc_dir
