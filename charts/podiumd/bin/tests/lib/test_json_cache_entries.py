"""lib.json_cache.load_json_cache with an entry check, the trivy report
parsing in lib.checks.cve, and the image-upgrade cache's same-major target."""

import json

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

from lib.checks.cve import is_cve_entry
from lib.checks.cve import trivy_vulnerabilities
from lib.image.upgrade_cache import UpgradeEntry
from lib.image.upgrade_cache import cache_key
from lib.image.upgrade_cache import is_upgrade_entry
from lib.image.upgrade_cache import same_major_upgrade
from lib.json_cache import load_json_cache


def test_load_json_cache_drops_entries_that_fail_the_check(tmp_path: Path):
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "good": {"checked_at": "2026-09-24T00:00:00+00:00", "newer": ["1.2.0"]},
                "no-newer": {"checked_at": "2026-09-24T00:00:00+00:00"},
                "old-newest-shape": {"checked_at": "2026-09-24T00:00:00+00:00", "newest": "1.2.0"},
                "not-a-dict": 5,
            }
        ),
        encoding="utf-8",
    )
    assert load_json_cache(path, is_upgrade_entry) == {
        "good": {"checked_at": "2026-09-24T00:00:00+00:00", "newer": ["1.2.0"]}
    }


def test_load_json_cache_non_object_file_is_empty(tmp_path: Path):
    path = tmp_path / "cache.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_json_cache(path, is_upgrade_entry) == {}


def test_trivy_vulnerabilities_keeps_the_three_fields():
    report = {
        "Results": [
            {"Vulnerabilities": [{"VulnerabilityID": "CVE-1", "PkgName": "zlib", "Severity": "HIGH", "Title": "x"}]},
            {"Vulnerabilities": None},
            {},
        ]
    }
    assert trivy_vulnerabilities(report) == [{"VulnerabilityID": "CVE-1", "PkgName": "zlib", "Severity": "HIGH"}]


def test_trivy_vulnerabilities_fills_missing_fields_with_question_mark():
    assert trivy_vulnerabilities({"Results": [{"Vulnerabilities": [{"VulnerabilityID": "CVE-2"}]}]}) == [
        {"VulnerabilityID": "CVE-2", "PkgName": "?", "Severity": "?"}
    ]


def test_trivy_vulnerabilities_rejects_other_shapes():
    assert trivy_vulnerabilities([]) is None
    assert trivy_vulnerabilities({"Results": "x"}) is None
    assert trivy_vulnerabilities({"Results": [{"Vulnerabilities": [{"Severity": 3}]}]}) is None


def test_is_cve_entry():
    vuln = {"VulnerabilityID": "CVE-1", "PkgName": "zlib", "Severity": "HIGH"}
    assert is_cve_entry({"scanned_at": "2026-09-24", "vulnerabilities": [vuln]})
    assert not is_cve_entry({"scanned_at": "2026-09-24", "vulnerabilities": [{**vuln, "Extra": 1}]})
    assert not is_cve_entry({"vulnerabilities": []})


def test_same_major_upgrade_is_the_newer_tag_in_the_pins_major():
    now = datetime.now(timezone.utc).isoformat()
    cache: dict[str, UpgradeEntry] = {
        cache_key("library/postgres", "16.15-alpine"): {"checked_at": now, "newer": ["16.17-alpine", "18.3-alpine"]},
        cache_key("library/postgres", "16.17-alpine"): {"checked_at": now, "newer": ["18.3-alpine"]},
    }
    assert same_major_upgrade(cache, "library/postgres", "16.15-alpine", 1) == "16.17-alpine"
    assert same_major_upgrade(cache, "library/postgres", "16.17-alpine", 1) is None  # only a newer major
    assert same_major_upgrade(cache, "library/postgres", "15.9-alpine", 1) is None  # no cache entry


def test_same_major_upgrade_ignores_a_stale_entry():
    stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    cache: dict[str, UpgradeEntry] = {
        cache_key("library/postgres", "16.15-alpine"): {"checked_at": stale, "newer": ["16.17-alpine"]}
    }
    assert same_major_upgrade(cache, "library/postgres", "16.15-alpine", 1) is None
