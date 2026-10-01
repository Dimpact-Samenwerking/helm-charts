"""fix_images_manifest_entry_urls and add_missing_images_manifest_entries scenarios."""

import io
import tarfile

from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
import yaml

import lib.fix_doc_consistency.manifest_entries_new_and_urls as manifest_entries_new_and_urls

from lib.fix_doc_consistency.manifest_entries_new_and_urls import MissingEntriesContext
from lib.fix_doc_consistency.manifest_entries_new_and_urls import add_missing_images_manifest_entries
from lib.fix_doc_consistency.manifest_entries_new_and_urls import fix_images_manifest_entry_names
from lib.fix_doc_consistency.manifest_entries_new_and_urls import fix_images_manifest_entry_urls
from lib.fix_doc_consistency.manifest_entries_new_and_urls import remove_stale_images_manifest_entries

if TYPE_CHECKING:
    from lib.chart.chart_yaml import ChartDependency
    from lib.yaml_types import YamlMapping


def write(path, text):
    path.write_text(text, encoding="utf-8")


def make_tgz(charts_dir, name, version, values, raw_files=None):
    """A minimal vendored <name>-<version>.tgz; raw_files maps tar paths to verbatim text.

    Duplicates tests/lib/test_chart.py's make_tgz: test helpers are not importable across test files.
    """
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump(values).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for internal_path, text in (raw_files or {}).items():
            raw_data = text.encode("utf-8")
            raw_info = tarfile.TarInfo(name=internal_path)
            raw_info.size = len(raw_data)
            tar.addfile(raw_info, io.BytesIO(raw_data))
    return tgz_path


# --- fix_images_manifest_entry_urls ---


def test_fix_images_manifest_entry_urls_restores_stripped_host(cdb: ModuleType, tmp_path: Path):
    """An existing entry whose url lost its registry host gets the host restored."""
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {
                    "opentelemetry-collector": {
                        "image": {"repository": "otel/opentelemetry-collector-contrib", "tag": "0.158.0@sha256:aaaa"}
                    }
                },
            }
        ),
    )
    text = (
        "#   sidecar: zac - opentelemetry-collector-contrib 0.158.0 (new)\n"
        "- name: otel/opentelemetry-collector-contrib\n"
        "  url: otel/opentelemetry-collector-contrib\n"
        '  version: "0.158.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {
        "zac": {
            "opentelemetry-collector": {
                "image": {"repository": "otel/opentelemetry-collector-contrib", "tag": "0.158.0@sha256:aaaa"}
            }
        }
    }

    repo_map = {"otel/opentelemetry-collector-contrib": ("zac", "opentelemetry-collector", "image")}
    new_text, changed, unresolved = fix_images_manifest_entry_urls(text, tmp_path, deps, target_values, repo_map)

    assert unresolved == []
    assert changed == [
        (
            "otel/opentelemetry-collector-contrib",
            "otel/opentelemetry-collector-contrib",
            "docker.io/otel/opentelemetry-collector-contrib",
        )
    ]
    assert "url: docker.io/otel/opentelemetry-collector-contrib" in new_text
    assert "url: otel/opentelemetry-collector-contrib\n" not in new_text


def test_fix_images_manifest_entry_urls_leaves_correct_url_untouched(cdb: ModuleType, images_manifest_chart_dir):
    text = (
        "# zac 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}}
    }

    repo_map = {"infonl/zaakafhandelcomponent": ("zac", "image")}
    new_text, changed, unresolved = fix_images_manifest_entry_urls(
        text, images_manifest_chart_dir, deps, target_values, repo_map
    )
    assert changed == []
    assert unresolved == []
    assert new_text == text


def test_fix_images_manifest_entry_urls_reports_url_line_with_trailing_text(cdb: ModuleType, images_manifest_chart_dir):
    """A "url:" line with trailing text (a comment) is reported as unresolved and left as is, not a crash."""
    text = (
        "# zac 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent  # primary image\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}}
    }

    repo_map = {"infonl/zaakafhandelcomponent": ("zac", "image")}
    new_text, changed, unresolved = fix_images_manifest_entry_urls(
        text, images_manifest_chart_dir, deps, target_values, repo_map
    )
    assert changed == []
    assert unresolved == ["infonl/zaakafhandelcomponent"]
    assert new_text == text


