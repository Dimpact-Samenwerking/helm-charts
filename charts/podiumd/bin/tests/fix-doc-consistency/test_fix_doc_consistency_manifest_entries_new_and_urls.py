"""fix_images_manifest_entry_urls, plus add_missing_images_manifest_entries' own
core/split-tag/allow-pull/global-image scenarios."""

import io
import tarfile

import pytest
import yaml


def write(path, text):
    path.write_text(text, encoding="utf-8")


def make_tgz(charts_dir, name, version, values, raw_files=None):
    """A minimal vendored <name>-<version>.tgz — enough to exercise
    documented_repository_for_path (nested_subchart_documented_image_
    repository under the hood) without a real `helm pull`. raw_files (a
    {internal tar path: text} dict, e.g. "<name>/charts/<nested>/
    values.yaml") writes each verbatim, matching tests/lib/test_chart.py's
    own make_tgz (not importable across test files in this codebase's
    per-file test-helper convention)."""
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


def test_fix_images_manifest_entry_urls_restores_stripped_host(cdb, tmp_path):
    """Regression test (real bug, real doc): a historical (now-
    superseded) reordering commit silently stripped the registry host
    off several "url:" fields while moving their own entry blocks —
    confirmed live: images-4.9.1.yaml's own zac otel sidecar ("otel/
    opentelemetry-collector-contrib" instead of "docker.io/otel/
    opentelemetry-collector-contrib"). Nothing ever re-verified an
    EXISTING entry's own url against what it should actually be."""
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
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {
        "zac": {
            "opentelemetry-collector": {
                "image": {"repository": "otel/opentelemetry-collector-contrib", "tag": "0.158.0@sha256:aaaa"}
            }
        }
    }

    repo_map = {"otel/opentelemetry-collector-contrib": ("zac", "opentelemetry-collector", "image")}
    new_text, changed, unresolved = cdb.fix_images_manifest_entry_urls(text, tmp_path, deps, target_values, repo_map)

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


def test_fix_images_manifest_entry_urls_leaves_correct_url_untouched(cdb, images_manifest_chart_dir):
    text = (
        "# zac 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}}
    }

    repo_map = {"infonl/zaakafhandelcomponent": ("zac", "image")}
    new_text, changed, unresolved = cdb.fix_images_manifest_entry_urls(
        text, images_manifest_chart_dir, deps, target_values, repo_map
    )
    assert changed == []
    assert unresolved == []
    assert new_text == text


def test_fix_images_manifest_entry_urls_reports_unresolvable_entry(cdb, tmp_path):
    write(tmp_path / "Chart.yaml", yaml.safe_dump({"dependencies": []}))
    write(tmp_path / "values.yaml", yaml.safe_dump({}))
    text = '- name: totally-unknown\n  url: example.com/totally-unknown\n  version: "1.0.0"\n'

    new_text, changed, unresolved = cdb.fix_images_manifest_entry_urls(text, tmp_path, [], {})
    assert changed == []
    assert unresolved == ["totally-unknown"]
    assert new_text == text


# --- add_missing_images_manifest_entries ---


@pytest.fixture
def images_manifest_chart_dir(tmp_path):
    """A real Chart.yaml + values.yaml on disk (needed by
    lib.image_repository_check.find_images_without_repository, which
    reads them itself rather than taking already-loaded dicts) — zac's
    own "repository:" is set explicitly so its primary image resolves,
    matching lib.chart.paths_by_repository's own "no owning dependency
    needed for an own override" resolution."""
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


def test_add_missing_images_manifest_entries_appends_new_entry(cdb, images_manifest_chart_dir):
    text = "# Baseline: podiumd 4.8.5.\n"
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}}
    }
    baseline_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}}
    }

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values
    )

    assert skipped == []
    assert added == ["zac"]
    assert "# zac 5.0.2 -> 5.1.0" in new_text  # primary: plain "# " prefix, no em-dash
    assert "- name: infonl/zaakafhandelcomponent" in new_text
    assert "url: ghcr.io/infonl/zaakafhandelcomponent" in new_text
    assert 'version: "5.1.0"' in new_text
    assert 'digest: "sha256:aaaa"' in new_text


