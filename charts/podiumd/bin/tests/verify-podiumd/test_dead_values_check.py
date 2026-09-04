"""check_dead_values — report-only check for values.yaml leaves no
template ever reads. No real helm invocation happens in these tests: a
fake `run` simulates a tiny renderer that only cares about two modeled
leaves (foo.used — echoed into its output; required.field — makes the
render fail entirely if nulled), so every other leaf (foo.dead) is
"dead" by construction. See lib.dead_values_check's own module
docstring for the top-down/recurse-on-diff strategy, the per-subchart
scoped rendering, and the full-chart confirmation safety net this
exercises."""
import io
import tarfile
from types import SimpleNamespace

import yaml

from dep_helpers import make_dep

CHART_YAML = "apiVersion: v2\nname: podiumd\nversion: 0.0.1\n"

VALUES_YAML = (
    "foo:\n"
    '  used: "abc"\n'
    '  dead: "xyz"\n'
    "required:\n"
    '  field: "present"\n'
)


def make_chart_dir(tmp_path, values=VALUES_YAML):
    (tmp_path / "Chart.yaml").write_text(CHART_YAML, encoding="utf-8")
    (tmp_path / "values.yaml").write_text(values, encoding="utf-8")
    return tmp_path


def write_chart_yaml_with_dep(tmp_path, dep):
    (tmp_path / "Chart.yaml").write_text(
        yaml.safe_dump({"apiVersion": "v2", "name": "podiumd", "version": "0.0.1", "dependencies": [dep]}),
        encoding="utf-8",
    )


def make_tgz(charts_dir, name, version):
    """A minimal vendored <name>-<version>.tgz — just enough for
    _resolve_scope's own `.is_file()` check to find it; its content is
    irrelevant here since these tests fake `run` directly rather than
    invoking real helm."""
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump({}).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def _overlay_values(cmd):
    """Merge every "-f <file>" argument's YAML content in cmd, in order —
    mirrors how Helm layers multiple -f overlays on top of each other."""
    merged = {}
    paths = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-f"]
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
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
    """A `run` stand-in modeling exactly two leaves: required.field makes
    the whole render fail if ever nulled (a `required` guard); foo.used
    is echoed into the rendered output (so nulling it changes the
    render). Every other leaf (foo.dead) is invisible to this model —
    nulling it can never change anything, i.e. genuinely dead."""
    def run(cmd, **kwargs):
        if call_log is not None:
            call_log.append(cmd)
        overrides = _overlay_values(cmd)
        if _get(overrides, ("required", "field"), "present") is None:
            return SimpleNamespace(returncode=1, stdout="", stderr="Error: required.field is required")
        used = _get(overrides, ("foo", "used"), "abc")
        stdout = (
            "---\n# Source: podiumd/templates/x.yaml\n"
            "kind: ConfigMap\nmetadata:\n  name: x\n"
            f"data:\n  used: {used!r}\n"
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return run


# --- flatten_leaves / candidate_leaf_paths (pure, no run()) ---

def test_flatten_leaves_scalars_and_empty_containers(libdeadvaluescheck):
    values = {"a": {"b": "x", "c": None}, "d": {}, "e": [], "f": [1, 2]}
    leaves = dict(libdeadvaluescheck.flatten_leaves(values))
    assert leaves == {
        ("a", "b"): "x",
        ("a", "c"): None,
        ("d",): {},
        ("e",): [],
        ("f",): [1, 2],
    }


def test_candidate_leaf_paths_skips_null_values(libdeadvaluescheck):
    values = {"a": {"b": "x", "c": None}}
    paths = libdeadvaluescheck.candidate_leaf_paths(values)
    assert paths == [("a", "b")]


def test_candidate_leaf_paths_skips_subchart_visibility_exempt(libdeadvaluescheck):
    values = {"zaakbrug": {"staging": {"apiProxy": {"tag": "stable"}}, "other": "x"}}
    paths = libdeadvaluescheck.candidate_leaf_paths(values)
    assert ("zaakbrug", "staging", "apiProxy", "tag") not in paths
    assert ("zaakbrug", "other") in paths


# --- check_dead_values (mocked run) ---

def test_check_dead_values_finds_the_one_dead_leaf(libdeadvaluescheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run())

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "1/3 dead (report only)"
    out = capsys.readouterr().out
    assert "foo.dead" in out
    assert "foo.used" not in out
    assert "required.field" not in out


def test_check_dead_values_whole_subtree_confirmed_dead_in_one_render(libdeadvaluescheck, tmp_path, monkeypatch):
    """Two leaves the fake model never reads at all — nulling both at once
    (the whole "foo" subtree, tested as one unit) still matches baseline,
    so both are confirmed dead without ever recursing into "foo"'s own
    children (only 2 `run` calls total: baseline + the one combined
    subtree render)."""
    chart_dir = make_chart_dir(tmp_path, values="foo:\n  dead1: \"x\"\n  dead2: \"y\"\n")
    call_log = []
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run(call_log))

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "2/2 dead (report only)"
    assert len(call_log) == 2


