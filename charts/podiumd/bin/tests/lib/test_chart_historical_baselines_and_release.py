"""lib.chart_historical_baselines — historical images-manifest lookups
(historical_images_manifest_paths, historical_app_version_for_
repository, historical_app_version_for_path) — and lib.chart_release_
baseline_basics.write_release_baselines. Split out of the former
test_chart.py (see test_chart_path_and_version_helpers.py for
upgrade_docs_baseline/release_table_baseline reads, and the other
test_chart_*.py files for the rest)."""


# --- historical_images_manifest_paths / historical_app_version_for_repository ---
# the replacement for the removed images-baseline.yaml fallback: walks
# this chart's own past docs/images/images-<version>.yaml manifests,
# most-recent-first, instead of a separate cumulative side-file.


def _write_images_manifest(images_dir, version, entries):
    """`url` defaults to `name` when an entry doesn't give one of its own
    — fine for historical_app_version_for_repository's own tests (called
    with a bare repo string, no expected_url to cross-check at all), but
    a caller exercising historical_app_version_for_path's own url cross-
    check (see its own docstring) must pass a REAL, host-qualified "url"
    explicitly, matching what full_repository_for_path would actually
    resolve for its test's own path — a bare url identical to `name`
    isn't what any real images-manifest entry ever looks like."""
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / f"images-{version}.yaml").write_text(
        "".join(
            f'- name: {e["name"]}\n  url: {e.get("url", e["name"])}\n  version: "{e["version"]}"\n'
            f'  digest: "{e["digest"]}"\n'
            for e in entries
        ),
        encoding="utf-8",
    )


def test_historical_images_manifest_paths_sorts_most_recent_first(libcharthistoricalbaselines, tmp_path):
    images_dir = tmp_path / "docs" / "images"
    for version in ("4.7.0", "4.9.0", "4.8.5"):
        _write_images_manifest(images_dir, version, [])
    paths = libcharthistoricalbaselines.historical_images_manifest_paths(tmp_path)
    assert [p.name for p in paths] == ["images-4.9.0.yaml", "images-4.8.5.yaml", "images-4.7.0.yaml"]


def test_historical_images_manifest_paths_excludes_versions_after_at_or_before(libcharthistoricalbaselines, tmp_path):
    images_dir = tmp_path / "docs" / "images"
    for version in ("4.7.0", "4.8.5", "4.9.0", "4.9.1"):
        _write_images_manifest(images_dir, version, [])
    paths = libcharthistoricalbaselines.historical_images_manifest_paths(tmp_path, at_or_before="4.9.0")
    assert [p.name for p in paths] == ["images-4.9.0.yaml", "images-4.8.5.yaml", "images-4.7.0.yaml"]


def test_historical_images_manifest_paths_ignores_non_semver_names(libcharthistoricalbaselines, tmp_path):
    """images-baseline.yaml itself (the removed side-file) never parses
    as a bare "X.Y.Z" version — silently skipped, never mistaken for a
    real release."""
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "images-baseline.yaml").write_text("[]\n", encoding="utf-8")
    _write_images_manifest(images_dir, "4.8.5", [])
    paths = libcharthistoricalbaselines.historical_images_manifest_paths(tmp_path)
    assert [p.name for p in paths] == ["images-4.8.5.yaml"]


def test_historical_images_manifest_paths_empty_when_dir_missing(libcharthistoricalbaselines, tmp_path):
    assert libcharthistoricalbaselines.historical_images_manifest_paths(tmp_path) == []
    assert libcharthistoricalbaselines.historical_images_manifest_paths(None) == []


def test_historical_app_version_for_repository_stops_at_most_recent_match(libcharthistoricalbaselines, tmp_path):
    """Two past manifests both mention the same repository, at DIFFERENT
    versions — the most recent one (searched first) wins, not the
    oldest."""
    images_dir = tmp_path / "docs" / "images"
    _write_images_manifest(
        images_dir, "4.7.0", [{"name": "brp-api/personen-mock", "version": "2.5.0", "digest": "sha256:aaaa"}]
    )
    _write_images_manifest(
        images_dir, "4.8.5", [{"name": "brp-api/personen-mock", "version": "2.6.0", "digest": "sha256:bbbb"}]
    )

    assert (
        libcharthistoricalbaselines.historical_app_version_for_repository(
            tmp_path, "brp-api/personen-mock", at_or_before="4.9.0"
        )
        == "2.6.0"
    )


