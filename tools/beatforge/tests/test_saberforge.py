"""SABERFORGE adapter tests (BEATSABER.SPEC.MD §11). Offline: no Vertex, no Colab,
no external checkers, no Beat Saber runtime — the model/Colab/checkers live behind
fixtures. Highest-value: the parity realizer DP on synthetic streams with known
optimal parity, each legality rule, the swing simulator, intent parsing (no
coordinate/cutdir), difficulty monotonicity + NJS constancy, and JSMap round-trip.
"""
import json
import shutil

import pytest

from beatforge.adapters.base import NullAdapter, TargetAdapter
from beatforge.adapters.beatsaber.adapter import BeatSaberAdapter
from beatforge.adapters.beatsaber import difficulty as diffmod
from beatforge.adapters.beatsaber import parity as par
from beatforge.adapters.beatsaber import qa as bs_qa
from beatforge.adapters.beatsaber import serialize as ser
from beatforge.adapters.beatsaber import simulate as sim
from beatforge.adapters.beatsaber import validate as V
from beatforge.adapters.beatsaber.grammar import (BUDGETS, DIFFICULTIES, DOWN, UP,
                                                  SWING_VECTORS, angle_between,
                                                  swing_angle_deg)
from beatforge.adapters.beatsaber.realize import ResolvedNote, SaberObject, realize
from beatforge.adapters.beatsaber.resolve import (IntentError, deterministic_intent,
                                                  resolve_intent)


def _analysis(bpm=120.0, offset=0.1, n=40, dur=60.0):
    onsets = [{"id": f"p{i:03d}", "time": round(offset + (4 + i) / bpm * 60, 4),
               "nearest_beat": float(4 + i), "snap_error_ms": 3.0, "strength": 0.6,
               "bands": {"low": 0.6, "mid": 0.25, "high": 0.15}, "source": "x",
               "sustain": (i % 5 == 0), "sustain_beats": 2.0 if i % 5 == 0 else 0.0}
              for i in range(n)]
    return {"bpm": bpm, "offset": offset, "duration_s": dur, "meter": 4,
            "onsets": onsets,
            "sections": [{"name": "a", "start_bar": 0, "end_bar": 4, "energy_pct": 0.4},
                         {"name": "b", "start_bar": 4, "end_bar": 12, "energy_pct": 0.9}],
            "energy_curve": [0.4, 0.5, 0.9, 0.9, 0.7, 0.6, 0.5, 0.4]}


# ---- REQ-ARCH-01: adapter isolation ---- #
def test_null_and_beatsaber_satisfy_protocol():
    assert isinstance(NullAdapter(), TargetAdapter)
    assert isinstance(BeatSaberAdapter(), TargetAdapter)


# ---- REQ-BS-01: grammar / swing-vector math ---- #
def test_swing_vectors_and_angles():
    assert SWING_VECTORS[UP] == (0.0, 1.0)
    assert SWING_VECTORS[DOWN] == (0.0, -1.0)
    assert abs(angle_between(UP, DOWN) - 180.0) < 1e-6      # up vs down = 180°
    assert abs(swing_angle_deg(UP) - 90.0) < 1e-6


def test_grid_bounds_enforced_by_realizer():
    objs = realize([ResolvedNote(beat=4 + i * 0.5, hand="left") for i in range(8)],
                   _analysis(), "expert", BUDGETS["expert"])
    for o in objs:
        assert 0 <= o.x <= 3 and 0 <= o.y <= 2


# ---- REQ-BS-02: parity realizer (DP over swing state) ---- #
def test_single_hand_stream_strict_alternation_zero_resets():
    notes = [ResolvedNote(beat=4 + i * 0.5, hand="left",
                          phrase={"movement": "static", "tech": "flowy"}) for i in range(16)]
    objs = realize(notes, _analysis(), "expert", BUDGETS["expert"])
    assert not V.detect_resets(objs, BUDGETS["expert"])
    pars = [par.direction_parity(o.direction) for o in objs]
    assert all(pars[i] != pars[i - 1] for i in range(1, len(pars)))


def test_two_hand_no_opposite_swing_path_violation():
    notes = [ResolvedNote(beat=4 + i * 0.5, hand=("left" if i % 2 == 0 else "right"),
                          phrase={"movement": "sweep", "tech": "streamy"}) for i in range(24)]
    objs = realize(notes, _analysis(), "expert", BUDGETS["expert"])
    assert not V.detect_opposite_swing_path(objs)


