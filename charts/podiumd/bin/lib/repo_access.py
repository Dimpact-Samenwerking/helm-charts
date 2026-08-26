"""Fast reachability/authorization check for every repo Chart.yaml's
dependencies reference — the "Dependencies" step's real `helm dependency
update` can take minutes and re-downloads everything every run (see
lib.dependencies), so an unreachable or unauthorized repo is much cheaper
to catch here first: one lightweight request per unique repo, bounded by
TIMEOUT_SECONDS, instead of however far into a full dependency resolution
the same problem would otherwise surface."""
import urllib.error
import urllib.parse
import urllib.request

from lib.chart import load_yaml
from lib.registry import registry_tag_exists
from lib.render_scope import resolve_dependency_repo

TIMEOUT_SECONDS = 10


def dependency_repos(chart_dir):
    """(name, kind, target) for every Chart.yaml dependency that needs
    network access to resolve — kind "http" (target is the repo's base URL,
    an "@alias" already resolved via lib.render_scope.REQUIRED_REPOS) or
    "oci" (target is (host, repo_path, version), repo_path already
    combining the oci:// URL's own path with the dependency's chart name —
    matching the "<host>/<oci-path>/<chart-name>:<version>" reference `helm
    dependency update` actually pulls, confirmed by hand 2026-08-26). A
    "file://" dependency (e.g. mi-data, a local sub-chart in this same
    monorepo) needs neither and is omitted."""
    deps = (load_yaml(chart_dir / "Chart.yaml") or {}).get("dependencies", [])
    repos = []
    for dep in deps:
        repository = resolve_dependency_repo(dep.get("repository", ""))
        name = dep.get("alias", dep["name"])
        if repository.startswith("file://"):
            continue
        if repository.startswith("oci://"):
            host, _, oci_path = repository[len("oci://"):].partition("/")
            repo_path = f"{oci_path}/{dep['name']}" if oci_path else dep["name"]
            repos.append((name, "oci", (host, repo_path, dep["version"])))
        else:
            repos.append((name, "http", repository))
    return repos


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


def _check_oci_repo(host, repo_path, version):
    """Same manifest-existence check check_image_digests uses for a live
    image (lib.registry.registry_tag_exists, dynamic bearer-token discovery
    included) — an OCI-based Helm chart is just another tagged artifact on
    the same registry API, so a missing/unauthorized/unreachable chart
    fails exactly the same way a missing/unauthorized/unreachable image
    would."""
    label = f"oci://{host}/{repo_path}:{version}"
    try:
        exists, _ = registry_tag_exists(host, repo_path, version, timeout=TIMEOUT_SECONDS)
    except (urllib.error.URLError, OSError) as e:
        return False, f"{getattr(e, 'reason', e)} fetching {label}"
    if not exists:
        return False, f"{label} not found"
    return True, None


def check_repo_access(chart_dir):
    """Fails if any repo a Chart.yaml dependency needs is unreachable or
    unauthorized — before "Dependencies" spends minutes re-downloading
    every dependency only to hit the exact same problem. Dependencies
    sharing the same repo (e.g. every @maykinmedia chart) are tested once,
    not once per dependency."""
    repos = dependency_repos(chart_dir)
    grouped = {}
    for name, kind, target in repos:
        grouped.setdefault((kind, target), []).append(name)

    print(f"Checking access to {len(grouped)} unique repo(s) "
          f"for {len(repos)} network-resolved dependenc{'y' if len(repos) == 1 else 'ies'}...")

    failures = []
    for (kind, target), names in grouped.items():
        if kind == "http":
            ok, error = _check_http_repo(target)
            label = target
        else:
            ok, error = _check_oci_repo(*target)
            host, repo_path, version = target
            label = f"oci://{host}/{repo_path}:{version}"
        print(f"  [{'OK' if ok else 'FAIL'}] {', '.join(names)}  {label}"
              + (f"  — {error}" if error else ""))
        if not ok:
            failures.append((names, error))

    if failures:
        detail = "; ".join(f"{'/'.join(names)}: {error}" for names, error in failures)
        return False, f"{len(failures)}/{len(grouped)} repo(s) unreachable or unauthorized — {detail}"
    return True, f"{len(grouped)} repo(s) reachable ({len(repos)} dependencies)"
