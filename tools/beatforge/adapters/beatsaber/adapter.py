"""adapter.py — BeatSaberAdapter: the TargetAdapter #2 for Beat Saber Standard
mode (SABERFORGE spec §2, REQ-ARCH-01). Ties design (intent) -> realize (parity
DP) -> validate/repair -> simulate -> serialize (v3 via JSMap) -> QA + external
referees, touching nothing outside adapters/beatsaber/.

Positioning (spec §0, REQ-POS-01..03): every output is an AI-assisted *draft* for
ChroMapper refinement — labelled in metadata, own-music-first, and there is NO
BeatSaver upload/publish path anywhere in this package.
"""
from __future__ import annotations

import json
from pathlib import Path

from ... import config
from ...analyze import analyze_track
from . import check, difficulty as diffmod, qa as bs_qa, simulate
from .grammar import BUDGETS, DIFFICULTIES, grammar_description
from .lighting import basic_lighting
from .resolve import (IntentError, deterministic_intent, resolve_intent)
from .realize import realize as realize_objects
from .serialize import AI_MARKER, write_song_folder
from .validate import validate_repair


class BeatSaberAdapter:
    name = "beatsaber"

    def grammar(self) -> dict:
        return grammar_description()

    def design_brief(self, analysis: dict, difficulty: str) -> str:
        from .design import designer_prompt
        return designer_prompt(difficulty, analysis)

    def realize(self, design: dict, analysis: dict, difficulty: str) -> list:
        resolved = resolve_intent(design, analysis, difficulty)
        return realize_objects(resolved, analysis, difficulty, BUDGETS[difficulty])

    def validate_repair(self, placements, analysis, difficulty):
        rr = validate_repair(placements, analysis, difficulty)
        return rr.objects, {"repairs": rr.repairs, "ok": rr.ok, "original": rr.original}

    def serialize(self, per_difficulty, analysis, track_id, out_dir):
        meta = _track_meta(track_id, analysis)
        return write_song_folder(meta, analysis, per_difficulty,
                                 _audio_path(track_id), Path(out_dir))

    def qa_metrics(self, placements, analysis, difficulty):
        return bs_qa.chart_metrics(placements, analysis, difficulty)


# --------------------------------------------------------------------------- #
# Orchestration (REQ-BS-13): analysis -> design -> realize -> validate ->
# simulate -> serialize -> QA + referees, one track. Deterministic by default;
# the Gemini designer + critic run only with a client.
# --------------------------------------------------------------------------- #
COPYRIGHT_CAVEAT = (
    "[saberforge] COPYRIGHT: --i-have-rights acknowledged. SABERFORGE is a "
    "mapper's drafting assistant for YOUR OWN music (paid-plan Suno / original). "
    "Mapping third-party copyrighted audio is your responsibility; these drafts "
    "are AI-assisted and are NOT for BeatSaver upload.")


