"""lib.version_numbers — dotted_numbers, stable_semver_key."""

from lib.version_numbers import dotted_numbers
from lib.version_numbers import stable_semver_key


def test_dotted_numbers_compare_numerically():
    assert dotted_numbers("1.10.0") > dotted_numbers("1.9.3")
    assert dotted_numbers("3") == (3,)


def test_stable_semver_key_accepts_v_prefix_and_rejects_prereleases():
    assert stable_semver_key("v1.2.3") == (1, 2, 3)
    assert stable_semver_key("1.2.3-rc.1") is None
    assert stable_semver_key("1.2") is None
