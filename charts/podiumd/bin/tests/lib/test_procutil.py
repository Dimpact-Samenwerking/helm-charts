"""lib.procutil.run/run_script — thin subprocess wrappers."""

from types import ModuleType

import pytest


def test_run_never_raises_on_nonzero_exit(libprocutil: ModuleType):
    result = libprocutil.run(["sh", "-c", "exit 3"])
    assert result.returncode == 3


def test_run_passes_through_kwargs(libprocutil: ModuleType):
    result = libprocutil.run(["echo", "hello"], capture_output=True, text=True)
    assert result.stdout.strip() == "hello"


# --- run_script ---


def test_run_script_runs_the_command(libprocutil: ModuleType):
    result = libprocutil.run_script(["true"])
    assert result.returncode == 0


def test_run_script_flushes_stdout_before_running(libprocutil: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """The whole point of run_script over a bare subprocess.run: flush the
    caller's own buffered prints first, so they can't appear after the
    child's inherited-stdout output once stdout isn't a tty."""
    calls = []
    monkeypatch.setattr(libprocutil.sys.stdout, "flush", lambda: calls.append("flush"))
    libprocutil.run_script(["true"])
    assert calls == ["flush"]
