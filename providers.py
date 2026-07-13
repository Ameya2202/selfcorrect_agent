"""LLM providers.

The agent talks to a provider through three methods that mirror the PRD's
agent roles:

    propose()  -> Author: read the file, propose an improved version + a pytest suite
    diagnose() -> Grader: classify why a test run failed
    revise()   -> Author: correct the test or the code given the diagnosis

`AnthropicProvider` calls the real Claude API. `MockProvider` is deterministic
and offline, used for self-tests and `--mock` demos.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from .config import Config

# The module under test is always written to the sandbox as `solution.py`,
# so generated tests must `from solution import ...`. This keeps the sandbox
# deterministic regardless of the original filename.
MODULE_NAME = "solution"


@dataclass
class Proposal:
    improved_code: str
    tests_code: str
    rationale: str


@dataclass
class Diagnosis:
    # one of: bad_test | bad_code | environmental
    classification: str
    explanation: str


@dataclass
class Revision:
    improved_code: str
    tests_code: str
    note: str


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response, tolerating code fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    # Find the outermost JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


# --------------------------------------------------------------------------- #
# Real provider
# --------------------------------------------------------------------------- #
class AnthropicProvider:
    """Uses the Anthropic Messages API. Requires ANTHROPIC_API_KEY in the env."""

    SYSTEM = (
        "You are a meticulous senior engineer acting as two roles inside a "
        "self-correcting loop: an Author that improves code and writes pytest "
        "tests, and a Grader that diagnoses test failures. You make minimal, "
        "behaviour-preserving improvements unless fixing a clear bug or missing "
        "edge case. You NEVER weaken or delete a test's assertion just to make "
        "it pass. You always respond with strict JSON and nothing else."
    )

    def __init__(self, config: Config):
        from anthropic import Anthropic  # imported lazily so mock-only use needs no key

        self.config = config
        self.client = Anthropic()

    def _call(self, user_prompt: str) -> str:
        resp = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=self.SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    def propose(self, filename: str, code: str) -> Proposal:
        prompt = f"""ROLE: Author.
The file `{filename}` is below. Produce an improved version of it and a pytest
suite that pins down its intended behaviour, including edge cases.

Rules:
- The improved module will be importable as `{MODULE_NAME}`. Your tests MUST do
  `from {MODULE_NAME} import ...`.
- Keep the public API the same unless a name is clearly wrong.
- Fix real bugs and unhandled edge cases; do not change behaviour gratuitously.
- Tests must be runnable as-is with pytest and must actually assert behaviour.

Respond with strict JSON:
{{"improved_code": "<full improved module source>",
  "tests_code": "<full pytest file source>",
  "rationale": "<2-4 sentences on what you changed and why>"}}

--- BEGIN {filename} ---
{code}
--- END {filename} ---"""
        d = _extract_json(self._call(prompt))
        return Proposal(d["improved_code"], d["tests_code"], d.get("rationale", ""))

    def diagnose(self, code: str, tests_code: str, failure_output: str) -> Diagnosis:
        prompt = f"""ROLE: Grader.
A pytest run failed. Decide the single best cause.

Classify as exactly one of:
- "bad_test": the test's expectation is wrong / the test itself is faulty.
- "bad_code": the module under test has a real defect the test correctly caught.
- "environmental": failure is due to environment/setup, not logic.

Respond with strict JSON:
{{"classification": "bad_test|bad_code|environmental",
  "explanation": "<1-3 sentences>"}}

--- MODULE ({MODULE_NAME}.py) ---
{code}
--- TESTS ---
{tests_code}
--- PYTEST OUTPUT ---
{failure_output}"""
        d = _extract_json(self._call(prompt))
        return Diagnosis(d["classification"], d.get("explanation", ""))

    def revise(
        self, code: str, tests_code: str, failure_output: str, classification: str
    ) -> Revision:
        prompt = f"""ROLE: Author.
The previous run failed and was diagnosed as: {classification}.
Apply the minimal correction:
- If bad_test: fix the faulty test(s) WITHOUT weakening the behaviour being checked.
- If bad_code: fix the module's defect.
Return BOTH files in full even if one is unchanged.

Respond with strict JSON:
{{"improved_code": "<full module source>",
  "tests_code": "<full pytest source>",
  "note": "<1 sentence on the correction>"}}

--- MODULE ({MODULE_NAME}.py) ---
{code}
--- TESTS ---
{tests_code}
--- PYTEST OUTPUT ---
{failure_output}"""
        d = _extract_json(self._call(prompt))
        return Revision(
            d.get("improved_code", code), d.get("tests_code", tests_code), d.get("note", "")
        )


# --------------------------------------------------------------------------- #
# Mock provider (deterministic, offline) — used for self-test and demos
# --------------------------------------------------------------------------- #
class MockProvider:
    """A deterministic stand-in that produces real, runnable Python so the
    whole loop (including a genuine correction iteration) can be exercised
    without network access or an API key.

    Scenario: improves a `normalize_spaces` function and writes a test suite
    that contains one deliberately-wrong expectation, so the first run fails,
    is diagnosed as `bad_test`, corrected, and then passes.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config

    def propose(self, filename: str, code: str) -> Proposal:
        improved = (
            'def normalize_spaces(text):\n'
            '    """Collapse all runs of whitespace to single spaces and trim ends."""\n'
            '    if text is None:\n'
            '        raise ValueError("text must not be None")\n'
            '    return " ".join(text.split())\n'
        )
        tests = (
            "from solution import normalize_spaces\n"
            "import pytest\n\n\n"
            "def test_basic():\n"
            '    assert normalize_spaces("hello   world") == "hello world"\n\n\n'
            "def test_trim_and_collapse():\n"
            '    assert normalize_spaces("  a   b  ") == "a b"\n\n\n'
            "def test_tabs_and_newlines():\n"
            '    assert normalize_spaces("a\\t\\tb\\nc") == "a b c"\n\n\n'
            "def test_planted_wrong_expectation():\n"
            "    # Deliberately wrong expected value; the loop should fix this test.\n"
            '    assert normalize_spaces("x  y") == "x  y"\n\n\n'
            "def test_none_raises():\n"
            "    with pytest.raises(ValueError):\n"
            "        normalize_spaces(None)\n"
        )
        rationale = (
            "Collapsed internal whitespace (not just trimmed ends) and added a "
            "guard against None input; wrote edge-case tests for tabs, newlines, "
            "and the None path."
        )
        return Proposal(improved, tests, rationale)

    def diagnose(self, code: str, tests_code: str, failure_output: str) -> Diagnosis:
        if "test_planted_wrong_expectation" in failure_output:
            return Diagnosis(
                "bad_test",
                'The test asserts "x  y" but the (correct) behaviour collapses it to "x y".',
            )
        return Diagnosis("bad_code", "A genuine defect was caught by the tests.")

    def revise(self, code, tests_code, failure_output, classification) -> Revision:
        if classification == "bad_test":
            fixed = tests_code.replace(
                'assert normalize_spaces("x  y") == "x  y"',
                'assert normalize_spaces("x  y") == "x y"',
            )
            return Revision(code, fixed, "Corrected the faulty expectation in the test.")
        return Revision(code, tests_code, "No change.")


def get_provider(config: Config):
    if config.use_mock or not config.has_api_key:
        return MockProvider(config)
    return AnthropicProvider(config)
