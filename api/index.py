"""Vercel serverless entrypoint.

Vercel's Python runtime deploys every file in ``/api`` as a function and looks
for a module-level ``app`` (an ASGI/WSGI application). This file exposes the
FastAPI app in a way that works in the ephemeral serverless environment:

- The package files live at the deploy root (one level up from ``/api``). We
  register them under the import name ``selfcorrect_agent`` so the package's
  relative imports keep working without restructuring the repo.
- The app runs in offline **mock** mode by default (no API key, deterministic,
  safe to expose publicly). Set ANTHROPIC_API_KEY + SELFCORRECT_MOCK=0 in the
  Vercel project env if you really want the live model.
- The review target is copied into ``/tmp`` (the only writable path on Vercel)
  so the loop — and even "Apply to file" — works within a warm instance.

Caveats inherent to serverless: module-level state (cross-cycle history,
promoted heuristics) only lives as long as an instance stays warm, and any
applied change is written to the ephemeral ``/tmp`` copy, not a durable file.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import types

# --- make the sibling modules importable as the ``selfcorrect_agent`` package -
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if "selfcorrect_agent" not in sys.modules:
    pkg = types.ModuleType("selfcorrect_agent")
    pkg.__path__ = [ROOT]  # type: ignore[attr-defined]
    sys.modules["selfcorrect_agent"] = pkg

# --- default to the safe offline provider for a public deployment ------------
os.environ.setdefault("SELFCORRECT_MOCK", "1")

from selfcorrect_agent.config import Config  # noqa: E402
from selfcorrect_agent.server import create_app  # noqa: E402

# --- stage a writable copy of the demo target in /tmp ------------------------
_src = os.path.join(ROOT, "example_target.py")
_target = os.path.join(tempfile.gettempdir(), "example_target.py")
try:
    if not os.path.exists(_target):
        shutil.copy2(_src, _target)
except Exception:
    _target = _src  # fall back to the read-only bundled file

app = create_app(_target, Config())