def test_bomb_reset_inserts_a_bomb_with_lead_time():
    notes = [ResolvedNote(beat=4 + i * 0.5, hand="left") for i in range(6)]
    notes.insert(3, ResolvedNote(beat=5.4, hand="left", kind="bomb_reset"))
    objs = realize(notes, _analysis(), "hard", BUDGETS["hard"])
    bombs = [o for o in objs if o.kind == "bomb"]
    assert len(bombs) == 1 and bombs[0].meta.get("reset")


# ---- REQ-BS-03: legality validator + repair ---- #
def test_detect_and_repair_forced_reset():
    bad = [SaberObject(kind="note", beat=4 + i * 0.5, x=0, y=0, color=0, direction=DOWN)
           for i in range(4)]                             # all forehand = 3 resets
    assert V.detect_resets(bad, BUDGETS["expert"])
    rr = V.validate_repair(bad, _analysis(), "expert")
    assert not V.detect_resets(rr.objects, BUDGETS["expert"])   # repaired to alternate


def test_detect_parallel_same_color():
    stacked = [SaberObject(kind="note", beat=8.0, x=0, y=0, color=0, direction=UP),
               SaberObject(kind="note", beat=8.0, x=1, y=0, color=0, direction=DOWN)]
    assert V.detect_parallel_same_color(stacked)      # 180° apart on same snap


def test_detect_bomb_spacing_under_20ms():
    a = _analysis(bpm=120.0)
    close = [SaberObject(kind="bomb", beat=8.0, x=1, y=1),
             SaberObject(kind="bomb", beat=8.0 + 0.02, x=1, y=1)]  # ~10ms at 120bpm
    assert V.detect_bomb_spacing(close, a["bpm"], a["offset"])


def test_detect_over_angle_at_high_bpm():
    a = _analysis(bpm=180.0)
    # a natural reversal (up→down) is FREE — the easy back-and-forth motion.
    reversal = [SaberObject(kind="note", beat=8.0, x=0, y=0, color=0, direction=UP),
                SaberObject(kind="note", beat=8.0625, x=0, y=0, color=0, direction=DOWN)]
    assert not V.detect_angle(reversal, a["bpm"], BUDGETS["expert"])
    # a same-direction repeat (up→up) needs a full reset the time can't afford.
    repeat = [SaberObject(kind="note", beat=8.0, x=0, y=0, color=0, direction=UP),
              SaberObject(kind="note", beat=8.0625, x=0, y=0, color=0, direction=UP)]
    assert V.detect_angle(repeat, a["bpm"], BUDGETS["expert"])


# ---- REQ-BS-04: in-core swing simulator ---- #
def test_simulator_clean_on_realized_map_and_flags_bad_fixture():
    notes = [ResolvedNote(beat=4 + i * 0.5, hand=("left" if i % 2 == 0 else "right"))
             for i in range(24)]
    objs = realize(notes, _analysis(), "expert", BUDGETS["expert"])
    assert sim.simulate(objs, _analysis()).clean
    bad = [SaberObject(kind="note", beat=4 + i * 0.5, x=0, y=0, color=0, direction=DOWN)
           for i in range(6)]
    assert not sim.simulate(bad, _analysis()).clean


# ---- REQ-BS-05: intent parsing rejects coordinates / cutdirs / bad vocab / bad ref ---- #
def test_reject_coordinate_field():
    with pytest.raises(IntentError, match="geometry"):
        resolve_intent({"notes": [{"ref": "p000", "kind": "note", "x": 1}]}, _analysis(), "expert")


def test_reject_cutdir_field():
    with pytest.raises(IntentError, match="geometry"):
        resolve_intent({"notes": [{"ref": "p000", "kind": "note", "d": 3}]}, _analysis(), "expert")


def test_reject_raw_time_field():
    with pytest.raises(IntentError, match="raw-time"):
        resolve_intent({"notes": [{"ref": "p000", "kind": "note", "time": 4.0}]}, _analysis(), "expert")


def test_reject_unknown_vocab():
    d = {"notes": [{"ref": "p000", "kind": "note"}],
         "phrases": [{"start_bar": 0, "end_bar": 4, "tech": "wild"}]}
    with pytest.raises(IntentError, match="closed vocabulary"):
        resolve_intent(d, _analysis(), "expert")


def test_reject_unresolvable_ref():
    with pytest.raises(IntentError, match="not in onset inventory"):
        resolve_intent({"notes": [{"ref": "p999", "kind": "note"}]}, _analysis(), "expert")


