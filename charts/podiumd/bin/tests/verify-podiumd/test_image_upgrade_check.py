"""check_image_upgrades — report-only check for whether a newer same-variant
tag is published for every unique digest-pinned image, split into own/
partner-vendor/other-vendor buckets (same classification as check_cves,
reused directly from lib.cve_check). No real helm/registry invocation
happens in these tests — `run` and `find_newest_same_variant_tag` are
mocked throughout."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

DIGEST_A = "a" * 64  # own: frankgateway
DIGEST_B = "b" * 64  # partner: openzaak (Maykin)
DIGEST_C = "c" * 64  # other: redis-operator

CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 0.0.1
dependencies:
  - name: openzaak
    version: 1.0.0
    repository: https://maykinmedia.github.io/charts/
  - name: redis-operator
    version: 1.0.0
    repository: https://ot-container-kit.github.io/helm-charts/
"""

VALUES_YAML = (
    "frankgateway:\n"
    "  image:\n"
    "    repository: ghcr.io/wearefrank/frank-gateway\n"
    f'    tag: "104@sha256:{DIGEST_A}"\n'
    "openzaak:\n"
    "  image:\n"
    "    repository: maykinmedia/objects-api\n"
    f'    tag: "1.0.0@sha256:{DIGEST_B}"\n'
    "redis-operator:\n"
    "  image:\n"
    "    repository: docker.io/alpine/k8s\n"
    f'    tag: "1.36.2@sha256:{DIGEST_C}"\n'
)

RENDERED = (
    "---\n"
    "# Source: podiumd/templates/frankgateway.yaml\n"
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "metadata:\n"
    "  name: frankgateway\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      containers:\n"
    "        - name: apisix\n"
    f"          image: ghcr.io/wearefrank/frank-gateway:104@sha256:{DIGEST_A}\n"
    "---\n"
    "# Source: podiumd/charts/openzaak/templates/deployment.yaml\n"
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "metadata:\n"
    "  name: openzaak\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      containers:\n"
    "        - name: openzaak\n"
    f"          image: maykinmedia/objects-api:1.0.0@sha256:{DIGEST_B}\n"
    "---\n"
    "# Source: podiumd/charts/redis-operator/templates/deployment.yaml\n"
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "metadata:\n"
    "  name: redis-operator\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      containers:\n"
    "        - name: redis-operator\n"
    f"          image: docker.io/alpine/k8s:1.36.2@sha256:{DIGEST_C}\n"
)


def make_chart_dir(tmp_path, values=VALUES_YAML, chart_yaml=CHART_YAML):
    (tmp_path / "Chart.yaml").write_text(chart_yaml, encoding="utf-8")
    (tmp_path / "values.yaml").write_text(values, encoding="utf-8")
    return tmp_path


def template_run(rendered=RENDERED, returncode=0):
    """The actual helm template render — the only `run` call this check
    makes; every per-image lookup goes through find_newest_same_variant_tag,
    not `run`."""
    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=rendered, stderr="")
    return run


def newest_tag_for(**by_repo_path):
    """find_newest_same_variant_tag stub: returns by_repo_path[repo_path] if
    given, else echoes version back unchanged (no newer tag)."""
    def find(host, repo_path, version):
        return by_repo_path.get(repo_path, version)
    return find


# --- cache helpers ---

def test_cache_entry_is_fresh_within_ttl(libimageupgradecheck):
    entry = {"checked_at": datetime.now(timezone.utc).isoformat()}
    assert libimageupgradecheck.cache_entry_is_fresh(entry) is True


def test_cache_entry_is_stale_past_ttl(libimageupgradecheck):
    stale = datetime.now(timezone.utc) - timedelta(days=libimageupgradecheck.IMAGE_UPGRADE_CACHE_TTL_DAYS + 1)
    assert libimageupgradecheck.cache_entry_is_fresh({"checked_at": stale.isoformat()}) is False


def test_cache_entry_is_fresh_handles_malformed_entry(libimageupgradecheck):
    assert libimageupgradecheck.cache_entry_is_fresh({}) is False
    assert libimageupgradecheck.cache_entry_is_fresh({"checked_at": "not-a-date"}) is False


def test_load_cache_missing_file_returns_empty(libimageupgradecheck, tmp_path):
    assert libimageupgradecheck.load_cache(tmp_path) == {}


