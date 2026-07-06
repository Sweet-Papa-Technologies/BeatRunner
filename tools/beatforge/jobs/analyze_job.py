#!/usr/bin/env python3
"""analyze_job.py — SELF-CONTAINED Colab GPU analysis payload (Workstream B,
higher-fidelity path). Shipped to a remote Colab kernel via `colab exec -f`,
which sends this file's *contents* — so it imports ONLY the pinned scientific
stack (requirements.lock), never `beatforge`.

Produces the SAME analysis.json schema as beatforge/dsp.py so downstream
(Workstreams C/D) is identical, but with the fidelity DSP that wants a GPU:
  * madmom DBN beat + downbeat tracking      -> beat_backend="madmom_dbn"
  * Demucs (htdemucs) stem separation on GPU -> stem_source="stem_demucs"
  * drum-stem onsets (rhythm) + other/lead-stem sustains (holds)

Usage (on the Colab VM):  python analyze_job.py <audio_basename>
Writes to CWD: analysis.json, job_meta.json, {drums,bass,other,vocals}.wav.

Determinism (REQ-COMPUTE-04): PYTHONHASHSEED + torch.manual_seed set, Demucs run
in eval/no-grad. Timing fields live only in job_meta (excluded from equality).
"""
import json
import os
import sys
import time

os.environ.setdefault("PYTHONHASHSEED", "0")

SR = 22050
HOP = 256
SUSTAIN_MIN_BEATS = 1.0


def _versions():
    v = {}
    for mod in ("numpy", "scipy", "librosa", "madmom", "torch", "demucs"):
        try:
            v[mod] = __import__(mod).__version__
        except Exception:
            v[mod] = None
    return v


def _band_split(S_col, freqs):
    low = float(S_col[freqs < 250].sum())
    mid = float(S_col[(freqs >= 250) & (freqs < 2000)].sum())
    high = float(S_col[freqs >= 2000].sum())
    tot = low + mid + high + 1e-9
    return {"low": round(low / tot, 3), "mid": round(mid / tot, 3), "high": round(high / tot, 3)}