def test_historical_app_version_for_repository_none_when_never_mentioned(libcharthistoricalbaselines, tmp_path):
    images_dir = tmp_path / "docs" / "images"
    _write_images_manifest(
        images_dir, "4.8.5", [{"name": "some-other/image", "version": "1.0.0", "digest": "sha256:aaaa"}]
    )

    assert (
        libcharthistoricalbaselines.historical_app_version_for_repository(
            tmp_path, "brp-api/personen-mock", at_or_before="4.9.0"
        )
        is None
    )


def test_historical_app_version_for_repository_ignores_manifests_after_at_or_before(
    libcharthistoricalbaselines, tmp_path
):
    """A repository that only ever appears in a LATER release's own
    manifest (e.g. the in-progress target's own images-<target>.yaml)
    is never found — the search never looks forward, avoiding the
    circularity of a "changed vs baseline" check feeding on its own
    target manifest."""
    images_dir = tmp_path / "docs" / "images"
    _write_images_manifest(
        images_dir, "4.9.0", [{"name": "brp-api/personen-mock", "version": "2.7.0", "digest": "sha256:bbbb"}]
    )

    assert (
        libcharthistoricalbaselines.historical_app_version_for_repository(
            tmp_path, "brp-api/personen-mock", at_or_before="4.8.5"
        )
        is None
    )


def test_historical_app_version_for_path_resolves_repo_then_searches(libcharthistoricalbaselines, tmp_path):
    images_dir = tmp_path / "docs" / "images"
    _write_images_manifest(
        images_dir,
        "4.8.0",
        [
            {
                "name": "brp-api/personen-mock",
                "url": "ghcr.io/brp-api/personen-mock",
                "version": "2.5.0",
                "digest": "sha256:aaaa",
            }
        ],
    )
    deps = [{"name": "brppersonenmock", "version": "1.2.9"}]
    values = {"brppersonenmock": {"image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0@sha256:bbbb"}}}

    assert (
        libcharthistoricalbaselines.historical_app_version_for_path(
            tmp_path, deps, values, ("brppersonenmock", "image"), at_or_before="4.8.5"
        )
        == "2.5.0"
    )


def test_historical_app_version_for_path_rejects_stripped_name_collision(libcharthistoricalbaselines, tmp_path):
    """Real bug, real data: global.images.redis (added in 4.9.1, bare
    repository "redis") and redis-operator's own quay.io/opstree/redis
    both strip to the exact same bare name "redis" — but images-
    4.6.4.yaml's own real "redis" entry (url: quay.io/opstree/redis) is
    redis-operator's OWN old version, recorded under a bare "name:" from
    before this repo's own strip-registry naming convention was
    consistently applied everywhere. An exact "name:" match alone wrongly
    returns it as if it were global.images.redis's own history; cross-
    checking the historical entry's own "url:" against the CURRENT
    path's real, fully-qualified repository (docker.io/redis, Docker
    Hub's own implicit host) correctly rejects it instead."""
    images_dir = tmp_path / "docs" / "images"
    _write_images_manifest(
        images_dir,
        "4.6.4",
        [{"name": "redis", "url": "quay.io/opstree/redis", "version": "v8.6.2", "digest": "sha256:aaaa"}],
    )
    deps = []
    values = {"global": {"images": {"redis": {"repository": "redis", "tag": "8.0@sha256:bbbb"}}}}

    assert (
        libcharthistoricalbaselines.historical_app_version_for_path(
            tmp_path, deps, values, ("global", "images", "redis"), at_or_before="4.9.0"
        )
        is None
    )


