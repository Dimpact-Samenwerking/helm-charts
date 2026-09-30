"""check_dead_values: report values.yaml leaves no template reads.

A fake `run` models two read leaves (foo.used, required.field); every other leaf is dead.
"""

import io
import tarfile

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest
import yaml

from dep_helpers import make_dep

CHART_YAML = "apiVersion: v2\nname: podiumd\nversion: 0.0.1\n"

VALUES_YAML = 'foo:\n  used: "abc"\n  dead: "xyz"\nrequired:\n  field: "present"\n'


def make_chart_dir(tmp_path: Path, values=VALUES_YAML):
    (tmp_path / "Chart.yaml").write_text(CHART_YAML, encoding="utf-8")
    (tmp_path / "values.yaml").write_text(values, encoding="utf-8")
    return tmp_path


def write_chart_yaml_with_deps(tmp_path: Path, deps):
    (tmp_path / "Chart.yaml").write_text(
        yaml.safe_dump({"apiVersion": "v2", "name": "podiumd", "version": "0.0.1", "dependencies": deps}),
        encoding="utf-8",
    )


def write_chart_yaml_with_dep(tmp_path: Path, dep):
    write_chart_yaml_with_deps(tmp_path, [dep])


def make_tgz(charts_dir, name, version):
    """Empty vendored <name>-<version>.tgz; only _resolve_scope's `.is_file()` needs it."""
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump({}).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def _overlay_values(cmd):
    """Merge every "-f <file>" in cmd, in order, as Helm layers overlays."""
    merged = {}
    paths = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-f"]
    for path in paths:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        _deep_merge(merged, data)
    return merged


