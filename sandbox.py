"""Sandboxed test runner.

Writes the candidate module and the generated tests into an isolated temp
directory and runs pytest in a subprocess with a hard timeout. Nothing here
touches the user's real files.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .providers import MODULE_NAME


@dataclass
class RunResult:
    passed: bool
    n_passed: int
    n_failed: int
    n_errors: int
    output: str

    @property
    def summary(self) -> str:
        bits = []
        if self.n_passed:
            bits.append(f"{self.n_passed} passed")
        if self.n_failed:
            bits.append(f"{self.n_failed} failed")
        if self.n_errors:
            bits.append(f"{self.n_errors} errors")
        return ", ".join(bits) or "no tests collected"


_COUNT = re.compile(r"(\d+) (passed|failed|error|errors)")


def _parse_counts(output: str):
    n_passed = n_failed = n_errors = 0
    for num, kind in _COUNT.findall(output):
        n = int(num)
        if kind == "passed":
            n_passed = n
        elif kind == "failed":
            n_failed = n
        else:
            n_errors = n
    return n_passed, n_failed, n_errors


def run_pytest(improved_code: str, tests_code: str, timeout: int = 60) -> RunResult:
    with tempfile.TemporaryDirectory(prefix="selfcorrect_") as d:
        tmp = Path(d)
        (tmp / f"{MODULE_NAME}.py").write_text(improved_code, encoding="utf-8")
        (tmp / f"test_{MODULE_NAME}.py").write_text(tests_code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--no-header",
                 "-p", "no:cacheprovider", str(tmp)],
                cwd=str(tmp),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            n_passed, n_failed, n_errors = _parse_counts(output)
            passed = proc.returncode == 0 and n_failed == 0 and n_errors == 0
            return RunResult(passed, n_passed, n_failed, n_errors, output.strip())
        except subprocess.TimeoutExpired:
            return RunResult(False, 0, 0, 1, f"Test run timed out after {timeout}s.")
