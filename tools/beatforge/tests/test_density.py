"""test_density.py — Workstream B dynamics (REQ-R2-DYN-01/02/03).

Entirely offline and model-free, by design: the whole point of Round 2 is that
dynamics stops being a prompt instruction and becomes deterministic machinery,
so it must be testable with zero model calls — the same standard foot-flow is
held to.
"""
from __future__ import annotations

import pytest

from beatforge import config, dsp

SECTIONS = [
    {"name": "S0", "start_bar": 0, "end_bar": 4, "energy_pct": 0.3, "role_guess": "intro"},
    {"name": "S1", "start_bar": 4, "end_bar": 8, "energy_pct": 0.9, "role_guess": "drop"},
]


# --------------------------------------------------------------------------- #
# REQ-R2-DYN-01 — the plan itself
# --------------------------------------------------------------------------- #
def test_flat_song_yields_a_flat_plan():
    """No energy contrast means no shape to follow. Inventing one would make the
    designer fabricate dynamics the music does not have."""
    plan = dsp.density_plan([0.5] * 8, SECTIONS, 120.0)
    fracs = {b["target_frac"] for b in plan["per_bar"]}
    assert len(fracs) == 1
    assert plan["flat"] is True


def test_build_drop_song_rises_monotonically_then_peaks():
    curve = [0.1, 0.2, 0.35, 0.5, 0.7, 0.85, 1.0, 0.6]
    plan = dsp.density_plan(curve, SECTIONS, 120.0)
    fracs = [b["target_frac"] for b in plan["per_bar"]]
    assert fracs[:7] == sorted(fracs[:7])          # monotone rise into the drop
    assert fracs[6] == max(fracs)                  # peak at the loudest bar
    assert fracs[7] < fracs[6]                     # and it comes back down


def test_plan_is_strictly_monotone_in_energy():
    """The gate is a RANK correlation. A plan whose ordering disagrees with the
    energy ordering cannot score well however musical it sounds — so this is the
    property that actually has to hold."""
    curve = [0.9, 0.1, 0.5, 0.3, 0.7, 0.2, 1.0, 0.4]
    plan = dsp.density_plan(curve, SECTIONS, 120.0)
    pairs = sorted((b["energy"], b["target_frac"]) for b in plan["per_bar"])
    fracs = [f for _, f in pairs]
    assert fracs == sorted(fracs)


def test_plan_is_difficulty_scaled():
    plan = dsp.density_plan([0.1, 0.5, 1.0], SECTIONS, 120.0)
    bar = plan["per_bar"][2]
    order = ["beginner", "easy", "medium", "hard", "challenge"]
    targets = [bar["target_notes"][t] for t in order]
    assert targets == sorted(targets)              # harder tier -> denser
    assert targets[0] < targets[-1]


def test_quiet_bars_still_get_a_floor_not_silence():
    """Dynamics must not be bought with dead air — the no-dead-pause rule predates
    Round 2 and outranks the correlation."""
    plan = dsp.density_plan([0.0, 1.0], SECTIONS, 120.0)
    quiet = plan["per_bar"][0]
    assert quiet["target_frac"] == pytest.approx(config.DENSITY_PLAN_FLOOR)
    assert quiet["target_notes"]["hard"] > 0
    assert quiet["band"]["hard"][0] >= 0


def test_band_brackets_the_target():
    plan = dsp.density_plan([0.2, 0.9], SECTIONS, 120.0)
    for b in plan["per_bar"]:
        lo, hi = b["band"]["hard"]
        assert lo <= b["target_notes"]["hard"] <= hi
        assert lo < hi


def test_ceiling_scales_with_tempo():
    """Notes-per-bar is an NPS budget times the bar's real duration; a slow song's
    bar holds more notes at the same NPS."""
    slow = dsp.density_plan([1.0], SECTIONS, 60.0)
    fast = dsp.density_plan([1.0], SECTIONS, 180.0)
    assert slow["bar_seconds"] > fast["bar_seconds"]
    assert (slow["per_bar"][0]["target_notes"]["hard"]
            > fast["per_bar"][0]["target_notes"]["hard"])


def test_per_section_aggregates_its_bars():
    curve = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    plan = dsp.density_plan(curve, SECTIONS, 120.0)
    intro, drop = plan["per_section"]
    assert intro["role_guess"] == "intro" and drop["role_guess"] == "drop"
    assert drop["target_frac"] > intro["target_frac"]


def test_empty_energy_curve_is_survivable():
    plan = dsp.density_plan([], SECTIONS, 120.0)
    assert plan["per_bar"] == [] and plan["flat"] is True


