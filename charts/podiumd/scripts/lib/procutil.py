"""Tiny subprocess wrapper shared by every script that shells out to
`helm`/`git` — never raises on a non-zero exit, so callers decide what a
failure means for them."""
import subprocess


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=False, **kwargs)
