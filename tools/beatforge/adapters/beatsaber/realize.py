"""realize.py — turn designer INTENT (which onsets are notes, each note's kind +
hand + per-phrase feel) into concrete, swing-legal, FLOWING Beat Saber geometry
(SABERFORGE spec §5, REQ-BS-02). This is the adapter's core build.

The designer never emits grid coordinates, cut directions, or parity — only
`(ref, hand, kind)` and phrase feel. This solver assigns `(x, y, d)` per note.

Flow model (what makes swings playable, not a jackhammer):
  * parity ALTERNATES per hand (forehand↔backhand), telegraphed resets excepted;
  * a swing's cut direction carries its VERTICAL component from parity (down-family
    for forehand, up-family for backhand) and its HORIZONTAL component from the
    direction of lateral travel — so the sabre flows diagonally the way the pattern
    is moving instead of chopping straight up/down on one spot;
  * the block sits so the follow-through sweeps into open space (down-cuts mid/top,
    up-cuts mid/bottom), kept near the middle row and only spread to the aligned
    extreme on accents / high energy;
  * lateral motion, row spread and density all scale with the song's energy, so the
    map breathes in the quiet and drives in the drop.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import parity as par
from .grammar import (BACKHAND, DOWN, DOWN_LEFT, DOWN_RIGHT, FOREHAND, DOT,
                      HAND_COLOR, OPPOSITE_DIRECTION, PARITY_ROWS, UP, UP_LEFT,
                      UP_RIGHT, opposite_parity, swing_turn)


@dataclass
class ResolvedNote:
    """One resolved designer intent event, before geometry is assigned."""
    beat: float
    hand: str = "either"              # left|right|either
    kind: str = "note"                # note|arc|chain|bomb_reset
    tail_beat: float | None = None    # arc/chain tail
    slices: int | None = None         # chain slice count
    phrase: dict = field(default_factory=dict)


@dataclass
class SaberObject:
    """A realized, concrete Beat Saber object. serialize.py maps these onto the
    v3 collections (colorNotes / bombNotes / obstacles / sliders / burstSliders)."""
    kind: str                         # note|bomb|arc|chain
    beat: float
    x: int
    y: int
    color: int = 0                    # 0 red/left, 1 blue/right (note/arc/chain)
    direction: int = DOT              # cut direction d
    angle: int = 0                    # a offset (deg, v3)
    tail_beat: float | None = None
    tail_x: int | None = None
    tail_y: int | None = None
    tail_direction: int | None = None
    slice_count: int | None = None
    squish: float = 1.0
    meta: dict = field(default_factory=dict)


# Home column bands per hand at min/max energy width. Keeping red on the left and
# blue on the right preserves the joint swing-path separation (§5.1) while still
# giving each hand room to move laterally.
_HAND_BANDS = {"left": [0, 1, 2], "right": [1, 2, 3]}


def _energy_at(analysis: dict, beat: float, meter: int) -> float:
    ec = analysis.get("energy_curve", [])
    if ec:
        bar = int(beat // meter)
        if 0 <= bar < len(ec):
            return float(ec[bar])
    for s in analysis.get("sections", []):
        if s["start_bar"] * meter <= beat < s["end_bar"] * meter:
            return float(s.get("energy_pct", 0.6))
    return 0.6


def _band(hand: str, energy: float, tech: str) -> list[int]:
    """Columns this hand may use right now — 2 wide when calm, 3 when driving so
    lateral motion (and thus diagonal flow) grows with the music."""
    full = _HAND_BANDS[hand]
    wide = energy > 0.6 or tech in ("tech", "streamy")
    width = 3 if wide else 2
    return full[:width] if hand == "left" else full[-width:]


def _direction(parity_name: str, dx: int) -> int:
    """Cut direction: vertical component from parity, horizontal from lateral
    travel `dx` (>0 moving right, <0 left, 0 none) — the sabre flows the way the
    pattern moves rather than chopping straight up/down."""
    if parity_name == BACKHAND:
        return UP_RIGHT if dx > 0 else UP_LEFT if dx < 0 else UP
    return DOWN_RIGHT if dx > 0 else DOWN_LEFT if dx < 0 else DOWN


def _row(parity_name: str, rows: tuple, energy: float, accent: bool, i: int) -> int:
    """Mostly the middle row (flowing), spreading to the parity's ALIGNED extreme
    (down-cut→top, up-cut→bottom) on accents or in high-energy stretches."""
    natural = PARITY_ROWS[parity_name][-1]          # the aligned extreme (2 or 0)
    use_extreme = accent or (energy > 0.62 and i % 2 == 0) or (energy > 0.85)
    y = natural if use_extreme else 1
    if y not in rows:                               # tier may forbid the top row
        y = min(rows, key=lambda r: abs(r - y))
    return y


def _step_lateral(x: int, direction: int, band: list[int]) -> tuple[int, int]:
    """Walk one column along `direction`, bouncing at the band edges. Guarantees a
    non-zero lateral move whenever the band is wider than one column, so
    consecutive swings get diagonal directions instead of cardinals."""
    if len(band) <= 1:
        return band[0], direction
    nx = x + direction
    if nx < band[0]:
        direction = 1
        nx = band[0] + 1
    elif nx > band[-1]:
        direction = -1
        nx = band[-1] - 1
    return nx, direction


def _assign_hands(notes: list[ResolvedNote]) -> None:
    """Resolve every `either` note to a concrete hand, keeping the two hands
    balanced (spec REQ-BS-10 hand balance 40–60%)."""
    counts = {"left": 0, "right": 0}
    last = "right"
    for n in notes:
        if n.hand in ("left", "right"):
            counts[n.hand] += 1
            last = n.hand
            continue
        if counts["left"] < counts["right"]:
            n.hand = "left"
        elif counts["right"] < counts["left"]:
            n.hand = "right"
        else:
            n.hand = "left" if last == "right" else "right"
        counts[n.hand] += 1
        last = n.hand


def _realize_hand(notes: list[ResolvedNote], hand: str, analysis: dict, budget,
                  meter: int, start_parity: str) -> list[SaberObject]:
    """Constructive flow walker for one hand's swing sequence."""
    color = HAND_COLOR[hand]
    bpm = analysis["bpm"]
    rows = tuple(budget.rows)
    # one swing per hand per beat — two same-colour blocks on one beat would stack
    # into an unplayable double; keep the first at each beat.
    swings, seen = [], set()
    for n in sorted(notes, key=lambda n: n.beat):
        if n.kind not in ("note", "arc", "chain"):
            continue
        key = round(n.beat, 3)
        if key in seen:
            continue
        seen.add(key)
        swings.append(n)
    if not swings:
        return []

    parity_name = start_parity
    band = _band(hand, _energy_at(analysis, swings[0].beat, meter), "flowy")
    x = band[0] if hand == "left" else band[-1]
    lateral = 1 if hand == "left" else -1
    prev_x = x
    prev_dir = None
    prev_beat = swings[0].beat
    out: list[SaberObject] = []

    for i, n in enumerate(swings):
        ph = n.phrase
        if i == 0:
            parity_name = start_parity
        elif ph.get("_telegraphed"):
            parity_name = parity_name            # telegraphed reset keeps parity
        else:
            parity_name = opposite_parity(parity_name)

        energy = _energy_at(analysis, n.beat, meter)
        tech = ph.get("tech", "flowy")
        band = _band(hand, energy, tech)
        x, lateral = _step_lateral(x, lateral, band)
        dx = x - prev_x
        accent = abs(n.beat - round(n.beat)) < 1e-3 and round(n.beat) % meter == 0
        y = _row(parity_name, rows, energy, accent, i)
        d = _choose_direction(parity_name, dx, prev_dir, n.beat - prev_beat, bpm, accent)

        obj = SaberObject(kind="note", beat=n.beat, x=x, y=y, color=color,
                          direction=d, meta={"hand": hand, "parity": parity_name})
        if n.kind == "arc" and n.tail_beat is not None:
            _make_arc(obj, n, parity_name, rows, band)
        elif n.kind == "chain":
            _make_chain(obj, n, parity_name, rows)
        out.append(obj)
        prev_x, prev_dir, prev_beat = x, obj.direction, n.beat
    return out


