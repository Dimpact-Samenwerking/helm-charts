"""check_digest_pinning — every "image: {tag: ...}" block in values.yaml
must have a digest-pinned tag, except the one known keycloak-operator
field that uses a separate split tag/sha convention instead.

Also check_subchart_image_visibility / find_unresolved_subchart_images —
a separate, report-only scan for images defined only in a vendored
dependency's own default values.yaml (see lib.chart.subchart_values),
which check_digest_pinning can never see since it only ever walks
podiumd's own values.yaml."""
import io
import tarfile

import yaml

from dep_helpers import make_dep

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def write_values_yaml(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def write_chart_yaml(chart_dir, deps):
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")


def make_tgz(charts_dir, name, version, values, templates=None):
    """A minimal vendored <name>-<version>.tgz containing <name>/values.yaml
    and, if `templates` is given (a {filename: text} dict), <name>/templates/
    <filename> for each entry — enough to exercise subchart_values and
    subchart_template_text without a real `helm pull`. `templates=None`
    (the default) omits templates/ entirely, matching a vendored .tgz whose
    layout subchart_template_text can't make sense of."""
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump(values).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for filename, text in (templates or {}).items():
            tpl_data = text.encode("utf-8")
            tpl_info = tarfile.TarInfo(name=f"{name}/templates/{filename}")
            tpl_info.size = len(tpl_data)
            tar.addfile(tpl_info, io.BytesIO(tpl_data))


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


def test_keycloak_operator_keycloak_image_is_exempt(vp, tmp_path):
    """keycloak-operator.operator.config.keycloakImage uses the exact
    same split tag/sha convention as operator.image above -- only
    visible to this check at all since find_image_tag_paths started
    recognizing "...Image"-suffixed keys, not just the literal "image"."""
    write_values_yaml(tmp_path, """\
keycloak-operator:
  operator:
    config:
      keycloakImage:
        repository: quay.io/keycloak/keycloak
        tag: "26.7.3"
        sha: "ff4257d0d64efbe99ed1ddfaf07765cc3c36dc7518bf8324d41961327f441c54"
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


def test_suffixed_image_key_is_enforced_too(vp, tmp_path, capsys):
    """A component needing more than one distinctly-named image (e.g. a
    job's main "image" plus a separate "initImage") can't use the bare
    "image" key for both — real-world case: ensurePodiumdAdminUser's
    Python init image. Regression: find_image_tag_paths used to only
    recognize the literal key "image", silently exempting every
    "...Image"-suffixed sibling from digest-pin enforcement entirely."""
    write_values_yaml(tmp_path, """\
keycloak-operator:
  jobs:
    ensurePodiumdAdminUser:
      initImage:
        repository: python
        tag: "3.14-slim"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False
    assert detail == "1/1 image(s) not digest-pinned"
    out = capsys.readouterr().out
    assert "keycloak-operator.jobs.ensurePodiumdAdminUser.initImage.tag: '3.14-slim'" in out


def test_plural_images_container_not_treated_as_an_image_block(vp, tmp_path):
    """"images" (plural, a container of several named templates, e.g.
    global.images.nginx) must not itself be flagged — it doesn't end in
    "Image" (capital I), so only its own literally-"image"/"...Image"-
    keyed children would ever be."""
    write_values_yaml(tmp_path, """\
global:
  images:
    nginx:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert detail == "0 pin(s), 0 unpinned"


# --- check_subchart_image_visibility / find_unresolved_subchart_images ---

def test_no_dependencies_passes(vp, tmp_path):
    write_chart_yaml(tmp_path, [])
    write_values_yaml(tmp_path, "{}\n")
    ok, detail = vp.check_subchart_image_visibility(tmp_path)
    assert ok is True
    assert detail == "0 unresolved"


def test_dependency_not_yet_vendored_is_skipped(vp, tmp_path):
    """No .tgz on disk yet (the "Dependencies" step hasn't run) — nothing
    to read, so silently skipped rather than an error."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    write_values_yaml(tmp_path, "{}\n")
    ok, detail = vp.check_subchart_image_visibility(tmp_path)
    assert ok is True
    assert detail == "0 unresolved"


def test_overridden_subchart_image_is_not_reported(vp, tmp_path):
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"}})
    write_values_yaml(tmp_path, f"""\
openzaak:
  image:
    repository: openzaak/open-zaak
    tag: "1.14.2@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_subchart_image_visibility(tmp_path)
    assert ok is True
    assert detail == "0 unresolved"


def test_unoverridden_floating_subchart_image_is_reported_but_never_fails(vp, tmp_path, capsys):
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2", alias="oz")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"}})
    write_values_yaml(tmp_path, "{}\n")

    ok, detail = vp.check_subchart_image_visibility(tmp_path)

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s), 0 exempt) — report only"
    out = capsys.readouterr().out
    assert "oz.image.tag: '1.14.2' (FLOATING in the sub-chart's own default)" in out


def test_unoverridden_already_pinned_subchart_image_is_reported_as_pinned(vp, tmp_path, capsys):
    write_chart_yaml(tmp_path, [make_dep("zac", "1.0.297", alias="zac")])
    make_tgz(tmp_path / "charts", "zac", "1.0.297",
              {"opentelemetry-collector": {"image": {
                  "repository": "otel/opentelemetry-collector", "tag": f"0.169.0@sha256:{DIGEST_A}"}}})
    write_values_yaml(tmp_path, "{}\n")

    ok, detail = vp.check_subchart_image_visibility(tmp_path)

    assert ok is True
    assert detail == "1 unresolved (0 floating tag(s), 0 exempt) — report only"
    out = capsys.readouterr().out
    assert f"zac.opentelemetry-collector.image.tag: '0.169.0@sha256:{DIGEST_A}' (pinned in the sub-chart's own default)" in out


def test_nested_subchart_image_path_resolved_correctly(vp, tmp_path):
    """A sub-chart default nested under more than one key (e.g. a sidecar)
    must be checked against the SAME nested path in podiumd's own
    values.yaml, not just its top-level scope."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(tmp_path, f"""\
openzaak:
  redis:
    image:
      repository: redis
      tag: "8.0@sha256:{DIGEST_B}"
""")
    ok, detail = vp.check_subchart_image_visibility(tmp_path)
    assert ok is True
    assert detail == "0 unresolved"


def test_exempted_digest_pinning_path_never_shows_up_as_unresolved(vp, tmp_path):
    """keycloak-operator.operator is exempt from check_digest_pinning
    because podiumd DOES override it (with a split tag/sha convention
    instead of an embedded digest) — it must never appear as "unresolved"
    here, since it has an own_tag by definition."""
    write_chart_yaml(tmp_path, [make_dep("keycloak-operator", "1.0.0")])
    make_tgz(tmp_path / "charts", "keycloak-operator", "1.0.0",
              {"operator": {"image": {"repository": "quay.io/keycloak/keycloak-operator", "tag": "26.6.4"}}})
    write_values_yaml(tmp_path, """\
keycloak-operator:
  operator:
    image:
      repository: quay.io/keycloak/keycloak-operator
      tag: "26.6.4"
""")
    ok, detail = vp.check_subchart_image_visibility(tmp_path)
    assert ok is True
    assert detail == "0 unresolved"


def test_multiple_unresolved_images_all_reported(vp, tmp_path, capsys):
    write_chart_yaml(tmp_path, [
        make_dep("openzaak", "1.14.2"),
        make_dep("openklant", "2.0.0"),
    ])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    make_tgz(tmp_path / "charts", "openklant", "2.0.0",
              {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(tmp_path, "{}\n")

    ok, detail = vp.check_subchart_image_visibility(tmp_path)

    assert ok is True
    assert detail == "2 unresolved (2 floating tag(s), 0 exempt) — report only"
    out = capsys.readouterr().out
    assert "openzaak.redis.image.tag" in out
    assert "openklant.redis.image.tag" in out


# --- SUBCHART_VISIBILITY_EXEMPT (staging etc.) ---

def test_exempted_subchart_visibility_finding_is_not_reported(vp, tmp_path, capsys):
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28")])
    make_tgz(tmp_path / "charts", "zaakbrug", "2.3.28",
              {"staging": {"image": {"repository": "openzaak/open-zaak", "tag": "1.9.0"}}})
    write_values_yaml(tmp_path, "{}\n")

    ok, detail = vp.check_subchart_image_visibility(tmp_path)

    assert ok is True
    assert detail == "0 unresolved (1 exempt)"
    out = capsys.readouterr().out
    assert "zaakbrug.staging" not in out
    assert "1 exempt" in out


def test_exempted_subchart_visibility_prefix_matches_nested_path_too(vp, tmp_path):
    """SUBCHART_VISIBILITY_EXEMPT's ("zaakbrug", "staging") entry must also
    cover staging.apiProxy — a path segment prefix match, not just an
    exact-path one — since the whole staging deployment mode (main image
    AND its API proxy sidecar) is what's permanently disabled."""
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28")])
    make_tgz(tmp_path / "charts", "zaakbrug", "2.3.28",
              {"staging": {"apiProxy": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "stable"}}}})
    write_values_yaml(tmp_path, "{}\n")

    ok, detail = vp.check_subchart_image_visibility(tmp_path)

    assert ok is True
    assert detail == "0 unresolved (1 exempt)"


def test_exemption_is_scoped_to_its_own_dependency_only(vp, tmp_path, capsys):
    """A DIFFERENT dependency's own "staging"-named key must NOT be
    silently swallowed by zaakbrug's own exemption — the exemption is
    keyed on (scope_key, subpath), not a bare rule-name match."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"staging": {"image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"}}})
    write_values_yaml(tmp_path, "{}\n")

    ok, detail = vp.check_subchart_image_visibility(tmp_path)

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s), 0 exempt) — report only"
    out = capsys.readouterr().out
    assert "openzaak.staging.image.tag" in out


def test_exempt_and_non_exempt_findings_mixed(vp, tmp_path, capsys):
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28"), make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "zaakbrug", "2.3.28",
              {"staging": {"image": {"repository": "openzaak/open-zaak", "tag": "1.9.0"}}})
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(tmp_path, "{}\n")

    ok, detail = vp.check_subchart_image_visibility(tmp_path)

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s), 1 exempt) — report only"
    out = capsys.readouterr().out
    assert "zaakbrug.staging" not in out
    assert "openzaak.redis.image.tag" in out
    assert "1 more already reviewed and exempted" in out


# --- subchart_template_text (structurally unreferenced keys) ---

def test_unreferenced_subchart_key_is_dropped_when_templates_show_it_is_dead(vp, tmp_path, capsys):
    """A vendored sub-chart's own top-level values key (e.g. pabc's "web"/
    "poller") that no template in that same sub-chart ever reads is
    structurally inert — reporting it as "unresolved" is just noise, since
    no podiumd override there could ever change what gets rendered."""
    write_chart_yaml(tmp_path, [make_dep("pabc", "1.1.1")])
    make_tgz(tmp_path / "charts", "pabc", "1.1.1",
              {"image": {"repository": "pabc/pabc-api", "tag": "1.1.1"},
               "web": {"image": {"tag": "1.1.1"}}},
              templates={"deployment.yaml": "image: {{ .Values.image.repository }}:{{ .Values.image.tag }}\n"})
    write_values_yaml(tmp_path, f"""\
pabc:
  image:
    repository: pabc/pabc-api
    tag: "1.1.1@sha256:{DIGEST_A}"
""")

    ok, detail = vp.check_subchart_image_visibility(tmp_path)

    assert ok is True
    assert detail == "0 unresolved"
    out = capsys.readouterr().out
    assert "web" not in out


def test_referenced_subchart_key_is_still_reported_even_with_templates_present(vp, tmp_path, capsys):
    """The flip side of the above: a key a template DOES read must still be
    reported as unresolved — the filter only drops keys with zero textual
    reference anywhere in templates/, not everything just because
    templates/ happens to be readable."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"redis": {"image": {"repository": "redis", "tag": "8.0"}}},
              templates={"deployment.yaml": "image: {{ .Values.redis.image.repository }}\n"})
    write_values_yaml(tmp_path, "{}\n")

    ok, detail = vp.check_subchart_image_visibility(tmp_path)

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s), 0 exempt) — report only"
    out = capsys.readouterr().out
    assert "openzaak.redis.image.tag" in out


def test_unreferenced_key_without_a_templates_dir_at_all_is_still_reported(vp, tmp_path, capsys):
    """A vendored .tgz with no templates/ directory at all (the shape
    every other test's make_tgz call already uses) is "can't tell", not
    "definitely unreferenced" — must NOT be filtered out just because the
    haystack subchart_template_text would see is empty."""
    write_chart_yaml(tmp_path, [make_dep("pabc", "1.1.1")])
    make_tgz(tmp_path / "charts", "pabc", "1.1.1",
              {"web": {"image": {"tag": "1.1.1"}}})
    write_values_yaml(tmp_path, "{}\n")

    ok, detail = vp.check_subchart_image_visibility(tmp_path)

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s), 0 exempt) — report only"
    out = capsys.readouterr().out
    assert "pabc.web.image.tag" in out
