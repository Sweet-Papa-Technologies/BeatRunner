"""analyze.py — Workstream B orchestration over a ComputeBackend.

Idempotent + cached by (audio_sha256, analysis params) so re-runs never
re-provision unless --force (REQ-COMPUTE-04). Handles the loud-fail / opt-in
local-fallback contract (REQ-COMPUTE-05). Never touches the CLI or DSP directly
— only the backend.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config, dsp
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
            return cached

    own_backend = backend is None
    if backend is None:
        backend = make_backend(opts)
    try:
        result = _run_with_degradation(audio, opts, backend)
    finally:
        if own_backend:
            backend.close()

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
