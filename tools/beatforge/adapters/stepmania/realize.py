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
# Minimum beats between jumps per density, and the run-guard gap. Real DDR charts
# jump on ~8% of rows: jumps PUNCTUATE, they don't fill every beat. Jumps only
# land on integer beats, on a strong metric slot, with breathing room on each
# side (never mid-stream), and spaced at least this far apart.
_JUMP_MIN_SPACING = {"downbeats": 4.0, "accents": 2.0, "free": 1.0}
_JUMP_RUN_GUARD = 0.5      # if a neighbour note is within this many beats, keep single
# Hard ceiling on jump share per density, matched to authored DDR (~8% hardest).
# Guarantees jumps stay accents even on note-dense songs where the spacing rule
# alone would still allow a jump on every strong beat.
_JUMP_MAX_FRAC = {"downbeats": 0.03, "accents": 0.07, "free": 0.12}


def decide_jumps(notes: list[ResolvedNote], budget, meter: int = 4) -> None:
    """Flag a sparse, musical subset of notes as jumps. Jumps are accents on
    strong beats with space around them — never every beat, never inside a fast
    run — then capped to an authored-DDR share so streams stay single & flowing."""
    for n in notes:
        n.is_jump = False
    density = budget.jumps                       # tier ceiling drives the cap
    candidates = []
    last_jump = -99.0
    for i, n in enumerate(notes):
        if n.kind in ("hold", "roll", "mine"):
            continue
        d = n.phrase.get("jump_density", density)
        if d == "none":
            continue
        if abs(n.beat - round(n.beat)) > 1e-3:        # jumps only on integer beats
            continue
        if round(n.beat % meter, 3) not in _JUMP_ALLOWED.get(d, set()):
            continue
        prev_gap = n.beat - notes[i - 1].beat if i > 0 else 9.0
        next_gap = notes[i + 1].beat - n.beat if i + 1 < len(notes) else 9.0
        if min(prev_gap, next_gap) < _JUMP_RUN_GUARD:  # don't jump inside a run
            continue
        if n.beat - last_jump < _JUMP_MIN_SPACING.get(d, 2.0):
            continue
        candidates.append(n)
        last_jump = n.beat
    # cap to the tier's authored jump share, keeping an EVENLY spread subset
    cap = int(_JUMP_MAX_FRAC.get(density, 0.10) * len(notes))
    if cap <= 0:
        return
    if len(candidates) > cap:
        step = len(candidates) / cap
        candidates = [candidates[int(k * step)] for k in range(cap)]
    for n in candidates:
        n.is_jump = True


def realize(notes: list[ResolvedNote], budget, meter: int = 4) -> list[Placement]:
    """Viterbi lowest-cost panel assignment. Returns Placements with concrete
    panels."""
    if not notes:
        return []
    notes = sorted(notes, key=lambda n: n.beat)
    # Viterbi with BACKPOINTERS (not full-path copies): dp maps state->cost, and
    # per step we record how each surviving state was reached. This is O(N) memory
    # instead of O(N^2) list-copying, so pathologically dense charts (1000s of
    # notes) no longer blow up RAM / OOM-kill the process.
    dp: dict[tuple, float] = {ff.REST_STATE: 0.0}
    back: list[dict] = []                 # per note: state -> (prev_state, choice)

    for n in notes:
        mv = n.phrase.get("movement", "static")
        prog = _progress(n, meter)
        ndp: dict[tuple, float] = {}
        bp: dict[tuple, tuple] = {}

        def relax(state, cost, prev, choice):
            if state not in ndp or cost < ndp[state]:
                ndp[state] = cost
                bp[state] = (prev, choice)

        if n.is_jump:
            for st, c0 in dp.items():
                for pl in range(4):
                    for pr in range(4):
                        dc, ns = ff.jump_cost(st, pl, pr, budget, n.beat)
                        if dc >= ff.FORBIDDEN:
                            continue
                        relax(ns, c0 + dc, st, ((pl, pr), "J"))
        else:
            for st, c0 in dp.items():
                for foot in (ff.LEFT, ff.RIGHT):
                    for panel in range(4):
                        dc, ns = ff.step(st, foot, panel, budget, mv, prog, n.beat)
                        if dc >= ff.FORBIDDEN:
                            continue
                        relax(ns, c0 + dc, st, ((panel,), foot))
        # keep the best-N states to bound growth (all 32 fit, but be safe)
        keep = dict(sorted(ndp.items(), key=lambda kv: kv[1])[:64])
        back.append({s: bp[s] for s in keep})
        dp = keep

    # reconstruct the lowest-cost path via backpointers
    state = min(dp, key=lambda s: dp[s])
    choices = []
    for step in reversed(back):
        prev, choice = step[state]
        choices.append(choice)
        state = prev
    choices.reverse()

    out = []
    for n, (panels, foot) in zip(notes, choices):
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