def test_check_dead_values_deep_dead_subtree_confirmed_regardless_of_depth(libdeadvaluescheck, tmp_path, monkeypatch):
    """The whole point of testing top-down: "bar"'s two dead leaves sit 4
    levels deep, but since NEITHER is ever read, nulling the entire "bar"
    subtree in one render already matches baseline — no need to recurse
    into bar.a, then bar.a.b, then each leaf individually. Only 3 `run`
    calls total: baseline, "foo" (used, so it's tested and rejected at
    the top level), "bar" (dead, confirmed in one shot despite its
    depth)."""
    chart_dir = make_chart_dir(
        tmp_path,
        values=(
            "foo:\n"
            '  used: "abc"\n'
            "bar:\n"
            "  a:\n"
            "    b:\n"
            '      c: "dead1"\n'
            '      d: "dead2"\n'
        ),
    )
    call_log = []
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run(call_log))

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "2/3 dead (report only)"
    assert len(call_log) == 3


def test_check_dead_values_nothing_dead_prints_ok(libdeadvaluescheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path, values="foo:\n  used: \"abc\"\n")
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run())

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "0/1 dead"
    assert "OK: no dead values.yaml entries found" in capsys.readouterr().out


def test_check_dead_values_baseline_render_failure_is_skipped_not_failed(libdeadvaluescheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)

    def always_fail(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(libdeadvaluescheck, "run", always_fail)

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "skipped — baseline render failed"


# --- per-subchart scoped rendering + full-chart confirmation safety net ---

def fake_run_scoped(call_log=None, full_reads_dead=False):
    """Models "zac" as a real vendored dependency: a SCOPED render
    (chart_name == "zac", the dependency's own release name) sees its
    overlay's keys flat (no "zac:" nesting — exactly what _resolve_scope
    is supposed to build) and echoes "used" (default "abc" if not
    overridden); "dead" is invisible to it. A FULL-chart render
    (chart_name == CHART_NAME) does the same for zac.used, but ALSO
    echoes zac.dead when full_reads_dead is True — modeling the
    "keycloak"-style exception where podiumd's own top-level templates
    read a dependency-scoped value directly, invisible to that
    dependency's own isolated render (see this module's docstring's
    safety-net rationale)."""
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
        stdout = (
            "---\n# Source: podiumd/templates/x.yaml\n"
            "kind: ConfigMap\nmetadata:\n  name: x\ndata:\n"
            + "".join(f"  {line}\n" for line in lines)
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return run


def make_scoped_chart_dir(tmp_path):
    write_chart_yaml_with_dep(tmp_path, make_dep("zac", "1.0.0"))
    make_tgz(tmp_path / "charts", "zac", "1.0.0")
    (tmp_path / "values.yaml").write_text('zac:\n  used: "abc"\n  dead: "xyz"\n', encoding="utf-8")
    return tmp_path


def test_check_dead_values_uses_scoped_render_for_matching_dependency(libdeadvaluescheck, tmp_path, monkeypatch):
    chart_dir = make_scoped_chart_dir(tmp_path)
    call_log = []
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run_scoped(call_log))

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "1/2 dead (report only)"
    assert any(cmd[2] == "zac" for cmd in call_log), "expected at least one scoped (zac) render"


def test_check_dead_values_safety_net_rejects_scoped_false_positive(libdeadvaluescheck, tmp_path, monkeypatch):
    """zac.dead looks dead to zac's own isolated render, but the (faked)
    full chart actually reads it — the confirmation pass against the
    real full-chart baseline must catch this and NOT report it."""
    chart_dir = make_scoped_chart_dir(tmp_path)
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run_scoped(full_reads_dead=True))

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "0/2 dead"


def test_resolve_scope_falls_back_to_full_scope_without_matching_dependency(libdeadvaluescheck, tmp_path):
    full_scope = {"chart_name": "podiumd", "baseline_docs": []}
    scope = libdeadvaluescheck._resolve_scope(tmp_path, {}, {}, "zac", full_scope)
    assert scope is full_scope


def test_resolve_scope_falls_back_to_full_scope_without_vendored_tgz(libdeadvaluescheck, tmp_path):
    full_scope = {"chart_name": "podiumd", "baseline_docs": []}
    dep_by_key = {"zac": make_dep("zac", "1.0.0")}
    scope = libdeadvaluescheck._resolve_scope(tmp_path, {"zac": {"a": "b"}}, dep_by_key, "zac", full_scope)
    assert scope is full_scope


def test_dependency_by_key_uses_alias_when_present(libdeadvaluescheck, tmp_path):
    write_chart_yaml_with_dep(tmp_path, make_dep("zaakafhandelcomponent", "1.0.0", alias="zac"))
    dep_by_key = libdeadvaluescheck._dependency_by_key(tmp_path)
    assert "zac" in dep_by_key
    assert dep_by_key["zac"]["name"] == "zaakafhandelcomponent"


def test_load_merged_values_layers_extra_args_over_values_yaml(libdeadvaluescheck, tmp_path):
    (tmp_path / "values.yaml").write_text("foo:\n  a: 1\n  b: 2\n", encoding="utf-8")
    overlay_path = tmp_path / "overlay.yaml"
    overlay_path.write_text("foo:\n  b: 3\n  c: 4\n", encoding="utf-8")

    merged = libdeadvaluescheck._load_merged_values(tmp_path, ["-f", str(overlay_path)])

    assert merged == {"foo": {"a": 1, "b": 3, "c": 4}}
