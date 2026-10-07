#!/usr/bin/env python3
"""openbao-keycloak-setup.py — configure OpenBao's Keycloak client, role and group.

Puts the `openbao` client, its `uploaders` client role and the
`vault-uploaders` group (with that role) into the realm, and optionally adds
members to the group. Run it before the deploy that enables OpenBao, so
everything OpenBao needs in Keycloak is in place, also when the realm import
runs with keycloak.config.skipRoles/skipGroups (the default), which never
creates the role and the group.

Single source of truth: the definitions are not written here. The script
renders the chart's own realm import (templates/keycloak-podiumd-realm-config.yaml)
with the environment's values and takes the `openbao` client, the role and the
group from it, so names, redirect URIs and mappers always match what the
deploy imports.

Idempotent: it creates what is missing and updates what differs; run it as
often as you like. --check only reports.

The client secret: when Secret keycloak-podiumd-realm-secrets (key
openbao-oidc-secret) already exists, that value is used. On a first install
it doesn't exist yet; Keycloak then generates one, and the deploy's realm
import replaces it with the chart's secret, which the openbao-config Job
uses too.

Usage:
  KEYCLOAK_URL=https://<keycloak admin host> \\
  ./openbao-keycloak-setup.py --release podiumd --chart <chart> -n podiumd \\
      -f values.yaml -f <env-values>.yaml [--members alice,bob] [--check]

  ./openbao-keycloak-setup.py --realm-config <rendered realm-config.yaml> ...

Options:
  --chart CHART            chart to render (path or repo/name); with -f/--set
  --release NAME           Helm release name (default: podiumd)
  -n, --namespace NS       namespace (default: podiumd)
  -f, --values FILE        values file, repeatable, same order as the deploy
  --set KEY=VALUE          extra --set for the render, repeatable
  --version VERSION        chart version, when --chart is a repo chart
  --realm-config FILE      use an already rendered realm ConfigMap instead
  --members USERS          comma-separated usernames to add to the group
  --check                  report only; exit 1 when something is missing or differs

Environment:
  KEYCLOAK_URL             required: Keycloak base URL of the admin API
  KEYCLOAK_ADMIN_USER      master-realm admin user (default: admin)
  KEYCLOAK_ADMIN_PASSWORD  its password; when unset and KUBE_CONTEXT is set,
                           read from Secret keycloak-podiumd-admin (keys
                           username/password) in NAMESPACE; otherwise prompted
  KUBE_CONTEXT             kube-context for reading Secrets (optional)

Requires: python3 with PyYAML, helm (unless --realm-config), kubectl (only
with KUBE_CONTEXT).
"""

import argparse
import base64
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

CLIENT_ID = "openbao"


