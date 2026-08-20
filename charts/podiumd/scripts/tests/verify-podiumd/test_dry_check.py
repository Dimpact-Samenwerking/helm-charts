"""check_dry / find_similar_template_pairs — a report-only, never-failing
scan for templates/*.yaml file pairs that look like copy-paste duplication
(the shape podiumd.storagePVC was factored out of: 9 files, identical
except for the literal component name)."""
import difflib

BASE_LINES = [
    "apiVersion: v1",
    "kind: Pod",
    "metadata:",
    "  name: foo",
    "spec:",
    "  containers:",
    "  - name: c",
    "    image: nginx",
    "    ports:",
    "    - 80",
]


def write_template(chart_dir, name, lines):
    templates_dir = chart_dir / "templates"
    templates_dir.mkdir(exist_ok=True)
    (templates_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_no_templates_dir_passes(vp, tmp_path):
    ok, detail = vp.check_dry(tmp_path)
    assert ok is True
    assert "0 candidate(s)" in detail


def test_single_template_passes(vp, tmp_path):
    write_template(tmp_path, "a.yaml", BASE_LINES)
    ok, detail = vp.check_dry(tmp_path)
    assert ok is True
    assert "0 candidate(s)" in detail


def test_near_identical_pair_flagged_as_likely_worth_deduping(vp, tmp_path, capsys):
    high = list(BASE_LINES)
    high[3] = "  name: bar"
    write_template(tmp_path, "a.yaml", BASE_LINES)
    write_template(tmp_path, "b.yaml", high)

    ok, detail = vp.check_dry(tmp_path)
    assert ok is True  # never fails
    assert "1 candidate(s)" in detail
    out = capsys.readouterr().out
    assert "90% similar" in out
    assert "a.yaml" in out and "b.yaml" in out
    assert "likely worth deduping" in out


def test_moderately_similar_pair_flagged_as_borderline(vp, tmp_path, capsys):
    border = list(BASE_LINES)
    border[3] = "  name: bar"
    border[6] = "  - name: d"
    border[9] = "    - 81"
    write_template(tmp_path, "a.yaml", BASE_LINES)
    write_template(tmp_path, "b.yaml", border)

    ok, detail = vp.check_dry(tmp_path)
    assert ok is True
    assert "1 candidate(s)" in detail
    out = capsys.readouterr().out
    assert "70% similar" in out
    assert "borderline" in out


def test_dissimilar_pair_not_reported(vp, tmp_path):
    low = list(BASE_LINES)
    for i in (1, 3, 4, 6, 7, 9):
        low[i] = f"CHANGED{i}"
    write_template(tmp_path, "a.yaml", BASE_LINES)
    write_template(tmp_path, "b.yaml", low)

    ok, detail = vp.check_dry(tmp_path)
    assert ok is True
    assert "0 candidate(s)" in detail


def test_tiny_identical_files_not_reported(vp, tmp_path):
    """Below DRY_MIN_SIGNIFICANT_LINES, two files being identical is more
    likely coincidental boilerplate than real duplication worth flagging."""
    tiny = BASE_LINES[:5]
    write_template(tmp_path, "a.yaml", tiny)
    write_template(tmp_path, "b.yaml", tiny)

    ok, detail = vp.check_dry(tmp_path)
    assert ok is True
    assert "0 candidate(s)" in detail


def test_blank_lines_and_comments_ignored_in_comparison(vp, tmp_path, capsys):
    """Two structurally-identical templates that differ only in blank-line
    placement and comment wording must still be flagged."""
    commented = (
        ["# a comment nobody will read", ""] + BASE_LINES[:4]
        + ["", "# another comment"] + BASE_LINES[4:]
    )
    write_template(tmp_path, "a.yaml", BASE_LINES)
    write_template(tmp_path, "b.yaml", commented)

    ok, detail = vp.check_dry(tmp_path)
    assert ok is True
    assert "1 candidate(s)" in detail
    out = capsys.readouterr().out
    assert "100% similar" in out


def test_threshold_classifies_the_real_storage_pvc_case_as_worth_deduping(vp, tmp_path, capsys):
    """Regression pin: the confirmed real-world dedup win (9 pre-refactor
    storage.yaml files, factored into podiumd.storagePVC) scored ~0.82
    similar — differing only by the literal component name substituted in
    ~9 of 65 lines. If DRY_HIGH_SIMILARITY_THRESHOLD ever creeps above that,
    this exact case silently falls back to "borderline" advice, which is
    wrong — it's not a judgment call, it was a real duplicate."""
    a = list(BASE_LINES) * 6 + BASE_LINES[:5]  # 65 lines, same shape as the real file pair
    b = [line.replace("foo", "bar") if "name: foo" in line else line for line in a]
    write_template(tmp_path, "objecten-storage.yaml", a)
    write_template(tmp_path, "openklant-storage.yaml", b)

    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    assert ratio >= vp.DRY_HIGH_SIMILARITY_THRESHOLD, \
        f"test fixture ratio {ratio} no longer represents the real ~0.82 storage-file case"

    ok, detail = vp.check_dry(tmp_path)
    assert ok is True
    out = capsys.readouterr().out
    assert "likely worth deduping" in out
    assert "borderline" not in out


def test_never_fails_even_with_many_near_duplicates(vp, tmp_path):
    """Mirrors the real pre-refactor case (9 near-identical storage.yaml
    files) — however many candidates are found, this check must always
    pass; it is advisory only."""
    for i in range(5):
        lines = list(BASE_LINES)
        lines[3] = f"  name: component-{i}"
        write_template(tmp_path, f"storage-{i}.yaml", lines)

    ok, detail = vp.check_dry(tmp_path)
    assert ok is True
    assert "candidate(s) found" in detail
