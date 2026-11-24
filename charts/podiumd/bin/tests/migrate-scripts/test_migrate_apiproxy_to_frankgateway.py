"""charts/podiumd/scripts/migrate-apiproxy-to-frankgateway.py: apiproxy replaced by the Frank!Gateway outway in three phases."""

import argparse

from pathlib import Path
from types import ModuleType

import pytest

GATEWAY = "http://frankgateway-outway.podiumd.svc.cluster.local:9080"

ENV = """\
apiproxy:
  enabled: true
  nginxCertsSecret: api-proxy-certs
  image:
    repository: "acr.example.io/nginxinc/nginx-unprivileged"
  nodeSelector:
    kubernetes.azure.com/mode: user
  locations:
    bag:
      targetUrl: "https://api.bag.example.nl/lvbag/v2"
      hostHeader: api.bag.example.nl
      apikey: "REP_API_BAG_KEY_REP"
      urlRewrite:
        enabled: true
    brp:
      targetUrl: "https://brp.example.nl/gateway/"
    kvkSearch:
      targetUrl: "https://api.kvk.example.nl/test/api/v2/zoeken"
      apikey: "REP_API_KVK_KEY_REP"
kiss:
  settings:
    haalCentraal:
      baseUrl: "http://api-proxy.podiumd.svc.cluster.local"  # the BFF appends /brp/personen
      customHeaders:
        x-request-afnemerscode: "123456"
        x-request-application: "gem-acc-kiss-podiumd-contact"
zac:
  brpApi:
    url: "http://api-proxy.podiumd.svc.cluster.local/brp"
openformulieren:
  configuration:
    data: |
      zgw_consumers:
        services:
          - identifier: brp-api
            api_root: http://api-proxy.podiumd.svc.cluster.local/haalcentraal/api/brp/
          - identifier: pdok
            api_root: https://api.pdok.nl/bzk/locatieserver/search/
          - identifier: vng-selectielijst
            api_root: https://selectielijst.openzaak.nl/api/v1/
"""

CHART = """\
frankgateway:
  image:
    repository: ghcr.io/wearefrank/frank-gateway
    tag: "1.2.1@sha256:0000"
  etcd:
    image:
      repository: quay.io/coreos/etcd
      tag: v3.6.15
  seed:
    job:
      image:
        repository: docker.io/curlimages/curl
        tag: "8.0.0"
  upstreamTls:
    verify: true
    caBundleSecretRef: {}
"""


def phase_args(tmp_path: Path, phase: int, forms_application: str | None = None) -> argparse.Namespace:
    """The command line of one phase, with CHART as the chart defaults."""
    chart = tmp_path / "values.yaml"
    chart.write_text(CHART, encoding="utf-8")
    return argparse.Namespace(
        phase=phase,
        chart_values=str(chart),
        forms_application=forms_application,
        oip_application=None,
        brp_key="REP_API_BRP_KEY_REP",
    )


def run_phases(apiproxy: ModuleType, tmp_path: Path, *phases: int) -> str:
    text = ENV
    for phase in phases:
        text, _ = apiproxy.migrate_text(text, phase_args(tmp_path, phase))
    return text


def test_phase1_appends_the_outway_and_keeps_the_file(apiproxy: ModuleType, tmp_path: Path):
    new, notes = apiproxy.migrate_text(ENV, phase_args(tmp_path, 1))

    assert new.startswith(ENV)
    block = apiproxy.load_safe(new)["frankgateway"]
    outway = block["instances"]["outway"]
    assert sorted(outway["routes"]) == ["forms-brp", "forms-pdok", "kiss-brp", "zac-brp"]
    assert block["instances"]["inway"] == {"enabled": False}
    assert outway["clientCertificates"] == {"apiproxy": {"openbaoPath": "frankgateway/client-certs/apiproxy"}}
    assert outway["upstreamTls"] == {"caBundleSecretRef": {"name": "api-proxy-certs", "key": "ca.crt"}}
    assert block["image"] == {"repository": "acr.example.io/wearefrank/frank-gateway"}
    assert block["seed"]["job"]["nodeSelector"] == {"kubernetes.azure.com/mode": "user"}
    assert "CHECK image acr.example.io/wearefrank/frank-gateway:1.2.1 must be mirrored before this deploy" in notes
    assert any(n.startswith("openformulieren vng-selectielijst not routed") for n in notes)


