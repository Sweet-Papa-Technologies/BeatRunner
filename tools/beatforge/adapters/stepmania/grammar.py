"""grammar.py — dance-single note vocabulary, difficulty budgets, closed intent
vocabularies (STEPFORGE spec §4-6)."""
from __future__ import annotations

from dataclasses import dataclass

# dance-single panels, left->right in a .sm/.ssc row.
PANELS = ("L", "D", "U", "R")
PANEL_INDEX = {p: i for i, p in enumerate(PANELS)}
# Panel (x, y) unit positions for foot geometry: L=left, R=right, D=down, U=up.
PANEL_POS = {0: (-1.0, 0.0), 1: (0.0, -1.0), 2: (0.0, 1.0), 3: (1.0, 0.0)}

# Row tokens.
EMPTY, TAP, HOLD_HEAD, TAIL, ROLL_HEAD, MINE = "0", "1", "2", "3", "4", "M"
LEGAL_ROWS = (4, 8, 12, 16, 24, 32, 48, 64, 192)

# Closed intent vocabularies (REQ-SM-06) — anything else is a validation error.
TEXTURES = ("steps", "stream", "jumpstream", "drill", "runningman",
            "jacks_sparse", "stops_breather")
MOVEMENTS = ("static", "drift_L_to_R", "drift_R_to_L", "zigzag", "box")
CROSSOVERS = ("none", "light", "moderate")
KINDS = ("tap", "hold", "roll", "mine")


@dataclass(frozen=True)
class DiffBudget:
    name: str
    sm_difficulty: str          # StepMania DIFFICULTY name
    finest_subdiv: float        # beats
    max_nps_4s: float
    crossover: str              # none|light|moderate  (tolerance)
    footswitch: bool            # allowed?
    jack_limit: int
    jumps: str                  # "downbeats" | "accents" | "free"
    hold_share: tuple           # (lo, hi)
    hold_len_beats: tuple
    meter_range: tuple          # (lo, hi) clamp for METER


# Spec §5 budget table (Easy/Medium/Hard are v1; Beginner/Challenge frame them).
BUDGETS = {
    "beginner": DiffBudget("beginner", "Beginner", 1.0, 2.0, "none", False, 0,
                           "downbeats", (0.10, 0.20), (2.0, 8.0), (1, 2)),
    "easy": DiffBudget("easy", "Easy", 0.5, 3.0, "none", False, 0,
                       "downbeats", (0.10, 0.20), (2.0, 8.0), (2, 4)),
    "medium": DiffBudget("medium", "Medium", 0.25, 5.0, "light", False, 2,
                         "accents", (0.05, 0.15), (1.0, 8.0), (5, 6)),
    "hard": DiffBudget("hard", "Hard", 0.25, 8.0, "moderate", True, 4,
                       "free", (0.05, 0.12), (1.0, 8.0), (7, 9)),
    "challenge": DiffBudget("challenge", "Challenge", 0.25, 10.0, "moderate", True, 5,
                            "free", (0.05, 0.12), (1.0, 8.0), (10, 12)),
}
DIFFICULTIES = ("easy", "medium", "hard")   # spec default set (§13)
ALL_DIFFICULTIES = ("beginner", "easy", "medium", "hard", "challenge")


def grammar_description() -> dict:
    return {
        "panels": list(PANELS),
        "note_types": {"tap": TAP, "hold_head": HOLD_HEAD, "tail": TAIL,
                       "roll_head": ROLL_HEAD, "mine": MINE},
        "legal_row_subdivisions": list(LEGAL_ROWS),
        "textures": list(TEXTURES), "movements": list(MOVEMENTS),
        "crossovers": list(CROSSOVERS), "kinds": list(KINDS),
        "difficulties": list(ALL_DIFFICULTIES),
    }
