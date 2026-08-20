"""Shared infrastructure for every check that operates on a full `helm
template` render: scoping a finding to this chart's own templates/ vs. a
vendored sub-chart, classifying a vendored sub-chart as a "friendly"
partner vendor worth per-item detail, splitting/mapping the render back to
its source templates, and the common grouped-findings printer. Used by
check_render (verify-podiumd.py) and check_yamllint/check_kubeconform/
check_shellcheck/check_kube_score (lib/*_check.py)."""
import re
from collections import Counter

from lib.chart import load_yaml
from lib.procutil import run

CHART_NAME = "podiumd"
TOP_N_TEMPLATES = 5

OWN_TEMPLATES_PREFIX = "podiumd/templates/"

# name -> repo URL, for every Chart.yaml dependency that uses a named/alias
# repository (not a plain https:// URL and not an oci:// registry — those
# don't need `helm repo add`). Also used to resolve an "@alias" repository
# field to its real URL for friendly_vendor_charts's keyword matching.
REQUIRED_REPOS = {
    "adfinis": "https://charts.adfinis.com",
    "wiremind": "https://wiremind.github.io/wiremind-helm-charts",
    "dimpact": "https://Dimpact-Samenwerking.github.io/helm-charts/",
    "maykinmedia": "https://maykinmedia.github.io/charts/",
    "kiss-elastic": "https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic",
    "zac": "https://infonl.github.io/dimpact-zaakafhandelcomponent/",
    "zgw-office-addin": "https://infonl.github.io/zgw-office-addin",
    "worth-nl": "https://worth-nl.github.io/helm-charts",
    "opstree": "https://ot-container-kit.github.io/helm-charts/",
}


def supports_skip_schema_validation():
    result = run(["helm", "template", "--help"], capture_output=True, text=True)
    return "--skip-schema-validation" in result.stdout


def report_largest_templates(rendered_text):
    source_re = re.compile(r"^# Source: (.+)$")
    counts = Counter()
    current = None
    for line in rendered_text.splitlines():
        m = source_re.match(line)
        if m:
            current = m.group(1)
        elif current:
            counts[current] += 1

    if not counts:
        return
    print("Largest rendered templates (by line count):")
    for path, n in counts.most_common(TOP_N_TEMPLATES):
        print(f"  {n:6d}  {path}")


def report_errors_by_subchart(error_text):
    chart_re = re.compile(r"([A-Za-z0-9_.\-]+)/templates/")
    counts = Counter(chart_re.findall(error_text))
    if not counts:
        return
    print("Errors by sub-chart:")
    for chart, n in counts.most_common():
        print(f"  {chart}: {n}")


# Same pattern as report_errors_by_subchart — the chart name immediately
# preceding "/templates/" in a "# Source:" path, e.g. "zac" out of
# "podiumd/charts/zac/templates/configmap-nginx.yaml".
SOURCE_CHART_RE = re.compile(r"([A-Za-z0-9_.\-]+)/templates/")


def chart_name_from_source(source):
    m = SOURCE_CHART_RE.search(source or "")
    return m.group(1) if m else (source or "(unknown source)")


# Vendored sub-charts from these upstream orgs are close/collaborative
# dependencies — Dutch govtech partners in the same "common ground"
# ecosystem this repo lives in — worth seeing individual findings for, even
# though this repo still can't directly fix their code. Matched case-
# insensitively as a substring of the dependency's `repository:` field in
# Chart.yaml (an "@alias" is resolved via REQUIRED_REPOS first, since e.g.
# "@zac" itself doesn't contain "infonl" — only its resolved URL does).
# Every other vendored sub-chart (elastic, redis-operator,
# keycloak-operator, openbao, ...) stays aggregate-count-only: harder to
# act on, not worth the extra detail.
FRIENDLY_VENDOR_KEYWORDS = {
    "maykinmedia": "Maykin",
    "infonl": "Info(NL)",
    "worth-nl": "Worth",
    "wearefrank": "WeAreFrank",
    "dimpact": "Dimpact",
    # not currently matched by kiss-chart's own Chart.yaml dependency entry
    # (oci://ghcr.io/klantinteractie-servicesysteem) — see
    # FRIENDLY_VENDOR_CHART_OVERRIDES below — kept here too in case a
    # future dependency's repository URL does contain it.
    "icatt-menselijk-digitaal": "ICATT",
}