def test_bar_band_returns_none_past_the_end_of_the_plan():
    """A chart can run a bar past the last analyzed bar; that must not raise."""
    plan = dsp.density_plan([0.5, 0.9], SECTIONS, 120.0)
    assert dsp.bar_band(plan, "hard", 0) is not None
    assert dsp.bar_band(plan, "hard", 99) is None
    assert dsp.bar_band(plan, "hard", -1) is None


def test_density_tier_nps_matches_stepmania_budgets():
    """core/ cannot import an adapter, so config.DENSITY_TIER_MAX_NPS duplicates
    grammar.BUDGETS' max_nps_4s. This test is the reason that duplication is safe:
    it fails the moment the two drift apart."""
    from beatforge.adapters.stepmania.grammar import BUDGETS
    for tier, budget in BUDGETS.items():
        assert config.DENSITY_TIER_MAX_NPS[tier] == budget.max_nps_4s, tier


# --------------------------------------------------------------------------- #
# REQ-R2-DYN-02 — the designer gets a budget, and the parser enforces it
# --------------------------------------------------------------------------- #
def _analysis_with_plan(make_analysis):
    a = make_analysis()
    a["density_plan"] = dsp.density_plan(a["energy_curve"], a["sections"],
                                         a["bpm"], meter=4)
    return a


def test_designer_brief_states_the_budget_as_numbers(make_analysis):
    """Round 1's brief said 'density must follow energy' in prose and the designer
    ignored it. The budget has to arrive as numbers."""
    from beatforge.adapters.stepmania.design import _density_text, designer_prompt
    a = _analysis_with_plan(make_analysis)
    text = _density_text(a, "hard")
    assert "notes/bar" in text
    assert "bars" in text
    prompt = designer_prompt("hard", a)
    assert "DENSITY BUDGET" in prompt
    assert text.splitlines()[-1].strip() in prompt


def test_designer_brief_only_carries_this_tiers_bands(make_analysis):
    """The prompt is already 97% onset menu (see docs/cost-autopsy.md); the other
    four tiers' bands would be pure bulk."""
    from beatforge.adapters.stepmania.design import _density_view
    view = _density_view(_analysis_with_plan(make_analysis), "easy")
    assert view["tier"] == "easy"
    assert all(set(s) == {"start_bar", "end_bar", "role", "min", "max", "target"}
               for s in view["sections"])


def test_parser_rejects_a_phrase_declaring_out_of_band_density(make_analysis):
    from beatforge.adapters.stepmania.resolve import IntentError, resolve_intent
    a = _analysis_with_plan(make_analysis)
    band = dsp.range_band(a["density_plan"], "hard", 4, 12)
    assert band is not None
    design = {"notes": [{"ref": "p000", "kind": "tap"}],
              "phrases": [{"start_bar": 4, "end_bar": 12, "texture": "stream",
                           "density": band[1] * 3 + 10}]}
    with pytest.raises(IntentError, match="outside the allowed band"):
        resolve_intent(design, a, "hard")


def test_parser_accepts_a_phrase_inside_the_band(make_analysis):
    from beatforge.adapters.stepmania.resolve import resolve_intent
    a = _analysis_with_plan(make_analysis)
    lo, hi, target = dsp.range_band(a["density_plan"], "hard", 4, 12)
    design = {"notes": [{"ref": "p000", "kind": "tap"}],
              "phrases": [{"start_bar": 4, "end_bar": 12, "texture": "stream",
                           "density": target}]}
    assert len(resolve_intent(design, a, "hard")) == 1


def test_phrase_without_a_declared_density_is_still_allowed(make_analysis):
    """Omission is fine — the repair pass still enforces the plan. Only an
    explicit out-of-band DECLARATION is a rejection."""
    from beatforge.adapters.stepmania.resolve import resolve_intent
    a = _analysis_with_plan(make_analysis)
    design = {"notes": [{"ref": "p000", "kind": "tap"}],
              "phrases": [{"start_bar": 4, "end_bar": 12, "texture": "stream"}]}
    assert len(resolve_intent(design, a, "hard")) == 1


def test_parser_rejects_a_non_numeric_density(make_analysis):
    from beatforge.adapters.stepmania.resolve import IntentError, resolve_intent
    a = _analysis_with_plan(make_analysis)
    design = {"notes": [], "phrases": [{"start_bar": 4, "end_bar": 12,
                                        "density": "lots"}]}
    with pytest.raises(IntentError, match="must be a number"):
        resolve_intent(design, a, "hard")


def test_deterministic_intent_declares_density_from_the_plan(make_analysis):
    """The no-LLM path meets the same contract, so the contract is testable
    without spending a cent."""
    from beatforge.adapters.stepmania.resolve import deterministic_intent, resolve_intent
    a = _analysis_with_plan(make_analysis)
    design = deterministic_intent(a, "hard")
    assert any("density" in ph for ph in design["phrases"])
    resolve_intent(design, a, "hard")          # its own output must validate