def test_fix_images_manifest_entry_urls_reports_unresolvable_entry(cdb: ModuleType, tmp_path: Path):
    write(tmp_path / "Chart.yaml", yaml.safe_dump({"dependencies": []}))
    write(tmp_path / "values.yaml", yaml.safe_dump({}))
    text = '- name: totally-unknown\n  url: example.com/totally-unknown\n  version: "1.0.0"\n'

    new_text, changed, unresolved = fix_images_manifest_entry_urls(text, tmp_path, [], {})
    assert changed == []
    assert unresolved == ["totally-unknown"]
    assert new_text == text


# --- add_missing_images_manifest_entries ---


@pytest.fixture
def images_manifest_chart_dir(tmp_path: Path):
    """Chart.yaml + values.yaml on disk: find_images_without_repository reads them itself."""
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
            }
        ),
    )
    return tmp_path


def test_add_missing_images_manifest_entries_appends_new_entry(cdb: ModuleType, images_manifest_chart_dir):
    text = "# Baseline: podiumd 4.8.5.\n"
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}}
    }
    baseline_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}}
    }

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert skipped == []
    assert added == ["zac"]
    assert "# zac 5.0.2 -> 5.1.0" in new_text  # primary: plain "# " prefix, no em-dash
    assert "- name: infonl/zaakafhandelcomponent" in new_text
    assert "url: ghcr.io/infonl/zaakafhandelcomponent" in new_text
    assert 'version: "5.1.0"' in new_text
    assert 'digest: "sha256:aaaa"' in new_text


def test_add_missing_images_manifest_entries_genuinely_new_image_renders_new(
    cdb: ModuleType, images_manifest_chart_dir
):
    """A brand-new image (no baseline, no historical manifest) renders "(new)", not a self-transition."""
    text = "# Baseline: podiumd 4.8.5.\n"
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {
        "zac": {
            "opentelemetry-collector": {
                "image": {"repository": "otel/opentelemetry-collector-contrib", "tag": "0.158.0@sha256:" + "a" * 64}
            }
        }
    }
    baseline_values: YamlMapping = {}

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert skipped == []
    assert added == ["zac - opentelemetry-collector-contrib"]
    assert "opentelemetry-collector-contrib 0.158.0 (new)" in new_text
    assert "0.158.0 -> 0.158.0" not in new_text
    assert "(digest changed)" not in new_text


def test_add_missing_images_manifest_entries_moved_repository_gets_real_transition(cdb: ModuleType, tmp_path: Path):
    """A repository that moved anchors (postgres into global.images) renders its real transition, not "(new)"."""
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [{"name": "openbao", "version": "2.0.0"}],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "global": {"images": {"postgres": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}},
                "openbao": {
                    "database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}}
                },
            }
        ),
    )
    text = "# Baseline: podiumd 4.8.5.\n"
    deps: list[ChartDependency] = [{"name": "openbao", "version": "2.0.0"}]
    target_values: YamlMapping = {
        "global": {"images": {"postgres": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}},
        "openbao": {
            "database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}}
        },
    }
    baseline_values: YamlMapping = {
        "openbao": {"database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16-alpine@sha256:bbbb"}}}},
    }

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            tmp_path,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert skipped == []
    assert added == ["postgres"]
    assert "# postgres 16-alpine -> 16.15-alpine" in new_text
    assert "(new)" not in new_text


def test_add_missing_images_manifest_entries_catches_same_version_changed_digest(
    cdb: ModuleType, images_manifest_chart_dir
):
    """A same-version, changed-digest re-pin is added, not only detected.

    Guards that the list-diff call here passes both `values=` and `baseline_values=`.
    """
    text = "# Baseline: podiumd 4.8.5.\n"
    deps: list[ChartDependency] = [{"name": "clamav", "version": "1.0.0"}]
    target_values: YamlMapping = {
        "clamav": {"image": {"repository": "clamav/clamav", "tag": "1.5.4@sha256:" + "b" * 64}}
    }
    baseline_values: YamlMapping = {
        "clamav": {"image": {"repository": "clamav/clamav", "tag": "1.5.4@sha256:" + "a" * 64}}
    }

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert skipped == []
    assert added == ["clamav"]
    assert "- name: clamav/clamav" in new_text
    assert f'digest: "sha256:{"b" * 64}"' in new_text
    # Both the "# Changes:" item and the entry comment share version_text: neither may read "<v> -> <v>".
    assert "clamav 1.5.4 (digest changed)" in new_text
    assert "clamav 1.5.4 -> 1.5.4" not in new_text