def test_add_missing_images_manifest_entries_genuinely_new_image_renders_new(cdb, images_manifest_chart_dir):
    """Regression test (real bug, real doc): a genuinely brand-new image
    (no baseline value at all, and no historical images-<version>.yaml
    manifest ever records it either) used to fall back to `old_version =
    new_version` as a fake "old" value, which made the "same version ->
    (digest changed)" branch fire wrongly — confirmed live: images-
    4.9.1.yaml's own zac otel sidecar comment read "0.158.0 -> 0.158.0"
    instead of "0.158.0 (new)". Must render "(new)", never a nonsensical
    self-transition or a false "(digest changed)"."""
    text = "# Baseline: podiumd 4.8.5.\n"
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {
        "zac": {
            "opentelemetry-collector": {
                "image": {"repository": "otel/opentelemetry-collector-contrib", "tag": "0.158.0@sha256:" + "a" * 64}
            }
        }
    }
    baseline_values = {}

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values
    )

    assert skipped == []
    assert added == ["zac - opentelemetry-collector-contrib"]
    assert "opentelemetry-collector-contrib 0.158.0 (new)" in new_text
    assert "0.158.0 -> 0.158.0" not in new_text
    assert "(digest changed)" not in new_text


def test_add_missing_images_manifest_entries_moved_repository_gets_real_transition(cdb, tmp_path):
    """Real case (podiumd 4.9.1): the postgres consolidation (see
    lib.chart.baseline_tag_for_sidecar_path) — global.images.postgres
    never existed in baseline_values, but the same "postgres" repository
    already did, at openbao.database.schemaJob.image. Must render the
    real "16-alpine -> 16.15-alpine" transition, never "(new)"."""
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
    deps = [{"name": "openbao", "version": "2.0.0"}]
    target_values = {
        "global": {"images": {"postgres": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}},
        "openbao": {
            "database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}}
        },
    }
    baseline_values = {
        "openbao": {"database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16-alpine@sha256:bbbb"}}}},
    }

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text, tmp_path, deps, target_values, baseline_values
    )

    assert skipped == []
    assert added == ["postgres"]
    assert "# postgres 16-alpine -> 16.15-alpine" in new_text
    assert "(new)" not in new_text


def test_add_missing_images_manifest_entries_catches_same_version_changed_digest(cdb, images_manifest_chart_dir):
    """Regression test (real bug, real doc, clamav-shaped): a same-
    version, changed-digest re-pin is correctly DETECTED by lib.
    upgradedoc.find_images_manifest_list_diff (see its own docstring),
    but this function has its own SEPARATE call to it — and had been
    passing neither `values=` nor `baseline_values=`, silently
    collapsing that call back to the old version-only behaviour (see
    find_images_manifest_list_diff's own "every real caller passes
    both" docstring note). Confirmed live: running fix-doc-consistency
    against the real chart produced zero mention of clamav's own real
    digest-only re-pin at all — not even "no existing entry, add
    manually". This must actually ADD the entry, not just detect it."""
    text = "# Baseline: podiumd 4.8.5.\n"
    deps = [{"name": "clamav", "version": "1.0.0"}]
    target_values = {"clamav": {"image": {"repository": "clamav/clamav", "tag": "1.5.4@sha256:" + "b" * 64}}}
    baseline_values = {"clamav": {"image": {"repository": "clamav/clamav", "tag": "1.5.4@sha256:" + "a" * 64}}}

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values
    )

    assert skipped == []
    assert added == ["clamav"]
    assert "- name: clamav/clamav" in new_text
    assert f'digest: "sha256:{"b" * 64}"' in new_text
    # Real bug: "clamav 1.5.4 -> 1.5.4" reads as "nothing changed" even
    # though the version DID stay the same and only the digest changed —
    # both the "# Changes:" header item and the per-entry "#" comment
    # above its own "- name:" block share this SAME version_text
    # construction, so both must say "(digest changed)" instead of the
    # degenerate "<version> -> <version>" arrow form.
    assert "clamav 1.5.4 (digest changed)" in new_text
    assert "clamav 1.5.4 -> 1.5.4" not in new_text


def test_add_missing_images_manifest_entries_name_is_stripped_url_is_fully_qualified(cdb, images_manifest_chart_dir):
    """Regression test: "name:" is the curated ACR mirror slug's own
    starting point — the same STRIPPED repo_map key docs/images/
    acr-mirror-naming.md documents, still a human's job to fix
    afterward — but "url:" must be the REAL, fully host-qualified
    repository (lib.chart.full_repository_for_path), never the same
    stripped value: a manifest entry's "url:" with no registry host at
    all (real bug, confirmed live in images-4.9.1.yaml) is silently
    wrong for every Docker-Hub-hosted image (host omitted in values.
    yaml's own "repository:" by Docker Hub's own convention)."""
    text = ""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}}
    }

    new_text, added, _skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values={}
    )
    assert added == ["zac"]
    assert "- name: infonl/zaakafhandelcomponent" in new_text
    assert "url: ghcr.io/infonl/zaakafhandelcomponent" in new_text


