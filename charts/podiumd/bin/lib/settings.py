"""Accessors for charts/podiumd/etc/settings.yaml — the operator-tunable
policy constants (cache TTLs, CVE severity sets, retry counts,
quality-gate pass/fail sets, thresholds, ...) that used to live as bare
module-level constants scattered across ~12 lib/*.py files. Moving them
into one YAML file lets an operator retune a value (e.g. loosen a CVE
cache TTL, add a host to the never-probe list) without touching Python
source.

Follows the exact precedent of lib.chart._release_baselines(chart_dir):
_load_settings below is tolerant of a missing settings.yaml (returns {}
rather than raising), takes chart_dir explicitly rather than discovering
it itself, and does no caching of its own — every accessor call re-reads
and re-parses the file. That's deliberately simple/cheap rather than
fast: these are called at most a handful of times per verify-podiumd
run, never in a hot loop, so there's no reason to add a caching layer
lib.chart's own equivalent doesn't have either.

Each public function below is a single named accessor for one leaf
value (e.g. cve_scan.high_severity_levels -> cve_high_severity_levels).
Every accessor is resilient by construction: if settings.yaml is
missing entirely, missing its relevant top-level section, or missing
just that one key, the accessor silently falls back to today's
hard-coded default (the same value the constant it replaces has always
had) rather than raising — a partially-filled-in or wholly absent
settings.yaml must never break a check. Only the value's presence in
the YAML overrides the default; there is no other way to change one of
these constants.

This module is infrastructure only (step 1 of 2). It is not yet wired
into any of the ~12 consuming files (lib/cve_check.py, lib/repo_access.
py, etc.) — those still define and use their own local constants
unchanged. Step 2 (a separate, later task) migrates each consumer to
call the matching accessor here instead of its own local constant, and
only then can that constant be deleted from the consumer."""
import yaml

SETTINGS_FILE_NAME = "etc/settings.yaml"


def _load_settings(chart_dir):
    """The parsed contents of chart_dir/etc/settings.yaml, or {} if the
    file doesn't exist yet — same missing-file tolerance as lib.chart.
    _release_baselines. Not a public accessor itself: callers want one
    of the named functions below, each of which reads one specific
    dotted key and applies its own hard-coded default."""
    path = chart_dir / SETTINGS_FILE_NAME
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _get(chart_dir, section, key, default):
    """One `settings[section][key]`, or `default` if settings.yaml, the
    section, or the key itself is missing. Shared by every accessor
    below so each one stays a one-liner; the default is always supplied
    by the caller (never looked up here) so it can never drift from the
    value documented alongside each accessor."""
    return (_load_settings(chart_dir).get(section) or {}).get(key, default)


def cve_high_severity_levels(chart_dir):
    """cve_scan.high_severity_levels — replaces lib.cve_check.
    HIGH_SEVERITIES, a set (tested with `in`, never iterated in order),
    default {"CRITICAL", "HIGH"}."""
    return set(_get(chart_dir, "cve_scan", "high_severity_levels", ["CRITICAL", "HIGH"]))


def cve_max_cves_per_package_before_summarizing(chart_dir):
    """cve_scan.max_cves_per_package_before_summarizing — replaces
    lib.cve_check.PACKAGE_CVE_LIST_THRESHOLD, default 5."""
    return _get(chart_dir, "cve_scan", "max_cves_per_package_before_summarizing", 5)


def cve_scan_cache_ttl_days(chart_dir):
    """cve_scan.scan_cache_ttl_days — replaces lib.cve_check.
    CVE_CACHE_TTL_DAYS, default 7."""
    return _get(chart_dir, "cve_scan", "scan_cache_ttl_days", 7)


def image_upgrade_tag_check_cache_ttl_days(chart_dir):
    """image_upgrade_check.tag_check_cache_ttl_days — replaces
    lib.image_upgrade_cache.IMAGE_UPGRADE_CACHE_TTL_DAYS, default 1."""
    return _get(chart_dir, "image_upgrade_check", "tag_check_cache_ttl_days", 1)


def repo_access_cache_ttl_minutes(chart_dir):
    """repo_access.cache_ttl_minutes — replaces lib.repo_access_cache.
    REPO_ACCESS_CACHE_TTL_MINUTES, default 30."""
    return _get(chart_dir, "repo_access", "cache_ttl_minutes", 30)


def repo_access_request_timeout_seconds(chart_dir):
    """repo_access.request_timeout_seconds — replaces lib.repo_access.
    TIMEOUT_SECONDS, default 10."""
    return _get(chart_dir, "repo_access", "request_timeout_seconds", 10)


