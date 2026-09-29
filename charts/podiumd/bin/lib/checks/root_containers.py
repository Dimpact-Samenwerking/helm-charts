"""Report-only check for rendered containers that run as root.

A container's user comes from its securityContext (container over pod) and,
when that doesn't decide, from the image config's "User" (empty means root),
read from the registry without pulling. Image users are cached per digest in
the gitignored .cache/image-user-cache.json; a digest's config never
changes. Never fails on findings.
"""

import urllib.error

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import TypedDict
from typing import TypeGuard

from lib.checks.cve import bucket_of
from lib.checks.cve import classify_source
from lib.checks.cve import parse_image_ref
from lib.json_cache import cache_file
from lib.json_cache import load_json_cache
from lib.json_cache import save_json_cache
from lib.registry import image_config_user
from lib.registry import parse_repo
from lib.render_scope import RenderedContainer
from lib.render_scope import friendly_vendor_charts
from lib.render_scope import render_chart_docs
from lib.render_scope import rendered_containers
from lib.settings import repo_access_request_timeout_seconds
from lib.settings import root_containers_accepted
from lib.yaml_types import YamlMapping
from lib.yaml_types import shape_problem

CACHE_FILENAME = "image-user-cache.json"

Verdict = Literal["ok", "root-manifest", "root-image", "will-not-start", "unknown"]

VERDICT_TEXT = {
    "root-manifest": "runs as root (runAsUser: 0)",
    "root-image": "runs as root (image default user)",
    "will-not-start": "will not start: runAsNonRoot without a numeric non-root user",
}


class UserEntry(TypedDict):
    """An image's config "User" ("" means root)."""

    user: str


def _is_user_entry(value: object) -> TypeGuard[UserEntry]:
    return shape_problem(value, {"user": str}) is None


@dataclass(frozen=True)
class RunAs:
    """A container's effective runAsUser and runAsNonRoot (container level over pod level)."""

    user: int | None
    non_root: bool | None


def _security_value(spec: YamlMapping, key: str) -> object:
    context = spec.get("securityContext")
    return context.get(key) if isinstance(context, dict) else None


def effective_run_as(pod_spec: YamlMapping, container: YamlMapping) -> RunAs:
    """The container's run-as settings; a container setting overrides the pod's."""

    def pick(key: str) -> object:
        own = _security_value(container, key)
        return own if own is not None else _security_value(pod_spec, key)

    user, non_root = pick("runAsUser"), pick("runAsNonRoot")
    return RunAs(
        user if isinstance(user, int) and not isinstance(user, bool) else None,
        non_root if isinstance(non_root, bool) else None,
    )


def image_user_is_root(user: str) -> bool:
    """Whether an image config "User" ("name", "uid", "uid:gid" or empty) is root."""
    name = user.split(":", 1)[0].strip()
    return name in ("", "root", "0")


def root_verdict(run_as: RunAs, image_user: str | None) -> Verdict:
    """Whether the container runs as root, given its run-as settings and image user.

    `image_user` is None when it could not be read; it only matters when the
    manifest doesn't set runAsUser. The kubelet refuses runAsNonRoot with an
    image user that is root or a name, since a name can't be verified.
    """
    if run_as.user is not None:
        return "root-manifest" if run_as.user == 0 else "ok"
    if image_user is None:
        return "unknown"
    numeric_non_root = image_user.split(":", 1)[0].isdigit() and not image_user_is_root(image_user)
    if run_as.non_root:
        return "ok" if numeric_non_root else "will-not-start"
    return "root-image" if image_user_is_root(image_user) else "ok"


def _image_reference(image: str) -> tuple[str, str, str | None]:
    """(repository, tag-or-digest reference, cache key or None) of a container image string."""
    if "@sha256:" in image:
        repository, _version, digest = parse_image_ref(image)
        return repository, f"sha256:{digest}", f"{repository}@sha256:{digest}"
    repository, sep, tag = image.rpartition(":")
    if not sep or "/" in tag:
        return image, "latest", None
    return repository, tag, None


@dataclass
class _UserLookup:
    """Image users by image string: the digest cache plus this run's fetches."""

    old_cache: dict[str, UserEntry]
    timeout: float
    new_cache: dict[str, UserEntry]
    users: dict[str, str | None]

    def user(self, image: str) -> str | None:
        """`image`'s default user, from this run, the cache or the registry; None if unreadable."""
        if image in self.users:
            return self.users[image]
        repository, reference, key = _image_reference(image)
        cached = self.old_cache.get(key) if key else None
        if cached is not None:
            user: str | None = cached["user"]
        else:
            host, repo_path = parse_repo(repository)
            print(f"  reading the default user of {host}/{repo_path}@{reference[:19]}...", flush=True)
            try:
                user = image_config_user(host, repo_path, reference, timeout=self.timeout)
            except (urllib.error.URLError, OSError) as e:
                print(f"  [FETCH-ERR] {image}  {e}")
                user = None
        if key and user is not None:
            self.new_cache[key] = {"user": user}
        self.users[image] = user
        return user


