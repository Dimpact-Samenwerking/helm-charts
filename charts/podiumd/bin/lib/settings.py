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
into any of the ~12 consuming files (lib/checks/cve.py, lib/repo_access.
py, etc.) — those still define and use their own local constants
unchanged. Step 2 (a separate, later task) migrates each consumer to
call the matching accessor here instead of its own local constant, and
only then can that constant be deleted from the consumer."""

from pathlib import Path
from typing import NoReturn
from typing import TypedDict

from lib.chart.values_tree_primitives import get_path
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlValue
from lib.yaml_types import load_yaml_mapping
from lib.yaml_types import shape_problem

SETTINGS_FILE_NAME = "etc/settings.yaml"


def _load_settings(chart_dir: Path) -> YamlMapping:
    """The parsed contents of chart_dir/etc/settings.yaml, or {} if the
    file doesn't exist yet — same missing-file tolerance as lib.chart.
    _release_baselines. Not a public accessor itself: callers want one
    of the named functions below, each of which reads one specific
    dotted key and applies its own hard-coded default."""
    path = chart_dir / SETTINGS_FILE_NAME
    if not path.is_file():
        return {}
    return load_yaml_mapping(path)


def _setting(chart_dir: Path, section: str, key: str) -> YamlValue:
    """settings[section][key], or None when settings.yaml, the section or
    the key is missing (or null) — the caller then uses its default."""
    return get_path(_load_settings(chart_dir), f"{section}.{key}")


def _wrong_type(section: str, key: str, expected: str) -> NoReturn:
    msg = f"error: {SETTINGS_FILE_NAME}: {section}.{key} must be {expected}"
    raise SystemExit(msg)


def _checked(chart_dir: Path, section: str, key: str, shape: object, expected: str) -> YamlValue:
    """_setting, after checking a present value has `shape` (see
    lib.yaml_types.shape_problem); exits naming the key when it doesn't."""
    value = _setting(chart_dir, section, key)
    if value is not None and shape_problem(value, shape) is not None:
        _wrong_type(section, key, expected)
    return value


def _int(chart_dir: Path, section: str, key: str, default: int) -> int:
    value = _checked(chart_dir, section, key, int, "an integer")
    return value if isinstance(value, int) else default


def _number(chart_dir: Path, section: str, key: str, default: float) -> float:
    value = _checked(chart_dir, section, key, (int, float), "a number")
    return float(value) if isinstance(value, int | float) else default


def _text(chart_dir: Path, section: str, key: str, default: str) -> str:
    value = _checked(chart_dir, section, key, str, "a string")
    return value if isinstance(value, str) else default


def _text_list(chart_dir: Path, section: str, key: str, default: list[str]) -> list[str]:
    value = _checked(chart_dir, section, key, [str], "a list of strings")
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else default


def _int_list(chart_dir: Path, section: str, key: str, default: list[int]) -> list[int]:
    value = _checked(chart_dir, section, key, [int], "a list of integers")
    return [v for v in value if isinstance(v, int)] if isinstance(value, list) else default


def _text_map(chart_dir: Path, section: str, key: str, default: dict[str, str]) -> dict[str, str]:
    value = _checked(chart_dir, section, key, dict, "a mapping of strings")
    if not isinstance(value, dict):
        return default
    if not all(isinstance(v, str) for v in value.values()):
        _wrong_type(section, key, "a mapping of strings")
    return {k: v for k, v in value.items() if isinstance(v, str)}


def _text_list_map(chart_dir: Path, section: str, key: str, default: dict[str, list[str]]) -> dict[str, list[str]]:
    value = _checked(chart_dir, section, key, dict, "a mapping of string lists")
    if not isinstance(value, dict):
        return default
    if any(shape_problem(v, [str]) is not None for v in value.values()):
        _wrong_type(section, key, "a mapping of string lists")
    return {k: [item for item in v if isinstance(item, str)] for k, v in value.items() if isinstance(v, list)}