def test_add_missing_images_manifest_entries_real_version_bump_keeps_arrow_wording(cdb, images_manifest_chart_dir):
    """A genuine version bump (old_version != new_version) still renders
    the normal "<old> -> <new>" arrow form — the "(digest changed)"
    wording is ONLY for the same-version case, never a substitute for a
    real version transition."""
    text = ""
    deps = [{"name": "curl", "version": "1.0.0"}]
    target_values = {"curl": {"image": {"repository": "curlimages/curl", "tag": "8.22.0@sha256:" + "b" * 64}}}
    baseline_values = {"curl": {"image": {"repository": "curlimages/curl", "tag": "8.21.0@sha256:" + "a" * 64}}}

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values
    )

    assert skipped == []
    assert added == ["curl"]
    assert "curl 8.21.0 -> 8.22.0" in new_text
    assert "digest changed" not in new_text


def test_add_missing_images_manifest_entries_docker_hub_repository_gets_docker_io_host(cdb, images_manifest_chart_dir):
    """Regression test: a Docker-Hub-hosted image's own "repository:"
    conventionally omits the host entirely (e.g. "curlimages/curl") —
    the entry's "url:" must still come out fully host-qualified
    ("docker.io/curlimages/curl"), not the bare, hostless string."""
    text = ""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {"zac": {"image": {"repository": "curlimages/curl", "tag": "8.22.0@sha256:aaaa"}}}

    new_text, added, _skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values={}
    )
    assert added == ["zac"]
    assert "- name: curlimages/curl" in new_text
    assert "url: docker.io/curlimages/curl" in new_text


def test_add_missing_images_manifest_entries_separate_registry_key_is_used_for_url(cdb, images_manifest_chart_dir):
    """Regression test (mi's own real "azure-cli" case): a component
    whose registry host lives in a SEPARATE sibling "registry:" key
    (Azure Container Registry's own convention) rather than embedded in
    "repository:" itself (bare "azure-cli", no namespace at all) must
    still get a fully host-qualified "url:" — that sibling key is
    authoritative, never parse_repo's own Docker Hub inference (which
    would wrongly assume "docker.io/azure-cli")."""
    text = ""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {
        "zac": {"image": {"registry": "mcr.microsoft.com", "repository": "azure-cli", "tag": "2.90.0@sha256:aaaa"}}
    }

    new_text, added, _skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values={}
    )
    assert added == ["zac"]
    assert "- name: azure-cli" in new_text
    assert "url: mcr.microsoft.com/azure-cli" in new_text


def test_add_missing_images_manifest_entries_noop_when_entry_already_covers_it(cdb, images_manifest_chart_dir):
    text = (
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}}
    }
    baseline_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}}
    }

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values
    )
    assert added == []
    assert skipped == []
    assert new_text == text


def test_add_missing_images_manifest_entries_skips_when_no_digest_pinned(cdb, images_manifest_chart_dir):
    """A path whose current tag has no "@sha256:..." at all can't
    produce a valid entry (digest is a required field) — reported as
    skipped, not silently dropped or written incomplete."""
    write(
        images_manifest_chart_dir / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0"}},
            }
        ),
    )
    text = ""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0"}}}
    baseline_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}}
    }

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values
    )
    assert added == []
    assert skipped == ["zac"]
    assert new_text == text


def test_add_missing_images_manifest_entries_eck_operator_split_digest_field_resolves(cdb, images_manifest_chart_dir):
    """Regression test (real bug, real chart): eck-operator's own image
    pin uses a split "tag:"/"digest:" convention (not the usual embedded
    "tag: <ver>@sha256:<digest>"). Before lib.chart.SPLIT_TAG_SHA_PATHS
    was generalized to support a "digest:"-named sibling field (not just
    the two keycloak paths' own "sha:"), resolved_digest_pin had no way
    to find it at all, so this always skipped it with "no resolvable
    repository, or its values.yaml tag has no digest pinned yet" —
    confirmed live on the real 4.9.1-to-4.9.2 doc set. eck-operator
    existed (enabled) at the baseline with no explicit "image:" override
    at all, same shape as the real 4.9.1 baseline."""
    text = "# Baseline: podiumd 4.9.1.\n"
    deps = [{"name": "eck-operator", "version": "3.5.0"}]
    target_values = {
        "eck-operator": {
            "enabled": True,
            "image": {
                "repository": "docker.elastic.co/eck/eck-operator",
                "tag": "3.5.0",
                "digest": "sha256:" + "b" * 64,
            },
        }
    }
    baseline_values = {"eck-operator": {"enabled": True}}

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values
    )

    assert skipped == []
    assert added == ["eck-operator"]
    assert "url: docker.elastic.co/eck/eck-operator" in new_text
    assert 'version: "3.5.0"' in new_text
    assert f'digest: "sha256:{"b" * 64}"' in new_text