def die(msg):
    print(f"    FAIL  {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg):
    print(f"    OK    {msg}")


def change(msg):
    print(f"    SET   {msg}")


def kubectl_secret(context, namespace, name, key):
    try:
        out = subprocess.run(
            ["kubectl", "--context", context, "-n", namespace, "get", "secret", name,
             "-o", f"jsonpath={{.data.{key}}}"],
            check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError:
        return ""
    return base64.b64decode(out).decode() if out else ""


def render_realm(args):
    if args.realm_config:
        with open(args.realm_config, encoding="utf-8") as fh:
            text = fh.read()
    else:
        if not args.chart:
            die("--chart or --realm-config is required")
        # The role and the group are only rendered when the skip flags are off;
        # force them on for this render, the deploy keeps its own setting.
        cmd = ["helm", "template", args.release, args.chart, "-n", args.namespace,
               "--show-only", "templates/keycloak-podiumd-realm-config.yaml",
               "--set", "keycloak.config.skipRoles=false",
               "--set", "keycloak.config.skipGroups=false",
               # Only the realm import is needed: secrets the deploy pipeline
               # substitutes may still be empty here and would fail the schema.
               "--skip-schema-validation"]
        if args.version:
            cmd += ["--version", args.version]
        for f in args.values:
            cmd += ["-f", f]
        for s in args.set:
            cmd += ["--set", s]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            die("helm template failed:\n" + res.stderr.strip())
        text = res.stdout
    for doc in yaml.safe_load_all(text):
        if doc and doc.get("kind") == "ConfigMap" and "podiumd.yaml" in doc.get("data", {}):
            return yaml.safe_load(doc["data"]["podiumd.yaml"])
    die("no realm ConfigMap (keycloak-podiumd-realm-config) in the render; is openbao enabled?")
    return None


def wanted_from_realm(realm):
    client = next((c for c in realm.get("clients", []) if c.get("clientId") == CLIENT_ID), None)
    if client is None:
        die("the render has no 'openbao' client; set openbao.enabled=true in the values")
    roles = [r["name"] for r in realm.get("roles", {}).get("client", {}).get(CLIENT_ID, [])]
    groups = [g for g in realm.get("groups", []) if CLIENT_ID in g.get("clientRoles", {})]
    if not roles or not groups:
        die("the render has no openbao client role or group")
    return client, roles, groups


class Keycloak:
    def __init__(self, url, realm, user, password):
        self.url, self.realm, self.user, self.password = url.rstrip("/"), realm, user, password
        self.token = None
        self._login()

    def _login(self):
        data = urllib.parse.urlencode({
            "grant_type": "password", "client_id": "admin-cli",
            "username": self.user, "password": self.password}).encode()
        try:
            with urllib.request.urlopen(
                    f"{self.url}/realms/master/protocol/openid-connect/token", data, timeout=30) as r:
                self.token = json.load(r)["access_token"]
        except urllib.error.URLError as exc:
            die(f"Keycloak admin login failed at {self.url}: {exc}")

    def api(self, method, path, body=None, retry=True):
        req = urllib.request.Request(
            f"{self.url}/admin/realms/{self.realm}{path}", method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and retry:
                self._login()
                return self.api(method, path, body, retry=False)
            if exc.code == 404 and method == "GET":
                return None
            die(f"{method} {path}: HTTP {exc.code} {exc.read().decode(errors='replace')[:300]}")
        return None


def ensure_client(kc, want, secret, check):
    """Returns (internal id, number of differences)."""
    diffs = 0
    found = kc.api("GET", f"/clients?clientId={CLIENT_ID}") or []
    body = {k: v for k, v in want.items()
            if k not in ("secret", "protocolMappers", "optionalClientScopes")}
    if secret:
        body["secret"] = secret
    if not found:
        diffs += 1
        if check:
            print(f"    MISS  client {CLIENT_ID}")
            return None, diffs
        kc.api("POST", "/clients", {**body, "protocolMappers": want.get("protocolMappers", []),
                                    "optionalClientScopes": want.get("optionalClientScopes", [])})
        change(f"client {CLIENT_ID} created")
        found = kc.api("GET", f"/clients?clientId={CLIENT_ID}")
        return found[0]["id"], diffs
    current = found[0]
    cid = current["id"]
    stale = [k for k, v in body.items() if k != "secret" and current.get(k) != v]
    if stale:
        diffs += 1
        if check:
            print(f"    DIFF  client {CLIENT_ID}: {', '.join(sorted(stale))}")
        else:
            kc.api("PUT", f"/clients/{cid}", {**current, **body})
            change(f"client {CLIENT_ID} updated: {', '.join(sorted(stale))}")
    else:
        ok(f"client {CLIENT_ID}")
    # Protocol mappers, by name.
    have = {m["name"]: m for m in kc.api("GET", f"/clients/{cid}/protocol-mappers/models") or []}
    for m in want.get("protocolMappers", []):
        cur = have.get(m["name"])
        same = cur and cur.get("protocolMapper") == m.get("protocolMapper") and \
            all(str(cur.get("config", {}).get(k)) == str(v) for k, v in m.get("config", {}).items())
        if same:
            continue
        diffs += 1
        if check:
            print(f"    DIFF  mapper {m['name']}")
        elif cur:
            kc.api("PUT", f"/clients/{cid}/protocol-mappers/models/{cur['id']}", {**m, "id": cur["id"]})
            change(f"mapper {m['name']} updated")
        else:
            kc.api("POST", f"/clients/{cid}/protocol-mappers/models", m)
            change(f"mapper {m['name']} created")
    # Optional client scopes, by name.
    scopes = {s["name"]: s["id"] for s in kc.api("GET", "/client-scopes") or []}
    have_opt = {s["name"] for s in kc.api("GET", f"/clients/{cid}/optional-client-scopes") or []}
    for name in want.get("optionalClientScopes", []):
        if name in have_opt or name not in scopes:
            continue
        diffs += 1
        if check:
            print(f"    DIFF  optional scope {name}")
        else:
            kc.api("PUT", f"/clients/{cid}/optional-client-scopes/{scopes[name]}")
            change(f"optional scope {name} added")
    return cid, diffs


def ensure_role(kc, cid, role, check):
    if cid and kc.api("GET", f"/clients/{cid}/roles/{urllib.parse.quote(role)}"):
        ok(f"client role {CLIENT_ID}:{role}")
        return 0
    if check:
        print(f"    MISS  client role {CLIENT_ID}:{role}")
        return 1
    kc.api("POST", f"/clients/{cid}/roles", {"name": role})
    change(f"client role {CLIENT_ID}:{role} created")
    return 1


def find_group(kc, name):
    for g in kc.api("GET", f"/groups?search={urllib.parse.quote(name)}&exact=true") or []:
        if g["name"] == name:
            return g
    return None


def ensure_group(kc, cid, group, check):
    diffs = 0
    name = group["name"]
    g = find_group(kc, name)
    if not g:
        diffs += 1
        if check:
            print(f"    MISS  group {name}")
            return None, diffs + len(group["clientRoles"][CLIENT_ID])
        kc.api("POST", "/groups", {"name": name, "attributes": group.get("attributes", {})})
        change(f"group {name} created")
        g = find_group(kc, name)
    else:
        ok(f"group {name}")
    have = set()
    if cid:
        have = {r["name"] for r in kc.api("GET", f"/groups/{g['id']}/role-mappings/clients/{cid}") or []}
    for role in group["clientRoles"][CLIENT_ID]:
        if role in have:
            ok(f"group {name} has {CLIENT_ID}:{role}")
            continue
        diffs += 1
        if check:
            print(f"    MISS  group {name} role {CLIENT_ID}:{role}")
            continue
        rep = kc.api("GET", f"/clients/{cid}/roles/{urllib.parse.quote(role)}")
        kc.api("POST", f"/groups/{g['id']}/role-mappings/clients/{cid}",
               [{"id": rep["id"], "name": rep["name"]}])
        change(f"group {name} given {CLIENT_ID}:{role}")
    return g, diffs


def ensure_members(kc, g, name, members, check):
    diffs = 0
    current = {u["username"] for u in kc.api("GET", f"/groups/{g['id']}/members?max=1000") or []} if g else set()
    for user in members:
        if user in current:
            ok(f"{user} in {name}")
            continue
        found = kc.api("GET", f"/users?username={urllib.parse.quote(user)}&exact=true") or []
        if not found:
            die(f"user {user} does not exist in realm {kc.realm}")
        diffs += 1
        if check:
            print(f"    MISS  {user} in {name}")
            continue
        kc.api("PUT", f"/users/{found[0]['id']}/groups/{g['id']}")
        change(f"{user} added to {name}")
    return diffs


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--chart")
    p.add_argument("--release", default="podiumd")
    p.add_argument("-n", "--namespace", default="podiumd")
    p.add_argument("-f", "--values", action="append", default=[])
    p.add_argument("--set", action="append", default=[])
    p.add_argument("--version")
    p.add_argument("--realm-config")
    p.add_argument("--members", default="")
    p.add_argument("--check", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args()
    if args.help:
        print(__doc__)
        return 0

    url = os.environ.get("KEYCLOAK_URL", "")
    if not url:
        die("KEYCLOAK_URL is not set")
    context = os.environ.get("KUBE_CONTEXT", "")
    user = os.environ.get("KEYCLOAK_ADMIN_USER", "")
    password = os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "")
    if not password and context:
        user = user or kubectl_secret(context, args.namespace, "keycloak-podiumd-admin", "username")
        password = kubectl_secret(context, args.namespace, "keycloak-podiumd-admin", "password")
    user = user or "admin"
    if not password:
        password = getpass.getpass(f"Keycloak admin password for '{user}' (master realm): ")

    print("==> Render the chart's realm import")
    realm = render_realm(args)
    want_client, roles, groups = wanted_from_realm(realm)
    ok(f"realm {realm['realm']}: client {CLIENT_ID}, role(s) {', '.join(roles)}, "
       f"group(s) {', '.join(g['name'] for g in groups)}")

    secret = kubectl_secret(context, args.namespace, "keycloak-podiumd-realm-secrets",
                            "openbao-oidc-secret") if context else ""

    print(f"==> Keycloak {url}, realm {realm['realm']}" + (" (check only)" if args.check else ""))
    kc = Keycloak(url, realm["realm"], user, password)
    cid, diffs = ensure_client(kc, want_client, secret, args.check)
    for role in roles:
        diffs += ensure_role(kc, cid, role, args.check)
    members = [m.strip() for m in args.members.split(",") if m.strip()]
    for group in groups:
        g, d = ensure_group(kc, cid, group, args.check)
        diffs += d
        if members:
            diffs += ensure_members(kc, g, group["name"], members, args.check)

    if args.check:
        print("Check only: nothing changed." + (" Differences found." if diffs else " In sync."))
        return 1 if diffs else 0
    print("Done: OpenBao's Keycloak client, role and group are in place.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