def build_song(track_id: str, opts: config.RunOptions, difficulties=DIFFICULTIES,
               deterministic: bool = True, client=None, i_have_rights: bool = False) -> dict:
    if i_have_rights:
        print(COPYRIGHT_CAVEAT)
    adapter = BeatSaberAdapter()
    analysis = analyze_track(track_id, opts)
    bpm = analysis["bpm"]
    out_dir = config.SABERFORGE_DIR / config.TRACK_CATALOGUE.get(track_id, track_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    njs_table = diffmod.njs_offset_table(difficulties, bpm)
    per_difficulty = {}
    report = {"track_id": track_id, "bpm": bpm, "offset": analysis["offset"],
              "mode": "deterministic" if (deterministic or client is None) else "gemini",
              "credit": AI_MARKER, "ai_assisted": True,
              "own_music_default": True, "auto_publish": False, "charts": {}}

    for diff in difficulties:
        best = _design_once(adapter, track_id, diff, analysis, deterministic, client, None)

        if not deterministic and client is not None:
            best["critic"] = _run_critic(track_id, diff, analysis, best["objects"], client)
            if float((best["critic"] or {}).get("score", 0)) < config.CRITIC_SHIP_THRESHOLD:
                issues = "; ".join(f"{i.get('where','')}: {i.get('problem','')}"
                                   for i in (best["critic"] or {}).get("issues", []))
                revised = _design_once(adapter, track_id, diff, analysis, False, client,
                                       f"A critic raised these issues — fix them while keeping "
                                       f"every budget rule: {issues}")
                revised["critic"] = _run_critic(track_id, diff, analysis, revised["objects"], client)
                if float(revised["critic"].get("score", 0)) >= float(best["critic"].get("score", 0)):
                    best = revised
                if float(best["critic"].get("score", 0)) < config.CRITIC_SHIP_THRESHOLD:
                    best["critic"]["human_review"] = True
            (out_dir / f"{diff}.critic.json").write_text(json.dumps(best["critic"], indent=2))

        (out_dir / f"{diff}.design.json").write_text(json.dumps(best["design"], indent=2))

        njs, offset, rank = njs_table[diff]
        objs = best["objects"]
        lighting = basic_lighting(analysis)
        per_difficulty[diff] = {"difficulty": BUDGETS[diff].difficulty_name,
                                "rank": rank, "njs": njs, "offset": offset,
                                "objects": objs, "lighting": lighting}

        sim = simulate.simulate(objs, analysis)
        previews = bs_qa.render_previews(objs, analysis, _audio_path(track_id), out_dir / diff)
        report["charts"][diff] = {
            "notes": len([o for o in objs if o.kind in ("note", "arc", "chain")]),
            "bombs": sum(1 for o in objs if o.kind == "bomb"),
            "arcs": sum(1 for o in objs if o.kind == "arc"),
            "chains": sum(1 for o in objs if o.kind == "chain"),
            "njs": njs, "offset": offset, "difficulty_rank": rank,
            "repaired": best["vinfo"]["original"] - len([o for o in objs if o.kind in ("note", "arc", "chain")]),
            "repair_ok": best["vinfo"]["ok"], "simulator_clean": sim.clean,
            "forced_resets": len(sim.forced_resets),
            "critic": best.get("critic"), "previews": previews, "metrics": best["metrics"]}

    files = adapter.serialize(per_difficulty, analysis, track_id, out_dir)
    report["files"] = files.get("files", {})
    report["jsmap_verified"] = files.get("verified", False)
    report["fallback_serializer"] = files.get("fallback", False)

    # triple-referee legality (REQ-BS-09): in-core validator + simulator + external.
    externals = check.run_external_checkers(str(out_dir))
    in_core_ok = all(c["repair_ok"] for c in report["charts"].values())
    sim_clean = all(c["simulator_clean"] for c in report["charts"].values())
    report["referees"] = check.referee_summary(in_core_ok, sim_clean, externals)

    report["njs_constant"] = all(
        report["charts"][d]["njs"] == njs_table[d][0] for d in difficulties)
    report["difficulty_monotonic"] = diffmod.is_monotonic(difficulties)
    report["out"] = str(out_dir.relative_to(config.REPO_ROOT))
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    return report


def _design_once(adapter, track_id, diff, analysis, deterministic, client, seed_feedback):
    attempts = 1 if (deterministic or client is None) else config.DESIGN_MAX_ATTEMPTS
    feedback = seed_feedback
    design, objects, last_err = {}, None, None
    for _ in range(attempts):
        if deterministic or client is None:
            design = deterministic_intent(analysis, diff)
        else:
            from .design import design_intent
            design = design_intent(track_id, diff, analysis, _audio_path(track_id), client,
                                   seed_feedback=feedback)
        try:
            objects = adapter.realize(design, analysis, diff)
            break
        except IntentError as e:
            last_err = e
            feedback = (f"Your previous output was rejected: {e}. Reference onsets by "
                        f"their EXACT id or grid:<beat>, kind must be note/arc/chain/"
                        f"bomb_reset, hand must be left/right/either, and NEVER include a "
                        f"coordinate, cut direction, colour or parity. Fix and resubmit.")
            objects = None
    if objects is None:
        raise last_err or RuntimeError("design failed")
    objects, vinfo = adapter.validate_repair(objects, analysis, diff)
    metrics = adapter.qa_metrics(objects, analysis, diff)
    return {"design": design, "objects": objects, "vinfo": vinfo,
            "metrics": metrics, "critic": None}


def _run_critic(track_id, diff, analysis, objs, client) -> dict:
    try:
        from .design import critic_review
        return critic_review(track_id, diff, analysis, objs, _audio_path(track_id), client)
    except Exception as e:
        return {"error": str(e)[:200], "score": 0}


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
