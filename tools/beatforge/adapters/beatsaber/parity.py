"""parity.py — the swing-parity state machine + comfort cost model (SABERFORGE
spec §5, Appendix C). This is what makes a Beat Saber chart feel good: the
realizer solves a lowest-cost cut assignment over these penalties, per hand.

A single hand's state is (parity, cut_dir, x, y): which way the last swing went
(forehand/backhand), its direction, and where the block sat. Smooth play
ALTERNATES parity — a same-parity swing in a row is a *reset*, allowed only when
telegraphed with enough lead time (§5.2). This is the swing-flow analog of the
StepMania foot-flow model in adapters/stepmania/footflow.py.
"""
from __future__ import annotations

from .grammar import (DIRECTION_PARITY, DOT, NEUTRAL, PARITY_DIRECTIONS,
                      PARITY_ROWS, angle_between)

# Penalty constants (tunable). reset ≫ over-angle > off-natural-row > off-column.
RESET = 30.0                 # two same-parity swings in a row (undesired)
RESET_TELEGRAPHED = 4.0      # a reset that a bomb reset made legal (still costs a little)
OVER_ANGLE = 12.0            # angle change too large for the time available
ALT_BONUS = -2.0             # reward clean forehand/backhand alternation
NATURAL_ROW_BONUS = -0.6     # reward a note on the parity's natural row
OFF_COLUMN = 0.4             # gentle cost for leaving the hand's home half
DOT_COST = 0.5               # dots are parity-neutral but read as low-craft; use sparingly
FORBIDDEN = 1e6

# A hand's home half of the grid keeps red left / blue right so the two sabers
# don't fight for swing-path space (the joint constraint's default, §5.1).
HOME_COLUMNS = {"left": (0, 1, 2), "right": (1, 2, 3)}
NEUTRAL_STATE = (None, None, None, None)   # (parity, dir, x, y) before the first note


def _angle_budget_deg(dt_beats: float, bpm: float) -> float:
    """How large an angle change the hand can comfortably make in `dt_beats` at
    `bpm`. Larger gaps allow larger turns; at high precision only ~180°/135° fit
    (spec §5.2). Linear in the inter-note time with a floor and a 180° ceiling."""
    dt_s = max(1e-3, dt_beats) * 60.0 / max(1e-6, bpm)
    # ~180° per 0.30s of swing time, floored so adjacent 1/16ths still allow a flip.
    return min(180.0, max(45.0, dt_s / 0.30 * 180.0))


def transition_cost(state, parity: str, direction: int, x: int, y: int,
                    hand: str, dt_beats: float, bpm: float, telegraphed: bool = False):
    """Cost of the next swing having (parity, direction, x, y) given the previous
    `state`, and the resulting state. Returns (cost, new_state)."""
    prev_parity, prev_dir, _, _ = state
    cost = 0.0

    # --- parity discipline: alternate by default ---
    if prev_parity is not None and parity != NEUTRAL:
        if parity == prev_parity:                      # a reset
            cost += RESET_TELEGRAPHED if telegraphed else RESET
        else:
            cost += ALT_BONUS                          # clean alternation

    # --- angle discipline: scale allowed Δangle by the inter-note gap × BPM ---
    if prev_dir is not None and prev_dir != DOT and direction != DOT:
        dang = angle_between(prev_dir, direction)
        budget = _angle_budget_deg(dt_beats, bpm)
        if dang > budget + 1e-6:
            cost += OVER_ANGLE * (dang - budget) / 180.0

    # --- natural-row bias: forehand finishes low, backhand high ---
    if parity in PARITY_ROWS and y in PARITY_ROWS[parity]:
        cost += NATURAL_ROW_BONUS

    # --- home-column bias: keep each hand on its side of the grid ---
    if x not in HOME_COLUMNS.get(hand, (0, 1, 2, 3)):
        cost += OFF_COLUMN

    if direction == DOT:
        cost += DOT_COST

    return cost, (parity, direction, x, y)


def cut_options(parity: str):
    """The (direction) choices that realize a swing of `parity`, best first."""
    return PARITY_DIRECTIONS[parity]


def is_reset(prev_parity: str | None, parity: str) -> bool:
    """True iff placing a `parity` swing after `prev_parity` is a reset."""
    return (prev_parity is not None and parity != NEUTRAL
            and parity == prev_parity)


def direction_parity(direction: int) -> str:
    return DIRECTION_PARITY[direction]
