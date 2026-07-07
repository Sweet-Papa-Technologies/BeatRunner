"""STEPFORGE adapter tests (STEPMANIA.SPEC.MD / ORIGINAL DOC §11). Offline: no
Vertex, no Colab, no StepMania runtime. The highest-value tests are the foot-flow
realizer (synthetic streams with known-optimal panelings) and legality."""
import io

import pytest
import simfile

from beatforge.adapters.base import NullAdapter, TargetAdapter
from beatforge.adapters.stepmania.adapter import StepManiaAdapter
from beatforge.adapters.stepmania.grammar import BUDGETS, PANELS
from beatforge.adapters.stepmania.difficulty import compute_meter
from beatforge.adapters.stepmania.quantize import (Placement, snap_beat,
                                                  to_simfile_notes)
from beatforge.adapters.stepmania.realize import ResolvedNote, realize, decide_jumps
from beatforge.adapters.stepmania.resolve import IntentError, resolve_intent
from beatforge.adapters.stepmania.serialize import build_simfile
from beatforge.adapters.stepmania.validate import validate_repair
from beatforge.adapters.stepmania import footflow as ff


# ---- REQ-ARCH-01: adapter isolation ---- #
def test_null_and_stepmania_satisfy_protocol():
    assert isinstance(NullAdapter(), TargetAdapter)
    assert isinstance(StepManiaAdapter(), TargetAdapter)


# ---- REQ-SM-01: beat -> row quantization ---- #
def test_snap_to_subdivision():
    assert float(snap_beat(8.26, 0.25)) == 8.25
    assert float(snap_beat(8.3, 0.5)) == 8.5


def test_triplet_and_16th_render_to_right_resolution():
    trip = [Placement(4 + i / 3, (i % 4,)) for i in range(3)]
    body = str(to_simfile_notes(trip, 1 / 3))
    assert body.split(",")[1].count("\n") in (12, 13)     # a triplet measure -> 12ths
    sixteenth = [Placement(4 + i * 0.25, (i % 4,)) for i in range(4)]
    body16 = str(to_simfile_notes(sixteenth, 0.25))
    assert "1" in body16


# ---- REQ-SM-03: realizer alternation + crossover budget ---- #
def test_eighth_stream_strict_alternation_zero_double_steps():
    notes = [ResolvedNote(beat=4 + i * 0.5, phrase={"movement": "static"}) for i in range(16)]
    out = realize(notes, BUDGETS["medium"])
    feet = [p.meta["foot"] for p in out]
    assert all(feet[i] != feet[i - 1] for i in range(1, len(feet)))   # strict alternation


def test_no_crossover_budget_forbids_crossed_feet():
    notes = [ResolvedNote(beat=4 + i * 0.5, phrase={"movement": "zigzag"}) for i in range(16)]
    out = realize(notes, BUDGETS["easy"])   # crossover: none
    # re-walk feet; a crossover would put left foot physically right of right foot
    l, r = 0, 3
    for p in out:
        foot = p.meta["foot"]
        if foot == ff.LEFT:
            l = p.panels[0]
        else:
            r = p.panels[0]
        assert ff.PANEL_POS[l][0] <= ff.PANEL_POS[r][0] + 1e-9


# ---- REQ-SM-04: foot-flow validator + repair ---- #
def test_nps_thinning_keeps_whole_chart():
    notes = [ResolvedNote(beat=4 + i * 0.25) for i in range(120)]
    out = realize(notes, BUDGETS["easy"])
    a = {"bpm": 120.0, "offset": 0.1, "duration_s": 40.0, "onsets": []}
    rr = validate_repair(out, a, "easy")
    beats = [p.beat for p in rr.placements]
    assert beats[0] < 8 and beats[-1] > 25 and len(rr.placements) > 20


def test_clean_chart_zero_repairs():
    notes = [ResolvedNote(beat=4 + i * 1.0) for i in range(16)]   # quarters, sparse
    out = realize(notes, BUDGETS["medium"])
    a = {"bpm": 120.0, "offset": 0.1, "duration_s": 40.0, "onsets": []}
    rr = validate_repair(out, a, "medium")
    assert rr.original - len(rr.placements) == 0 and rr.ok


# ---- REQ-SM-05/06: intent parsing, no timestamps/panels, closed vocab ---- #
def _analysis():
    onsets = [{"id": f"p{i:03d}", "nearest_beat": float(4 + i), "snap_error_ms": 3.0,
               "strength": 0.6, "bands": {"low": 0.6, "mid": 0.25, "high": 0.15},
               "sustain": False, "sustain_beats": 0.0} for i in range(40)]
    return {"bpm": 120.0, "offset": 0.1, "duration_s": 40.0, "meter": 4,
            "onsets": onsets, "sections": [], "energy_curve": []}


def test_reject_raw_time():
    with pytest.raises(IntentError, match="raw-time"):
        resolve_intent({"notes": [{"ref": "p000", "kind": "tap", "row": 12}]}, _analysis(), "medium")


def test_reject_panel_in_intent():
    with pytest.raises(IntentError, match="realizer assigns panels"):
        resolve_intent({"notes": [{"ref": "p000", "kind": "tap", "panel": "L"}]}, _analysis(), "medium")


def test_reject_freestyle_texture():
    d = {"notes": [{"ref": "p000", "kind": "tap"}],
         "phrases": [{"start_bar": 0, "end_bar": 4, "texture": "freestyle"}]}
    with pytest.raises(IntentError, match="closed vocabulary"):
        resolve_intent(d, _analysis(), "medium")


# ---- REQ-SM-07/11: serialize round-trips through simfile ---- #
def test_serialize_round_trips_through_simfile():
    placements = {"medium": (5, [Placement(4 + i * 0.5, (i % 4,)) for i in range(16)])}
    a = {"bpm": 128.0, "offset": 0.176, "sections": [], "duration_s": 33.0}
    meta = {"title": "T", "artist": "A", "music": "t.ogg"}
    sf = build_simfile(meta, a, placements, ssc=True)
    reopened = simfile.load(io.StringIO(str(sf)))
    assert reopened.title == "T"
    assert reopened.offset == "-0.176" and "128.000" in reopened.bpms
    assert len(reopened.charts) == 1 and reopened.charts[0].stepstype == "dance-single"


# ---- REQ-SM-09: meter monotonic ---- #
def test_meter_monotonic_by_construction():
    notes = [Placement(4 + i * 0.25, (i % 4,)) for i in range(80)]
    me = compute_meter(notes, 120.0, "easy")
    mm = compute_meter(notes, 120.0, "medium")
    mh = compute_meter(notes, 120.0, "hard")
    assert me <= mm <= mh
