#!/usr/bin/env python3
"""Convert PodiumD image references to the strip-registry mirror convention.

New mirror-naming convention
----------------------------
The ACR mirror repo name is the upstream image reference with **only the
registry host stripped** — the full `<namespace>/<repo>` path of the original
is kept verbatim. No drop-namespace / drop-hyphen / Dutch-rename translation.

    quay.io/keycloak/keycloak          -> keycloak/keycloak
    docker.io/maykinmedia/open-inwoner -> maykinmedia/open-inwoner
    ghcr.io/infonl/zaakafhandelcomponent -> infonl/zaakafhandelcomponent
    docker.io/library/redis            -> library/redis

So the mirrored image is `<global.imageRegistry>/<namespace>/<repo>:<tag>`,
e.g. `acrprodmgmt.azurecr.io/maykinmedia/open-inwoner:2.3.0`.

This replaces the hand-maintained translation table in
`docs/images/acr-mirror-naming.md`. The rule is mechanical: for any NEW image
just call `strip_registry(upstream_url)` — nothing to look up.

Two things this script does
---------------------------
1. `--gen-manifest` : print an images-manifest block (`name:` / `url:`) for every
   known image, with `name = strip_registry(url)`. Source of truth for the new
   ACR repo names.
2. (default) `rewrite <values.yaml>` : migrate a gemeente values file from the
   LEGACY translated ACR names to the new stripped-upstream names. Handles the
   three shapes used in podiumd.yml:
     - inline   `repository: <registry>/<legacyname>`
     - inline   `imageName:  <registry>/<legacyname>`
     - split    `registry: <registry>` + `repository: <legacyname>`
   Use `--dry-run` (default) to print a unified diff; `--in-place` to write.

LEGACY_UPSTREAM below is one-time migration data (legacy ACR name -> canonical
upstream url). It exists only to translate files written under the OLD scheme;
it is NOT maintained for new images and can be deleted once every environment
has been migrated. Entries marked `# best-guess` were uncertain in the old
table — verify the upstream before trusting the mirrored pull.
"""
from __future__ import annotations

import argparse
import difflib
import glob
import os
import re
import sys

