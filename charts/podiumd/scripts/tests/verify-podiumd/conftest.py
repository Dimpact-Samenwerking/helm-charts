"""Loads verify-podiumd.py (a hyphenated filename, not importable normally)
as a module named `vp` so tests can call its functions directly.

Also provides one fixture per lib/*_check.py module the checks were
refactored into (same convention as tests/lib/conftest.py's libregistry/
libchart/etc. fixtures). Most tests still go through `vp.check_X(...)` —
that keeps working unchanged since verify-podiumd.py re-exports every
check function. But a monkeypatch on a *helper* a moved check calls
internally (run, friendly_vendor_charts, registry_tag_exists, ...) must
target the module that check now actually lives in — `vp.run` only
affects code whose global `run` was bound by verify-podiumd.py's own
imports, not a lib module's separate `from lib.procutil import run`
binding. Use e.g. `libyamllintcheck` for those cases."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "verify-podiumd.py"

import lib.cve_check as cve_check
import lib.docs_consistency as docs_consistency
import lib.dry_check as dry_check
import lib.gitutil as gitutil
import lib.image_digests as image_digests
import lib.image_references_check as image_references_check
import lib.image_upgrade_check as image_upgrade_check
import lib.kube_score_check as kube_score_check
import lib.kubeconform_check as kubeconform_check
import lib.node_selector_check as node_selector_check
import lib.registry as registry
import lib.render_scope as render_scope
import lib.shellcheck_check as shellcheck_check
import lib.upgradedoc as upgradedoc
import lib.vendored_tgz_check as vendored_tgz_check
import lib.yamllint_check as yamllint_check


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_podiumd", SCRIPT_PATH)
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
def libimageupgradecheck():
    return image_upgrade_check


def make_dep(name, version, alias=None, repository="@example", condition=None):
    dep = {"name": name, "version": version, "repository": repository}
    if alias:
        dep["alias"] = alias
    if condition:
        dep["condition"] = condition
    return dep
