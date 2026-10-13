"""lib.version_numbers — is_bare_version, dotted_numbers, stable_semver_key, major_line, newest_per_major."""

from lib.version_numbers import dotted_numbers
from lib.version_numbers import is_bare_version
from lib.version_numbers import major_line
from lib.version_numbers import newest_per_major
from lib.version_numbers import stable_semver_key


def test_dotted_numbers_compare_numerically():
    assert dotted_numbers("1.10.0") > dotted_numbers("1.9.3")
    assert dotted_numbers("3") == (3,)


def test_stable_semver_key_accepts_v_prefix_and_rejects_prereleases():
    assert stable_semver_key("v1.2.3") == (1, 2, 3)
    assert stable_semver_key("1.2.3-rc.1") is None
    assert stable_semver_key("1.2") is None


def test_is_bare_version_accepts_only_major_minor_patch():
    assert is_bare_version("4.8.2")
    assert is_bare_version("10.20.300")
    for other in ("4.8", "v4.8.2", "--help", "4.8.2-rc1", "origin/feature/podiumd-4.8.2", "", None):
        assert not is_bare_version(other)


def test_major_line_of_an_image_tag():
    assert major_line("16.15-alpine") == (16,)
    assert major_line("v8.6.6") == (8,)
    assert major_line("104") == ()  # a single build number is one line
    assert major_line("latest") is None


def test_newest_per_major_keeps_the_highest_newer_version_per_line():
    candidates = [("16.10", (16, 10)), ("16.17", (16, 17)), ("17.9", (17, 9)), ("18.3", (18, 3)), ("15.9", (15, 9))]
    assert newest_per_major((16, 15), candidates) == ["16.17", "17.9", "18.3"]
    assert newest_per_major((18, 3), candidates) == []


def test_newest_per_major_treats_single_numbers_as_one_line():
    assert newest_per_major((104,), [(str(n), (n,)) for n in range(100, 110)]) == ["109"]
