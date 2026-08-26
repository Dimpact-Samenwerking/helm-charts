"""check_digest_pinning — every "image: {tag: ...}" block in values.yaml
must have a digest-pinned tag, except the one known keycloak-operator
field that uses a separate split tag/sha convention instead."""

DIGEST_A = "a" * 64


def write_values_yaml(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def test_no_values_yaml_passes(vp, tmp_path):
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert "0 pin(s)" in detail


def test_all_digest_pinned_passes(vp, tmp_path):
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert detail == "1 pin(s), 0 unpinned"


def test_floating_tag_fails(vp, tmp_path, capsys):
    write_values_yaml(tmp_path, """\
clamav:
  metrics:
    image:
      repository: docker.io/sergeymakinen/clamav_exporter
      tag: "v2.1.8"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False
    assert detail == "1/1 image(s) not digest-pinned"
    out = capsys.readouterr().out
    assert "clamav.metrics.image.tag: 'v2.1.8'" in out


def test_mix_of_pinned_and_floating_reports_only_the_floating_one(vp, tmp_path):
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
clamav:
  metrics:
    image:
      repository: docker.io/sergeymakinen/clamav_exporter
      tag: "v2.1.8"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False
    assert detail == "1/2 image(s) not digest-pinned"


def test_keycloak_operator_own_image_is_exempt(vp, tmp_path):
    """keycloak-operator.operator.image uses the adfinis chart's own
    split tag/sha convention -- embedding @sha256 in tag there would
    produce a double digest. Must never be flagged, regardless of what
    its own tag looks like."""
    write_values_yaml(tmp_path, """\
keycloak-operator:
  operator:
    image:
      repository: quay.io/keycloak/keycloak-operator
      tag: "26.6.4"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert detail == "1 pin(s), 0 unpinned"


def test_omc_own_image_is_exempt(vp, tmp_path):
    """omc's values.yaml comment says the subchart itself can't handle a
    digest-pinned tag -- must never be flagged."""
    write_values_yaml(tmp_path, """\
omc:
  image:
    tag: "1.17.19"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert detail == "1 pin(s), 0 unpinned"


def test_keycloak_operator_exemption_does_not_hide_other_violations(vp, tmp_path):
    write_values_yaml(tmp_path, """\
keycloak-operator:
  operator:
    image:
      repository: quay.io/keycloak/keycloak-operator
      tag: "26.6.4"
  jobs:
    ensurePodiumdAdminUser:
      image:
        repository: postgres
        tag: "16"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False
    assert detail == "1/2 image(s) not digest-pinned"


def test_sha256_style_digest_is_case_sensitive_lowercase_hex(vp, tmp_path):
    """A malformed/uppercase digest must still fail -- this check is
    about the shape scan_digest_pins itself requires, not just "has an
    @sha256 substring somewhere"."""
    write_values_yaml(tmp_path, """\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False


def test_multiple_violations_all_reported(vp, tmp_path, capsys):
    write_values_yaml(tmp_path, f"""\
clamav:
  metrics:
    image:
      repository: docker.io/sergeymakinen/clamav_exporter
      tag: "v2.1.8"
pabc:
  initContainers:
    waitFor:
      image:
        repository: groundnuty/k8s-wait-for
        tag: "v2.0"
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False
    assert detail == "2/3 image(s) not digest-pinned"
    out = capsys.readouterr().out
    assert "clamav.metrics.image.tag" in out
    assert "pabc.initContainers.waitFor.image.tag" in out
