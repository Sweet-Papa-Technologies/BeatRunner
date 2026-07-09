"""adapter.py — StepManiaAdapter: the TargetAdapter for StepMania dance-single
(STEPFORGE §2). Ties design (intent) -> realize (panels) -> validate/repair ->
serialize (simfile) -> QA, touching nothing outside adapters/stepmania/.
"""
from __future__ import annotations

import json
from pathlib import Path

from ... import config
from ...analyze import analyze_track
from . import qa as sm_qa
from .difficulty import compute_meter
from .grammar import BUDGETS, DIFFICULTIES, grammar_description
from .realize import decide_jumps, realize
from .resolve import deterministic_intent, fill_gaps, resolve_intent, thin_for_difficulty
from .serialize import write_song_folder
from .validate import validate_repair


class StepManiaAdapter:
    name = "stepmania"

    def grammar(self) -> dict:
        return grammar_description()

    def design_brief(self, analysis: dict, difficulty: str) -> str:
        from .design import designer_prompt
        return designer_prompt(difficulty, analysis)

    def realize(self, design: dict, analysis: dict, difficulty: str) -> list:
        resolved = resolve_intent(design, analysis, difficulty)
        resolved = fill_gaps(resolved, analysis, difficulty)   # no dead pauses
        resolved = thin_for_difficulty(resolved, analysis, difficulty)  # tier envelope
        decide_jumps(resolved, BUDGETS[difficulty], analysis.get("meter", 4))
        return realize(resolved, BUDGETS[difficulty], analysis.get("meter", 4))

    def validate_repair(self, placements, analysis, difficulty):
        rr = validate_repair(placements, analysis, difficulty)
        meter = compute_meter(rr.placements, analysis["bpm"], difficulty)
        return rr.placements, meter, {"repairs": rr.repairs, "ok": rr.ok,
                                      "original": rr.original}

    def serialize(self, per_difficulty, analysis, track_id, out_dir):
        meta = _track_meta(track_id, analysis)
        return write_song_folder(meta, analysis, per_difficulty,
                                _audio_path(track_id), Path(out_dir),
                                formats=("ssc", "sm"))

    def qa_metrics(self, placements, analysis, difficulty):
        return sm_qa.chart_metrics(placements, analysis, difficulty)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def build_song(track_id: str, opts: config.RunOptions, difficulties=DIFFICULTIES,
               deterministic: bool = True, client=None) -> dict:
    adapter = StepManiaAdapter()
    analysis = analyze_track(track_id, opts)
    bpm = analysis["bpm"]
    out_dir = config.STEPMANIA_DIR / config.TRACK_CATALOGUE.get(track_id, track_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    per_difficulty = {}
    report = {"track_id": track_id, "bpm": bpm, "offset": analysis["offset"],
              "mode": "deterministic" if (deterministic or client is None) else "gemini",
              "charts": {}}
    for diff in difficulties:
        best = _design_once(adapter, track_id, diff, analysis, deterministic, client, None)
        (out_dir / f"{diff}.design.json").write_text(json.dumps(best["design"], indent=2))

        # critic (Author≠Judge, REQ-SM-13) + one targeted revision below the ship
        # threshold, then human-review flag. Gemini path only.
        if not deterministic and client is not None:
            best["critic"] = _run_critic(track_id, diff, analysis, best["placements"], client)
            if float((best["critic"] or {}).get("score", 0)) < 7:
                issues = "; ".join(f"{i.get('where','')}: {i.get('problem','')}"
                                   for i in (best["critic"] or {}).get("issues", []))
                revised = _design_once(adapter, track_id, diff, analysis, False, client,
                                       f"A critic raised these issues — fix them while keeping "
                                       f"every budget rule: {issues}")
                revised["critic"] = _run_critic(track_id, diff, analysis, revised["placements"], client)
                if float(revised["critic"].get("score", 0)) >= float(best["critic"].get("score", 0)):
                    best = revised
                if float(best["critic"].get("score", 0)) < 7:
                    best["critic"]["human_review"] = True
            (out_dir / f"{diff}.critic.json").write_text(json.dumps(best["critic"], indent=2))

        meter, placements = best["meter"], best["placements"]
        per_difficulty[diff] = (meter, placements)
        previews = sm_qa.render_previews(placements, analysis, _audio_path(track_id), out_dir / diff)
        report["charts"][diff] = {
            "notes": len(placements), "meter": meter,
            "jumps": sum(1 for p in placements if len(p.panels) > 1),
            "holds": sum(1 for p in placements if p.hold_beats),
            "repaired": best["vinfo"]["original"] - len(placements),
            "repair_ok": best["vinfo"]["ok"], "critic": best.get("critic"),
            "previews": previews, "metrics": best["metrics"]}

    files = adapter.serialize(per_difficulty, analysis, track_id, out_dir)
    report["files"] = files
    report["out"] = str(out_dir.relative_to(config.REPO_ROOT))
    _meter_monotonic(report)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    return report


def _design_once(adapter, track_id, diff, analysis, deterministic, client, seed_feedback):
    from .resolve import IntentError
    attempts = 1 if (deterministic or client is None) else 3
    feedback = seed_feedback
    design, placements, last_err = {}, None, None
    for attempt in range(attempts):
        if deterministic or client is None:
            design = deterministic_intent(analysis, diff)
        else:
            from .design import design_intent
            design = design_intent(track_id, diff, analysis, _audio_path(track_id), client,
                                  seed_feedback=feedback)
        try:
            placements = adapter.realize(design, analysis, diff)   # resolve inside
            break
        except IntentError as e:                # bad designer output -> re-prompt
            last_err = e
            feedback = (f"Your previous output was rejected: {e}. Reference onsets by "
                        f"their EXACT id from the inventory, kind must be tap/hold/roll/"
                        f"mine, and never include a panel. Fix and resubmit.")
            placements = None
    if placements is None:
        raise last_err or RuntimeError("design failed")
    placements, meter, vinfo = adapter.validate_repair(placements, analysis, diff)
    metrics = adapter.qa_metrics(placements, analysis, diff)
    return {"design": design, "placements": placements, "meter": meter,
            "vinfo": vinfo, "metrics": metrics, "critic": None}


def _run_critic(track_id, diff, analysis, placements, client) -> dict:
    try:
        from .design import critic_review
        return critic_review(track_id, diff, analysis, placements, _audio_path(track_id), client)
    except Exception as e:
        return {"error": str(e)[:200], "score": 0}


def _meter_monotonic(report: dict):
    order = [d for d in ("beginner", "easy", "medium", "hard", "challenge")
             if d in report["charts"]]
    meters = [report["charts"][d]["meter"] for d in order]
    report["meter_monotonic"] = all(meters[i] <= meters[i + 1] for i in range(len(meters) - 1))


def _track_meta(track_id: str, analysis: dict) -> dict:
    base = config.TRACK_CATALOGUE.get(track_id, track_id)
    title, artist = config.TRACK_META.get(track_id, (base, "beatforge"))
    return {"title": title, "artist": artist, "music": f"{base}.ogg"}


def _audio_path(track_id: str) -> str:
    base = config.TRACK_CATALOGUE.get(track_id, track_id)
    for root in (config.TRACKS_PUB, config.TRACKS_SRC):
        p = root / f"{base}.ogg"
        if p.exists():
            return str(p)
    raise FileNotFoundError(track_id)
