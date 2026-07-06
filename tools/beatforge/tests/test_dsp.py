"""DSP ground-truth tests (REQ-DSP-01..04). Runs on synthetic clips in-process
— no CLI, no Colab, no network."""
import numpy as np

from beatforge import config, dsp


def test_tempo_disambiguation_resolves_true_octave(click_wav):
    """REQ-DSP-02: a 120-BPM click must resolve to ~120, NOT its 60 or 240
    octave. The score table is emitted and the winner is flagged."""
    a = dsp.analyze_signal(click_wav(bpm=120.0, dur_s=16.0))
    assert abs(a["bpm"] - 120.0) < 3.0, a["bpm"]
    cands = a["tempo_candidates"]
    assert cands, "score table must be present"
    chosen = [c for c in cands if c.get("chosen")]
    assert len(chosen) == 1
    # the 60 and 240 octaves exist as candidates but must not win
    assert abs(chosen[0]["bpm"] - 120.0) < 3.0


def test_tempo_disambiguation_offbeat_track(click_wav):
    """A 90-BPM click resolves within the genre band, not half/double."""
    a = dsp.analyze_signal(click_wav(bpm=90.0, dur_s=16.0))
    assert abs(a["bpm"] - 90.0) < 4.0, a["bpm"]


def test_onset_snap_within_tolerance(click_wav):
    """REQ-DSP-03/04: detected onsets land within ±35ms of a grid line, and
    every onset's nearest_beat reproduces its time within |snap error|."""
    a = dsp.analyze_signal(click_wav(bpm=120.0, dur_s=16.0, subdiv=2))
    perc = [o for o in a["onsets"] if o["id"].startswith("p")]
    assert perc, "should detect percussive onsets"
    within = np.mean([abs(o["snap_error_ms"]) <= config.ONSET_SNAP_MAX_MS for o in perc])
    assert within >= 0.85, within
    bpm, off = a["bpm"], a["offset"]
    for o in a["onsets"]:
        grid_t = off + o["nearest_beat"] / bpm * 60
        assert abs((grid_t - o["time"]) * 1000 - (-o["snap_error_ms"])) < 1.0


def test_onset_count_sanity(click_wav):
    """REQ-DSP-04 sanity gate: onset count in a sane band for a short clip."""
    a = dsp.analyze_signal(click_wav(bpm=120.0, dur_s=32.0, subdiv=2))
    assert len(a["onsets"]) > 10


def test_analysis_is_deterministic(click_wav):
    """REQ-DSP-01/COMPUTE-04: same input -> byte-identical analysis."""
    p = click_wav(bpm=128.0, dur_s=12.0)
    import json
    a1 = json.dumps(dsp.analyze_signal(p), sort_keys=True)
    a2 = json.dumps(dsp.analyze_signal(p), sort_keys=True)
    assert a1 == a2


def test_energy_curve_length_equals_bar_count(click_wav):
    """REQ-DSP-05: per-bar energy array length equals the bar count."""
    a = dsp.analyze_signal(click_wav(bpm=120.0, dur_s=16.0))
    total_bars = sum(s["end_bar"] - s["start_bar"] for s in a["sections"])
    assert len(a["energy_curve"]) == total_bars
