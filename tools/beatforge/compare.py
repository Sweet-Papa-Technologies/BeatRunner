"""compare.py — benchmark an alternative audio LLM (e.g. local Gemma 4 12B on an
OpenAI-compatible server) against Gemini 3.5 Flash on this pipeline's real work.

Two tests, both grounded in the DSP truth so the comparison is objective:

  1. AUDIO-UNDERSTANDING PROBE — give each model the track audio and ask for a
     strict-JSON {tempo_bpm, has_kick, section_count, one_line}. We already KNOW
     the true tempo from Workstream B, so |reported - measured| BPM is a direct
     score of how well each model actually hears music.

  2. DESIGNER + SHARED-JUDGE — have each model design the same (track, difficulty)
     chart, then judge BOTH charts with the SAME critic (Gemini, for fairness) and
     report critic score, attempts, gate pass, and event count side by side.

Run: `python -m beatforge compare --track overdrive [--difficulty standard]
      [--probe-only]` with BEATFORGE_OPENAI_BASE_URL pointing at the server.
"""
from __future__ import annotations

import json
import time

from . import config, qa
from .analyze import analyze_track
from .design import critic_pass, design_chart
from .llm import OpenAICompatClient, OpenAICompatError, VertexClient
from .vertex import VertexError

_PROBE = (
    "You are hearing a ~33s synthwave track. Listen and reply with ONLY this JSON "
    "object, no prose:\n"
    '{"tempo_bpm": <number>, "has_kick": <true|false>, "section_count": <int>, '
    '"one_line": "<short description of the structure you hear>"}'
)


def audio_probe(client, audio_path: str) -> dict:
    t0 = time.monotonic()
    out = client.generate_json(_PROBE, audio_path=audio_path)
    out["_latency_s"] = round(time.monotonic() - t0, 2)
    return out


def _audio_path(track_id: str) -> str:
    base = config.TRACK_CATALOGUE.get(track_id, track_id)
    for root in (config.TRACKS_PUB, config.TRACKS_SRC):
        p = root / f"{base}.ogg"
        if p.exists():
            return str(p)
    raise FileNotFoundError(track_id)


def compare_track(track_id: str, difficulty: str, opts: config.RunOptions,
                  probe_only: bool = False) -> dict:
    analysis = analyze_track(track_id, opts)
    audio = _audio_path(track_id)
    true_bpm = analysis["bpm"]
    gemini = VertexClient()
    gemma = OpenAICompatClient()
    judge = gemini  # same judge for both, for a fair musicality comparison

    report: dict = {"track": track_id, "difficulty": difficulty,
                    "measured_bpm": round(true_bpm, 2), "probe": {}, "design": {}}

    # ---- 1. audio-understanding probe ----
    for name, client in (("gemini", gemini), ("gemma", gemma)):
        try:
            p = audio_probe(client, audio)
            p["bpm_error"] = round(abs(float(p.get("tempo_bpm", 0)) - true_bpm), 2)
            report["probe"][name] = p
        except (VertexError, OpenAICompatError, ValueError) as e:
            report["probe"][name] = {"error": str(e)[:300]}

    if probe_only:
        return report

    # ---- 2. designer + shared judge ----
    for name, client in (("gemini", gemini), ("gemma", gemma)):
        try:
            t0 = time.monotonic()
            chart = design_chart(track_id, difficulty, analysis, audio, client, opts)
            review = critic_pass(chart, analysis, audio, judge)  # SAME judge
            report["design"][name] = {
                "events": chart.metrics["event_count"],
                "attempts": chart.attempts,
                "onset_alignment": chart.metrics["onset_alignment"],
                "gates_pass": qa.gates_pass(chart.metrics),
                "critic_score": review.get("score"),
                "critic_verdict": (review.get("verdict") or "")[:160],
                "design_seconds": round(time.monotonic() - t0, 1),
            }
        except (VertexError, OpenAICompatError, RuntimeError, ValueError) as e:
            report["design"][name] = {"error": str(e)[:300]}
    return report


def format_report(r: dict) -> str:
    lines = [f"\n=== Gemma 4 12B  vs  Gemini 3.5 Flash — {r['track']}/{r['difficulty']} ===",
             f"DSP-measured true BPM: {r['measured_bpm']}", "",
             "AUDIO-UNDERSTANDING PROBE (lower BPM error = hears tempo better):"]
    for name in ("gemini", "gemma"):
        p = r["probe"].get(name, {})
        if "error" in p:
            lines.append(f"  {name:6s}: ERROR {p['error'][:120]}")
        else:
            lines.append(f"  {name:6s}: bpm={p.get('tempo_bpm')} (err {p.get('bpm_error')}) "
                         f"kick={p.get('has_kick')} sections={p.get('section_count')} "
                         f"{p.get('_latency_s')}s | \"{p.get('one_line','')[:70]}\"")
    if r.get("design"):
        lines.append("\nDESIGNER (same Gemini critic judges both):")
        for name in ("gemini", "gemma"):
            d = r["design"].get(name, {})
            if "error" in d:
                lines.append(f"  {name:6s}: ERROR {d['error'][:120]}")
            elif d:
                lines.append(f"  {name:6s}: critic={d.get('critic_score')} "
                             f"events={d.get('events')} attempts={d.get('attempts')} "
                             f"align={d.get('onset_alignment')} gates={d.get('gates_pass')} "
                             f"{d.get('design_seconds')}s")
    return "\n".join(lines)