@dataclass(frozen=True)
class Finding:
    """One container that runs as root, won't start, or couldn't be checked."""

    bucket: str
    label: str
    container: RenderedContainer
    image: str
    verdict: Verdict

    @property
    def key(self) -> str:
        """The root_containers.accepted key: "<source template>:<container>"."""
        return f"{self.container.source}:{self.container.container.get('name', '')}"

    def line(self) -> str:
        """The report line for this finding."""
        c = self.container
        vendor = f" [{self.label}]" if self.bucket == "partner" else ""
        what = VERDICT_TEXT.get(self.verdict, "could not read the image's default user")
        return f"{c.source} {c.kind}/{c.name} [{c.container.get('name', '')}]{vendor}: {self.image} {what}"


def _findings(containers: list[RenderedContainer], lookup: _UserLookup, vendor_map: dict[str, str]) -> list[Finding]:
    """A Finding for every container whose verdict isn't "ok"."""
    findings: list[Finding] = []
    for c in containers:
        image = str(c.container.get("image") or "")
        run_as = effective_run_as(c.pod_spec, c.container)
        verdict = root_verdict(run_as, None if run_as.user is not None else lookup.user(image))
        if verdict != "ok":
            label = classify_source(c.source, vendor_map)
            findings.append(Finding(bucket_of(label), label, c, image, verdict))
    return findings


_BUCKET_TITLES = (("own", "Own templates"), ("partner", "Partner-vendor charts"), ("other", "Other-vendor charts"))


def _print_report(findings: list[Finding], accepted: dict[str, str]) -> None:
    """Findings per bucket, then the accepted ones and fetch errors."""
    open_findings = [f for f in findings if f.key not in accepted and f.verdict != "unknown"]
    for bucket, title in _BUCKET_TITLES:
        lines = [f.line() for f in open_findings if f.bucket == bucket]
        if lines:
            print(f"--- {title} ---")
            print("\n".join(lines))
    accepted_findings = [f for f in findings if f.key in accepted]
    if accepted_findings:
        print("--- Accepted (etc/settings.yaml root_containers.accepted) ---")
        print("\n".join(f"{f.line()} — {accepted[f.key]}" for f in accepted_findings))
    unknown = [f for f in findings if f.verdict == "unknown"]
    if unknown:
        print(f"INCOMPLETE: the default user of {len(unknown)} container(s) could not be read:")
        print("\n".join(f"  {f.line()}" for f in unknown))
    elif not open_findings:
        print("OK: no container runs as root")


def _detail(findings: list[Finding], accepted: dict[str, str]) -> str:
    open_findings = [f for f in findings if f.key not in accepted and f.verdict != "unknown"]
    root = [f for f in open_findings if f.verdict in ("root-manifest", "root-image")]
    counts = ", ".join(f"{sum(1 for f in root if f.bucket == b)} {b}" for b, _title in _BUCKET_TITLES)
    will_not_start = sum(1 for f in open_findings if f.verdict == "will-not-start")
    unknown = sum(1 for f in findings if f.verdict == "unknown")
    accepted_count = sum(1 for f in findings if f.key in accepted)
    return (
        f"root: {counts}; will not start: {will_not_start}; accepted: {accepted_count}; "
        f"unreadable image user: {unknown}"
    )


def check_root_containers(chart_dir: Path, extra_args: list[str]) -> tuple[bool, str]:
    """verify-podiumd check: report rendered containers that run as root or won't start.

    Returns (True, "root: ...") regardless of findings, or (False, error) if
    the chart doesn't render.
    """
    rendered, error = render_chart_docs(chart_dir, extra_args)
    if rendered is None:
        return False, error or "helm template failed to render"
    containers = rendered_containers(rendered.docs)
    cache_path = cache_file(chart_dir, CACHE_FILENAME)
    lookup = _UserLookup(
        load_json_cache(cache_path, _is_user_entry), repo_access_request_timeout_seconds(chart_dir), {}, {}
    )
    print(f"Checking the run-as user of {len(containers)} rendered container(s)...")
    findings = _findings(containers, lookup, friendly_vendor_charts(chart_dir))
    save_json_cache(cache_path, lookup.new_cache)
    accepted = root_containers_accepted(chart_dir)
    _print_report(findings, accepted)
    return True, _detail(findings, accepted)
