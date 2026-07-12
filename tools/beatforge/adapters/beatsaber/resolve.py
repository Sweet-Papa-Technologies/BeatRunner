"""resolve.py — designer INTENT -> ResolvedNotes, plus a deterministic intent
generator for the no-LLM path (SABERFORGE spec §6, REQ-BS-05).

The designer emits WHICH onsets are notes, each note's KIND (note/arc/chain/
bomb_reset), a HAND (left/right/either), and per-phrase FEEL from a CLOSED
vocabulary. It NEVER emits grid coordinates, cut directions, parity, or a raw
time — those are rejected here with specific errors. Geometry comes later from
the parity realizer.
"""
from __future__ import annotations

import re

from ... import config
from .grammar import BUDGETS, HANDS, OBJECT_KINDS
from .realize import ResolvedNote, _energy_at

_GRID_RE = re.compile(r"^grid:(\d+(?:\.\d+)?)$")
_ONSET_RE = re.compile(r"^[pms]\d+$")
# Anything that would let the model place geometry or a raw time is rejected —
# the anti-hallucination contract (spec §3, mirrors the StepMania adapter).
_TIME_KEYS = {"time", "t", "row", "seconds", "sec", "ms", "beat", "at", "b"}
_COORD_KEYS = {"x", "y", "d", "c", "cutdir", "cut_direction", "direction",
               "angle", "a", "color", "colour", "col", "column", "cols",
               "columns", "lane", "parity", "line_index", "line_layer"}

# Closed phrase vocabularies (spec §6) — anything else is a validation error.
DENSITIES = ("sparse", "steady", "driving", "burst")
MOVEMENTS = ("static", "lean_in", "lean_out", "sweep")
TECHS = ("flowy", "tech", "streamy")
HAND_BALANCES = ("even", "left_lead", "right_lead")


class IntentError(ValueError):
    pass


def _playable(analysis: dict):
    bpm, offset = analysis["bpm"], analysis["offset"]
    last = (analysis["duration_s"] - config.PLAYABLE_TAIL_S - offset) * bpm / 60.0
    return config.FIRST_PLAYABLE_BEAT, last


def _onset_lookup(analysis: dict) -> dict:
    """Onset id -> onset, tolerant of dropped zero-padding / casing."""
    lut = {}
    for o in analysis.get("onsets", []):
        oid = o["id"]
        lut[oid] = o
        lut[oid.lower()] = o
        m = re.match(r"^([pms])0*(\d+)$", oid)
        if m:
            lut[f"{m.group(1)}{int(m.group(2))}"] = o
    return lut


def _phrase_for(beat: float, phrases: list, meter: int) -> dict:
    bar = beat / meter
    for ph in phrases:
        if ph["start_bar"] - 1e-9 <= bar < ph["end_bar"] + 1e-9:
            return ph
    return {"density": "steady", "movement": "static", "tech": "flowy",
            "hand_balance": "even", "emphasis": "kick+snare"}


def _resolve_ref(ref, onsets, lo_beat, hi_beat, idx, label="ref"):
    if not isinstance(ref, str):
        raise IntentError(f"note[{idx}] missing string `{label}`")
    gm = _GRID_RE.match(ref)
    if gm:
        return float(gm.group(1))
    if _ONSET_RE.match(ref):
        o = onsets.get(ref) or onsets.get(ref.lower())
        if o is None:
            raise IntentError(f"note[{idx}].{label} '{ref}' not in onset inventory")
        return float(o["nearest_beat"])
    raise IntentError(f"note[{idx}].{label} '{ref}' is neither an onset id nor grid:<beat>")


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
        if keys & _COORD_KEYS:
            raise IntentError(f"note[{i}] specifies geometry {sorted(keys & _COORD_KEYS)}; "
                              "the parity realizer assigns coordinates/cut directions, not the designer")

        kind = ev.get("kind", "note")
        if kind not in OBJECT_KINDS:
            kind = "note"
        hand = ev.get("hand", "either")
        if hand not in HANDS:
            raise IntentError(f"note[{i}].hand '{hand}' not in {list(HANDS)}")

        if kind == "bomb_reset":
            # a bomb reset telegraphs a parity break; it references a beat too.
            beat = _resolve_ref(ev.get("ref"), onsets, lo_beat, hi_beat, i)
            if lo_beat - 1e-6 <= beat <= hi_beat + 1e-6:
                out.append(ResolvedNote(beat=beat, hand=hand, kind="bomb_reset",
                                        phrase=_phrase_for(beat, phrases, meter)))
            continue

        beat = _resolve_ref(ev.get("ref"), onsets, lo_beat, hi_beat, i)
        if beat < lo_beat - 1e-6 or beat > hi_beat + 1e-6:
            continue
        tail_beat = None
        if kind == "arc":
            if "tail_ref" not in ev:
                raise IntentError(f"note[{i}] kind=arc needs a `tail_ref`")
            tail_beat = _resolve_ref(ev["tail_ref"], onsets, lo_beat, hi_beat, i, "tail_ref")
            if tail_beat <= beat:
                raise IntentError(f"note[{i}] arc tail must come after its head")
        slices = None
        if kind == "chain":
            slices = ev.get("slices", 3)
            if not isinstance(slices, int) or not (2 <= slices <= 8):
                raise IntentError(f"note[{i}] chain `slices` must be an int in 2..8")
        out.append(ResolvedNote(beat=beat, hand=hand, kind=kind, tail_beat=tail_beat,
                                slices=slices, phrase=_phrase_for(beat, phrases, meter)))
    out.sort(key=lambda n: n.beat)
    return out


