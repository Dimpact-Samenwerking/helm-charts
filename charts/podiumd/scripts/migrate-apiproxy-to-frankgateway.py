#!/usr/bin/env python3
"""Replace apiproxy (nginx) by the Frank!Gateway outway in a gemeente podiumd.yml, one phase per run.

Every app reaches an external service at

    http://frankgateway-outway.podiumd.svc.cluster.local:9080/<app>/<service>/...

which the gateway maps onto the service's root URL; <app> is zac, kiss, forms
or oip. The roots come from the apiproxy locations (bag, brp, kvk) and Open
Formulieren's pdok service. Run the phases in order, each as its own commit
and deploy:

  --phase 1  Add a `frankgateway:` block: the outway with one route per app
             and service, inway and internal off. apiproxy keeps running and
             no app uses the gateway yet.
             - The gateway sets the API keys (BAG X-Api-Key, KVK apikey) from
               OpenBao, and a static `x-api-key: <--brp-key>` on every BRP
               route.
             - forms-brp and oip-brp also get KISS's fixed
               kiss.settings.haalCentraal.customHeaders, with "kiss" in
               x-request-application replaced by the app (or the value of
               --forms-application / --oip-application). ZAC and KISS send
               their own protocollering headers.
             - The client certificate of apiproxy.nginxCertsSecret comes from
               OpenBao (frankgateway/client-certs/apiproxy). Its ca.crt is
               trusted for the upstreams through
               upstreamTls.caBundleSecretRef, when the chart has that setting.
             - apiproxy's nodeSelector goes to every gateway workload, and its
               mirror registry to the gateway images.
  --phase 2  Point ZAC, KISS, Open Formulieren and Open Inwoner at their
             routes: one value per setting changes, nothing else in the file.
  --phase 3  Set apiproxy.enabled to false. Refused while a value in the file
             still points at api-proxy.

Notes name what needs a person: OpenBao entries to load (OPENBAO), images to
mirror, settings to change by hand and services that are not routed (CHECK).
Selectielijst and other external ZGW APIs are never routed: their absolute URLs
are stored in Open Zaak, so the apps must keep the real address.

The chart defaults the file is layered on come from the values.yaml next to
this script, i.e. the chart of this checkout; use --chart-values for another
chart version. Before writing, the script checks that the edited file parses to
exactly the original values plus the change. Running a phase twice is safe:
the second run changes nothing.

Exit code: 1 when a file has an error, or under --check when a file needs
migrating; else 0.

Usage:
  pip install ruamel.yaml
  python3 migrate-apiproxy-to-frankgateway.py --phase 1 --dry-run <values-repo>/applications/gemeenten/<gemeente>/<stage>/podiumd.yml
  python3 migrate-apiproxy-to-frankgateway.py --phase 1 <values-repo>/applications/gemeenten/<gemeente>/<stage>/podiumd.yml
  python3 migrate-apiproxy-to-frankgateway.py --phase 2 --forms-application <name> path/to/podiumd.yml
"""

from __future__ import annotations

import copy
import functools
import io
import re
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import urlsplit

from migrate_common import MigrationError
from migrate_common import literal_block
from migrate_common import load_rt
from migrate_common import load_safe
from migrate_common import rt_yaml
from migrate_common import run
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

if TYPE_CHECKING:
    import argparse

GATEWAY = "http://frankgateway-outway.podiumd.svc.cluster.local:9080"
CHART_VALUES = Path(__file__).resolve().parents[1] / "values.yaml"
BRP_KEY = "REP_API_BRP_KEY_REP"
CLIENT_CERT = "apiproxy"
PDOK_ROOT = "https://api.pdok.nl/"
APPLICATION_HEADER = "x-request-application"
PHASE_GATEWAY, PHASE_APPS, PHASE_OFF = 1, 2, 3
# The app key in podiumd.yml of each path prefix.
APP_KEYS = {"zac": "zac", "kiss": "kiss", "forms": "openformulieren", "oip": "openinwoner"}
_PLACEHOLDER = re.compile(r"^REP_(.+)_REP$")
_URL = re.compile(r"^(https?)://([^/:]+)(?::(\d+))?(/.*)$")
_REGEX_SPECIAL = re.compile(r"([\].[+?(){}|^$*\\])")


@dataclass(frozen=True)
class Service:
    """An external service behind the gateway."""

    name: str
    root: str  # ends in /
    host: str  # Host header and SNI
    key_header: str  # header the gateway sets from OpenBao, "" for none
    key: str  # the env's key value (a REP_..._REP placeholder), "" for none
    client_cert: bool


