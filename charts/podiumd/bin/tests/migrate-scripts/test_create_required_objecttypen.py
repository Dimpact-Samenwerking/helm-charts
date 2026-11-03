"""templates/create-required-objecttypen.yaml: the Job's Python script, run against an in-memory Objecttypen API.

The script has no Helm expressions, so it is taken from the template as is;
/schemas, where the Job mounts files/objecttypen/, points at that directory.
"""

import json
import runpy
import sys
import textwrap

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

SCRIPT_KEY = "  create-required-objecttypen.py: |\n"
API = "http://objecten.test/api/v2"
PAGE_SIZE = 3
PRODUCTAANVRAAG = "Productaanvraag-Dimpact"


def job_script(template: Path, schemas_dir: Path) -> str:
    """The script in the configmap's create-required-objecttypen.py literal block, dedented."""
    lines = template.read_text(encoding="utf-8").splitlines(keepends=True)
    start = lines.index(SCRIPT_KEY) + 1
    end = next(
        (n for n in range(start, len(lines)) if lines[n].strip() and not lines[n].startswith("    ")), len(lines)
    )
    source = textwrap.dedent("".join(lines[start:end]))
    assert source.count("schemas_dir = '/schemas'\n") == 1
    return source.replace("schemas_dir = '/schemas'\n", f"schemas_dir = {str(schemas_dir)!r}\n")


@dataclass
class Response:
    status_code: int
    body: Any

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        return json.dumps(self.body)

    def json(self) -> Any:
        return self.body


@dataclass
class ObjecttypesApi:
    """Objecttypes and their versions, served the way Open Object's API pages and numbers them."""

    types: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    posts: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])
    fail_on: str | None = None

    def add(self, name: str, *versions: tuple[str, Any], name_plural: str | None = None) -> None:
        uuid = f"uuid-{name}"
        self.types[uuid] = {
            "uuid": uuid,
            "name": name,
            "namePlural": name_plural or f"{name}s",
            "versions": [
                {"version": n, "status": status, "jsonSchema": schema}
                for n, (status, schema) in enumerate(versions, start=1)
            ],
        }

    def _page(self, url: str, items: list[Any], params: dict[str, str] | None) -> Response:
        start = 0 if params is not None else int(url.rsplit("page=", 1)[1])
        base = url.split("?", 1)[0]
        more = start + PAGE_SIZE < len(items)
        return Response(
            200,
            {"results": items[start : start + PAGE_SIZE], "next": f"{base}?page={start + PAGE_SIZE}" if more else None},
        )

    def get(self, url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> Response:
        assert headers == {"Authorization": "Token admin-token"}
        if self.fail_on and self.fail_on in url:
            return Response(500, {"detail": "boom"})
        path = url.split("?", 1)[0].removeprefix(API)
        if path == "/objecttypes":
            listed = [
                {**t, "versions": [f"{API}/objecttypes/{t['uuid']}/versions/{v['version']}" for v in t["versions"]]}
                for t in self.types.values()
            ]
            return self._page(url, listed, params)
        uuid = path.removeprefix("/objecttypes/").removesuffix("/versions")
        return self._page(url, self.types[uuid]["versions"], params)

    def post(self, url: str, json: Any = None, headers: dict[str, str] | None = None) -> Response:
        assert headers is not None
        assert headers["Authorization"] == "Token admin-token"
        path = url.removeprefix(API)
        self.posts.append((path, json))
        if path == "/objecttypes":
            self.types[json["uuid"]] = {**json, "versions": []}
            return Response(201, {"uuid": json["uuid"]})
        versions = self.types[path.removeprefix("/objecttypes/").removesuffix("/versions")]["versions"]
        versions.append({"version": len(versions) + 1, **json})
        return Response(201, versions[-1])

    def name_of(self, path: str) -> str:
        return self.types[path.split("/")[2]]["name"]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> ObjecttypesApi:
    fake = ObjecttypesApi()
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=fake.get, post=fake.post))
    monkeypatch.setenv("AUTHORIZATION_TOKEN", "admin-token")
    monkeypatch.setenv("OBJECTTYPES_URL", API)
    return fake


RunJob = Callable[[list[str] | None], None]


@pytest.fixture(scope="module")
def schemas_dir(scripts_dir: Path) -> Path:
    """files/objecttypen/, which the Job mounts at /schemas."""
    return scripts_dir.parent / "files" / "objecttypen"


@pytest.fixture(scope="module")
def schemas(schemas_dir: Path) -> dict[str, Any]:
    """The chart's objecttype schemas by objecttype name."""
    return {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in schemas_dir.glob("*.json")}


@pytest.fixture
def run_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, scripts_dir: Path, schemas_dir: Path) -> RunJob:
    """Runs the Job's script; the argument is UPDATE_EXISTING_VERSIONS, None for unset."""
    template = scripts_dir.parent / "templates" / "create-required-objecttypen.yaml"
    script = tmp_path / "create-required-objecttypen.py"
    script.write_text(job_script(template, schemas_dir), encoding="utf-8")

    def run(update_existing_versions: list[str] | None) -> None:
        if update_existing_versions is None:
            monkeypatch.delenv("UPDATE_EXISTING_VERSIONS", raising=False)
        else:
            monkeypatch.setenv("UPDATE_EXISTING_VERSIONS", json.dumps(update_existing_versions))
        runpy.run_path(str(script), run_name="__main__")

    return run