def run(audio_path):
    import librosa
    import numpy as np
    import torch
    t0 = time.time()
    torch.manual_seed(0)

    y, _ = librosa.load(audio_path, sr=SR, mono=True)
    dur = len(y) / SR

    # ---- beats + downbeats via madmom DBN (deterministic) ----
    beat_backend = "madmom_dbn"
    try:
        from madmom.features.beats import DBNBeatTrackingProcessor, RNNBeatProcessor
        from madmom.features.downbeats import (DBNDownBeatTrackingProcessor,
                                              RNNDownBeatProcessor)
        db_act = RNNDownBeatProcessor()(audio_path)
        db = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)(db_act)
        beat_times = db[:, 0].tolist()
        downbeat_indices = [i for i, r in enumerate(db) if int(r[1]) == 1]
        # tempo from median inter-beat interval
        ibis = np.diff(db[:, 0])
        bpm = float(60.0 / np.median(ibis)) if len(ibis) else 120.0
        offset = float(beat_times[0]) if beat_times else 0.0
    except Exception as e:  # librosa fallback keeps the job alive
        beat_backend = "librosa"
        tempo, beats = librosa.beat.beat_track(y=y, sr=SR, hop_length=HOP, tightness=140)
        beat_times = librosa.frames_to_time(beats, sr=SR, hop_length=HOP).tolist()
        bpm = float(np.atleast_1d(tempo)[0])
        offset = float(beat_times[0]) if beat_times else 0.0
        downbeat_indices = list(range(0, len(beat_times), 4))
        print(f"madmom unavailable ({e}); used librosa", file=sys.stderr)

    period = 60.0 / bpm

    # ---- Demucs stems (GPU) ----
    stem_source = "none"
    stems = {}
    drums_y = None
    try:
        import torchaudio
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
        model = get_model("htdemucs")
        model.eval()
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(dev)
        wav, sr0 = torchaudio.load(audio_path)
        if sr0 != model.samplerate:
            wav = torchaudio.functional.resample(wav, sr0, model.samplerate)
        if wav.shape[0] == 1:
            wav = wav.repeat(2, 1)
        with torch.no_grad():
            est = apply_model(model, wav[None].to(dev), split=True, overlap=0.25)[0]
        for name, src in zip(model.sources, est):
            path = f"{name}.wav"
            torchaudio.save(path, src.cpu(), model.samplerate)
            stems[name] = path
        stem_source = "stem_demucs"
        drums_y = librosa.load(stems["drums"], sr=SR, mono=True)[0]
    except Exception as e:
        print(f"Demucs unavailable ({e}); HPSS-only", file=sys.stderr)

    # ---- onsets (drum stem if available, else HPSS percussive) ----
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    harm, perc = librosa.decompose.hpss(S)
    perc_src = drums_y if drums_y is not None else librosa.istft(perc, hop_length=HOP)
    onset_env = librosa.onset.onset_strength(y=perc_src, sr=SR, hop_length=HOP)
    frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=SR, hop_length=HOP,
                                        backtrack=True)
    times = librosa.frames_to_time(frames, sr=SR, hop_length=HOP)
    strengths = onset_env[frames] / (onset_env.max() or 1.0)

    harm_rms = librosa.feature.rms(S=harm)[0]
    harm_rms /= (harm_rms.max() or 1.0)
    hi = float(np.percentile(harm_rms, 75))
    min_sus = int(SUSTAIN_MIN_BEATS * period * SR / HOP)

    onsets = []
    for i, (t, st) in enumerate(zip(times, strengths)):
        n = (t - offset) / period
        q = round(n * 4) / 4.0
        snap_ms = (t - (offset + q * period)) * 1000.0
        col = int(min(t * SR / HOP, S.shape[1] - 1))
        bands = _band_split(S[:, col], freqs)
        sustain, sdur, src_tag = False, 0.0, ("stem_drums" if drums_y is not None else "mix")
        seg = harm_rms[col:min(len(harm_rms), col + min_sus)]
        if len(seg) >= min_sus and seg.mean() > hi and (seg.std() / (seg.mean() + 1e-9)) < 0.35:
            sustain, sdur = True, round(len(seg) / (SR / HOP) / period, 2)
        onsets.append({
            "id": f"p{i:03d}", "time": round(float(t), 4), "nearest_beat": round(q, 3),
            "snap_error_ms": round(float(snap_ms), 1), "strength": round(float(st), 4),
            "bands": bands, "source": src_tag, "sustain": sustain, "sustain_beats": sdur})

    # ---- structure + per-bar energy ----
    meter = 4
    bar_len = period * meter
    n_bars = max(1, int(np.ceil((dur - offset) / bar_len)))
    rms = librosa.feature.rms(S=S)[0]
    rms /= (rms.max() or 1.0)
    per_bar = []
    for b in range(n_bars):
        f0 = int((offset + b * bar_len) * SR / HOP)
        f1 = int((offset + (b + 1) * bar_len) * SR / HOP)
        seg = rms[max(0, f0):min(len(rms), f1)]
        per_bar.append(float(seg.mean()) if len(seg) else 0.0)
    per_bar = np.array(per_bar)
    energy = (per_bar / (per_bar.max() or 1.0)).round(4).tolist()
    sections = _sections(energy, n_bars)

    analysis = {
        "schema_version": "colab_job_v1", "track_file": os.path.basename(audio_path),
        "duration_s": round(dur, 3), "sample_rate": SR, "bpm": round(bpm, 3),
        "offset": round(offset, 3), "meter": meter, "beat_backend": beat_backend,
        "stem_source": stem_source, "beats": [round(float(b), 4) for b in beat_times],
        "downbeat_indices": downbeat_indices, "onsets": onsets,
        "sustain_available": sum(1 for o in onsets if o["sustain"]),
        "sections": sections, "energy_curve": energy,
        "energy_cv": round(float(per_bar.std() / (per_bar.mean() + 1e-9)), 4),
    }
    with open("analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    with open("job_meta.json", "w") as f:
        json.dump({"backend": "colab", "gpu": (torch.cuda.get_device_name(0)
                   if torch.cuda.is_available() else "cpu"),
                   "wall_clock_s": round(time.time() - t0, 1),
                   "versions": _versions(), "beat_backend": beat_backend,
                   "stem_source": stem_source}, f, indent=2)
    print(f"wrote analysis.json ({len(onsets)} onsets, bpm={bpm:.2f}, stems={stem_source})")


def _sections(energy, n_bars):
    import numpy as np
    e = np.array(energy)
    if len(e) > 2:
        nov = np.abs(np.diff(e, prepend=e[:1]))
        thr = nov.mean() + nov.std()
        bounds = [0] + [i for i in range(1, n_bars) if nov[i] > thr] + [n_bars]
    else:
        bounds = [0, n_bars]
    bounds = sorted(set(bounds))
    out = []
    for si in range(len(bounds) - 1):
        s0, s1 = bounds[si], bounds[si + 1]
        seg = e[s0:s1]
        ep = float(seg.mean()) if len(seg) else 0.0
        role = ("intro" if si == 0 else "outro" if si == len(bounds) - 2
                else "drop" if ep > 0.75 else "break" if ep < 0.4 else "build")
        out.append({"name": f"S{si}", "start_bar": s0, "end_bar": s1,
                    "energy_pct": round(ep, 3), "role_guess": role, "heuristic": True})
    return out


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "input.ogg")
