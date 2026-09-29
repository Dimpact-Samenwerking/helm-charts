"""Accessors for the operator-tunable policy constants in charts/podiumd/etc/settings.yaml.

Each accessor returns its built-in default when the file, section or key is missing or null.
A present value of the wrong shape exits with an error naming the key, never a silent default.
The file is parsed once per version and cached (accessors run thousands of times per run);
each read copies only the value it returns."""

import copy

from pathlib import Path
from typing import NoReturn
from typing import TypedDict

from lib.chart.values_tree_primitives import get_path
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlValue
from lib.yaml_types import cached_file_mapping
from lib.yaml_types import load_yaml_mapping
from lib.yaml_types import shape_problem

SETTINGS_FILE_NAME = "etc/settings.yaml"


def _load_settings(chart_dir: Path) -> YamlMapping:
    """The parsed settings.yaml, or {} if missing. Shared cached mapping: never mutate it."""
    path = chart_dir / SETTINGS_FILE_NAME
    if not path.is_file():
        return {}
    return cached_file_mapping(path, "", lambda: load_yaml_mapping(path)) or {}


def _setting(chart_dir: Path, section: str, key: str) -> YamlValue:
    """A copy of settings[section][key], or None when missing or null."""
    return copy.deepcopy(get_path(_load_settings(chart_dir), f"{section}.{key}"))


def _wrong_type(section: str, key: str, expected: str) -> NoReturn:
    msg = f"error: {SETTINGS_FILE_NAME}: {section}.{key} must be {expected}"
    raise SystemExit(msg)


def _checked(chart_dir: Path, section: str, key: str, shape: object, expected: str) -> YamlValue:
    """_setting, exiting with an error naming the key if a present value lacks `shape`."""
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
    """cve_scan.high_severity_levels."""
    return set(_text_list(chart_dir, "cve_scan", "high_severity_levels", ["CRITICAL", "HIGH"]))


def cve_max_cves_per_package_before_summarizing(chart_dir: Path):
    """cve_scan.max_cves_per_package_before_summarizing."""
    return _int(chart_dir, "cve_scan", "max_cves_per_package_before_summarizing", 5)


def cve_scan_cache_ttl_days(chart_dir: Path):
    """cve_scan.scan_cache_ttl_days."""
    return _int(chart_dir, "cve_scan", "scan_cache_ttl_days", 7)


def image_upgrade_tag_check_cache_ttl_days(chart_dir: Path):
    """image_upgrade_check.tag_check_cache_ttl_days."""
    return _int(chart_dir, "image_upgrade_check", "tag_check_cache_ttl_days", 1)


def root_containers_accepted(chart_dir: Path) -> dict[str, str]:
    """root_containers.accepted: "<source template>:<container>" -> why it may run as root."""
    return _text_map(chart_dir, "root_containers", "accepted", {})


def chart_upgrade_check_cache_ttl_days(chart_dir: Path):
    """chart_upgrade_check.cache_ttl_days."""
    return _int(chart_dir, "chart_upgrade_check", "cache_ttl_days", 1)


def repo_access_cache_ttl_minutes(chart_dir: Path):
    """repo_access.cache_ttl_minutes."""
    return _int(chart_dir, "repo_access", "cache_ttl_minutes", 30)


def repo_access_request_timeout_seconds(chart_dir: Path):
    """repo_access.request_timeout_seconds."""
    return _int(chart_dir, "repo_access", "request_timeout_seconds", 10)


def repo_access_never_probe_host_suffixes(chart_dir: Path):
    """repo_access.never_probe_host_suffixes, as a tuple."""
    return tuple(_text_list(chart_dir, "repo_access", "never_probe_host_suffixes", ["azurecr.io"]))


def render_report_top_n_largest_templates_shown(chart_dir: Path):
    """render_report.top_n_largest_templates_shown."""
    return _int(chart_dir, "render_report", "top_n_largest_templates_shown", 5)


def render_report_default_output_file_name(chart_dir: Path):
    """render_report.default_output_file_name: render-podiumd's output file (release_secret_size skips it)."""
    return _text(chart_dir, "render_report", "default_output_file_name", "rendered-helm.yaml")


def dry_check_similarity_threshold(chart_dir: Path):
    """dry_check.similarity_threshold."""
    return _number(chart_dir, "dry_check", "similarity_threshold", 0.6)


def dry_check_high_similarity_threshold(chart_dir: Path):
    """dry_check.high_similarity_threshold."""
    return _number(chart_dir, "dry_check", "high_similarity_threshold", 0.75)


def dry_check_min_significant_lines(chart_dir: Path):
    """dry_check.min_significant_lines."""
    return _int(chart_dir, "dry_check", "min_significant_lines", 8)


def release_secret_kubernetes_limit_bytes(chart_dir: Path):
    """release_secret.kubernetes_secret_limit_bytes."""
    return _int(chart_dir, "release_secret", "kubernetes_secret_limit_bytes", 1024 * 1024)


def release_secret_warn_at_fraction_of_limit(chart_dir: Path):
    """release_secret.warn_at_fraction_of_limit."""
    return _number(chart_dir, "release_secret", "warn_at_fraction_of_limit", 0.90)


