"""lib.settings — every etc/settings.yaml accessor. Three shapes exercised
per accessor: (a) no settings.yaml at all -> documented hard-coded
default, (b) a full settings.yaml -> the YAML-provided value, correctly
typed, (c) a PARTIAL settings.yaml (only some top-level sections
present) -> keys/sections present are read from it, keys/sections
absent fall back to their own default, without crashing. A last test
confirms a chart_dir with no etc/ directory at all doesn't crash
_load_settings either — mirrors lib.chart._release_baselines' own
tolerance for a missing etc/release-baseline.yaml."""

import yaml

FULL_SETTINGS = {
    "cve_scan": {
        "high_severity_levels": ["CRITICAL", "HIGH", "MEDIUM"],
        "max_cves_per_package_before_summarizing": 9,
        "scan_cache_ttl_days": 14,
    },
    "image_upgrade_check": {
        "tag_check_cache_ttl_days": 2,
    },
    "repo_access": {
        "cache_ttl_minutes": 60,
        "request_timeout_seconds": 20,
        "never_probe_host_suffixes": ["azurecr.io", "example.internal"],
    },
    "render_report": {
        "top_n_largest_templates_shown": 10,
        "default_output_file_name": "custom-render.yaml",
    },
    "dry_check": {
        "similarity_threshold": 0.5,
        "high_similarity_threshold": 0.8,
        "min_significant_lines": 12,
    },
    "release_secret": {
        "kubernetes_secret_limit_bytes": 2097152,
        "warn_at_fraction_of_limit": 0.75,
    },
    "dependency_fetch": {
        "retry_attempts": 5,
        "retry_backoff_seconds": [1, 2, 3],
    },
    "quality_gates": {
        "kubeconform_failing_statuses": ["statusError"],
        "shellcheck_failing_levels": ["error"],
        "shellcheck_shell_names": ["sh", "bash"],
        "yamllint_failing_rules": ["syntax"],
        "markdown_disabled_rules": ["md013"],
        "kube_score_check_id": "custom-check",
    },
    "helm_doc": {
        "max_diff_lines_shown": 100,
    },
    "vendor_classification": {
        "keywords": {"maykinmedia": "Maykin", "infonl": "Info(NL)"},
        "chart_overrides": {"kiss": "ICATT", "foo": "Bar"},
    },
    "helm_repos": {
        "urls_by_alias": {"zac": "https://example.invalid/zac/"},
    },
    "component_resolution": {
        "chart_version_lockstep_components": ["kiss-chart", "pabc"],
        "native_components": ["other-native"],
        "version_repository_paths": {"redis-operator": "redisOperator.imageName", "foo-op": "fooOperator.imageName"},
        "version_path_nested_subcharts": {"eck-stack": {"eck-elasticsearch.version": "eck-elasticsearch"}},
        "image_paths": {"widget": ["image"]},
        "default_image_paths": ["custom-default-image"],
        "version_paths": {"widget-b": ["version"]},
    },
}


