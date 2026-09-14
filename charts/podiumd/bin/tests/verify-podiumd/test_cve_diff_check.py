"""check_cve_diff — for every image check_image_upgrades flagged with a
newer tag, or check_image_digests flagged with a slid digest, scan BOTH
the current and proposed image with trivy and report the per-severity CVE
set difference. No real docker/trivy/registry invocation happens in these
tests — run_trivy/load_upgrade_cache/find_sliding_pins are all mocked
directly on lib.cve_diff_check's own module bindings (the module that
actually owns them, per this test suite's own convention), never on
lib.cve_check/lib.image_digests/lib.image_upgrade_cache themselves."""
import urllib.error
from datetime import datetime, timedelta, timezone

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def write_values_yaml(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def vuln(severity, cve, pkg):
    return {"VulnerabilityID": cve, "PkgName": pkg, "Severity": severity}


def fresh_upgrade_entry(newest):
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "newest": newest}


def stale_upgrade_entry(newest):
    return {"checked_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(), "newest": newest}


def make_run_trivy(vulns_by_ref, calls=None):
    def _run_trivy(ref):
        if calls is not None:
            calls.append(ref)
        return vulns_by_ref.get(ref, [])
    return _run_trivy


# --- diff_vulns ---

def test_diff_vulns_exact_set_difference_per_severity(libcvediffcheck):
    current = [vuln("CRITICAL", "CVE-1", "openssl"), vuln("HIGH", "CVE-2", "libxml2")]
    proposed = [vuln("HIGH", "CVE-2", "libxml2"), vuln("MEDIUM", "CVE-3", "curl")]

    closed, introduced = libcvediffcheck.diff_vulns(current, proposed)

    assert closed == [vuln("CRITICAL", "CVE-1", "openssl")]
    assert introduced == [vuln("MEDIUM", "CVE-3", "curl")]


def test_diff_vulns_never_collapses_into_a_naive_net_count(libcvediffcheck):
    """5 closed + 3 introduced must stay two distinct lists, never a
    misleading "net -2"."""
    current = [vuln("HIGH", f"CVE-{i}", "pkg") for i in range(5)]
    proposed = [vuln("HIGH", f"CVE-new-{i}", "pkg") for i in range(3)]

    closed, introduced = libcvediffcheck.diff_vulns(current, proposed)

    assert len(closed) == 5
    assert len(introduced) == 3


# --- check_cve_diff: "upgrade" candidates ---

def test_upgrade_candidate_reports_correct_closed_and_introduced(
        libcvediffcheck, tmp_path, monkeypatch, capsys):
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache",
                         lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [vuln("CRITICAL", "CVE-1", "openssl"), vuln("HIGH", "CVE-2", "libxml2")],
        "ghcr.io/infonl/zac:1.1.0": [vuln("HIGH", "CVE-2", "libxml2"), vuln("MEDIUM", "CVE-3", "curl")],
    }
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy(vulns_by_ref))

    ok, detail = libcvediffcheck.check_cve_diff(tmp_path, [])

    assert ok is True
    assert "1 candidate(s) diffed: 1 CVE(s) closed overall, 1 newly introduced" in detail
    out = capsys.readouterr().out
    assert "ghcr.io/infonl/zac: 1.0.0 -> 1.1.0  [upgrade]" in out
    assert "closed: 1 CRIT" in out
    assert "introduced: 1 MEDIUM" in out


def test_upgrade_candidate_current_ref_is_the_plain_pinned_tag(
        libcvediffcheck, tmp_path, monkeypatch):
    """Unlike the sliding-digest case below, an "upgrade" candidate's own
    current side is the bare pinned tag -- its digest hasn't drifted, so
    there's nothing to pin more precisely against."""
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache",
                         lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    calls = []
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy({}, calls))

    libcvediffcheck.check_cve_diff(tmp_path, [])

    assert "ghcr.io/infonl/zac:1.0.0" in calls
    assert "ghcr.io/infonl/zac:1.1.0" in calls


def test_stale_upgrade_cache_entry_is_not_a_candidate(libcvediffcheck, tmp_path, monkeypatch):
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache",
                         lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": stale_upgrade_entry("1.1.0")})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])

    calls = []
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy({}, calls))

    ok, detail = libcvediffcheck.check_cve_diff(tmp_path, [])

    assert ok is True
    assert detail == "0 candidate(s)"
    assert calls == []


