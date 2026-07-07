"""difficulty.py — integer METER estimate per difficulty (STEPFORGE §8,
REQ-SM-09). One documented heuristic from objective features; monotonic across
Easy<Medium<Hard by construction (clamped into each tier's range)."""
from __future__ import annotations

from .grammar import BUDGETS
from .quantize import Placement


def compute_meter(placements: list[Placement], bpm: float, difficulty: str) -> int:
    """Meter from sustained NPS + jump/crossover/stream density, clamped to the
    difficulty's range so tiers stay monotonic."""
    lo, hi = BUDGETS[difficulty].meter_range
    if not placements:
        return lo
    times = sorted(p.beat / bpm * 60 for p in placements)
    peak = 0
    for i in range(len(times)):
        j = i
        while j < len(times) and times[j] - times[i] < 4.0:
            j += 1
        peak = max(peak, (j - i) / 4.0)                 # notes/sec sustained
    jumps = sum(1 for p in placements if len(p.panels) > 1) / len(placements)
    holds = sum(1 for p in placements if p.hold_beats) / len(placements)
    # longest run of consecutive-beat notes (stream length) as a tech proxy
    frac = min(1.0, peak / 9.0 + jumps * 0.25 + holds * 0.15)
    return max(lo, min(hi, lo + round((hi - lo) * frac)))