def test_add_missing_images_manifest_entries_name_is_stripped_url_is_fully_qualified(
    cdb: ModuleType, images_manifest_chart_dir
):
    """The "name:" is the stripped repo_map key; the "url:" is the fully host-qualified repository, since a
    hostless url is wrong for Docker Hub images."""
    text = ""
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}}
    }

    new_text, added, _skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values={},
        ),
    )
    assert added == ["zac"]
    assert "- name: infonl/zaakafhandelcomponent" in new_text
    assert "url: ghcr.io/infonl/zaakafhandelcomponent" in new_text


def test_add_missing_images_manifest_entries_real_version_bump_keeps_arrow_wording(
    cdb: ModuleType, images_manifest_chart_dir
):
    """A real version bump keeps "<old> -> <new>"; "(digest changed)" is only for same-version re-pins."""
    text = ""
    deps: list[ChartDependency] = [{"name": "curl", "version": "1.0.0"}]
    target_values: YamlMapping = {
        "curl": {"image": {"repository": "curlimages/curl", "tag": "8.22.0@sha256:" + "b" * 64}}
    }
    baseline_values: YamlMapping = {
        "curl": {"image": {"repository": "curlimages/curl", "tag": "8.21.0@sha256:" + "a" * 64}}
    }

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert skipped == []
    assert added == ["curl"]
    assert "curl 8.21.0 -> 8.22.0" in new_text
    assert "digest changed" not in new_text


def test_add_missing_images_manifest_entries_docker_hub_repository_gets_docker_io_host(
    cdb: ModuleType, images_manifest_chart_dir
):
    """A hostless Docker Hub "repository:" gets a "docker.io/..." url."""
    text = ""
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {"zac": {"image": {"repository": "curlimages/curl", "tag": "8.22.0@sha256:aaaa"}}}

    new_text, added, _skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values={},
        ),
    )
    assert added == ["zac"]
    assert "- name: curlimages/curl" in new_text
    assert "url: docker.io/curlimages/curl" in new_text


def test_add_missing_images_manifest_entries_separate_registry_key_is_used_for_url(
    cdb: ModuleType, images_manifest_chart_dir
):
    """A sibling "registry:" key is authoritative for the url, not parse_repo's Docker Hub inference."""
    text = ""
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {
        "zac": {"image": {"registry": "mcr.microsoft.com", "repository": "azure-cli", "tag": "2.90.0@sha256:aaaa"}}
    }

    new_text, added, _skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values={},
        ),
    )
    assert added == ["zac"]
    assert "- name: azure-cli" in new_text
    assert "url: mcr.microsoft.com/azure-cli" in new_text


def test_add_missing_images_manifest_entries_noop_when_entry_already_covers_it(
    cdb: ModuleType, images_manifest_chart_dir
):
    text = (
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}}
    }
    baseline_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}}
    }

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )
    assert added == []
    assert skipped == []
    assert new_text == text


def test_add_missing_images_manifest_entries_skips_when_no_digest_pinned(cdb: ModuleType, images_manifest_chart_dir):
    """A tag without "@sha256:" is reported as skipped, not written incomplete (digest is required)."""
    write(
        images_manifest_chart_dir / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0"}},
            }
        ),
    )
    text = ""
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0"}}
    }
    baseline_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}}
    }

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )
    assert added == []
    assert skipped == ["zac"]
    assert new_text == text


def test_add_missing_images_manifest_entries_eck_operator_split_digest_field_resolves(
    cdb: ModuleType, images_manifest_chart_dir
):
    """eck-operator's split "tag:"/"digest:" pin resolves its digest from the "digest:" sibling."""
    text = "# Baseline: podiumd 4.9.1.\n"
    deps: list[ChartDependency] = [{"name": "eck-operator", "version": "3.5.0"}]
    target_values: YamlMapping = {
        "eck-operator": {
            "enabled": True,
            "image": {
                "repository": "docker.elastic.co/eck/eck-operator",
                "tag": "3.5.0",
                "digest": "sha256:" + "b" * 64,
            },
        }
    }
    baseline_values: YamlMapping = {"eck-operator": {"enabled": True}}

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert skipped == []
    assert added == ["eck-operator"]
    assert "url: docker.elastic.co/eck/eck-operator" in new_text
    assert 'version: "3.5.0"' in new_text
    assert f'digest: "sha256:{"b" * 64}"' in new_text