# Legacy ACR mirror name  ->  canonical upstream url (no tag).
# Reconstructed from docs/images/acr-mirror-naming.md (+ chart values.yaml).
LEGACY_UPSTREAM: dict[str, str] = {
    "apisix": "docker.io/apache/apisix",
    "busybox": "docker.io/library/busybox",
    "clamav": "docker.io/clamav/clamav",
    "clamav_exporter": "docker.io/clamav/clamav-prometheus-exporter",  # best-guess
    "contact-adapter": "ghcr.io/info-nl/contact-adapter",  # best-guess
    "contact-frontend": "ghcr.io/info-nl/contact-frontend",  # best-guess
    "contact-sync": "ghcr.io/info-nl/contact-sync",  # best-guess
    "curl": "docker.io/curlimages/curl",
    "eck-operator": "docker.io/elastic/eck-operator",
    "elasticsearch/elasticsearch": "docker.io/elastic/elasticsearch",
    "enterprise-search/enterprise-search": "docker.io/elastic/enterprise-search",
    "etcd": "gcr.io/etcd-development/etcd",
    "gotenberg": "docker.io/gotenberg/gotenberg",
    "infinispan-init": "docker.io/redhat/ubi8-micro",  # best-guess
    "infinispan-server": "docker.io/infinispan/server",
    "internetaakafhandeling.poller": "ghcr.io/interne-taak-afhandeling/internetaakafhandeling.poller",
    "internetaakafhandeling.web": "ghcr.io/interne-taak-afhandeling/internetaakafhandeling.web",
    "k8s": "docker.io/alpine/k8s",
    "k8s-kubectl": "docker.io/lachlanevenson/k8s-kubectl",
    "k8s-wait-for": "docker.io/groundnuty/k8s-wait-for",
    "keycloak": "quay.io/keycloak/keycloak",
    "keycloak-config-cli": "quay.io/keycloak/keycloak-config-cli",  # best-guess
    "keycloak-operator": "quay.io/keycloak/keycloak-operator",
    "kibana/kibana": "docker.io/elastic/kibana",
    "nginx-unprivileged": "docker.io/nginxinc/nginx-unprivileged",
    "nginx": "docker.io/library/nginx",
    "objecten": "docker.io/maykinmedia/objecten-api",
    "objecttypen": "docker.io/maykinmedia/objecttypes-api",
    "oauth2-proxy": "quay.io/oauth2-proxy/oauth2-proxy",
    "opa": "docker.io/openpolicyagent/opa",
    "omc": "docker.io/worthnl/notifynl-omc",
    "open-beheer": "docker.io/maykinmedia/open-beheer",
    "openarchiefbeheer": "docker.io/maykinmedia/open-archiefbeheer",
    "openformulieren": "docker.io/openformulieren/open-forms",
    "openinwoner": "docker.io/maykinmedia/open-inwoner",
    "openklant": "docker.io/maykinmedia/open-klant",
    "opennotificaties": "docker.io/maykinmedia/open-notificaties",
    "openzaak": "docker.io/openzaak/open-zaak",
    "opentelemetry-collector-contrib": "ghcr.io/open-telemetry/opentelemetry-collector-contrib",
    "pabc-api": "ghcr.io/info-nl/pabc-api",  # best-guess
    "pabc-migrations": "ghcr.io/info-nl/pabc-migrations",  # best-guess
    "personen-mock": "docker.io/brpapi/personen-mock",  # best-guess
    "rabbitmq": "docker.io/bitnami/rabbitmq",
    "redis": "docker.io/library/redis",
    "redis-exporter": "docker.io/oliver006/redis_exporter",
    "redis-operator": "docker.io/spotahome/redis-operator",
    "referentielijsten-api": "docker.io/maykinmedia/referentielijsten-api",
    "solr": "docker.io/library/solr",
    "solr-operator": "docker.io/apache/solr-operator",
    "zac": "ghcr.io/infonl/zaakafhandelcomponent",
    "zgw-office-add-in-backend": "ghcr.io/infonl/zgw-office-add-in-backend",
    "zgw-office-add-in-frontend": "ghcr.io/infonl/zgw-office-add-in-frontend",
    "python": "docker.io/library/python",
    "postgres": "docker.io/library/postgres",
    "alpine": "docker.io/library/alpine",
    "zookeeper": "docker.io/pravega/zookeeper",
    "zookeeper-operator": "docker.io/pravega/zookeeper-operator",
}

DEFAULT_REGISTRY = "acrprodmgmt.azurecr.io"


def strip_registry(url: str) -> str:
    """Drop the leading registry host from an image url, keep the rest.

    A first path segment is treated as a registry host when it contains a '.'
    or ':' (docker.io, quay.io, ghcr.io, gcr.io, host:port, ...) or is
    'localhost'. Everything else (e.g. 'library/redis') is returned unchanged.
    """
    url = url.strip().split("@", 1)[0]  # drop any digest
    head, _, rest = url.partition("/")
    if rest and ("." in head or ":" in head or head == "localhost"):
        return rest
    return url


def legacy_to_new() -> dict[str, str]:
    """legacy ACR name -> new stripped-upstream ACR name."""
    return {name: strip_registry(url) for name, url in LEGACY_UPSTREAM.items()}


