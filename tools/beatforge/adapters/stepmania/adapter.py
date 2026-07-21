"""adapter.py — StepManiaAdapter: the TargetAdapter for StepMania dance-single
(STEPFORGE §2). Ties design (intent) -> realize (panels) -> validate/repair ->
serialize (simfile) -> QA, touching nothing outside adapters/stepmania/.
"""
from __future__ import annotations

import json
from pathlib import Path

from ... import config, ledger
from ...analyze import analyze_track
from . import footflow as ff
from . import qa as sm_qa
from .density import DensityRepair, thin_to_plan
from .difficulty import compute_meter
from .grammar import BUDGETS, DIFFICULTIES, grammar_description
from .realize import decide_jumps, realize
from .resolve import deterministic_intent, fill_gaps, resolve_intent, thin_for_difficulty
from .serialize import write_song_folder
from .validate import validate_repair


def _flow_max(placements: list, analysis: dict, difficulty: str) -> float:
    """Worst single foot-flow transition cost in this chart, measured AFTER
    validate/repair — that is the chart the gate actually judges, and repair's
    note drops change the foot path."""
    repaired = validate_repair(placements, analysis, difficulty).placements
    max_cost, _ = sm_qa._flow_costs(repaired, BUDGETS[difficulty])
    return max_cost


FLOW_CEILING = ff.DOUBLE_STEP + ff.JACK      # forbidden-tier transition


def _flow_ok(placements: list, analysis: dict, difficulty: str) -> bool:
    return _flow_max(placements, analysis, difficulty) < FLOW_CEILING + 1e-6


class StepManiaAdapter:
    name = "stepmania"
    last_density_repair = None      # set by realize(); surfaced in the QA report

    def grammar(self) -> dict:
        return grammar_description()

    def design_brief(self, analysis: dict, difficulty: str) -> str:
        from .design import designer_prompt
        return designer_prompt(difficulty, analysis)

    def realize(self, design: dict, analysis: dict, difficulty: str) -> list:
        resolved = resolve_intent(design, analysis, difficulty)
        resolved = fill_gaps(resolved, analysis, difficulty)   # no dead pauses
        resolved = thin_for_difficulty(resolved, analysis, difficulty)  # tier envelope
        budget, meter = BUDGETS[difficulty], analysis.get("meter", 4)

        # REQ-R2-DYN-03: shape density BEFORE the foot-flow DP runs, so the DP
        # re-solves alternation over the survivors rather than having notes
        # deleted out from under a path it already committed to.
        rep = thin_to_plan(resolved, analysis, difficulty)
        if not rep.dropped and not rep.added:
            # Nothing to weigh up — skip the second DP solve and the two extra
            # validate passes the flow guard would otherwise cost.
            self.last_density_repair = rep
            return self._realize_notes(rep.notes, budget, meter)

        base = self._realize_notes(list(resolved), budget, meter)
        shaped = self._realize_notes(rep.notes, budget, meter)

        # SACRED-03 outranks the dynamics target. Shaping re-solves flow rather
        # than breaking it, but re-solving over a different note set can still
        # land a chart the other side of the forbidden-tier ceiling. Measured
        # over the 13-song benchmark, shaping fixed the flow gate on 7 charts and
        # broke it on 6 — a net gain that SACRED-03 nonetheless does not permit,
        # because its bar is *zero* charts with forbidden-tier transitions. So
        # when shaping would newly break the ceiling, the unshaped chart wins and
        # that chart simply forgoes its density gain.
        # RATCHET (R3): shaping may never make foot flow worse. R2 used the weaker
        # rule "reject only if shaping newly crosses the ceiling", which let flow
        # degrade freely on charts that were already over it — and the real pack
        # measured the damage: the `easy` flow gate fell 75% -> 25% and
        # flow_cost_max nearly doubled. Pad comfort is the product; density is a
        # target. When they conflict, comfort wins.
        if (_flow_max(shaped, analysis, difficulty)
                <= _flow_max(base, analysis, difficulty) + 1e-6):
            self.last_density_repair = rep
            return shaped
        self.last_density_repair = DensityRepair(
            notes=list(resolved), spans=rep.spans, ok=False)
        return base

    @staticmethod
    def _realize_notes(notes: list, budget, meter: int) -> list:
        decide_jumps(notes, budget, meter)
        return realize(notes, budget, meter)

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
    # Every model call and compute unit under this block is attributed to this
    # song and target in build/cost/<song>/cost_ledger.jsonl (REQ-R2-COST-01).
    with ledger.stage("song", song=track_id, target="stepmania"):
        return _build_song(track_id, opts, difficulties, deterministic, client)