@dataclass(frozen=True)
class Target:
    """An app setting that phase 2 points at the gateway route <app>-<service>."""

    app: str
    service: str
    where: tuple[str, ...]  # the key path in podiumd.yml; the app key for a zgw-consumers service
    identifier: str = ""  # the zgw-consumers service in <app key>.configuration.data, "" for a plain key

    @property
    def route(self) -> str:
        return f"{self.app}-{self.service}"

    @property
    def path(self) -> str:
        if self.identifier:
            return f"{self.where[0]}.configuration.data service {self.identifier} api_root"
        return ".".join(self.where)

    def new_url(self, current: str) -> str:
        """The gateway URL for this setting; the apps append their own paths to it."""
        prefix = f"{GATEWAY}/{self.app}/{self.service}"
        if self.identifier:
            tails = {"kvk": "api/", "pdok": current.removeprefix(PDOK_ROOT)}
            return f"{prefix}/{tails.get(self.service, '')}"
        if self.app == "kiss":
            # The BFF appends /brp/personen to the Haal Centraal base and
            # v2/zoeken, v1/... to the KVK base.
            return f"{GATEWAY}/kiss" if self.service == "brp" else f"{prefix}/api"
        return prefix


# Every app setting the gateway replaces, in the order phase 2 reports them.
TARGETS = (
    *(
        Target(app, service, (APP_KEYS[app],), identifier)
        for app in ("forms", "oip")
        for identifier, service in (("brp-api", "brp"), ("kvk-api", "kvk"), ("bag-api", "bag"), ("pdok", "pdok"))
    ),
    Target("kiss", "brp", ("kiss", "settings", "haalCentraal", "baseUrl")),
    Target("kiss", "kvk", ("kiss", "settings", "kvk", "baseUrl")),
    Target("zac", "brp", ("zac", "brpApi", "url")),
    Target("zac", "bag", ("zac", "bagApi", "url")),
    Target("zac", "kvk", ("zac", "kvkApi", "url")),
)


def get(values: Any, path: str) -> Any:
    """The value at dotted `path`, None when a step is missing."""
    for key in path.split("."):
        if not isinstance(values, dict):
            return None
        values = values.get(key)
    return values


def _merge(base: Any, override: Any) -> Any:
    """Helm's merge of the env values over the chart defaults: maps deep, everything else replaced."""
    if not (isinstance(base, dict) and isinstance(override, dict)):
        return copy.deepcopy(override)
    merged = dict(base)
    for key, value in override.items():
        merged[key] = _merge(base.get(key), value) if key in base else copy.deepcopy(value)
    return merged


@functools.cache
def _chart_values(path: str) -> dict:
    return load_safe(Path(path).read_text(encoding="utf-8")) or {}


def _service_maps(data: Any) -> list[dict]:
    """Every mapping in a parsed configuration.data."""
    if isinstance(data, dict):
        return [data, *(m for v in data.values() for m in _service_maps(v))]
    if isinstance(data, list):
        return [m for v in data for m in _service_maps(v)]
    return []


def service_root(values: dict, app_key: str, identifier: str) -> str:
    """api_root of the zgw-consumers service `identifier` of an app, "" without it."""
    data = get(values, f"{app_key}.configuration.data")
    if not isinstance(data, str):
        return ""
    for mapping in _service_maps(load_safe(data)):
        if mapping.get("identifier") == identifier:
            return str(mapping.get("api_root") or "")
    return ""


def current_value(values: dict, target: Target) -> str:
    if target.identifier:
        return service_root(values, target.where[0], target.identifier)
    value = get(values, ".".join(target.where))
    return value if isinstance(value, str) else ""


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


