"""Sandboxed test runner.

Writes the candidate module and the generated tests into an isolated temp
directory and runs pytest. On Vercel / other serverless hosts, spawning a
subprocess is unreliable, so we fall back to (or prefer) an in-process run.
Nothing here touches the user's real files.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
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


def _prefer_inprocess() -> bool:
    """Serverless platforms (Vercel, AWS Lambda, …) often break subprocess pytest."""
    if os.environ.get("SELFCORRECT_INPROCESS", "").strip() == "1":
        return True
    if os.environ.get("SELFCORRECT_INPROCESS", "").strip() == "0":
        return False
    return bool(
        os.environ.get("VERCEL")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("FUNCTION_TARGET")
    )


def _run_subprocess(tmp: Path, timeout: int) -> RunResult:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header",
             "-p", "no:cacheprovider", str(tmp)],
            cwd=str(tmp),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        n_passed, n_failed, n_errors = _parse_counts(output)
        # Treat "couldn't even start pytest" as an error, not a clean fail.
        if proc.returncode != 0 and n_passed == n_failed == n_errors == 0 and output.strip():
            if "No module named pytest" in output or "ModuleNotFoundError" in output:
                n_errors = 1
        passed = proc.returncode == 0 and n_failed == 0 and n_errors == 0
        return RunResult(passed, n_passed, n_failed, n_errors, output.strip())
    except subprocess.TimeoutExpired:
        return RunResult(False, 0, 0, 1, f"Test run timed out after {timeout}s.")
    except OSError as e:
        return RunResult(False, 0, 0, 1, f"Subprocess spawn failed: {e}")


def _sandbox_module_names():
    """Modules written into the sandbox that must not leak across runs."""
    return (MODULE_NAME, f"test_{MODULE_NAME}")


def _drop_sandbox_modules():
    dropped = []
    for base in _sandbox_module_names():
        for name in list(sys.modules):
            if name == base or name.startswith(f"{base}."):
                dropped.append((name, sys.modules.pop(name)))
    return dropped


def _run_inprocess(tmp: Path) -> RunResult:
    """Run pytest inside the current interpreter (works on Vercel)."""
    import pytest  # local: keeps headless import light when unused

    # Isolate the sandbox on sys.path and drop any cached solution/test modules.
    # Without this, a second TemporaryDirectory run hits pytest's
    # "import file mismatch" because test_solution stays cached from run 1.
    prev_path = list(sys.path)
    prev_cwd = os.getcwd()
    dropped = _drop_sandbox_modules()

    buf = io.StringIO()
    code = 1
    try:
        os.chdir(tmp)
        sys.path.insert(0, str(tmp))
        with redirect_stdout(buf), redirect_stderr(buf):
            code = pytest.main(
                ["-q", "--no-header", "-p", "no:cacheprovider", str(tmp)]
            )
    except Exception as e:  # noqa: BLE001 — surface to the agent loop
        buf.write(f"\nIn-process pytest crashed: {type(e).__name__}: {e}\n")
        code = 1
    finally:
        os.chdir(prev_cwd)
        sys.path[:] = prev_path
        _drop_sandbox_modules()
        for name, mod in dropped:
            # Do not restore sandbox modules — they pointed at deleted temp paths.
            pass

    output = buf.getvalue().strip()
    n_passed, n_failed, n_errors = _parse_counts(output)
    if code != 0 and n_passed == n_failed == n_errors == 0:
        n_errors = 1
    passed = code == 0 and n_failed == 0 and n_errors == 0
    return RunResult(passed, n_passed, n_failed, n_errors, output)


def run_pytest(improved_code: str, tests_code: str, timeout: int = 60) -> RunResult:
    # Prefer /tmp on serverless so TemporaryDirectory is always writable.
    root = tempfile.gettempdir()
    with tempfile.TemporaryDirectory(prefix="selfcorrect_", dir=root) as d:
        tmp = Path(d)
        (tmp / f"{MODULE_NAME}.py").write_text(improved_code, encoding="utf-8")
        (tmp / f"test_{MODULE_NAME}.py").write_text(tests_code, encoding="utf-8")

        if _prefer_inprocess():
            return _run_inprocess(tmp)

        result = _run_subprocess(tmp, timeout)
        # If the subprocess couldn't run pytest at all, retry in-process.
        if (not result.passed
                and result.n_passed == result.n_failed == 0
                and ("Subprocess spawn failed" in result.output
                     or "No module named pytest" in result.output
                     or "ModuleNotFoundError" in result.output
                     or not result.output)):
            return _run_inprocess(tmp)
        return result
