"""realize.py — turn a quantized note stream + phrase intent into concrete,
comfortable panels via a Viterbi DP over the foot-state machine (STEPFORGE §5,
REQ-SM-03).

The designer supplies WHICH onsets are notes, each note's KIND, and per-phrase
INTENT (texture/movement/crossover/jump_density). It never places panels. This
solver picks the panels: the lowest-total-discomfort foot path that also honors
the phrase intent. That's why the model can't hand you an awful pattern — it
doesn't place panels at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import footflow as ff
from .grammar import PANELS
from .quantize import Placement


@dataclass
class ResolvedNote:
    beat: float
    kind: str = "tap"                 # tap|hold|roll|mine
    hold_beats: float | None = None
    is_jump: bool = False
    phrase: dict = field(default_factory=dict)   # movement/crossover/texture/jump_density


_JUMP_ALLOWED = {"none": set(), "downbeats": {0.0}, "accents": {0.0, 2.0},
                 "free": {0.0, 1.0, 2.0, 3.0}}


def decide_jumps(notes: list[ResolvedNote], budget, meter: int = 4) -> None:
    """Flag notes as jumps per the covering phrase's jump_density and the beat's
    metric position, capped so jumps stay accents not spam."""
    for n in notes:
        if n.kind in ("hold", "roll", "mine"):
            continue
        density = n.phrase.get("jump_density", budget.jumps)
        allowed = _JUMP_ALLOWED.get(density, set())
        pos = round(n.beat % meter, 3)
        n.is_jump = pos in allowed and budget.jumps != "downbeats" or (
            pos == 0.0 and budget.jumps != "none" and density != "none")


def realize(notes: list[ResolvedNote], budget, meter: int = 4) -> list[Placement]:
    """Viterbi lowest-cost panel assignment. Returns Placements with concrete
    panels."""
    if not notes:
        return []
    notes = sorted(notes, key=lambda n: n.beat)
    # dp: state -> (total_cost, path). path is a list of chosen panel tuples.
    dp: dict[tuple, tuple[float, list]] = {ff.REST_STATE: (0.0, [])}

    for n in notes:
        mv = n.phrase.get("movement", "static")
        prog = _progress(n, meter)
        ndp: dict[tuple, tuple[float, list]] = {}

        def relax(state, cost, choice):
            cur = ndp.get(state)
            if cur is None or cost < cur[0]:
                ndp[state] = (cost, choice)

        if n.is_jump:
            for st, (c0, path) in dp.items():
                for pl in range(4):
                    for pr in range(4):
                        dc, ns = ff.jump_cost(st, pl, pr, budget)
                        if dc >= ff.FORBIDDEN:
                            continue
                        relax(ns, c0 + dc, path + [((pl, pr), "J")])
        else:
            for st, (c0, path) in dp.items():
                for foot in (ff.LEFT, ff.RIGHT):
                    for panel in range(4):
                        dc, ns = ff.step(st, foot, panel, budget, mv, prog, n.beat)
                        if dc >= ff.FORBIDDEN:
                            continue
                        relax(ns, c0 + dc, path + [((panel,), foot)])
        # keep the best-N states to bound growth (all 32 fit, but be safe)
        dp = dict(sorted(ndp.items(), key=lambda kv: kv[1][0])[:64])

    best = min(dp.values(), key=lambda v: v[0])
    out = []
    for n, (panels, foot) in zip(notes, best[1]):
        out.append(Placement(beat=n.beat, panels=tuple(panels), kind=n.kind,
                             hold_beats=n.hold_beats,
                             meta={"texture": n.phrase.get("texture", ""), "foot": foot}))
    return out


def _progress(n: ResolvedNote, meter: int) -> float:
    ph = n.phrase
    if "start_bar" in ph and "end_bar" in ph and ph["end_bar"] > ph["start_bar"]:
        b0 = ph["start_bar"] * meter
        b1 = ph["end_bar"] * meter
        return max(0.0, min(1.0, (n.beat - b0) / (b1 - b0)))
    return 0.0