def repo_access_never_probe_host_suffixes(chart_dir):
    """repo_access.never_probe_host_suffixes — replaces lib.repo_access.
    DENYLISTED_HOST_SUFFIXES, a tuple (only ever iterated via
    `host.endswith(suffix) for suffix in ...`), default ("azurecr.io",).
    YAML only ever hands back a list, so this always re-wraps it in a
    tuple to match the consumer's existing type exactly."""
    return tuple(_get(chart_dir, "repo_access", "never_probe_host_suffixes", ["azurecr.io"]))


def render_report_top_n_largest_templates_shown(chart_dir):
    """render_report.top_n_largest_templates_shown — replaces
    lib.render_scope.TOP_N_TEMPLATES, default 5."""
    return _get(chart_dir, "render_report", "top_n_largest_templates_shown", 5)


def dry_check_similarity_threshold(chart_dir):
    """dry_check.similarity_threshold — replaces lib.dry_check.
    DRY_SIMILARITY_THRESHOLD, default 0.6."""
    return _get(chart_dir, "dry_check", "similarity_threshold", 0.6)


def dry_check_high_similarity_threshold(chart_dir):
    """dry_check.high_similarity_threshold — replaces lib.dry_check.
    DRY_HIGH_SIMILARITY_THRESHOLD, default 0.75."""
    return _get(chart_dir, "dry_check", "high_similarity_threshold", 0.75)


def dry_check_min_significant_lines(chart_dir):
    """dry_check.min_significant_lines — replaces lib.dry_check.
    DRY_MIN_SIGNIFICANT_LINES, default 8."""
    return _get(chart_dir, "dry_check", "min_significant_lines", 8)


def release_secret_kubernetes_limit_bytes(chart_dir):
    """release_secret.kubernetes_secret_limit_bytes — replaces
    lib.release_secret_size.SECRET_LIMIT, default 1024 * 1024."""
    return _get(chart_dir, "release_secret", "kubernetes_secret_limit_bytes", 1024 * 1024)


def release_secret_warn_at_fraction_of_limit(chart_dir):
    """release_secret.warn_at_fraction_of_limit — replaces
    lib.release_secret_size.WARN_THRESHOLD, default 0.90."""
    return _get(chart_dir, "release_secret", "warn_at_fraction_of_limit", 0.90)


def dependency_fetch_retry_attempts(chart_dir):
    """dependency_fetch.retry_attempts — replaces lib.dependencies.
    RETRY_ATTEMPTS, default 3."""
    return _get(chart_dir, "dependency_fetch", "retry_attempts", 3)


def dependency_fetch_retry_backoff_seconds(chart_dir):
    """dependency_fetch.retry_backoff_seconds — replaces lib.dependencies.
    RETRY_BACKOFF_SECONDS, a tuple indexed by attempt number (`RETRY_
    BACKOFF_SECONDS[attempt - 1]`), default (5, 15, 45). Re-wrapped in a
    tuple to match, same as repo_access_never_probe_host_suffixes above."""
    return tuple(_get(chart_dir, "dependency_fetch", "retry_backoff_seconds", [5, 15, 45]))


def quality_gates_kubeconform_failing_statuses(chart_dir):
    """quality_gates.kubeconform_failing_statuses — replaces
    lib.kubeconform_check.KUBECONFORM_FAILING_STATUSES, a set (membership
    test only), default {"statusError", "statusInvalid"}."""
    return set(_get(chart_dir, "quality_gates", "kubeconform_failing_statuses",
                     ["statusError", "statusInvalid"]))


def quality_gates_shellcheck_failing_levels(chart_dir):
    """quality_gates.shellcheck_failing_levels — replaces
    lib.shellcheck_check.SHELLCHECK_FAILING_LEVELS, a set (membership
    test only), default {"error", "warning"}."""
    return set(_get(chart_dir, "quality_gates", "shellcheck_failing_levels", ["error", "warning"]))


def quality_gates_shellcheck_shell_names(chart_dir):
    """quality_gates.shellcheck_shell_names — replaces
    lib.shellcheck_check.SHELLCHECK_SHELL_NAMES, a set (membership test
    only), default {"sh", "bash", "dash", "ksh"}."""
    return set(_get(chart_dir, "quality_gates", "shellcheck_shell_names",
                     ["sh", "bash", "dash", "ksh"]))


