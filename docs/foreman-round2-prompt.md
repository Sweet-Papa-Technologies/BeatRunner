# STEPFORGE ROUND 2 — Close the dynamics gap, open the books

**To:** FOREMAN (Director → Coder via Claude Code)
**Repo:** tools/beatforge (BEATFORGE core + adapters/stepmania)
**Governing docs:** IMPROVE.MD (Pillars), Director Governance Policy, STEPFORGE spec
**Referee:** the Round 1 benchmark harness. It is now the regression suite. Nothing ships that regresses it.

---

## 0. Context (read, do not re-derive)

Round 1 (13 songs × 5 difficulties × 3 generators, 195 charts, identical scorer and audio):

- **Won — timing:** STEPFORGE median 8ms absolute error vs real transients; 81.4% of notes inside the ±21ms ITG Fantastic window. AutoStepper 64ms, DDC 58ms.
- **Won — danceability:** flow-gate pass 63/65 charts vs DDC 8/65 and AutoStepper 0/65.
- **Lost — dynamics:** density-vs-energy Spearman ρ 0.338 mean vs DDC 0.466; gate (ρ ≥ 0.55) passed 23% of the time vs DDC 43%; DDC ahead on 10 of 13 songs. Root cause as diagnosed in the report: DDC *learned* dynamics from thousands of human charts; our designer is merely *told* in a prompt. Dynamics is currently a suggestion, not a structure.
- **Discarded as tautological:** onset alignment and BPM error (scored against our own DSP analysis). Do not cite them in any Accept criterion.
- **Known outliers:** The Pools (19ms median err, ρ −0.15), Token Economy (17ms err), Room Smells Like Poo (ρ 0.19), Bttr (ρ 0.14).

Separately: the full pipeline cost ~**$80 for 30 songs** (~$2.67/song, ~$0.53/chart at 5 difficulties). We do not currently know where that money goes. That is unacceptable observability, independent of whether the number is fine.

---

## 1. Sacred core — the Director may not trade these away

Per the Director Governance Policy, the following are constitution-level. Discrepancies escalate to me; they are never auto-"corrected."

- **REQ-R2-SACRED-01 — Anti-hallucination contract stands.** The LLM references onset IDs only. It never emits timestamps, beat numbers, or panel coordinates. No fix for dynamics may route audio analysis through an LLM.
  `Accept:` grep/trace-gate shows no schema change permitting timestamps or panels in designer output; designer-intent parser rejection tests still pass.
- **REQ-R2-SACRED-02 — No timing regression.** Re-run of the Round 1 harness on the same 13 songs: overall median timing error ≤ 9ms and Fantastic share ≥ 80%.
  `Accept:` harness report committed as artifact; both thresholds met.
- **REQ-R2-SACRED-03 — No flow regression.** Flow-gate pass ≥ 63/65; zero charts contain forbidden-tier transitions.
  `Accept:` harness report; foot-flow synthetic tests unchanged and green.
- **REQ-R2-SACRED-04 — BEATFORGE `core/` DSP analysis unchanged** except for additive outputs (new fields in analysis.json are fine; changed semantics of existing fields are not).
  `Accept:` diff review; analysis cache keys bumped only if output schema is extended.

---

## 2. Workstream A — Cost telemetry first (do this before touching dynamics)

We instrument before we optimize, and we instrument before we add the dynamics work — otherwise Round 2's own cost is unmeasurable too.

- **REQ-R2-COST-01 — Per-call ledger.** Every model call (designer, critic, re-prompts, any other Vertex call) logs: stage, song, difficulty, attempt #, model name, input tokens, output tokens, **audio/multimodal tokens separately if audio is attached**, cached-token count if context caching is in play, latency, and computed $ cost from a checked-in price table (`config/pricing.py`, editable, with a `pricing_as_of` date).
  `Accept:` running one song end-to-end produces `build/<song>/cost_ledger.jsonl` with every call present; unit test validates schema.