def services(values: dict) -> tuple[dict[str, Service], list[str]]:
    """The services the gateway routes to, from the apiproxy locations and Open Formulieren's pdok."""
    found: dict[str, Service] = {}
    notes: list[str] = []
    locations = get(values, "apiproxy.locations") or {}
    client_cert = bool(get(values, "apiproxy.nginxCertsSecret"))

    def add(name: str, location: str, key_header: str, root: str) -> None:
        host = _host(root)
        if host == "api-proxy" or host.startswith("api-proxy."):
            notes.append(f"{name}: apiproxy targetUrl points back at api-proxy itself (a placeholder), no service")
            return
        settings = locations.get(location) or {}
        key = str(settings.get("apikey") or "") if key_header else ""
        found[name] = Service(
            name, root.rstrip("/") + "/", settings.get("hostHeader") or host, key_header, key, client_cert
        )

    if bag := get(locations, "bag.targetUrl"):
        add("bag", "bag", "X-Api-Key", bag)
    if brp := get(locations, "brp.targetUrl"):
        add("brp", "brp", "", brp)
    if kvk := get(locations, "kvkSearch.targetUrl"):
        # Every KVK client appends api/v2/zoeken, api/v1/basisprofielen, ...
        # to the root, so the root is the search URL without that tail.
        if match := re.match(r"^(.*/)api/v2/zoeken/?$", kvk):
            add("kvk", "kvkSearch", "apikey", match.group(1))
        else:
            notes.append(
                f"CHECK kvk: apiproxy.locations.kvkSearch.targetUrl {kvk} does not end in api/v2/zoeken: "
                "no kvk service; route KVK by hand"
            )
    if service_root(values, "openformulieren", "pdok").startswith(PDOK_ROOT):
        found["pdok"] = Service("pdok", PDOK_ROOT, _host(PDOK_ROOT), "", "", client_cert=False)
    return found, notes


def key_field(key: str, service: str) -> str:
    """The OpenBao field of an API key: the placeholder's name, lower case."""
    match = _PLACEHOLDER.match(key)
    return match.group(1).lower() if match else f"{service}_api_key"


def brp_headers(values: dict, application: str) -> tuple[dict[str, str], list[str]]:
    """KISS's fixed BRP headers with `application` as x-request-application; CHECK notes for what is skipped."""
    headers: dict[str, str] = {}
    notes: list[str] = []
    for name, value in (get(values, "kiss.settings.haalCentraal.customHeaders") or {}).items():
        if isinstance(value, dict | list):
            notes.append(
                f"CHECK kiss.settings.haalCentraal.customHeaders.{name} differs per request: "
                "the gateway cannot send it for Open Formulieren and Open Inwoner"
            )
            continue
        headers[str(name)] = application if name == APPLICATION_HEADER else str(value)
    return headers, notes


def application_name(values: dict, app: str, given: str | None) -> str:
    """x-request-application for an app: `given`, else KISS's with "kiss" replaced by the app."""
    if given:
        return given
    kiss = str(get(values, f"kiss.settings.haalCentraal.customHeaders.{APPLICATION_HEADER}") or "")
    return kiss.replace("kiss", app, 1) if "kiss" in kiss else ""


def route(app: str, service: Service, headers: dict[str, str], *, body_rewrite: bool) -> dict:
    """The APISIX route <app>-<service>: /<app>/<service>/* onto the service root."""
    match = _URL.match(service.root)
    if not match:
        msg = f"{app}-{service.name}: root {service.root} is not an http(s) URL"
        raise MigrationError(msg)
    scheme, host, port, path = match.groups()
    port = port or ("443" if scheme == "https" else "80")
    rewrite: dict[str, Any] = {"regex_uri": [f"^/{app}/{service.name}/(.*)", f"{path}$1"]}
    plugins: dict[str, Any] = {"proxy-rewrite": rewrite}
    upstream: dict[str, Any] = {
        "type": "roundrobin",
        "scheme": scheme,
        "pass_host": "rewrite",
        "upstream_host": service.host,
        "nodes": {f"{host}:{port}": 1},
    }
    if scheme == "https" and service.client_cert:
        upstream["tls"] = {"client_cert_id": f"client-{CLIENT_CERT}"}
    if service.key:
        function = (
            'local set_secret_header = require("openbao-secret-header") return set_secret_header({ '
            f'path = "frankgateway", field = "{key_field(service.key, service.name)}", '
            f'header = "{service.key_header}" }})'
        )
        plugins["serverless-pre-function"] = {"phase": "rewrite", "functions": [function]}
    if headers:
        rewrite["headers"] = {"set": headers}
    if body_rewrite:
        # nginx sub_filter: the upstream's absolute URLs in the body become the
        # gateway URL of this app. Compression off upstream, so the body is text.
        rewrite.setdefault("headers", {})["remove"] = ["Accept-Encoding"]
        plugins["response-rewrite"] = {
            "filters": [
                {
                    "regex": _REGEX_SPECIAL.sub(r"\\\1", service.root),
                    "scope": "global",
                    "replace": f"{GATEWAY}/{app}/{service.name}/",
                    "options": "jo",
                }
            ]
        }
    return {
        "uri": f"/{app}/{service.name}/*",
        "name": f"{app}-{service.name}",
        "labels": {"managed-by": "iac"},
        "plugins": plugins,
        "upstream": upstream,
    }