@pytest.fixture
def eck_stack_chart_dir(tmp_path: Path):
    """eck-stack's bare "version:" CRD fields never carry a digest; the repository comes only from the
    vendored eck-elasticsearch sub-subchart's commented-out example."""
    make_tgz(
        tmp_path / "charts",
        "eck-stack",
        "0.20.0",
        {},
        raw_files={
            "eck-stack/charts/eck-elasticsearch/values.yaml": (
                "# Elasticsearch Docker image to deploy.\n#\n"
                "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0\n"
            ),
        },
    )
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {
                        "name": "eck-stack",
                        "alias": "kiss-eck",
                        "version": "0.20.0",
                        "repository": "https://helm.elastic.co",
                    }
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}))
    return tmp_path


def test_add_missing_images_manifest_entries_allow_pull_fetches_digest_from_registry(
    cdb: ModuleType, eck_stack_chart_dir, monkeypatch: pytest.MonkeyPatch
):
    """With allow_pull=True, a digest missing from values.yaml is fetched from the registry."""
    deps: list[ChartDependency] = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    target_values: YamlMapping = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    baseline_values: YamlMapping = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.3"}}}
    fake_digest = "sha256:" + "a" * 64
    calls = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append((host, repo, tag))
        return True, fake_digest

    monkeypatch.setattr(manifest_entries_new_and_urls, "registry_tag_exists", fake_registry_tag_exists)

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        "",
        MissingEntriesContext(
            eck_stack_chart_dir,
            deps,
            target_values,
            baseline_values,
            allow_pull=True,
        ),
    )

    assert skipped == []
    assert added == ["kiss-eck"]
    assert calls == [("docker.elastic.co", "elasticsearch/elasticsearch", "8.19.19")]
    assert f'digest: "{fake_digest}"' in new_text
    assert 'version: "8.19.19"' in new_text


def test_add_missing_images_manifest_entries_allow_pull_false_never_touches_network(
    cdb: ModuleType, eck_stack_chart_dir, monkeypatch: pytest.MonkeyPatch
):
    """allow_pull=False never calls the registry: skipped."""
    deps: list[ChartDependency] = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    target_values: YamlMapping = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    baseline_values: YamlMapping = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.3"}}}

    def fail_if_called(host, repo, tag):
        msg = "registry_tag_exists must never be called when allow_pull=False"
        raise AssertionError(msg)

    monkeypatch.setattr(manifest_entries_new_and_urls, "registry_tag_exists", fail_if_called)

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        "",
        MissingEntriesContext(
            eck_stack_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert added == []
    assert skipped == ["kiss-eck"]
    assert new_text == ""


def test_add_missing_images_manifest_entries_allow_pull_registry_miss_still_skips(
    cdb: ModuleType, eck_stack_chart_dir, monkeypatch: pytest.MonkeyPatch
):
    """A registry miss (exists=False) is still reported as skipped."""
    deps: list[ChartDependency] = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    target_values: YamlMapping = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    baseline_values: YamlMapping = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.3"}}}

    monkeypatch.setattr(manifest_entries_new_and_urls, "registry_tag_exists", lambda host, repo, tag: (False, None))

    _new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        "",
        MissingEntriesContext(
            eck_stack_chart_dir,
            deps,
            target_values,
            baseline_values,
            allow_pull=True,
        ),
    )

    assert added == []
    assert skipped == ["kiss-eck"]


@pytest.fixture
def keycloak_operator_chart_dir(tmp_path: Path):
    """keycloak-operator's operator.image uses split "tag:"/"sha:"; its "tag:" never has "@sha256:"."""
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [{"name": "keycloak-operator", "version": "1.12.1", "repository": "@adfinis"}],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "keycloak-operator": {
                    "operator": {
                        "image": {
                            "repository": "quay.io/keycloak/keycloak-operator",
                            "tag": "26.7.2",
                            "sha": "9d1f1b2b",
                        }
                    }
                },
            }
        ),
    )
    return tmp_path


