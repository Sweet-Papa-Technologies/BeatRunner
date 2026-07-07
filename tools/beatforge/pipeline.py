"""pipeline.py — top-level orchestration of Workstreams B→C→D→E per track.

Ties analysis (B) → designer + gate loop (C/D) → fresh-context critic with one
targeted revision below the ship threshold (REQ-QA-04) → beatmap + QA report +
previews written to build/analysis/ and public/maps/.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import config, qa
from .analyze import analyze_track
from .compute import ComputeBackend
from .design import ChartResult, critic_pass, design_chart
from .llm import LLMClient, make_llm_client


def chart_track(
    track_id: str, opts: config.RunOptions, client: LLMClient,
    backend: ComputeBackend | None = None,
) -> dict:
    """Analyze one track and produce all requested difficulties + QA reports."""
    analysis = analyze_track(track_id, opts, backend=backend)
    audio = _audio_path(track_id)
    base = config.TRACK_CATALOGUE.get(track_id, track_id)
    summary = {"track_id": track_id, "bpm": analysis["bpm"],
               "offset": analysis["offset"], "stem_source": analysis["stem_source"],
               "beat_backend": analysis["beat_backend"], "charts": {}}

    for diff in opts.difficulties:
        try:
            chart = design_chart(track_id, diff, analysis, audio, client, opts)
            chart = _critic_and_maybe_revise(chart, analysis, audio, client, opts)
        except Exception as e:  # one difficulty failing must not abort the batch
            print(f"[chart] {track_id}/{diff} FAILED: {e}")
            summary["charts"][diff] = {"error": str(e)}
            (config.BUILD_DIR / f"{base}.{diff}.error.txt").write_text(str(e))
            continue

        # write beatmap for the game (public/maps/)
        map_path = config.MAPS_PUB / f"{base}.{diff}.beatmap.json"
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(json.dumps(chart.beatmap, indent=2))

        # previews (best-effort) + QA report
        previews = qa.render_previews(
            analysis.get("track_file", f"{base}.ogg"), audio, chart.beatmap,
            analysis, config.BUILD_DIR / f"{base}.{diff}")
        report = {
            "track_id": track_id, "difficulty": diff,
            "attempts": chart.attempts, "metrics": chart.metrics,
            "critic": chart.critic, "repairs": chart.repairs,
            "design_notes": chart.design.get("design_notes", ""),
            "design_sections": chart.design.get("sections", []),
            "previews": previews,
            "map_path": str(map_path.relative_to(config.REPO_ROOT)),
        }
        (config.BUILD_DIR / f"{base}.{diff}.qa.json").write_text(json.dumps(report, indent=2))
        summary["charts"][diff] = {
            "events": chart.metrics["event_count"],
            "attempts": chart.attempts,
            "critic_score": (chart.critic or {}).get("score"),
            "gates_pass": qa.gates_pass(chart.metrics),
            "map": report["map_path"],
        }
    (config.BUILD_DIR / f"{base}.summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def _critic_and_maybe_revise(
    chart: ChartResult, analysis: dict, audio: str, client: LLMClient,
    opts: config.RunOptions,
) -> ChartResult:
    """REQ-QA-04: run the fresh-context critic. Below the ship threshold, take ONE
    targeted designer revision (feeding the critic's issues back), keep whichever
    scores higher, and flag for human review if still short — never loop forever."""
    review = critic_pass(chart, analysis, audio, client)
    chart.critic = review
    if float(review.get("score", 0)) >= config.CRITIC_SHIP_THRESHOLD:
        return chart

    issues = "; ".join(
        f"{i.get('where','')}: {i.get('problem','')}" for i in review.get("issues", []))
    violations = ("A critic reviewing your chart raised these musicality issues — "
                  f"address them while keeping every budget rule: {issues}")
    try:
        revised = design_chart(chart.track_id, chart.difficulty, analysis, audio,
                              client, opts, seed_violations=violations)
    except Exception:
        chart.critic["human_review"] = True
        return chart
    revised.critic = critic_pass(revised, analysis, audio, client)
    best = revised if float(revised.critic.get("score", 0)) >= float(review.get("score", 0)) else chart
    if float(best.critic.get("score", 0)) < config.CRITIC_SHIP_THRESHOLD:
        best.critic["human_review"] = True
    return best


def _audio_path(track_id: str) -> str:
    base = config.TRACK_CATALOGUE.get(track_id, track_id)
    for root in (config.TRACKS_PUB, config.TRACKS_SRC):
        p = root / f"{base}.ogg"
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"no audio for {track_id}")
