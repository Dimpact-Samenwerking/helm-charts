"""check_utf8_format — BOM detection and stripping."""


def test_no_bom_passes(vp, tmp_path):
    (tmp_path / "values.yaml").write_bytes(b"zac:\n  enabled: true\n")
    ok, detail = vp.check_utf8_format(tmp_path)
    assert ok is True
    assert detail == "no BOM"


def test_bom_is_detected_and_stripped(vp, tmp_path):
    values_path = tmp_path / "values.yaml"
    values_path.write_bytes(b"\xef\xbb\xbfzac:\n  enabled: true\n")
    ok, detail = vp.check_utf8_format(tmp_path)
    assert ok is False
    assert "BOM" in detail
    # the file must actually be rewritten without the BOM
    assert values_path.read_bytes() == b"zac:\n  enabled: true\n"