def rewrite_text(text: str, registry: str) -> tuple[str, list[tuple[str, str]]]:
    """Rewrite legacy ACR refs to the new convention. Returns (text, changes)."""
    mapping = legacy_to_new()
    changes: list[tuple[str, str]] = []
    # Longest legacy names first so 'keycloak' can't clobber 'keycloak-operator'.
    names = sorted(mapping, key=len, reverse=True)

    for name in names:
        new = mapping[name]
        if new == name:
            continue
        esc = re.escape(name)

        # 1) inline:  <registry>/<name>   (repository:/imageName:/quoted)
        # Trailing boundary must NOT include '/': a legacy ACR ref is a single
        # path segment ending at a quote/space/EOL. Allowing '/' would let a
        # short name (keycloak) re-match the prefix of an already-rewritten
        # path (keycloak/keycloak-operator) -> double segment.
        inline = re.compile(rf"({re.escape(registry)}/){esc}(?=[\"'\s]|$)")
        text, n1 = inline.subn(rf"\g<1>{new}", text)

        # 2) split:   repository: <name>   (bare value, registry on a sibling key)
        split = re.compile(
            rf"(^\s*repository:\s*[\"']?){esc}([\"']?\s*(?:#.*)?)$",
            re.MULTILINE,
        )
        text, n2 = split.subn(rf"\g<1>{new}\g<2>", text)

        if n1 or n2:
            changes.append((name, new))
    return text, changes


def _parse_manifest(path: str) -> list[dict[str, str]]:
    """Minimal parser for an images-*.yaml list of {name,url,version,digest}."""
    entries: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            s = raw.strip()
            if s.startswith("- name:"):
                if cur.get("url"):
                    entries.append(cur)
                cur = {"name": s[len("- name:"):].strip()}
            elif s.startswith("url:"):
                cur["url"] = s[len("url:"):].strip()
            elif s.startswith("version:"):
                cur["version"] = s[len("version:"):].strip()
            elif s.startswith("digest:"):
                cur["digest"] = s[len("digest:"):].strip()
    if cur.get("url"):
        entries.append(cur)
    return entries


def cmd_gen_manifest() -> None:
    """Aggregate every per-release images-*.yaml into one manifest with the
    new stripped-registry names, carrying the latest pinned version + digest."""
    images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "images")
    files = sorted(
        f for f in glob.glob(os.path.join(images_dir, "images-*.yaml"))
        if os.path.basename(f) != "images-mirror-stripped.yaml"
    )
    by_url: dict[str, dict[str, str]] = {}  # url -> entry; later (newer) file wins
    for f in files:
        for e in _parse_manifest(f):
            by_url[e["url"]] = e

    print("# Images manifest - strip-registry mirror convention.")
    print("# name = upstream url with the registry host stripped (full path kept).")
    print("# Aggregated from every docs/images/images-*.yaml (latest pin per image).")
    print("# Generated by scripts/mirror-strip-registry.py --gen-manifest")
    print()
    for url in sorted(by_url, key=strip_registry):
        e = by_url[url]
        print(f"- name: {strip_registry(url)}")
        print(f"  url: {url}")
        if e.get("version"):
            print(f"  version: {e['version']}")
        if e.get("digest"):
            print(f"  digest: {e['digest']}")


def cmd_rewrite(path: str, registry: str, in_place: bool) -> int:
    with open(path, encoding="utf-8") as fh:
        original = fh.read()
    new_text, changes = rewrite_text(original, registry)

    if not changes:
        print(f"No legacy ACR references found in {path}", file=sys.stderr)
        return 0

    if in_place:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_text)
        print(f"Rewrote {path} ({len(changes)} image names converted).", file=sys.stderr)
    else:
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"{path} (legacy)",
            tofile=f"{path} (strip-registry)",
        )
        sys.stdout.writelines(diff)
    print(
        "\nConverted names:\n  "
        + "\n  ".join(f"{o} -> {registry}/{n}" for o, n in sorted(changes)),
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("values", nargs="?", help="gemeente values file to rewrite (e.g. podiumd.yml)")
    p.add_argument("--registry", default=DEFAULT_REGISTRY, help=f"ACR registry host (default {DEFAULT_REGISTRY})")
    p.add_argument("--in-place", action="store_true", help="write changes back to the file (default: print diff)")
    p.add_argument("--gen-manifest", action="store_true", help="print an images manifest with the new mirror names and exit")
    args = p.parse_args(argv)

    if args.gen_manifest:
        cmd_gen_manifest()
        return 0
    if not args.values:
        p.error("a values file is required (or use --gen-manifest)")
    return cmd_rewrite(args.values, args.registry, args.in_place)


if __name__ == "__main__":
    raise SystemExit(main())
