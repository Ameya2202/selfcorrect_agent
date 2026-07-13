"""selfcorrect_agent — a drop-in self-correcting code agent.

Quick start (in your own code):

    from selfcorrect_agent import improve_file
    improve_file("path/to/your_module.py")     # opens the review website

Headless (no UI), e.g. in CI or scripts:

    from selfcorrect_agent import run_headless
    session = run_headless("path/to/your_module.py")
    if session.status == "ready" and session.changed:
        session.apply()                        # writes the file + a .bak backup

Set ANTHROPIC_API_KEY to use the real model. Without a key (or with
SELFCORRECT_MOCK=1) it runs the deterministic offline provider.
"""
from __future__ import annotations

import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from .agent import SelfCorrectingAgent, Session
from .config import Config

__all__ = ["improve_file", "run_headless", "SelfCorrectingAgent", "Session", "Config"]


def run_headless(file_path: str, config: Optional[Config] = None) -> Session:
    """Run the self-correction cycle and return the Session without any UI."""
    return SelfCorrectingAgent(config or Config()).run(file_path)


def improve_file(file_path: str, config: Optional[Config] = None,
                 open_browser: bool = True) -> None:
    """Launch the review website for `file_path` and block until you stop it.

    The page auto-runs the cycle, shows the proposed change, and asks you to
    approve before anything is written to the file.
    """
    import uvicorn  # local import keeps headless use dependency-light

    config = config or Config()
    path = str(Path(file_path).resolve())
    if not Path(path).is_file():
        raise FileNotFoundError(path)

    from .server import create_app
    app = create_app(path, config)
    url = f"http://{config.host}:{config.port}/"

    if open_browser:
        def _open():
            time.sleep(1.0)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    print(f"\n  Self-Correcting Agent reviewing: {path}")
    print(f"  Open {url} in your browser (Ctrl+C to stop).\n")
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning")
