"""resolve.py — designer INTENT -> ResolvedNotes, and a deterministic intent
generator for the no-LLM path (STEPFORGE §5-6).

The designer emits WHICH onsets are notes (by id / grid ref), each note's KIND,
and per-phrase INTENT from a CLOSED vocabulary. It never emits a time or a panel
(rejected here). Panels come later from the realizer.
"""
from __future__ import annotations

import re

from ... import config
from .grammar import BUDGETS, CROSSOVERS, KINDS, MOVEMENTS, TEXTURES
from .realize import ResolvedNote

_GRID_RE = re.compile(r"^grid:(\d+(?:\.\d+)?)$")
_ONSET_RE = re.compile(r"^[pms]\d+$")
_TIME_KEYS = {"time", "t", "row", "seconds", "sec", "ms", "beat", "at"}
_PANEL_KEYS = {"panel", "panels", "col", "cols", "column", "columns", "lane"}


class IntentError(ValueError):
    pass


def _playable(analysis: dict):
    bpm, offset = analysis["bpm"], analysis["offset"]
    last = (analysis["duration_s"] - config.PLAYABLE_TAIL_S - offset) * bpm / 60.0
    return config.FIRST_PLAYABLE_BEAT, last


def _phrase_for(beat: float, phrases: list, meter: int) -> dict:
    bar = beat / meter
    for ph in phrases:
        if ph["start_bar"] - 1e-9 <= bar < ph["end_bar"] + 1e-9:
            return ph
    return {"movement": "static", "crossover": "light", "texture": "steps",
            "jump_density": "accents"}


def _onset_lookup(analysis: dict) -> dict:
    """Onset id -> onset, tolerant of the model dropping zero-padding
    (p16 -> p016) or casing (P016 -> p016)."""
    lut = {}
    for o in analysis.get("onsets", []):
        oid = o["id"]
        lut[oid] = o
        lut[oid.lower()] = o
        m = re.match(r"^([pms])0*(\d+)$", oid)   # also index un-padded form
        if m:
            lut[f"{m.group(1)}{int(m.group(2))}"] = o
    return lut


def resolve_intent(design: dict, analysis: dict, difficulty: str) -> list[ResolvedNote]:
    onsets = _onset_lookup(analysis)
    meter = analysis.get("meter", 4)
    lo_beat, hi_beat = _playable(analysis)
    phrases = _validate_phrases(design.get("phrases", []))

    notes_in = design.get("notes")
    if not isinstance(notes_in, list):
        raise IntentError("designer output has no `notes` array")
    out: list[ResolvedNote] = []
    for i, ev in enumerate(notes_in):
        if not isinstance(ev, dict):
            raise IntentError(f"note[{i}] must be an object")
        keys = set(ev.keys())
        if keys & _TIME_KEYS:
            raise IntentError(f"note[{i}] carries a raw-time field {sorted(keys & _TIME_KEYS)}; "
                              "reference onsets/grid only, never a time")
        if keys & _PANEL_KEYS:
            raise IntentError(f"note[{i}] specifies a panel {sorted(keys & _PANEL_KEYS)}; "
                              "the realizer assigns panels, not the designer")
        ref = ev.get("ref")
        kind = ev.get("kind", "tap")
        # "jump" isn't a note KIND (jumps are the realizer's job from jump_density);
        # the model sometimes emits it anyway. Treat any non-kind as a plain tap
        # rather than failing the whole chart.
        if kind not in KINDS:
            kind = "tap"
        if not isinstance(ref, str):
            raise IntentError(f"note[{i}] missing string `ref`")
        gm = _GRID_RE.match(ref)
        if gm:
            beat = float(gm.group(1))
        elif _ONSET_RE.match(ref):
            o = onsets.get(ref) or onsets.get(ref.lower())
            if o is None:
                raise IntentError(f"note[{i}].ref '{ref}' not in onset inventory")
            beat = float(o["nearest_beat"])
        else:
            raise IntentError(f"note[{i}].ref '{ref}' is neither an onset id nor grid:<beat>")
        if beat < lo_beat - 1e-6 or beat > hi_beat + 1e-6:
            continue
        hold = ev.get("hold_beats")
        if kind in ("hold", "roll"):
            if not isinstance(hold, (int, float)) or hold <= 0:
                raise IntentError(f"note[{i}] kind={kind} needs hold_beats > 0")
        out.append(ResolvedNote(beat=beat, kind=kind,
                               hold_beats=float(hold) if hold else None,
                               phrase=_phrase_for(beat, phrases, meter)))
    out.sort(key=lambda n: n.beat)
    return out


