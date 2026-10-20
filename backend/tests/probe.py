"""One way to run a child-process probe, so the same Windows bug cannot bite a fourth time.

Twice now a test that asserts something true has gone red for a reason that has nothing to
do with its assertion: under pytest's capture on Windows the inherited stdin handle is
already closed, so `subprocess.Popen._make_inheritable` raises
`OSError [WinError 6] The handle is invalid` before the child process even starts. Both
times the fix was `stdin=subprocess.DEVNULL`, and both times it was rediscovered from the
traceback rather than from the previous fix.

So import-purity probes go through here. `stdin=DEVNULL` is a correctness requirement of
running a subprocess under pytest on Windows, not tidiness -- do not remove it.

`-I` is deliberately NOT used: isolated mode implies `-E`, which ignores PYTHONPATH, and
PYTHONPATH is how the child finds the repo. A probe that cannot import `backend` proves
nothing about what `backend` imports.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_probe(code: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run `code` in a fresh interpreter that can import `backend`, and return the result."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=check,
        # Required, not tidiness. See the module docstring.
        stdin=subprocess.DEVNULL,
    )