def _enabled(values: dict, app: str) -> bool:
    return get(values, f"{APP_KEYS[app]}.enabled") is not False


def routes(values: dict, args: argparse.Namespace) -> tuple[dict[str, dict], list[str]]:
    """One route per app setting in TARGETS whose app is enabled and whose service exists."""
    found, notes = services(values)
    body_rewrite = get(values, "apiproxy.locations.bag.urlRewrite.enabled") is True
    out: dict[str, dict] = {}
    for target in TARGETS:
        service = found.get(target.service)
        if not service or not current_value(values, target) or not _enabled(values, target.app):
            continue
        headers: dict[str, str] = {}
        if target.service == "brp":
            headers["x-api-key"] = args.brp_key
            if target.app in {"forms", "oip"}:
                application = application_name(values, target.app, getattr(args, f"{target.app}_application"))
                if application:
                    fixed, skipped = brp_headers(values, application)
                    headers.update(fixed)
                    notes += [n for n in skipped if n not in notes]
                else:
                    notes.append(
                        f"CHECK {target.route}: no --{target.app}-application and KISS has no {APPLICATION_HEADER} "
                        "with 'kiss' in it: no protocollering headers"
                    )
        out[target.route] = route(target.app, service, headers, body_rewrite=body_rewrite and target.service == "bag")
    return out, notes


def _images(values: dict, chart: dict, text: str) -> tuple[dict[str, Any], list[str]]:
    """The gateway image repositories on apiproxy's mirror registry; notes for the images to mirror."""
    repository = str(get(values, "apiproxy.image.repository") or "")
    mirror = repository.split("/", 1)[0]
    if "/" not in repository or "." not in mirror:
        return {}, []
    images: dict[str, Any] = {}
    notes: list[str] = []
    for path in ("image", "etcd.image", "seed.job.image"):
        source = str(get(chart, f"frankgateway.{path}.repository") or "")
        first, _, rest = source.partition("/")
        mirrored = f"{mirror}/{rest if rest and '.' in first else source}"
        node = images
        for key in path.split("."):
            node = node.setdefault(key, {})
        node["repository"] = mirrored
        if not re.search(rf"{re.escape(mirrored)}[\"' ]*$", text, re.MULTILINE):
            tag = str(get(chart, f"frankgateway.{path}.tag") or "").split("@")[0]
            notes.append(f"CHECK image {mirrored}:{tag} must be mirrored before this deploy")
    return images, notes


def frankgateway_block(values: dict, chart: dict, text: str, args: argparse.Namespace) -> tuple[dict, list[str]]:
    """The `frankgateway:` values of phase 1, and its notes."""
    outway_routes, notes = routes(values, args)
    if not outway_routes:
        msg = "no app uses a service the gateway can route: nothing to migrate"
        raise MigrationError(msg)
    outway: dict[str, Any] = {"enabled": True}
    certs = get(values, "apiproxy.nginxCertsSecret")
    found, _ = services(values)
    if certs:
        outway["clientCertificates"] = {CLIENT_CERT: {"openbaoPath": f"frankgateway/client-certs/{CLIENT_CERT}"}}
        notes.append(
            f"OPENBAO <mount>/frankgateway/client-certs/{CLIENT_CERT} cert=<client.crt + chain> key=<client.key> "
            f"<- Secret {certs}"
        )
        if "caBundleSecretRef" in (get(chart, "frankgateway.upstreamTls") or {}):
            outway["upstreamTls"] = {"caBundleSecretRef": {"name": certs, "key": "ca.crt"}}
        else:
            notes.append(
                f"CHECK nginx trusts ca.crt from Secret {certs}; this chart cannot add it to the gateway "
                "(upstreamTls.caBundleSecretRef, 4.10.2): an upstream under a private CA fails verification"
            )
    for service in found.values():
        if service.key:
            literal = "" if _PLACEHOLDER.match(service.key) else " (a LITERAL in this file: remove it from git)"
            notes.append(
                f"OPENBAO <mount>/frankgateway field {key_field(service.key, service.name)} <- {service.key}"
                f"{literal} ({service.name}, header {service.key_header})"
            )
    outway["routes"] = outway_routes
    block: dict[str, Any] = {"enabled": True}
    images, image_notes = _images(values, chart, text)
    block.update(images)
    if node_selector := get(values, "apiproxy.nodeSelector"):
        # Run where apiproxy runs: every gateway workload.
        block["nodeSelector"] = node_selector
        for path in ("etcd", "seed.job", "clientCertSync"):
            node = block
            for key in path.split("."):
                node = node.setdefault(key, {})
            node["nodeSelector"] = copy.deepcopy(node_selector)
    block["instances"] = {"inway": {"enabled": False}, "internal": {"enabled": False}, "outway": outway}
    notes += image_notes + _not_routed(values)
    return block, notes


