"""simulate.py — the in-core swing simulator (SABERFORGE spec §5, REQ-BS-04):
the beatable-by-construction gate. It deterministically "plays" a finished map,
tracking both hands' parity + grid position through the whole note sequence, and
reports every forced reset or impossible transition. Shippable maps must simulate
clean (zero forced resets). This is the SABERFORGE analog of the StepMania bot /
WaveSurf autopilot.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import parity as par
from .grammar import DOT, swing_turn
from .parity import direction_parity


@dataclass
class SimResult:
    forced_resets: list = field(default_factory=list)   # (color, beat)
    impossible: list = field(default_factory=list)      # (color, beat, reason)
    hand_notes: dict = field(default_factory=dict)      # color -> count

    @property
    def clean(self) -> bool:
        return not self.forced_resets and not self.impossible


def simulate(objs: list, analysis: dict) -> SimResult:
    """Replay the map. A forced reset = two same-parity swings in a row on one
    hand with no telegraphed bomb reset between them. An impossible transition =
    an angle change too large for the time available at this BPM."""
    bpm = analysis["bpm"]
    res = SimResult(hand_notes={0: 0, 1: 0})

    # bomb resets per hand: a bomb tagged reset telegraphs a legal parity break for
    # the next swing on that hand.
    reset_beats = {0: [], 1: []}
    for o in objs:
        if o.kind == "bomb" and o.meta.get("reset"):
            hand = o.meta.get("hand", "left")
            reset_beats[0 if hand == "left" else 1].append(o.beat)

    for color in (0, 1):
        seq = sorted((o for o in objs if o.kind in ("note", "arc", "chain")
                      and o.color == color), key=lambda o: o.beat)
        res.hand_notes[color] = len(seq)
        prev_parity = None
        prev_dir = None
        prev_beat = None
        for o in seq:
            p = direction_parity(o.direction)
            if p != par.NEUTRAL and prev_parity is not None and p == prev_parity:
                telegraphed = any(prev_beat is not None and prev_beat < rb <= o.beat + 1e-6
                                  for rb in reset_beats[color]) or o.meta.get("telegraphed")
                if not telegraphed:
                    res.forced_resets.append((color, round(o.beat, 3)))
            if prev_dir is not None and prev_dir != DOT and o.direction != DOT and prev_beat is not None:
                dt = max(1e-3, o.beat - prev_beat)
                # a natural reversal (anti-parallel) costs 0 turn; only rotation
                # BEYOND that is bounded by the reaction time (spec §5.2).
                if swing_turn(prev_dir, o.direction) > par._angle_budget_deg(dt, bpm) + 1e-6:
                    res.impossible.append((color, round(o.beat, 3), "over_angle"))
            if p != par.NEUTRAL:
                prev_parity = p
            prev_dir = o.direction
            prev_beat = o.beat
    return res
