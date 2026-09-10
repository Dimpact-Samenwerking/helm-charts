"""lib.baseline_report.show_baseline_section — the shared "print one
release-baseline.yaml section's own outcome" three-tier wrapper
show-component-baseline-version and show-image-baseline-version both
build their own resolve-and-print body on top of."""


def test_show_baseline_section_prints_header(libbaselinereport, capsys):
    libbaselinereport.show_baseline_section("upgrade_docs", "4.8.5", lambda baseline: None)
    assert "=== upgrade_docs baseline ===" in capsys.readouterr().out


def test_show_baseline_section_none_baseline_is_skipped_without_calling_resolve(libbaselinereport, capsys):
    called = []
    result = libbaselinereport.show_baseline_section("release_table", None, lambda baseline: called.append(baseline))
    assert result is False
    assert called == []
    out = capsys.readouterr().out
    assert "  (release-baseline.yaml has no release_table key — skipping)" in out


def test_show_baseline_section_calls_resolve_with_the_baseline_value(libbaselinereport):
    received = []

    def resolve(baseline):
        received.append(baseline)
        return None

    libbaselinereport.show_baseline_section("upgrade_docs", "4.8.5", resolve)
    assert received == ["4.8.5"]


def test_show_baseline_section_success_returns_true_and_prints_no_error_line(libbaselinereport, capsys):
    def resolve(baseline):
        print("  Component: zac")
        return None

    result = libbaselinereport.show_baseline_section("upgrade_docs", "4.8.5", resolve)
    assert result is True
    out = capsys.readouterr().out
    assert "Component: zac" in out
    assert "error" not in out


def test_show_baseline_section_error_is_printed_verbatim_and_returns_false(libbaselinereport, capsys):
    """`resolve`'s own return value is printed AS-IS -- never given a
    second "error: " prefix here -- since a caller's own resolution step
    may already have one baked in (e.g. a SystemExit message it just
    reraises the text of)."""
    result = libbaselinereport.show_baseline_section("upgrade_docs", "4.8.5", lambda baseline: "error: boom")
    assert result is False
    out = capsys.readouterr().out
    assert "  error: boom" in out
    assert "error: error:" not in out


def test_show_baseline_section_always_ends_with_one_blank_line(libbaselinereport, capsys):
    libbaselinereport.show_baseline_section("upgrade_docs", "4.8.5", lambda baseline: None)
    assert capsys.readouterr().out.endswith("\n\n")

    libbaselinereport.show_baseline_section("upgrade_docs", None, lambda baseline: None)
    assert capsys.readouterr().out.endswith("\n\n")

    libbaselinereport.show_baseline_section("upgrade_docs", "4.8.5", lambda baseline: "error: boom")
    assert capsys.readouterr().out.endswith("\n\n")
