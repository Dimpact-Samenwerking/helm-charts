"""check_utf8_format — BOM detection only, never writes to values.yaml."""


def test_no_bom_passes(vp, tmp_path):
    (tmp_path / "values.yaml").write_bytes(b"zac:\n  enabled: true\n")
    ok, detail = vp.check_utf8_format(tmp_path)
    assert ok is True
    assert detail == "no BOM"


def test_bom_is_detected_but_not_written(vp, tmp_path):
    values_path = tmp_path / "values.yaml"
    original = b"\xef\xbb\xbfzac:\n  enabled: true\n"
    values_path.write_bytes(original)
    ok, detail = vp.check_utf8_format(tmp_path)
    assert ok is False
    assert "BOM" in detail
    # this is a verify script — it must never write to a tracked file
    assert values_path.read_bytes() == original
