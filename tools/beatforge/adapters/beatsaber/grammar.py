"""grammar.py — Beat Saber Standard-mode note vocabulary, 4×3 grid geometry,
cut-direction swing vectors, colour→hand map, object kinds, and the per-difficulty
budget table with NJS (SABERFORGE spec §4, REQ-BS-01).

The BEATFORGE core owns timing truth; this module owns the static grammar the
parity engine (§5) and serializer (§7) build on. Nothing here reaches outside
adapters/beatsaber/ (REQ-ARCH-01).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Grid — 4 columns x∈0..3 (left→right), 3 rows y∈0..2 (bottom→top) = 12 cells.
# --------------------------------------------------------------------------- #
GRID_COLS = 4
GRID_ROWS = 3
ROWS = (0, 1, 2)            # bottom, middle, top
COLS = (0, 1, 2, 3)

# Colours: c=0 red/left saber, c=1 blue/right saber (spec §4).
RED, BLUE = 0, 1
COLOR_HAND = {RED: "left", BLUE: "right"}
HAND_COLOR = {"left": RED, "right": BLUE}

# --------------------------------------------------------------------------- #
# Cut directions d and their swing UNIT VECTORS (the direction the saber travels
# through the block). 0=up,1=down,2=left,3=right,4=up-left,5=up-right,
# 6=down-left,7=down-right,8=any(dot). (spec §4 / Appendix B).
# --------------------------------------------------------------------------- #
UP, DOWN, LEFT, RIGHT = 0, 1, 2, 3
UP_LEFT, UP_RIGHT, DOWN_LEFT, DOWN_RIGHT = 4, 5, 6, 7
DOT = 8
CUT_DIRECTIONS = (0, 1, 2, 3, 4, 5, 6, 7, 8)

_INV_SQRT2 = 1.0 / math.sqrt(2.0)
# Unit vector per direction (x right-positive, y up-positive). Dot has no vector.
SWING_VECTORS: dict[int, tuple[float, float]] = {
    UP: (0.0, 1.0),
    DOWN: (0.0, -1.0),
    LEFT: (-1.0, 0.0),
    RIGHT: (1.0, 0.0),
    UP_LEFT: (-_INV_SQRT2, _INV_SQRT2),
    UP_RIGHT: (_INV_SQRT2, _INV_SQRT2),
    DOWN_LEFT: (-_INV_SQRT2, -_INV_SQRT2),
    DOWN_RIGHT: (_INV_SQRT2, -_INV_SQRT2),
    DOT: (0.0, 0.0),
}

# Swing PARITY family for each direction. A forehand swing ends low (the saber
# travels downward); a backhand swing ends high (travels upward). Horizontal cuts
# and dots are parity-neutral (serve either). Smooth play alternates the family
# per hand; two same-family swings in a row is a "reset" (spec §5).
FOREHAND, BACKHAND, NEUTRAL = "forehand", "backhand", "neutral"
DIRECTION_PARITY: dict[int, str] = {
    UP: BACKHAND, UP_LEFT: BACKHAND, UP_RIGHT: BACKHAND,
    DOWN: FOREHAND, DOWN_LEFT: FOREHAND, DOWN_RIGHT: FOREHAND,
    LEFT: NEUTRAL, RIGHT: NEUTRAL, DOT: NEUTRAL,
}
# Directions available to realize a swing of a given parity, best (most natural)
# first. A backhand naturally ends high → up-family; forehand → down-family.
PARITY_DIRECTIONS: dict[str, tuple[int, ...]] = {
    BACKHAND: (UP, UP_LEFT, UP_RIGHT, LEFT, RIGHT),
    FOREHAND: (DOWN, DOWN_LEFT, DOWN_RIGHT, LEFT, RIGHT),
}
# The rows a parity's swing sits on comfortably: the block must be placed so the
# swing's FOLLOW-THROUGH continues into open space, not against it. A down-cut
# (forehand) is comfortable in the middle/TOP rows (follow-through sweeps down); an
# up-cut (backhand) in the middle/BOTTOM rows (follow-through sweeps up). Placing a
# down-cut on the bottom row (or an up-cut on the top row) forces the saber to
# traverse the whole grid against the swing — the classic unplayable jackhammer.
# Middle row (1) is listed first: streams flow best kept near centre.
PARITY_ROWS: dict[str, tuple[int, ...]] = {BACKHAND: (1, 0), FOREHAND: (1, 2)}


def opposite_parity(parity: str) -> str:
    return BACKHAND if parity == FOREHAND else FOREHAND


def swing_angle_deg(direction: int) -> float:
    """Absolute angle (degrees, 0=+x/right, 90=+y/up) of a cut direction's swing
    vector. Dots return 0.0 (no defined angle)."""
    vx, vy = SWING_VECTORS[direction]
    if vx == 0.0 and vy == 0.0:
        return 0.0
    return math.degrees(math.atan2(vy, vx))


def angle_between(d1: int, d2: int) -> float:
    """Smallest angle (0..180°) between two cut directions' swing vectors. Dots
    (no direction) return 0.0 — they impose no angle constraint."""
    if d1 == DOT or d2 == DOT:
        return 0.0
    a = (swing_angle_deg(d1) - swing_angle_deg(d2)) % 360.0
    return min(a, 360.0 - a)


# The 180° flip of each cut direction (anti-parallel swing vector).
OPPOSITE_DIRECTION = {UP: DOWN, DOWN: UP, LEFT: RIGHT, RIGHT: LEFT,
                      UP_LEFT: DOWN_RIGHT, DOWN_RIGHT: UP_LEFT,
                      UP_RIGHT: DOWN_LEFT, DOWN_LEFT: UP_RIGHT, DOT: DOT}


def swing_turn(prev_dir: int, new_dir: int) -> float:
    """Extra wrist rotation (0..180°) a swing needs BEYOND the natural reversal of
    the previous swing. Alternating parity means the next cut is normally the
    anti-parallel of the last one (down→up, down-right→up-left) — the easiest,
    most natural motion, which must cost ZERO. So the turn is measured against the
    OPPOSITE of the previous direction, not the previous direction itself. This is
    the angle that actually taxes the wrist and is what the time budget bounds."""
    if prev_dir == DOT or new_dir == DOT:
        return 0.0
    return angle_between(OPPOSITE_DIRECTION[prev_dir], new_dir)


# --------------------------------------------------------------------------- #
# Object kinds the designer may request (closed set, spec §6). Grid geometry is
# NEVER designer-supplied — the realizer assigns it.
# --------------------------------------------------------------------------- #
OBJECT_KINDS = ("note", "arc", "chain", "bomb_reset")
HANDS = ("left", "right", "either")

# --------------------------------------------------------------------------- #
# Difficulty budgets (spec §5 table). NJS/offset are per-difficulty and MUST be
# constant within a difficulty (ScoreSaber hard rule, REQ-BS-08). finest_precision
# is the smallest note subdivision in beats; max_nps_4s the sustained density cap.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DiffBudget:
    name: str
    difficulty_name: str        # Beat Saber DifficultyName (Easy/Normal/…/ExpertPlus)
    difficulty_rank: int        # 1/3/5/7/9
    finest_precision: float     # smallest note subdivision, beats
    max_nps_4s: float           # max sustained notes-per-second over any 4s window
    rows: tuple                 # grid rows this tier may use
    resets: str                 # "none" | "telegraphed"
    doubles: str                # "rare" | "accents" | "free"
    arc_chain_share: tuple      # (lo, hi) share of notes that may be arcs/chains
    njs: float                  # note jump speed
    offset: float               # spawn offset
    doubles_max_frac: float     # hard ceiling on two-hand simultaneous share


BUDGETS: dict[str, DiffBudget] = {
    "easy": DiffBudget("easy", "Easy", 1, 1 / 4, 2.0, (0, 1), "none",
                       "rare", (0.00, 0.05), 10.0, 0.0, 0.05),
    "normal": DiffBudget("normal", "Normal", 3, 1 / 8, 3.5, (0, 1), "none",
                         "accents", (0.05, 0.10), 10.0, 0.0, 0.10),
    "hard": DiffBudget("hard", "Hard", 5, 1 / 8, 5.0, (0, 1, 2), "telegraphed",
                       "free", (0.05, 0.15), 12.0, 0.0, 0.25),
    "expert": DiffBudget("expert", "Expert", 7, 1 / 16, 7.0, (0, 1, 2), "telegraphed",
                         "free", (0.05, 0.15), 16.0, 0.0, 0.40),
    "expertplus": DiffBudget("expertplus", "ExpertPlus", 9, 1 / 16, 10.0, (0, 1, 2),
                             "telegraphed", "free", (0.05, 0.12), 18.0, 0.0, 0.50),
}
# Spec default set (§8/§13) and the full ladder for monotonicity checks.
DIFFICULTIES = ("easy", "normal", "hard", "expert", "expertplus")
ALL_DIFFICULTIES = DIFFICULTIES

# Precision-vs-BPM ceiling (spec §5.2 / Appendix C): ≤1/16 up to 180 BPM,
# ≤1/8 up to 360 BPM. Below the BPM key, that precision is the finest allowed.
PRECISION_BPM_LIMIT = ((180.0, 1 / 16), (360.0, 1 / 8))
BOMB_MIN_SPACING_MS = 20.0      # bombs ≥20 ms apart (spec §5.2)
MAX_ACTIVE_ARCS_PER_HAND = 5    # arcs ≤5 active per hand (spec §4/§5.2)


def grammar_description() -> dict:
    """Static description of the target grammar (TargetAdapter.grammar)."""
    return {
        "grid": {"cols": GRID_COLS, "rows": GRID_ROWS},
        "colors": {"red_left": RED, "blue_right": BLUE},
        "cut_directions": {str(d): SWING_VECTORS[d] for d in CUT_DIRECTIONS},
        "object_kinds": list(OBJECT_KINDS),
        "hands": list(HANDS),
        "difficulties": list(ALL_DIFFICULTIES),
    }
