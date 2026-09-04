"""check_dead_values — report-only check for values.yaml leaves no
template ever reads. No real helm invocation happens in these tests: a
fake `run` simulates a tiny renderer that only cares about two modeled
leaves (foo.used — echoed into its output; required.field — makes the
render fail entirely if nulled), so every other leaf (foo.dead) is
"dead" by construction. See lib.dead_values_check's own module
docstring for the batch/fallback strategy this exercises."""
from types import SimpleNamespace

import pytest
import yaml

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


_MISSING = object()


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


def test_check_dead_values_whole_batch_confirmed_dead_in_one_render(libdeadvaluescheck, tmp_path, monkeypatch):
    """Two leaves the fake model never reads at all — nulling both at once
    still matches baseline, so both are confirmed dead without any
    per-leaf fallback render (only 2 `run` calls total: baseline + the
    one combined batch render)."""
    chart_dir = make_chart_dir(tmp_path, values="foo:\n  dead1: \"x\"\n  dead2: \"y\"\n")
    call_log = []
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run(call_log))

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "2/2 dead (report only)"
    assert len(call_log) == 2


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


@pytest.mark.parametrize("batch_size", [1, 2, 3, 25])
def test_check_dead_values_result_independent_of_batch_size(libdeadvaluescheck, tmp_path, monkeypatch, batch_size):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libdeadvaluescheck, "run", fake_run())
    monkeypatch.setattr(libdeadvaluescheck, "DEAD_VALUES_BATCH_SIZE", batch_size)

    ok, detail = libdeadvaluescheck.check_dead_values(chart_dir, [])

    assert ok is True
    assert detail == "1/3 dead (report only)"
