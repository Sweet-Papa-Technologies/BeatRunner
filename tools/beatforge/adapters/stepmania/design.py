"""design.py — the StepMania intent designer (Gemini 3.5 Flash, swappable via
llm.py) and the fresh-context critic (STEPFORGE §6, REQ-SM-05/13). The model
hears the audio and emits INTENT (which onsets, kinds, phrase textures) — never
panels or times."""
from __future__ import annotations

import json
from pathlib import Path

from ... import config
from .grammar import BUDGETS

_PROMPTS = Path(__file__).resolve().parent / "prompts"


def _budget_text(difficulty: str) -> str:
    b = BUDGETS[difficulty]
    lo_h, hi_h = b.hold_share
    return (f"- finest row subdivision: {b.finest_subdiv} beat\n"
            f"- max sustained NPS (4s window): {b.max_nps_4s}\n"
            f"- crossovers: {b.crossover}\n"
            f"- footswitches: {'allowed (sparse)' if b.footswitch else 'none'}\n"
            f"- jacks: max {b.jack_limit} in a burst\n"
            f"- jumps: {b.jumps}\n"
            f"- holds/rolls share of notes: {lo_h:.0%}-{hi_h:.0%}\n"
            f"- density must follow the per-bar energy (Spearman >= 0.55)")


def _compact_analysis(analysis: dict, difficulty: str) -> dict:
    b = BUDGETS[difficulty]
    subdiv = b.finest_subdiv
    lo = config.FIRST_PLAYABLE_BEAT
    hi = (analysis["duration_s"] - config.PLAYABLE_TAIL_S - analysis["offset"]) * analysis["bpm"] / 60.0
    onsets = []
    for o in analysis.get("onsets", []):
        beat = o["nearest_beat"]
        if beat < lo or beat > hi:
            continue
        if abs(beat - round(beat / subdiv) * subdiv) > 1e-3:
            continue
        if abs(o.get("snap_error_ms", 0)) > config.ONSET_SNAP_MAX_MS:
            continue
        usable = o["sustain"] and o.get("sustain_beats", 0) >= b.hold_len_beats[0] - 1.0
        onsets.append({"id": o["id"], "beat": beat, "strength": o["strength"],
                       "bands": o["bands"], "sustain": usable,
                       "sustain_beats": o.get("sustain_beats", 0)})
    return {"bpm": analysis["bpm"], "offset": analysis["offset"], "meter": analysis.get("meter", 4),
            "duration_s": analysis["duration_s"], "finest_subdivision": subdiv,
            "sections": analysis.get("sections", []),
            "energy_curve": analysis.get("energy_curve", []), "onsets": onsets}


def designer_prompt(difficulty: str, analysis: dict) -> str:
    tmpl = (_PROMPTS / "designer.md").read_text()
    return (tmpl.replace("{difficulty}", difficulty)
                .replace("{budget}", _budget_text(difficulty))
                .replace("{analysis}", json.dumps(_compact_analysis(analysis, difficulty))))


def design_intent(track_id: str, difficulty: str, analysis: dict, audio: str, client,
                  seed_feedback: str | None = None) -> dict:
    prompt = designer_prompt(difficulty, analysis)
    if seed_feedback:
        prompt += ("\n\n--- REVISION: your previous chart drew this critique; address "
                   "it while keeping every budget rule ---\n" + seed_feedback)
    return client.generate_json(prompt, audio_path=audio)


def critic_review(track_id: str, difficulty: str, analysis: dict, placements: list,
                  audio: str, client) -> dict:
    """Fresh-context critic (Author≠Judge, REQ-SM-13): render the realized chart
    UNAMBIGUOUSLY (holds as explicit start→end spans so a post-hold tap is never
    misread as a concurrent conflict) and have Gemini judge musicality/playability."""
    from .grammar import PANELS
    bpm, offset = analysis["bpm"], analysis["offset"]

    def t(beat):
        return round(offset + beat / bpm * 60, 3)

    rows = []
    for p in placements[:600]:
        panels = "".join(PANELS[c] for c in p.panels)
        if p.hold_beats:
            rows.append(f"{t(p.beat):.3f}: HOLD {panels} until {t(p.beat + p.hold_beats):.3f}")
        elif len(p.panels) > 1:
            rows.append(f"{t(p.beat):.3f}: JUMP {panels}")
        else:
            rows.append(f"{t(p.beat):.3f}: tap {panels}")
    prompt = (
        f"You are a StepMania (ITG) chart critic. You are HEARING the audio and "
        f"reading a realized {difficulty} dance-single chart. Each line is "
        f"'<time_s>: EVENT panels'. A 'HOLD X until T' occupies panel X from its "
        f"time until T — any later 'tap X' AFTER that end time is a normal, legal "
        f"step, NOT a conflict; do not flag it. Note that the validator already "
        f"guarantees no note lands on a panel while it is held, and jumps are <=2 "
        f"panels. You did NOT design this — judge it fresh: do steps land on the "
        f"music, is the foot flow comfortable, does density track energy, does the "
        f"drop hit?\n"
        f"Chart:\n" + "\n".join(rows) + "\n\n"
        f"Reply ONLY JSON: {{\"score\": <0-10>, \"verdict\": \"<one line>\", "
        f"\"issues\": [{{\"where\":\"..\",\"problem\":\"..\"}}]}}")
    return client.generate_json(prompt, audio_path=audio)
