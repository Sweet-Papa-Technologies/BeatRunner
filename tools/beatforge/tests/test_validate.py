"""Validation, ergonomic lint + salience repair, schema parity
(REQ-VAL-01/02/03)."""
import pytest

from beatforge import config
from beatforge.resolve import ResolvedEvent
from beatforge.validate import (BeatmapError, RepairExceeded, _dedupe_same_beat,
                               _repair_loop, parse_beatmap_py, validate_and_repair)


def _pad(a, n=14, start=8.0):
    """Well-spaced legal filler onsets so a single targeted repair stays under the
    15% global cap and doesn't itself trip a budget rule."""
    return [_ev(start + i * 2.0, ["GAP", "BAR", "NOTE"][i % 3], sal=0.9)
            for i in range(n)]


# ---- REQ-VAL-01 schema parity with src/core/beatmap.ts ---- #
def test_parse_beatmap_sorts_and_dedupes():
    raw = {"track": "t.ogg", "bpm": 120, "offset": 0.1, "events": [
        {"beat": 8, "type": "BAR"}, {"beat": 4, "type": "GAP"},
        {"beat": 8, "type": "BAR"},  # exact dup -> removed
        {"beat": 8, "type": "NOTE"},  # same beat, diff type -> kept
    ]}
    out = parse_beatmap_py(raw)
    assert [e["beat"] for e in out["events"]] == [4, 8, 8]
    assert sum(1 for e in out["events"] if e["beat"] == 8) == 2


def test_parse_beatmap_rejects_bad_fields():
    with pytest.raises(BeatmapError):
        parse_beatmap_py({"track": "", "bpm": 120, "offset": 0, "events": []})
    with pytest.raises(BeatmapError):
        parse_beatmap_py({"track": "t", "bpm": 0, "offset": 0, "events": []})
    with pytest.raises(BeatmapError):
        parse_beatmap_py({"track": "t", "bpm": 120, "offset": -1, "events": []})
    with pytest.raises(BeatmapError):
        parse_beatmap_py({"track": "t", "bpm": 120, "offset": 0,
                          "events": [{"beat": 1, "type": "X"}]})
    with pytest.raises(BeatmapError):
        parse_beatmap_py({"track": "t", "bpm": 120, "offset": 0,
                          "events": [{"beat": 1, "type": "BAR", "dur": 0}]})


def _ev(beat, typ="BAR", sal=0.5, dur=None, ref="p", onset=True, snap=5.0):
    return ResolvedEvent(beat=beat, type=typ, dur=dur, ref=f"{ref}{beat}",
                         salience=sal, snap_ms=snap, is_onset=onset,
                         meta={"onset": {"sustain": dur is not None,
                                         "sustain_beats": dur or 0}})


# ---- REQ-VAL-02 grid/snap integrity (padded so 1 drop stays < 15%) ---- #
def test_drops_events_outside_playable_window(make_analysis):
    a = make_analysis()
    evs = _pad(a) + [_ev(1.0), _ev(999.0)]  # too early / too late
    vr = validate_and_repair(evs, a, "standard")
    beats = [e["beat"] for e in vr.events]
    assert 1.0 not in beats and 999.0 not in beats and 8.0 in beats


def test_drops_illegal_subdivision(make_analysis):
    a = make_analysis()
    vr = validate_and_repair(_pad(a) + [_ev(9.5)], a, "casual")  # 9.5 illegal at casual
    assert 9.5 not in [e["beat"] for e in vr.events]


def test_drops_bad_snap_onsets(make_analysis):
    a = make_analysis()
    vr = validate_and_repair(_pad(a) + [_ev(41.0, snap=80.0)], a, "standard")
    assert 41.0 not in [e["beat"] for e in vr.events]


# ---- REQ-VAL-03 ergonomic detectors tested directly (no global 15% cap) ---- #
def test_chord_same_beat_dedupe_keeps_strongest():
    repairs = []
    out = _dedupe_same_beat([_ev(8.0, "BAR", sal=0.2), _ev(8.0, "NOTE", sal=0.9)], repairs)
    assert len(out) == 1 and out[0].type == "NOTE"
    assert any(r["reason"] == "chord_same_beat" for r in repairs)


def test_jack_limit_repaired():
    b = config.BUDGETS["overdrive"]
    repairs = []
    evs = [_ev(8 + i * 1.0, "BAR", sal=0.1 + i * 0.05) for i in range(6)]
    out = _repair_loop(evs, b, 120.0, 0.1, repairs)
    lanes = [e.type for e in out]
    run = maxrun = 1
    for i in range(1, len(lanes)):
        run = run + 1 if lanes[i] == lanes[i - 1] else 1
        maxrun = max(maxrun, run)
    assert maxrun <= b.jack_limit
    assert any(r["reason"] == "jack_limit" for r in repairs)


def test_nps_burst_repaired():
    b = config.BUDGETS["overdrive"]  # max 7 nps/4s
    repairs = []
    # 40 notes at 0.25-beat spacing (125ms) => ~8 nps in a 4s window at 120bpm
    evs = [_ev(8 + i * 0.25, ["GAP", "BAR", "NOTE"][i % 3], sal=0.1 + i * 0.001)
           for i in range(40)]
    out = _repair_loop(evs, b, 120.0, 0.1, repairs)
    # after repair no 4s window exceeds the budget
    times = sorted(0.1 + e.beat / 120.0 * 60 for e in out)
    worst = max((sum(1 for t in times if ti <= t < ti + 4.0) / 4.0) for ti in times)
    assert worst <= b.max_nps_4s + 1e-6
    assert any(r["reason"] == "nps_4s" for r in repairs)


def test_tap_during_hold_repaired():
    b = config.BUDGETS["casual"]  # 0 taps allowed during a hold
    repairs = []
    hold = _ev(8.0, "BAR", dur=4.0)
    taps = [_ev(9.0, "GAP", sal=0.1), _ev(10.0, "NOTE", sal=0.1)]
    out = _repair_loop([hold, *taps], b, 120.0, 0.1, repairs)
    assert any(r["reason"] == "taps_during_hold" for r in repairs)
    # the hold survives; offending taps are thinned to the allowance
    assert any(e.dur for e in out)


def test_tap_on_held_lane_always_removed():
    """A tap on the SAME lane as an active hold is unplayable and must be removed
    at every difficulty, even overdrive which otherwise allows taps during holds."""
    b = config.BUDGETS["overdrive"]  # allows 2 other-lane taps during a hold
    repairs = []
    hold = _ev(8.0, "BAR", dur=4.0)
    same_lane = _ev(9.0, "BAR", sal=0.9)   # tap on the held lane
    out = _repair_loop([hold, same_lane], b, 120.0, 0.1, repairs)
    assert any(r["reason"] == "tap_on_held_lane" for r in repairs)
    # the held lane has no tap inside the hold span anymore
    inside = [e for e in out if not e.dur and e.type == "BAR" and 8.0 < e.beat < 12.0]
    assert not inside


def test_repair_exceeded_triggers_failure(make_analysis):
    a = make_analysis()
    # everything crammed at illegal subdivisions -> >15% repaired -> raise
    evs = [_ev(8 + i * 0.1, "BAR") for i in range(30)]
    with pytest.raises(RepairExceeded):
        validate_and_repair(evs, a, "casual")


def test_hold_length_clamped_into_band(make_analysis):
    a = make_analysis()
    vr = validate_and_repair([_ev(8.0, "GAP", dur=20.0)], a, "standard")  # max 8
    held = [e for e in vr.events if e.get("dur")]
    assert held and held[0]["dur"] <= config.BUDGETS["standard"].hold_len_beats[1]
