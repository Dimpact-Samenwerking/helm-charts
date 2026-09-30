"""lib.chart: historical images-manifest lookups and write_release_baselines."""

from pathlib import Path
from types import ModuleType

# --- historical_images_manifest_paths / historical_app_version_for_repository ---


def _write_images_manifest(images_dir, version, entries):
    """Write images-<version>.yaml; `url` defaults to `name`.

    Tests of historical_app_version_for_path's url cross-check must pass a
    real host-qualified "url".
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / f"images-{version}.yaml").write_text(
        "".join(
            f'- name: {e["name"]}\n  url: {e.get("url", e["name"])}\n  version: "{e["version"]}"\n'
            f'  digest: "{e["digest"]}"\n'
            for e in entries
        ),
        encoding="utf-8",
    )


def test_historical_images_manifest_paths_sorts_most_recent_first(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
    images_dir = tmp_path / "docs" / "images"
    for version in ("4.7.0", "4.9.0", "4.8.5"):
        _write_images_manifest(images_dir, version, [])
    paths = libcharthistoricalbaselines.historical_images_manifest_paths(tmp_path)
    assert [p.name for p in paths] == ["images-4.9.0.yaml", "images-4.8.5.yaml", "images-4.7.0.yaml"]


def test_historical_images_manifest_paths_excludes_versions_after_at_or_before(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
    images_dir = tmp_path / "docs" / "images"
    for version in ("4.7.0", "4.8.5", "4.9.0", "4.9.1"):
        _write_images_manifest(images_dir, version, [])
    paths = libcharthistoricalbaselines.historical_images_manifest_paths(tmp_path, at_or_before="4.9.0")
    assert [p.name for p in paths] == ["images-4.9.0.yaml", "images-4.8.5.yaml", "images-4.7.0.yaml"]


def test_historical_images_manifest_paths_ignores_non_semver_names(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
    """Non-version names like images-baseline.yaml are skipped."""
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "images-baseline.yaml").write_text("[]\n", encoding="utf-8")
    _write_images_manifest(images_dir, "4.8.5", [])
    paths = libcharthistoricalbaselines.historical_images_manifest_paths(tmp_path)
    assert [p.name for p in paths] == ["images-4.8.5.yaml"]


def test_historical_images_manifest_paths_empty_when_dir_missing(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
    assert libcharthistoricalbaselines.historical_images_manifest_paths(tmp_path) == []
    assert libcharthistoricalbaselines.historical_images_manifest_paths(None) == []


def test_historical_app_version_for_repository_stops_at_most_recent_match(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
    """The most recent manifest mentioning the repository wins."""
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


def test_historical_app_version_for_repository_none_when_never_mentioned(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
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
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
    """Manifests after at_or_before are ignored, so a check never compares against its own target."""
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


def test_historical_app_version_for_path_resolves_repo_then_searches(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
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


def test_historical_app_version_for_path_rejects_stripped_name_collision(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
    """A bare-name match with a different "url:" is rejected.

    "redis" in images-4.6.4.yaml is quay.io/opstree/redis, not
    global.images.redis (docker.io/redis).
    """
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


def test_historical_app_version_for_repository_url_mismatch_is_not_a_match(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
    """Same collision via historical_app_version_for_repository's expected_url."""
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
    # Without expected_url, matching is by name only.
    assert (
        libcharthistoricalbaselines.historical_app_version_for_repository(tmp_path, "redis", at_or_before="4.9.0")
        == "v8.6.2"
    )
    assert (
        libcharthistoricalbaselines.historical_app_version_for_repository(
            tmp_path, "redis", at_or_before="4.9.0", expected_url="quay.io/opstree/redis"
        )
        == "v8.6.2"
    )


def test_historical_app_version_for_path_none_when_path_unresolvable(
    libcharthistoricalbaselines: ModuleType, tmp_path: Path
):
    """A path with no resolvable repository returns None."""
    assert (
        libcharthistoricalbaselines.historical_app_version_for_path(
            tmp_path, [], {}, ("brppersonenmock", "image"), at_or_before="4.8.5"
        )
        is None
    )


# --- write_release_baselines ---


def test_write_release_baselines_creates_file_with_both_keys(libchartreleasebaselinebasics: ModuleType, tmp_path: Path):
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == "4.9.0"
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) == "4.8.5"


def test_write_release_baselines_updates_only_upgrade_docs_leaves_release_table(
    libchartreleasebaselinebasics: ModuleType, tmp_path: Path
):
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.1")
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == "4.9.1"
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) == "4.8.5"


def test_write_release_baselines_updates_only_release_table_leaves_upgrade_docs(
    libchartreleasebaselinebasics: ModuleType, tmp_path: Path
):
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, release_table="4.9.0")
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == "4.9.0"
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) == "4.9.0"


def test_write_release_baselines_no_args_leaves_both_unchanged(
    libchartreleasebaselinebasics: ModuleType, tmp_path: Path
):
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    libchartreleasebaselinebasics.write_release_baselines(tmp_path)
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == "4.9.0"
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) == "4.8.5"


def test_write_release_baselines_values_are_double_quoted(libchartreleasebaselinebasics: ModuleType, tmp_path: Path):
    """Values are double-quoted, keys bare, matching the repo's YAML convention.

    yaml.safe_dump alone leaves unambiguous scalars like "4.9.1" unquoted.
    """
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs="4.9.1", release_table="4.8.5")
    text = (tmp_path / "etc" / "release-baseline.yaml").read_text(encoding="utf-8")
    assert text == 'upgrade_docs: "4.9.1"\nrelease_table: "4.8.5"\n'


def test_write_release_baselines_escapes_backslash_and_double_quote_correctly(
    libchartreleasebaselinebasics: ModuleType, tmp_path: Path
):
    """Backslashes and double quotes are escaped by PyYAML and round-trip through the reader."""
    pathological = 'has "quotes" and a \\ backslash'
    libchartreleasebaselinebasics.write_release_baselines(tmp_path, upgrade_docs=pathological)
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == pathological

    text = (tmp_path / "etc" / "release-baseline.yaml").read_text(encoding="utf-8")
    assert text == 'upgrade_docs: "has \\"quotes\\" and a \\\\ backslash"\n'
