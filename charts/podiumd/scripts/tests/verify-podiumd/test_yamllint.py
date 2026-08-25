"""check_yamllint / build_line_sources / chart_name_from_source — runs
yamllint against the full `helm template` render (never against raw
templates/*.yaml, which contain Go template syntax that isn't valid YAML on
its own) and buckets findings by scope (this chart's own templates/ vs. a
"friendly" vendored sub-chart — Maykin/Info(NL)/ICATT/Worth/WeAreFrank/
Dimpact/local — vs. any other vendored sub-chart) and by rule (a real
structural problem — key-duplicates, syntax — vs. cosmetic style). Only an
own+real finding fails; a partner-vendor finding is printed per-item but
never fails; any other vendored finding only ever gets a one-line aggregate
count; cosmetic findings aren't reported at all anywhere — too noisy to be
worth surfacing right now. All `helm`/`yamllint` subprocess calls are
mocked via vp.run — friendly_vendor_charts is mocked too, since these tests
use tmp_path (no real Chart.yaml) — no real yamllint or helm invocation
happens in these tests."""
from types import SimpleNamespace



def fake_run(returncode=0, stdout="", stderr=""):
    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return run


def no_friendly_vendors(libyamllintcheck, monkeypatch):
    """Most tests don't care about the partner-vendor split — default to
    an empty mapping so every vendored finding lands in the plain
    "other vendor" aggregate-count bucket, as before that feature existed."""
    monkeypatch.setattr(libyamllintcheck, "friendly_vendor_charts", lambda chart_dir: {})


RENDERED = (
    "---\n"
    "# Source: podiumd/templates/frankgateway.yaml\n"
    "apiVersion: v1\n"
    "kind: Service\n"
    "---\n"
    "# Source: podiumd/charts/zac/templates/configmap.yaml\n"
    "apiVersion: v1\n"
    "kind: ConfigMap\n"
)
# Line numbers (1-based) of RENDERED:
#  1 ---
#  2 # Source: podiumd/templates/frankgateway.yaml
#  3 apiVersion: v1
#  4 kind: Service
#  5 ---
#  6 # Source: podiumd/charts/zac/templates/configmap.yaml
#  7 apiVersion: v1
#  8 kind: ConfigMap


def sequenced_run(yamllint_stdout, yamllint_returncode=1, rendered=RENDERED):
    def run(cmd, **kwargs):
        if cmd[0] == "yamllint":
            return SimpleNamespace(returncode=yamllint_returncode, stdout=yamllint_stdout, stderr="")
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")  # no --skip-schema-validation
        return SimpleNamespace(returncode=0, stdout=rendered, stderr="")  # helm template
    return run


# --- build_line_sources ---

def test_build_line_sources_maps_lines_to_preceding_source_comment(librenderscope):
    sources = librenderscope.build_line_sources(RENDERED)
    assert sources[3] == "podiumd/templates/frankgateway.yaml"
    assert sources[4] == "podiumd/templates/frankgateway.yaml"
    assert sources[7] == "podiumd/charts/zac/templates/configmap.yaml"


def test_build_line_sources_line_before_any_source_is_none(librenderscope):
    sources = librenderscope.build_line_sources(RENDERED)
    assert sources[1] is None


# --- chart_name_from_source ---

def test_chart_name_from_source_extracts_chart_immediately_before_templates(librenderscope):
    assert librenderscope.chart_name_from_source("podiumd/charts/zac/templates/configmap.yaml") == "zac"


def test_chart_name_from_source_uses_deepest_nested_chart(librenderscope):
    path = "podiumd/charts/eck-operator/charts/eck-operator-crds/templates/all-crds.yaml"
    assert librenderscope.chart_name_from_source(path) == "eck-operator-crds"


def test_chart_name_from_source_falls_back_to_raw_string(librenderscope):
    assert librenderscope.chart_name_from_source("no templates segment here") == "no templates segment here"


# --- check_yamllint ---

def test_check_yamllint_no_findings_passes(vp, libyamllintcheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_stdout="", yamllint_returncode=0))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "0 real" in detail