def test_an_empty_api_gets_every_objecttype_with_a_published_version(
    api: ObjecttypesApi, run_job: RunJob, schemas: dict[str, Any]
):
    run_job(None)

    assert sorted(t["name"] for t in api.types.values()) == sorted(schemas)
    for objecttype in api.types.values():
        assert [(v["version"], v["status"]) for v in objecttype["versions"]] == [(1, "published")]
        assert objecttype["versions"][0]["jsonSchema"] == schemas[objecttype["name"]]


def test_existing_objecttypes_without_versions_only_get_a_version(
    api: ObjecttypesApi, run_job: RunJob, schemas: dict[str, Any]
):
    """objecten's objecttypes setup step creates the types without versions."""
    for name in sorted(schemas):
        api.add(name)

    run_job(None)

    assert all(path.endswith("/versions") for path, _ in api.posts)
    assert sorted(api.name_of(path) for path, _ in api.posts) == sorted(schemas)


@pytest.mark.parametrize("update_existing_versions", [None, []])
def test_objecttypes_with_a_version_are_left_alone_by_default(
    api: ObjecttypesApi, run_job: RunJob, schemas: dict[str, Any], update_existing_versions: list[str] | None
):
    for name in sorted(schemas):
        api.add(name, ("published", {"old": True}))

    run_job(update_existing_versions)

    assert api.posts == []


def test_a_listed_objecttype_gets_a_new_version_when_its_published_schema_differs(
    api: ObjecttypesApi, run_job: RunJob, schemas: dict[str, Any]
):
    for name in sorted(schemas):
        api.add(name, ("published", {"old": True}))

    run_job([PRODUCTAANVRAAG])

    assert api.posts == [
        (
            f"/objecttypes/uuid-{PRODUCTAANVRAAG}/versions",
            {"status": "published", "jsonSchema": schemas[PRODUCTAANVRAAG]},
        )
    ]


def test_a_draft_on_top_of_the_current_published_schema_changes_nothing(
    api: ObjecttypesApi, run_job: RunJob, schemas: dict[str, Any]
):
    for name in sorted(schemas):
        api.add(name, ("published", schemas[name]), ("draft", {"draft": True}))

    run_job([PRODUCTAANVRAAG])

    assert api.posts == []


OLD = ("published", {"old": True})


@pytest.mark.parametrize(
    ("existing", "update_existing_versions"),
    [([], None), ([OLD], [PRODUCTAANVRAAG])],
    ids=["create", "update"],
)
def test_a_second_run_changes_nothing(
    api: ObjecttypesApi,
    run_job: RunJob,
    schemas: dict[str, Any],
    existing: list[tuple[str, Any]],
    update_existing_versions: list[str] | None,
):
    """The Job runs on every deploy."""
    for name in sorted(schemas) if existing else []:
        api.add(name, *existing)
    run_job(update_existing_versions)
    first = list(api.posts)

    run_job(update_existing_versions)

    assert first
    assert api.posts == first


@pytest.mark.parametrize(
    ("versions", "new_versions"),
    [
        ([OLD, ("published", "CHART")], 0),
        ([("published", "CHART"), OLD], 1),
        ([("draft", {"draft": True})], 1),
        ([OLD, OLD, OLD, ("published", "CHART")], 0),
    ],
    ids=["highest-published-is-current", "highest-published-is-old", "only-drafts", "beyond-the-first-page"],
)
def test_the_highest_published_version_decides(
    api: ObjecttypesApi,
    run_job: RunJob,
    schemas: dict[str, Any],
    versions: list[tuple[str, Any]],
    new_versions: int,
):
    """A "CHART" schema stands for the chart's schema; the fake pages the versions list by PAGE_SIZE."""
    for name in sorted(schemas):
        if name == PRODUCTAANVRAAG:
            api.add(name, *[(status, schemas[name] if schema == "CHART" else schema) for status, schema in versions])
        else:
            api.add(name, ("published", schemas[name]))

    run_job([PRODUCTAANVRAAG])

    expected = [
        (
            f"/objecttypes/uuid-{PRODUCTAANVRAAG}/versions",
            {"status": "published", "jsonSchema": schemas[PRODUCTAANVRAAG]},
        )
    ]
    assert api.posts == expected * new_versions


def test_an_objecttype_is_found_by_its_plural_name(api: ObjecttypesApi, run_job: RunJob, schemas: dict[str, Any]):
    """A type renamed in Objecten keeps matching on namePlural, so it is not created again."""
    for name in sorted(schemas):
        if name == PRODUCTAANVRAAG:
            api.add("Productaanvraag (renamed)", name_plural="Productaanvragen-Dimpact")
        else:
            api.add(name, ("published", schemas[name]))

    run_job(None)

    assert api.posts == [
        (
            "/objecttypes/uuid-Productaanvraag (renamed)/versions",
            {"status": "published", "jsonSchema": schemas[PRODUCTAANVRAAG]},
        )
    ]


def test_a_failed_request_stops_the_job_with_its_status(api: ObjecttypesApi, run_job: RunJob):
    api.fail_on = "/objecttypes"

    with pytest.raises(SystemExit, match=r"listing objecttypes failed: HTTP 500"):
        run_job(None)
