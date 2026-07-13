"""Configuration for the self-correcting agent.

Everything is overridable via environment variables so you can drop the
package into any project without editing code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    # Which Claude model the Author/Grader roles use.
    model: str = os.environ.get("SELFCORRECT_MODEL", "claude-sonnet-4-6")
    # Max self-correction attempts before the agent escalates to a human.
    max_attempts: int = int(os.environ.get("SELFCORRECT_MAX_ATTEMPTS", "4"))
    # Hard timeout (seconds) for each sandboxed pytest run.
    test_timeout: int = int(os.environ.get("SELFCORRECT_TEST_TIMEOUT", "60"))
    # Max tokens per LLM call.
    max_tokens: int = int(os.environ.get("SELFCORRECT_MAX_TOKENS", "4096"))
    # Web UI host/port.
    host: str = os.environ.get("SELFCORRECT_HOST", "127.0.0.1")
    port: int = int(os.environ.get("SELFCORRECT_PORT", "8765"))
    # Use the deterministic offline provider instead of the real API.
    use_mock: bool = os.environ.get("SELFCORRECT_MOCK", "0") == "1"

    @property
    def has_api_key(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