# --- check_cve_diff: "sliding digest" candidates ---

def test_sliding_candidate_uses_pinned_digest_not_bare_tag_for_current_side(
        libcvediffcheck, tmp_path, monkeypatch, capsys):
    """The tag alone would now resolve to the NEW upstream digest, not
    what's actually pinned in values.yaml -- current_ref MUST be
    "repo@sha256:<pinned_digest>", never "repo:version"."""
    write_values_yaml(tmp_path, f"""\
openzaak:
  redis:
    image:
      repository: redis
      tag: "8.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache", lambda chart_dir: {})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins",
                         lambda chart_dir: [("redis", "8.0", DIGEST_A, f"sha256:{DIGEST_B}")])

    calls = []
    vulns_by_ref = {
        f"redis@sha256:{DIGEST_A}": [vuln("CRITICAL", "CVE-1", "openssl")],
        f"redis@sha256:{DIGEST_B}": [],
    }
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy(vulns_by_ref, calls))

    ok, detail = libcvediffcheck.check_cve_diff(tmp_path, [])

    assert ok is True
    assert f"redis@sha256:{DIGEST_A}" in calls
    assert f"redis@sha256:{DIGEST_B}" in calls
    assert "redis:8.0" not in calls
    out = capsys.readouterr().out
    assert "[sliding digest]" in out
    assert "closed: 1 CRIT" in out


# --- check_cve_diff: caching the PROPOSED side ---

def test_sliding_candidate_proposed_side_caches_across_runs(libcvediffcheck, tmp_path, monkeypatch):
    """A sliding candidate's own proposed digest is already known (see
    gather_candidates' own "proposed_digest" field) -- no registry call
    is needed to make it cache-eligible, and a second run reuses the
    cached scan instead of re-invoking trivy."""
    write_values_yaml(tmp_path, f"""\
openzaak:
  redis:
    image:
      repository: redis
      tag: "8.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache", lambda chart_dir: {})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins",
                         lambda chart_dir: [("redis", "8.0", DIGEST_A, f"sha256:{DIGEST_B}")])

    calls = []
    vulns_by_ref = {
        f"redis@sha256:{DIGEST_A}": [vuln("CRITICAL", "CVE-1", "openssl")],
        f"redis@sha256:{DIGEST_B}": [vuln("HIGH", "CVE-2", "libxml2")],
    }
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy(vulns_by_ref, calls))

    libcvediffcheck.check_cve_diff(tmp_path, [])
    assert calls.count(f"redis@sha256:{DIGEST_B}") == 1  # first run: a real scan

    calls.clear()
    libcvediffcheck.check_cve_diff(tmp_path, [])
    assert f"redis@sha256:{DIGEST_B}" not in calls  # second run: cache hit, no new scan


def test_upgrade_candidate_proposed_side_resolves_digest_then_caches_across_runs(
        libcvediffcheck, tmp_path, monkeypatch):
    """An "upgrade" candidate's own proposed side is a bare tag -- its
    digest is resolved via ONE registry_tag_exists manifest lookup
    (never a docker pull), called with exactly (host, repo_path,
    newest-tag). Once resolved, a second run reuses the cached scan
    instead of re-invoking trivy, the same as the sliding case."""
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache",
                         lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])

    resolve_calls = []

    def fake_registry_tag_exists(host, repo, tag):
        resolve_calls.append((host, repo, tag))
        return True, f"sha256:{DIGEST_B}"

    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", fake_registry_tag_exists)

    trivy_calls = []
    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [],
        "ghcr.io/infonl/zac:1.1.0": [vuln("CRITICAL", "CVE-1", "openssl")],
    }
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy(vulns_by_ref, trivy_calls))

    libcvediffcheck.check_cve_diff(tmp_path, [])
    assert resolve_calls == [("ghcr.io", "infonl/zac", "1.1.0")]
    assert trivy_calls.count("ghcr.io/infonl/zac:1.1.0") == 1  # first run: a real scan

    trivy_calls.clear()
    libcvediffcheck.check_cve_diff(tmp_path, [])
    assert "ghcr.io/infonl/zac:1.1.0" not in trivy_calls  # second run: cache hit, no new scan


