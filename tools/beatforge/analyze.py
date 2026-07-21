"""analyze.py — Workstream B orchestration over a ComputeBackend.

Idempotent + cached by (audio_sha256, analysis params) so re-runs never
re-provision unless --force (REQ-COMPUTE-04). Handles the loud-fail / opt-in
local-fallback contract (REQ-COMPUTE-05). Never touches the CLI or DSP directly
— only the backend.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config, dsp, ledger
from .compute import (AnalysisResult, ColabError, ComputeBackend,
                      LocalCpuBackend, make_backend)


def _cache_key(audio_path: str) -> str:
    return f"{dsp.audio_sha256(audio_path)[:16]}-{config.BEAT_ANALYSIS_VERSION}"


def analysis_path(track_id: str) -> Path:
    base = config.TRACK_CATALOGUE.get(track_id, track_id)
    return config.BUILD_DIR / f"{base}.analysis.json"


def _audio_for(track_id: str) -> str:
    base = config.TRACK_CATALOGUE.get(track_id, track_id)
    for root in (config.TRACKS_PUB, config.TRACKS_SRC):
        p = root / f"{base}.ogg"
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"no audio for track '{track_id}' ({base}.ogg)")


def load_cached(track_id: str) -> dict | None:
    p = analysis_path(track_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def analyze_track(
    track_id: str,
    opts: config.RunOptions,
    backend: ComputeBackend | None = None,
) -> dict:
    """Analyze one track, honoring the cache. `backend` may be shared across a
    batch (REQ-COMPUTE-03); if None, a fresh one is made and closed here."""
    audio = _audio_for(track_id)
    out = analysis_path(track_id)
    key = _cache_key(audio)

    if not opts.force:
        cached = load_cached(track_id)
        if cached and cached.get("cache_key") == key:
            # REQ-R2-COST-02: a cache hit is logged as an explicit $0 entry. An
            # absent entry would be indistinguishable from missing instrumentation,
            # and "re-runs cost nothing for analysis" is a claim the ledger has to
            # be able to substantiate, not just imply.
            ledger.record_compute(
                stage_name="analysis", song=track_id, backend=opts.backend,
                gpu=None, minutes=0.0, cache_hit=True,
                detail={"cache_key": key, "reason": "analysis cache hit"})
            return cached

    own_backend = backend is None
    if backend is None:
        backend = make_backend(opts)
    t0 = time.monotonic()
    try:
        result = _run_with_degradation(audio, opts, backend)
    finally:
        if own_backend:
            backend.close()

    # Prefer the job's own self-reported wall clock (Colab measures the work
    # itself); fall back to what we timed from here, marked estimated, so a
    # backend that can't report still produces a number instead of a blank.
    wall = result.job_meta.get("wall_clock_s")
    estimated = wall is None
    minutes = (float(wall) if wall is not None else (time.monotonic() - t0)) / 60.0
    ledger.record_compute(
        stage_name="analysis", song=track_id,
        backend=result.job_meta.get("backend", opts.backend),
        gpu=result.job_meta.get("gpu"), minutes=minutes, cache_hit=False,
        estimated=estimated,
        detail={"cache_key": key,
                "stem_source": result.job_meta.get("stem_source"),
                "beat_backend": result.job_meta.get("beat_backend"),
                "onsets": len(result.analysis.get("onsets", []))})

    analysis = result.analysis
    analysis["cache_key"] = key
    analysis["track_id"] = track_id
    analysis["job_meta"] = result.job_meta
    if result.stem_paths:
        analysis["stem_paths"] = result.stem_paths

    _sanity_gate(analysis)

    config.BUILD_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(analysis, indent=2))
    meta = config.BUILD_DIR / f"{Path(audio).stem}.job_meta.json"
    meta.write_text(json.dumps(result.job_meta, indent=2))
    return analysis


def _run_with_degradation(
    audio: str, opts: config.RunOptions, backend: ComputeBackend,
) -> AnalysisResult:
    """REQ-COMPUTE-05: Colab failure is loud unless --allow-local-fallback, in
    which case we drop to LocalCpuBackend and STAMP the degradation."""
    try:
        return backend.run_analysis(audio, opts)
    except ColabError as e:
        if not opts.allow_local_fallback:
            raise ColabError(
                f"Colab backend unavailable: {e}\n"
                "Re-run with --allow-local-fallback to accept the reduced-fidelity "
                "local path (HPSS-only, no stems), or fix Colab auth/quota.") from e
        print(f"[beatforge] WARNING: Colab unavailable ({e}); "
              "falling back to LocalCpuBackend (stem_source=none).")
        result = LocalCpuBackend().run_analysis(audio, opts)
        result.analysis["degraded_from"] = "colab"
        result.job_meta["degraded_from"] = "colab"
        return result


def _sanity_gate(analysis: dict) -> None:
    """REQ-DSP-04 sanity: onset count in a sane band; bpm/offset sane."""
    n = len(analysis.get("onsets", []))
    lo, hi = config.ONSET_COUNT_SANITY
    if not (lo <= n <= hi):
        print(f"[beatforge] WARNING: {analysis.get('track_file')} has {n} onsets "
              f"(outside sanity band {lo}-{hi}); analysis kept but flagged.")
        analysis["sanity_warnings"] = analysis.get("sanity_warnings", []) + [
            f"onset_count={n} outside {lo}-{hi}"]
    if analysis["bpm"] <= 0 or analysis["offset"] < 0:
        raise ValueError(f"insane bpm/offset: {analysis['bpm']}/{analysis['offset']}")