def fill_gaps(resolved: list[ResolvedNote], analysis: dict, difficulty: str,
              max_gap_beats: float = 8.0) -> list[ResolvedNote]:
    """Safety net: the designer sometimes leaves a whole quiet-labelled section
    empty even when it's full of onsets (a 24s hole in the intro). Any stretch of
    the PLAYABLE window longer than `max_gap_beats` with no note gets filled with
    sparse taps on real on-grid onsets (or grid lines), so the chart never has a
    dead pause. Only activates on pathological gaps — normal charts are untouched."""
    b = BUDGETS[difficulty]
    subdiv = b.finest_subdiv
    bpm, offset = analysis["bpm"], analysis["offset"]
    lo_beat, hi_beat = _playable(analysis)
    meter = analysis.get("meter", 4)
    cadence = 2.0 if difficulty in ("beginner", "easy") else 1.0

    # on-grid onsets in the window, indexed by snapped beat, strongest first pick
    grid_onsets: dict[float, dict] = {}
    for o in analysis.get("onsets", []):
        beat = o["nearest_beat"]
        if beat < lo_beat or beat > hi_beat:
            continue
        if abs(beat - round(beat / subdiv) * subdiv) > 1e-3:
            continue
        if abs(o.get("snap_error_ms", 0)) > config.ONSET_SNAP_MAX_MS:
            continue
        k = round(beat, 3)
        if k not in grid_onsets or o["strength"] > grid_onsets[k]["strength"]:
            grid_onsets[k] = o

    occupied = {round(n.beat, 3) for n in resolved}
    boundaries = sorted([lo_beat] + [n.beat for n in resolved] + [hi_beat])
    added: list[ResolvedNote] = []
    for i in range(1, len(boundaries)):
        g0, g1 = boundaries[i - 1], boundaries[i]
        if g1 - g0 <= max_gap_beats:
            continue
        beat = g0 + cadence
        while beat < g1 - cadence / 2:
            tb = round(round(beat / subdiv) * subdiv, 3)
            if tb in occupied:
                beat += cadence
                continue
            # snap the fill to the nearest real onset within half a cadence, else grid
            ref_beat = min((k for k in grid_onsets if abs(k - tb) <= cadence / 2 + 1e-6),
                           key=lambda k: abs(k - tb), default=tb)
            ph = _phrase_for(ref_beat, [], meter)
            added.append(ResolvedNote(beat=ref_beat, kind="tap", phrase=ph))
            occupied.add(round(ref_beat, 3))
            beat += cadence
    if added:
        resolved = sorted(resolved + added, key=lambda n: n.beat)
    return resolved