def _build_song(track_id, opts, difficulties, deterministic, client) -> dict:
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
        # Progress is printed per stage: a 5-difficulty song is ~30min of model
        # calls, and a silent process is indistinguishable from a hung one — both
        # to a human tailing the log and to the batch watchdog.
        print(f"    [{diff}] designing…", flush=True)
        best = _design_once(adapter, track_id, diff, analysis, deterministic, client, None)
        (out_dir / f"{diff}.design.json").write_text(json.dumps(best["design"], indent=2))
        print(f"    [{diff}] design ok — {len(best['placements'])} notes", flush=True)

        # critic (Author≠Judge, REQ-SM-13) + one targeted revision below the ship
        # threshold, then human-review flag. Gemini path only.
        if not deterministic and client is not None:
            print(f"    [{diff}] critiquing…", flush=True)
            best["critic"] = _run_critic(track_id, diff, analysis, best["placements"],
                                         client, metrics=best["metrics"])
            if float((best["critic"] or {}).get("score", 0)) < 7:
                print(f"    [{diff}] critic scored "
                      f"{(best['critic'] or {}).get('score')} (<7) — revising once…", flush=True)
                issues = "; ".join(f"{i.get('where','')}: {i.get('problem','')}"
                                   for i in (best["critic"] or {}).get("issues", []))
                revised = _design_once(adapter, track_id, diff, analysis, False, client,
                                       f"A critic raised these issues — fix them while keeping "
                                       f"every budget rule: {issues}")
                revised["critic"] = _run_critic(track_id, diff, analysis,
                                                revised["placements"], client,
                                                pass_no=2, metrics=revised["metrics"])
                if float(revised["critic"].get("score", 0)) >= float(best["critic"].get("score", 0)):
                    best = revised
                if float(best["critic"].get("score", 0)) < 7:
                    best["critic"]["human_review"] = True
            (out_dir / f"{diff}.critic.json").write_text(json.dumps(best["critic"], indent=2))

        meter, placements = best["meter"], best["placements"]
        per_difficulty[diff] = (meter, placements)
        print(f"    [{diff}] rendering previews…", flush=True)
        previews = sm_qa.render_previews(placements, analysis, _audio_path(track_id), out_dir / diff)
        print(f"    [{diff}] DONE — meter {meter}, {len(placements)} notes, "
              f"critic {(best.get('critic') or {}).get('score', 'n/a')}", flush=True)
        report["charts"][diff] = {
            "notes": len(placements), "meter": meter,
            "jumps": sum(1 for p in placements if len(p.panels) > 1),
            "holds": sum(1 for p in placements if p.hold_beats),
            "repaired": best["vinfo"]["original"] - len(placements),
            "repair_ok": best["vinfo"]["ok"], "critic": best.get("critic"),
            "previews": previews, "metrics": best["metrics"],
            # REQ-R2-DYN-03/04: the density plan's verdict and the measured
            # Spearman are first-class in the QA report, per chart.
            "density": best.get("density"),
            "density_energy_spearman": best["metrics"].get("density_energy_spearman")}

    files = adapter.serialize(per_difficulty, analysis, track_id, out_dir)
    report["files"] = files
    report["out"] = str(out_dir.relative_to(config.REPO_ROOT))
    _meter_monotonic(report)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    return report