def _validate_phrases(phrases: list) -> list:
    for ph in phrases:
        for field_name, vocab in (("density", DENSITIES), ("movement", MOVEMENTS),
                                  ("tech", TECHS), ("hand_balance", HAND_BALANCES)):
            v = ph.get(field_name)
            if v is not None and v not in vocab:
                raise IntentError(f"phrase {field_name} '{v}' not in closed vocabulary {list(vocab)}")
    return phrases


# --------------------------------------------------------------------------- #
# Deterministic intent (no LLM) — select on-grid onsets, alternate hands,
# phrases from sections (spec §12 step 1-3: prove the rig before any model call).
# --------------------------------------------------------------------------- #
def deterministic_intent(analysis: dict, difficulty: str) -> dict:
    b = BUDGETS[difficulty]
    subdiv = b.finest_precision
    lo_beat, hi_beat = _playable(analysis)
    meter = analysis.get("meter", 4)

    # Energy-aware onset selection: the note spacing follows the song so the map
    # BREATHES in quiet sections and DRIVES in the drops. Density tracking energy
    # is what makes the chart dynamic instead of a uniform wall of notes.
    elig = []
    last = -99.0
    for o in sorted(analysis.get("onsets", []), key=lambda o: o["nearest_beat"]):
        beat = o["nearest_beat"]
        if beat < lo_beat or beat > hi_beat:
            continue
        if abs(beat - round(beat / subdiv) * subdiv) > 1e-3:
            continue
        if abs(o.get("snap_error_ms", 0)) > config.ONSET_SNAP_MAX_MS:
            continue
        if beat - last < 1e-3:                  # never two notes on the exact same beat
            continue
        gap = _energy_gap(_energy_at(analysis, beat, meter), subdiv)
        # always keep a strong downbeat even inside a sparse window (the pulse)
        is_downbeat = abs(beat - round(beat)) < 1e-3 and round(beat) % meter == 0
        if beat - last < gap - 1e-6 and not is_downbeat:
            continue
        elig.append(o)
        last = beat

    hand_cycle = ("left", "right")
    lo_ac, hi_ac = b.arc_chain_share
    arc_target = int(((lo_ac + hi_ac) / 2) * len(elig)) if hi_ac > 0 else 0
    doubles_cap = int(b.doubles_max_frac * len(elig))
    notes = []
    made_ac = 0
    doubles = 0
    for i, o in enumerate(elig):
        beat = o["nearest_beat"]
        energy = _energy_at(analysis, beat, meter)
        hand = hand_cycle[i % 2]
        n = {"ref": o["id"], "hand": hand, "kind": "note"}
        # arcs/chains toward the tier's share, preferring sustained onsets for arcs.
        if made_ac < arc_target and i + 1 < len(elig) and i % 4 == 0:
            if o.get("sustain") and o.get("sustain_beats", 0) >= 0.5:
                n["kind"] = "arc"
                n["tail_ref"] = elig[i + 1]["id"]
            else:
                n["kind"] = "chain"
                n["slices"] = 3
            made_ac += 1
        notes.append(n)
        # doubles: two-handed hits on strong downbeats in high-energy sections,
        # capped to the tier's budget — punch in the drops, never everywhere.
        accent = abs(beat - round(beat)) < 1e-3 and round(beat) % meter == 0
        if (b.doubles in ("accents", "free") and accent and energy > 0.8
                and n["kind"] == "note" and doubles < doubles_cap):
            notes.append({"ref": o["id"], "hand": "right" if hand == "left" else "left",
                          "kind": "note"})
            doubles += 1

    phrases = []
    for s in analysis.get("sections", []):
        energy = s.get("energy_pct", 0.5)
        phrases.append({
            "start_bar": s["start_bar"], "end_bar": s["end_bar"],
            "density": "driving" if energy > 0.75 else "steady" if energy > 0.45 else "sparse",
            "movement": "lean_in" if energy > 0.75 else "sweep" if energy > 0.45 else "static",
            "tech": "streamy" if energy > 0.7 else "tech" if energy > 0.5 else "flowy",
            "hand_balance": "even", "emphasis": "kick+snare"})
    return {"design_notes": "deterministic (energy-driven)", "notes": notes, "phrases": phrases}


def _energy_gap(energy: float, subdiv: float) -> float:
    """Minimum note spacing (beats) for a section's energy: dense in the drops,
    sparse in the quiet. Never finer than the tier subdivision."""
    if energy >= 0.8:
        gap = subdiv                    # full density; NPS cap thins if needed
    elif energy >= 0.6:
        gap = max(subdiv, 0.25)         # 16ths/8ths
    elif energy >= 0.45:
        gap = 0.5                       # 8ths
    elif energy >= 0.3:
        gap = 1.0                       # quarters
    else:
        gap = 2.0                       # half notes — breathe
    return max(subdiv, gap)