def test_add_missing_images_manifest_entries_split_tag_sha_primary_gets_entry(
    cdb: ModuleType, keycloak_operator_chart_dir
):
    """A split "tag:"/"sha:" primary image reads its digest from "sha:" instead of being skipped."""
    text = ""
    deps: list[ChartDependency] = [{"name": "keycloak-operator", "version": "1.12.1"}]
    target_values: YamlMapping = {
        "keycloak-operator": {
            "operator": {
                "image": {"repository": "quay.io/keycloak/keycloak-operator", "tag": "26.7.2", "sha": "9d1f1b2b"}
            }
        }
    }
    baseline_values: YamlMapping = {
        "keycloak-operator": {
            "operator": {
                "image": {"repository": "quay.io/keycloak/keycloak-operator", "tag": "26.6.4", "sha": "eeeeeeee"}
            }
        }
    }

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            keycloak_operator_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert skipped == []
    assert added == ["keycloak-operator"]
    assert "# keycloak-operator 26.6.4 -> 26.7.2" in new_text
    assert "- name: keycloak/keycloak-operator" in new_text
    assert 'version: "26.7.2"' in new_text
    assert 'digest: "sha256:9d1f1b2b"' in new_text


def test_add_missing_images_manifest_entries_split_tag_sha_no_sha_override_still_skipped(
    cdb: ModuleType, keycloak_operator_chart_dir
):
    """No values.yaml override for "sha:" (subchart default not visible): still skipped."""
    write(
        keycloak_operator_chart_dir / "values.yaml",
        yaml.safe_dump(
            {
                "keycloak-operator": {
                    "operator": {"image": {"repository": "quay.io/keycloak/keycloak-operator", "tag": "26.7.2"}}
                },
            }
        ),
    )
    text = ""
    deps: list[ChartDependency] = [{"name": "keycloak-operator", "version": "1.12.1"}]
    target_values: YamlMapping = {
        "keycloak-operator": {
            "operator": {"image": {"repository": "quay.io/keycloak/keycloak-operator", "tag": "26.7.2"}}
        }
    }
    baseline_values: YamlMapping = {
        "keycloak-operator": {
            "operator": {"image": {"repository": "quay.io/keycloak/keycloak-operator", "tag": "26.6.4"}}
        }
    }

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            keycloak_operator_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert added == []
    assert skipped == ["keycloak-operator"]
    assert new_text == text


@pytest.fixture
def global_image_chart_dir(tmp_path: Path):
    """An orphan block (apiproxy) whose only image aliases the global.images.nginx YAML anchor."""
    write(tmp_path / "Chart.yaml", yaml.safe_dump({"dependencies": []}))
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "global": {
                    "images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}
                },
                "apiproxy": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}},
            }
        ),
    )
    return tmp_path


def test_add_missing_images_manifest_entries_global_image_gets_one_entry_not_per_alias(
    cdb: ModuleType, global_image_chart_dir
):
    """A shared global.images.* anchor gets one entry (bare basename, under "global"), none per alias."""
    text = ""
    deps: list[ChartDependency] = []
    target_values: YamlMapping = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
        "apiproxy": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}},
    }
    baseline_values: YamlMapping = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}},
        "apiproxy": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}},
    }

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            global_image_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert skipped == []
    assert added == ["nginx-unprivileged"]
    assert new_text.count("- name: nginxinc/nginx-unprivileged") == 1
    assert "# nginx-unprivileged 1.31.3 -> 1.31.4" in new_text
    assert "apiproxy" not in new_text


def test_add_missing_images_manifest_entries_skips_image_with_no_resolvable_repository(
    cdb: ModuleType, images_manifest_chart_dir
):
    """An image with no own override and no subchart default is unresolvable, so never auto-added."""
    write(
        images_manifest_chart_dir / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
                    {"name": "kiss-chart", "alias": "kiss", "version": "3.0.0", "repository": "@kiss"},
                ],
            }
        ),
    )
    write(
        images_manifest_chart_dir / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
                "kiss": {"adapter": {"image": {"tag": "0.6.7@sha256:cccc"}}},
            }
        ),
    )
    text = ""
    deps: list[ChartDependency] = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"},
        {"name": "kiss-chart", "alias": "kiss", "version": "3.0.0"},
    ]
    target_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
        "kiss": {"adapter": {"image": {"tag": "0.6.7@sha256:cccc"}}},
    }
    baseline_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}},
        "kiss": {"adapter": {"image": {"tag": "0.6.6@sha256:dddd"}}},
    }

    new_text, added, skipped, _backfilled = add_missing_images_manifest_entries(
        text,
        MissingEntriesContext(
            images_manifest_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )
    assert added == ["zac"]
    assert skipped == []  # kiss.adapter.image is excluded entirely, not reported as skipped either
    assert "kiss" not in new_text


# --- remove_stale_images_manifest_entries ---


def test_remove_stale_images_manifest_entries_removes_entry_back_at_baseline(
    cdb: ModuleType, images_manifest_chart_dir
):
    """zac reverted to its baseline version and digest: the entry, its
    comment and its "# Changes:" item are removed."""
    text = (
        "# Baseline: podiumd 4.8.5.\n"
        "#\n"
        "# Changes:\n"
        "#   1. zac 5.0.2 -> 5.1.0.\n"
        "#\n"
        "\n"
        "# zac 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}}
    }

    new_text, removed = remove_stale_images_manifest_entries(
        text, MissingEntriesContext(images_manifest_chart_dir, deps, values, values)
    )

    assert removed == ["infonl/zaakafhandelcomponent"]
    assert "- name:" not in new_text
    assert "# zac 5.0.2 -> 5.1.0" not in new_text
    assert "#   1. zac" not in new_text
    assert "# Changes:\n" in new_text


def test_remove_stale_images_manifest_entries_keeps_changed_digest(cdb: ModuleType, images_manifest_chart_dir):
    """Same version as baseline but a new digest is a real change, so the entry stays."""
    text = (
        "# Changes:\n"
        "#   1. zac 5.0.2 (digest changed).\n"
        "\n"
        "# zac 5.0.2 (digest changed)\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.0.2"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:" + "a" * 64}}
    }
    baseline_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:" + "b" * 64}}
    }

    new_text, removed = remove_stale_images_manifest_entries(
        text, MissingEntriesContext(images_manifest_chart_dir, deps, target_values, baseline_values)
    )

    assert removed == []
    assert new_text == text