# --------------------------------------------------------------------------- #
# REQ-R2-DYN-03 — deterministic density repair
# --------------------------------------------------------------------------- #
def _note(beat, kind="tap", **kw):
    from beatforge.adapters.stepmania.realize import ResolvedNote
    return ResolvedNote(beat=float(beat), kind=kind, phrase={}, **kw)


def test_over_dense_bar_is_thinned_to_the_plan(make_analysis):
    from beatforge.adapters.stepmania.density import thin_to_plan
    a = _analysis_with_plan(make_analysis)
    # 24 notes crammed into bar 0 (beats 0..3.75), far over any tier's target
    notes = [_note(i * 0.125) for i in range(24)]
    rep = thin_to_plan(notes, a, "easy")
    target = a["density_plan"]["per_bar"][0]["target_notes"]["easy"]
    # Enforcement is PER BAR, so assert on bar 0 — the rest of the chart is
    # simultaneously being topped up from the onset pool.
    in_bar_0 = [n for n in rep.notes if int(n.beat // 4) == 0]
    assert len(in_bar_0) <= max(1, round(target))
    assert len(rep.dropped) > 0


def test_thinning_drops_the_lowest_strength_notes_first(make_analysis):
    """Weakest first is the whole point: the chart should keep the transients a
    listener actually hears."""
    from beatforge.adapters.stepmania.density import thin_to_plan
    a = make_analysis(n_onsets=0, n_sustain=0)
    # bar 0 gets four onsets of clearly separated strength
    a["onsets"] = [
        {"id": f"p{i}", "time": 0.0, "nearest_beat": float(i) * 0.5,
         "snap_error_ms": 0.0, "strength": s, "bands": {}, "source": "mix_perc",
         "sustain": False, "sustain_beats": 0.0}
        for i, s in enumerate([0.1, 0.9, 0.2, 0.8])]
    a["energy_curve"] = [0.0]
    a["sections"] = [{"name": "S0", "start_bar": 0, "end_bar": 1,
                      "energy_pct": 0.0, "role_guess": "intro"}]
    a["density_plan"] = dsp.density_plan(a["energy_curve"], a["sections"], a["bpm"])
    notes = [_note(i * 0.5) for i in range(4)]
    rep = thin_to_plan(notes, a, "beginner")
    kept = {round(n.beat, 3) for n in rep.notes}
    # the two strongest onsets sit at beats 0.5 and 1.5
    assert 0.5 in kept
    assert 0.0 not in kept        # weakest (0.1) went first


def test_thinning_never_removes_holds_or_rolls(make_analysis):
    """Deleting a hold would drop a head+tail pair, and Round 1 already
    under-produces holds (8.9% vs AutoStepper's 17.3%)."""
    from beatforge.adapters.stepmania.density import thin_to_plan
    a = _analysis_with_plan(make_analysis)
    notes = ([_note(i * 0.125) for i in range(20)]
             + [_note(0.5, "hold", hold_beats=2.0), _note(1.5, "roll", hold_beats=2.0)])
    rep = thin_to_plan(notes, a, "easy")
    kinds = [n.kind for n in rep.notes]
    assert kinds.count("hold") == 1 and kinds.count("roll") == 1


def test_under_dense_bar_is_filled_only_from_real_onsets(make_analysis):
    """Fill comes from measured transients, never invented ones — otherwise the
    correlation is bought with notes that aren't on the music (SACRED-02)."""
    from beatforge.adapters.stepmania.density import thin_to_plan
    a = _analysis_with_plan(make_analysis)
    onset_beats = {round(float(o["nearest_beat"]), 3) for o in a["onsets"]}
    rep = thin_to_plan([_note(8.0)], a, "challenge")
    assert len(rep.notes) > 1                       # it did top the bar up
    for beat in rep.added:
        assert beat in onset_beats


def test_fill_stops_when_the_onset_pool_is_empty(make_analysis):
    """A bar with nothing to add stays under target and gets reported, rather
    than being padded with fabricated notes."""
    from beatforge.adapters.stepmania.density import thin_to_plan
    a = _analysis_with_plan(make_analysis)
    a["onsets"] = []
    rep = thin_to_plan([_note(8.0)], a, "challenge")
    assert rep.added == []


def test_repair_does_not_introduce_forbidden_tier_flow(make_analysis):
    """SACRED-03. Thinning runs before the foot-flow DP precisely so the DP can
    re-solve alternation over the survivors."""
    from beatforge.adapters.stepmania import footflow as ff
    from beatforge.adapters.stepmania.density import thin_to_plan
    from beatforge.adapters.stepmania.grammar import BUDGETS
    from beatforge.adapters.stepmania.qa import chart_metrics
    from beatforge.adapters.stepmania.realize import decide_jumps, realize
    a = _analysis_with_plan(make_analysis)
    notes = [_note(4 + i * 0.25) for i in range(64)]
    rep = thin_to_plan(notes, a, "hard")
    decide_jumps(rep.notes, BUDGETS["hard"], 4)
    placements = realize(rep.notes, BUDGETS["hard"], 4)
    metrics = chart_metrics(placements, a, "hard")
    assert metrics["flow_cost_max"] < ff.DOUBLE_STEP + ff.JACK
    assert metrics["gates"]["flow_ceiling"] is True


def test_measure_flags_under_dense_spans_and_builds_a_scoped_reprompt(make_analysis):
    """The re-prompt names the phrases, not the chart: a whole-chart re-design is
    the most expensive single move in the pipeline (see docs/cost-autopsy.md)."""
    from beatforge.adapters.stepmania.density import measure, reprompt_note
    from beatforge.adapters.stepmania.quantize import Placement
    a = _analysis_with_plan(make_analysis)
    report = measure([Placement(4.0, (0,))], a, "hard")     # one note, whole song
    assert report["under_dense"]
    note = reprompt_note(report)
    assert note is not None
    assert "ONLY these phrases" in note
    assert "bars" in note and "notes/bar" in note


def test_reprompt_note_is_none_when_nothing_is_under_dense(make_analysis):
    from beatforge.adapters.stepmania.density import reprompt_note
    assert reprompt_note({"under_dense": [], "plan_available": True}) is None


def test_gate_passes_when_there_is_no_plan_to_judge_against():
    from beatforge.adapters.stepmania.density import gate_pass
    assert gate_pass({"plan_available": False}) is True


def test_analysis_carries_density_plan_additively(click_wav):
    """REQ-R2-DYN-01 accept: analysis.json contains density_plan. REQ-R2-SACRED-04:
    it is ADDITIVE — every pre-existing field is still present and unchanged."""
    analysis = dsp.analyze_signal(click_wav(bpm=128.0, dur_s=20.0))
    assert "density_plan" in analysis
    plan = analysis["density_plan"]
    assert len(plan["per_bar"]) == len(analysis["energy_curve"])
    assert set(plan["tiers"]) == set(config.DENSITY_TIER_MAX_NPS)
    for field in ("bpm", "offset", "onsets", "sections", "energy_curve",
                  "energy_cv", "beats", "downbeat_indices", "meter"):
        assert field in analysis, f"{field} disappeared — that would be a SACRED-04 breach"


def test_flow_guard_rejects_shaping_that_would_break_the_flow_ceiling(make_analysis, monkeypatch):
    """SACRED-03 outranks the dynamics target. Shaping re-solves foot flow rather
    than breaking it, but re-solving over a different note set can still land a
    chart the wrong side of the forbidden-tier ceiling. When it would, the
    unshaped chart wins and that chart forgoes its density gain.

    Measured over the benchmark: without this guard, shaping fixed the flow gate
    on 7 charts and broke it on 6. SACRED-03's bar is *zero* broken charts, so a
    net gain is not good enough.
    """
    from beatforge.adapters.stepmania import adapter as A
    a = _analysis_with_plan(make_analysis)
    # `beginner` is the tier where this fixture is genuinely over-dense after the
    # resolve/fill/thin chain, so shaping really happens and the guard really runs.
    design = {"notes": [{"ref": o["id"], "kind": "tap"} for o in a["onsets"]],
              "phrases": []}
    ad = A.StepManiaAdapter()

    # Force the verdict: the shaped candidate always "breaks" flow, the baseline
    # never does. The guard must then hand back the baseline.
    calls = {"n": 0}

    def fake_flow_ok(placements, analysis, difficulty):
        calls["n"] += 1
        return calls["n"] != 1          # first call (shaped) fails, baseline passes
    monkeypatch.setattr(A, "_flow_ok", fake_flow_ok)

    placements = ad.realize(design, a, "beginner")
    assert placements is not None
    assert calls["n"] == 2, "the guard must actually have been consulted"
    # The rejected-shaping record is marked not-ok so the QA report can see it.
    assert ad.last_density_repair.ok is False
    assert ad.last_density_repair.dropped == []   # the shaping was discarded


def test_flow_guard_keeps_shaping_when_flow_is_fine(make_analysis, monkeypatch):
    from beatforge.adapters.stepmania import adapter as A
    a = _analysis_with_plan(make_analysis)
    design = {"notes": [{"ref": o["id"], "kind": "tap"} for o in a["onsets"]],
              "phrases": []}
    ad = A.StepManiaAdapter()
    monkeypatch.setattr(A, "_flow_ok", lambda p, an, d: True)
    ad.realize(design, a, "beginner")
    assert ad.last_density_repair.ok is True
    assert ad.last_density_repair.dropped, "shaping should have thinned this chart"
