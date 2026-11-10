"""Fake image digests, chart file writers and a raising stand-in shared by the test suites."""

from collections.abc import Callable
from collections.abc import Iterable
from pathlib import Path
from typing import NoReturn

import yaml


def hex_digest(fill: str) -> str:
    """A fake 64-character sha256 hex digest made of `fill`."""
    return fill * 64


def sha256_digest(fill: str) -> str:
    """A fake "sha256:<hex>" digest made of `fill`."""
    hex_part = hex_digest(fill)
    return f"sha256:{hex_part}"


HEX_A = hex_digest("a")
HEX_B = hex_digest("b")
HEX_C = hex_digest("c")
HEX_D = hex_digest("d")
HEX_E = hex_digest("e")
HEX_F = hex_digest("f")
SHA256_A = sha256_digest("a")
SHA256_B = sha256_digest("b")
SHA256_C = sha256_digest("c")
SHA256_D = sha256_digest("d")
SHA256_E = sha256_digest("e")
SHA256_F = sha256_digest("f")


def write_lines(path: Path, lines: Iterable[str]) -> None:
    """Write `lines` to `path` as UTF-8, each ending in a newline."""
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def write_values_text(chart_dir: Path, text: str) -> Path:
    """Write `text` as chart_dir's values.yaml and return its path."""
    path = chart_dir / "values.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def write_empty_value_blocks(chart_dir: Path, keys: Iterable[str]) -> None:
    """values.yaml with each of `keys` as an empty top-level block."""
    write_lines(chart_dir / "values.yaml", (f"{key}: {{}}" for key in keys))


def write_global_images(chart_dir: Path, image_keys: Iterable[str]) -> None:
    """values.yaml with a global.images map of `image_keys` (shared-image anchors)."""
    write_lines(chart_dir / "values.yaml", ["global:", "  images:", *(f"    {key}: {{}}" for key in image_keys)])


def write_chart_version(chart_dir: Path, version: str) -> None:
    """A podiumd Chart.yaml with `version` and no dependencies."""
    write_lines(chart_dir / "Chart.yaml", ["apiVersion: v2", "name: podiumd", f"version: {version}"])


def write_chart_with_dependencies(chart_dir: Path, deps: Iterable[tuple[str, str | None]]) -> None:
    """A podiumd Chart.yaml with `deps` as [(name, alias_or_None), ...], each at version 1.0.0."""
    lines = ["apiVersion: v2", "name: podiumd", "version: 1.0.0", "dependencies:"]
    for name, alias in deps:
        lines.append(f"  - name: {name}")
        if alias:
            lines.append(f"    alias: {alias}")
        lines += ["    version: 1.0.0", '    repository: "@x"']
    write_lines(chart_dir / "Chart.yaml", lines)


def write_chart_dependencies(chart_yaml: Path, deps: list[dict[str, str]]) -> None:
    """A Chart.yaml at `chart_yaml` holding only `deps` as its dependencies."""
    chart_yaml.write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")


def raising(error: BaseException | type[BaseException]) -> Callable[..., NoReturn]:
    """A stand-in for a function that raises `error` whatever it is called with."""

    def raise_error(*_args: object, **_kwargs: object) -> NoReturn:
        raise error

    return raise_error
