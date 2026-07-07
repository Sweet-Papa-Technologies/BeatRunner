"""adapters/base.py — the TargetAdapter Protocol (STEPFORGE spec §2, REQ-ARCH-01).

The BEATFORGE core owns audio analysis, the designer/critic harness, the
re-prompt loop and the gate framework. A *target adapter* owns everything
game-specific: the note grammar, the design brief, turning musical intent into
concrete placements, legality/ergonomic repair, serialization, and QA. The core
never imports anything game-specific — it talks to this Protocol only, so
swapping targets (StepMania, Beat Saber, …) requires no core change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class AdapterResult:
    """What an adapter returns for one (track, difficulty)."""
    difficulty: str
    notes: list          # realized, concrete placements (adapter-defined objects)
    meter: int
    qa: dict = field(default_factory=dict)
    repairs: list = field(default_factory=list)
    design: dict = field(default_factory=dict)
    critic: dict | None = None


@runtime_checkable
class TargetAdapter(Protocol):
    """A game output target. Implementations live entirely under their own
    package (e.g. adapters/stepmania/) and touch nothing outside it."""

    name: str

    def grammar(self) -> dict:
        """The target's note vocabulary + difficulty slots (static description)."""
        ...

    def design_brief(self, analysis: dict, difficulty: str) -> str:
        """Assemble the designer prompt for a (track, difficulty)."""
        ...

    def realize(self, design: dict, analysis: dict, difficulty: str) -> list:
        """Turn designer INTENT (+ analysis timing truth) into concrete, legal
        placements. Deterministic; the adapter's core build."""
        ...

    def validate_repair(self, placements: list, analysis: dict, difficulty: str):
        """Ergonomic/legality gates + repair. Returns (placements, meter, report)."""
        ...

    def serialize(self, per_difficulty: dict, analysis: dict, track_id: str,
                  out_dir) -> dict:
        """Write the song folder (serialized simfile + audio + artifacts)."""
        ...

    def qa_metrics(self, placements: list, analysis: dict, difficulty: str) -> dict:
        """Objective per-chart metrics (onset alignment, flow cost, density…)."""
        ...


class NullAdapter:
    """Reference no-op adapter proving the Protocol is game-agnostic
    (REQ-ARCH-01 Accept). Produces an empty chart for any input."""

    name = "null"

    def grammar(self) -> dict:
        return {"panels": [], "note_types": [], "difficulties": []}

    def design_brief(self, analysis: dict, difficulty: str) -> str:
        return ""

    def realize(self, design: dict, analysis: dict, difficulty: str) -> list:
        return []

    def validate_repair(self, placements, analysis, difficulty):
        return [], 0, {}

    def serialize(self, per_difficulty, analysis, track_id, out_dir):
        return {}

    def qa_metrics(self, placements, analysis, difficulty):
        return {}
