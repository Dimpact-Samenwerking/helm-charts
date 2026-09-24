"""Loads verify-podiumd (a hyphenated filename, not importable normally)
as a module named `vp` so tests can call its functions directly.

Also provides one fixture per lib/*_check.py module the checks were
refactored into (same convention as tests/lib/conftest.py's libregistry/
libchart/etc. fixtures). Most tests still go through `vp.check_X(...)` —
that keeps working unchanged since verify-podiumd re-exports every
check function. But a monkeypatch on a *helper* a moved check calls
internally (run, friendly_vendor_charts, registry_tag_exists, ...) must
target the module that check now actually lives in — `vp.run` only
affects code whose global `run` was bound by verify-podiumd's own
imports, not a lib module's separate `from lib.procutil import run`
binding. Use e.g. `libyamllintcheck` for those cases."""

import importlib.util
import subprocess
import sys

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "verify-podiumd"

import lib.checks.cve as cve_check
import lib.checks.cve_diff as cve_diff_check
import lib.checks.dead_values as dead_values_check
import lib.checks.digest_pinning as digest_pinning_check
import lib.checks.dry as dry_check
import lib.checks.helm_docs as helm_docs_check
import lib.checks.kube_score as kube_score_check
import lib.checks.kubeconform as kubeconform_check
import lib.checks.lockstep as lockstep_check
import lib.checks.markdown as markdown_check
import lib.checks.node_selector as node_selector_check
import lib.checks.shellcheck as shellcheck_check
import lib.checks.vendored_tgz as vendored_tgz_check
import lib.checks.yamllint as yamllint_check
import lib.docs_consistency as docs_consistency
import lib.docs_consistency.images_manifest_format as docs_consistency_images_manifest_format
import lib.docs_consistency.markdown_format as docs_consistency_markdown_format
import lib.docs_consistency.pointer_consistency as docs_consistency_pointer_consistency
import lib.docs_consistency.values_diff as docs_consistency_values_diff
import lib.gitutil as gitutil
import lib.image.digests as image_digests
import lib.image.references_check as image_references_check
import lib.image.upgrade_cache as image_upgrade_cache
import lib.image.upgrade_check as image_upgrade_check
import lib.registry as registry
import lib.release_secret_size as release_secret_size
import lib.render_scope as render_scope
import lib.settings as settings
import lib.upgradedoc.app_version_and_image_paths as upgradedoc_app_version_and_image_paths
import lib.upgradedoc.consistency_checks as upgradedoc_consistency_checks
import lib.upgradedoc.grouped_comments_and_changes_block as upgradedoc_grouped_comments_and_changes_block
import lib.upgradedoc.images_manifest_list_diff as upgradedoc_images_manifest_list_diff
import lib.upgradedoc.images_manifest_ordering as upgradedoc_images_manifest_ordering
import lib.upgradedoc.resolve_component_row as upgradedoc_resolve_component_row
import lib.upgradedoc.sorting_and_ordering as upgradedoc_sorting_and_ordering
import lib.upgradedoc.string_and_parsing_basics as upgradedoc_string_and_parsing_basics
import lib.upgradedoc.version_cells_and_key_changes as upgradedoc_version_cells_and_key_changes