def test_save_and_load_cache_roundtrip(libimageupgradecheck, tmp_path):
    cache = {"org/repo:1.0.0": {"checked_at": "2026-01-01T00:00:00+00:00", "newest": "1.0.0"}}
    libimageupgradecheck.save_cache(tmp_path, cache)
    assert libimageupgradecheck.load_cache(tmp_path) == cache


# --- check_image_upgrades: preconditions ---

def test_check_image_upgrades_render_failure_fails(vp, libimageupgradecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run(returncode=1))
    ok, detail = vp.check_image_upgrades(chart_dir, [])
    assert ok is False
    assert "failed to render" in detail


# --- check_image_upgrades: full own/partner/other integration ---

def test_check_image_upgrades_splits_own_partner_other_and_never_fails(
    vp, libimageupgradecheck, tmp_path, monkeypatch, capsys,
):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run())
    monkeypatch.setattr(libimageupgradecheck, "find_newest_same_variant_tag",
                         newest_tag_for(**{"wearefrank/frank-gateway": "999"}))

    ok, detail = vp.check_image_upgrades(chart_dir, [])
    assert ok is True  # never fails
    assert "upgradable: 1/1 own, 0/1 partner-vendor, 0/1 other-vendor" in detail
    assert "0 fetch error(s)" in detail

    out = capsys.readouterr().out
    assert "--- Own images ---" in out
    assert "ghcr.io/wearefrank/frank-gateway:104: newer tag available: 999" in out

    assert "--- Partner-vendor images ---" not in out  # nothing upgradable there
    assert "--- Other-vendor images ---" not in out  # nothing upgradable there
    assert "OK: no newer tag published for any pinned image" not in out  # frankgateway IS upgradable


def test_check_image_upgrades_partner_upgrade_shown_with_vendor_label(
    vp, libimageupgradecheck, tmp_path, monkeypatch, capsys,
):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run())
    monkeypatch.setattr(libimageupgradecheck, "find_newest_same_variant_tag",
                         newest_tag_for(**{"maykinmedia/objects-api": "2.0.0"}))

    ok, detail = vp.check_image_upgrades(chart_dir, [])
    assert ok is True
    assert "upgradable: 0/1 own, 1/1 partner-vendor, 0/1 other-vendor" in detail
    out = capsys.readouterr().out
    assert "--- Partner-vendor images ---" in out
    assert "docker.io/maykinmedia/objects-api:1.0.0 [Maykin]: newer tag available: 2.0.0" in out


def test_check_image_upgrades_other_vendor_aggregate_line(vp, libimageupgradecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run())
    monkeypatch.setattr(libimageupgradecheck, "find_newest_same_variant_tag",
                         newest_tag_for(**{"alpine/k8s": "1.37.0"}))

    ok, detail = vp.check_image_upgrades(chart_dir, [])
    assert ok is True
    assert "upgradable: 0/1 own, 0/1 partner-vendor, 1/1 other-vendor" in detail
    out = capsys.readouterr().out
    assert "--- Other-vendor images ---" in out
    assert "1/1 image(s) have a newer tag published" in out
    assert "alpine/k8s" not in out.split("--- Other-vendor images ---")[1]  # no per-image detail


def test_check_image_upgrades_nothing_upgradable_prints_ok(vp, libimageupgradecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run())
    monkeypatch.setattr(libimageupgradecheck, "find_newest_same_variant_tag", newest_tag_for())

    ok, detail = vp.check_image_upgrades(chart_dir, [])
    assert ok is True
    assert "upgradable: 0/1 own, 0/1 partner-vendor, 0/1 other-vendor" in detail
    out = capsys.readouterr().out
    assert "OK: no newer tag published for any pinned image" in out
    assert "---" not in out  # no bucket had anything to report


def test_check_image_upgrades_fetch_error_reported_but_still_passes(
    vp, libimageupgradecheck, tmp_path, monkeypatch, capsys,
):
    import urllib.error

    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run())

    def find(host, repo_path, version):
        if repo_path == "wearefrank/frank-gateway":
            raise urllib.error.URLError("boom")
        return version

    monkeypatch.setattr(libimageupgradecheck, "find_newest_same_variant_tag", find)

    ok, detail = vp.check_image_upgrades(chart_dir, [])
    assert ok is True
    assert "1 fetch error(s)" in detail
    out = capsys.readouterr().out
    assert "FETCH-ERR" in out
    assert "could not be checked:\n  ghcr.io/wearefrank/frank-gateway:104" in out