def _choose_direction(parity_name: str, dx: int, prev_dir: int | None,
                      dt_beats: float, bpm: float, accent: bool) -> int:
    """Pick the cut direction. The DEFAULT is the natural anti-parallel reversal of
    the previous swing — zero extra wrist turn, perfect flow, and always the right
    parity. Only when the timing budget affords it (an accent, or ample time) do we
    rotate toward a lateral-matching diagonal for variety, and never past what the
    reaction window allows — so dense streams stay clean and playable while calmer
    passages get shape."""
    want = _direction(parity_name, dx)
    if prev_dir is None:
        return want
    base = OPPOSITE_DIRECTION[prev_dir]          # zero-turn reversal
    if par.direction_parity(base) != parity_name:
        # telegraphed reset (parity unchanged): no zero-turn reversal exists —
        # take a same-family direction and accept the (telegraphed) turn.
        return want
    budget_deg = par._angle_budget_deg(max(1e-3, dt_beats), bpm)
    if want != base and swing_turn(prev_dir, want) <= budget_deg + 1e-6 \
            and (accent or dt_beats >= 1.0):
        return want
    return base


def _make_arc(obj: SaberObject, n: ResolvedNote, parity_name: str, rows, band) -> None:
    """An arc (slider) eases the sabre from the head into a follow-through tail on
    the opposite parity's aligned row, continuing the swing path."""
    obj.kind = "arc"
    tail_parity = opposite_parity(parity_name)
    ty = next((r for r in PARITY_ROWS[tail_parity] if r in rows), obj.y)
    obj.tail_beat = n.tail_beat
    obj.tail_x = obj.x
    obj.tail_y = ty
    obj.tail_direction = obj.direction if obj.direction != DOT else DOT


