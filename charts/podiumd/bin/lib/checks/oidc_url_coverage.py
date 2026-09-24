"""Verifies every Keycloak client in templates/keycloak-podiumd-realm-
config.yaml that builds its `redirectUris:` from a `.Values.<path>` has
that same path listed as the "oidcUrl" of some `$oidcClients` entry at
the top of that file. That list feeds the template's own render-time
guard (a `range` that `fail`s when an enabled entry's oidcUrl is empty
or still the example.nl placeholder), so a client whose redirect-URI
value is missing from it renders example.nl redirect URIs silently: the
deploy succeeds and every login then fails with "Invalid parameter:
redirect_uri". helm-charts PR #461's review found exactly that gap
(kiss, zac, ita, pabc, monitoring, datamigratie, zaakbrug had no
entry); PR #490 closed it, and this check stops it from coming back
when a new client is added.

Scans the raw template source (not a `helm template` render) — Go
template syntax breaks a real YAML parser (see lib.checks.node_selector),
so this is a best-effort textual scan: the file is split into client
blocks on its `- clientId:` list items, and each `redirectUris:` key's
own list items inside a block are read line by line. Every
`.Values.<path>` (or `$.Values.<path>`) inside such an item must be
covered. An item with no `.Values` path at all — a `range` variable like
the frankgateway dashboard clients' `$fgInst.dashboard.auth.hostname`,
or a plain literal like OpenBao's `http://localhost:8250/*` CLI callback
— can't be mapped statically, so it's reported as informational only,
never a failure. `webOrigins:` is deliberately not checked: it's built
from the same value as `redirectUris:` in every client, and a wrong
web origin alone doesn't break a login. A client with no `redirectUris:`
at all (a service-account-only client) is ignored."""

import re

from pathlib import Path

REALM_CONFIG_TEMPLATE = Path("templates") / "keycloak-podiumd-realm-config.yaml"

OIDC_CLIENTS_LIST_RE = re.compile(r"\$oidcClients\s*:=\s*list\b(?P<body>.*?)\}\}", re.DOTALL)
OIDC_URL_ENTRY_RE = re.compile(r'"oidcUrl"\s+\$?(?P<path>\.Values(?:\.[\w-]+)+)')
CLIENT_ITEM_RE = re.compile(r"^\s*-\s+clientId:\s*(?P<id>.*?)\s*$")
REDIRECT_URIS_KEY_RE = re.compile(r"^(?P<indent>\s*)redirectUris:\s*$")
LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<value>.*?)\s*$")
VALUES_PATH_RE = re.compile(r"\$?(?P<path>\.Values(?:\.[\w-]+)+)")


def oidc_client_url_paths(text: str) -> set[str] | None:
    """{".Values.<path>", ...} for every `"oidcUrl" .Values.<path>` in
    the template's `$oidcClients := list ...` assignment, or None when
    that assignment isn't in the text at all."""
    list_m = OIDC_CLIENTS_LIST_RE.search(text)
    if list_m is None:
        return None
    return {m.group("path") for m in OIDC_URL_ENTRY_RE.finditer(list_m.group("body"))}


def _client_blocks(lines: list[str]) -> list[tuple[str, int, list[str]]]:
    """[(clientId text, 1-based line number, block lines), ...] — one per
    `- clientId:` list item, each running up to the next one (or the end
    of the file; only redirectUris: items are read from a block, so any
    unrelated trailing content the last block picks up is harmless)."""
    starts = [(i, m.group("id").strip("\"'")) for i, line in enumerate(lines) if (m := CLIENT_ITEM_RE.match(line))]
    return [
        (client_id, start + 1, lines[start : starts[n + 1][0] if n + 1 < len(starts) else len(lines)])
        for n, (start, client_id) in enumerate(starts)
    ]


def _redirect_uri_items(block: list[str]) -> list[str]:
    """Every list item under every `redirectUris:` key in one client
    block, in order. Items may be indented deeper than the key or sit at
    the key's own indent (both valid YAML); blank lines, `#` comments and
    template-only control lines (`{{- if ... }}`) between items are
    skipped; the first other line ends the list."""
    items: list[str] = []
    i = 0
    while i < len(block):
        key_m = REDIRECT_URIS_KEY_RE.match(block[i])
        i += 1
        if key_m is None:
            continue
        key_indent = len(key_m.group("indent"))
        while i < len(block):
            line = block[i]
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "{{")):
                i += 1
                continue
            item_m = LIST_ITEM_RE.match(line)
            if item_m is None or len(item_m.group("indent")) < key_indent:
                break
            items.append(item_m.group("value"))
            i += 1
    return items


def scan_oidc_url_coverage(
    text: str,
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]] | None:
    """(uncovered, unmapped) for a realm-config template's text, or None
    when it has no `$oidcClients` list (see oidc_client_url_paths).
    uncovered: (clientId, line, ".Values.<path>") for every redirect URI
    `.Values` path no `$oidcClients` entry lists as its "oidcUrl".
    unmapped: (clientId, line, raw item) for every redirect URI with no
    `.Values` path at all (informational — see module docstring)."""
    covered = oidc_client_url_paths(text)
    if covered is None:
        return None
    uncovered: list[tuple[str, int, str]] = []
    unmapped: list[tuple[str, int, str]] = []
    for client_id, line_no, block in _client_blocks(text.splitlines()):
        for item in _redirect_uri_items(block):
            paths = [m.group("path") for m in VALUES_PATH_RE.finditer(item)]
            if not paths:
                unmapped.append((client_id, line_no, item))
            uncovered.extend((client_id, line_no, path) for path in paths if path not in covered)
    return uncovered, unmapped


def check_oidc_url_coverage(chart_dir: Path) -> tuple[bool, str]:
    """Fails if any Keycloak client in the realm-config template builds a
    redirect URI from a `.Values` path with no `$oidcClients` entry (see
    module docstring), printing each clientId and uncovered path. Also
    fails, clearly, when the template or its `$oidcClients` list is
    missing — this check's whole premise is gone then, and passing
    silently would hide that. Redirect URIs with no `.Values` path are
    printed as informational notes, never a failure."""
    template = chart_dir / REALM_CONFIG_TEMPLATE
    if not template.is_file():
        print(f"FAIL: {REALM_CONFIG_TEMPLATE} not found — cannot check its Keycloak clients' redirectUris")
        return False, "realm config template missing"

    result = scan_oidc_url_coverage(template.read_text(encoding="utf-8"))
    if result is None:
        print(f"FAIL: no `$oidcClients := list ...` assignment found in {REALM_CONFIG_TEMPLATE}")
        return False, "$oidcClients list missing"
    uncovered, unmapped = result

    for client_id, line_no, item in unmapped:
        print(
            f"  note: {REALM_CONFIG_TEMPLATE}:{line_no}  clientId {client_id}: redirect URI {item} (not a .Values path)"
        )

    if not uncovered:
        print("OK: every Keycloak client redirect URI built from .Values has a matching $oidcClients oidcUrl entry")
        return True, f"0 uncovered, {len(unmapped)} unmapped (informational)"

    print(
        f"Found {len(uncovered)} Keycloak client redirect URI value(s) with no matching $oidcClients "
        f'"oidcUrl" entry in {REALM_CONFIG_TEMPLATE} (would render example.nl redirect URIs silently):'
    )
    for client_id, line_no, path in uncovered:
        print(f"  {REALM_CONFIG_TEMPLATE}:{line_no}  clientId {client_id}: {path}")
    return False, f"{len(uncovered)} uncovered"