def test_a_route_maps_the_prefix_onto_the_service_root(apiproxy: ModuleType, tmp_path: Path):
    new, _ = apiproxy.migrate_text(ENV, phase_args(tmp_path, 1))

    zac_brp = apiproxy.load_safe(new)["frankgateway"]["instances"]["outway"]["routes"]["zac-brp"]
    assert zac_brp["uri"] == "/zac/brp/*"
    assert zac_brp["plugins"]["proxy-rewrite"] == {
        "regex_uri": ["^/zac/brp/(.*)", "/gateway/$1"],
        "headers": {"set": {"x-api-key": "REP_API_BRP_KEY_REP"}},
    }
    assert zac_brp["upstream"]["nodes"] == {"brp.example.nl:443": 1}
    assert zac_brp["upstream"]["tls"] == {"client_cert_id": "client-apiproxy"}


def test_forms_brp_gets_kiss_headers_with_its_own_application(apiproxy: ModuleType, tmp_path: Path):
    new, _ = apiproxy.migrate_text(ENV, phase_args(tmp_path, 1))

    headers = apiproxy.load_safe(new)["frankgateway"]["instances"]["outway"]["routes"]["forms-brp"]["plugins"][
        "proxy-rewrite"
    ]
    assert headers["headers"]["set"] == {
        "x-api-key": "REP_API_BRP_KEY_REP",
        "x-request-afnemerscode": "123456",
        "x-request-application": "gem-acc-forms-podiumd-contact",
    }


def test_an_application_option_wins(apiproxy: ModuleType, tmp_path: Path):
    new, _ = apiproxy.migrate_text(ENV, phase_args(tmp_path, 1, forms_application="gem-formulieren"))

    routes = apiproxy.load_safe(new)["frankgateway"]["instances"]["outway"]["routes"]
    assert routes["forms-brp"]["plugins"]["proxy-rewrite"]["headers"]["set"]["x-request-application"] == (
        "gem-formulieren"
    )


def test_a_header_per_request_is_reported(apiproxy: ModuleType, tmp_path: Path):
    text = ENV.replace(
        '        x-request-afnemerscode: "123456"\n',
        "        x-doelbinding:\n          RaadpleegMetBurgerservicenummer: BRPACT-KISS\n",
    )

    new, notes = apiproxy.migrate_text(text, phase_args(tmp_path, 1))

    routes = apiproxy.load_safe(new)["frankgateway"]["instances"]["outway"]["routes"]
    assert "x-doelbinding" not in routes["forms-brp"]["plugins"]["proxy-rewrite"]["headers"]["set"]
    assert any(n.startswith("CHECK kiss.settings.haalCentraal.customHeaders.x-doelbinding differs") for n in notes)


def test_the_bag_body_rewrite_of_nginx_is_kept(apiproxy: ModuleType, tmp_path: Path):
    text = ENV.replace(
        "          - identifier: pdok\n",
        "          - identifier: bag-api\n"
        "            api_root: http://api-proxy.podiumd.svc.cluster.local/lvbag/individuelebevragingen/v2/\n"
        "          - identifier: pdok\n",
    )

    new, notes = apiproxy.migrate_text(text, phase_args(tmp_path, 1))

    forms_bag = apiproxy.load_safe(new)["frankgateway"]["instances"]["outway"]["routes"]["forms-bag"]
    assert forms_bag["plugins"]["response-rewrite"]["filters"][0]["regex"] == r"https://api\.bag\.example\.nl/lvbag/v2/"
    assert forms_bag["plugins"]["proxy-rewrite"]["headers"]["remove"] == ["Accept-Encoding"]
    functions = forms_bag["plugins"]["serverless-pre-function"]["functions"]
    assert 'field = "api_bag_key", header = "X-Api-Key"' in functions[0]
    assert "OPENBAO <mount>/frankgateway field api_bag_key <- REP_API_BAG_KEY_REP (bag, header X-Api-Key)" in notes


