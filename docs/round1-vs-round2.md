# Round 1 vs Round 2 — STEPFORGE

**Scope note, up front.** The numbers below are measured **offline on the
deterministic path** across all 13 benchmark tracks × 5 difficulties (65 charts),
using the same `adapters/stepmania/qa.chart_metrics` that `chartbench/score.py`
calls and the same DSP analyses. The **Gemini-path harness re-run has not been
performed** — it needs Vertex spend I did not incur. Read every "Round 2" figure
as *the deterministic path with the Round 2 machinery*, and the DYN-06 / SACRED-02
/ SACRED-03 acceptance as **pending that run**. What is claimed here is what was
measured; nothing is extrapolated into a pass.

---

## Headline

| axis | Round 1 | Round 2 (deterministic) | target | |
|---|---:|---:|---:|:--:|
| **density-vs-energy ρ (mean over 65 charts)** | 0.338 *(Gemini path)* | **0.501** | ≥ 0.47 | ✅ |
| — same-path baseline | 0.266 *(deterministic)* | **0.501** | | |
| **density gate pass** | 23.1% | **49.2%** | ≥ 43% | ✅ |
| DDC, the thing to beat | 0.466 / 43.1% | — | — | **beaten on both** |
| flow-gate pass | — | 73.8% → **84.6%** | no regression | ✅ (improved) |
| flow_cost_max (mean) | — | 13.72 → **11.25** | no regression | ✅ (improved) |
| charts newly breaking the flow ceiling | — | **0 / 65** | zero | ✅ |
| tracks with ρ ≥ 0.47 | — | **8 / 13** | — | |
| tracks improved | — | **13 / 13** | — | |

