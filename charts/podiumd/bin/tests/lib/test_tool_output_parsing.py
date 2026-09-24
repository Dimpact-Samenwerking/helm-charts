"""Checked parsing of tool JSON output: kubeconform, shellcheck, kube-score
(lib.checks.*), and lib.yaml_types.shape_problem behind them."""

import json

from lib.checks.kube_score import is_kube_score_objects
from lib.checks.kubeconform import parse_kubeconform_output
from lib.checks.shellcheck import parse_shellcheck_output
from lib.yaml_types import shape_problem

RESOURCE = {"filename": "stdin", "kind": "Pod", "name": "x", "version": "v1", "status": "statusInvalid", "msg": "bad"}
COMMENT = {
    "file": "-",
    "line": 1,
    "endLine": 1,
    "column": 6,
    "endColumn": 8,
    "level": "info",
    "code": 2086,
    "message": "Double quote to prevent globbing and word splitting.",
    "fix": None,
}


def test_parse_kubeconform_output():
    assert parse_kubeconform_output(json.dumps({"resources": [RESOURCE]})) == [RESOURCE]
    assert parse_kubeconform_output(json.dumps({"resources": []})) == []
    assert parse_kubeconform_output("not json") is None
    assert parse_kubeconform_output(json.dumps({"resources": [{**RESOURCE, "status": 1}]})) is None
    assert parse_kubeconform_output(json.dumps({"other": []})) is None


def test_parse_shellcheck_output():
    assert parse_shellcheck_output(json.dumps({"comments": [COMMENT]})) == [COMMENT]
    assert parse_shellcheck_output(json.dumps({"comments": [{**COMMENT, "code": "2086"}]})) is None
    assert parse_shellcheck_output("") is None


def test_kube_score_object_list_shape():
    check = {"check": {"id": "container-resources"}, "grade": 1, "skipped": False}
    assert is_kube_score_objects([{"object_name": "Pod/v1//x", "checks": [{**check, "comments": None}]}])
    comment = {"path": "c", "summary": "no limits", "description": "..."}
    assert is_kube_score_objects([{"object_name": "Pod/v1//x", "checks": [{**check, "comments": [comment]}]}])
    assert not is_kube_score_objects(
        [{"object_name": "Pod/v1//x", "checks": [{**check, "grade": True, "comments": None}]}]
    )


def test_shape_problem_messages():
    assert shape_problem({"a": [1, "x"]}, {"a": [int]}) == "a[1]: expected int, got str"
    assert shape_problem({}, {"a": int}) == "(top level): missing 'a'"
    assert shape_problem(value=True, shape=int) == "(top level): expected int, got bool"
    assert shape_problem(None, (int, type(None))) is None
