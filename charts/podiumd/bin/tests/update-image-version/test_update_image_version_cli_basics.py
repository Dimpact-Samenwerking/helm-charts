"""update-image-version main(): argument parsing and basename/key resolution.
registry_tag_exists is patched on lib.image.version, whose globals it resolves
through."""

from pathlib import Path
from types import ModuleType

import pytest

from lib.image import version as image_version


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


def test_help_flag_prints_docstring_and_exits_zero(
    uiv: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr("sys.argv", ["update-image-version", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        uiv.main()
    assert exc_info.value.code == 0
    assert "Bump every values.yaml image tag pin" in capsys.readouterr().out


def test_wrong_arg_count_prints_docstring_and_exits_one(
    uiv: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr("sys.argv", ["update-image-version", "only-one-arg"])
    with pytest.raises(SystemExit) as exc_info:
        uiv.main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


def test_main_updates_matching_pin(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    values_path = write_values(
        tmp_path,
        (
            "pabc:\n"
            "  image:\n"
            "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
            f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
        ),
    )
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "pabc", "pabc-api", "1.1.2"])

    uiv.main()

    out = capsys.readouterr().out
    assert "values.yaml:4" in out
    assert f"1.1.2@sha256:{'b' * 64}" in values_path.read_text(encoding="utf-8")


def pabc_values(tmp_path: Path, version: str) -> Path:
    """values.yaml with one pabc-api pin at `version`."""
    return write_values(
        tmp_path,
        (
            "pabc:\n"
            "  image:\n"
            "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
            f'    tag: "{version}@sha256:{"a" * 64}"\n'
        ),
    )


def registry_has_b_digest(_host: str, _repo: str, _tag: str) -> tuple[bool, str]:
    return True, "sha256:" + "b" * 64


def test_main_ends_with_fix_doc_consistency(
    uiv: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_run_fix_doc_consistency: list[str],
) -> None:
    """A bump ends with one fix-doc-consistency run."""
    monkeypatch.setattr(uiv, "VALUES_YAML", pabc_values(tmp_path, "1.1.1"))
    monkeypatch.setattr(image_version, "registry_tag_exists", registry_has_b_digest)
    monkeypatch.setattr("sys.argv", ["update-image-version", "pabc", "pabc-api", "1.1.2"])

    uiv.main()

    assert stub_run_fix_doc_consistency == ["fix-doc"]


def test_main_already_at_target_still_runs_fix_doc_consistency(
    uiv: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_run_fix_doc_consistency: list[str],
) -> None:
    """A rerun after values.yaml was written but the docs were not: the docs are completed."""
    monkeypatch.setattr(uiv, "VALUES_YAML", pabc_values(tmp_path, "1.1.2"))
    monkeypatch.setattr("sys.argv", ["update-image-version", "pabc", "pabc-api", "1.1.2"])

    uiv.main()

    assert stub_run_fix_doc_consistency


def test_main_reports_noop_when_already_at_target(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    values_path = write_values(
        tmp_path,
        (
            "pabc:\n"
            "  image:\n"
            "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
            f'    tag: "1.1.2@sha256:{"a" * 64}"\n'
        ),
    )
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["update-image-version", "pabc", "pabc-api", "1.1.2"])

    uiv.main()

    out = capsys.readouterr().out
    assert "already at 1.1.2 everywhere it's pinned; completing docs" in out
    assert values_path.read_text(encoding="utf-8").count("1.1.2@sha256:") == 1


def test_main_resolves_given_component_key_and_basename(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """<key> scopes the search to that component's values.yaml subtree."""
    write_chart_yaml(tmp_path, [("openklant", None)])
    values_path = write_values(
        tmp_path,
        (f'openklant:\n  image:\n    repository: maykinmedia/open-klant\n    tag: "2.15.0@sha256:{"a" * 64}"\n'),
    )
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "openklant", "open-klant", "2.15.1"])

    uiv.main()

    assert f"2.15.1@sha256:{'b' * 64}" in values_path.read_text(encoding="utf-8")


def test_main_accepts_dependency_name_not_just_alias(uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Regression: <key> accepts the Chart.yaml name as well as the alias
    (the values.yaml key), like update-component-version's <component>."""
    write_chart_yaml(tmp_path, [("zaakafhandelcomponent", "zac")])
    values_path = write_values(
        tmp_path,
        (f'zac:\n  image:\n    repository: infonl/zaakafhandelcomponent\n    tag: "5.4.3@sha256:{"a" * 64}"\n'),
    )
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "zaakafhandelcomponent", "zaakafhandelcomponent", "5.4.4"])

    uiv.main()

    assert f"5.4.4@sha256:{'b' * 64}" in values_path.read_text(encoding="utf-8")


def test_main_raises_when_basename_not_unique_under_key(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Distinct repositories sharing a basename under one <key> is an error,
    never a guess."""
    write_chart_yaml(tmp_path, [("zaakafhandelcomponent", "zac")])
    values_path = write_values(
        tmp_path,
        (
            "zac:\n"
            "  image:\n"
            f'    repository: org-one/curl\n    tag: "1.0.0@sha256:{"a" * 64}"\n'
            "  sidecar:\n"
            "    image:\n"
            f'      repository: org-two/curl\n      tag: "1.0.0@sha256:{"b" * 64}"\n'
        ),
    )
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["update-image-version", "zac", "curl", "2.0.0"])

    with pytest.raises(SystemExit, match="'curl' under 'zac' is not unique"):
        uiv.main()


def test_main_exits_on_no_match(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    values_path = write_values(
        tmp_path, 'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:' + "a" * 64 + '"\n'
    )
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["update-image-version", "a", "curl", "8.22.0"])

    with pytest.raises(SystemExit):
        uiv.main()