def quality_gates_yamllint_failing_rules(chart_dir):
    """quality_gates.yamllint_failing_rules — replaces
    lib.yamllint_check.YAMLLINT_FAILING_RULES, a set (membership test
    only), default {"key-duplicates", "syntax"}."""
    return set(_get(chart_dir, "quality_gates", "yamllint_failing_rules",
                     ["key-duplicates", "syntax"]))


def quality_gates_markdown_disabled_rules(chart_dir):
    """quality_gates.markdown_disabled_rules — replaces
    lib.markdown_check.MARKDOWN_DISABLED_RULES. A list of rule IDs, same
    shape as every other quality_gates.* rule set here — the caller joins
    it with "," when building `pymarkdown -d <joined>`, since that's the
    one place this needs to be a single string, not the settings file's
    own concern. Default ["md013", "md014"]."""
    return list(_get(chart_dir, "quality_gates", "markdown_disabled_rules", ["md013", "md014"]))


def quality_gates_kube_score_check_id(chart_dir):
    """quality_gates.kube_score_check_id — replaces
    lib.kube_score_check.KUBE_SCORE_CHECK_ID, a plain string, default
    "container-resources"."""
    return _get(chart_dir, "quality_gates", "kube_score_check_id", "container-resources")


def helm_doc_max_diff_lines_shown(chart_dir):
    """helm_doc.max_diff_lines_shown — replaces lib.helm_docs_check.
    MAX_DIFF_LINES, default 40."""
    return _get(chart_dir, "helm_doc", "max_diff_lines_shown", 40)


def vendor_classification_keywords(chart_dir):
    """vendor_classification.keywords — replaces lib.render_scope.
    FRIENDLY_VENDOR_KEYWORDS, a dict (vendor keyword -> friendly label,
    matched case-insensitively as a substring of a dependency's resolved
    repository URL), default {"maykinmedia": "Maykin", "infonl":
    "Info(NL)", "worth-nl": "Worth", "wearefrank": "WeAreFrank",
    "dimpact": "Dimpact", "icatt-menselijk-digitaal": "ICATT"}."""
    return dict(_get(chart_dir, "vendor_classification", "keywords", {
        "maykinmedia": "Maykin",
        "infonl": "Info(NL)",
        "worth-nl": "Worth",
        "wearefrank": "WeAreFrank",
        "dimpact": "Dimpact",
        "icatt-menselijk-digitaal": "ICATT",
    }))


def vendor_classification_chart_overrides(chart_dir):
    """vendor_classification.chart_overrides — replaces lib.render_scope.
    FRIENDLY_VENDOR_CHART_OVERRIDES, a dict (chart name -> friendly label,
    for a dependency whose own repository URL doesn't reveal its real
    vendor at all), default {"kiss": "ICATT"}."""
    return dict(_get(chart_dir, "vendor_classification", "chart_overrides", {"kiss": "ICATT"}))


def helm_repos_urls_by_alias(chart_dir):
    """helm_repos.urls_by_alias — replaces lib.render_scope.
    REQUIRED_REPOS, a dict (repo alias -> real URL, for every Chart.yaml
    dependency that references a repo by "@alias"), default {"adfinis":
    "https://charts.adfinis.com", "wiremind": "https://wiremind.github.io/
    wiremind-helm-charts", "dimpact": "https://Dimpact-Samenwerking.
    github.io/helm-charts/", "maykinmedia": "https://maykinmedia.github.
    io/charts/", "kiss-elastic": "https://raw.githubusercontent.com/
    Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic",
    "zac": "https://infonl.github.io/dimpact-zaakafhandelcomponent/",
    "zgw-office-addin": "https://infonl.github.io/zgw-office-addin",
    "worth-nl": "https://worth-nl.github.io/helm-charts", "opstree":
    "https://ot-container-kit.github.io/helm-charts/"}."""
    return dict(_get(chart_dir, "helm_repos", "urls_by_alias", {
        "adfinis": "https://charts.adfinis.com",
        "wiremind": "https://wiremind.github.io/wiremind-helm-charts",
        "dimpact": "https://Dimpact-Samenwerking.github.io/helm-charts/",
        "maykinmedia": "https://maykinmedia.github.io/charts/",
        "kiss-elastic": "https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic",
        "zac": "https://infonl.github.io/dimpact-zaakafhandelcomponent/",
        "zgw-office-addin": "https://infonl.github.io/zgw-office-addin",
        "worth-nl": "https://worth-nl.github.io/helm-charts",
        "opstree": "https://ot-container-kit.github.io/helm-charts/",
    }))