# ---- REQ-BS-08: NJS constant per difficulty + monotonic difficulty ---- #
def test_njs_constant_and_monotonic():
    table = diffmod.njs_offset_table(DIFFICULTIES, 128.0)
    njs = [table[d][0] for d in DIFFICULTIES]
    assert njs == sorted(njs)                       # non-decreasing NJS
    assert diffmod.is_monotonic(DIFFICULTIES)
    # constant within a difficulty: same call, same value (locked)
    assert diffmod.compute_njs("expert", 128.0) == diffmod.compute_njs("expert", 128.0)


# ---- REQ-BS-10: objective QA metrics gates ---- #
def test_qa_metrics_and_gates_on_clean_chart():
    notes = [ResolvedNote(beat=4 + i * 0.5, hand="either",
                          phrase={"movement": "static"}) for i in range(24)]
    objs = realize(notes, _analysis(), "hard", BUDGETS["hard"])
    m = bs_qa.chart_metrics(objs, _analysis(), "hard")
    assert m["gates"]["hand_balance"] and m["gates"]["no_unforced_resets"]
    assert m["gates"]["simulator_clean"] and m["gates"]["nps_in_budget"]


# ---- REQ-BS-06 / REQ-POS-01 / REQ-POS-03: serialize round-trips through JSMap ---- #
@pytest.mark.skipif(not shutil.which("node"), reason="node/bsmap required for JSMap round-trip")
def test_serialize_round_trips_through_jsmap(tmp_path):
    a = _analysis()
    notes = [ResolvedNote(beat=4 + i * 0.5, hand=("left" if i % 2 == 0 else "right"))
             for i in range(24)]
    objs = realize(notes, a, "expert", BUDGETS["expert"])
    (tmp_path / "song.ogg").write_bytes(b"x")
    per = {"expert": {"difficulty": "Expert", "rank": 7, "njs": 16, "offset": 0,
                      "objects": objs, "lighting": []}}
    meta = {"title": "T", "artist": "A", "music": "song.ogg"}
    res = ser.write_song_folder(meta, a, per, str(tmp_path / "song.ogg"), tmp_path)
    assert res["verified"] and res["roundtrip_ok"]
    dat = json.loads((tmp_path / "ExpertStandard.dat").read_text())
    assert dat["version"].startswith("3.")
    assert all(k in dat for k in ("colorNotes", "bombNotes", "obstacles"))   # REQ-BS-06
    info = json.loads((tmp_path / "Info.dat").read_text())
    # REQ-POS-01: AI-assisted marker present in metadata
    assert ser.AI_MARKER in json.dumps(info)


def test_serialize_marker_present_in_fallback_without_node(tmp_path, monkeypatch):
    """REQ-POS-01: even the no-Node fallback carries the AI-assisted marker."""
    a = _analysis()
    objs = realize([ResolvedNote(beat=4 + i * 0.5, hand="left") for i in range(8)],
                   a, "hard", BUDGETS["hard"])
    per = {"hard": {"difficulty": "Hard", "rank": 5, "njs": 12, "offset": 0,
                    "objects": objs, "lighting": []}}
    monkeypatch.setattr(ser, "_run_jsmap", lambda p: None)   # force fallback
    (tmp_path / "song.ogg").write_bytes(b"x")
    res = ser.write_song_folder({"title": "T", "artist": "A", "music": "song.ogg"},
                                a, per, str(tmp_path / "song.ogg"), tmp_path)
    assert res["fallback"] and not res["verified"]
    info = json.loads((tmp_path / "Info.dat").read_text())
    assert ser.AI_MARKER in json.dumps(info)


# ---- REQ-POS-02: no BeatSaver upload/publish path anywhere in the package ---- #
def test_no_beatsaver_upload_path():
    import pathlib
    pkg = pathlib.Path(ser.__file__).resolve().parent
    for src in pkg.rglob("*.py"):
        text = src.read_text().lower()
        assert "beatsaver.com" not in text          # no publish endpoint anywhere
    for src in pkg.rglob("*.mjs"):
        assert "beatsaver.com" not in src.read_text().lower()


# ---- deterministic intent produces a realizable, simulate-clean draft ---- #
def test_deterministic_intent_realizes_clean():
    a = _analysis(n=48)
    design = deterministic_intent(a, "expert")
    objs = realize(resolve_intent(design, a, "expert"), a, "expert", BUDGETS["expert"])
    assert objs
    assert sim.simulate(objs, a).clean
