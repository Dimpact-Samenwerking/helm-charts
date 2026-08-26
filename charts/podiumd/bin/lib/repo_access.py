"""Fast reachability/authorization check for every repo Chart.yaml's
dependencies AND values.yaml's digest-pinned images actually need — the
"Dependencies" step's real `helm dependency update` can take minutes and
re-downloads everything every run (see lib.dependencies), and even "Image
digests" (which does its own live registry check) only runs AFTER
Dependencies — so an unreachable or unauthorized repo/registry is much
cheaper, and much earlier, to catch here: one lightweight request per
unique repo/image, bounded by TIMEOUT_SECONDS, before either of those
steps does any real (and much more expensive) work."""
import re
import urllib.error
import urllib.parse
import urllib.request

from lib.chart import load_yaml
from lib.image_digests import scan_digest_pins
from lib.registry import parse_repo, registry_tag_exists
from lib.render_scope import resolve_dependency_repo

TIMEOUT_SECONDS = 10

# "- name: <name>" at the start of a Chart.yaml dependency block — used to
# re-derive a dependency's own source line, since PyYAML's safe_load (what
# lib.chart.load_yaml uses) doesn't track source lines at all. Same
# raw-text-regex approach every other line-anchored scan in this codebase
# uses (see lib.image_digests.DIGEST_PIN_RE and friends), rather than a
# real YAML AST with position info.
DEP_NAME_RE = re.compile(r'^\s*-\s*name:\s*"?([\w.\-]+)"?\s*(?:#.*)?$')


def _dependency_line_numbers(chart_yaml_text):
    """name -> 1-indexed line number of its "- name: <name>" entry."""
    return {
        m.group(1): i + 1
        for i, line in enumerate(chart_yaml_text.splitlines())
        for m in [DEP_NAME_RE.match(line)] if m
    }


