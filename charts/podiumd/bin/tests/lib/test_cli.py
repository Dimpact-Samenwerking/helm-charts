"""lib.cli's input helpers: user-named files, output paths and network
failures end in a one-line SystemExit, never a traceback."""

import http.client
import urllib.error

from email.message import Message
from pathlib import Path

import pytest

from lib.cli import check_output_path
from lib.cli import flag_args
from lib.cli import network_errors
from lib.cli import read_user_file


def test_read_user_file_returns_text(tmp_path: Path):
    path = tmp_path / "token.txt"
    path.write_text("s3cr3t\n", encoding="utf-8")
    assert read_user_file(path, "--token-file") == "s3cr3t\n"


def test_read_user_file_missing(tmp_path: Path):
    with pytest.raises(SystemExit, match=r"error: --token-file .*missing\.txt does not exist or is not a file"):
        read_user_file(tmp_path / "missing.txt", "--token-file")


def test_read_user_file_directory(tmp_path: Path):
    with pytest.raises(SystemExit, match="does not exist or is not a file"):
        read_user_file(tmp_path, "--values")


def test_read_user_file_not_utf8(tmp_path: Path):
    path = tmp_path / "binary"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(SystemExit, match="can't be read"):
        read_user_file(path, "--values")


def test_check_output_path_accepts_new_file_in_existing_directory(tmp_path: Path):
    check_output_path(tmp_path / "out.csv", "--output")


def test_check_output_path_directory(tmp_path: Path):
    with pytest.raises(SystemExit, match="is a directory"):
        check_output_path(tmp_path, "--output")


def test_check_output_path_missing_parent(tmp_path: Path):
    with pytest.raises(SystemExit, match=r"directory .*missing does not exist"):
        check_output_path(tmp_path / "missing" / "out.csv", "--output")


def test_network_errors_passes_through_without_error():
    with network_errors("container registry"):
        value = 1
    assert value == 1


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            urllib.error.HTTPError("https://registry/v2/x", 429, "Too Many Requests", Message(), None),
            r"container registry request failed: HTTP 429 Too Many Requests \(https://registry/v2/x\)",
        ),
        (urllib.error.URLError("Name or service not known"), "could not reach container registry: Name or service"),
        (TimeoutError("timed out"), "connection to container registry failed: timed out"),
        (ConnectionResetError("reset by peer"), "connection to container registry failed: reset by peer"),
        (http.client.InvalidURL("URL can't contain control characters"), "invalid container registry URL"),
    ],
)
def test_network_errors_becomes_one_line_exit(error: Exception, expected: str):
    with pytest.raises(SystemExit, match=expected), network_errors("container registry"):
        raise error


def test_network_errors_leaves_other_errors_alone():
    error = KeyError("not a network error")
    with pytest.raises(KeyError), network_errors("container registry"):
        raise error


@pytest.mark.parametrize("argv", [[], ["--dry-run"]])
def test_flag_args_returns_the_given_flags(monkeypatch: pytest.MonkeyPatch, argv: list[str]):
    monkeypatch.setattr("sys.argv", ["script", *argv])
    assert flag_args("doc", "--dry-run") == set(argv)


@pytest.mark.parametrize("argv", [["-h"], ["-h", "--dry-run"], ["--dry-run", "-h"], ["--help"], ["--bogus", "-h"]])
def test_flag_args_prints_help_for_h_anywhere(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
):
    monkeypatch.setattr("sys.argv", ["script", *argv])
    with pytest.raises(SystemExit) as exc:
        flag_args("doc", "--dry-run")
    assert exc.value.code == 0
    assert capsys.readouterr().out == "doc\n"


def test_flag_args_rejects_an_unknown_argument(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr("sys.argv", ["script", "--dry-rn"])
    with pytest.raises(SystemExit) as exc:
        flag_args("doc", "--dry-run")
    assert exc.value.code == 1
    assert capsys.readouterr().out == "doc\n"
