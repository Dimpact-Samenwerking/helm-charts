"""lib.json_cache.load_json_cache with an entry check, and the trivy report
parsing in lib.checks.cve."""

import json

from pathlib import Path

from lib.checks.cve import is_cve_entry
from lib.checks.cve import trivy_vulnerabilities
from lib.image.upgrade_cache import is_upgrade_entry
from lib.json_cache import load_json_cache


def test_load_json_cache_drops_entries_that_fail_the_check(tmp_path: Path):
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "good": {"checked_at": "2026-09-24T00:00:00+00:00", "newest": "1.2.0"},
                "no-newest": {"checked_at": "2026-09-24T00:00:00+00:00"},
                "not-a-dict": 5,
            }
        ),
        encoding="utf-8",
    )
    assert load_json_cache(path, is_upgrade_entry) == {
        "good": {"checked_at": "2026-09-24T00:00:00+00:00", "newest": "1.2.0"}
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