@pytest.fixture
def eck_stack_chart_dir(tmp_path):
    """eck-stack's own bare "version:" CRD fields (see COMPONENT_
    VERSION_PATH_NESTED_SUBCHARTS) never carry a digest anywhere in
    values.yaml at all — the real case documented_repository_for_path/
    the allow_pull registry fallback exist for. The repository comes
    from the vendored eck-elasticsearch sub-subchart's own commented-
    out documented example, the only place it's recorded."""
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
    cdb, eck_stack_chart_dir, monkeypatch
):
    """Real feature: the repository resolves fine (via the vendored
    subchart's own documented example), but resolved_digest_pin alone
    can never produce a digest for a bare CRD version field — nothing
    in values.yaml carries one. With allow_pull=True, a real registry
    manifest lookup (the same call /fetch-image-digest and update-
    image-version's own missing_entries handling already make) fills
    it in instead of skipping."""
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    target_values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    baseline_values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.3"}}}
    fake_digest = "sha256:" + "a" * 64
    calls = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append((host, repo, tag))
        return True, fake_digest

    monkeypatch.setattr(cdb, "registry_tag_exists", fake_registry_tag_exists)

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        "", eck_stack_chart_dir, deps, target_values, baseline_values, allow_pull=True
    )

    assert skipped == []
    assert added == ["kiss-eck"]
    assert calls == [("docker.elastic.co", "elasticsearch/elasticsearch", "8.19.19")]
    assert f'digest: "{fake_digest}"' in new_text
    assert 'version: "8.19.19"' in new_text


def test_add_missing_images_manifest_entries_allow_pull_false_never_touches_network(
    cdb, eck_stack_chart_dir, monkeypatch
):
    """Default allow_pull=False must never call the registry at all —
    left exactly as before: skipped, no network access attempted."""
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    target_values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    baseline_values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.3"}}}

    def fail_if_called(host, repo, tag):
        raise AssertionError("registry_tag_exists must never be called when allow_pull=False")

    monkeypatch.setattr(cdb, "registry_tag_exists", fail_if_called)

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        "", eck_stack_chart_dir, deps, target_values, baseline_values
    )

    assert added == []
    assert skipped == ["kiss-eck"]
    assert new_text == ""


def test_add_missing_images_manifest_entries_allow_pull_registry_miss_still_skips(
    cdb, eck_stack_chart_dir, monkeypatch
):
    """The registry genuinely has no such tag (exists=False) — still
    reported as skipped, not a crash or a bad/partial entry."""
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    target_values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    baseline_values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.3"}}}

    monkeypatch.setattr(cdb, "registry_tag_exists", lambda host, repo, tag: (False, None))

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        "", eck_stack_chart_dir, deps, target_values, baseline_values, allow_pull=True
    )

    assert added == []
    assert skipped == ["kiss-eck"]


@pytest.fixture
def keycloak_operator_chart_dir(tmp_path):
    """keycloak-operator's own primary image (operator.config.keycloakImage)
    uses the adfinis chart's own split "tag:"/"sha:" convention — its
    "tag:" alone never carries "@sha256:...", the real case
    resolved_digest_pin exists for."""
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
                        "config": {
                            "keycloakImage": {
                                "repository": "quay.io/keycloak/keycloak",
                                "tag": "26.7.2",
                                "sha": "9d1f1b2b",
                            }
                        }
                    }
                },
            }
        ),
    )
    return tmp_path