def test_remove_stale_images_manifest_entries_keeps_entry_without_resolvable_repository(
    cdb: ModuleType, tmp_path: Path
):
    """An entry with no resolvable repository can't be judged unchanged: it stays for a human and the
    check still reports it."""
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump({"dependencies": [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]}),
    )
    values: YamlMapping = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}
    write(tmp_path / "values.yaml", yaml.safe_dump(values))
    text = '# zac 5.0.1 -> 5.0.2\n- name: zac\n  url: ghcr.io/infonl/zaakafhandelcomponent\n  version: "5.0.2"\n'
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]

    new_text, removed = remove_stale_images_manifest_entries(
        text, MissingEntriesContext(tmp_path, deps, values, values)
    )

    assert removed == []
    assert new_text == text


# --- fix_images_manifest_entry_names ---


def test_fix_images_manifest_entry_names_uses_url_minus_registry_host(cdb: ModuleType):
    """An entry named without Docker Hub's implicit "library/" is renamed to its url minus the host."""
    text = '- name: python\n  url: docker.io/library/python\n  version: "3.14.7-slim"\n'
    repo_map = {"library/python": ("keycloak-operator", "initImage")}

    new_text, renamed = fix_images_manifest_entry_names(text, repo_map)

    assert renamed == [("python", "library/python")]
    assert new_text == '- name: library/python\n  url: docker.io/library/python\n  version: "3.14.7-slim"\n'


def test_fix_images_manifest_entry_names_leaves_known_and_unknown_names(cdb: ModuleType):
    """A known-repository name stays, as does one whose url resolves to nothing known (left for the check)."""
    text = "- name: azure-cli\n  url: mcr.microsoft.com/azure-cli\n- name: mystery\n  url: docker.io/acme/mystery\n"
    repo_map = {"azure-cli": ("mi", "image")}

    new_text, renamed = fix_images_manifest_entry_names(text, repo_map)

    assert renamed == []
    assert new_text == text


def test_fix_images_manifest_entry_names_renames_a_known_name_that_is_not_its_url(cdb: ModuleType):
    """A known name that isn't its url's key is renamed: after the url correction, the url is what is pulled."""
    text = '- name: "library/postgres"\n  url: docker.io/library/python\n'
    repo_map = {"library/postgres": ("zac", "db", "image"), "library/python": ("keycloak-operator", "initImage")}

    new_text, renamed = fix_images_manifest_entry_names(text, repo_map)

    assert renamed == [("library/postgres", "library/python")]
    assert new_text == '- name: "library/python"\n  url: docker.io/library/python\n'


def test_fix_images_manifest_entry_names_skips_a_name_another_entry_has(cdb: ModuleType):
    text = "- name: python\n  url: docker.io/library/python\n- name: library/python\n  url: docker.io/library/python\n"
    repo_map = {"library/python": ("keycloak-operator", "initImage")}

    new_text, renamed = fix_images_manifest_entry_names(text, repo_map)

    assert renamed == []
    assert new_text == text
