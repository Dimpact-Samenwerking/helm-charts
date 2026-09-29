"""verify-image-version main(): argument parsing and wiring into
check_basename_version. registry_tag_exists is patched on lib.image.version,
which resolves it through its own module globals."""

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


def test_help_flag_prints_docstring_and_exits_zero(
    viv: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr("sys.argv", ["verify-image-version", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        viv.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"{viv.__doc__}\n"


def test_wrong_arg_count_prints_docstring_and_exits_one(
    viv: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr("sys.argv", ["verify-image-version", "only-one-arg"])
    with pytest.raises(SystemExit) as exc_info:
        viv.main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


def test_main_found_reports_ok(
    viv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    monkeypatch.setattr(viv, "VALUES_YAML", values_path)
    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["verify-image-version", "pabc", "pabc-api", "1.1.2"])

    with pytest.raises(SystemExit) as exc_info:
        viv.main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert f"[FOUND  ] ghcr.io/platform-autorisatie-beheer-component/pabc-api:1.1.2  digest=sha256:{'b' * 64}" in out
    assert "OK: image version exists" in out


def test_main_missing_reports_fail(
    viv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    monkeypatch.setattr(viv, "VALUES_YAML", values_path)
    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (False, None))
    monkeypatch.setattr("sys.argv", ["verify-image-version", "pabc", "pabc-api", "9.9.9"])

    with pytest.raises(SystemExit) as exc_info:
        viv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "[MISSING] ghcr.io/platform-autorisatie-beheer-component/pabc-api:9.9.9" in out
    assert "FAIL: image version does not exist yet" in out


def test_main_resolves_given_component_key_and_basename(
    viv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """<key> scopes the search to that component's values.yaml subtree."""
    write_chart_yaml(tmp_path, [("openklant", None)])
    values_path = write_values(
        tmp_path,
        (f'openklant:\n  image:\n    repository: maykinmedia/open-klant\n    tag: "2.15.0@sha256:{"a" * 64}"\n'),
    )
    monkeypatch.setattr(viv, "VALUES_YAML", values_path)
    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["verify-image-version", "openklant", "open-klant", "2.15.1"])

    with pytest.raises(SystemExit) as exc_info:
        viv.main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "for 'openklant' 'open-klant'" in out
    assert "maykinmedia/open-klant:2.15.1" in out


def test_main_accepts_dependency_name_not_just_alias(
    viv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Regression: <key> accepts the Chart.yaml name as well as the alias
    (the values.yaml key), like update-component-version's <component>."""
    write_chart_yaml(tmp_path, [("zaakafhandelcomponent", "zac")])
    values_path = write_values(
        tmp_path,
        (f'zac:\n  image:\n    repository: infonl/zaakafhandelcomponent\n    tag: "5.4.3@sha256:{"a" * 64}"\n'),
    )
    monkeypatch.setattr(viv, "CHART_YAML", tmp_path / "Chart.yaml")
    monkeypatch.setattr(viv, "VALUES_YAML", values_path)
    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["verify-image-version", "zaakafhandelcomponent", "zaakafhandelcomponent", "5.4.4"])

    with pytest.raises(SystemExit) as exc_info:
        viv.main()

    assert exc_info.value.code == 0
    assert "infonl/zaakafhandelcomponent:5.4.4" in capsys.readouterr().out


def test_main_unresolvable_target_propagates(viv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """resolve_scoped_matches' own SystemExit for an unpinned image propagates."""
    values_path = write_values(tmp_path, "foo: bar\n")
    monkeypatch.setattr(viv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["verify-image-version", "foo", "totally-unknown", "1.0.0"])

    with pytest.raises(SystemExit, match="no image pin with basename 'totally-unknown' found under 'foo'"):
        viv.main()