def test_a_kvk_root_without_the_search_tail_is_reported(apiproxy: ModuleType, tmp_path: Path):
    text = ENV.replace("test/api/v2/zoeken", "iconnect/zoeken/v2/zoeken", 1)

    _, notes = apiproxy.migrate_text(text, phase_args(tmp_path, 1))

    assert notes[0].startswith("CHECK kvk: apiproxy.locations.kvkSearch.targetUrl")


def test_phase2_changes_only_the_app_values(apiproxy: ModuleType, tmp_path: Path):
    phase1 = run_phases(apiproxy, tmp_path, 1)

    new, notes = apiproxy.migrate_text(phase1, phase_args(tmp_path, 2))

    changed = [(a, b) for a, b in zip(phase1.splitlines(), new.splitlines(), strict=True) if a != b]
    assert changed == [
        (
            '      baseUrl: "http://api-proxy.podiumd.svc.cluster.local"  # the BFF appends /brp/personen',
            f'      baseUrl: "{GATEWAY}/kiss"  # the BFF appends /brp/personen',
        ),
        ('    url: "http://api-proxy.podiumd.svc.cluster.local/brp"', f'    url: "{GATEWAY}/zac/brp"'),
        (
            "            api_root: http://api-proxy.podiumd.svc.cluster.local/haalcentraal/api/brp/",
            f"            api_root: {GATEWAY}/forms/brp/",
        ),
        (
            "            api_root: https://api.pdok.nl/bzk/locatieserver/search/",
            f"            api_root: {GATEWAY}/forms/pdok/bzk/locatieserver/search/",
        ),
    ]
    assert len(notes) == 4


def test_phase2_needs_phase1(apiproxy: ModuleType, tmp_path: Path):
    with pytest.raises(apiproxy.MigrationError, match="run --phase 1 first"):
        apiproxy.migrate_text(ENV, phase_args(tmp_path, 2))


def test_phase3_waits_until_nothing_uses_api_proxy(apiproxy: ModuleType, tmp_path: Path):
    with pytest.raises(
        apiproxy.MigrationError, match=r"still pointing at api-proxy: kiss\.settings\.haalCentraal\.baseUrl"
    ):
        apiproxy.migrate_text(run_phases(apiproxy, tmp_path, 1), phase_args(tmp_path, 3))


def test_phase3_switches_apiproxy_off(apiproxy: ModuleType, tmp_path: Path):
    phase2 = run_phases(apiproxy, tmp_path, 1, 2)

    new, notes = apiproxy.migrate_text(phase2, phase_args(tmp_path, 3))

    assert new == phase2.replace("apiproxy:\n  enabled: true\n", "apiproxy:\n  enabled: false\n", 1)
    assert notes == ["apiproxy.enabled: true -> false"]


@pytest.mark.parametrize("phase", [1, 2, 3])
def test_a_second_run_changes_nothing(apiproxy: ModuleType, tmp_path: Path, phase: int):
    done = run_phases(apiproxy, tmp_path, *range(1, phase + 1))

    assert apiproxy.migrate_text(done, phase_args(tmp_path, phase)) == (done, [])


def test_a_file_without_apiproxy_is_left_alone(apiproxy: ModuleType, tmp_path: Path):
    text = "zac:\n  enabled: true\n"

    assert apiproxy.migrate_text(text, phase_args(tmp_path, 1)) == (text, [])
