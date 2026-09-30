"""lib.checks.root_containers, image_config_user and rendered_containers."""

import urllib.error
import urllib.request

from email.message import Message
from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast

import pytest

from lib import registry
from lib.checks import root_containers
from lib.checks.cve import split_image_ref
from lib.checks.root_containers import RunAs
from lib.checks.root_containers import check_root_containers
from lib.checks.root_containers import effective_run_as
from lib.checks.root_containers import image_user_is_root
from lib.checks.root_containers import root_verdict
from lib.registry import image_config_user
from lib.render_scope import RenderedDocs
from lib.render_scope import rendered_containers
from lib.render_scope import split_rendered_by_source

if TYPE_CHECKING:
    from lib.yaml_types import YamlValue


@pytest.mark.parametrize(
    ("pod", "container", "expected"),
    [
        ({}, {}, RunAs(user=None, non_root=None)),
        ({"securityContext": {"runAsUser": 1000, "runAsNonRoot": True}}, {}, RunAs(user=1000, non_root=True)),
        ({"securityContext": {"runAsUser": 1000}}, {"securityContext": {"runAsUser": 0}}, RunAs(user=0, non_root=None)),
        (
            {"securityContext": {"runAsNonRoot": True}},
            {"securityContext": {"runAsNonRoot": False}},
            RunAs(user=None, non_root=False),
        ),
    ],
    ids=["unset", "pod-level", "container-overrides-pod", "container-non-root-false"],
)
def test_effective_run_as_prefers_the_container(pod, container, expected: RunAs):
    assert effective_run_as(pod, container) == expected


@pytest.mark.parametrize(
    ("run_as", "image_user", "verdict"),
    [
        (RunAs(user=0, non_root=None), "1000", "root-manifest"),
        (RunAs(user=1000, non_root=None), "", "ok"),
        (RunAs(user=None, non_root=True), "65532", "ok"),
        (RunAs(user=None, non_root=True), "65532:65532", "ok"),
        (RunAs(user=None, non_root=True), "", "will-not-start"),
        (RunAs(user=None, non_root=True), "curl_user", "will-not-start"),
        (RunAs(user=None, non_root=None), "", "root-image"),
        (RunAs(user=None, non_root=None), "root", "root-image"),
        (RunAs(user=None, non_root=None), "0:0", "root-image"),
        (RunAs(user=None, non_root=None), "101", "ok"),
        (RunAs(user=None, non_root=None), "gotenberg", "ok"),
        (RunAs(user=None, non_root=None), None, "unknown"),
    ],
)
def test_root_verdict(run_as: RunAs, image_user: str | None, verdict: str):
    assert root_verdict(run_as, image_user) == verdict


def test_image_user_is_root():
    assert all(image_user_is_root(u) for u in ("", "root", "0", "0:0", "root:root"))
    assert not any(image_user_is_root(u) for u in ("1000", "65532:65532", "curl_user"))


RENDER = """\
---
# Source: podiumd/templates/app.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
spec:
  template:
    spec:
      initContainers:
        - name: wait
          image: example/wait:1.0@sha256:aaaa
      containers:
        - name: app
          image: example/app:2.0@sha256:bbbb
          securityContext:
            runAsUser: 1000
---
# Source: podiumd/charts/vendor/templates/cron.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cron
spec:
  jobTemplate:
    spec:
      template:
        spec:
          securityContext:
            runAsNonRoot: true
          containers:
            - name: job
              image: example/job:3.0@sha256:cccc
---
# Source: podiumd/templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cm
"""


def test_rendered_containers_walks_every_workload_kind_and_init_containers():
    containers = rendered_containers(split_rendered_by_source(RENDER))
    assert [(c.kind, c.name, c.container["name"], c.init) for c in containers] == [
        ("Deployment", "app", "wait", True),
        ("Deployment", "app", "app", False),
        ("CronJob", "cron", "job", False),
    ]


def _run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, users: dict[str, str | None], accepted: str = "{}"
) -> tuple[tuple[bool, str], list[str]]:
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "settings.yaml").write_text(f"root_containers:\n  accepted: {accepted}\n", encoding="utf-8")
    monkeypatch.setattr(
        root_containers,
        "render_chart_docs",
        lambda chart_dir, extra_args: (RenderedDocs({}, split_rendered_by_source(RENDER)), None),
    )
    monkeypatch.setattr(root_containers, "friendly_vendor_charts", lambda chart_dir: {})
    calls: list[str] = []

    def fake_user(host: str, repo: str, reference: str, timeout: float | None = None) -> str:
        calls.append(repo)
        user = users[repo]
        if user is None:
            msg = "unreachable"
            raise urllib.error.URLError(msg)
        return user

    monkeypatch.setattr(root_containers, "image_config_user", fake_user)
    return check_root_containers(tmp_path, []), calls