def _design_once(adapter, track_id, diff, analysis, deterministic, client, seed_feedback):
    from . import density as sm_density
    from .resolve import IntentError
    attempts = 1 if (deterministic or client is None) else 3
    feedback = seed_feedback
    design, placements, last_err = {}, None, None
    for attempt in range(attempts):
        if deterministic or client is None:
            design = deterministic_intent(analysis, diff)
        else:
            from .design import design_intent
            # A re-prompt is a separate, separately-billed stage: the autopsy asks
            # for the DISTRIBUTION of calls per chart, which collapses to a useless
            # average if retries hide inside the "designer" bucket.
            stage_name = "designer" if (attempt == 0 and not seed_feedback) else "reprompt"
            with ledger.stage(stage_name, difficulty=diff, attempt=attempt + 1):
                design = design_intent(track_id, diff, analysis, _audio_path(track_id),
                                       client, seed_feedback=feedback)
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
    # Capture the repair record for THIS realize now. The density re-prompt below
    # may call realize() again, overwriting the adapter's scratch field — and if
    # its revision is rejected we would otherwise report the discarded chart's
    # thin/fill counts against the chart we actually kept.
    repair = getattr(adapter, "last_density_repair", None)

    # REQ-R2-DYN-03: score the REALIZED chart against the density plan. Thinning
    # already handled over-dense spans; what can remain is under-dense ones, and
    # those get exactly ONE phrase-scoped re-prompt — not a whole-chart re-design,
    # which per the cost autopsy is the single most expensive move available and
    # would throw away the phrases that were already right.
    dreport = sm_density.measure(placements, analysis, diff)
    if (not deterministic and client is not None
            and not sm_density.gate_pass(dreport) and not seed_feedback):
        note = sm_density.reprompt_note(dreport)
        if note:
            print(f"    [{diff}] density under budget in "
                  f"{len(dreport['under_dense'])} phrase(s) — one scoped re-prompt…",
                  flush=True)
            try:
                from .design import design_intent
                with ledger.stage("reprompt_density", difficulty=diff, attempt=1):
                    redesign = design_intent(track_id, diff, analysis,
                                             _audio_path(track_id), client,
                                             seed_feedback=note)
                rp = adapter.realize(redesign, analysis, diff)
                rp, rmeter, rvinfo = adapter.validate_repair(rp, analysis, diff)
                rdreport = sm_density.measure(rp, analysis, diff)
                # Keep the revision only if it genuinely honours the plan better;
                # a re-prompt that made things worse is not an improvement.
                if rdreport["in_band_frac"] > dreport["in_band_frac"]:
                    design, placements, meter, vinfo = redesign, rp, rmeter, rvinfo
                    dreport = rdreport
                    repair = getattr(adapter, "last_density_repair", None)
            except Exception as e:               # a failed re-prompt keeps the original
                print(f"    [{diff}] density re-prompt failed ({e}); keeping original",
                      flush=True)

    metrics = adapter.qa_metrics(placements, analysis, diff)
    metrics["density_plan"] = dreport
    repair = getattr(adapter, "last_density_repair", None)
    return {"design": design, "placements": placements, "meter": meter,
            "vinfo": vinfo, "metrics": metrics, "critic": None,
            "density": {"report": dreport,
                        "thinned": len(repair.dropped) if repair else 0,
                        "filled": len(repair.added) if repair else 0,
                        "spans": repair.spans if repair else []}}


def _run_critic(track_id, diff, analysis, placements, client, pass_no: int = 1,
                metrics: dict | None = None) -> dict:
    try:
        from .design import critic_review
        with ledger.stage("critic", difficulty=diff, attempt=pass_no):
            return critic_review(track_id, diff, analysis, placements,
                                 _audio_path(track_id), client, metrics=metrics)
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