def _deep_merge(base, overlay):
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _get(tree, path, default):
    node = tree
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def fake_run(call_log=None):
    """Fake render: nulling required.field fails; foo.used is echoed; all other leaves are dead."""

    def run(cmd, **kwargs):
        if call_log is not None:
            call_log.append(cmd)
        overrides = _overlay_values(cmd)
        if _get(overrides, ("required", "field"), "present") is None:
            return SimpleNamespace(returncode=1, stdout="", stderr="Error: required.field is required")
        used = _get(overrides, ("foo", "used"), "abc")
        stdout = (
            f"---\n# Source: podiumd/templates/x.yaml\nkind: ConfigMap\nmetadata:\n  name: x\ndata:\n  used: {used!r}\n"
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    return run


# --- flatten_leaves / candidate_leaf_paths (pure, no run()) ---


def test_flatten_leaves_scalars_and_empty_containers(libdeadvaluescheck: ModuleType):
    values = {"a": {"b": "x", "c": None}, "d": {}, "e": [], "f": [1, 2]}
    leaves = dict(libdeadvaluescheck.flatten_leaves(values))
    assert leaves == {
        ("a", "b"): "x",
        ("a", "c"): None,
        ("d",): {},
        ("e",): [],
        ("f",): [1, 2],
    }


def test_candidate_leaf_paths_skips_null_values(libdeadvaluescheck: ModuleType):
    values = {"a": {"b": "x", "c": None}}
    paths = libdeadvaluescheck.candidate_leaf_paths(values)
    assert paths == [("a", "b")]


def test_candidate_leaf_paths_no_longer_treats_zaakbrug_staging_specially(libdeadvaluescheck: ModuleType):
    """zaakbrug's "staging" subtree is an ordinary candidate, not special-cased."""
    values = {"zaakbrug": {"staging": {"apiProxy": {"tag": "stable"}}, "other": "x"}}
    paths = libdeadvaluescheck.candidate_leaf_paths(values)
    assert ("zaakbrug", "staging", "apiProxy", "tag") in paths
    assert ("zaakbrug", "other") in paths


def test_candidate_leaf_paths_skips_exempt_full_paths(libdeadvaluescheck: ModuleType):
    values = {"zac": {"enabled": True, "used": "x"}}
    paths = libdeadvaluescheck.candidate_leaf_paths(values, {("zac", "enabled")})
    assert paths == [("zac", "used")]


def test_condition_leaf_paths_reads_every_dependency_condition(libdeadvaluescheck: ModuleType, tmp_path: Path):
    write_chart_yaml_with_deps(
        tmp_path,
        [
            make_dep("zac", "1.0.0", condition="zac.enabled"),
            make_dep("eck-stack", "1.0.0", alias="kiss-eck", condition="kiss-eck.enabled"),
            make_dep("no-condition-dep", "1.0.0"),
        ],
    )
    paths = libdeadvaluescheck._condition_leaf_paths(tmp_path)
    assert paths == {("zac", "enabled"), ("kiss-eck", "enabled")}


# --- check_dead_values (mocked run) ---


def test_check_dead_values_finds_the_one_dead_leaf(
    libdeadvaluescheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run())

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "1/3 dead (report only)"
    out = capsys.readouterr().out
    assert "foo.dead" in out
    assert "foo.used" not in out
    assert "required.field" not in out


def test_check_dead_values_whole_subtree_confirmed_dead_in_one_render(
    libdeadvaluescheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An entirely dead subtree is confirmed in one render without recursing.

    4 runs: full baseline, own-templates baseline, subtree render, full-chart re-confirmation.
    """
    chart_dir = make_chart_dir(tmp_path, values='foo:\n  dead1: "x"\n  dead2: "y"\n')
    call_log = []
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run(call_log))

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "2/2 dead (report only)"
    assert len(call_log) == 4


def test_check_dead_values_deep_dead_subtree_confirmed_regardless_of_depth(
    libdeadvaluescheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Top-down search confirms a deep dead subtree in one render.

    5 runs: full baseline, own-templates baseline, "foo" (used), "bar" (dead), full re-confirmation.
    """
    chart_dir = make_chart_dir(
        tmp_path,
        values=('foo:\n  used: "abc"\nbar:\n  a:\n    b:\n      c: "dead1"\n      d: "dead2"\n'),
    )
    call_log = []
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run(call_log))

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "2/3 dead (report only)"
    assert len(call_log) == 5


def test_check_dead_values_nothing_dead_prints_ok(
    libdeadvaluescheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    chart_dir = make_chart_dir(tmp_path, values='foo:\n  used: "abc"\n')
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run())

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "0/1 dead"
    assert "OK: no dead values.yaml entries found" in capsys.readouterr().out


def test_check_dead_values_zaakbrug_staging_is_now_an_ordinary_dead_finding(
    libdeadvaluescheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """zaakbrug.staging is reported and counted like any other dead leaf, with no exemption bucket."""
    values = (
        "foo:\n"
        '  used: "abc"\n'
        '  dead: "xyz"\n'
        "required:\n"
        '  field: "present"\n'
        "zaakbrug:\n"
        "  staging:\n"
        "    apiProxy:\n"
        '      tag: "stable"\n'
    )
    chart_dir = make_chart_dir(tmp_path, values=values)
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run())

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "2/4 dead (report only)"
    out = capsys.readouterr().out
    assert "foo.dead" in out
    assert "zaakbrug.staging.apiProxy.tag" in out
    assert "exempt" not in out
    assert "policy" not in out


def test_check_dead_values_baseline_render_failure_is_skipped_not_failed(
    libdeadvaluescheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    chart_dir = make_chart_dir(tmp_path)

    def always_fail(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(libdeadvaluescheck, "run", always_fail)

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "skipped — baseline render failed"


# --- per-subchart scoped rendering + full-chart confirmation safety net ---


def fake_run_scoped(call_log=None, *, full_reads_dead=False):
    """Fake render with "zac" as a vendored dependency.

    Scoped render sees un-nested keys and echoes "used". Full-chart render also echoes
    zac.dead when full_reads_dead: parent templates reading a subchart value directly.
    """

    def run(cmd, **kwargs):
        if call_log is not None:
            call_log.append(cmd)
        chart_name = cmd[2]
        overrides = _overlay_values(cmd)
        if chart_name == "zac":
            used = _get(overrides, ("used",), "abc")
            lines = [f"used: {used!r}"]
        else:
            used = _get(overrides, ("zac", "used"), "abc")
            lines = [f"used: {used!r}"]
            if full_reads_dead:
                dead = _get(overrides, ("zac", "dead"), "xyz")
                lines.append(f"dead: {dead!r}")
        stdout = "---\n# Source: podiumd/templates/x.yaml\nkind: ConfigMap\nmetadata:\n  name: x\ndata:\n" + "".join(
            f"  {line}\n" for line in lines
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    return run


def make_scoped_chart_dir(tmp_path: Path):
    write_chart_yaml_with_dep(tmp_path, make_dep("zac", "1.0.0"))
    make_tgz(tmp_path / "charts", "zac", "1.0.0")
    (tmp_path / "values.yaml").write_text('zac:\n  used: "abc"\n  dead: "xyz"\n', encoding="utf-8")
    return tmp_path


def test_check_dead_values_uses_scoped_render_for_matching_dependency(
    libdeadvaluescheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    chart_dir = make_scoped_chart_dir(tmp_path)
    call_log = []
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run_scoped(call_log))

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "1/2 dead (report only)"
    assert any(cmd[2] == "zac" for cmd in call_log), "expected at least one scoped (zac) render"


def test_check_dead_values_safety_net_rejects_scoped_false_positive(
    libdeadvaluescheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A leaf dead in scoped render but read by the full chart is not reported."""
    chart_dir = make_scoped_chart_dir(tmp_path)
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run_scoped(full_reads_dead=True))

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "0/2 dead"


def test_check_dead_values_never_nulls_a_dependencys_own_condition_leaf(
    libdeadvaluescheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A Chart.yaml "condition:" leaf (zac.enabled) is never nulled in any overlay.

    A standalone subchart render has no parent to gate, so nulling it is unobservable.
    """
    write_chart_yaml_with_dep(tmp_path, make_dep("zac", "1.0.0", condition="zac.enabled"))
    make_tgz(tmp_path / "charts", "zac", "1.0.0")
    (tmp_path / "values.yaml").write_text('zac:\n  enabled: true\n  used: "abc"\n', encoding="utf-8")

    scoped_run = fake_run_scoped()
    seen_overlays = []

    def spying_run(cmd, **kwargs):
        seen_overlays.append(_overlay_values(cmd))  # read the -f file BEFORE it gets unlinked
        return scoped_run(cmd, **kwargs)

    monkeypatch.setattr(libdeadvaluescheck, "run", spying_run)

    ok, detail = libdeadvaluescheck.check_dead_values(tmp_path, [])

    assert ok is True
    assert detail == "0/1 dead"  # "enabled" excluded entirely; only "used" is a real candidate
    for overlay in seen_overlays:
        zac_view = overlay.get("zac", overlay)
        # Overlays are full copies, so check the original value, not just non-None.
        assert zac_view.get("enabled") is True, f"zac.enabled was nulled or dropped in {overlay}"


def test_resolve_scope_prefers_own_scope_without_matching_dependency(libdeadvaluescheck: ModuleType, tmp_path: Path):
    own_scope = {"chart_name": "podiumd", "baseline_docs": []}
    full_scope = {"chart_name": "podiumd", "baseline_docs": []}
    context = libdeadvaluescheck.ScopeResolutionContext(tmp_path, {}, {}, own_scope, full_scope)
    scope = libdeadvaluescheck._resolve_scope(context, "keycloak")
    assert scope is own_scope


def test_resolve_scope_falls_back_to_full_scope_without_matching_dependency_or_own_scope(
    libdeadvaluescheck: ModuleType, tmp_path: Path
):
    full_scope = {"chart_name": "podiumd", "baseline_docs": []}
    context = libdeadvaluescheck.ScopeResolutionContext(tmp_path, {}, {}, None, full_scope)
    scope = libdeadvaluescheck._resolve_scope(context, "keycloak")
    assert scope is full_scope


def test_resolve_scope_falls_back_to_full_scope_without_vendored_tgz(libdeadvaluescheck: ModuleType, tmp_path: Path):
    full_scope = {"chart_name": "podiumd", "baseline_docs": []}
    dep_by_key = {"zac": make_dep("zac", "1.0.0")}
    context = libdeadvaluescheck.ScopeResolutionContext(tmp_path, {"zac": {"a": "b"}}, dep_by_key, None, full_scope)
    scope = libdeadvaluescheck._resolve_scope(context, "zac")
    assert scope is full_scope


def test_dependency_by_key_uses_alias_when_present(libdeadvaluescheck: ModuleType, tmp_path: Path):
    write_chart_yaml_with_dep(tmp_path, make_dep("zaakafhandelcomponent", "1.0.0", alias="zac"))
    dep_by_key = libdeadvaluescheck._dependency_by_key(tmp_path)
    assert "zac" in dep_by_key
    assert dep_by_key["zac"]["name"] == "zaakafhandelcomponent"


def test_load_merged_values_layers_extra_args_over_values_yaml(libdeadvaluescheck: ModuleType, tmp_path: Path):
    (tmp_path / "values.yaml").write_text("foo:\n  a: 1\n  b: 2\n", encoding="utf-8")
    overlay_path = tmp_path / "overlay.yaml"
    overlay_path.write_text("foo:\n  b: 3\n  c: 4\n", encoding="utf-8")

    merged = libdeadvaluescheck._load_merged_values(tmp_path, ["-f", str(overlay_path)])

    assert merged == {"foo": {"a": 1, "b": 3, "c": 4}}
