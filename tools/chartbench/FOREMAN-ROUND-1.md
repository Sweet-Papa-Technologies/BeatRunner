# FOREMAN BRIEF — Round 1 benchmark findings → pipeline work

**Owner:** beatforge / STEPFORGE chart pipeline
**Source of truth:** `tools/chartbench/BENCHMARK.md`, `tools/chartbench/out/*.json`
**Status:** Round 1 complete. One confirmed regression-class gap, two hardening items,
two measurement bugs in our own QA that must be fixed before Round 2 is meaningful.

---

## 0. What was measured, and what you can trust

13 songs × 5 difficulties × 3 generators = 195 charts, 39,483 notes.
Generators: **STEPFORGE** (ours), **AutoStepper** (phr00t, 2018, DSP), **DDC**
(Dance Dance Convolution, ICML 2017, from the author's pretrained checkpoints).
All three scored by `tools/chartbench/score.py` against the same DSP analysis of the
same audio, with each simfile rebased into real seconds first (`sm_parse.rebase`).

| axis | STEPFORGE | AutoStepper | DDC | trust it? |
|---|---:|---:|---:|---|
| median timing error | **8 ms** | 64 ms | 58 ms | ✅ |
| notes inside ITG "Fantastic" (±21ms) | **81.4%** | 13.8% | 5.0% | ✅ |
| flow cost, max (mean over charts) | **9.41** | 25.18 | 24.75 | ✅ |
| flow-gate pass rate | **96.9%** | 0.0% | 12.3% | ✅ |
| density-vs-energy ρ | 0.338 | 0.189 | **0.466** | ✅ |
| density gate pass | 23.1% | 7.7% | **43.1%** | ✅ |
| onset_alignment | 0.939 | 0.241 | 0.092 | ❌ **tautological — do not use** |
| bpm error | 0.000 | 0.148 | 0.146 | ❌ **tautological — do not use** |

The last two are rigged: our designer places notes by referencing IDs from the very
onset inventory the metric scores against, and our `#BPMS` *is* the analysis's BPM.
**Any future work that "improves" those two numbers has improved nothing.**

---

## TASK 1 — [P0] Close the dynamics gap (we lose to a 2017 model)

**The finding.** Our charts do not follow the song's energy contour. DDC's do.
Spearman ρ of note-density against the per-bar energy curve: **ours 0.338, DDC 0.466**.
Our own `density_energy` gate passes on **23.1%** of our charts. DDC's charts pass our
gate at **43.1%** — a competitor passes our gate nearly twice as often as we do.

**Root cause hypothesis.** DDC's step-placement CNN is *conditioned on difficulty and
trained on thousands of human charts*, so density-follows-energy is learned behaviour.
Ours is a **prompt instruction** in `adapters/stepmania/prompts/designer.md`, and the
designer is free to ignore it — nothing downstream enforces it. `validate.py` /
`qa.py` **measure** density-vs-energy but only as a *report gate*, and per
`config.DENSITY_GATE_MIN_CV` + the `section_structured` check, the gate is **waived**
on flat tracks — so on a lot of our catalogue nothing is enforcing dynamics at all.

**Work.**
1. **Make it a budget, not a suggestion.** Add a per-section note-density *target* to
   the designer contract: derive, from `analysis["sections"]` and `energy_curve`, a
   target notes-per-bar for each section (scaled by the difficulty's `max_nps_4s`), and
   pass it into the designer prompt as hard numbers per section — not prose.
2. **Enforce it in the realizer/validator**, where the model can't wriggle out. If a
   section's realized density deviates from its target band by more than X%, thin or
   densify *within that section* using the onset inventory (drop lowest-salience onsets
   to thin; add next-highest-salience onsets to densify). This is the same
   repair machinery `validate.py` already has — extend it, don't invent a new one.
3. **Stop waiving the gate so eagerly.** Investigate `DENSITY_GATE_MIN_CV = 0.12` and
   the `section_structured` spread threshold (`SECTION_STRUCTURE_MIN_SPREAD`). DDC hits
   ρ 0.466 on the *same tracks* we declare "too flat to shape" — so the tracks are not
   too flat. The exemption is hiding the defect, not accommodating reality.
4. **Acceptance:** mean ρ ≥ 0.50 and density-gate pass ≥ 60% across the 13-song set,
   **with no regression** in median timing error (must stay ≤ 12ms) or flow-gate pass
   (must stay ≥ 95%). Those two are our moat — do not trade them away for ρ.

**Verification:** re-run `python3 tools/chartbench/score.py --pack "SweetPapa Dream Mix - Founder Mix" --label STEPFORGE-v2`
then `score.py --compare out/STEPFORGE.json out/STEPFORGE-v2.json out/DDC.json`.

---

## TASK 2 — [P0] Fix two measurement bugs in our own QA

These are bugs in how we *grade ourselves*, and they matter more than they look,
because Task 1's acceptance criteria depend on the scorer being honest.

**2a. `onset_alignment` is self-referential and must be re-specified.**
It scores "did the note land within 35ms of an onset *from the inventory the designer
was handed*". It cannot fail. Replace or supplement with a metric that is independent
of our own onset detector:
  - Score against an **independent onset source** — `librosa.onset.onset_detect` with
    different parameters, or better, the pretrained `ddc_onset` PyTorch package
    (`pip install git+https://github.com/chrisdonahue/ddc_onset`), which gives a
    100Hz onset-salience function from a model that has never seen our DSP.
  - Keep reporting the ITG-window buckets (±21 / ±43 / ±102 ms) — those are the game's
    own definition of on-time and are far more defensible than a 35ms threshold we
    picked ourselves.

**2b. The 35ms window is doing too much work on dense tracks.**
`analyze.py` emitted sanity warnings on 6 of 13 tracks: 800–1600 onsets where the sane
band is 50–400 (e.g. `stay_awake_for_me` = 1601 onsets, ~13/sec). At 13 onsets/sec a
±35ms window covers most of the timeline, so "aligned to an onset" becomes nearly free
for *anyone*. Two consequences:
  - Our 0.939 is inflated.
  - **More importantly, the onset detector may be over-triggering** — which would mean
    the designer is choosing from an inventory full of spurious transients. Investigate
    `dsp.py` onset thresholds against these 13 tracks. If the inventory is noisy, that
    is a plausible *contributing cause* of the Task 1 dynamics failure: if every bar has
    plenty of onsets, the designer has no signal telling it which bars are *supposed*
    to be busy.

**Acceptance:** onset counts land inside the 50–400 sanity band (or the band is
re-derived and justified); an independent-onset alignment metric exists and is reported
alongside the ITG windows.

---

## TASK 3 — [P1] Keep the two things we actually won on

Regression guards, not new features. Add these to the gate config so Round 2 work
cannot silently trade away Round 1's wins:

- **Timing:** median note error ≤ 12ms; ≥ 75% of notes inside ±21ms.
- **Flow:** flow-gate pass ≥ 95%; `flow_cost_max` ≤ 12.

For context on how large the moat is: AutoStepper passes the flow gate on **0 of 65**
charts and DDC on **8 of 65**. Neither baseline has any model of a human having two
feet. That is the differentiator — protect it.

---

## TASK 4 — [P2] Cheap wins visible in the data

- **Hold vocabulary.** Our hold share is 8.9%; AutoStepper's is 17.3%. Our
  `hold_share` budget bands (`config.BUDGETS`, 5–20% by tier) allow more than we emit.
  We are under-using holds — likely because `usable_sustain_count()` is conservative.
  Worth a look; holds are cheap expressiveness.
- **`the_pools` and `token_economy` are our two worst timing songs** (19.1ms and
  16.5ms median vs a 5–10ms field). Both are tracks where our BPM and the beat grid
  may be drifting. Check whether these need a multi-segment `#BPMS` map rather than the
  single constant-tempo entry we always emit — `sm_parse.bpm_map()` already supports
  reading them, we just never *write* them.

---

## TASK 5 — [P2] Extend the benchmark for Round 2

- Add **`ddc_onset`** (PyTorch, installs cleanly on arm64) as a step-placement
  F-score baseline — it's the metric the DDC paper actually reports, and it's the
  cheapest rigour available.
- Consider **Mapperatorinator** (osu!mania 4K is column-isomorphic to dance-single) as
  a *modern* SOTA baseline. Beating a 2017 model is table stakes; the honest question
  is whether we beat 2026.
- The harness is reusable: `sm_parse.py` reads any simfile, `score.py` grades it,
  `make_pack.py` installs it as a playable ITGmania pack. Adding a 4th generator is a
  one-line `make_pack.py` invocation.

---

## Do not do

- Do not tune anything to improve `onset_alignment` or `bpm error`. They are
  tautologies (§0). Improving them is measuring your own reflection.
- Do not chase ρ by globally increasing note density. The gate is a *correlation*, not
  a count — spraying notes raises density everywhere and moves ρ toward zero.
- Do not touch `footflow.py`'s penalty weights to make the flow numbers prettier. They
  are the reason we won Task 3's axis, and they are calibrated against physical
  comfort, not against a scoreboard.
