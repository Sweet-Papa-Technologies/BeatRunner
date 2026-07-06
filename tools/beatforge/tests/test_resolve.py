"""Designer-output parsing tests (REQ-CHART-02: no raw timestamps)."""
import pytest

from beatforge.resolve import ResolveError, resolve_events


def test_rejects_raw_timestamp(make_analysis):
    """REQ-CHART-02: an event carrying a numeric time field is rejected with a
    specific error — a hallucinated timestamp can never reach the map."""
    a = make_analysis()
    design = {"events": [{"ref": "p000", "lane": "BAR", "time": 12.34}]}
    with pytest.raises(ResolveError, match="raw-time"):
        resolve_events(design, a)


def test_rejects_all_time_aliases(make_analysis):
    a = make_analysis()
    for field in ("t", "seconds", "ms", "timestamp", "at"):
        design = {"events": [{"ref": "p001", "lane": "GAP", field: 1.0}]}
        with pytest.raises(ResolveError):
            resolve_events(design, a)


def test_resolves_onset_ref_to_nearest_beat(make_analysis):
    a = make_analysis()
    design = {"events": [{"ref": "p005", "lane": "NOTE"}]}
    out = resolve_events(design, a)
    assert out[0].beat == 9.0  # p005 -> beat 4+5
    assert out[0].is_onset and out[0].type == "NOTE"


def test_resolves_grid_ref(make_analysis):
    a = make_analysis()
    out = resolve_events({"events": [{"ref": "grid:36.5", "lane": "BAR"}]}, a)
    assert out[0].beat == 36.5 and not out[0].is_onset and out[0].salience == 0.0


def test_unknown_onset_id_rejected(make_analysis):
    a = make_analysis()
    with pytest.raises(ResolveError, match="not in the onset inventory"):
        resolve_events({"events": [{"ref": "p999", "lane": "BAR"}]}, a)


def test_bad_lane_rejected(make_analysis):
    a = make_analysis()
    with pytest.raises(ResolveError, match="lane"):
        resolve_events({"events": [{"ref": "p000", "lane": "MIDDLE"}]}, a)


def test_hold_on_non_sustain_rejected(make_analysis):
    a = make_analysis()
    with pytest.raises(ResolveError, match="not a sustain candidate"):
        resolve_events({"events": [{"ref": "p000", "lane": "BAR", "hold_beats": 4}]}, a)


def test_hold_length_must_match_candidate(make_analysis):
    a = make_analysis()  # s000 sustain_beats=4.0
    # within ±1 beat is fine
    ok = resolve_events({"events": [{"ref": "s000", "lane": "GAP", "hold_beats": 5}]}, a)
    assert ok[0].dur == 5
    # >1 beat off is rejected
    with pytest.raises(ResolveError, match=">1 beat"):
        resolve_events({"events": [{"ref": "s000", "lane": "GAP", "hold_beats": 8}]}, a)