# "kiss" can't be derived from its own Chart.yaml repository field — KISS
# (oci://ghcr.io/klantinteractie-servicesysteem) is developed by ICATT
# (org "icatt-menselijk-digitaal" on GitHub/GHCR — see
# docs/apps/kiss/kiss-BASICS.md and the podiumd-adapter image repository),
# but neither appears in KISS's own repository URL, only in prose/its own
# sub-chart's image override. Keyed by chart name (alias if the dependency
# has one, matching how "# Source:" paths are built — see
# chart_name_from_source).
FRIENDLY_VENDOR_CHART_OVERRIDES = {
    "kiss": "ICATT",
}


def _resolve_dependency_repo(repository):
    if repository.startswith("@"):
        return REQUIRED_REPOS.get(repository[1:], repository)
    return repository


def friendly_vendor_charts(chart_dir):
    """Chart name -> vendor label, for every Chart.yaml dependency whose
    (resolved) repository matches a FRIENDLY_VENDOR_KEYWORDS entry, plus the
    FRIENDLY_VENDOR_CHART_OVERRIDES exceptions that can't be derived that
    way, plus any "file://" dependency — a local sub-chart living in this
    same monorepo (e.g. mi-data) isn't a "vendor" at all and is trivially
    fixable here, so it gets the same per-item visibility. Chart name is
    the dependency's alias if it has one, else its name — matching how
    Helm names the charts/<name>/ directory a "# Source:" path is rooted
    at."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml") or {}
    deps = chart_yaml.get("dependencies", [])
    dep_chart_names = {dep.get("alias", dep["name"]) for dep in deps}

    # Only apply an override for a chart that's actually a dependency here
    # — otherwise a name collision with some unrelated future dependency
    # would silently inherit an override meant for a specific chart.
    mapping = {name: vendor for name, vendor in FRIENDLY_VENDOR_CHART_OVERRIDES.items()
               if name in dep_chart_names}
    for dep in deps:
        chart_name = dep.get("alias", dep["name"])
        repo = _resolve_dependency_repo(dep.get("repository", ""))
        if repo.startswith("file://"):
            mapping[chart_name] = "Local"
            continue
        for keyword, vendor in FRIENDLY_VENDOR_KEYWORDS.items():
            if keyword in repo.lower():
                mapping[chart_name] = vendor
                break
    return mapping


def build_line_sources(rendered_text):
    """Map each 1-based line number in a full `helm template` render to the
    most recent preceding "# Source: <path>" comment, so a yamllint finding
    (which only knows line numbers) can be attributed back to the template
    file that produced it."""
    sources = {}
    current = None
    for i, line in enumerate(rendered_text.splitlines(), 1):
        if line.startswith("# Source: "):
            current = line[len("# Source: "):].strip()
        sources[i] = current
    return sources


# kind/version/name only — kubeconform's JSON output carries no line number
# or originating-file info per resource (unlike yamllint), so scoping own
# vs. vendored has to happen BEFORE validation: split the render into
# separate per-scope YAML streams and run the tool once per stream.
SOURCE_DOC_SPLIT_RE = re.compile(r"(?m)^---\n(?=# Source: )")


def split_rendered_by_source(rendered_text):
    """Split a full `helm template` render into (source, doc_text) pairs,
    one per "# Source: <path>" block — each doc_text keeps its own leading
    "---\\n# Source: ...\\n" header, so any subset of the pairs can be
    concatenated back into a smaller, still-valid multi-document YAML
    stream (used to validate this chart's own templates and its vendored
    sub-charts as separate runs)."""
    docs = SOURCE_DOC_SPLIT_RE.split(rendered_text)
    result = []
    for doc in docs:
        m = re.match(r"# Source: (.+)\n", doc)
        if m:
            result.append((m.group(1).strip(), f"---\n{doc}"))
    return result


def print_grouped_findings(findings, key_fn, item_fn, label_fn, items_label="line(s)"):
    """Shared grouping printer for check_yamllint/check_kubeconform/
    check_shellcheck/check_kube_score: the same root cause (e.g. a
    duplicated label key) typically shows up once per resource, not once
    overall — group by key_fn and join the occurrences (item_fn) onto one
    line, so N near-identical hits print as a handful of lines instead of
    a wall of repeats."""
    groups = {}
    for finding in findings:
        groups.setdefault(key_fn(finding), []).append(finding)
    for key, group in groups.items():
        count = f" x{len(group)}" if len(group) > 1 else ""
        print(f"  {label_fn(key)}{count}")
        print(f"      {items_label}: {', '.join(item_fn(f) for f in group)}")