def _not_routed(values: dict) -> list[str]:
    notes = []
    if get(values, "zac.smartDocuments.url"):
        notes.append("zac.smartDocuments.url not routed: ZAC also builds the browser's wizard redirect from it")
    notes.extend(
        f"{app_key} vng-selectielijst not routed: its URLs are stored in Open Zaak, so it keeps its api_root"
        for app_key in ("openarchiefbeheer", "openformulieren", "openinwoner")
        if service_root(values, app_key, "vng-selectielijst")
    )
    return notes


def _quoted(node: Any) -> Any:
    """A copy with every string that YAML would read differently, and every placeholder, double-quoted."""
    if isinstance(node, dict):
        return {k: _quoted(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_quoted(v) for v in node]
    if isinstance(node, str) and ("REP_" in node or load_safe(f"k: {node}") != {"k": node}):
        return DoubleQuotedScalarString(node)
    return node


def dump(values: dict) -> str:
    yaml = rt_yaml(width=4096)
    yaml.indent(mapping=2, sequence=4, offset=2)
    stream = io.StringIO()
    yaml.dump(_quoted(values), stream)
    return stream.getvalue()


def _check(new: str, want: dict) -> None:
    if _parsed(load_safe(new)) != _parsed(want):
        msg = "self-check failed: the edited file does not match the intended values; nothing written"
        raise MigrationError(msg)


def _parsed(doc: dict) -> dict:
    """`doc` with every app's configuration.data parsed, so data edits compare as values."""
    out = copy.deepcopy(doc)
    for value in out.values():
        data = get(value, "configuration.data")
        if isinstance(data, str):
            value["configuration"]["data"] = load_safe(data)
    return out


def phase1(text: str, doc: dict, values: dict, args: argparse.Namespace) -> tuple[str, list[str]]:
    if "frankgateway" in doc:
        # Done before, or set by hand: phase 2 changes what phase 1 would add
        # (Open Formulieren's pdok root), so the block is never compared.
        return text, []
    chart = _chart_values(args.chart_values)
    block, notes = frankgateway_block(values, chart, text, args)
    added = dump({"frankgateway": block})
    want = load_safe(added)["frankgateway"]
    new = text.rstrip("\n") + "\n\n# Frank!Gateway outway, replaces apiproxy (migrate-apiproxy-to-frankgateway.py).\n"
    new += added
    _check(new, {**doc, "frankgateway": want})
    return new, notes


def _value_position(rt: Any, lines: list[str], target: Target) -> tuple[int, int]:
    """(line, column) in the file of the value of `target`."""
    if not target.identifier:
        parent = rt
        for key in target.where[:-1]:
            parent = parent[key]
        return parent.lc.value(target.where[-1])
    configuration = rt[target.where[0]]["configuration"]
    start, _, indent = literal_block(lines, configuration, "data", f"{target.where[0]}.configuration.data")
    for mapping in _rt_maps(load_rt(str(configuration["data"]))):
        if mapping.get("identifier") == target.identifier:
            line, column = mapping.lc.value("api_root")
            return start + line, indent + column
    msg = f"{target.path}: not found"
    raise MigrationError(msg)


def _rt_maps(node: Any) -> list[Any]:
    if isinstance(node, dict):
        return [node, *(m for v in node.values() for m in _rt_maps(v))]
    if isinstance(node, list):
        return [m for v in node for m in _rt_maps(v)]
    return []


def _set(doc: dict, target: Target, value: str) -> None:
    """Set `target` in the parsed `doc`; configuration.data is parsed in place."""
    if not target.identifier:
        parent = doc
        for key in target.where[:-1]:
            parent = parent[key]
        parent[target.where[-1]] = value
        return
    configuration = doc[target.where[0]]["configuration"]
    if isinstance(configuration["data"], str):
        configuration["data"] = load_safe(configuration["data"])
    for mapping in _service_maps(configuration["data"]):
        if mapping.get("identifier") == target.identifier:
            mapping["api_root"] = value


def _replace(lines: list[str], position: tuple[int, int], old: str, new: str) -> None:
    line, column = position
    at = lines[line].find(old, column)
    if at < 0:
        msg = f"line {line + 1} does not hold {old}: change it by hand"
        raise MigrationError(msg)
    lines[line] = lines[line][:at] + new + lines[line][at + len(old) :]


def phase2(text: str, doc: dict, values: dict) -> tuple[str, list[str]]:
    configured = get(doc, "frankgateway.instances.outway.routes") or {}
    if not configured:
        msg = "no frankgateway outway routes in this file: run --phase 1 first"
        raise MigrationError(msg)
    lines = text.splitlines(keepends=True)
    rt = load_rt(text)
    want = _parsed(doc)
    notes: list[str] = []
    for target in TARGETS:
        if target.route not in configured:
            continue
        current = current_value(doc, target)
        if not current:
            notes.append(f"CHECK {target.path} is not set in this file: set it to {target.new_url('')} by hand")
            continue
        if current.startswith(GATEWAY):
            continue
        new_url = target.new_url(current)
        _replace(lines, _value_position(rt, lines, target), current, new_url)
        _set(want, target, new_url)
        notes.append(f"{target.path}: {current} -> {new_url}")
        notes += _phase2_notes(values, target, current)
    new = "".join(lines)
    if new != text:
        _check(new, want)
    return new, notes


def _phase2_notes(values: dict, target: Target, current: str) -> list[str]:
    if target.app == "kiss" and target.service == "kvk" and current.rstrip("/").endswith("/api/v2/zoeken"):
        return [f"{target.path} ended in /api/v2/zoeken, so KISS called .../v2/zoeken/v2/zoeken: fixed"]
    if target.app == "zac" and "api-proxy" not in current:
        found, _ = services(values)
        root = found[target.service].root.rstrip("/") if target.service in found else ""
        if root and current.rstrip("/") != root:
            return [f"CHECK {target.path} called {current}; through the gateway it reaches {root} (from apiproxy)"]
    return []


def _api_proxy_users(doc: dict) -> list[str]:
    """Every value outside apiproxy that still points at api-proxy."""
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str) and re.search(r"//api-proxy[.:/]", node):
            found.append(path)

    walk({k: v for k, v in doc.items() if k != "apiproxy"}, "")
    return found


