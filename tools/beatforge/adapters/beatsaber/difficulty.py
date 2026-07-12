"""difficulty.py — per-difficulty NJS/offset + difficultyRank (SABERFORGE spec
§8, REQ-BS-08). NJS/offset are CONSTANT within a difficulty (ScoreSaber hard
rule); NJS may auto-nudge for very high/very low BPM so reaction time stays sane,
then is locked for the whole chart. Difficulty stays monotonic Easy→Expert+ by
construction (the budget table is ordered)."""
from __future__ import annotations

from .grammar import BUDGETS, DIFFICULTIES

# NJS comfort clamp. NJS sets how fast blocks fly in; at a given BPM the reaction
# distance is proportional to NJS/BPM. We nudge NJS for outlier tempos so the
# reaction window stays sane, then clamp + lock it for the whole chart.
_NJS_MIN, _NJS_MAX = 8.0, 23.0


def compute_njs(difficulty: str, bpm: float) -> tuple[float, float]:
    """(njs, offset) for a difficulty at this BPM. Base NJS from the budget,
    nudged so very fast/slow songs keep a sane reaction time, clamped + locked."""
    b = BUDGETS[difficulty]
    njs = b.njs
    # Beat Saber's default reaction distance targets ~120-160 BPM. Outside that,
    # nudge NJS proportionally so blocks don't arrive too early/late, then clamp.
    if bpm > 0:
        ref_bpm = 130.0
        njs = njs * (bpm / ref_bpm) ** 0.5
    njs = max(_NJS_MIN, min(_NJS_MAX, round(njs, 1)))
    # never let the nudge break the monotonic ladder: keep >= a floor per tier
    njs = max(njs, b.njs * 0.8)
    return round(njs, 1), b.offset


def difficulty_rank(difficulty: str) -> int:
    return BUDGETS[difficulty].difficulty_rank


def njs_offset_table(difficulties, bpm: float) -> dict:
    """{difficulty: (njs, offset, rank)} for the requested set, NJS locked."""
    return {d: (*compute_njs(d, bpm), difficulty_rank(d)) for d in difficulties}


def is_monotonic(difficulties) -> bool:
    """True iff NJS, finest-precision and max-NPS all increase (non-decreasing)
    along the requested difficulty order (spec §8 accept)."""
    order = [d for d in DIFFICULTIES if d in difficulties]
    njs = [BUDGETS[d].njs for d in order]
    nps = [BUDGETS[d].max_nps_4s for d in order]
    prec = [BUDGETS[d].finest_precision for d in order]   # finer = smaller
    return (all(njs[i] <= njs[i + 1] for i in range(len(njs) - 1))
            and all(nps[i] <= nps[i + 1] for i in range(len(nps) - 1))
            and all(prec[i] >= prec[i + 1] for i in range(len(prec) - 1)))