def _make_chain(obj: SaberObject, n: ResolvedNote, parity_name: str, rows) -> None:
    """A chain (burstSlider): a head note sliced toward the parity's follow-through
    cell in the same swing direction."""
    obj.kind = "chain"
    natural = PARITY_ROWS[parity_name][-1]
    ty = natural if natural in rows else obj.y
    obj.slice_count = max(2, min(8, n.slices or 3))
    obj.squish = 1.0
    obj.tail_beat = n.tail_beat if n.tail_beat is not None else n.beat + 0.5
    obj.tail_x = obj.x
    obj.tail_y = ty
    if obj.direction == DOT:
        obj.direction = par.cut_options(parity_name)[0]


def _bomb_reset_objects(beat: float, hand: str, budget) -> list[SaberObject]:
    """Emit a telegraphed bomb reset (spec §5): a bomb in the hand's home column
    that pushes the sabre toward neutral, giving the next same-parity swing legal
    lead time. Bombs never leave the 4×3 grid."""
    x = 1 if hand == "left" else 2
    return [SaberObject(kind="bomb", beat=beat, x=x, y=1, meta={"hand": hand,
                                                                "reset": True})]


def realize(resolved: list[ResolvedNote], analysis: dict, difficulty: str,
            budget) -> list[SaberObject]:
    """Assign concrete geometry to every resolved note. Splits by hand, resolves
    `either`, runs the per-hand flow walker, inserts bomb resets, and enforces the
    two-hand joint swing-path constraint on simultaneous notes."""
    if not resolved:
        return []
    meter = analysis.get("meter", 4)
    notes = sorted(resolved, key=lambda n: n.beat)
    _assign_hands([n for n in notes if n.kind != "bomb_reset"])

    bombs: list[SaberObject] = []
    for i, n in enumerate(notes):
        if n.kind != "bomb_reset":
            continue
        hand = n.hand if n.hand in ("left", "right") else "left"
        bombs += _bomb_reset_objects(n.beat, hand, budget)
        for m in notes[i + 1:]:
            if m.kind in ("note", "arc", "chain") and m.hand == hand:
                m.phrase = {**m.phrase, "_telegraphed": True}
                break

    left = [n for n in notes if n.hand == "left" and n.kind != "bomb_reset"]
    right = [n for n in notes if n.hand == "right" and n.kind != "bomb_reset"]
    # start the hands on opposite parity so the two sabres don't mirror identically
    objs = (_realize_hand(left, "left", analysis, budget, meter, FOREHAND)
            + _realize_hand(right, "right", analysis, budget, meter, BACKHAND)
            + bombs)
    objs.sort(key=lambda o: (o.beat, o.color))
    _separate_simultaneous(objs)
    return objs


def _separate_simultaneous(objs: list[SaberObject]) -> None:
    """Joint swing-path constraint (spec §5.1): on any beat where both colours
    have a note, force red to the left half (x≤1) and blue to the right half
    (x≥2) so neither sits in the other's pre-cut/follow-through swing path."""
    by_beat: dict[float, list[SaberObject]] = {}
    for o in objs:
        if o.kind in ("note", "arc", "chain"):
            by_beat.setdefault(round(o.beat, 4), []).append(o)
    for group in by_beat.values():
        if len({o.color for o in group}) < 2:
            continue
        for o in group:
            if o.color == 0 and o.x > 1:
                o.x = 1
                if o.tail_x is not None:
                    o.tail_x = min(o.tail_x, 1)
            elif o.color == 1 and o.x < 2:
                o.x = 2
                if o.tail_x is not None:
                    o.tail_x = max(o.tail_x, 2)
