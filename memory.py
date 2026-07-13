"""Cross-cycle memory + the offline "dreaming" consolidation step.

The in-session loop (agent.py) is stateless: it improves one file and stops.
This module adds the *between-session* half of the PRD that the console UI
surfaces — it remembers what happened across cycles and, on a "dreaming"
pass, consolidates repeated observations into durable **heuristics**.

Everything here is in-memory and deterministic; nothing is written to disk.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# Human-readable heuristics minted from a repeated failure classification.
_HEURISTIC_TEXT = {
    "bad_test": (
        "Author over-trusts freshly generated tests. Before the first run, "
        "re-check each assertion against the intended behaviour (e.g. whitespace "
        "is collapsed, not just trimmed) so a faulty expectation doesn't cost a cycle."
    ),
    "bad_code": (
        "Recurring real defects: proactively add guards for None/empty input and "
        "an edge-case test alongside every behaviour change."
    ),
    "environmental": (
        "Some failures are environmental, not logical. Retry once and quarantine "
        "before spending an attempt on a code/test correction."
    ),
}


@dataclass
class Heuristic:
    id: str
    text: str
    source: str          # the classification it was distilled from
    observations: int    # how many cycles reinforced it
    promoted: bool = False
    promoted_at: Optional[float] = None


@dataclass
class CycleRecord:
    index: int
    session_id: str
    status: str          # ready | escalate | error
    ok: bool             # reached a green, trustworthy state
    changed: bool
    attempts: int
    attempts_to_green: Optional[int]
    false_incidents: int
    coverage: float      # 0..100
    summary: str
    ts: float = field(default_factory=time.time)


class AgentMemory:
    """Aggregates cycle outcomes and promotes heuristics during dreaming."""

    def __init__(self) -> None:
        self.cycles: List[CycleRecord] = []
        # classification -> reinforcement count observed across cycles
        self._observations: Dict[str, int] = {}
        self.heuristics: List[Heuristic] = []

    # -- recording -------------------------------------------------------- #
    def record_cycle(self, snapshot: dict) -> CycleRecord:
        rec = CycleRecord(
            index=len(self.cycles) + 1,
            session_id=snapshot["id"],
            status=snapshot["status"],
            ok=snapshot["status"] == "ready",
            changed=snapshot["changed"],
            attempts=snapshot["attempts_used"],
            attempts_to_green=snapshot.get("attempts_to_green"),
            false_incidents=snapshot.get("false_incidents", 0),
            coverage=snapshot.get("coverage", 0.0),
            summary=snapshot.get("final_summary", ""),
        )
        self.cycles.append(rec)
        for cls in snapshot.get("diagnoses", []):
            if cls in _HEURISTIC_TEXT:
                self._observations[cls] = self._observations.get(cls, 0) + 1
        return rec

    # -- dreaming --------------------------------------------------------- #
    def dream(self) -> dict:
        """Consolidate observations into promoted heuristics.

        Returns a summary of what this pass promoted. Observations already
        promoted are reinforced (their observation count grows) rather than
        duplicated.
        """
        by_source = {h.source: h for h in self.heuristics}
        newly_promoted: List[Heuristic] = []
        for cls, count in self._observations.items():
            existing = by_source.get(cls)
            if existing:
                existing.observations = count
                continue
            h = Heuristic(
                id=f"H{len(self.heuristics) + 1:02d}",
                text=_HEURISTIC_TEXT[cls],
                source=cls,
                observations=count,
                promoted=True,
                promoted_at=time.time(),
            )
            self.heuristics.append(h)
            newly_promoted.append(h)
            by_source[cls] = h
        return {
            "promoted_now": len(newly_promoted),
            "promoted_ids": [h.id for h in newly_promoted],
            "observations_reviewed": sum(self._observations.values()),
        }

    # -- reset ------------------------------------------------------------ #
    def reset(self) -> None:
        self.cycles.clear()
        self._observations.clear()
        self.heuristics.clear()

    # -- snapshot --------------------------------------------------------- #
    def snapshot(self) -> dict:
        total = len(self.cycles)
        wins = sum(1 for c in self.cycles if c.ok)
        # Cumulative success rate after each cycle, for the chart.
        curve, running = [], 0
        for i, c in enumerate(self.cycles, start=1):
            running += 1 if c.ok else 0
            curve.append(round(100.0 * running / i, 1))
        avg_cov = round(sum(c.coverage for c in self.cycles) / total, 1) if total else 0.0
        return {
            "cycle_count": total,
            "success_rate": round(100.0 * wins / total, 1) if total else 0.0,
            "success_curve": curve,
            "avg_coverage": avg_cov,
            "false_incidents_total": sum(c.false_incidents for c in self.cycles),
            "heuristics_promoted": sum(1 for h in self.heuristics if h.promoted),
            "pending_observations": sum(self._observations.values()),
            "cycles": [
                {
                    "index": c.index,
                    "status": c.status,
                    "ok": c.ok,
                    "changed": c.changed,
                    "attempts": c.attempts,
                    "attempts_to_green": c.attempts_to_green,
                    "false_incidents": c.false_incidents,
                    "coverage": c.coverage,
                    "summary": c.summary,
                }
                for c in self.cycles
            ],
            "heuristics": [
                {
                    "id": h.id,
                    "text": h.text,
                    "source": h.source,
                    "observations": h.observations,
                    "promoted": h.promoted,
                }
                for h in self.heuristics
            ],
        }
