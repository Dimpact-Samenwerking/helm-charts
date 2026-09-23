"""Chart.lock writing, byte-compatible with what `helm
dependency update` itself writes — so lib.dependencies can re-vendor only
the dependencies that changed and still leave behind a Chart.lock Helm
accepts as its own.

The one non-obvious part is the `digest:` line. Helm (internal/resolver
HashReq in Helm 3) computes it as

    "sha256:" + sha256(json.Marshal([2][]*chart.Dependency{req, lock}))

where `req` is Chart.yaml's own dependency list after Helm resolved every
"@alias" repository to its plain URL, and `lock` is the new Chart.lock
dependency list. Go's encoding/json has three quirks helm_lock_digest
mirrors exactly: struct fields in declaration order (not sorted),
`omitempty` fields dropped when empty, and <, >, & escaped as \\u003c,
\\u003e, \\u0026. Verified against a real Helm 3.22 Chart.lock for all 25
podiumd dependencies (tests/lib/test_chart_lock.py pins that case).

Only `helm dependency build` ever compares the digest (and refuses a
mismatching lock); `helm template`/`lint`/`package` never read it, and
Chart.lock is gitignored here — so a digest that ever drifted from
Helm's own would cost one full `helm dependency update`, not a broken
render."""

import hashlib
import json

from datetime import datetime
from pathlib import Path

import yaml

# chart.Dependency's JSON fields in Go declaration order (pkg/chart/
# dependency.go), with whether each one is `omitempty`.
_DEPENDENCY_JSON_FIELDS = (
    ("name", False),
    ("version", True),
    ("repository", False),
    ("condition", True),
    ("tags", True),
    ("enabled", True),
    ("import-values", True),
    ("alias", True),
)

_GO_JSON_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}


def resolved_repository(dep: dict, required_repos: dict):
    """dep's repository as Helm stores it in Chart.lock: an "@alias"
    resolved through `required_repos` (lib.settings.
    helm_repos_urls_by_alias), anything else (plain URL, oci://, file://)
    unchanged. An alias `required_repos` doesn't know stays "@alias"."""
    repo = dep.get("repository") or ""
    if repo.startswith("@"):
        return required_repos.get(repo[1:], repo)
    return repo


def _go_json_dependency(dep: dict):
    """dep as Go's json.Marshal writes a chart.Dependency: declared field
    order, omitempty fields left out when empty, version always a string
    (see lib.dependencies._dependency_key for why str())."""
    out = {}
    for field, omitempty in _DEPENDENCY_JSON_FIELDS:
        value = dep.get(field)
        if field == "version" and value is not None:
            value = str(value)
        if omitempty and not value:
            continue
        out[field] = "" if value is None else value
    return out


def _go_json(value: list):
    """json.Marshal output for value: no whitespace and Go's HTML-safe
    escapes. Key order is the caller's (see _sorted_nested_maps)."""
    text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    for char, escape in _GO_JSON_ESCAPES.items():
        text = text.replace(char, escape)
    return text


def _sorted_nested_maps(value: str | list | dict):
    """value with every dict below the top-level dependency fields sorted
    by key, the order Go marshals a map[string]interface{} in."""
    if isinstance(value, dict):
        return {key: _sorted_nested_maps(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted_nested_maps(item) for item in value]
    return value


def helm_lock_digest(chart_deps: list, lock_deps: list, required_repos: dict):
    """The `digest:` Helm writes into Chart.lock for Chart.yaml's
    `chart_deps` and the lock's own `lock_deps` — see the module
    docstring for the exact recipe."""
    req = []
    for dep in chart_deps:
        encoded = _go_json_dependency({**dep, "repository": resolved_repository(dep, required_repos)})
        if "import-values" in encoded:
            encoded["import-values"] = _sorted_nested_maps(encoded["import-values"])
        req.append(encoded)
    locked = [_go_json_dependency(dep) for dep in lock_deps]
    data = _go_json([req, locked])
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def lock_dependencies(chart_deps: list, required_repos: dict):
    """Chart.lock's `dependencies:` list for Chart.yaml's `chart_deps`,
    in Chart.yaml order — only name/repository/version, the three fields
    Helm writes there. Assumes every version is exact (lib.dependencies
    checks that first): Helm writes the version it resolved a range to,
    which only a real repo index lookup knows."""
    return [
        {
            "name": dep.get("name"),
            "repository": resolved_repository(dep, required_repos),
            "version": str(dep.get("version")),
        }
        for dep in chart_deps
    ]


def write_chart_lock(chart_dir: Path, chart_deps: list, required_repos: dict):
    """(Re)writes chart_dir/Chart.lock for `chart_deps` the way `helm
    dependency update` would: dependency list, digest, and a fresh
    `generated:` timestamp, keys sorted (Helm marshals the lock through
    JSON, so its YAML keys come out alphabetical too)."""
    lock_deps = lock_dependencies(chart_deps, required_repos)
    lock = {
        "dependencies": lock_deps,
        "digest": helm_lock_digest(chart_deps, lock_deps, required_repos),
        "generated": datetime.now().astimezone().isoformat(),
    }
    (chart_dir / "Chart.lock").write_text(yaml.safe_dump(lock, sort_keys=True), encoding="utf-8")
