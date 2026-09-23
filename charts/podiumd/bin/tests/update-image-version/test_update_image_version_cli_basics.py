"""update-image-version's main() — argument parsing, help/usage output,
and basename/key resolution into lib.image.version.update_image_version.
No doc-update path exercised here. No network needed:
lib.registry.registry_tag_exists is monkeypatched via the uiv module's own
imported binding (update_image_version lives in lib.image.version, which
resolves `registry_tag_exists` via ITS OWN globals — see
lib.image.version's import — so tests patch that module directly, same as
tests/lib/test_image_version.py does)."""

from pathlib import Path
from types import ModuleType

import pytest

from lib.image import version as image_version


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
    monkeypatch.setattr("sys.argv", ["update-image-version", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        uiv.main()
    assert exc_info.value.code == 0
    assert "Bump every values.yaml image tag pin" in capsys.readouterr().out


def test_wrong_arg_count_prints_docstring_and_exits_one(uiv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["update-image-version", "only-one-arg"])
    with pytest.raises(SystemExit) as exc_info:
        uiv.main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


def test_main_updates_matching_pin(uiv, tmp_path, monkeypatch, capsys):
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


def test_main_no_op_skips_fix_doc_consistency(
    uiv: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_run_fix_doc_consistency: list[str],
) -> None:
    """Nothing bumped, nothing to fix."""
    monkeypatch.setattr(uiv, "VALUES_YAML", pabc_values(tmp_path, "1.1.2"))
    monkeypatch.setattr("sys.argv", ["update-image-version", "pabc", "pabc-api", "1.1.2"])

    uiv.main()

    assert not stub_run_fix_doc_consistency


def test_main_reports_noop_when_already_at_target(uiv, tmp_path, monkeypatch, capsys):
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

    assert "nothing to do" in capsys.readouterr().out


def test_main_resolves_given_component_key_and_basename(uiv, tmp_path, monkeypatch, capsys):
    """<key> "openklant" scopes the search to that component's own
    values.yaml subtree, where <basename> "open-klant" is pinned."""
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


def test_main_accepts_dependency_name_not_just_alias(uiv, tmp_path, monkeypatch):
    """Regression test (real bug, confirmed live against the real chart):
    <key> used to only accept whichever string happens to literally BE
    the values.yaml top-level key — the alias, when a dependency has one
    — rejecting the dependency's own real Chart.yaml "name" outright
    ("no image pin with basename ... found under"), even though update-
    component-version's own <component> argument already accepts either
    form via find_dependency. lib.image.version.resolve_key_scope now
    resolves either form to the real values.yaml key first."""
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


def test_main_raises_when_basename_not_unique_under_key(uiv, tmp_path, monkeypatch, capsys):
    """Two DISTINCT repositories sharing a basename under the same <key>
    can't be identified uniquely (see lib.image.version.
    resolve_scoped_matches) -- an error, never a guess."""
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


def test_main_exits_on_no_match(uiv, tmp_path, monkeypatch, capsys):
    values_path = write_values(
        tmp_path, 'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:' + "a" * 64 + '"\n'
    )
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["update-image-version", "a", "curl", "8.22.0"])

    with pytest.raises(SystemExit):
        uiv.main()