def dependency_repos(chart_dir):
    """(name, line, kind, target) for every Chart.yaml dependency that
    needs network access to resolve — kind "http" (target is the repo's
    base URL, an "@alias" already resolved via
    lib.render_scope.REQUIRED_REPOS) or "oci" (target is (host, repo_path,
    version), repo_path already combining the oci:// URL's own path with
    the dependency's chart name — matching the
    "<host>/<oci-path>/<chart-name>:<version>" reference `helm dependency
    update` actually pulls, confirmed by hand 2026-08-26). "line" is the
    dependency's own line in Chart.yaml, or None if it couldn't be found
    (an unusual enough Chart.yaml layout that DEP_NAME_RE didn't match —
    degrades to no line number rather than a wrong one). A "file://"
    dependency (e.g. mi-data, a local sub-chart in this same monorepo)
    needs neither and is omitted."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    deps = (load_yaml(chart_yaml_path) or {}).get("dependencies", [])
    line_numbers = _dependency_line_numbers(chart_yaml_path.read_text(encoding="utf-8"))
    repos = []
    for dep in deps:
        repository = resolve_dependency_repo(dep.get("repository", ""))
        name = dep.get("alias", dep["name"])
        line = line_numbers.get(dep["name"])
        if repository.startswith("file://"):
            continue
        if repository.startswith("oci://"):
            host, _, oci_path = repository[len("oci://"):].partition("/")
            repo_path = f"{oci_path}/{dep['name']}" if oci_path else dep["name"]
            repos.append((name, line, "oci", (host, repo_path, dep["version"])))
        else:
            repos.append((name, line, "http", repository))
    return repos


def image_repos(values_path):
    """(lines, target) grouped by unique (host, repo_path, version) — for
    every digest-pinned image in values.yaml whose repository resolves
    WITHOUT the vendored subchart-default fallback
    (lib.chart.subchart_default_repository reads charts/*.tgz, which
    "Dependencies" is what actually populates — a pin needing that
    fallback can't be tested this early; "Image digests", which runs after
    Dependencies, covers those). "lines" is every values.yaml line pinning
    that exact (repository, version) — the same image is often pinned
    several times over."""
    pins = scan_digest_pins(values_path.read_text(encoding="utf-8").splitlines())
    grouped = {}
    for p in pins:
        if not p["repository"]:
            continue
        target = (*parse_repo(p["repository"]), p["version"])
        grouped.setdefault(target, []).append(p["line"])
    return list(grouped.items())


def _check_http_repo(url):
    """A classic Helm repo (added via `helm repo add`) publishes its whole
    catalog as index.yaml at its root — fetching just that (typically a few
    hundred KB at most) proves reachability/auth without pulling a single
    chart package."""
    index_url = urllib.parse.urljoin(url if url.endswith("/") else url + "/", "index.yaml")
    try:
        urllib.request.urlopen(index_url, timeout=TIMEOUT_SECONDS)
        return True, None
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} fetching {index_url}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"{getattr(e, 'reason', e)} fetching {index_url}"


def _check_registry_repo(host, repo_path, version):
    """Same manifest-existence check check_image_digests uses for a live
    image (lib.registry.registry_tag_exists, dynamic bearer-token discovery
    included) — an OCI-based Helm chart is just another tagged artifact on
    the same registry API a container image is, so a missing/unauthorized/
    unreachable chart or image fails exactly the same way."""
    try:
        exists, _ = registry_tag_exists(host, repo_path, version, timeout=TIMEOUT_SECONDS)
    except (urllib.error.URLError, OSError) as e:
        return False, f"{getattr(e, 'reason', e)}"
    if not exists:
        return False, "not found"
    return True, None


def check_repo_access(chart_dir):
    """Fails if any repo a Chart.yaml dependency needs, or any registry a
    values.yaml digest pin needs, is unreachable or unauthorized — before
    "Dependencies"/"Image digests" spend real time (and, for Dependencies,
    a full re-download of every dependency) only to hit the exact same
    problem. Anything sharing the same repo/image (e.g. every @maykinmedia
    chart, or the same image pinned several times) is tested once. Each
    finding is printed with its kind ("chart"/"image"), endpoint, and
    source location (Chart.yaml:<line> or values.yaml:<line>[,<line>...])."""
    chart_deps = dependency_repos(chart_dir)
    values_path = chart_dir / "values.yaml"
    img_targets = image_repos(values_path) if values_path.is_file() else []

    entries = []  # (kind, endpoint, location, test_kind, test_target)
    grouped_chart = {}
    for name, line, kind, target in chart_deps:
        info = grouped_chart.setdefault((kind, target), {"names": [], "lines": []})
        info["names"].append(name)
        if line:
            info["lines"].append(line)
    for (kind, target), info in grouped_chart.items():
        location = "Chart.yaml"
        if info["lines"]:
            location += ":" + ",".join(str(n) for n in sorted(info["lines"]))
        if kind == "http":
            endpoint = target
        else:
            host, repo_path, version = target
            endpoint = f"oci://{host}/{repo_path}:{version}"
        entries.append(("chart", f"{endpoint}  ({', '.join(info['names'])} — {location})", kind, target))

    for target, lines in img_targets:
        host, repo_path, version = target
        endpoint = f"{host}/{repo_path}:{version}"
        location = "values.yaml:" + ",".join(str(n) for n in sorted(lines))
        entries.append(("image", f"{endpoint}  ({location})", "registry", target))

    total_refs = len(chart_deps) + sum(len(lines) for _, lines in img_targets)
    print(f"Checking access to {len(entries)} unique repo(s)/image(s) "
          f"for {total_refs} network-resolved reference(s)...")

    failures = []
    for kind, description, test_kind, target in entries:
        ok, error = _check_http_repo(target) if test_kind == "http" else _check_registry_repo(*target)
        print(f"  [{'OK' if ok else 'FAIL'}] {kind:5}  {description}"
              + (f"  — {error}" if error else ""))
        if not ok:
            failures.append((kind, description, error))

    if failures:
        detail = "; ".join(f"{kind} {description}: {error}" for kind, description, error in failures)
        return False, f"{len(failures)}/{len(entries)} repo(s)/image(s) unreachable or unauthorized — {detail}"
    return True, f"{len(entries)} repo(s)/image(s) reachable ({total_refs} references)"
