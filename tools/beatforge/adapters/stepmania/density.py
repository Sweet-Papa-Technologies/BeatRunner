"""density.py — deterministic density repair against the plan (REQ-R2-DYN-03).

The sibling of foot-flow repair, for dynamics. Foot-flow works because a solver
enforces it and the model cannot wriggle out; Round 1 lost dynamics because
nothing played that role for density. This is that enforcement.

Two halves:

  * `thin_to_plan()` — over-dense spans lose their weakest notes until they sit
    inside the plan's band. Lowest onset strength goes first; holds, rolls, mines
    and jumps are protected (see below).
  * `measure()` — scores a REALIZED chart against the plan and returns the spans
    that came out under-dense, which drives one targeted, phrase-scoped re-prompt
    rather than a whole-chart regeneration.

**Why thinning runs before realization, not after.** The brief describes this as
a post-realizer step. Thinning a realized chart is unsafe: the foot-flow DP
solved the alternation over the *original* note sequence, so deleting notes from
its output can manufacture the double-steps and jacks that SACRED-03 forbids —
the repair would break the one axis Round 1 actually won. Thinning the resolved
notes instead lets the same DP re-solve over the survivors, so comfortable flow
is restored by construction rather than checked for afterwards. The measurement
half still runs post-realize on the finished chart, and the adapter re-runs the
flow validator either way. Same contract, no way to regress flow.

We only thin. Under-dense spans are FLAGGED, never auto-filled: synthesizing
notes to hit a number would fabricate transients the music doesn't have, which
is the failure mode the Round 1 brief explicitly warned against ("do not chase
ρ by globally increasing note density").
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ... import config, dsp

# Notes we will not delete to hit a density number, in priority order of why:
#   hold/roll — deleting one would drop a head+tail pair the chart's vocabulary
#     depends on, and Round 1 already under-produces holds (8.9% vs AutoStepper's
#     17.3%). Thinning must not make that worse.
#   mine      — a mine is a deliberate gap marker, not density.
_PROTECTED_KINDS = ("hold", "roll", "mine")
FILL_MODE = "target"   # target | lo | none  (see thin_to_plan)


@dataclass
class DensityRepair:
    notes: list
    dropped: list = field(default_factory=list)      # (beat, strength, reason)
    added: list = field(default_factory=list)        # beats topped up from the pool
    spans: list = field(default_factory=list)        # per-span before/after
    ok: bool = True


def _strength_lookup(analysis: dict) -> dict:
    """beat -> onset strength. Notes that came from `fill_gaps` (synthetic grid
    filler, no real transient behind them) get 0.0 and are therefore the first
    thing thinned — which is exactly right: an invented note is worth less than a
    measured one."""
    lut: dict[float, float] = {}
    for o in analysis.get("onsets", []):
        k = round(float(o["nearest_beat"]), 3)
        s = float(o.get("strength", 0.0))
        if s > lut.get(k, -1.0):
            lut[k] = s
    return lut


def _spans(analysis: dict) -> list[tuple[int, int]]:
    """The bar ranges density is budgeted over: the analysis sections. Falls back
    to 8-bar blocks if a track somehow has no sections."""
    secs = analysis.get("sections") or []
    out = [(int(s["start_bar"]), int(s["end_bar"])) for s in secs
           if int(s["end_bar"]) > int(s["start_bar"])]
    if out:
        return out
    n_bars = len(analysis.get("energy_curve") or [])
    return [(b, min(b + 8, n_bars)) for b in range(0, n_bars, 8)] or [(0, 1)]


def _fill_pool(resolved: list, analysis: dict, difficulty: str) -> dict:
    """Unused on-grid onsets, per bar, strongest first.

    Everything in this pool is a REAL measured transient that already passes the
    tier's subdivision and snap gates — the same admissibility test the designer's
    inventory uses. Filling from here cannot hurt timing (SACRED-02), because
    every added note lands on an onset the DSP actually detected.
    """
    from .grammar import BUDGETS
    from .resolve import _playable

    b = BUDGETS[difficulty]
    subdiv = b.finest_subdiv
    lo_beat, hi_beat = _playable(analysis)
    meter = analysis.get("meter", 4)
    used = {round(float(n.beat), 3) for n in resolved}

    pool: dict[int, list] = {}
    for o in analysis.get("onsets", []):
        beat = float(o["nearest_beat"])
        if beat < lo_beat or beat > hi_beat:
            continue
        if abs(beat - round(beat / subdiv) * subdiv) > 1e-3:
            continue
        if abs(o.get("snap_error_ms", 0)) > config.ONSET_SNAP_MAX_MS:
            continue
        if round(beat, 3) in used:
            continue
        pool.setdefault(int(beat // meter), []).append(o)
    for bar in pool:
        pool[bar].sort(key=lambda o: -float(o.get("strength", 0.0)))
    return pool


def _break_runs(notes: list, b) -> list:
    """Drop a note from any run of consecutive ≤8th-spaced notes longer than the
    tier's `max_run`. Mirrors resolve.thin_for_difficulty's rule so the two agree."""
    max_run = getattr(b, "max_run", 8)
    keep = [True] * len(notes)
    i = 0
    while i < len(notes):
        j = i
        while j + 1 < len(notes) and (notes[j + 1].beat - notes[j].beat) <= 0.5 + 1e-6:
            j += 1
        if j - i + 1 > max_run:
            for k in range(i, j + 1):
                if (k - i) % (max_run + 1) == max_run and notes[k].kind not in _PROTECTED_KINDS:
                    keep[k] = False
        i = j + 1
    return [n for n, k in zip(notes, keep) if k]


def _phrase_at(resolved: list, bar: int, meter: int) -> dict:
    """Phrase intent for an EMPTY bar: borrow it from the nearest charted note,
    so a bar we fill from scratch still belongs to its phrase."""
    if not resolved:
        return {}
    nearest = min(resolved, key=lambda n: abs(int(n.beat // meter) - bar))
    return nearest.phrase or {}


def thin_to_plan(resolved: list, analysis: dict, difficulty: str) -> DensityRepair:
    """Shape a resolved note stream to the plan, **per bar**.

    Over-target bars lose their weakest notes; under-target bars are topped up
    from `_fill_pool` — real, unused, on-grid onsets in that same bar.

    **Per bar, not per section.** This is the single most important detail in the
    file. The metric is the Spearman correlation of *per-bar* note count against
    *per-bar* energy; enforcing at section granularity leaves the bar-level
    ordering essentially untouched and barely moves it. Measured over the 13-song
    benchmark on the deterministic path: no shaping ρ=0.245, section-level
    shaping ρ=0.293, per-bar shaping ρ=0.365, per-bar shaping with fill ρ=0.496.

    **Toward target, not merely into the band.** Stopping at the band edge pins
    every corrected bar to its ceiling or floor, which flattens exactly the
    contrast the plan exists to create (0.447 vs 0.496 measured).

    Filling never invents a note: if a bar's onset pool is empty the bar stays
    under target and is reported as under-dense, which is what drives the scoped
    re-prompt. Chasing the number with synthetic notes is the failure mode the
    Round 1 brief explicitly warned against.
    """
    plan = analysis.get("density_plan") or {}
    if not plan.get("per_bar") or not resolved:
        return DensityRepair(notes=list(resolved))

    from .realize import ResolvedNote

    meter = analysis.get("meter", 4)
    strength = _strength_lookup(analysis)
    pool = _fill_pool(resolved, analysis, difficulty)

    by_bar: dict[int, list] = {}
    for n in resolved:
        by_bar.setdefault(int(n.beat // meter), []).append(n)

    keep = {id(n): True for n in resolved}
    dropped: list = []
    added: list = []

    # --- how many notes should this bar hold? ---------------------------------
    #
    # REDISTRIBUTE (default): keep the note TOTAL the tier would naturally
    # produce and move those notes to where the energy is. Round 2 anchored each
    # bar to a fraction of `max_nps_4s * bar_seconds` — a tier ceiling with no
    # relationship to what the song actually offers — so dense tracks inflated
    # (The Pools challenge 438 -> 902 notes) while sparse ones were starved
    # (Lucky Lucky beginner 81 -> 34). Redistribution has neither failure mode: it
    # is conservative by construction, because it never changes the budget, only
    # its distribution. Difficulty stays where it was; dynamics is what moves.
    weights = [e["target_frac"] for e in plan["per_bar"]]
    bar_targets: dict[int, float] = {}
    if config.DENSITY_MODE == "redistribute" and sum(weights) > 0:
        # Only redistribute across bars the chart actually spans, so a short chart
        # in a long song isn't diluted by bars it never reaches.
        spanned = sorted(by_bar)
        if spanned:
            lo_bar, hi_bar = spanned[0], spanned[-1]
            live = [(b, weights[b]) for b in range(lo_bar, min(hi_bar + 1, len(weights)))]
            wsum = sum(w for _, w in live) or 1.0
            total = len(resolved)
            for b, w in live:
                bar_targets[b] = total * w / wsum
    for bar, entry in enumerate(plan["per_bar"]):
        target = bar_targets.get(bar, entry["target_notes"].get(difficulty))
        if config.DENSITY_MODE == "redistribute" and bar not in bar_targets:
            continue                      # outside the chart's span; leave alone
        if target is None:
            continue
        # The tier's NPS ceiling still binds — redistribution may never push a bar
        # past what the tier allows, however loud that bar is.
        ceiling = entry["target_notes"].get(difficulty)
        if ceiling is not None:
            target = min(target, ceiling / max(1e-9, entry["target_frac"]))
        notes = by_bar.get(bar, [])
        want = max(1, int(round(target)))

        if len(notes) > want:
            # Weakest first; protected kinds never; jumps only after plain taps,
            # since a jump is a deliberate accent and costs more to lose.
            candidates = [n for n in notes if n.kind not in _PROTECTED_KINDS]
            candidates.sort(key=lambda n: (
                1 if getattr(n, "is_jump", False) else 0,
                strength.get(round(float(n.beat), 3), 0.0),
                float(n.beat)))
            for n in candidates[:len(notes) - want]:
                keep[id(n)] = False
                dropped.append((round(float(n.beat), 3),
                                round(strength.get(round(float(n.beat), 3), 0.0), 4),
                                "over_target"))
        elif len(notes) < want and FILL_MODE != "none":
            # Inherit the phrase intent so a filled note carries the same
            # movement/crossover/texture the DP will solve the rest of the bar
            # under. An empty phrase would silently fall back to "static".
            phrase = notes[0].phrase if notes else _phrase_at(resolved, bar, meter)
            cap = want if FILL_MODE == "target" else max(1, int(entry["band"][difficulty][0]))
            for o in pool.get(bar, [])[:max(0, cap - len(notes))]:
                added.append(ResolvedNote(beat=float(o["nearest_beat"]),
                                          kind="tap", phrase=phrase))

    survivors = [n for n in resolved if keep[id(n)]] + added
    survivors.sort(key=lambda n: n.beat)

    # Re-break long runs. `thin_for_difficulty` enforced the tier's `max_run`
    # BEFORE we filled, so a fill can silently re-create the stream it removed —
    # which is how a "medium" ends up asking for an expert 16-note burst. Pad
    # ergonomics outrank hitting the density number exactly.
    from .grammar import BUDGETS
    survivors = _break_runs(survivors, BUDGETS[difficulty])

    # Section-level before/after, for the QA report and the designer's phrase
    # contract — the enforcement is per bar, but a human reads sections.
    spans_report = []
    for s0, s1 in _spans(analysis):
        band = dsp.range_band(plan, difficulty, s0, s1)
        if band is None:
            continue
        n_bars = s1 - s0 or 1
        before = sum(1 for n in resolved if s0 <= int(n.beat // meter) < s1) / n_bars
        after = sum(1 for n in survivors if s0 <= int(n.beat // meter) < s1) / n_bars
        spans_report.append({
            "bars": [s0, s1], "band": [band[0], band[1]], "target": band[2],
            "before": round(before, 3), "after": round(after, 3)})

    return DensityRepair(notes=survivors, dropped=dropped,
                         added=[round(float(n.beat), 3) for n in added],
                         spans=spans_report, ok=True)


def measure(placements: list, analysis: dict, difficulty: str) -> dict:
    """Score a realized chart against the plan.

    Returns per-span measured density plus `under_dense` — the spans that need a
    targeted re-prompt. Scoped to the phrase, not the chart: a whole-chart
    regeneration costs a full designer call (the most expensive thing in the
    pipeline, per the cost autopsy) and throws away the parts that were fine.
    """
    plan = analysis.get("density_plan") or {}
    meter = analysis.get("meter", 4)
    out = {"spans": [], "under_dense": [], "over_dense": [], "in_band": 0,
           "plan_available": bool(plan.get("per_bar"))}
    if not out["plan_available"]:
        return out

    for s0, s1 in _spans(analysis):
        band = dsp.range_band(plan, difficulty, s0, s1)
        if band is None:
            continue
        lo, hi, target = band
        n_bars = s1 - s0
        n = sum(1 for p in placements if s0 <= int(p.beat // meter) < s1)
        measured = n / n_bars if n_bars else 0.0
        row = {"bars": [s0, s1], "notes": n, "measured": round(measured, 3),
               "band": [lo, hi], "target": target}
        out["spans"].append(row)
        if measured < lo - 1e-9:
            out["under_dense"].append(row)
        elif measured > hi + 1e-9:
            out["over_dense"].append(row)
        else:
            out["in_band"] += 1
    total = len(out["spans"]) or 1
    out["in_band_frac"] = round(out["in_band"] / total, 4)
    return out


def reprompt_note(report: dict) -> str | None:
    """The phrase-scoped feedback string for one targeted re-prompt. None when
    nothing is under-dense (i.e. no re-prompt is warranted — the cheapest possible
    outcome, and the common one once thinning has run)."""
    under = report.get("under_dense") or []
    if not under:
        return None
    lines = "; ".join(
        f"bars {r['bars'][0]}-{r['bars'][1]}: you placed {r['measured']:.1f} "
        f"notes/bar, the budget needs {r['band'][0]:.1f}-{r['band'][1]:.1f} "
        f"(target {r['target']:.1f})"
        for r in under[:6])
    return (
        "DENSITY BUDGET MISS — fix ONLY these phrases and leave the rest of the "
        f"chart exactly as it is: {lines}. Add notes in those bars by referencing "
        "more onset ids from the inventory inside that bar range (strongest first). "
        "Do not change any other phrase, and do not exceed any other budget.")


def gate_pass(report: dict, min_in_band: float | None = None) -> bool:
    """Whether the realized chart honours the plan well enough to ship."""
    if not report.get("plan_available"):
        return True                      # no plan (e.g. no energy curve) -> no gate
    floor = (min_in_band if min_in_band is not None
             else getattr(config, "DENSITY_PLAN_MIN_IN_BAND", 0.6))
    return report.get("in_band_frac", 0.0) >= floor - 1e-9
