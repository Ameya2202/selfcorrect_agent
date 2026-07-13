"""End-to-end self-test (offline, deterministic).

Run from the parent directory:  python -m selfcorrect_agent.selftest
Verifies: the loop runs, self-corrects a faulty test, reaches `ready`, the
website endpoints work, and apply writes the file + a backup.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

os.environ["SELFCORRECT_MOCK"] = "1"  # force the offline provider

from .config import Config
from .agent import SelfCorrectingAgent
from .server import create_app


def main():
    cfg = Config()
    assert cfg.use_mock or not cfg.has_api_key

    # 1. Headless loop -------------------------------------------------------
    here = Path(__file__).parent
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "example_target.py"
        shutil.copy2(here / "example_target.py", target)

        s = SelfCorrectingAgent(cfg).run(str(target))
        names = [st.name for st in s.steps]
        print("cycle:", " -> ".join(names))
        assert s.status == "ready", f"expected ready, got {s.status}"
        assert s.changed, "expected a proposed change"
        # the planted faulty test must have triggered a Correct step
        assert "Correct" in names, "expected a self-correction iteration"
        assert "Verify" in names, "expected a verify step"
        assert "x  y" not in s.tests_code or 'normalize_spaces("x  y") == "x y"' in s.tests_code
        print(f"[ok] loop reached ready in {s.attempts_used} attempts ({s.final_summary})")

    # 2. Website endpoints ---------------------------------------------------
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "example_target.py"
        shutil.copy2(here / "example_target.py", target)
        original = target.read_text()

        app = create_app(str(target), cfg)
        client = TestClient(app)

        assert client.get("/").status_code == 200
        assert "Self-Correcting Agent" in client.get("/").text
        assert client.get("/api/target").json()["mock"] is True

        run = client.post("/api/run", json={}).json()
        assert run["status"] == "ready" and run["changed"]
        sid = run["id"]
        print(f"[ok] /api/run -> ready, {len(run['steps'])} steps, diff has "
              f"{run['diff'].count(chr(10))} lines")

        applied = client.post("/api/apply",
                              json={"session_id": sid, "write_tests": True}).json()
        assert applied["applied"] is True
        assert Path(applied["backup_path"]).is_file(), "backup not created"
        assert Path(applied["test_path"]).is_file(), "test file not written"
        assert target.read_text() != original, "target file was not updated"
        assert "split()" in target.read_text(), "improved code not written"
        # backup must preserve the original
        assert Path(applied["backup_path"]).read_text() == original
        print(f"[ok] /api/apply wrote file + backup ({Path(applied['backup_path']).name})")

    print("\nALL SELF-TESTS PASSED")


if __name__ == "__main__":
    main()