def phase3(text: str, doc: dict) -> tuple[str, list[str]]:
    if get(doc, "apiproxy.enabled") is not True:
        return text, []
    if not get(doc, "frankgateway.instances.outway.routes"):
        msg = "no frankgateway outway routes in this file: run --phase 1 and 2 first"
        raise MigrationError(msg)
    if users := _api_proxy_users(doc):
        msg = f"still pointing at api-proxy: {', '.join(users)}; run --phase 2 or change them by hand"
        raise MigrationError(msg)
    lines = text.splitlines(keepends=True)
    _replace(lines, load_rt(text)["apiproxy"].lc.value("enabled"), "true", "false")
    new = "".join(lines)
    want = copy.deepcopy(doc)
    want["apiproxy"]["enabled"] = False
    _check(new, want)
    return new, ["apiproxy.enabled: true -> false"]


def migrate_text(text: str, args: argparse.Namespace) -> tuple[str, list[str]]:
    doc = load_safe(text)
    if not isinstance(doc, dict):
        msg = "not a YAML mapping"
        raise MigrationError(msg)
    if args.phase == PHASE_OFF:
        return phase3(text, doc)
    values = _merge(_chart_values(args.chart_values), doc)
    if get(values, "apiproxy.enabled") is not True and "frankgateway" not in doc:
        return text, []
    if args.phase == PHASE_GATEWAY:
        return phase1(text, doc, values, args)
    return phase2(text, doc, values)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--phase",
        type=int,
        choices=(PHASE_GATEWAY, PHASE_APPS, PHASE_OFF),
        required=True,
        help="the phase to apply (see above)",
    )
    parser.add_argument(
        "--chart-values", default=str(CHART_VALUES), help="chart defaults (default: the chart of this checkout)"
    )
    parser.add_argument(
        "--forms-application", help="x-request-application for Open Formulieren (default: KISS's, kiss -> forms)"
    )
    parser.add_argument(
        "--oip-application", help="x-request-application for Open Inwoner (default: KISS's, kiss -> oip)"
    )
    parser.add_argument("--brp-key", default=BRP_KEY, help=f"x-api-key on every BRP route (default: {BRP_KEY})")


if __name__ == "__main__":
    sys.exit(run(__doc__, migrate_text, add_arguments=add_arguments))
