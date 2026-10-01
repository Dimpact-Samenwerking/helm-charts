"""lib.version_numbers — is_bare_version, dotted_numbers, stable_semver_key."""

from lib.version_numbers import dotted_numbers
from lib.version_numbers import is_bare_version
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
