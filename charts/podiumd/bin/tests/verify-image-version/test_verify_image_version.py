"""verify-image-version's main() — argument parsing and end-to-end wiring
into lib.image_version.resolve_basename/check_basename_version. No
network needed: lib.registry.registry_tag_exists is monkeypatched via the
image_version module's own imported binding (check_basename_version lives
in lib.image_version, which resolves registry_tag_exists via ITS OWN
globals — see lib.image_version's import — so tests patch that module
directly, same as tests/update-image-version/test_update_image_version.py
does)."""
import pytest


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


def test_help_flag_prints_docstring_and_exits_zero(viv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["verify-image-version", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        viv.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == viv.__doc__ + "\n"


def test_wrong_arg_count_prints_docstring_and_exits_one(viv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["verify-image-version", "only-one-arg"])
    with pytest.raises(SystemExit) as exc_info:
        viv.main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


def test_main_found_reports_ok(viv, tmp_path, monkeypatch, capsys):
    values_path = write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(viv, "VALUES_YAML", values_path)
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["verify-image-version", "pabc-api", "1.1.2"])

    with pytest.raises(SystemExit) as exc_info:
        viv.main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert f"[FOUND  ] ghcr.io/platform-autorisatie-beheer-component/pabc-api:1.1.2  digest=sha256:{'b' * 64}" in out
    assert "OK: image version exists" in out


def test_main_missing_reports_fail(viv, tmp_path, monkeypatch, capsys):
    values_path = write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(viv, "VALUES_YAML", values_path)
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (False, None))
    monkeypatch.setattr("sys.argv", ["verify-image-version", "pabc-api", "9.9.9"])

    with pytest.raises(SystemExit) as exc_info:
        viv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "[MISSING] ghcr.io/platform-autorisatie-beheer-component/pabc-api:9.9.9" in out
    assert "FAIL: image version does not exist yet" in out


def test_main_resolves_component_alias_to_its_one_image(viv, tmp_path, monkeypatch, capsys):
    """"openklant" isn't a basename -- resolved as a Chart.yaml dependency
    whose own values.yaml scope pins exactly one image ("open-klant")."""
    write_chart_yaml(tmp_path, [("openklant", None)])
    values_path = write_values(tmp_path, (
        "openklant:\n"
        "  image:\n"
        "    repository: maykinmedia/open-klant\n"
        f'    tag: "2.15.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(viv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(viv, "VALUES_YAML", values_path)
    import lib.image_version as image_version
    monkeypatch.setattr(image_version, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["verify-image-version", "openklant", "2.15.1"])

    with pytest.raises(SystemExit) as exc_info:
        viv.main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "for 'open-klant'" in out
    assert "maykinmedia/open-klant:2.15.1" in out


def test_main_unresolvable_target_propagates(viv, tmp_path, monkeypatch):
    """resolve_basename (lib.image_version) already raises SystemExit with
    a clear message when <image> matches neither a pinned basename nor a
    Chart.yaml dependency — main() has nothing to add here. No Chart.yaml
    at all here (not even an empty one) — resolve_basename treats that
    the same as a dependency-less chart (deps=[])."""
    values_path = write_values(tmp_path, "foo: bar\n")
    monkeypatch.setattr(viv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(viv, "VALUES_YAML", values_path)
    monkeypatch.setattr("sys.argv", ["verify-image-version", "totally-unknown", "1.0.0"])

    with pytest.raises(SystemExit, match="is not a pinned image basename"):
        viv.main()
