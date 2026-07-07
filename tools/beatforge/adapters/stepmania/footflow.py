"""footflow.py — the foot-state machine + comfort cost model (STEPFORGE §5,
Appendix C). This is what makes a 4-panel chart feel good: the realizer solves a
lowest-cost panel assignment over these penalties.

State = (l_panel, r_panel, last_foot):
  l_panel/r_panel ∈ {0,1,2,3}  which panel each foot currently rests on (L,D,U,R)
  last_foot       ∈ {-1,0,1}   which foot moved last (-1 = none yet; 0=L, 1=R)
"""
from __future__ import annotations

from .grammar import PANEL_POS

# Penalty constants (tunable). double-step ≫ jack(low) > crossover > footswitch.
DOUBLE_STEP = 8.0
JACK = 6.0
FOOTSWITCH = 2.0
FOOTSWITCH_ILLEGAL = 40.0
CROSSOVER = 5.0
FORBIDDEN = 1e6
ALT_BONUS = -1.0            # reward clean alternation
DRIFT_BONUS = -0.8         # reward honoring the phrase movement direction

LEFT, RIGHT, NONE = 0, 1, -1
REST_STATE = (0, 3, NONE)  # left foot on L, right foot on R, nobody moved yet

_CROSS_SCALE = {"none": 6.0, "light": 1.0, "moderate": 0.4}


def _x(panel: int) -> float:
    return PANEL_POS[panel][0]


def step(state, foot: int, new_panel: int, budget, movement: str, progress: float,
         beat: float = 0.0):
    """Cost of moving `foot` onto `new_panel` from `state`, and the resulting
    state. Returns (cost, new_state)."""
    l, r, last = state
    if foot == LEFT:
        moving_from, new_l, new_r = l, new_panel, r
        other_panel = r
    else:
        moving_from, new_l, new_r = r, l, new_panel
        other_panel = l

    cost = 0.0
    # double-step: same foot twice when we could have alternated
    if last == foot:
        cost += DOUBLE_STEP
        # a jack is a double-step that also stays on the same panel
        if new_panel == moving_from:
            cost += JACK
    # footswitch: stepping on the panel the OTHER foot was resting on, alternating
    if last != foot and last != NONE and new_panel == other_panel:
        cost += FOOTSWITCH if budget.footswitch else FOOTSWITCH_ILLEGAL
    # crossover: left foot ends up physically right of the right foot (or vice versa)
    if _x(new_l) > _x(new_r) + 1e-9:
        cost += CROSSOVER * _CROSS_SCALE.get(budget.crossover, 1.0)
    # both feet on the same panel simultaneously is impossible only for jumps;
    # for sequential steps it just means a footswitch handled above.
    # comfort: clean alternation onto a fresh panel
    if last != foot and new_panel != moving_from:
        cost += ALT_BONUS
    # D and U are symmetric in the horizontal cost model, so ties always fell to
    # D and starved U (panel balance). Break the tie by beat parity so both
    # vertical panels get exercised roughly evenly.
    if new_panel in (1, 2):
        prefer_u = int(round(beat * 2)) % 2 == 1
        cost += -0.15 if (new_panel == 2) == prefer_u else 0.15
    # honor the phrase's movement direction
    cost += _movement_cost(new_panel, movement, progress)
    return cost, (new_l, new_r, foot)


def jump_cost(state, pl: int, pr: int, budget):
    """Cost of a two-panel jump landing left foot on `pl`, right foot on `pr`."""
    if pl == pr:
        return FORBIDDEN, state
    cost = 0.0
    if _x(pl) > _x(pr) + 1e-9:          # crossed jump — physically a twist
        cost += FORBIDDEN if budget.crossover == "none" else CROSSOVER * 3
    # prefer feet on their natural sides
    cost += 0.5 * (abs(_x(pl) - (-1)) + abs(_x(pr) - 1))
    return cost, (pl, pr, RIGHT)


def _movement_cost(new_panel: int, movement: str, progress: float) -> float:
    """Reward a panel whose horizontal position matches where the phrase's
    movement wants the feet to be at `progress` (0..1 through the phrase)."""
    x = _x(new_panel)                    # -1 (L) .. +1 (R)
    if movement == "drift_L_to_R":
        target = -1 + 2 * progress
    elif movement == "drift_R_to_L":
        target = 1 - 2 * progress
    elif movement == "zigzag":
        target = -1 if int(progress * 8) % 2 == 0 else 1
    else:                                # static / box / unknown -> no drift pref
        return 0.0
    return DRIFT_BONUS * (1.0 - abs(x - target) / 2.0)
