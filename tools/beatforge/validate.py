"""validate.py — Workstream D deterministic validation + repair (REQ-VAL-01..03).

Three layers:
  1. parse_beatmap_py  — schema parity with src/core/beatmap.ts parseBeatmap
                         (the TS core is the final referee; Node re-parses too).
  2. grid/snap integrity — legal subdivision per difficulty, |snap|<=35ms for
                         onset refs, drop events outside the playable window.
  3. ergonomic lint + salience repair — enforce the difficulty budget table by
                         removing the lowest-salience offending notes, re-lint;
                         if >15% get repaired away the chart FAILS (re-prompt).
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config
from .resolve import ResolvedEvent

EVENT_TYPES = ("GAP", "BAR", "NOTE")
_EPS = 1e-6


class BeatmapError(ValueError):
    """Mirror of src/core/beatmap.ts BeatmapError."""


class RepairExceeded(RuntimeError):
    """Raised when >MAX_REPAIR_FRACTION of events had to be repaired away."""
    def __init__(self, msg: str, report: dict):
        super().__init__(msg)
        self.report = report


# --------------------------------------------------------------------------- #
# 1. Schema parity with src/core/beatmap.ts parseBeatmap (REQ-VAL-01)
# --------------------------------------------------------------------------- #
def parse_beatmap_py(raw: dict) -> dict:
    """Semantics identical to parseBeatmap: validate types, sort events ascending
    by beat, de-dupe exact (beat,type) pairs, keep dur when > 0."""
    if not isinstance(raw, dict):
        raise BeatmapError("beat-map must be an object")
    track = raw.get("track")
    if not isinstance(track, str) or not track:
        raise BeatmapError("`track` must be a non-empty string")
    bpm = raw.get("bpm")
    if not _is_num(bpm) or bpm <= 0:
        raise BeatmapError("`bpm` must be a number > 0")
    offset = raw.get("offset")
    if not _is_num(offset) or offset < 0:
        raise BeatmapError("`offset` must be a number >= 0")
    events = raw.get("events")
    if not isinstance(events, list):
        raise BeatmapError("`events` must be an array")

    parsed = []
    for i, e in enumerate(events):
        if not isinstance(e, dict):
            raise BeatmapError(f"event[{i}] must be an object")
        beat = e.get("beat")
        if not _is_num(beat) or beat < 0:
            raise BeatmapError(f"event[{i}].beat must be a number >= 0")
        typ = e.get("type")
        if typ not in EVENT_TYPES:
            raise BeatmapError(f"event[{i}].type must be one of {'|'.join(EVENT_TYPES)}")
        dur = e.get("dur")
        if dur is not None:
            if not _is_num(dur) or dur <= 0:
                raise BeatmapError(f"event[{i}].dur must be a number > 0 when present")
            parsed.append({"beat": beat, "type": typ, "dur": dur})
        else:
            parsed.append({"beat": beat, "type": typ})

    parsed.sort(key=lambda x: x["beat"])
    seen, out = set(), []
    for ev in parsed:
        key = (ev["beat"], ev["type"])
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return {"track": track, "bpm": bpm, "offset": offset, "events": out}


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def usable_sustain_count(analysis: dict, difficulty: str) -> int:
    """How many sustain candidates can legally become a hold at this difficulty.
    Must apply the SAME filters the designer sees (design._compact_analysis), or
    the gate would demand holds the designer was told are unavailable:
      * length reaches the hold-length floor within the ±1-beat tolerance,
      * grid position is legal at this difficulty's subdivision,
      * inside the playable window, snap within tolerance.
    A track whose sustains fail all of these has ZERO usable holds -> hold-share
    is exempted rather than made impossible."""
    b = config.BUDGETS[difficulty]
    lo = b.hold_len_beats[0]
    subdiv = b.finest_subdiv
    last_beat = ((analysis["duration_s"] - config.PLAYABLE_TAIL_S - analysis["offset"])
                 * analysis["bpm"] / 60.0)
    n = 0
    for o in analysis.get("onsets", []):
        if not o.get("sustain") or o.get("sustain_beats", 0) < lo - 1.0:
            continue
        beat = o["nearest_beat"]
        if abs(beat - round(beat / subdiv) * subdiv) > 1e-3:
            continue
        if beat < config.FIRST_PLAYABLE_BEAT or beat > last_beat:
            continue
        if abs(o.get("snap_error_ms", 0)) > config.ONSET_SNAP_MAX_MS:
            continue
        n += 1
    return n


# --------------------------------------------------------------------------- #
# 2 + 3. Grid/snap + ergonomic repair
# --------------------------------------------------------------------------- #
@dataclass
class ValidationResult:
    events: list          # beatmap events (dicts: beat,type,[dur])
    resolved: list        # surviving ResolvedEvent objects (carry onset provenance)
    repairs: list         # [{"reason":..,"ref":..,"beat":..}]
    dropped_window: int
    dropped_grid: int
    dropped_snap: int
    original_count: int


def _t(beat: float, bpm: float, offset: float) -> float:
    return offset + beat / bpm * 60.0


def _last_playable_beat(analysis: dict) -> float:
    dur = analysis["duration_s"]
    bpm, offset = analysis["bpm"], analysis["offset"]
    return ((dur - config.PLAYABLE_TAIL_S) - offset) * bpm / 60.0


def _on_subdivision(beat: float, subdiv: float) -> bool:
    q = round(beat / subdiv)
    return abs(beat - q * subdiv) <= 1e-3


def validate_and_repair(
    resolved: list[ResolvedEvent], analysis: dict, difficulty: str,
) -> ValidationResult:
    budget = config.BUDGETS[difficulty]
    bpm, offset = analysis["bpm"], analysis["offset"]
    last_beat = _last_playable_beat(analysis)
    original = len(resolved)
    repairs = []

    # --- 2. hard drops: window, subdivision, snap ---
    kept: list[ResolvedEvent] = []
    d_win = d_grid = d_snap = 0
    for e in resolved:
        if e.beat < config.FIRST_PLAYABLE_BEAT - _EPS or e.beat > last_beat + _EPS:
            d_win += 1
            repairs.append({"reason": "outside_playable_window", "ref": e.ref, "beat": e.beat})
            continue
        if not _on_subdivision(e.beat, budget.finest_subdiv):
            d_grid += 1
            repairs.append({"reason": "illegal_subdivision", "ref": e.ref, "beat": e.beat})
            continue
        if e.is_onset and e.snap_ms > config.ONSET_SNAP_MAX_MS + _EPS:
            d_snap += 1
            repairs.append({"reason": "snap_gt_35ms", "ref": e.ref, "beat": e.beat,
                            "snap_ms": e.snap_ms})
            continue
        kept.append(e)

    # --- clamp hold lengths into the difficulty band (repair, not drop) ---
    lo_h, hi_h = budget.hold_len_beats
    for e in kept:
        if e.dur is not None:
            clamped = min(hi_h, max(lo_h, e.dur))
            if abs(clamped - e.dur) > _EPS:
                repairs.append({"reason": "hold_len_clamped", "ref": e.ref,
                                "from": e.dur, "to": clamped})
                e.dur = clamped

    # --- 3. iterative ergonomic repair (remove lowest-salience offender) ---
    kept = _dedupe_same_beat(kept, repairs)
    kept = _repair_loop(kept, budget, bpm, offset, repairs)

    kept_sorted = sorted(kept, key=lambda e: (e.beat, e.type))
    events = [_to_event(e) for e in kept_sorted]

    result = ValidationResult(
        events=events, resolved=kept_sorted, repairs=repairs,
        dropped_window=d_win, dropped_grid=d_grid, dropped_snap=d_snap,
        original_count=original)

    repaired_fraction = (original - len(events)) / original if original else 0.0
    if repaired_fraction > config.MAX_REPAIR_FRACTION:
        raise RepairExceeded(
            f"{repaired_fraction:.0%} of events repaired away (>{config.MAX_REPAIR_FRACTION:.0%}); "
            f"chart fails, triggering re-prompt",
            report=_repair_report(result))
    return result


def _to_event(e: ResolvedEvent) -> dict:
    ev = {"beat": round(e.beat, 3), "type": e.type}
    if e.dur is not None:
        ev["dur"] = round(e.dur, 3)
    return ev


def _dedupe_same_beat(events: list[ResolvedEvent], repairs: list) -> list[ResolvedEvent]:
    """Chords never allowed: at most one event per beat. Keep highest salience."""
    by_beat: dict[float, ResolvedEvent] = {}
    for e in sorted(events, key=lambda x: -x.salience):
        key = round(e.beat, 3)
        if key in by_beat:
            repairs.append({"reason": "chord_same_beat", "ref": e.ref, "beat": e.beat})
        else:
            by_beat[key] = e
    return sorted(by_beat.values(), key=lambda e: e.beat)


def _repair_loop(events, budget, bpm, offset, repairs, guard_max=5000):
    guard = 0
    while guard < guard_max:
        guard += 1
        events = sorted(events, key=lambda e: e.beat)
        offender = (_find_min_gap(events, budget, bpm, offset)
                    or _find_jack(events, budget)
                    or _find_nps(events, budget, bpm, offset)
                    or _find_hold_tap(events, budget, bpm, offset))
        if offender is None:
            break
        idx, reason = offender
        repairs.append({"reason": reason, "ref": events[idx].ref, "beat": events[idx].beat})
        events.pop(idx)
    return events


def _find_min_gap(events, budget, bpm, offset):
    """Consecutive events too close in beats OR ms -> drop lower-salience one."""
    for i in range(1, len(events)):
        a, b = events[i - 1], events[i]
        dbeat = b.beat - a.beat
        dms = (_t(b.beat, bpm, offset) - _t(a.beat, bpm, offset)) * 1000.0
        if dbeat < budget.min_gap_beats - _EPS or dms < budget.min_gap_ms - _EPS:
            drop = i - 1 if a.salience <= b.salience else i
            return drop, "min_gap"
    return None


def _find_jack(events, budget):
    """Same-lane consecutive run longer than the jack limit -> drop weakest in run."""
    run_start = 0
    for i in range(1, len(events) + 1):
        if i < len(events) and events[i].type == events[run_start].type:
            continue
        run = events[run_start:i]
        if len(run) > budget.jack_limit:
            weakest = min(range(run_start, i), key=lambda k: events[k].salience)
            return weakest, "jack_limit"
        run_start = i
    return None


def _find_nps(events, budget, bpm, offset):
    """Any 4s window exceeding max NPS -> drop the weakest note in that window."""
    if not events:
        return None
    times = [_t(e.beat, bpm, offset) for e in events]
    win = 4.0
    for i in range(len(events)):
        j = i
        while j < len(events) and times[j] - times[i] < win:
            j += 1
        count = j - i
        if count / win > budget.max_nps_4s + _EPS:
            weakest = min(range(i, j), key=lambda k: events[k].salience)
            return weakest, "nps_4s"
    return None


def _find_hold_tap(events, budget, bpm, offset):
    """Hold-span rules:
      * a tap on the SAME lane as an active hold is UNPLAYABLE (you're already
        holding that lane) -> always remove it, regardless of difficulty;
      * taps in OTHER lanes during the hold must not exceed the budget's allowed
        count (0/1/2) -> drop the weakest offender.
    """
    holds = [(i, e) for i, e in enumerate(events) if e.dur]
    for hi, hold in holds:
        h0 = hold.beat
        h1 = hold.beat + hold.dur
        overlap_lanes = {}
        for k, e in enumerate(events):
            if k == hi or e.dur:
                continue
            if not (h0 - _EPS < e.beat < h1 - _EPS):
                continue
            if e.type == hold.type:
                return k, "tap_on_held_lane"   # unplayable, remove immediately
            overlap_lanes.setdefault(e.type, []).append(k)
        if len(overlap_lanes) > budget.taps_during_hold:
            all_idx = [k for ks in overlap_lanes.values() for k in ks]
            weakest = min(all_idx, key=lambda k: events[k].salience)
            return weakest, "taps_during_hold"
    return None


def _repair_report(result: ValidationResult) -> dict:
    from collections import Counter
    reasons = Counter(r["reason"] for r in result.repairs)
    return {
        "original": result.original_count,
        "kept": len(result.events),
        "repaired": result.original_count - len(result.events),
        "reasons": dict(reasons),
    }
