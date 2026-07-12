"""validate.py — ScoreSaber-criteria legality lint + repair (SABERFORGE spec
§5.2, Appendix C, REQ-BS-03). Runs AFTER realization: the parity DP already
minimised swing cost, so repair is mostly reset/angle re-routing, NPS thinning,
bomb-spacing and precision fixes. >15% of notes repaired -> fail -> re-prompt
(the inherited fail-loud contract).

Each rule below has a standalone *detector* (used directly by the unit tests in
tests/test_saberforge.py) plus a repair path.
"""
from __future__ import annotations

from dataclasses import dataclass

from ... import config
from . import parity as par
from .grammar import (BOMB_MIN_SPACING_MS, DOT, MAX_ACTIVE_ARCS_PER_HAND,
                      PARITY_ROWS, PRECISION_BPM_LIMIT, angle_between,
                      opposite_parity, swing_turn)
from .parity import direction_parity
from .realize import SaberObject


@dataclass
class RepairReport:
    objects: list
    repairs: list
    original: int
    ok: bool                    # False if >15% repaired (re-prompt)


def _sec(beat: float, bpm: float, offset: float) -> float:
    return offset + beat / bpm * 60.0


def _notes(objs):
    return [o for o in objs if o.kind in ("note", "arc", "chain")]


# --------------------------------------------------------------------------- #
# Detectors (each returns a list of violation dicts). Pure, order-independent.
# --------------------------------------------------------------------------- #
def detect_resets(objs, budget) -> list[dict]:
    """A reset is two same-parity swings in a row on one hand. Telegraphed resets
    (a bomb reset precedes with lead time) are legal when the tier allows them."""
    out = []
    for color in (0, 1):
        seq = [o for o in _notes(objs) if o.color == color]
        seq.sort(key=lambda o: o.beat)
        prev = None
        for o in seq:
            p = direction_parity(o.direction)
            if p == par.NEUTRAL:
                prev = prev  # dots don't change the parity expectation
                continue
            if prev is not None and p == prev and not o.meta.get("telegraphed"):
                out.append({"rule": "reset", "beat": o.beat, "color": color})
            prev = p
    return out


def detect_angle(objs, bpm, budget) -> list[dict]:
    """Wrist rotation between consecutive same-hand swings must fit the time gap
    (spec §5.2). Measured as the turn BEYOND the natural anti-parallel reversal, so
    a normal alternating flip costs nothing and only genuine over-rotation flags."""
    out = []
    for color in (0, 1):
        seq = [o for o in _notes(objs) if o.color == color and o.direction != DOT]
        seq.sort(key=lambda o: o.beat)
        for a, b in zip(seq, seq[1:]):
            dt = max(1e-3, b.beat - a.beat)
            budget_deg = par._angle_budget_deg(dt, bpm)
            if swing_turn(a.direction, b.direction) > budget_deg + 1e-6:
                out.append({"rule": "angle", "beat": b.beat, "color": color})
    return out


def detect_parallel_same_color(objs) -> list[dict]:
    """Two same-colour notes on the same snap must not be parallel and must be
    ≤45° apart (spec §5.2)."""
    out = []
    by = {}
    for o in _notes(objs):
        by.setdefault((round(o.beat, 4), o.color), []).append(o)
    for (beat, color), group in by.items():
        for a, b in zip(group, group[1:]):
            if a.direction == DOT or b.direction == DOT:
                continue
            ang = angle_between(a.direction, b.direction)
            if ang > 45.0 + 1e-6:
                out.append({"rule": "parallel_same_color", "beat": beat, "color": color})
    return out


def detect_opposite_swing_path(objs) -> list[dict]:
    """No note in the opposite colour's pre-cut/follow-through swing path on a
    shared snap: red on the right half while blue is on the left half (crossed)
    is the intrusion this catches (spec §5.2)."""
    out = []
    by = {}
    for o in _notes(objs):
        by.setdefault(round(o.beat, 4), []).append(o)
    for beat, group in by.items():
        reds = [o for o in group if o.color == 0]
        blues = [o for o in group if o.color == 1]
        for r in reds:
            for bl in blues:
                if r.x > bl.x:               # red physically right of blue = crossed hands
                    out.append({"rule": "opposite_swing_path", "beat": beat})
                    break
    return out


