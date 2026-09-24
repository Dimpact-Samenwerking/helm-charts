"""lib.images_manifest — parse_images_manifest, try_parse_images_manifest,
images_manifest_problem."""

import pytest

from lib.images_manifest import images_manifest_problem
from lib.images_manifest import parse_images_manifest
from lib.images_manifest import try_parse_images_manifest
from lib.yaml_types import YamlShapeError

COMPLETE = '- name: a/b\n  url: docker.io/a/b\n  version: "1.0"\n  digest: "sha256:aa"\n'
DRAFT = "- name: a/b\n  url: docker.io/a/b\n"


def test_parse_images_manifest_reads_entries():
    assert parse_images_manifest(COMPLETE, "m.yaml") == [
        {"name": "a/b", "url": "docker.io/a/b", "version": "1.0", "digest": "sha256:aa"}
    ]
    assert parse_images_manifest("", "m.yaml") == []
    assert parse_images_manifest("[]\n", "m.yaml") == []


def test_parse_images_manifest_accepts_a_draft_entry():
    assert parse_images_manifest(DRAFT, "m.yaml") == [{"name": "a/b", "url": "docker.io/a/b"}]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("a: 1\n", "does not contain a YAML list of mappings"),
        ("- url: x\n", "entry #1 is missing key(s): name"),
        ("- name: a\n  version: 1.10\n", "entry #1: version must be a quoted string"),
    ],
)
def test_parse_images_manifest_names_the_problem(text, problem):
    with pytest.raises(YamlShapeError) as excinfo:
        parse_images_manifest(text, "m.yaml")
    assert str(excinfo.value) == f"m.yaml: {problem}"


def test_try_parse_images_manifest_returns_none_for_broken_documents():
    assert try_parse_images_manifest("- name: [unclosed\n") is None
    assert try_parse_images_manifest("a: 1\n") is None
    assert try_parse_images_manifest(DRAFT) == [{"name": "a/b", "url": "docker.io/a/b"}]


def test_images_manifest_problem_requires_all_four_keys():
    assert images_manifest_problem([{"name": "a/b", "url": "u", "version": "1", "digest": "d"}]) is None
    assert images_manifest_problem([{"name": "a/b", "url": "u"}]) == "entry #1 is missing key(s): version, digest"
