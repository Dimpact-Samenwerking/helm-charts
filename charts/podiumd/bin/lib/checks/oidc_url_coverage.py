"""Verify each Keycloak client's `.Values` redirect URI paths are in `$oidcClients`.

In templates/keycloak-podiumd-realm-config.yaml, `$oidcClients` feeds a render-time
guard that fails on an empty or example.nl oidcUrl. A client missing from it renders
example.nl redirect URIs silently and every login fails with "Invalid parameter:
redirect_uri".

Raw text scan (Go templating breaks a YAML parser): blocks split on `- clientId:`,
then each `redirectUris:` item is read. Items without a `.Values` path (range
variables, literals) can't be mapped and are informational only. `webOrigins:` isn't
checked: it mirrors redirectUris and a wrong origin alone doesn't break login.
"""

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
    return {entry_match.group("path") for entry_match in OIDC_URL_ENTRY_RE.finditer(list_m.group("body"))}


# (clientId, 1-based line, block lines) of one `- clientId:` item.
type ClientBlock = tuple[str, int, list[str]]
# (clientId, 1-based line, ".Values" path or raw redirect URI item).
type ClientItem = tuple[str, int, str]


def _client_blocks(lines: list[str]) -> list[ClientBlock]:
    """[(clientId text, 1-based line, block lines)] per `- clientId:` item, up to the next one.

    The last block runs to end of file; harmless since only redirectUris: items are read.
    """
    matches = [(index, CLIENT_ITEM_RE.match(line)) for index, line in enumerate(lines)]
    starts = [(index, client_match.group("id").strip("\"'")) for index, client_match in matches if client_match]
    ends = [*(start for start, _client_id in starts[1:]), len(lines)]
    spans = zip(starts, ends, strict=True)
    return [(client_id, start + 1, lines[start:end]) for (start, client_id), end in spans]


def _redirect_uri_items(block: list[str]) -> list[str]:
    """Every item under every `redirectUris:` key in one client block, in order.

    Items may sit deeper than or at the key's indent. Blank, `#` and template-only
    control lines are skipped; any other line ends the list.
    """
    items: list[str] = []
    index = 0
    while index < len(block):
        key_m = REDIRECT_URIS_KEY_RE.match(block[index])
        index += 1
        if key_m is not None:
            key_items, index = _list_items_from(block, index, len(key_m.group("indent")))
            items.extend(key_items)
    return items


def _list_items_from(block: list[str], index: int, key_indent: int) -> tuple[list[str], int]:
    """(items, index after them) of the list starting at block[index] under a key at `key_indent`."""
    items: list[str] = []
    for offset, line in enumerate(block[index:]):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "{{")):
            continue
        item_m = LIST_ITEM_RE.match(line)
        if item_m is None or len(item_m.group("indent")) < key_indent:
            return items, index + offset
        items.append(item_m.group("value"))
    return items, len(block)


def scan_oidc_url_coverage(text: str) -> tuple[list[ClientItem], list[ClientItem]] | None:
    """(uncovered, unmapped) for the template text, or None without an `$oidcClients` list.

    uncovered: (clientId, line, ".Values.<path>") not listed as any "oidcUrl".
    unmapped: (clientId, line, raw item) with no `.Values` path (informational).
    """
    covered = oidc_client_url_paths(text)
    if covered is None:
        return None
    uncovered: list[ClientItem] = []
    unmapped: list[ClientItem] = []
    for client_id, line_no, block in _client_blocks(text.splitlines()):
        for item in _redirect_uri_items(block):
            paths = [path_match.group("path") for path_match in VALUES_PATH_RE.finditer(item)]
            if not paths:
                unmapped.append((client_id, line_no, item))
            uncovered.extend((client_id, line_no, path) for path in paths if path not in covered)
    return uncovered, unmapped


def check_oidc_url_coverage(chart_dir: Path) -> tuple[bool, str]:
    """Fail on uncovered redirect URI paths, or when the template or `$oidcClients` is missing.

    Points at fix-oidc-url-coverage. Unmapped items are printed as notes only.
    """
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
    print("Run fix-oidc-url-coverage to add the missing $oidcClients entries.")
    return False, f"{len(uncovered)} uncovered — run fix-oidc-url-coverage to fix"