def dependency_fetch_retry_attempts(chart_dir: Path):
    """dependency_fetch.retry_attempts."""
    return _int(chart_dir, "dependency_fetch", "retry_attempts", 3)


def dependency_fetch_retry_backoff_seconds(chart_dir: Path):
    """dependency_fetch.retry_backoff_seconds, as a tuple indexed by attempt - 1."""
    return tuple(_int_list(chart_dir, "dependency_fetch", "retry_backoff_seconds", [5, 15, 45]))


def quality_gates_kubeconform_failing_statuses(chart_dir: Path):
    """quality_gates.kubeconform_failing_statuses."""
    return set(_text_list(chart_dir, "quality_gates", "kubeconform_failing_statuses", ["statusError", "statusInvalid"]))


def quality_gates_shellcheck_failing_levels(chart_dir: Path):
    """quality_gates.shellcheck_failing_levels."""
    return set(_text_list(chart_dir, "quality_gates", "shellcheck_failing_levels", ["error", "warning"]))


def quality_gates_shellcheck_shell_names(chart_dir: Path):
    """quality_gates.shellcheck_shell_names."""
    return set(_text_list(chart_dir, "quality_gates", "shellcheck_shell_names", ["sh", "bash", "dash", "ksh"]))


def quality_gates_yamllint_failing_rules(chart_dir: Path):
    """quality_gates.yamllint_failing_rules."""
    return set(_text_list(chart_dir, "quality_gates", "yamllint_failing_rules", ["key-duplicates", "syntax"]))


def quality_gates_markdown_disabled_rules(chart_dir: Path):
    """quality_gates.markdown_disabled_rules: rule IDs; the caller joins them for `pymarkdown -d`."""
    return list(_text_list(chart_dir, "quality_gates", "markdown_disabled_rules", ["md013", "md014"]))


def quality_gates_kube_score_check_id(chart_dir: Path):
    """quality_gates.kube_score_check_id."""
    return _text(chart_dir, "quality_gates", "kube_score_check_id", "container-resources")


def helm_doc_max_diff_lines_shown(chart_dir: Path):
    """helm_doc.max_diff_lines_shown."""
    return _int(chart_dir, "helm_doc", "max_diff_lines_shown", 40)


def vendor_classification_keywords(chart_dir: Path):
    """vendor_classification.keywords: keyword -> vendor label, matched case-insensitively in the repository URL."""
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
    """vendor_classification.chart_overrides: chart name -> vendor label, for repository URLs that don't reveal it."""
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
    """digest_pinning.exceptions as {path tuple: {"sibling_field": str | None, "writable": bool}}.

    Both keys are always present (missing sibling_field -> None, writable -> False)."""
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
    """helm_repos.urls_by_alias: repo alias -> URL for "@alias" Chart.yaml repositories."""
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
    """component_resolution.chart_version_lockstep_components."""
    return frozenset(
        _text_list(
            chart_dir,
            "component_resolution",
            "chart_version_lockstep_components",
            ["kiss-chart", "pabc", "eck-operator", "internetaakafhandeling"],
        )
    )


def component_resolution_native_components(chart_dir: Path):
    """component_resolution.native_components."""
    return frozenset(_text_list(chart_dir, "component_resolution", "native_components", ["frankgateway", "keycloak"]))


def component_resolution_version_repository_paths(chart_dir: Path):
    """component_resolution.version_repository_paths."""
    return dict(
        _text_map(
            chart_dir, "component_resolution", "version_repository_paths", {"redis-operator": "redisOperator.imageName"}
        )
    )


def component_resolution_version_path_nested_subcharts(chart_dir: Path):
    """component_resolution.version_path_nested_subcharts."""
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


def component_resolution_embedded_version_images(chart_dir: Path):
    """component_resolution.embedded_version_images: path whose tag embeds another image's version -> that image."""
    return _text_map(
        chart_dir,
        "component_resolution",
        "embedded_version_images",
        {"keycloak.keycloakConfigCli.image": "keycloak.image"},
    )


def component_resolution_image_paths(chart_dir: Path):
    """component_resolution.image_paths: component -> image block paths, for components with several images."""
    return dict(
        _text_list_map(
            chart_dir,
            "component_resolution",
            "image_paths",
            {
                "zgw-office-addin": ["frontend.image", "backend.image"],
                "keycloak-operator": ["operator.image"],
                "openbao": ["server.image", "configuration.job.image"],
                "internetaakafhandeling": ["web.image", "poller.image"],
                "kiss-chart": ["image", "settings.syncJobs.image"],
                "pabc": ["image", "migrations.image"],
                "eck-operator": ["image"],
            },
        )
    )


def component_resolution_default_image_paths(chart_dir: Path):
    """component_resolution.default_image_paths: image paths for components without an image_paths entry."""
    return list(_text_list(chart_dir, "component_resolution", "default_image_paths", ["image"]))


def component_resolution_version_paths(chart_dir: Path):
    """component_resolution.version_paths: component -> paths holding a bare version, not an image block."""
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