def test_historical_app_version_for_repository_url_mismatch_is_not_a_match(libcharthistoricalbaselines, tmp_path):
    """The same collision, exercised directly against historical_app_
    version_for_repository's own expected_url parameter — the lower-
    level primitive historical_app_version_for_path builds on."""
    images_dir = tmp_path / "docs" / "images"
    _write_images_manifest(
        images_dir,
        "4.6.4",
        [{"name": "redis", "url": "quay.io/opstree/redis", "version": "v8.6.2", "digest": "sha256:aaaa"}],
    )

    assert (
        libcharthistoricalbaselines.historical_app_version_for_repository(
            tmp_path, "redis", at_or_before="4.9.0", expected_url="docker.io/redis"
        )
        is None
    )
    # Without expected_url, the exact previous name-only behavior is
    # preserved (a caller with no path/deps/values of its own to resolve
    # a real url from) — still finds the (wrong-for-redis, but that's
    # the caller's own problem to avoid by always passing expected_url
    # when it has one) name-only match.
    assert (
        libcharthistoricalbaselines.historical_app_version_for_repository(tmp_path, "redis", at_or_before="4.9.0")
        == "v8.6.2"
    )
    # A matching url, on the other hand, IS a real match.
    assert (
        libcharthistoricalbaselines.historical_app_version_for_repository(
            tmp_path, "redis", at_or_before="4.9.0", expected_url="quay.io/opstree/redis"
        )
        == "v8.6.2"
    )


def test_historical_app_version_for_path_none_when_path_unresolvable(libcharthistoricalbaselines, tmp_path):
    """No dependency/override resolves a repository for this path at
    all — nothing to search images-<version>.yaml for."""
    assert (
        libcharthistoricalbaselines.historical_app_version_for_path(
            tmp_path, [], {}, ("brppersonenmock", "image"), at_or_before="4.8.5"
        )
        is None
    )


# --- write_release_baselines ---


def test_write_release_baselines_creates_file_with_both_keys(libchartreleasebaselinebasics, tmp_path):
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == "4.9.0"
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) == "4.8.5"


def test_write_release_baselines_updates_only_upgrade_docs_leaves_release_table(
    libchartreleasebaselinebasics, tmp_path
):
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.1")
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == "4.9.1"
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) == "4.8.5"


def test_write_release_baselines_updates_only_release_table_leaves_upgrade_docs(
    libchartreleasebaselinebasics, tmp_path
):
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, release_table="4.9.0")
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == "4.9.0"
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) == "4.9.0"


def test_write_release_baselines_no_args_leaves_both_unchanged(libchartreleasebaselinebasics, tmp_path):
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    libchartreleasebaselinebasics.write_release_baselines(tmp_path)
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == "4.9.0"
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) == "4.8.5"


def test_write_release_baselines_values_are_double_quoted(libchartreleasebaselinebasics, tmp_path):
    """Real bug, confirmed live: plain yaml.safe_dump only quotes a
    scalar when it's ambiguous with another YAML type (int/float/bool/
    null) — a version string like "4.9.1" (two dots, never a valid
    number) is never ambiguous, so it came out bare ("upgrade_docs:
    4.9.1", no quotes) — inconsistent with this codebase's own
    established YAML-writing convention (e.g. images-<version>.yaml's
    own `version: "3.1.1"`). Keys stay bare — only the values are
    quoted."""
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.1", release_table="4.8.5")
    text = (tmp_path / "etc" / "release-baseline.yaml").read_text(encoding="utf-8")
    assert text == 'upgrade_docs: "4.9.1"\nrelease_table: "4.8.5"\n'


def test_write_release_baselines_escapes_backslash_and_double_quote_correctly(libchartreleasebaselinebasics, tmp_path):
    """The quoting must come from PyYAML's own scalar emitter, never
    hand-rolled string interpolation (f'{key}: "{value}"\\n') — a value
    containing a literal backslash or an embedded double-quote
    character needs YAML's own backslash-escape rules applied
    correctly, or the file becomes invalid (or silently wrong-meaning)
    YAML. Round-tripped through the real read path (upgrade_docs_
    baseline, which calls yaml.safe_load) to prove it, not just
    eyeballing the written text."""
    pathological = 'has "quotes" and a \\ backslash'
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs=pathological)
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == pathological

    text = (tmp_path / "etc" / "release-baseline.yaml").read_text(encoding="utf-8")
    assert text == 'upgrade_docs: "has \\"quotes\\" and a \\\\ backslash"\n'
