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

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "verify-podiumd"

import lib.cve_check as cve_check
import lib.cve_diff_check as cve_diff_check
import lib.dead_values_check as dead_values_check
import lib.digest_pinning_check as digest_pinning_check
import lib.docs_consistency as docs_consistency
import lib.dry_check as dry_check
import lib.gitutil as gitutil
import lib.helm_docs_check as helm_docs_check
import lib.image_digests as image_digests
import lib.image_references_check as image_references_check
import lib.image_upgrade_cache as image_upgrade_cache
import lib.image_upgrade_check as image_upgrade_check
import lib.kube_score_check as kube_score_check
import lib.kubeconform_check as kubeconform_check
import lib.lockstep_check as lockstep_check
import lib.markdown_check as markdown_check
import lib.node_selector_check as node_selector_check
import lib.registry as registry
import lib.release_secret_size as release_secret_size
import lib.render_scope as render_scope
import lib.settings as settings
import lib.shellcheck_check as shellcheck_check
import lib.upgradedoc as upgradedoc
import lib.vendored_tgz_check as vendored_tgz_check
import lib.yamllint_check as yamllint_check


def _load_module():
    loader = SourceFileLoader("verify_podiumd", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_podiumd", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def vp():
    return _load_module()


@pytest.fixture(scope="session")
def libdrycheck():
    return dry_check


@pytest.fixture(scope="session")
def libdigestpinningcheck():
    return digest_pinning_check


@pytest.fixture(scope="session")
def libimagedigests():
    return image_digests


@pytest.fixture(scope="session")
def libdocsconsistency():
    return docs_consistency


@pytest.fixture(scope="session")
def librenderscope():
    return render_scope


@pytest.fixture(scope="session")
def libyamllintcheck():
    return yamllint_check


@pytest.fixture(scope="session")
def libkubeconformcheck():
    return kubeconform_check


@pytest.fixture(scope="session")
def libshellcheckcheck():
    return shellcheck_check


@pytest.fixture(scope="session")
def libkubescorecheck():
    return kube_score_check


@pytest.fixture(scope="session")
def librelease_secret_size():
    return release_secret_size


@pytest.fixture(scope="session")
def libgitutil():
    return gitutil


@pytest.fixture(scope="session")
def libupgradedoc():
    return upgradedoc


@pytest.fixture(scope="session")
def libregistry():
    return registry


@pytest.fixture(scope="session")
def libimagereferencescheck():
    return image_references_check


@pytest.fixture(scope="session")
def libnodeselectorcheck():
    return node_selector_check


@pytest.fixture(scope="session")
def libvendoredtgzcheck():
    return vendored_tgz_check


@pytest.fixture(scope="session")
def libcvecheck():
    return cve_check


@pytest.fixture(scope="session")
def libcvediffcheck():
    return cve_diff_check


@pytest.fixture(scope="session")
def libhelmdocscheck():
    return helm_docs_check


@pytest.fixture(scope="session")
def libmarkdowncheck():
    return markdown_check


@pytest.fixture(scope="session")
def libimageupgradecheck():
    return image_upgrade_check


@pytest.fixture(scope="session")
def libimageupgradecache():
    return image_upgrade_cache


@pytest.fixture(scope="session")
def liblockstepcheck():
    return lockstep_check


@pytest.fixture(scope="session")
def libdeadvaluescheck():
    return dead_values_check


@pytest.fixture(scope="session")
def libsettings():
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
def chart_repo(tmp_path):
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