def _text_map_map(
    chart_dir: Path, section: str, key: str, default: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    value = _checked(chart_dir, section, key, dict, "a mapping of string mappings")
    if not isinstance(value, dict):
        return default
    result: dict[str, dict[str, str]] = {}
    for k, v in value.items():
        if not isinstance(v, dict) or not all(isinstance(item, str) for item in v.values()):
            _wrong_type(section, key, "a mapping of string mappings")
        result[k] = {ik: iv for ik, iv in v.items() if isinstance(iv, str)}
    return result


def cve_high_severity_levels(chart_dir: Path):
    """cve_scan.high_severity_levels — replaces lib.checks.cve.
    HIGH_SEVERITIES, a set (tested with `in`, never iterated in order),
    default {"CRITICAL", "HIGH"}."""
    return set(_text_list(chart_dir, "cve_scan", "high_severity_levels", ["CRITICAL", "HIGH"]))


def cve_max_cves_per_package_before_summarizing(chart_dir: Path):
    """cve_scan.max_cves_per_package_before_summarizing — replaces
    lib.checks.cve.PACKAGE_CVE_LIST_THRESHOLD, default 5."""
    return _int(chart_dir, "cve_scan", "max_cves_per_package_before_summarizing", 5)


def cve_scan_cache_ttl_days(chart_dir: Path):
    """cve_scan.scan_cache_ttl_days — replaces lib.checks.cve.
    CVE_CACHE_TTL_DAYS, default 7."""
    return _int(chart_dir, "cve_scan", "scan_cache_ttl_days", 7)


def image_upgrade_tag_check_cache_ttl_days(chart_dir: Path):
    """image_upgrade_check.tag_check_cache_ttl_days — replaces
    lib.image.upgrade_cache.IMAGE_UPGRADE_CACHE_TTL_DAYS, default 1."""
    return _int(chart_dir, "image_upgrade_check", "tag_check_cache_ttl_days", 1)


def repo_access_cache_ttl_minutes(chart_dir: Path):
    """repo_access.cache_ttl_minutes — replaces lib.repo_access_cache.
    REPO_ACCESS_CACHE_TTL_MINUTES, default 30."""
    return _int(chart_dir, "repo_access", "cache_ttl_minutes", 30)


def repo_access_request_timeout_seconds(chart_dir: Path):
    """repo_access.request_timeout_seconds — replaces lib.repo_access.
    TIMEOUT_SECONDS, default 10."""
    return _int(chart_dir, "repo_access", "request_timeout_seconds", 10)


def repo_access_never_probe_host_suffixes(chart_dir: Path):
    """repo_access.never_probe_host_suffixes — replaces lib.repo_access.
    DENYLISTED_HOST_SUFFIXES, a tuple (only ever iterated via
    `host.endswith(suffix) for suffix in ...`), default ("azurecr.io",).
    YAML only ever hands back a list, so this always re-wraps it in a
    tuple to match the consumer's existing type exactly."""
    return tuple(_text_list(chart_dir, "repo_access", "never_probe_host_suffixes", ["azurecr.io"]))


def render_report_top_n_largest_templates_shown(chart_dir: Path):
    """render_report.top_n_largest_templates_shown — replaces
    lib.render_scope.TOP_N_TEMPLATES, default 5."""
    return _int(chart_dir, "render_report", "top_n_largest_templates_shown", 5)


def render_report_default_output_file_name(chart_dir: Path):
    """render_report.default_output_file_name — render-podiumd's default
    output file in the chart root, also excluded by lib.release_secret_size,
    default "rendered-helm.yaml"."""
    return _text(chart_dir, "render_report", "default_output_file_name", "rendered-helm.yaml")


def dry_check_similarity_threshold(chart_dir: Path):
    """dry_check.similarity_threshold — replaces lib.checks.dry.
    DRY_SIMILARITY_THRESHOLD, default 0.6."""
    return _number(chart_dir, "dry_check", "similarity_threshold", 0.6)


def dry_check_high_similarity_threshold(chart_dir: Path):
    """dry_check.high_similarity_threshold — replaces lib.checks.dry.
    DRY_HIGH_SIMILARITY_THRESHOLD, default 0.75."""
    return _number(chart_dir, "dry_check", "high_similarity_threshold", 0.75)


def dry_check_min_significant_lines(chart_dir: Path):
    """dry_check.min_significant_lines — replaces lib.checks.dry.
    DRY_MIN_SIGNIFICANT_LINES, default 8."""
    return _int(chart_dir, "dry_check", "min_significant_lines", 8)


def release_secret_kubernetes_limit_bytes(chart_dir: Path):
    """release_secret.kubernetes_secret_limit_bytes — replaces
    lib.release_secret_size.SECRET_LIMIT, default 1024 * 1024."""
    return _int(chart_dir, "release_secret", "kubernetes_secret_limit_bytes", 1024 * 1024)


def release_secret_warn_at_fraction_of_limit(chart_dir: Path):
    """release_secret.warn_at_fraction_of_limit — replaces
    lib.release_secret_size.WARN_THRESHOLD, default 0.90."""
    return _number(chart_dir, "release_secret", "warn_at_fraction_of_limit", 0.90)


def dependency_fetch_retry_attempts(chart_dir: Path):
    """dependency_fetch.retry_attempts — replaces lib.dependencies.
    RETRY_ATTEMPTS, default 3."""
    return _int(chart_dir, "dependency_fetch", "retry_attempts", 3)


def dependency_fetch_retry_backoff_seconds(chart_dir: Path):
    """dependency_fetch.retry_backoff_seconds — replaces lib.dependencies.
    RETRY_BACKOFF_SECONDS, a tuple indexed by attempt number (`RETRY_
    BACKOFF_SECONDS[attempt - 1]`), default (5, 15, 45). Re-wrapped in a
    tuple to match, same as repo_access_never_probe_host_suffixes above."""
    return tuple(_int_list(chart_dir, "dependency_fetch", "retry_backoff_seconds", [5, 15, 45]))


def quality_gates_kubeconform_failing_statuses(chart_dir: Path):
    """quality_gates.kubeconform_failing_statuses — replaces
    lib.checks.kubeconform.KUBECONFORM_FAILING_STATUSES, a set (membership
    test only), default {"statusError", "statusInvalid"}."""
    return set(_text_list(chart_dir, "quality_gates", "kubeconform_failing_statuses", ["statusError", "statusInvalid"]))


def quality_gates_shellcheck_failing_levels(chart_dir: Path):
    """quality_gates.shellcheck_failing_levels — replaces
    lib.checks.shellcheck.SHELLCHECK_FAILING_LEVELS, a set (membership
    test only), default {"error", "warning"}."""
    return set(_text_list(chart_dir, "quality_gates", "shellcheck_failing_levels", ["error", "warning"]))


def quality_gates_shellcheck_shell_names(chart_dir: Path):
    """quality_gates.shellcheck_shell_names — replaces
    lib.checks.shellcheck.SHELLCHECK_SHELL_NAMES, a set (membership test
    only), default {"sh", "bash", "dash", "ksh"}."""
    return set(_text_list(chart_dir, "quality_gates", "shellcheck_shell_names", ["sh", "bash", "dash", "ksh"]))


def quality_gates_yamllint_failing_rules(chart_dir: Path):
    """quality_gates.yamllint_failing_rules — replaces
    lib.checks.yamllint.YAMLLINT_FAILING_RULES, a set (membership test
    only), default {"key-duplicates", "syntax"}."""
    return set(_text_list(chart_dir, "quality_gates", "yamllint_failing_rules", ["key-duplicates", "syntax"]))


def quality_gates_markdown_disabled_rules(chart_dir: Path):
    """quality_gates.markdown_disabled_rules — replaces
    lib.checks.markdown.MARKDOWN_DISABLED_RULES. A list of rule IDs, same
    shape as every other quality_gates.* rule set here — the caller joins
    it with "," when building `pymarkdown -d <joined>`, since that's the
    one place this needs to be a single string, not the settings file's
    own concern. Default ["md013", "md014"]."""
    return list(_text_list(chart_dir, "quality_gates", "markdown_disabled_rules", ["md013", "md014"]))


def quality_gates_kube_score_check_id(chart_dir: Path):
    """quality_gates.kube_score_check_id — replaces
    lib.checks.kube_score.KUBE_SCORE_CHECK_ID, a plain string, default
    "container-resources"."""
    return _text(chart_dir, "quality_gates", "kube_score_check_id", "container-resources")


def helm_doc_max_diff_lines_shown(chart_dir: Path):
    """helm_doc.max_diff_lines_shown — replaces lib.checks.helm_docs.
    MAX_DIFF_LINES, default 40."""
    return _int(chart_dir, "helm_doc", "max_diff_lines_shown", 40)


def vendor_classification_keywords(chart_dir: Path):
    """vendor_classification.keywords — replaces lib.render_scope.
    FRIENDLY_VENDOR_KEYWORDS, a dict (vendor keyword -> friendly label,
    matched case-insensitively as a substring of a dependency's resolved
    repository URL), default {"maykinmedia": "Maykin", "infonl":
    "Info(NL)", "worth-nl": "Worth", "wearefrank": "WeAreFrank",
    "dimpact": "Dimpact", "icatt-menselijk-digitaal": "ICATT"}."""
    return dict(
        _text_map(
            chart_dir,
            "vendor_classification",
            "keywords",
            {
                "maykinmedia": "Maykin",
                "infonl": "Info(NL)",
                "worth-nl": "Worth",
                "wearefrank": "WeAreFrank",
                "dimpact": "Dimpact",
                "icatt-menselijk-digitaal": "ICATT",
            },
        )
    )


def vendor_classification_chart_overrides(chart_dir: Path):
    """vendor_classification.chart_overrides — replaces lib.render_scope.
    FRIENDLY_VENDOR_CHART_OVERRIDES, a dict (chart name -> friendly label,
    for a dependency whose own repository URL doesn't reveal its real
    vendor at all), default {"kiss": "ICATT"}."""
    return dict(_text_map(chart_dir, "vendor_classification", "chart_overrides", {"kiss": "ICATT"}))


class DigestPinningException(TypedDict):
    """One digest_pinning.exceptions entry: the sibling field holding the
    digest (None: none) and whether update-component-version may write it."""

    sibling_field: str | None
    writable: bool


_DEFAULT_DIGEST_PINNING_EXCEPTIONS: YamlMapping = {
    "keycloak-operator.operator.image": {"sibling_field": "sha", "writable": True},
    "keycloak-operator.operator.config.keycloakImage": {"sibling_field": "sha", "writable": True},
    "keycloak.image": {"sibling_field": "sha", "writable": True},
    "eck-operator.image": {"sibling_field": "digest", "writable": True},
    "omc.image": {},
}


def digest_pinning_exceptions(chart_dir: Path) -> dict[tuple[str, ...], DigestPinningException]:
    """digest_pinning.exceptions — replaces BOTH lib.chart.
    SPLIT_TAG_SHA_PATHS and lib.checks.digest_pinning.EXEMPT_PATHS (the
    latter was always exactly "every key here"; the former was always
    exactly "entries that also carry a sibling_field") — see this
    iteration's plan for how these were two independently-hand-maintained,
    overlapping registries. Also replaces update-component-version's own
    separate, narrower write-side allowlist (see "writable" below).

    Returns {tuple_path: {"sibling_field": str | None, "writable": bool}},
    normalized so every entry has both keys (missing sibling_field ->
    None, missing writable -> False) — callers never need their own
    .get() dance."""
    shape = {"sibling_field?": str, "writable?": bool}
    value = _checked(chart_dir, "digest_pinning", "exceptions", dict, "a mapping of exception entries")
    raw: YamlMapping = value if isinstance(value, dict) else _DEFAULT_DIGEST_PINNING_EXCEPTIONS
    result: dict[tuple[str, ...], DigestPinningException] = {}
    for path, entry in raw.items():
        if not isinstance(entry, dict) or shape_problem(entry, shape) is not None:
            _wrong_type("digest_pinning", "exceptions", "a mapping of {sibling_field?: str, writable?: bool}")
        sibling_field, writable = entry.get("sibling_field"), entry.get("writable")
        result[tuple(path.split("."))] = {
            "sibling_field": sibling_field if isinstance(sibling_field, str) else None,
            "writable": writable is True,
        }
    return result


def helm_repos_urls_by_alias(chart_dir: Path):
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
    return dict(
        _text_map(
            chart_dir,
            "helm_repos",
            "urls_by_alias",
            {
                "adfinis": "https://charts.adfinis.com",
                "wiremind": "https://wiremind.github.io/wiremind-helm-charts",
                "dimpact": "https://Dimpact-Samenwerking.github.io/helm-charts/",
                "maykinmedia": "https://maykinmedia.github.io/charts/",
                "kiss-elastic": "https://raw.githubusercontent.com/Klantinteractie-Servicesysteem"
                "/.github/main/docs/scripts/elastic",
                "zac": "https://infonl.github.io/dimpact-zaakafhandelcomponent/",
                "zgw-office-addin": "https://infonl.github.io/zgw-office-addin",
                "worth-nl": "https://worth-nl.github.io/helm-charts",
                "opstree": "https://ot-container-kit.github.io/helm-charts/",
            },
        )
    )


def component_resolution_chart_version_lockstep_components(chart_dir: Path):
    """component_resolution.chart_version_lockstep_components — replaces
    lib.chart.CHART_VERSION_LOCKSTEP_COMPONENTS, a frozenset, default
    frozenset({"kiss-chart", "pabc", "eck-operator"})."""
    return frozenset(
        _text_list(
            chart_dir,
            "component_resolution",
            "chart_version_lockstep_components",
            ["kiss-chart", "pabc", "eck-operator"],
        )
    )


def component_resolution_native_components(chart_dir: Path):
    """component_resolution.native_components — replaces lib.chart.
    NATIVE_COMPONENTS, a frozenset, default frozenset({"frankgateway"})."""
    return frozenset(_text_list(chart_dir, "component_resolution", "native_components", ["frankgateway"]))


def component_resolution_version_repository_paths(chart_dir: Path):
    """component_resolution.version_repository_paths — replaces
    lib.chart.COMPONENT_VERSION_REPOSITORY_PATHS, default
    {"redis-operator": "redisOperator.imageName"}."""
    return dict(
        _text_map(
            chart_dir, "component_resolution", "version_repository_paths", {"redis-operator": "redisOperator.imageName"}
        )
    )


def component_resolution_version_path_nested_subcharts(chart_dir: Path):
    """component_resolution.version_path_nested_subcharts — replaces
    lib.chart.COMPONENT_VERSION_PATH_NESTED_SUBCHARTS, a nested dict,
    default {"eck-stack": {"eck-elasticsearch.version": "eck-elasticsearch",
    "eck-kibana.version": "eck-kibana",
    "eck-enterprise-search.version": "eck-enterprise-search"}}."""
    return _text_map_map(
        chart_dir,
        "component_resolution",
        "version_path_nested_subcharts",
        {
            "eck-stack": {
                "eck-elasticsearch.version": "eck-elasticsearch",
                "eck-kibana.version": "eck-kibana",
                "eck-enterprise-search.version": "eck-enterprise-search",
            },
        },
    )


def component_resolution_image_paths(chart_dir: Path):
    """component_resolution.image_paths — replaces lib.chart.
    COMPONENT_IMAGE_PATHS, a dict (component name/alias -> dotted
    values.yaml path(s) for its own image block(s), for a component that
    ships more than one independently-versioned image), default
    {"zgw-office-addin": ["frontend.image", "backend.image"],
    "keycloak-operator": ["operator.config.keycloakImage"],
    "openbao": ["server.image"],
    "internetaakafhandeling": ["web.image", "poller.image"],
    "kiss-chart": ["image", "settings.syncJobs.image"],
    "eck-operator": ["image"]} — see etc/settings.yaml's own
    component_resolution.image_paths comment for the reasoning behind
    each entry."""
    return dict(
        _text_list_map(
            chart_dir,
            "component_resolution",
            "image_paths",
            {
                "zgw-office-addin": ["frontend.image", "backend.image"],
                "keycloak-operator": ["operator.config.keycloakImage"],
                "openbao": ["server.image"],
                "internetaakafhandeling": ["web.image", "poller.image"],
                "kiss-chart": ["image", "settings.syncJobs.image"],
                "eck-operator": ["image"],
            },
        )
    )


def component_resolution_default_image_paths(chart_dir: Path):
    """component_resolution.default_image_paths — replaces lib.chart.
    DEFAULT_IMAGE_PATHS, the image path(s) assumed for any component with
    no image_paths entry of its own, default ["image"]."""
    return list(_text_list(chart_dir, "component_resolution", "default_image_paths", ["image"]))


def component_resolution_version_paths(chart_dir: Path):
    """component_resolution.version_paths — replaces lib.chart.
    COMPONENT_VERSION_PATHS, a dict (component name -> dotted values.yaml
    path(s) pointing directly at a bare version string, for a component
    whose real app version isn't expressed as an "image: {repository,
    tag}" block at all), default {"eck-stack": ["eck-elasticsearch.
    version", "eck-kibana.version"], "redis-operator": ["redisOperator.
    imageTag"]} — see etc/settings.yaml's own component_resolution.
    version_paths comment for the reasoning behind each entry."""
    return dict(
        _text_list_map(
            chart_dir,
            "component_resolution",
            "version_paths",
            {
                "eck-stack": ["eck-elasticsearch.version", "eck-kibana.version"],
                "redis-operator": ["redisOperator.imageTag"],
            },
        )
    )
