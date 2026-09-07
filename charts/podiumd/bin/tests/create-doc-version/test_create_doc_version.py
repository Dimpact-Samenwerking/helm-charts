"""create-doc-version's main() — argument parsing, and end-to-end wiring
into lib.component_docs.existing_doc_baselines/create_missing_docs (both
covered directly in tests/lib/test_component_docs.py). run_script (the
fix-helm-doc delegation) is mocked out via cdv.run_script
directly — no real subprocess needed."""
import subprocess

import pytest


def setup_dirs(cdv, tmp_path, monkeypatch, baseline="4.8.5"):
    """baseline=None skips writing etc/release-baseline.yaml at all — for
    the "no release-baseline.yaml at all" error case."""
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("version: 4.9.0\n", encoding="utf-8")
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    images_dir = tmp_path / "docs" / "images"
    doc_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)
    if baseline is not None:
        (tmp_path / "etc").mkdir()
        (tmp_path / "etc" / "release-baseline.yaml").write_text(
            f'upgrade_docs: "{baseline}"\n', encoding="utf-8")
    monkeypatch.setattr(cdv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(cdv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cdv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(cdv, "IMAGES_DIR", images_dir)
    monkeypatch.setattr(cdv, "run_script", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0))
    return doc_dir, images_dir


# --- main(): argument/help handling ---

def test_help_flag_prints_docstring_and_exits_zero(cdv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["create-doc-version", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        cdv.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == cdv.__doc__ + "\n"


def test_any_argument_fails(cdv, monkeypatch, capsys):
    """This script never takes the baseline (or anything else) as an
    argument — any positional argument (other than -h/--help) is
    rejected with the usage docstring."""
    monkeypatch.setattr("sys.argv", ["create-doc-version", "4.8.5"])
    with pytest.raises(SystemExit) as exc_info:
        cdv.main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


def test_invalid_baseline_format_fails(cdv, tmp_path, monkeypatch, capsys):
    """A defensive check against a hand-edited or corrupted release-
    baseline.yaml, now that this can no longer come from a CLI argument."""
    setup_dirs(cdv, tmp_path, monkeypatch, baseline="not-a-version")
    monkeypatch.setattr("sys.argv", ["create-doc-version"])
    with pytest.raises(SystemExit) as exc_info:
        cdv.main()
    assert exc_info.value.code == 1
    assert "is not a valid MAJOR.MINOR.PATCH version" in capsys.readouterr().out


# --- main(): release-baseline.yaml ---

def test_no_release_baseline_fails(cdv, tmp_path, monkeypatch, capsys):
    setup_dirs(cdv, tmp_path, monkeypatch, baseline=None)
    monkeypatch.setattr("sys.argv", ["create-doc-version"])
    with pytest.raises(SystemExit) as exc_info:
        cdv.main()
    assert exc_info.value.code == 1
    assert ("release-baseline.yaml has no upgrade_docs key (or the file doesn't exist "
            "yet)") in capsys.readouterr().out


def test_uses_release_baseline(cdv, tmp_path, monkeypatch, capsys):
    doc_dir, images_dir = setup_dirs(cdv, tmp_path, monkeypatch, baseline="4.8.5")
    monkeypatch.setattr("sys.argv", ["create-doc-version"])

    cdv.main()  # success path: must not raise

    assert (doc_dir / "4.8.5-to-4.9.0-upgrade.md").is_file()


# --- main(): creation ---

def test_creates_all_standard_docs_when_none_exist(cdv, tmp_path, monkeypatch, capsys):
    doc_dir, images_dir = setup_dirs(cdv, tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", ["create-doc-version"])

    cdv.main()

    for suffix in ("upgrade", "gemeente-specific", "values-deltas"):
        assert (doc_dir / f"4.8.5-to-4.9.0-{suffix}.md").is_file()
    assert (images_dir / "images-4.9.0.yaml").is_file()
    out = capsys.readouterr().out
    assert "4.8.5-to-4.9.0-upgrade.md: created" in out


def test_creates_only_the_missing_doc(cdv, tmp_path, monkeypatch, capsys):
    doc_dir, images_dir = setup_dirs(cdv, tmp_path, monkeypatch)
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text("hand-written\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["create-doc-version"])

    cdv.main()

    assert (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8") == "hand-written\n"
    assert (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").is_file()


def test_nothing_to_do_when_everything_already_exists(cdv, tmp_path, monkeypatch, capsys):
    doc_dir, images_dir = setup_dirs(cdv, tmp_path, monkeypatch)
    for suffix in ("upgrade", "gemeente-specific", "values-deltas"):
        (doc_dir / f"4.8.5-to-4.9.0-{suffix}.md").write_text("x", encoding="utf-8")
    (images_dir / "images-4.9.0.yaml").write_text("x", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["create-doc-version"])

    cdv.main()

    assert "nothing to do — every doc already exists" in capsys.readouterr().out


def test_refuses_when_doc_exists_under_a_different_baseline(cdv, tmp_path, monkeypatch, capsys):
    """The whole point of the split: never silently rebase docs that
    should have been created fresh (or vice versa) — this is
    fix-doc-consistency's job, so refuse outright instead."""
    doc_dir, images_dir = setup_dirs(cdv, tmp_path, monkeypatch)
    existing = doc_dir / "4.8.4-to-4.9.0-upgrade.md"
    existing.write_text("real content\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["create-doc-version"])

    with pytest.raises(SystemExit) as exc_info:
        cdv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "already exist for target 4.9.0 under a different upgrade_docs_baseline" in out
    assert "4.8.4-to-4.9.0-upgrade.md" in out
    assert "use fix-doc-consistency instead" in out
    # refuses to create ANYTHING, not just the conflicting suffix
    assert not (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").exists()
    assert existing.read_text(encoding="utf-8") == "real content\n"  # untouched


def test_invokes_fix_helm_doc(cdv, tmp_path, monkeypatch):
    setup_dirs(cdv, tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(cdv, "run_script", lambda cmd, *a, **k: (calls.append(cmd), subprocess.CompletedProcess(cmd, 0))[1])
    monkeypatch.setattr("sys.argv", ["create-doc-version"])

    cdv.main()

    assert any(str(cdv.FIX_HELM_DOC_SCRIPT) in cmd for cmd in calls)
