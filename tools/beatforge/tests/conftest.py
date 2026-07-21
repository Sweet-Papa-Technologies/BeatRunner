"""Shared fixtures for beatforge tests — all offline, deterministic, no network,
and (per spec §9) NO Colab runtime is ever provisioned."""
from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from beatforge import config


@pytest.fixture(autouse=True)
def _isolate_cost_ledger(tmp_path, monkeypatch):
    """Keep test runs out of the repo's real build/cost/ ledgers. Any test that
    exercises a client without an explicit `ledger.capture()` still writes a
    ledger line — by design (REQ-R2-COST-01: nothing goes unrecorded) — so it has
    to land somewhere disposable, not in the artifact a cost report reads."""
    monkeypatch.setattr(config, "COST_DIR", tmp_path / "cost")


@pytest.fixture
def click_wav(tmp_path):
    """Factory: a synthetic click track at a known BPM (impulses on every beat +
    softer off-beats) so tempo disambiguation has an unambiguous ground truth."""
    def _make(bpm=120.0, dur_s=16.0, sr=22050, offset=0.0, subdiv=1):
        n = int(dur_s * sr)
        y = np.zeros(n, dtype=np.float32)
        period = 60.0 / bpm / subdiv
        t = offset
        i = 0
        while t < dur_s - 0.01:
            idx = int(t * sr)
            # short decaying blip
            L = int(0.02 * sr)
            env = np.exp(-np.linspace(0, 8, L))
            tone = np.sin(2 * np.pi * 1200 * np.arange(L) / sr) * env
            amp = 1.0 if (i % subdiv == 0) else 0.4
            y[idx:idx + L] += (amp * tone)[:max(0, min(L, n - idx))]
            t += period
            i += 1
        y = y / (np.max(np.abs(y)) or 1.0)
        path = tmp_path / f"click_{int(bpm)}.wav"
        sf.write(path, y, sr)
        return str(path)
    return _make


@pytest.fixture
def make_analysis():
    """Factory for a minimal but schema-valid analysis dict with N onsets on a
    grid, some sustain candidates, sections and an energy curve."""
    def _make(bpm=120.0, offset=0.1, n_onsets=40, n_sustain=4, energy_cv=0.2):
        onsets = []
        for i in range(n_onsets):
            beat = 4 + i  # one per beat starting at beat 4
            onsets.append({
                "id": f"p{i:03d}", "time": round(offset + beat / bpm * 60, 4),
                "nearest_beat": float(beat), "snap_error_ms": 5.0,
                "strength": 0.5 + 0.5 * (i % 3) / 2,
                "bands": {"low": 0.6, "mid": 0.25, "high": 0.15},
                "source": "mix_perc", "sustain": False, "sustain_beats": 0.0,
            })
        for j in range(n_sustain):
            beat = 8 + j * 8
            onsets.append({
                "id": f"s{j:03d}", "time": round(offset + beat / bpm * 60, 4),
                "nearest_beat": float(beat), "snap_error_ms": 3.0, "strength": 0.7,
                "bands": {"low": 0.2, "mid": 0.5, "high": 0.3},
                "source": "harmonic_sustain", "sustain": True, "sustain_beats": 4.0,
            })
        # energy curve with the requested contrast
        bars = 16
        base = np.linspace(0.4, 1.0, bars)
        curve = list(np.round(base, 3))
        return {
            "schema_version": "test", "track_id": "t", "track_file": "t.ogg",
            "duration_s": 32.0, "sample_rate": config.ANALYSIS_SR, "bpm": bpm,
            "offset": offset, "meter": 4, "beat_backend": "local_dsp",
            "stem_source": "none",
            "beats": [round(offset + b / bpm * 60, 4) for b in range(64)],
            "downbeat_indices": list(range(0, 64, 4)),
            "onsets": onsets, "sustain_available": n_sustain,
            "sections": [
                {"name": "S0", "start_bar": 0, "end_bar": 4, "energy_pct": 0.4,
                 "role_guess": "intro", "heuristic": True},
                {"name": "S1", "start_bar": 4, "end_bar": 12, "energy_pct": 0.9,
                 "role_guess": "drop", "heuristic": True},
                {"name": "S2", "start_bar": 12, "end_bar": 16, "energy_pct": 0.5,
                 "role_guess": "outro", "heuristic": True},
            ],
            "energy_curve": curve, "energy_cv": energy_cv,
        }
    return _make
