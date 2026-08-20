"""lib.procutil.run — a thin, never-raising subprocess wrapper."""


def test_run_never_raises_on_nonzero_exit(libprocutil):
    result = libprocutil.run(["sh", "-c", "exit 3"])
    assert result.returncode == 3


def test_run_passes_through_kwargs(libprocutil):
    result = libprocutil.run(["echo", "hello"], capture_output=True, text=True)
    assert result.stdout.strip() == "hello"
