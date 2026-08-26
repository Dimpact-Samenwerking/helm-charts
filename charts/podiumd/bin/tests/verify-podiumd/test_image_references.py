"""check_image_references / scan_image_references — every image: field in
templates/*.yaml must call the podiumd.image helper, per
.github/copilot-instructions.md's "Image References" convention."""


def write_template(chart_dir, name, text):
    templates_dir = chart_dir / "templates"
    templates_dir.mkdir(exist_ok=True)
    (templates_dir / name).write_text(text, encoding="utf-8")


def test_no_templates_dir_passes(vp, tmp_path):
    ok, detail = vp.check_image_references(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_helper_call_passes(vp, tmp_path):
    write_template(tmp_path, "a.yaml", '        image: {{ include "podiumd.image" .Values.foo.image }}\n')
    ok, detail = vp.check_image_references(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_helper_call_quoted_passes(vp, tmp_path):
    write_template(tmp_path, "a.yaml", '          image: {{ include "podiumd.image" $job.image | quote }}\n')
    ok, detail = vp.check_image_references(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_hand_interpolated_repository_and_tag_flagged(vp, tmp_path, capsys):
    write_template(tmp_path, "frankgateway.yaml",
                   '          image: "{{ $fg.image.repository }}:{{ $fg.image.tag }}"\n')
    ok, detail = vp.check_image_references(tmp_path)
    assert ok is False
    assert "1 violation(s)" in detail
    out = capsys.readouterr().out
    assert "frankgateway.yaml:1" in out


def test_bare_literal_image_flagged(vp, tmp_path, capsys):
    write_template(tmp_path, "redis-ha-pre-delete.yaml", "          image: docker.io/alpine/k8s:1.33.10\n")
    ok, detail = vp.check_image_references(tmp_path)
    assert ok is False
    assert "1 violation(s)" in detail
    out = capsys.readouterr().out
    assert "docker.io/alpine/k8s:1.33.10" in out


def test_multiple_violations_across_files_all_reported(vp, tmp_path, capsys):
    write_template(tmp_path, "a.yaml", '    image: "{{ .a.repository }}:{{ .a.tag }}"\n')
    write_template(tmp_path, "b.yaml", '    image: "{{ .b.repository }}:{{ .b.tag }}"\n')
    ok, detail = vp.check_image_references(tmp_path)
    assert ok is False
    assert "2 violation(s)" in detail
    out = capsys.readouterr().out
    assert "a.yaml:1" in out
    assert "b.yaml:1" in out


def test_similarly_named_keys_not_matched(vp, tmp_path):
    """imagePullPolicy: and initImage: aren't the `image:` key itself and
    must never be mistaken for a violation."""
    write_template(tmp_path, "a.yaml", "          imagePullPolicy: IfNotPresent\n          initImage: foo\n")
    ok, detail = vp.check_image_references(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_scan_image_references_returns_path_line_and_value(libimagereferencescheck, tmp_path):
    write_template(tmp_path, "a.yaml", '    image: "{{ .repository }}:{{ .tag }}"\n')
    findings = libimagereferencescheck.scan_image_references(tmp_path)
    assert len(findings) == 1
    path, line_no, value = findings[0]
    assert path.name == "a.yaml"
    assert line_no == 1
    assert value == '"{{ .repository }}:{{ .tag }}"'