def test_check_reports_root_and_will_not_start_and_caches_by_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    users: dict[str, str | None] = {"example/wait": "", "example/job": "named"}
    result, calls = _run(monkeypatch, tmp_path, users)

    assert result == (True, "root: 1 own, 0 partner, 0 other; will not start: 1; accepted: 0; unreadable image user: 0")
    out = capsys.readouterr().out
    assert "Deployment/app [wait]:\n    example/wait:1.0@sha256:aaaa\n    runs as root (image default user)\n" in out
    assert "CronJob/cron [job]:\n    example/job:3.0@sha256:cccc\n    will not start" in out
    assert "example/app" not in calls  # runAsUser decides; the image isn't read
    # A second run reads both users from the digest cache.
    assert _run(monkeypatch, tmp_path, users)[1] == []


def test_accepted_container_is_listed_as_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    accepted = '{"podiumd/templates/app.yaml:wait": "waits for the database, upstream image"}'
    result, _ = _run(monkeypatch, tmp_path, {"example/wait": "", "example/job": "1000"}, accepted)

    assert result[1] == "root: 0 own, 0 partner, 0 other; will not start: 0; accepted: 1; unreadable image user: 0"
    out = capsys.readouterr().out
    assert "--- Accepted" in out
    assert "\n    accepted: waits for the database, upstream image" in out
    assert "OK: no container runs as root" in out


def test_unreadable_image_user_is_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    result, _ = _run(monkeypatch, tmp_path, {"example/wait": None, "example/job": "1000"})

    assert result[1].endswith("unreadable image user: 1")
    out = capsys.readouterr().out
    assert "INCOMPLETE: the default user of 1 container(s) could not be read" in out
    assert "OK:" not in out


INDEX: "YamlValue" = {
    "manifests": [
        {"digest": "sha256:arm", "platform": {"os": "linux", "architecture": "arm64"}},
        {"digest": "sha256:amd", "platform": {"os": "linux", "architecture": "amd64"}},
    ]
}


def test_image_config_user_picks_the_amd64_image_of_an_index(monkeypatch: pytest.MonkeyPatch):
    responses: dict[str, YamlValue] = {
        "manifests/1.0": INDEX,
        "manifests/sha256:amd": {"config": {"digest": "sha256:cfg"}},
        "blobs/sha256:cfg": {"config": {"User": "65532"}},
    }
    monkeypatch.setattr(registry, "_registry_json", lambda host, repo, path, accept, timeout: responses[path])
    assert image_config_user("quay.io", "x/y", "1.0") == "65532"


def test_image_config_user_without_user_is_root(monkeypatch: pytest.MonkeyPatch):
    responses: dict[str, YamlValue] = {
        "manifests/1.0": {"config": {"digest": "sha256:cfg"}},
        "blobs/sha256:cfg": {"config": {}},
    }
    monkeypatch.setattr(registry, "_registry_json", lambda host, repo, path, accept, timeout: responses[path])
    assert image_config_user("quay.io", "x/y", "1.0") == ""


def test_redirect_to_another_host_drops_the_authorization_header():
    handler = registry._DropAuthOnRedirect()  # pyright: ignore[reportPrivateUsage]
    request = urllib.request.Request(
        "https://registry.example/v2/x/blobs/sha256:1", headers={"Authorization": "Bearer t"}
    )
    headers = cast("registry.HTTPMessage", Message())
    fp = cast("registry.IO[bytes]", None)

    to_cdn = handler.redirect_request(request, fp, 307, "Temporary Redirect", headers, "https://cdn.example/blob")
    same_host = handler.redirect_request(request, fp, 307, "Temporary Redirect", headers, "https://registry.example/b")

    assert to_cdn is not None and not to_cdn.has_header("Authorization")
    assert same_host is not None and same_host.has_header("Authorization")


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("example/app:1.0@sha256:abc", ("example/app", "1.0", "abc")),
        ("example/app@sha256:abc", ("example/app", None, "abc")),
        ("example/app:1.0", ("example/app", "1.0", None)),
        ("registry:5000/app", ("registry:5000/app", None, None)),
        ("registry:5000/app:2", ("registry:5000/app", "2", None)),
    ],
)
def test_split_image_ref(ref: str, expected: tuple[str, str | None, str | None]):
    assert split_image_ref(ref) == expected
