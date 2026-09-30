"""lib.chart.yaml_alias_groups — alias_groups_in_text, alias_groups."""

from pathlib import Path

from lib.chart.yaml_alias_groups import alias_groups
from lib.chart.yaml_alias_groups import alias_groups_in_text


def test_scalar_alias_groups_anchor_first():
    text = "a:\n  job:\n    tag: &t '1.0'\n  server:\n    tag: *t\n"
    group = ("a.job.tag", "a.server.tag")
    assert alias_groups_in_text(text) == {"a.job.tag": group, "a.server.tag": group}


def test_mapping_alias_groups_every_scalar_under_it():
    text = "r:\n  cron:\n    image: &i\n      repository: k8s\n      tag: '1.37.0'\n  pre:\n    image: *i\n"
    groups = alias_groups_in_text(text)
    assert groups["r.cron.image.tag"] == ("r.cron.image.tag", "r.pre.image.tag")
    assert groups["r.pre.image.repository"] == ("r.cron.image.repository", "r.pre.image.repository")


def test_merge_key_shares_values_but_explicit_key_wins():
    text = "base: &b\n  tag: '1'\n  repo: x\nuse:\n  <<: *b\n  tag: '2'\n"
    groups = alias_groups_in_text(text)
    assert groups["use.repo"] == ("base.repo", "use.repo")
    assert "use.tag" not in groups
    assert "base.tag" not in groups


def test_unshared_values_and_empty_document_have_no_groups():
    assert not alias_groups_in_text("a:\n  tag: '1'\nb:\n  tag: '1'\n")
    assert not alias_groups_in_text("")


def test_alias_groups_reads_the_file(tmp_path: Path):
    values = tmp_path / "values.yaml"
    values.write_text("x: &v '1'\ny: *v\n", encoding="utf-8")
    assert alias_groups(values) == {"x": ("x", "y"), "y": ("x", "y")}