def test_upgrade_candidate_resolve_failure_falls_back_to_uncached_scan(
        libcvediffcheck, tmp_path, monkeypatch, capsys):
    """A network error while resolving the proposed tag's digest must
    never abort the candidate or count as a scan error -- it just falls
    back to an uncached run_trivy call, same as if caching were never
    attempted at all."""
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache",
                         lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])

    def failing_resolve(host, repo, tag):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", failing_resolve)

    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [],
        "ghcr.io/infonl/zac:1.1.0": [vuln("CRITICAL", "CVE-1", "openssl")],
    }
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy(vulns_by_ref))

    ok, detail = libcvediffcheck.check_cve_diff(tmp_path, [])

    assert ok is True
    assert "0 scan error(s)" in detail
    out = capsys.readouterr().out
    assert "introduced: 1 CRIT" in out


# --- check_cve_diff: no flagged candidate at all ---

def test_no_flagged_upgrade_or_slide_never_scans_anything(libcvediffcheck, tmp_path, monkeypatch, capsys):
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache",
                         lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.0.0")})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])

    calls = []
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy({}, calls))

    ok, detail = libcvediffcheck.check_cve_diff(tmp_path, [])

    assert ok is True
    assert detail == "0 candidate(s)"
    assert calls == []
    out = capsys.readouterr().out
    assert "OK: no upgrade-available or sliding-digest candidate to diff" in out


# --- detail mode (--detail-cve-diff) ---

def test_default_report_is_terse_counts_only(libcvediffcheck, tmp_path, monkeypatch, capsys):
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache",
                         lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [],
        "ghcr.io/infonl/zac:1.1.0": [vuln("CRITICAL", "CVE-1", "openssl")],
    }
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy(vulns_by_ref))

    libcvediffcheck.check_cve_diff(tmp_path, [])

    out = capsys.readouterr().out
    assert "introduced: 1 CRIT" in out
    assert "CVE-1" not in out
    assert "openssl" not in out


def test_detail_flag_itemizes_high_severity_vulnerability_id_and_package(
        libcvediffcheck, tmp_path, monkeypatch, capsys):
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache",
                         lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [],
        "ghcr.io/infonl/zac:1.1.0": [vuln("CRITICAL", "CVE-1", "openssl")],
    }
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy(vulns_by_ref))

    libcvediffcheck.check_cve_diff(tmp_path, [], detail=True)

    out = capsys.readouterr().out
    assert "introduced: 1 CRIT" in out
    assert "openssl" in out
    assert "CVE-1" in out


def test_detail_flag_never_itemizes_medium_low_unknown(libcvediffcheck, tmp_path, monkeypatch, capsys):
    """Same convention as check_cves' own --detail-cve-check: only
    CRITICAL/HIGH ever get itemized, regardless of the flag."""
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache",
                         lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [],
        "ghcr.io/infonl/zac:1.1.0": [vuln("MEDIUM", "CVE-9", "zlib")],
    }
    monkeypatch.setattr(libcvediffcheck, "run_trivy", make_run_trivy(vulns_by_ref))

    libcvediffcheck.check_cve_diff(tmp_path, [], detail=True)

    out = capsys.readouterr().out
    assert "introduced: 1 MEDIUM" in out
    assert "zlib" not in out
    assert "CVE-9" not in out


# --- gather_candidates ---

def test_gather_candidates_combines_both_sources(libcvediffcheck, tmp_path, monkeypatch):
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
redis-thing:
  image:
    repository: redis
    tag: "8.0@sha256:{DIGEST_A}"
""")
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache",
                         lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")})
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins",
                         lambda chart_dir: [("redis", "8.0", DIGEST_A, f"sha256:{DIGEST_B}")])

    candidates = libcvediffcheck.gather_candidates(tmp_path)

    kinds = sorted(c["kind"] for c in candidates)
    assert kinds == ["sliding digest", "upgrade"]

    by_kind = {c["kind"]: c for c in candidates}
    # sliding digest already has its own resolved digest -- bare hex, no
    # "sha256:" prefix (see _bare_digest/cache_key) -- no extra call
    # needed to cache its proposed side.
    assert by_kind["sliding digest"]["proposed_digest"] == DIGEST_B
    # upgrade's own proposed side is a bare tag -- genuinely unresolved
    # until _scan_proposed actually needs it.
    assert by_kind["upgrade"]["proposed_digest"] is None