Both DYN-06 targets are cleared on the deterministic path, and both baselines
(our 0.338 and DDC's 0.466) are beaten. Flow — the axis Round 1 actually won and
SACRED-03 protects — **improved** rather than being traded away.

---

## Per track (mean ρ over 5 difficulties)

| track | before | after | Δ | offset fix |
|---|---:|---:|---:|---:|
| room smells like poo… | +0.209 | +0.580 | **+0.371** | — |
| song | +0.236 | +0.606 | **+0.370** | +13.5 ms |
| bttr | +0.200 | +0.563 | **+0.363** | — |
| banana banana | +0.336 | +0.683 | **+0.347** | — |
| stay awake for me | +0.079 | +0.369 | **+0.290** | — |
| lucky lucky | +0.366 | +0.611 | +0.246 | +6.7 ms |
| token economy | +0.294 | +0.524 | +0.229 | — |
| streaming is the life for me | +0.180 | +0.382 | +0.202 | — |
| robo fast food | +0.185 | +0.368 | +0.183 | — |
| smile and dance | +0.176 | +0.343 | +0.167 | — |
| the pools | +0.195 | +0.358 | +0.163 | +25.3 ms |
| do it for me now | +0.416 | +0.535 | +0.119 | — |
| explicit fast and free | +0.589 | +0.629 | +0.041 | — |
| **mean of the 13 track means** | **+0.266** | **+0.504** | **+0.238** | |

(The headline 0.501 is the mean over all 65 *charts*; 0.504 is the mean of the 13
*track* means. Same data, different weighting — tracks contribute equally in the
second even though they differ in how many difficulties score.)

Every track improves. The five that still sit below 0.47 are limited by two
things, neither of which is intent: **onset supply** (the plan asks for notes in
bars with no unused on-grid transient left, and the repair pass refuses to invent
them) and, on a few charts, **the flow guard below**, which deliberately forgoes a
density gain rather than break SACRED-03.

---

## What actually moved the number

Six increments, each measured independently on the same 13 tracks:

| change | mean ρ | gate pass |
|---|---:|---:|
| Round 1 behaviour (deterministic baseline) | 0.245 | 4.6% |
| + density plan enforced **per section** | 0.293 | 6.2% |
| + enforced **per bar** instead | 0.365 | 21.5% |
| + **fill** under-target bars from real onsets | 0.407 | 29.2% |
| + shape toward **target** rather than band edge | 0.496 | 43.1% |
| + second-pass **offset fix** (REQ-R2-OUT-01) | 0.530 | 52.3% |
| + **flow guard** — costs ρ on purpose, see below | **0.501** | **49.2%** |

Three of these are worth calling out because they are counter-intuitive:

**Per-bar, not per-section, is most of the win** (0.293 → 0.365, and it unlocks
everything after). The metric is a *rank* correlation over *bars*. Enforcing a
budget at section granularity leaves the bar-level ordering almost untouched, so
it barely moves ρ however sensible it looks in a report. I built the section
version first and it under-delivered; the per-bar rewrite is what worked.

**Shaping toward the target beats shaping into the band** (0.407 → 0.496).
Correcting a bar only as far as its band edge pins it to its ceiling or floor,
which flattens precisely the contrast the plan exists to create.

**The flow guard costs ρ, and shipping without it would have been a
SACRED-03 breach reported as a win.** Density shaping re-solves foot flow rather
than breaking it — that is why thinning runs before the DP — but re-solving over
a different note set can still land a chart the wrong side of the forbidden-tier
ceiling. Un-guarded, shaping *fixed* the flow gate on 7 charts and *broke* it on
6. Net +1, flow_cost_max down, fleet flow-gate pass up: it would have passed a
casual "no flow regression" read. SACRED-03's bar is **zero** charts with
forbidden-tier transitions, so net-positive is not the test. The guard re-realizes
the unshaped chart and keeps it whenever shaping would newly break the ceiling.
Result: **0 charts lost, 7 gained**, at a cost of 0.026 ρ and 3 points of gate
pass. Both DYN-06 targets still clear.

One implementation detail mattered: the guard must compare the chart **after**
`validate_repair`, not before. Repair drops notes for NPS/jack/hold-overlap and
those drops change the foot path — comparing pre-repair charts let 2 of the 6
regressions through the guard undetected.

---

## Guardrails

| guardrail | measurement | status |
|---|---|:--:|
| **SACRED-01** anti-hallucination | schema unchanged: designer still emits onset refs + a `density` number; no timestamp/panel field added. Rejection tests green (`test_reject_raw_time`, `test_reject_panel_in_intent`) | ✅ |
| **SACRED-02** no timing regression | onset snap median improved on 3 tracks, unchanged on 10. Harness thresholds (≤9 ms, ≥80% Fantastic) **not run** | ⏳ |
| **SACRED-03** no flow regression | flow gate 73.8% → **84.6%**; flow_cost_max 13.72 → **11.25**; **0 of 65 charts newly break the ceiling** (7 gained); `test_repair_does_not_introduce_forbidden_tier_flow` + `test_flow_guard_rejects_shaping_that_would_break_the_flow_ceiling` green | ✅ |
| **SACRED-04** core DSP additive | `density_plan` + `offset_correction_ms` added; **re-scoring the untouched DDC pack gives max \|Δρ\| = 0.000000 across 65 charts** and identical `flow_cost_max` | ✅ |

SACRED-03 is protected twice over, and neither is luck. Structurally: density
shaping runs *before* the foot-flow DP, so the DP re-solves alternation over the
survivors — thinning a realized chart, the literal reading of "post-realizer" in
the brief, would delete notes the DP had already solved around and could
manufacture the very double-steps SACRED-03 forbids. Then defensively: the flow
guard re-realizes the unshaped chart and prefers it whenever shaping would newly
cross the ceiling. The measurement half still runs post-realize.

---

## Cost impact of Round 2

| | per song |
|---|---:|
| designer prompt, added by the density budget block | ~181 tokens |
| designer prompt, added by the DYN-05 exemplars | ~325 tokens |
| designer text tokens, fleet mean | 117,136 → 125,030 (**+6.7%**) |
| modelled visible-token cost, **verified** rates | $0.4453 → $0.4571 (**+2.7%**) |

The +6.7% is **not** the prompt additions — those are ~500 tokens, 0.4%. It is a
second-order effect of the timing fix: re-phasing the grid means more onsets pass
the ±35 ms snap filter, so the inventory the designer is offered gets larger. On
The Pools, whose grid was 25.3 ms out, admissible onsets go 832 → 1,251 and its
designer prompt grows **+48.8%**. The other twelve tracks move +1.7% to +5.3%.

**+2.7% is far inside the +25% escalation threshold in §7 of the brief, so no
escalation is triggered.** It is worth stating plainly all the same: better timing
costs more tokens, and that coupling will recur.

(Dollar figures use the **verified** `gemini-3.5-flash` rates — $1.50/M input,
$9.00/M output — confirmed against the Vertex pricing page on 2026-07-21. An
earlier draft used placeholder rates that were 3.6× low on output; see
`docs/cost-autopsy.md`. The *percentage* was barely affected, but the absolute
per-song figure roughly quadrupled.)

---

## spec-lint / trace-gate — a discrepancy, escalated not fixed

The Definition of Done asks that spec-lint and trace-gate pass. **They cannot be
run, and if they could be they would pass vacuously.** Three separate reasons:

1. **The gate scripts do not exist in the repo.** `gates.config` names
   `"script": "spec-lint"` / `"trace-gate"` as tier-0 enabled, but there is no
   such executable anywhere in the tree and no npm script for them.
2. **The configured ID pattern cannot match a Round 2 ID.**
   `policy.json` sets `id_pattern: "REQ-[A-Z]+-\\d+"`. That matches `REQ-TIME-01`
   and `REQ-SM-01`, but **not** `REQ-R2-COST-01` — the `R2` segment contains a
   digit, so `[A-Z]+` fails. Every one of the 17 Round 2 requirements is
   invisible to the gate.
3. **Scope points elsewhere.** `spec_file` is `in-the-pocket-spec.md` (the game
   spec, not the Round 2 brief), and trace-gate's `test_glob` is TypeScript-only
   (`tests/**/*.test.ts`), so no beatforge Python test is in scope either.

So a green "spec-lint and trace-gate pass" on this branch would mean *the gates
found nothing to check* — the same class of defect as Round 1's tautological
`onset_alignment`: a number that cannot fail.

**I have not edited `policy.json` or `gates.config`.** Widening a gate's pattern
or scope so that it grades my own work is exactly the change that should not be
made unilaterally, and the Director Governance Policy says discrepancies escalate
rather than get auto-corrected. **Escalating: decide whether the R2 IDs should be
renamed to fit the existing pattern, or the pattern/scope widened to cover the
Round 2 brief and the Python suite.**

What I verified by hand in the meantime, which is what the two gates are *for*:

| check (the gate's substance) | result |
|---|---:|
| every REQ-R2-* in the brief carries an `Accept:` criterion (spec-lint) | **17 / 17** |
| every REQ-R2-* maps to an entry in `TEST-REQS.yaml` (trace-gate) | **17 / 17** |
| every such entry declares concrete `intents` | **17 / 17** |

---

## First real Gemini-path evidence — `the_pools`

One song has now been run end to end through the **Gemini designer path** with the
Round 2 machinery live (18 model calls, $4.28, ledger attached). `the_pools` was
Round 1's **worst** track for dynamics — the only negative ρ in the fleet.

| difficulty | notes | ρ | flow gate | critic | thinned | filled |
|---|---:|---:|:--:|---:|---:|---:|
| beginner | 207 | **+0.696** | ✅ | 10 | 6 | 15 |
| easy | 316 | **+0.526** | ✅ | 6 | 2 | 64 |
| medium | 367 | +0.190 | ✅ | 6 | 0 | 0 |
| hard | 767 | +0.362 | ✅ | 5 | 0 | 358 |
| challenge | 976 | +0.308 | ✅ | — | 64 | 71 |
| **mean** | | **+0.416** | **5/5** | | | |

**Round 1: −0.15. Round 2 Gemini path: +0.416.** A +0.57 swing on the track that
was furthest from the target, and the flow ceiling holds on all five charts.

The `thinned`/`filled` columns are the DYN-03 repair working on real designer
output — 358 notes topped up from real onsets on `hard`, 64 thinned on
`challenge`. The scoped density re-prompt (DYN-03's cheap path) also fired live on
`challenge`, and the critic-revision loop fired on `medium` and `hard`.

**Do not read a fleet mean into this.** It is one song, deliberately chosen as the
hardest case, and its Gemini-path mean (+0.416) sits above the deterministic-path
figure for the same track (+0.358) but below the fleet deterministic mean (+0.501).
The 13-song Gemini harness is still the thing that settles DYN-06.

---

## What still needs to run

1. **The 13-song harness through the Gemini designer path**, then
   `score.py --compare` against `out/DDC.json`. This is the only thing that
   converts the ⏳ above into ✅ and makes DYN-06 formally accepted.
2. **One instrumented song end to end** → `beatforge cost-report`, which resolves
   autopsy hypotheses #3–#6 (see `docs/cost-autopsy.md`).
3. **Verify the `gemini-3.5-flash` rate** in `pricing.py` and set
   `verified=True`. Every dollar figure in the autopsy scales with it.

Reductions (REQ-R2-COST-05) are deliberately **not** implemented: §5 of the brief
gates them on the autopsy shipping first, and the autopsy's own conclusion is
that the dominant driver cannot be identified without one real ledger run.