def detect_bomb_spacing(objs, bpm, offset) -> list[dict]:
    """Bombs sharing a cell must be ≥20 ms apart (spec §5.2)."""
    out = []
    by = {}
    for o in objs:
        if o.kind == "bomb":
            by.setdefault((o.x, o.y), []).append(o)
    for cell, group in by.items():
        group.sort(key=lambda o: o.beat)
        for a, b in zip(group, group[1:]):
            if (_sec(b.beat, bpm, offset) - _sec(a.beat, bpm, offset)) * 1000.0 < BOMB_MIN_SPACING_MS - 1e-6:
                out.append({"rule": "bomb_spacing", "beat": b.beat, "cell": cell})
    return out


def detect_precision(objs, bpm, budget) -> list[dict]:
    """Precision sanity: ≤1/16 up to 180 BPM, ≤1/8 up to 360 BPM (spec §5.2), and
    never finer than the tier's finest_precision."""
    finest = budget.finest_precision
    for cap_bpm, cap_prec in PRECISION_BPM_LIMIT:
        if bpm <= cap_bpm:
            finest = max(finest, cap_prec)
            break
    else:
        finest = max(finest, PRECISION_BPM_LIMIT[-1][1])
    out = []
    for o in _notes(objs):
        if abs(o.beat / finest - round(o.beat / finest)) > 1e-3:
            out.append({"rule": "precision", "beat": o.beat})
    return out


def detect_arc_overlap(objs) -> list[dict]:
    """≤5 arcs active per hand at any instant (spec §4/§5.2)."""
    out = []
    for color in (0, 1):
        arcs = [o for o in objs if o.kind == "arc" and o.color == color
                and o.tail_beat is not None]
        events = []
        for a in arcs:
            events.append((a.beat, 1, a))
            events.append((a.tail_beat, -1, a))
        events.sort(key=lambda e: (e[0], e[1]))
        active = 0
        for _, delta, a in events:
            active += delta
            if active > MAX_ACTIVE_ARCS_PER_HAND:
                out.append({"rule": "arc_overlap", "beat": a.beat, "color": color})
    return out


# --------------------------------------------------------------------------- #
# Repair pipeline
# --------------------------------------------------------------------------- #
def validate_repair(objs: list[SaberObject], analysis: dict, difficulty: str) -> RepairReport:
    from .grammar import BUDGETS
    b = BUDGETS[difficulty]
    bpm, offset = analysis["bpm"], analysis["offset"]
    original = len(_notes(objs))
    repairs: list = []

    objs = sorted(objs, key=lambda o: (o.beat, o.color))

    # 1. drop bombs that violate spacing.
    objs = _drop_bomb_spacing(objs, bpm, offset, repairs)
    # 2. NPS thinning to the tier cap (drop lowest-impact notes).
    objs = _thin_nps(objs, b, bpm, offset, repairs)
    # 3. precision snap: drop notes still off the legal grid after everything.
    objs = _drop_precision(objs, b, bpm, repairs)
    # 4. normalise parity on the SURVIVORS (thinning can create new same-parity
    #    adjacencies): re-derive strict alternation, choosing within each parity
    #    family the direction that best fits the inter-note angle budget. Runs last
    #    so the swing simulator is clean by construction.
    _normalize_parity(objs, bpm, repairs)

    kept_notes = len(_notes(objs))
    repaired_frac = (original - kept_notes) / original if original else 0.0
    return RepairReport(objs, repairs, original, repaired_frac <= config.MAX_REPAIR_FRACTION + 1e-9)


