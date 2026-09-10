"""Loads fix-doc-consistency (a hyphenated filename, not importable
normally) as a module named `cdb` so tests can call its functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "fix-doc-consistency"


@pytest.fixture(scope="session")
def cdb():
    loader = SourceFileLoader("fix_doc_consistency", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("fix_doc_consistency", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_registry_tag_exists(cdb, monkeypatch):
    """cdb.main()'s own final step (lib.image_docs.regenerate_images_
    baseline_manifest) resolves a live registry digest for any pin whose
    tag has no embedded "@sha256:..." of its own — most test fixtures
    always embed one (never actually reaching this), but a fixture that
    doesn't would otherwise make every `cdb.main()`-calling test attempt
    a REAL network call, with no default timeout (lib.registry.
    registry_tag_exists's own `timeout` param) — real slowdown observed
    live (fix-doc-consistency's own suite: ~13s -> ~130s) once this step
    was wired in unconditionally. Stubbed safe by default, same
    convention tests/update-image-version/conftest.py's own stub_fix_
    helm_doc uses — patched on lib.image_docs's own module globals
    (where regenerate_images_baseline_manifest actually calls it from,
    not cdb's own binding, which is a SEPARATE name in a different
    module — see that module's own import). A test needing different
    registry behavior overrides this via its own monkeypatch.setattr,
    same as any other autouse default."""
    import lib.image_docs as image_docs
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
    monkeypatch.setattr(cdb, "render_chart",
                         lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="", stderr=""))