def test_add_missing_images_manifest_entries_split_tag_sha_primary_gets_entry(cdb, keycloak_operator_chart_dir):
    """Real bug: keycloak-operator's own primary image was silently
    SKIPPED entirely (treated the same as "no digest pinned yet") since
    its "tag:" never embeds "@sha256:..." — the digest lives in the
    sibling "sha:" field instead. Must be read from there, not skipped."""
    text = ""
    deps = [{"name": "keycloak-operator", "version": "1.12.1"}]
    target_values = {
        "keycloak-operator": {
            "operator": {
                "config": {
                    "keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.2", "sha": "9d1f1b2b"}
                }
            }
        }
    }
    baseline_values = {
        "keycloak-operator": {
            "operator": {
                "config": {
                    "keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.6.4", "sha": "eeeeeeee"}
                }
            }
        }
    }

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text, keycloak_operator_chart_dir, deps, target_values, baseline_values
    )

    assert skipped == []
    assert added == ["keycloak-operator"]
    assert "# keycloak-operator 26.6.4 -> 26.7.2" in new_text
    assert "- name: keycloak/keycloak" in new_text
    assert 'version: "26.7.2"' in new_text
    assert 'digest: "sha256:9d1f1b2b"' in new_text


def test_add_missing_images_manifest_entries_split_tag_sha_no_sha_override_still_skipped(
    cdb, keycloak_operator_chart_dir
):
    """No podiumd override for the sibling "sha:" field at all (inherits
    the vendored subchart's own default, not visible from values.yaml) —
    genuinely can't produce a digest-pinned entry, so still reported as
    skipped rather than writing one with a missing/wrong digest."""
    write(
        keycloak_operator_chart_dir / "values.yaml",
        yaml.safe_dump(
            {
                "keycloak-operator": {
                    "operator": {
                        "config": {"keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.2"}}
                    }
                },
            }
        ),
    )
    text = ""
    deps = [{"name": "keycloak-operator", "version": "1.12.1"}]
    target_values = {
        "keycloak-operator": {
            "operator": {"config": {"keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.2"}}}
        }
    }
    baseline_values = {
        "keycloak-operator": {
            "operator": {"config": {"keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.6.4"}}}
        }
    }

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text, keycloak_operator_chart_dir, deps, target_values, baseline_values
    )

    assert added == []
    assert skipped == ["keycloak-operator"]
    assert new_text == text


@pytest.fixture
def global_image_chart_dir(tmp_path):
    """apiproxy's own real shape: an orphan top-level block (no Chart.yaml
    dependency of its own) whose SOLE image aliases the shared
    global.images.nginx anchor — the same YAML-anchored value, not a
    coincidentally-matching repository."""
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


def test_add_missing_images_manifest_entries_global_image_gets_one_entry_not_per_alias(cdb, global_image_chart_dir):
    """Real feature: a shared global.images.* anchor gets exactly ONE
    entry, named via its own bare basename and positioned under
    "global" 's own values.yaml order — never a separate entry for
    apiproxy (or any other component) that merely aliases the same
    anchor. repo_group_representative's own "global" tier plus find_
    images_manifest_list_diff's existing repo-group collapse are what
    make this "just work": apiproxy's own path is never independently
    considered "missing" at all once it collapses to the same
    representative as global.images.nginx itself."""
    text = ""
    deps = []
    target_values = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}}},
        "apiproxy": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}},
    }
    baseline_values = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}}},
        "apiproxy": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3@sha256:bbbb"}},
    }

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text, global_image_chart_dir, deps, target_values, baseline_values
    )

    assert skipped == []
    assert added == ["nginx-unprivileged"]
    assert new_text.count("- name: nginxinc/nginx-unprivileged") == 1
    assert "# nginx-unprivileged 1.31.3 -> 1.31.4" in new_text
    assert "apiproxy" not in new_text


def test_add_missing_images_manifest_entries_skips_image_with_no_resolvable_repository(cdb, images_manifest_chart_dir):
    """kiss.adapter.image's own real-world case: no own override AND no
    vendored subchart default — not a real, referenceable image, so
    never auto-added (matches lib.image_repository_check.
    find_images_without_repository's own definition of "unresolvable",
    reused via find_images_manifest_list_diff)."""
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
    deps = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"},
        {"name": "kiss-chart", "alias": "kiss", "version": "3.0.0"},
    ]
    target_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
        "kiss": {"adapter": {"image": {"tag": "0.6.7@sha256:cccc"}}},
    }
    baseline_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}},
        "kiss": {"adapter": {"image": {"tag": "0.6.6@sha256:dddd"}}},
    }

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values
    )
    assert added == ["zac"]
    assert skipped == []  # kiss.adapter.image is excluded entirely, not reported as skipped either
    assert "kiss" not in new_text
