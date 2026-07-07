"""design.py — Workstream C: Gemini 3.5 Flash as level designer + critic.

One designer call per (track, difficulty): the model HEARS the audio and reads
the DSP analysis, then places notes by referencing onset IDs / grid lines only
(never a timestamp — enforced in resolve.py). The result is resolved, validated,
repaired, and gated (Workstream D); on gate failure the designer is re-invoked
with the machine-readable violation report (REQ-QA-03), up to 3 attempts. A
separate fresh-context critic call judges musicality (REQ-QA-04, Author≠Judge).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import config, qa
from .llm import LLMClient
from .resolve import ResolveError, resolve_events
from .validate import RepairExceeded, ValidationResult, validate_and_repair


@dataclass
class ChartResult:
    track_id: str
    difficulty: str
    beatmap: dict
    metrics: dict
    design: dict
    repairs: list
    attempts: int
    critic: dict | None = None
    artifacts: dict = field(default_factory=dict)


def _budget_text(difficulty: str) -> str:
    b = config.BUDGETS[difficulty]
    lo_h, hi_h = b.hold_share
    return (
        f"- min gap between events: >= {b.min_gap_beats} beat AND >= {b.min_gap_ms:.0f}ms\n"
        f"- finest grid subdivision: {b.finest_subdiv} beat\n"
        f"- max sustained NPS (any 4s window): {b.max_nps_4s}\n"
        f"- same-lane consecutive (jack) limit: {b.jack_limit}\n"
        f"- taps in other lanes during a hold: {b.taps_during_hold}\n"
        f"- hold length: {b.hold_len_beats[0]}-{b.hold_len_beats[1]} beats\n"
        f"- share of events that are holds: {lo_h:.0%}-{hi_h:.0%}\n"
        f"- simultaneous events (chords): never\n"
        f"- density must rise into high-energy sections and breathe in breaks"
    )


def _compact_analysis(analysis: dict, difficulty: str) -> dict:
    """A designer-facing view: everything the model needs to place notes, minus
    the bulky raw beat array. Onsets are FILTERED to those whose grid position is
    legal at this difficulty's finest subdivision, so the designer can't pick a
    candidate that validation would later drop (which was over-repairing casual)."""
    budget = config.BUDGETS[difficulty]
    subdiv = budget.finest_subdiv
    hold_floor = budget.hold_len_beats[0]
    # playable window (mirrors validate): only offer onsets the validator would keep,
    # so onset refs never become hard-drops (which over-repair sparse casual charts).
    last_beat = ((analysis["duration_s"] - config.PLAYABLE_TAIL_S - analysis["offset"])
                 * analysis["bpm"] / 60.0)
    onsets = []
    for o in analysis.get("onsets", []):
        beat = o["nearest_beat"]
        if abs(beat - round(beat / subdiv) * subdiv) > 1e-3:
            continue  # not on a legal line for this difficulty
        if beat < config.FIRST_PLAYABLE_BEAT or beat > last_beat:
            continue  # outside the playable window
        if abs(o.get("snap_error_ms", 0)) > config.ONSET_SNAP_MAX_MS:
            continue  # would fail the snap gate
        # Only offer a hold if the candidate can reach this difficulty's hold-length
        # floor within the ±1-beat contract tolerance; otherwise present it as a tap
        # so the designer never proposes an impossible hold (e.g. a 1-beat pad on casual).
        usable = o["sustain"] and o.get("sustain_beats", 0) >= hold_floor - 1.0
        onsets.append({
            "id": o["id"], "beat": beat, "strength": o["strength"],
            "bands": o["bands"], "sustain": usable,
            "sustain_beats": o.get("sustain_beats", 0)})
    return {
        "bpm": analysis["bpm"],
        "offset": analysis["offset"],
        "meter": analysis.get("meter", 4),
        "duration_s": analysis["duration_s"],
        "sections": analysis.get("sections", []),
        "energy_curve": analysis.get("energy_curve", []),
        "sustain_available": sum(1 for o in onsets if o["sustain"]),
        "finest_subdivision": subdiv,
        "onsets": onsets,
    }


def _designer_prompt(difficulty: str, analysis: dict, violations: str | None) -> str:
    tmpl = (config.PROMPTS_DIR / "designer.md").read_text()
    prompt = (tmpl
              .replace("{difficulty}", difficulty)
              .replace("{budget}", _budget_text(difficulty))
              .replace("{finest_subdiv}", str(config.BUDGETS[difficulty].finest_subdiv)))
    compact = _compact_analysis(analysis, difficulty)
    prompt += "\n\n--- MACHINE ANALYSIS (authoritative timing truth) ---\n"
    prompt += json.dumps(compact)
    # Explicit, unambiguous hold directive — the designer under-produced holds when
    # left to infer the share from the budget. Name the exact usable candidates.
    b = config.BUDGETS[difficulty]
    hold_ids = [o["id"] for o in compact["onsets"] if o["sustain"]]
    if hold_ids:
        lo, hi = b.hold_share
        prompt += (
            f"\n\n--- HOLD REQUIREMENT (hard) ---\n"
            f"About {lo:.0%}-{hi:.0%} of your events MUST be holds. Create each hold by "
            f"putting `hold_beats` on one of THESE sustain-candidate ids (and ONLY these): "
            f"{hold_ids}. Each hold_beats must be within ±1 beat of that candidate's "
            f"sustain_beats and within {b.hold_len_beats[0]}-{b.hold_len_beats[1]} beats. "
            f"NEVER put hold_beats on a non-sustain onset.")
    else:
        prompt += ("\n\n--- HOLDS ---\nThis track has no sustain candidate usable at "
                   "this difficulty; do NOT create any holds (all events are taps).")
    if violations:
        prompt += ("\n\n--- YOUR PREVIOUS ATTEMPT FAILED THESE GATES; FIX THEM ---\n"
                   + violations)
    return prompt


def design_chart(
    track_id: str, difficulty: str, analysis: dict, audio_path: str,
    client: LLMClient, opts: config.RunOptions,
    seed_violations: str | None = None,
) -> ChartResult:
    """Run the designer→validate→gate loop for one (track, difficulty).
    `seed_violations` lets a critic revision steer the first attempt."""
    track_file = analysis.get("track_file", f"{track_id}.ogg")
    violations: str | None = seed_violations
    last_err: str | None = None
    raw_design: dict = {}

    for attempt in range(1, config.DESIGN_MAX_ATTEMPTS + 1):
        prompt = _designer_prompt(difficulty, analysis, violations or last_err)
        raw_design = client.generate_json(prompt, audio_path=audio_path)
        _dump(track_id, difficulty, f"design.attempt{attempt}", raw_design)

        try:
            resolved = resolve_events(raw_design, analysis)
            vr = validate_and_repair(resolved, analysis, difficulty)
        except (ResolveError, RepairExceeded) as e:
            last_err = f"Your chart was rejected: {e}. Fix it and resubmit."
            violations = None
            continue

        beatmap = _beatmap(track_file, analysis, vr)
        metrics = qa.compute_metrics(vr, analysis, difficulty)

        if qa.gates_pass(metrics):
            return ChartResult(track_id, difficulty, beatmap, metrics, raw_design,
                              vr.repairs, attempt)
        violations = qa.violation_report(metrics, difficulty)
        last_err = None

    # exhausted attempts — fail loudly with artifacts preserved (REQ-QA-03)
    raise RuntimeError(
        f"{track_id}/{difficulty}: designer failed gates after "
        f"{config.DESIGN_MAX_ATTEMPTS} attempts. Last violations: {violations or last_err}")


def _beatmap(track_file: str, analysis: dict, vr: ValidationResult) -> dict:
    return {
        "track": track_file,
        "bpm": analysis["bpm"],
        "offset": analysis["offset"],
        "events": vr.events,
    }


def critic_pass(
    chart: ChartResult, analysis: dict, audio_path: str, client: LLMClient,
) -> dict:
    """Fresh-context Gemini critic (Author≠Judge, REQ-QA-04). Renders the chart
    as (time, lane, hold) so the model judges by ear against the audio."""
    bpm, offset = analysis["bpm"], analysis["offset"]
    rows = [
        {"t": round(offset + e["beat"] / bpm * 60, 3), "lane": e["type"],
         "hold_beats": e.get("dur", 0)}
        for e in chart.beatmap["events"]
    ]
    sections = [{"role": s["role_guess"], "bars": [s["start_bar"], s["end_bar"]]}
                for s in analysis.get("sections", [])]
    tmpl = (config.PROMPTS_DIR / "chart_critic.md").read_text()
    prompt = (tmpl
              .replace("{difficulty}", chart.difficulty)
              .replace("{chart}", json.dumps(rows))
              .replace("{sections}", json.dumps(sections)))
    review = client.generate_json(prompt, audio_path=audio_path)
    _dump(chart.track_id, chart.difficulty, "critic", review)
    return review


def _dump(track_id: str, difficulty: str, tag: str, obj: dict) -> None:
    base = config.TRACK_CATALOGUE.get(track_id, track_id)
    config.BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (config.BUILD_DIR / f"{base}.{difficulty}.{tag}.json").write_text(
        json.dumps(obj, indent=2))
