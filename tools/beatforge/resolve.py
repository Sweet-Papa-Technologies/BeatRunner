"""resolve.py — turn designer events (refs) into timed beatmap events.

The designer NEVER emits a timestamp (REQ-CHART-02). Times enter the beatmap
only here, deterministically:
    onset ref  ->  that onset's `nearest_beat` (already 1/4-snapped, |snap|<=35ms)
    grid:<beat> ->  the beat literally
    hold_beats ->  beatmap `dur` (validated against a sustain candidate ±1 beat)

Anything carrying a numeric time/seconds field is rejected with a specific error,
so a hallucinated timestamp can never reach the map.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LANES = {"GAP", "BAR", "NOTE"}
_GRID_RE = re.compile(r"^grid:(\d+(?:\.\d+)?)$")
_ONSET_RE = re.compile(r"^[pms]\d+$")
# Fields that would smuggle a raw time into an event — forbidden (REQ-CHART-02).
_TIME_FIELDS = {"time", "t", "seconds", "sec", "ms", "start", "at", "timestamp"}


class ResolveError(ValueError):
    pass


@dataclass
class ResolvedEvent:
    beat: float
    type: str
    dur: float | None = None
    ref: str = ""
    salience: float = 0.0      # onset strength; grid-only = 0 (lowest, repaired first)
    snap_ms: float = 0.0       # |grid - onset time| in ms; 0 for grid refs
    is_onset: bool = False
    meta: dict = field(default_factory=dict)


def _onset_index(analysis: dict) -> dict[str, dict]:
    return {o["id"]: o for o in analysis.get("onsets", [])}


def resolve_events(design: dict, analysis: dict) -> list[ResolvedEvent]:
    """Resolve every designer event. Raises ResolveError on a raw timestamp, an
    unknown onset id, a bad lane, or a hold on a non-sustain candidate."""
    onsets = _onset_index(analysis)
    events = design.get("events")
    if not isinstance(events, list):
        raise ResolveError("designer output has no `events` array")

    out: list[ResolvedEvent] = []
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            raise ResolveError(f"event[{i}] must be an object")
        # REQ-CHART-02: reject any raw-time field outright.
        smuggled = _TIME_FIELDS & set(ev.keys())
        if smuggled:
            raise ResolveError(
                f"event[{i}] carries forbidden raw-time field(s) {sorted(smuggled)}; "
                "the designer may reference onsets/grid only, never times")
        ref = ev.get("ref")
        lane = ev.get("lane")
        if not isinstance(ref, str):
            raise ResolveError(f"event[{i}] missing string `ref`")
        if lane not in LANES:
            raise ResolveError(f"event[{i}].lane must be one of {sorted(LANES)}, got {lane!r}")

        hold = ev.get("hold_beats")
        if hold is not None and (not isinstance(hold, (int, float)) or hold <= 0):
            raise ResolveError(f"event[{i}].hold_beats must be a number > 0 when present")

        # --- resolve the ref to a beat ---
        gm = _GRID_RE.match(ref)
        if gm:
            beat = float(gm.group(1))
            re_ = ResolvedEvent(beat=beat, type=lane, ref=ref, salience=0.0,
                               snap_ms=0.0, is_onset=False)
        elif _ONSET_RE.match(ref):
            onset = onsets.get(ref)
            if onset is None:
                raise ResolveError(f"event[{i}].ref '{ref}' is not in the onset inventory")
            beat = float(onset["nearest_beat"])
            re_ = ResolvedEvent(
                beat=beat, type=lane, ref=ref,
                salience=float(onset.get("strength", 0.0)),
                snap_ms=abs(float(onset.get("snap_error_ms", 0.0))),
                is_onset=True,
                meta={"onset": onset})
        else:
            raise ResolveError(
                f"event[{i}].ref '{ref}' is neither an onset id nor grid:<beat>")

        # --- holds: must map to a sustain candidate ±1 beat ---
        if hold is not None:
            if not re_.is_onset or not re_.meta.get("onset", {}).get("sustain"):
                raise ResolveError(
                    f"event[{i}] has hold_beats but ref '{ref}' is not a sustain candidate")
            want = float(re_.meta["onset"].get("sustain_beats", 0.0))
            if abs(float(hold) - want) > 1.0 + 1e-6:
                raise ResolveError(
                    f"event[{i}] hold_beats={hold} differs from candidate sustain "
                    f"{want} by >1 beat")
            re_.dur = float(hold)
        out.append(re_)
    return out
