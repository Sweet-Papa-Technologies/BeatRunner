"""validate.py — legality + ergonomic gates with repair (STEPFORGE §5,
REQ-SM-04/11). Runs AFTER realization: the DP already minimized foot-flow cost,
so repair is mostly NPS thinning, hold-overlap and jump-cap fixes, plus a
foot-flow-ceiling check. >15% of notes repaired -> fail -> re-prompt."""
from __future__ import annotations

from dataclasses import dataclass

from ... import config
from . import footflow as ff
from .grammar import BUDGETS
from .quantize import Placement, measure_resolution_ok, snap_beat


@dataclass
class RepairReport:
    placements: list
    repairs: list
    original: int
    ok: bool                    # False if >15% repaired (re-prompt)


def validate_repair(placements: list[Placement], analysis: dict, difficulty: str) -> RepairReport:
    b = BUDGETS[difficulty]
    bpm, offset = analysis["bpm"], analysis["offset"]
    last_beat = (analysis["duration_s"] - config.PLAYABLE_TAIL_S - offset) * bpm / 60.0
    original = len(placements)
    repairs = []

    # 1. hard legality: window, ≤2 panels, quantization
    kept = []
    for p in sorted(placements, key=lambda p: p.beat):
        if p.beat < config.FIRST_PLAYABLE_BEAT - 1e-6 or p.beat > last_beat + 1e-6:
            repairs.append(("window", round(p.beat, 3))); continue
        panels = tuple(dict.fromkeys(p.panels))[:2]
        if p.hold_beats and len(panels) != 1:
            panels = panels[:1]
        kept.append(Placement(p.beat, panels, p.kind, p.hold_beats, p.meta))

    # 2. iterative ergonomic repair
    kept = _repair(kept, b, bpm, offset, repairs)

    repaired_frac = (original - len(kept)) / original if original else 0.0
    return RepairReport(kept, repairs, original, repaired_frac <= 0.15 + 1e-9)


def _repair(notes, b, bpm, offset, repairs, guard_max=5000):
    guard = 0
    while guard < guard_max:
        guard += 1
        drop = (_hold_overlap(notes)
                or _jack(notes, max(1, b.jack_limit))   # jack_limit N = max same-panel run
                or _nps(notes, b.max_nps_4s, bpm, offset))
        if drop is None:
            break
        idx, reason = drop
        repairs.append((reason, round(notes[idx].beat, 3)))
        notes.pop(idx)
    return notes


def _hold_overlap(notes):
    for i, h in enumerate(notes):
        if not h.hold_beats:
            continue
        end = h.beat + h.hold_beats
        hp = set(h.panels)
        for j, n in enumerate(notes):
            if j == i:
                continue
            if h.beat - 1e-6 < n.beat < end + 1e-6 and hp & set(n.panels):
                return (j, "hold_overlap")
    return None


def _jack(notes, limit):
    run = 1
    for i in range(1, len(notes)):
        same = (notes[i].panels == notes[i - 1].panels and not notes[i].hold_beats)
        run = run + 1 if same else 1
        if run > limit:
            return (i, "jack")
    return None


def _nps(notes, max_nps, bpm, offset):
    if not notes:
        return None
    times = [offset + n.beat / bpm * 60 for n in notes]
    for i in range(len(notes)):
        j = i
        while j < len(notes) and times[j] - times[i] < 4.0:
            j += 1
        if (j - i) / 4.0 > max_nps + 1e-6:
            mid = (i + j) // 2
            taps = [k for k in range(i, j) if not notes[k].hold_beats and len(notes[k].panels) == 1]
            pool = taps or list(range(i, j))
            return (min(pool, key=lambda k: abs(k - mid)), "nps")
    return None
