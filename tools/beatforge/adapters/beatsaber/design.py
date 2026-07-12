"""design.py — the Beat Saber intent designer (Gemini 3.5 Flash via the shared
llm.py) + the fresh-context critic (SABERFORGE spec §6/§9, REQ-BS-05/11). The
model HEARS the track and emits INTENT — which onsets become notes, each note's
kind + hand, and per-phrase feel — NEVER grid coordinates, cut directions, or
parity. The parity realizer (§5) turns intent into swing-legal geometry.
"""
from __future__ import annotations

import json
from pathlib import Path

from ... import config
from .grammar import BUDGETS

_PROMPTS = Path(__file__).resolve().parent / "prompts"


def _budget_text(difficulty: str) -> str:
    b = BUDGETS[difficulty]
    lo_ac, hi_ac = b.arc_chain_share
    return (f"- finest note precision: 1/{round(1 / b.finest_precision)} beat\n"
            f"- max sustained NPS (4s window): {b.max_nps_4s}\n"
            f"- grid rows usable: {list(b.rows)} (0=bottom,1=mid,2=top)\n"
            f"- resets: {b.resets} (telegraphed = bomb reset with lead time only)\n"
            f"- doubles/stacks: {b.doubles}\n"
            f"- arcs+chains share of notes: {lo_ac:.0%}-{hi_ac:.0%}\n"
            f"- NJS ~{b.njs} (locked per difficulty)\n"
            f"- density must follow the per-bar energy (Spearman >= 0.55)")


def _compact_analysis(analysis: dict, difficulty: str) -> dict:
    b = BUDGETS[difficulty]
    subdiv = b.finest_precision
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
        onsets.append({"id": o["id"], "beat": beat, "strength": o["strength"],
                       "bands": o["bands"], "sustain": o.get("sustain", False),
                       "sustain_beats": o.get("sustain_beats", 0)})
    return {"bpm": analysis["bpm"], "offset": analysis["offset"],
            "meter": analysis.get("meter", 4), "duration_s": analysis["duration_s"],
            "finest_precision": subdiv, "sections": analysis.get("sections", []),
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
        prompt += ("\n\n--- REVISION: your previous draft drew this critique; address "
                   "it while keeping every budget rule ---\n" + seed_feedback)
    return client.generate_json(prompt, audio_path=audio)


def critic_review(track_id: str, difficulty: str, analysis: dict, objs: list,
                  audio: str, client) -> dict:
    """Fresh-context critic (Author≠Judge, REQ-BS-11): render the realized map as
    a readable per-hand swing sequence and have Gemini judge flow/musicality."""
    from .grammar import COLOR_HAND
    from .parity import direction_parity
    bpm, offset = analysis["bpm"], analysis["offset"]
    _DIRNAME = {0: "up", 1: "down", 2: "left", 3: "right", 4: "up-left",
                5: "up-right", 6: "down-left", 7: "down-right", 8: "dot"}

    def t(beat):
        return round(offset + beat / bpm * 60, 3)

    rows = []
    for o in sorted(objs, key=lambda o: o.beat)[:600]:
        if o.kind == "bomb":
            rows.append(f"{t(o.beat):.3f}: BOMB ({o.x},{o.y})")
            continue
        hand = COLOR_HAND[o.color]
        par = direction_parity(o.direction)
        kind = o.kind.upper() if o.kind != "note" else "note"
        rows.append(f"{t(o.beat):.3f}: {hand} {kind} {_DIRNAME[o.direction]} "
                    f"[{par}] @({o.x},{o.y})")
    prompt = (
        f"You are a Beat Saber (Standard) map critic. You are HEARING the audio and "
        f"reading a realized {difficulty} map as a per-hand swing sequence. Each line "
        f"is '<time_s>: <hand> <kind> <cut-direction> [parity] @(x,y)'. Smooth play "
        f"ALTERNATES forehand/backhand per hand; a reset (two same-parity swings in a "
        f"row) is bad unless a BOMB telegraphs it. Casual-first: a miss breaks combo "
        f"but never kills. You did NOT design this — judge it fresh: do the notes land "
        f"on the music, does the swing flow comfortably (parity), does density track "
        f"energy, does the drop hit two-handed?\n"
        f"Map:\n" + "\n".join(rows) + "\n\n"
        f"Reply ONLY JSON: {{\"score\": <0-10>, \"verdict\": \"<one line>\", "
        f"\"issues\": [{{\"where\":\"bar/time\",\"problem\":\"..\"}}]}}")
    return client.generate_json(prompt, audio_path=audio)