def thin_for_difficulty(resolved: list[ResolvedNote], analysis: dict,
                        difficulty: str) -> list[ResolvedNote]:
    """Enforce the tier's rhythmic-complexity envelope (STEPFORGE difficulty
    accuracy). Difficulty = how many rhythmic LAYERS are included: lower tiers
    keep a faithful subset on coarser subdivisions with short streams; higher
    tiers admit 16ths and long streams. Learned from authored DDR (LOVE SHINE:
    easy≈quarters/no-stream → challenge≈16th streams). Two deterministic rules:

      1. drop taps finer than the tier's finest subdivision (keeps every remaining
         note on a real, tier-appropriate onset — holds/rolls are always kept),
      2. cap the SHARE of off-quarter notes to fine_frac, keeping lower tiers
         quarter-dominant (an easy chart is mostly on-beat, not a wall of 8ths),
         preferring to keep 8ths over 16ths and spreading the kept ones evenly,
      3. break any run of consecutive fast (≤8th-spaced) notes longer than the
         tier's max_run, so a 'medium' never sustains an expert 16-note stream.
    """
    b = BUDGETS[difficulty]
    if not resolved:
        return resolved
    notes = sorted(resolved, key=lambda n: n.beat)
    finest = b.finest_subdiv

    def on_grid(beat: float) -> bool:
        return abs(beat / finest - round(beat / finest)) < 1e-3

    def is_quarter(beat: float) -> bool:
        return abs(beat - round(beat)) < 1e-3

    def is_eighth(beat: float) -> bool:      # on the 0.5 grid but not a quarter
        return abs(beat * 2 - round(beat * 2)) < 1e-3 and not is_quarter(beat)

    def even_subset(lst, k):                 # keep k items spread evenly across lst
        if k >= len(lst):
            return lst
        if k <= 0:
            return []
        return [lst[int(x * len(lst) / k)] for x in range(k)]

    notes = [n for n in notes if n.kind in ("hold", "roll") or on_grid(n.beat)]

    # --- cap the off-quarter share to the tier's fine_frac ---
    fine_frac = getattr(b, "fine_frac", 0.6)
    protected = [n for n in notes if is_quarter(n.beat) or n.kind in ("hold", "roll")]
    fine = [n for n in notes if not is_quarter(n.beat) and n.kind not in ("hold", "roll")]
    # target counts fine notes RELATIVE to the kept total: keep_fine/(prot+keep_fine)
    # = fine_frac  ->  keep_fine = fine_frac/(1-fine_frac) * prot.
    target = (len(fine) if fine_frac >= 0.999
              else int(round(fine_frac / (1 - fine_frac) * len(protected))))
    if len(fine) > target:
        eighths = [n for n in fine if is_eighth(n.beat)]
        finer = [n for n in fine if not is_eighth(n.beat)]
        keep_e = even_subset(eighths, target)                  # 8ths first
        keep_f = even_subset(finer, max(0, target - len(keep_e)))
        kept = set(id(n) for n in keep_e + keep_f)
        notes = sorted(protected + [n for n in fine if id(n) in kept],
                       key=lambda n: n.beat)

    max_run = getattr(b, "max_run", 8)
    keep = [True] * len(notes)
    i = 0
    while i < len(notes):
        j = i
        while j + 1 < len(notes) and (notes[j + 1].beat - notes[j].beat) <= 0.5 + 1e-6:
            j += 1
        if j - i + 1 > max_run:                    # too-long stream -> segment it
            for k in range(i, j + 1):
                if (k - i) % (max_run + 1) == max_run:
                    keep[k] = False
        i = j + 1
    return [n for n, k in zip(notes, keep) if k]


def _validate_phrases(phrases: list) -> list:
    for ph in phrases:
        for field, vocab in (("texture", TEXTURES), ("movement", MOVEMENTS),
                             ("crossover", CROSSOVERS)):
            v = ph.get(field)
            if v is not None and v not in vocab:
                raise IntentError(f"phrase {field} '{v}' not in closed vocabulary {list(vocab)}")
    return phrases


# --------------------------------------------------------------------------- #
# Deterministic intent (no LLM) — select on-grid onsets, phrases from sections
# --------------------------------------------------------------------------- #
def deterministic_intent(analysis: dict, difficulty: str) -> dict:
    b = BUDGETS[difficulty]
    subdiv = b.finest_subdiv
    lo_beat, hi_beat = _playable(analysis)
    min_gap = subdiv
    notes, last = [], -99.0
    for o in sorted(analysis.get("onsets", []), key=lambda o: o["nearest_beat"]):
        beat = o["nearest_beat"]
        if beat < lo_beat or beat > hi_beat:
            continue
        if abs(beat - round(beat / subdiv) * subdiv) > 1e-3:
            continue
        if abs(o.get("snap_error_ms", 0)) > config.ONSET_SNAP_MAX_MS:
            continue
        if beat - last < min_gap - 1e-6:
            continue
        kind = "tap"
        hold = None
        if o.get("sustain") and o.get("sustain_beats", 0) >= b.hold_len_beats[0] - 1.0:
            kind = "hold"
            hold = min(b.hold_len_beats[1], max(b.hold_len_beats[0], round(o["sustain_beats"])))
        n = {"ref": o["id"], "kind": kind}
        if hold:
            n["hold_beats"] = hold
        notes.append(n)
        last = beat
    # one phrase per section, movement drifting with energy
    meter = analysis.get("meter", 4)
    phrases = []
    for s in analysis.get("sections", []):
        energy = s.get("energy_pct", 0.5)
        phrases.append({
            "start_bar": s["start_bar"], "end_bar": s["end_bar"],
            "texture": "stream" if energy > 0.7 else "steps",
            "movement": "drift_L_to_R", "crossover": b.crossover,
            "jump_density": b.jumps})
    return {"design_notes": "deterministic", "notes": notes, "phrases": phrases}