def _normalize_parity(objs, bpm, repairs):
    """Walk each hand's surviving swings and guarantee the map is clean by
    construction: strict forehand/backhand alternation (telegraphed resets
    excepted) AND no over-rotation. Notes that are already correct KEEP the
    realizer's flow direction; only a swing that would be a reset OR that
    over-rotates against its (post-thinning) neighbour is re-cut to the natural
    anti-parallel reversal — so repair preserves flow instead of flattening it."""
    from .realize import _direction
    from .grammar import OPPOSITE_DIRECTION
    for color in (0, 1):
        seq = sorted((o for o in _notes(objs) if o.color == color), key=lambda o: o.beat)
        prev_parity = None
        prev_dir = None
        prev_x = None
        prev_beat = None
        for o in seq:
            cur = direction_parity(o.direction)
            if cur == par.NEUTRAL:                     # dots: keep, don't alter parity
                prev_x = o.x
                continue
            if prev_parity is None or o.meta.get("telegraphed"):
                desired = cur                          # first swing / legal telegraphed reset
            else:
                desired = opposite_parity(prev_parity)
            budget_deg = par._angle_budget_deg(max(1e-3, o.beat - (prev_beat or o.beat)), bpm)
            over = (prev_dir is not None and o.direction != DOT
                    and swing_turn(prev_dir, o.direction) > budget_deg + 1e-6)
            if desired != cur or over:                 # reset or over-rotation → re-cut
                base = OPPOSITE_DIRECTION[prev_dir] if prev_dir is not None else None
                if base is not None and direction_parity(base) == desired:
                    o.direction = base                 # zero-turn reversal
                else:
                    o.direction = _direction(desired, 0 if prev_x is None else o.x - prev_x)
                if o.y == PARITY_ROWS[cur][-1] and desired != cur:
                    o.y = 1                            # off the now-wrong extreme
                o.meta["parity"] = desired
                repairs.append(("parity", round(o.beat, 3)))
            prev_parity = desired
            prev_dir = o.direction
            prev_x = o.x
            prev_beat = o.beat


def _drop_bomb_spacing(objs, bpm, offset, repairs):
    by = {}
    for o in objs:
        if o.kind == "bomb":
            by.setdefault((o.x, o.y), []).append(o)
    remove = set()
    for group in by.values():
        group.sort(key=lambda o: o.beat)
        last = None
        for o in group:
            if last is not None and (_sec(o.beat, bpm, offset) - _sec(last, bpm, offset)) * 1000.0 < BOMB_MIN_SPACING_MS - 1e-6:
                remove.add(id(o))
                repairs.append(("bomb_spacing", round(o.beat, 3)))
            else:
                last = o.beat
    return [o for o in objs if id(o) not in remove]


def _thin_nps(objs, budget, bpm, offset, repairs):
    notes = _notes(objs)
    others = [o for o in objs if o.kind == "bomb"]
    guard = 0
    while guard < 5000:
        guard += 1
        drop = _nps_worst(notes, budget.max_nps_4s, bpm, offset)
        if drop is None:
            break
        repairs.append(("nps", round(notes[drop].beat, 3)))
        notes.pop(drop)
    return sorted(notes + others, key=lambda o: (o.beat, o.color))


def _nps_worst(notes, max_nps, bpm, offset):
    if not notes:
        return None
    notes.sort(key=lambda o: o.beat)
    times = [_sec(n.beat, bpm, offset) for n in notes]
    for i in range(len(notes)):
        j = i
        while j < len(notes) and times[j] - times[i] < 4.0:
            j += 1
        if (j - i) / 4.0 > max_nps + 1e-6:
            mid = (i + j) // 2
            return mid
    return None


def _drop_precision(objs, budget, bpm, repairs):
    finest = budget.finest_precision
    for cap_bpm, cap_prec in PRECISION_BPM_LIMIT:
        if bpm <= cap_bpm:
            finest = max(finest, cap_prec)
            break
    keep = []
    for o in objs:
        if o.kind in ("note", "arc", "chain") and abs(o.beat / finest - round(o.beat / finest)) > 1e-3:
            repairs.append(("precision", round(o.beat, 3)))
            continue
        keep.append(o)
    return keep
