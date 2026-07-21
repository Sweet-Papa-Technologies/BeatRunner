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

    # 3. re-cap the jump share AFTER repair (pad ergonomics).
    #
    # `decide_jumps` caps jumps as a fraction of the notes it was handed, but
    # `_nps` thinning then drops *single taps* preferentially — jumps survive. The
    # surviving share therefore drifts UP as density rises, and it drifted badly:
    # Round 2's `hard` charts measured 21.5% jumps against a 12% budget, more than
    # its own `challenge` tier. On a dance pad a jump is a two-foot commitment, so
    # that is precisely the wrong thing to let inflate.
    kept = cap_jump_share(kept, b, meter=4, repairs=repairs)

    repaired_frac = (original - len(kept)) / original if original else 0.0
    return RepairReport(kept, repairs, original, repaired_frac <= 0.15 + 1e-9)


def cap_jump_share(notes, b, meter: int = 4, repairs: list | None = None):
    """Demote surplus jumps to single taps so the realized share honours the tier.

    Demotes rather than deletes: the note stays on the music (timing untouched,
    SACRED-02 safe), it just stops costing a second foot. Off-downbeat jumps go
    first — a jump on beat 1 is the accent the chart is built around, one on an
    off-beat is the one that makes a pad chart feel scrappy.
    """
    from .realize import _JUMP_MAX_FRAC

    jumps = [i for i, p in enumerate(notes) if len(p.panels) > 1 and not p.hold_beats]
    if not jumps:
        return notes
    cap = int(_JUMP_MAX_FRAC.get(b.jumps, 0.10) * len(notes))
    surplus = len(jumps) - cap
    if surplus <= 0:
        return notes

    def priority(i):
        beat = notes[i].beat
        on_downbeat = abs(beat % meter) < 1e-3
        on_beat = abs(beat - round(beat)) < 1e-3
        return (on_downbeat, on_beat, beat)      # False sorts first -> demoted first

    for i in sorted(jumps, key=priority)[:surplus]:
        p = notes[i]
        notes[i] = Placement(p.beat, p.panels[:1], p.kind, p.hold_beats, p.meta)
        if repairs is not None:
            repairs.append(("jump_demoted", round(p.beat, 3)))
    return notes


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