def test_check_yamllint_own_key_duplicate_fails(vp, libyamllintcheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    yamllint_out = '  4:5     error    duplication of key "kind" in mapping  (key-duplicates)\n'
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "1 real" in detail


def test_check_yamllint_own_cosmetic_not_reported_at_all(vp, libyamllintcheck, tmp_path, monkeypatch, capsys):
    """Cosmetic findings in our own templates aren't just non-failing —
    they're not mentioned anywhere in the output or detail string at all,
    per project decision (too noisy to be worth surfacing right now)."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    yamllint_out = "  4:1     error    trailing spaces  (trailing-spaces)\n"
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "cosmetic" not in detail
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"
    out = capsys.readouterr().out
    assert "trailing" not in out
    assert "cosmetic" not in out


def test_check_yamllint_vendored_key_duplicate_never_fails(vp, libyamllintcheck, tmp_path, monkeypatch, capsys):
    """Even a rule that would fail if found in our own templates must never
    fail the check when it's in a vendored sub-chart — we don't control
    that content, per project policy."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    yamllint_out = '  8:5     error    duplication of key "kind" in mapping  (key-duplicates)\n'
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 other-vendor" in detail
    out = capsys.readouterr().out
    assert "outside this repo's scope" in out
    assert "never a failure" in out


def test_check_yamllint_vendored_findings_reported_as_one_line_count(vp, libyamllintcheck, tmp_path, monkeypatch, capsys):
    """Non-friendly vendored findings are noisy (can be hundreds) and not
    actionable — reported as a single aggregate count, never dumped
    finding-by-finding."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    yamllint_out = (
        "  7:1     warning  missing starting space in comment  (comments)\n"
        "  8:1     error    trailing spaces  (trailing-spaces)\n"
    )
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "0 other-vendor" in detail  # both findings above are cosmetic rules — never counted
    out = capsys.readouterr().out
    assert "(trailing-spaces)" not in out
    assert "(comments)" not in out


def test_check_yamllint_friendly_vendor_finding_reported_per_item_never_fails(vp, libyamllintcheck, tmp_path, monkeypatch, capsys):
    """A vendored sub-chart from a listed partner org (Maykin, Info(NL),
    ICATT, Worth, WeAreFrank, Dimpact, or a local file:// dep) gets its
    finding printed individually — unlike a plain vendored finding, which
    only ever gets an aggregate count — but must still never fail."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    monkeypatch.setattr(libyamllintcheck, "friendly_vendor_charts", lambda chart_dir: {"zac": "Info(NL)"})
    yamllint_out = '  8:5     error    duplication of key "kind" in mapping  (key-duplicates)\n'
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 partner-vendor" in detail
    assert "0 other-vendor" in detail
    out = capsys.readouterr().out
    assert "reported for visibility, never a failure" in out
    assert "podiumd/charts/zac/templates/configmap.yaml" in out
    assert "Info(NL)" in out
    assert "duplication of key" in out  # per-item detail, not just a count


def test_check_yamllint_repeated_own_finding_in_one_file_is_grouped(vp, libyamllintcheck, tmp_path, monkeypatch, capsys):
    """The same root cause (e.g. the frankgateway templates duplicating
    app.kubernetes.io/name once per resource) shows up as several hits in
    one file — these must print as one grouped line with an occurrence
    count and a line list, not one [ERROR] line per hit."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    rendered = (
        "---\n"
        "# Source: podiumd/templates/frankgateway.yaml\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  labels:\n"
        "    app.kubernetes.io/name: podiumd\n"
        "    app.kubernetes.io/name: frankgateway-shim\n"
        "---\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  labels:\n"
        "    app.kubernetes.io/name: podiumd\n"
        "    app.kubernetes.io/name: frankgateway-shim\n"
    )
    yamllint_out = (
        '  8:5      error    duplication of key "app.kubernetes.io/name" in mapping  (key-duplicates)\n'
        '  14:5     error    duplication of key "app.kubernetes.io/name" in mapping  (key-duplicates)\n'
    )
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out, rendered=rendered))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "2 real" in detail
    out = capsys.readouterr().out
    assert out.count("[ERROR  ]") == 1  # one grouped line, not two
    assert "x2" in out
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    assert lines[-2:] == ["8", "14"]  # one location per line, not comma-joined


def test_check_yamllint_missing_binary_fails(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "not installed" in detail


def test_check_yamllint_render_failure_fails(vp, libyamllintcheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")

    def run(cmd, **kwargs):
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="Error: broke")

    monkeypatch.setattr(libyamllintcheck, "run", run)
    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail
