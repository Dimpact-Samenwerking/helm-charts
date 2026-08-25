"""lib.procutil.run/run_script — thin subprocess wrappers."""


def test_run_never_raises_on_nonzero_exit(libprocutil):
    result = libprocutil.run(["sh", "-c", "exit 3"])
    assert result.returncode == 3


def test_run_passes_through_kwargs(libprocutil):
    result = libprocutil.run(["echo", "hello"], capture_output=True, text=True)
    assert result.stdout.strip() == "hello"


# --- run_script ---

def test_run_script_runs_the_command(libprocutil):
    result = libprocutil.run_script(["true"])
    assert result.returncode == 0


def test_run_script_passes_through_kwargs(libprocutil):
    result = libprocutil.run_script(["echo", "hello"], capture_output=True, text=True)
    assert result.stdout.strip() == "hello"


def test_run_script_flushes_stdout_before_running(libprocutil, monkeypatch):
    """The whole point of run_script over a bare subprocess.run: flush the
    caller's own buffered prints first, so they can't appear after the
    child's inherited-stdout output once stdout isn't a tty."""
    calls = []
    monkeypatch.setattr(libprocutil.sys.stdout, "flush", lambda: calls.append("flush"))
    libprocutil.run_script(["true"])
    assert calls == ["flush"]