- **REQ-R2-COST-02 — Non-LLM compute in the ledger too.** Colab GPU minutes for Demucs/madmom (or a recorded estimate if the CLI can't report it), keyed per song, plus cache hit/miss so re-runs show $0 analysis cost.
  `Accept:` ledger distinguishes fresh-analysis vs cache-hit runs.
- **REQ-R2-COST-03 — Rollup report.** `beatforge cost-report` aggregates ledgers into: $/song, $/chart, $ by stage (analysis / designer / critic / re-prompt / other), token breakdown (text-in / audio-in / out), and top-5 most expensive calls with their prompts' byte sizes.
  `Accept:` report renders as markdown + JSON; committed for the benchmark set.
- **REQ-R2-COST-04 — The "$80 autopsy."** Using the ledger, produce `docs/cost-autopsy.md` answering, with numbers, each hypothesis — confirmed or falsified, no hand-waving:
  1. Is audio being attached to designer and/or critic calls, and what fraction of input tokens is audio? (A ~3-min track attached to every call across 5 difficulties × critic × retries would dominate everything.)
  2. How large is the serialized onset inventory per call (444–1601 onsets/song × id/strength/band/sustain), and is it resent verbatim for every difficulty and every critic pass instead of cached?
  3. How many model calls per chart, actually (designer + critic + re-prompt loop iterations)? Distribution, not average.
  4. Is any stage silently using a model other than the configured Gemini 3.5 Flash (per the prior governance incident, verify model strings in the ledger, don't trust config).
  5. Are thinking/reasoning tokens enabled anywhere, and what do they cost?
  6. What share is Colab/GPU vs Vertex?
  `Accept:` each of the six has a number and a verdict; report identifies the top 2 cost drivers.
- **REQ-R2-COST-05 — Reductions are a follow-up, gated on the autopsy.** Implement only the top 2 identified drivers' fixes now (likely candidates: drop audio attachment where the inventory suffices; Vertex context caching / prompt restructuring so the per-song analysis block is cached across difficulties and critic passes; cap re-prompt loops with budget awareness). Everything else goes into a ranked TODO with projected $ savings — do not speculative-optimize.
  `Accept:` re-run 3 benchmark songs; $/song reduced or the autopsy documents why the spend is justified; SACRED-02/03 still green.

---

## 3. Workstream B — Dynamics: make it structural, not rhetorical

The lesson of Round 1 is explicit: DDC wins because dynamics is baked into its learned distribution; ours is a sentence in a prompt. The fix is to move dynamics into the same class of machinery as timing (DSP ground truth) and flow (deterministic solver + gate). Prompting improvements are allowed but are the *last* lever, not the first.

- **REQ-R2-DYN-01 — Density budget in the analysis layer.** Extend BEATFORGE core output (additively) with a per-section and per-bar **density plan**: a target notes-per-bar band derived deterministically from the existing energy curve + section labels (breakdown/build/drop/verse/chorus), normalized per difficulty tier. This is DSP-side ground truth, same citizenship as the onset inventory.
  `Accept:` analysis.json contains `density_plan`; unit tests on synthetic energy curves (flat song → flat plan; build-drop song → monotone rise then peak); plan is difficulty-scaled.
- **REQ-R2-DYN-02 — Designer receives the budget as a constraint, not a vibe.** The design brief presents the per-phrase density band as a hard budget alongside the onset inventory; the intent schema gains a per-phrase declared density the parser validates against the band.
  `Accept:` parser rejects out-of-band phrase intents; prompt fixture updated; rejection test added.
- **REQ-R2-DYN-03 — Deterministic density repair pass.** Post-realizer, a repair step (sibling of foot-flow repair) enforces the plan: thin over-dense phrases by dropping lowest-strength onsets first (never breaking hold pairs or jump semantics), and flag under-dense phrases for one targeted re-prompt scoped to that phrase only — not a whole-chart regeneration (cheaper, and preserves the rest of the chart).
  `Accept:` synthetic tests: over-budget chart in → within-band chart out with lowest-strength notes removed; repair never introduces forbidden-tier flow (re-runs flow validator); per-phrase re-prompt path covered by a fixture.
- **REQ-R2-DYN-04 — Critic scores dynamics explicitly.** The Author≠Judge critic rubric gains a density-vs-energy dimension with the Spearman gate (ρ ≥ 0.55) computed numerically and handed to the critic, so its verdict cites the measured value rather than an impression.
  `Accept:` critic output schema includes the measured ρ; QA report surfaces it per chart.
- **REQ-R2-DYN-05 — Few-shot exemplars (eval-legal).** Add 2–3 few-shot excerpts to the design brief showing human charting behavior at breakdowns and drops (drawn from community packs as *examples*, per the no-training-corpus stance). Keep them short; the cost ledger from Workstream A must show their token overhead.
  `Accept:` exemplars in `prompts/`, ledger shows added cost, A/B on 3 songs shows ρ improvement attributable to them or they come back out.
- **REQ-R2-DYN-06 — Round 2 dynamics targets.** On the 13-song harness: mean ρ ≥ 0.47 (beat DDC's 0.466) and gate pass ≥ 43% (match or beat DDC's rate), with SACRED-02/03 intact.
  `Accept:` harness report committed; a comparison table Round 1 vs Round 2 in `docs/`.

---

## 4. Workstream C — Outlier forensics (small, bounded)

- **REQ-R2-OUT-01 — The Pools & Token Economy timing.** Both sit at 19/17ms vs the fleet's 3–10ms. Diagnose: tempo drift, wrong offset, half/double-time beat lock, or dense-onset ambiguity (both are 1100+ onset tracks). Fix if it's a pipeline bug; document if it's the audio.
  `Accept:` one-page note per song with the diagnosis; if fixed, harness shows ≤ 12ms on both.
- **REQ-R2-OUT-02 — Room Smells / Bttr / The Pools dynamics.** After DYN lands, check whether these three (ρ 0.19 / 0.14 / −0.15) are lifted by the density plan or need per-song notes (e.g., energy curve pathology on the track).
  `Accept:` covered in the Round 2 comparison table with commentary.

---

## 5. Order of work

1. **A (COST-01…04)** — ledger + autopsy. No pipeline behavior changes yet; pure instrumentation. Ship the autopsy to me before starting reductions.
2. **B (DYN-01…03)** — density plan + constraint + repair. Deterministic parts first, zero model calls needed to test them (same pattern as foot-flow).
3. **B (DYN-04…05)** — critic dimension + exemplars, measured by the now-live ledger.
4. **C** — outliers.
5. **A (COST-05)** — top-2 cost reductions, informed by real numbers.
6. **Full 13-song harness re-run** → Round 2 report artifact.

## 6. Definition of Done

Round 1 harness re-run green on SACRED-02/03; mean ρ ≥ 0.47 and dynamics-gate pass ≥ 43%; `cost_ledger.jsonl` produced for every run and `cost-autopsy.md` answers all six questions with numbers; `beatforge cost-report` works; The Pools / Token Economy each have a diagnosis note; Round 1 vs Round 2 comparison table committed. TEST-REQS updated with an R2 section mapping every REQ-R2-* to a test; spec-lint and trace-gate pass.

## 7. Escalate to me (do not decide autonomously)

- Any fix whose only viable path violates SACRED-01 (LLM touching timing/audio).
- If the autopsy shows the dominant cost is Demucs/Colab rather than Vertex — that's an architecture conversation, not a code fix.
- If ρ ≥ 0.47 is not reachable without exceeding a +25% cost-per-song increase over the post-reduction baseline.
