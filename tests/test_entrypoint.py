"""`python -m dejavu` must work.

It is the shell-agnostic entry point the Windows install guide falls back to when the
console script is not on PATH, so a regression here would silently break that advice.
"""

from __future__ import annotations

import subprocess
import sys


def test_module_entrypoint_reports_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "dejavu", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "dejavu" in result.stdout