def write_settings(chart_dir, data):
    (chart_dir / "etc").mkdir(exist_ok=True)
    (chart_dir / "etc" / "settings.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


# (accessor name, section, key, default, overridden value in FULL_SETTINGS,
# expected type constructor applied to both default and override for
# comparison — set/tuple/plain passthrough)
ACCESSOR_CASES = [
    ("cve_high_severity_levels", {"CRITICAL", "HIGH"}, {"CRITICAL", "HIGH", "MEDIUM"}, set),
    ("cve_max_cves_per_package_before_summarizing", 5, 9, None),
    ("cve_scan_cache_ttl_days", 7, 14, None),
    ("image_upgrade_tag_check_cache_ttl_days", 1, 2, None),
    ("repo_access_cache_ttl_minutes", 30, 60, None),
    ("repo_access_request_timeout_seconds", 10, 20, None),
    ("repo_access_never_probe_host_suffixes", ("azurecr.io",), ("azurecr.io", "example.internal"), tuple),
    ("render_report_top_n_largest_templates_shown", 5, 10, None),
    ("render_report_default_output_file_name", "rendered-helm.yaml", "custom-render.yaml", None),
    ("dry_check_similarity_threshold", 0.6, 0.5, None),
    ("dry_check_high_similarity_threshold", 0.75, 0.8, None),
    ("dry_check_min_significant_lines", 8, 12, None),
    ("release_secret_kubernetes_limit_bytes", 1024 * 1024, 2097152, None),
    ("release_secret_warn_at_fraction_of_limit", 0.90, 0.75, None),
    ("dependency_fetch_retry_attempts", 3, 5, None),
    ("dependency_fetch_retry_backoff_seconds", (5, 15, 45), (1, 2, 3), tuple),
    ("quality_gates_kubeconform_failing_statuses", {"statusError", "statusInvalid"}, {"statusError"}, set),
    ("quality_gates_shellcheck_failing_levels", {"error", "warning"}, {"error"}, set),
    ("quality_gates_shellcheck_shell_names", {"sh", "bash", "dash", "ksh"}, {"sh", "bash"}, set),
    ("quality_gates_yamllint_failing_rules", {"key-duplicates", "syntax"}, {"syntax"}, set),
    ("quality_gates_markdown_disabled_rules", ["md013", "md014"], ["md013"], list),
    ("quality_gates_kube_score_check_id", "container-resources", "custom-check", None),
    ("helm_doc_max_diff_lines_shown", 40, 100, None),
    (
        "vendor_classification_keywords",
        {
            "maykinmedia": "Maykin",
            "infonl": "Info(NL)",
            "worth-nl": "Worth",
            "wearefrank": "WeAreFrank",
            "dimpact": "Dimpact",
            "icatt-menselijk-digitaal": "ICATT",
        },
        {"maykinmedia": "Maykin", "infonl": "Info(NL)"},
        dict,
    ),
    ("vendor_classification_chart_overrides", {"kiss": "ICATT"}, {"kiss": "ICATT", "foo": "Bar"}, dict),
    (
        "helm_repos_urls_by_alias",
        {
            "adfinis": "https://charts.adfinis.com",
            "wiremind": "https://wiremind.github.io/wiremind-helm-charts",
            "dimpact": "https://Dimpact-Samenwerking.github.io/helm-charts/",
            "maykinmedia": "https://maykinmedia.github.io/charts/",
            "kiss-elastic": "https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic",
            "zac": "https://infonl.github.io/dimpact-zaakafhandelcomponent/",
            "zgw-office-addin": "https://infonl.github.io/zgw-office-addin",
            "worth-nl": "https://worth-nl.github.io/helm-charts",
            "opstree": "https://ot-container-kit.github.io/helm-charts/",
        },
        {"zac": "https://example.invalid/zac/"},
        dict,
    ),
    (
        "component_resolution_chart_version_lockstep_components",
        frozenset({"kiss-chart", "pabc", "eck-operator"}),
        frozenset({"kiss-chart", "pabc"}),
        frozenset,
    ),
    ("component_resolution_native_components", frozenset({"frankgateway"}), frozenset({"other-native"}), frozenset),
    (
        "component_resolution_version_repository_paths",
        {"redis-operator": "redisOperator.imageName"},
        {"redis-operator": "redisOperator.imageName", "foo-op": "fooOperator.imageName"},
        dict,
    ),
    (
        "component_resolution_version_path_nested_subcharts",
        {
            "eck-stack": {
                "eck-elasticsearch.version": "eck-elasticsearch",
                "eck-kibana.version": "eck-kibana",
                "eck-enterprise-search.version": "eck-enterprise-search",
            }
        },
        {"eck-stack": {"eck-elasticsearch.version": "eck-elasticsearch"}},
        dict,
    ),
    (
        "component_resolution_image_paths",
        {
            "zgw-office-addin": ["frontend.image", "backend.image"],
            "keycloak-operator": ["operator.config.keycloakImage"],
            "openbao": ["server.image"],
            "internetaakafhandeling": ["web.image", "poller.image"],
            "kiss-chart": ["image", "settings.syncJobs.image"],
            "eck-operator": ["image"],
        },
        {"widget": ["image"]},
        dict,
    ),
    ("component_resolution_default_image_paths", ["image"], ["custom-default-image"], list),
    (
        "component_resolution_version_paths",
        {
            "eck-stack": ["eck-elasticsearch.version", "eck-kibana.version"],
            "redis-operator": ["redisOperator.imageTag"],
        },
        {"widget-b": ["version"]},
        dict,
    ),
]


def test_every_accessor_documented_and_present(libsettings):
    """Guards against a typo'd/missing accessor name silently dropping a
    case out of the parametrized tests below."""
    for name, *_ in ACCESSOR_CASES:
        assert hasattr(libsettings, name), f"lib.settings.{name} missing"


def test_missing_settings_file_falls_back_to_defaults(libsettings, tmp_path):
    for name, default, _override, _cast in ACCESSOR_CASES:
        accessor = getattr(libsettings, name)
        assert accessor(tmp_path) == default


def test_no_etc_directory_at_all_does_not_crash(libsettings, tmp_path):
    """chart_dir has no etc/ directory whatsoever (not just a missing
    settings.yaml inside an existing etc/) — mirrors lib.chart.
    _release_baselines' own tolerance for this."""
    assert libsettings._load_settings(tmp_path) == {}
    for name, default, _override, _cast in ACCESSOR_CASES:
        assert getattr(libsettings, name)(tmp_path) == default


def test_full_settings_file_overrides_every_default(libsettings, tmp_path):
    write_settings(tmp_path, FULL_SETTINGS)
    for name, _default, override, cast in ACCESSOR_CASES:
        accessor = getattr(libsettings, name)
        result = accessor(tmp_path)
        assert result == override
        if cast is not None:
            assert isinstance(result, cast)


def test_partial_settings_file_mixes_overrides_and_defaults(libsettings, tmp_path):
    """Only dry_check is present — every dry_check accessor reads its
    override, every other accessor (including ones in wholly-absent
    sections like cve_scan) falls back to its default without crashing."""
    write_settings(
        tmp_path,
        {
            "dry_check": {
                "similarity_threshold": 0.5,
                "high_similarity_threshold": 0.8,
                "min_significant_lines": 12,
            },
        },
    )
    assert libsettings.dry_check_similarity_threshold(tmp_path) == 0.5
    assert libsettings.dry_check_high_similarity_threshold(tmp_path) == 0.8
    assert libsettings.dry_check_min_significant_lines(tmp_path) == 12

    # cve_scan section is entirely absent from this file
    assert libsettings.cve_high_severity_levels(tmp_path) == {"CRITICAL", "HIGH"}
    assert libsettings.cve_max_cves_per_package_before_summarizing(tmp_path) == 5
    assert libsettings.cve_scan_cache_ttl_days(tmp_path) == 7

    # a section present but missing one of its keys
    write_settings(
        tmp_path,
        {
            "release_secret": {
                "kubernetes_secret_limit_bytes": 2097152,
                # warn_at_fraction_of_limit intentionally omitted
            },
        },
    )
    assert libsettings.release_secret_kubernetes_limit_bytes(tmp_path) == 2097152
    assert libsettings.release_secret_warn_at_fraction_of_limit(tmp_path) == 0.90


def test_empty_settings_file_does_not_crash(libsettings, tmp_path):
    """An etc/settings.yaml that exists but parses to None (e.g. an empty
    file) must behave exactly like a missing one."""
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text("", encoding="utf-8")
    assert libsettings._load_settings(tmp_path) == {}
    for name, default, _override, _cast in ACCESSOR_CASES:
        assert getattr(libsettings, name)(tmp_path) == default


# --- digest_pinning_exceptions ---
#
# Returns a shape too irregular (tuple-path keys, nested per-entry dicts
# with their own normalization) to fit ACCESSOR_CASES' single cast-
# constructor convention above -- tested standalone instead, following
# the exact same missing-file/full-file/partial-file pattern.

DEFAULT_DIGEST_PINNING_EXCEPTIONS = {
    ("keycloak-operator", "operator", "image"): {"sibling_field": "sha", "writable": True},
    ("keycloak-operator", "operator", "config", "keycloakImage"): {"sibling_field": "sha", "writable": True},
    ("keycloak", "image"): {"sibling_field": "sha", "writable": True},
    ("eck-operator", "image"): {"sibling_field": "digest", "writable": True},
    ("omc", "image"): {"sibling_field": None, "writable": False},
}


def test_digest_pinning_exceptions_missing_file_matches_todays_five_entry_table(libsettings, tmp_path):
    """No etc/settings.yaml at all -- falls back to exactly today's real
    5-entry table (the one this iteration unified out of lib.chart.
    SPLIT_TAG_SHA_PATHS, lib.checks.digest_pinning.EXEMPT_PATHS, and
    update-component-version's own separate write-side allowlist)."""
    assert libsettings.digest_pinning_exceptions(tmp_path) == DEFAULT_DIGEST_PINNING_EXCEPTIONS


def test_digest_pinning_exceptions_full_file_override(libsettings, tmp_path):
    write_settings(
        tmp_path,
        {
            "digest_pinning": {
                "exceptions": {
                    "some-component.image": {"sibling_field": "digest", "writable": True},
                    "other-component.image": {},
                },
            },
        },
    )
    assert libsettings.digest_pinning_exceptions(tmp_path) == {
        ("some-component", "image"): {"sibling_field": "digest", "writable": True},
        ("other-component", "image"): {"sibling_field": None, "writable": False},
    }


def test_digest_pinning_exceptions_partial_entry_defaults_missing_keys(libsettings, tmp_path):
    """An entry that only sets one of sibling_field/writable still comes
    back with BOTH keys present (the other defaulted) -- callers never
    need their own .get() dance."""
    write_settings(
        tmp_path,
        {
            "digest_pinning": {
                "exceptions": {
                    "writable-no-sibling.image": {"writable": True},
                    "sibling-not-writable.image": {"sibling_field": "sha"},
                },
            },
        },
    )
    result = libsettings.digest_pinning_exceptions(tmp_path)
    assert result[("writable-no-sibling", "image")] == {"sibling_field": None, "writable": True}
    assert result[("sibling-not-writable", "image")] == {"sibling_field": "sha", "writable": False}