# --- caching ---

def test_check_image_upgrades_cache_miss_scans_and_persists(vp, libimageupgradecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run())
    monkeypatch.setattr(libimageupgradecheck, "find_newest_same_variant_tag", newest_tag_for())

    ok, detail = vp.check_image_upgrades(chart_dir, [])
    assert ok is True
    saved = libimageupgradecheck.load_cache(chart_dir)
    assert libimageupgradecheck.cache_key("ghcr.io/wearefrank/frank-gateway", "104") in saved

    out = capsys.readouterr().out
    assert "image-upgrade-cache.json changed — commit it" in out


def test_check_image_upgrades_cache_hit_skips_registry_call(vp, libimageupgradecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run())
    key = libimageupgradecheck.cache_key("ghcr.io/wearefrank/frank-gateway", "104")
    libimageupgradecheck.save_cache(chart_dir, {
        key: {"checked_at": datetime.now(timezone.utc).isoformat(), "newest": "999"},
    })

    def fail_if_queried(host, repo_path, version):
        if repo_path == "wearefrank/frank-gateway":
            raise AssertionError("frankgateway should have been served from cache")
        return version

    monkeypatch.setattr(libimageupgradecheck, "find_newest_same_variant_tag", fail_if_queried)

    ok, detail = vp.check_image_upgrades(chart_dir, [])
    assert ok is True
    out = capsys.readouterr().out
    assert "newer tag available: 999" in out  # cached value still used for reporting
    assert "1/3 image(s) served from cache" in out


def test_check_image_upgrades_expired_cache_entry_rechecks(vp, libimageupgradecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run())
    key = libimageupgradecheck.cache_key("ghcr.io/wearefrank/frank-gateway", "104")
    stale = datetime.now(timezone.utc) - timedelta(days=libimageupgradecheck.IMAGE_UPGRADE_CACHE_TTL_DAYS + 1)
    libimageupgradecheck.save_cache(chart_dir, {
        key: {"checked_at": stale.isoformat(), "newest": "999"},
    })
    monkeypatch.setattr(libimageupgradecheck, "find_newest_same_variant_tag", newest_tag_for())  # fresh: no newer tag

    ok, detail = vp.check_image_upgrades(chart_dir, [])
    assert ok is True
    assert "upgradable: 0/1 own" in detail  # stale "999" replaced by the fresh (unchanged) result
    out = capsys.readouterr().out
    assert "0/3 image(s) served from cache" in out  # expired entry does not count as a hit


def test_check_image_upgrades_prunes_entries_for_unpinned_images(vp, libimageupgradecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run())
    monkeypatch.setattr(libimageupgradecheck, "find_newest_same_variant_tag", newest_tag_for())
    stale_key = "org/gone:1.0.0"
    libimageupgradecheck.save_cache(chart_dir, {
        stale_key: {"checked_at": datetime.now(timezone.utc).isoformat(), "newest": "1.0.0"},
    })

    vp.check_image_upgrades(chart_dir, [])
    saved = libimageupgradecheck.load_cache(chart_dir)
    assert stale_key not in saved


def test_check_image_upgrades_heuristic_fallback_for_disabled_component(
    vp, libimageupgradecheck, tmp_path, monkeypatch, capsys,
):
    """A pin whose component isn't in the render at all (e.g. disabled in
    the CI values) falls back to the values-key heuristic: not a
    Chart.yaml dependency -> own."""
    values = VALUES_YAML + (
        "apiproxy:\n  image:\n    repository: org/apiproxy\n" f'    tag: "1.0.0@sha256:{"d" * 64}"\n'
    )
    chart_dir = make_chart_dir(tmp_path, values=values)
    monkeypatch.setattr(libimageupgradecheck, "run", template_run())
    monkeypatch.setattr(libimageupgradecheck, "find_newest_same_variant_tag",
                         newest_tag_for(**{"org/apiproxy": "2.0.0"}))

    ok, detail = vp.check_image_upgrades(chart_dir, [])
    assert ok is True
    assert "upgradable: 1/2 own" in detail  # frankgateway + apiproxy, only apiproxy has an upgrade
    out = capsys.readouterr().out
    assert "docker.io/org/apiproxy:1.0.0: newer tag available: 2.0.0" in out