def _load_module():
    loader = SourceFileLoader("verify_podiumd", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_podiumd", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def vp() -> ModuleType:
    return _load_module()


@pytest.fixture(scope="session")
def libdrycheck() -> ModuleType:
    return dry_check


@pytest.fixture(scope="session")
def libdigestpinningcheck() -> ModuleType:
    return digest_pinning_check


@pytest.fixture(scope="session")
def libimagedigests() -> ModuleType:
    return image_digests


@pytest.fixture(scope="session")
def libdocsconsistency() -> ModuleType:
    return docs_consistency


@pytest.fixture(scope="session")
def libimagesmanifest() -> ModuleType:
    return docs_consistency_images_manifest_format


@pytest.fixture(scope="session")
def libdocsconsistencypointer() -> ModuleType:
    return docs_consistency_pointer_consistency


@pytest.fixture(scope="session")
def libdocsconsistencymarkdown() -> ModuleType:
    return docs_consistency_markdown_format


@pytest.fixture(scope="session")
def libdocsconsistencyvaluesdiff() -> ModuleType:
    return docs_consistency_values_diff


@pytest.fixture(scope="session")
def librenderscope() -> ModuleType:
    return render_scope


@pytest.fixture(scope="session")
def libyamllintcheck() -> ModuleType:
    return yamllint_check


@pytest.fixture(scope="session")
def libkubeconformcheck() -> ModuleType:
    return kubeconform_check


@pytest.fixture(scope="session")
def libshellcheckcheck() -> ModuleType:
    return shellcheck_check


@pytest.fixture(scope="session")
def libkubescorecheck() -> ModuleType:
    return kube_score_check


@pytest.fixture(scope="session")
def librelease_secret_size() -> ModuleType:
    return release_secret_size


@pytest.fixture(scope="session")
def libgitutil() -> ModuleType:
    return gitutil


@pytest.fixture(scope="session")
def libupgradedocbasics() -> ModuleType:
    return upgradedoc_string_and_parsing_basics


@pytest.fixture(scope="session")
def libupgradedocsorting() -> ModuleType:
    return upgradedoc_sorting_and_ordering


@pytest.fixture(scope="session")
def libupgradedocconsistency() -> ModuleType:
    return upgradedoc_consistency_checks


@pytest.fixture(scope="session")
def libupgradedocresolverow() -> ModuleType:
    return upgradedoc_resolve_component_row


@pytest.fixture(scope="session")
def libupgradedocversioncells() -> ModuleType:
    return upgradedoc_version_cells_and_key_changes


@pytest.fixture(scope="session")
def libupgradedocappversion() -> ModuleType:
    return upgradedoc_app_version_and_image_paths


@pytest.fixture(scope="session")
def libupgradedocmanifestordering() -> ModuleType:
    return upgradedoc_images_manifest_ordering


@pytest.fixture(scope="session")
def libupgradedocmanifestdiff() -> ModuleType:
    return upgradedoc_images_manifest_list_diff


@pytest.fixture(scope="session")
def libupgradedoccomments() -> ModuleType:
    return upgradedoc_grouped_comments_and_changes_block


@pytest.fixture(scope="session")
def libregistry() -> ModuleType:
    return registry


@pytest.fixture(scope="session")
def libimagereferencescheck() -> ModuleType:
    return image_references_check


@pytest.fixture(scope="session")
def libnodeselectorcheck() -> ModuleType:
    return node_selector_check


@pytest.fixture(scope="session")
def libvendoredtgzcheck() -> ModuleType:
    return vendored_tgz_check


@pytest.fixture(scope="session")
def libcvecheck() -> ModuleType:
    return cve_check


@pytest.fixture(scope="session")
def libcvediffcheck() -> ModuleType:
    return cve_diff_check


@pytest.fixture(scope="session")
def libhelmdocscheck() -> ModuleType:
    return helm_docs_check


@pytest.fixture(scope="session")
def libmarkdowncheck() -> ModuleType:
    return markdown_check


@pytest.fixture(scope="session")
def libimageupgradecheck() -> ModuleType:
    return image_upgrade_check


@pytest.fixture(scope="session")
def libimageupgradecache() -> ModuleType:
    return image_upgrade_cache


@pytest.fixture(scope="session")
def liblockstepcheck() -> ModuleType:
    return lockstep_check


@pytest.fixture(scope="session")
def libdeadvaluescheck() -> ModuleType:
    return dead_values_check


@pytest.fixture(scope="session")
def libsettings() -> ModuleType:
    return settings


def _chart_repo_git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


_CHART_REPO_CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: zaakafhandelcomponent
    alias: zac
    version: 1.0.297
    repository: "@zac"
"""

_CHART_REPO_UPGRADE_DOC = """\
# Upgrade guide: PodiumD {baseline} → 4.9.0

## Component versions (4.9.0 vs {baseline})

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| ZAC (Zaakafhandelcomponent) | {app_source} → {app_target} | 1.0.297 (unchanged) | n/a |

See [`{baseline}-to-4.9.0-values-deltas.md`]({baseline}-to-4.9.0-values-deltas.md).
"""

_CHART_REPO_GEMEENTE_DOC = "# Gemeente-specific notes — PodiumD {baseline} → 4.9.0\n\nNone.\n"
_CHART_REPO_VALUES_DELTAS_DOC = (
    "# Values deltas — PodiumD {baseline} → 4.9.0\n\n"
    "## ZAC {app_source} → {app_target} (chart 1.0.297, unchanged) — image tag only\n\n"
    "No gemeente podiumd.yml changes are required for this hop.\n"
)
_CHART_REPO_IMAGES_MANIFEST = """\
# Baseline: podiumd {baseline} (test @ 0000000).
#
# Images new or changed in podiumd 4.9.0 vs {baseline}.
#
# Changes:
#   1. ZAC (Zaakafhandelcomponent) {app_source} -> {app_target} (chart 1.0.297, unchanged).
#
# See docs/_UPGRADE_PATHS/{baseline}-to-4.9.0-upgrade.md for the operator upgrade notes.

# ZAC — {app_source} -> {app_target}
- name: zac
  url: ghcr.io/infonl/zaakafhandelcomponent
  version: "{app_target}"
  digest: "sha256:abc"
"""


def _chart_repo_values_yaml(app_version):
    return (
        f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "{app_version}@sha256:abc"\n'
    )


@pytest.fixture
def chart_repo(tmp_path: Path):
    """Baseline commit (tagged podiumd-4.8.5) has ZAC 5.0.2; HEAD bumps it to
    5.4.3 and updates the matching docs to describe that exact change.

    Shared across the test_docs_consistency_integration_*.py files (promoted
    here since nearly every one of them uses it)."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    images_dir = chart_dir / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    _chart_repo_git("init", "-q", cwd=repo_root)
    _chart_repo_git("config", "user.email", "test@example.com", cwd=repo_root)
    _chart_repo_git("config", "user.name", "Test", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(_CHART_REPO_CHART_YAML)
    (chart_dir / "values.yaml").write_text(_chart_repo_values_yaml("5.0.2"))
    _chart_repo_git("add", "-A", cwd=repo_root)
    _chart_repo_git("commit", "-q", "-m", "baseline", cwd=repo_root)
    _chart_repo_git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "values.yaml").write_text(_chart_repo_values_yaml("5.4.3"))
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        _CHART_REPO_UPGRADE_DOC.format(baseline="4.8.5", app_source="5.0.2", app_target="5.4.3")
    )
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(_CHART_REPO_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        _CHART_REPO_VALUES_DELTAS_DOC.format(baseline="4.8.5", app_source="5.0.2", app_target="5.4.3")
    )
    (images_dir / "images-4.9.0.yaml").write_text(
        _CHART_REPO_IMAGES_MANIFEST.format(baseline="4.8.5", app_source="5.0.2", app_target="5.4.3")
    )
    _chart_repo_git("add", "-A", cwd=repo_root)
    _chart_repo_git("commit", "-q", "-m", "bump zac to 5.4.3", cwd=repo_root)

    return chart_dir


@pytest.fixture(autouse=True)
def stub_ensure_vendored_dependencies(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """main() now calls lib.dependencies.ensure_vendored_dependencies
    first, but every main()-level test here runs against a fake chart
    directory with no vendored sub-charts at all. Stubbed to a no-op by
    default; a test exercising the guard itself puts the real one back
    via its own monkeypatch.setattr, same as any other autouse default."""
    monkeypatch.setattr(vp, "ensure_vendored_dependencies", lambda chart_dir: None)
