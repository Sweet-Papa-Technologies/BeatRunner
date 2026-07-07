# STEPMANIA.SPEC.MD — StepMania chart generation for beatforge

> **Provenance note:** the committed `STEPMANIA.SPEC.MD` was an empty (0-byte)
> placeholder. This spec was drafted from the stated intent — "add StepMania map
> generation, reuse our same pattern/approach/code from the Gemini 3.5 Flash +
> local-tools workflow" — plus the StepMania `.sm`/`.ssc` file standard. Correct
> anything that doesn't match your vision; the `.sm` format itself is a hard
> standard and not negotiable.

## 0. Goal

Export the beatforge tracks as **StepMania songs** — a song folder per track
containing a `.sm` (and `.ssc`) simfile plus the audio — with **dance-single**
(4-panel: Left / Down / Up / Right) charts at multiple difficulties. Reuse the
existing pipeline end to end:

- **Workstream B (DSP truth)** — `analyze.py`/`dsp.py` already give bpm, offset,
  the onset inventory (each with an id + `nearest_beat` + band character +
  sustain), sections and per-bar energy. Reused **unchanged**.
- **Workstream C (designer)** — the **Gemini 3.5 Flash** designer (swappable via
  `llm.py`, so a local model can be dropped in later) places notes across the 4
  panels by **referencing onset IDs / grid lines only — never a raw row/time**.
- **Workstream D (validation)** — deterministic: legal quantization, playability
  (hand/jump limits), per-difficulty budgets, then emit.

The OVERDRIVE 3-lane game and its maps are **untouched**; StepMania is an
additional *export target*, not a replacement.

## 1. Output layout (REQ-SM-01)

```
build/stepmania/<song>/
   <song>.sm            # simfile (all difficulties)
   <song>.ssc           # SSC variant (same content, .ssc format)
   <song>.ogg           # copy of the track audio
   pack.txt             # human-readable summary of what was generated
```
`<song>` is the track's file base (e.g. `overdrive_pulse`). A StepMania install
just needs the folder dropped into `Songs/<pack>/`. The audio is copied so the
folder is self-contained.

## 2. Simfile header (REQ-SM-02)

- `#TITLE`, `#ARTIST` from the catalogue (`config.TRACK_CATALOGUE` / tracks.ts).
- `#MUSIC:<song>.ogg;`
- `#BPMS:0.000=<bpm>;` — beatforge tracks are constant-tempo, so one entry. The
  precise float bpm from analysis is used.
- `#OFFSET:-<offset>;` — StepMania `#OFFSET` is the seconds gap before beat 0;
  beatforge `offset` is exactly the time of beat 0, so `#OFFSET = -offset`.
- `#SAMPLESTART` at the highest-energy section, `#SAMPLELENGTH:12;`.
- `#SELECTABLE:YES;`.

## 3. Note data model (REQ-SM-03)

- **dance-single** = 4 columns, order **L, D, U, R** (StepMania column order).
- Note chars: `0` none, `1` tap, `2` hold head, `3` hold/roll tail, `M` mine
  (unused by default). Holds occupy head row `2` … tail row `3` in one column.
- The chart is a list of measures separated by `,`. Each measure spans **4 beats**
  and is rendered as N rows evenly subdividing it, where N is the finest
  quantization present in that measure, snapped to one of
  **{4, 8, 12, 16, 24, 32, 48, 64, 192}** (so 8ths, triplets, 16ths etc. render
  exactly). Empty measures are `0000` × 4.

## 4. Difficulties & meter (REQ-SM-04)

Five slots mapping onto the existing budget tiers plus two framing tiers:

| StepMania slot | source budget | meter (rating) |
|---|---|---|
| Beginner  | casual (thinned) | 1–2 |
| Easy      | casual           | 3–4 |
| Medium    | standard         | 5–6 |
| Hard      | overdrive        | 7–8 |
| Challenge | overdrive (dense)| 9–11 |

Meter is computed from objective density (peak NPS + jump/hold rate), not
hard-coded, and clamped to the ranges above.

## 5. Designer contract (REQ-SM-05)

Same anti-hallucination contract as the 3-lane designer: the model hears the
audio + reads the analysis and returns JSON events `{ "ref": "<onset id|grid:beat>",
"cols": ["L"|"D"|"U"|"R", ...], "hold_beats"?: <n> }`. `cols` may contain 1–2
panels (a jump); holds carry `hold_beats` matching a sustain candidate ±1 beat.
**No raw rows/times** — rejected in the resolver. Panels follow the music:
kick→prefer L/R foot alternation, snare→U/D accents, melodic contour→L→R sweep.

## 6. Deterministic validation & budgets (REQ-SM-06)

Enforced after resolution, LLM-free, with salience repair (reuse the pattern):
- **quantization** — every note beat lands on a legal subdivision for its tier.
- **playability** — no more than 2 simultaneous panels (a jump); no hold
  overlapping another note in the same column; jacks / min-gap per tier; peak NPS
  per tier; hold length + share per tier (reuse the budget table, 4-panel-adapted).
- `>15%` repaired → the chart fails and re-prompts (reuse REQ-QA-03 loop).

## 7. Fidelity checks (REQ-SM-07)

- The emitted `.sm` **round-trips**: a parser reads back the same bpm/offset and
  the same note count/positions we wrote (a small Python `.sm` reader in tests).
- Onset alignment ≥ tier floor (notes sit on detected onsets).
- Timing: row→seconds via `#OFFSET`+`#BPMS` reproduces the onset time within the
  snap tolerance.

## 8. CLI (REQ-SM-08)

```
python -m beatforge stepmania --track overdrive [--difficulty medium] [--deterministic]
python -m beatforge stepmania                     # all tracks, all difficulties
```
`--deterministic` uses a DSP-only note placement (no LLM) so valid simfiles can
be produced offline / without Vertex; default uses the Gemini designer.

## 9. SDLC / tests (REQ-SM-09)

pytest under `tools/beatforge/tests/` — emitter measure/quantization/hold
encoding, `#OFFSET`/`#BPMS` timing, `.sm` round-trip, difficulty meter, and the
validation budgets. All offline (deterministic placement + recorded analysis);
no Vertex or StepMania runtime required. Docs: a README "StepMania export"
section and this spec kept in sync.

--- 

ORIGINAL DOC:

# STEPFORGE — StepMania Chart Creator (BEATFORGE Target Adapter #1)

**Spec version:** 1.0 · **Target repo:** `Sweet-Papa-Technologies/BeatRunner` (toolkit lives here; game becomes one consumer)
**Implementer:** Claude Code with the `assetforge` SKILL (Vertex: Gemini 3.5 Flash) + the Colab CLI compute backend (DSP/Demucs)
**Depends on:** the BEATFORGE pipeline (`IMPROVE.MD` / `beatforge-spec`) — this spec **reuses its analysis core wholesale** and adds a StepMania output target.
**Conventions:** REQ IDs `REQ-[A-Z]+-\d+`; acceptance labelled `Accept:` (spec-lint / trace-gate compatible).

---

## 0. Context — this is the toolkit pivot, not a new pipeline

The revelation stands: **DSP timing truth + Gemini 3.5 Flash musical judgment + deterministic ergonomic repair** produces charts that follow the music. That recipe is game-agnostic. What changes per game is the *output grammar* and the *ergonomic rules*. So we split the codebase:

- **Core (already built, reused):** audio analysis (measured BPM/offset, beat grid, stem onsets with IDs + strengths, structure/energy), the onset-ID anti-hallucination contract, the Gemini designer/critic harness, the re-prompt loop, the QA-gate framework.
- **Target adapter (new, this spec):** everything StepMania-specific — 4-panel grammar, foot-flow ergonomics, `.sm/.ssc` serialization, difficulty metering.

Survey conclusions baked into this spec (so we don't relitigate them):
- **Integrate `garcia/simfile`** for all `.sm/.ssc` I/O. Do not hand-roll the format.
- **Keep the DSP core.** DDC's placement net has *no concept of tempo* (it maps to 192-row measures at a fixed 125 BPM); our measured-BPM + real-onset layer is strictly better and is the moat.
- **Build the foot-flow validator** (the StepMania analog of Beat Saber parity), informed by FootGraph-style foot-aware cost search.
- **No training corpus needed** — the LLM approach works on any song. Existing packs are eval benchmarks and few-shot examples, never training data.
- **Target the format, test in ITGmania** (current 4-panel community standard); the same file runs in SM5/OutFox.

## 1. Mission, Pillars, Non-Goals

**Mission:** Given any track, emit a StepMania song folder whose `dance-single` charts follow the music *and* feel good under the feet — steps land on real onsets, patterns are comfortable, difficulty scales honestly, and the drop plays like the drop.

**Pillars (inherited):** deterministic-first (DSP owns timing; the panel realizer owns legality; the LLM owns taste); Author≠Judge (separate designer and critic calls); casual-first (Miss never kills; low difficulties must *flow*); core is sacred (zero regressions to the BEATFORGE core or the game's `src/core`).

**Non-goals (v1):** `dance-double` (8-panel), `pump`/other modes, brackets/hands, mines-as-gimmick, autogen of banners/backgrounds, an in-app editor (we hand off to ArrowVortex/GrooveAuthor), and any ML difficulty *model* of our own (we populate METER heuristically and evaluate an external calc — see §8).

## 2. Architecture — Core + TargetAdapter

```
                         BEATFORGE CORE  (reused, unchanged)
  audio ─▶ analysis.json (bpm, offset, beats, onset inventory[id,strength,
           band,sustain], sections, energy)  ─▶ designer/critic harness
                                   │
                                   ▼   TargetAdapter (Protocol)
                         ┌───────────────────────────────────────────┐
                         │  StepManiaAdapter  (this spec)             │
                         │   grammar()          panel/note vocabulary │
                         │   design_brief()     craft rules → prompt  │
                         │   realize()          intent → panels (DP)  │  ← the build
                         │   validate_repair()  foot-flow gates       │
                         │   difficulty_budgets per Easy/Medium/Hard  │
                         │   serialize()        → .sm/.ssc via simfile│  ← integrate
                         │   qa_metrics()        onset/flow/density    │
                         └───────────────────────────────────────────┘
                                   │
                                   ▼
                    song folder:  <Title>/  {audio.ogg, <title>.ssc, banner?}
                                   │  (test in ITGmania; refine in GrooveAuthor)
```

Package layout (new code only):
```
tools/beatforge/
  core/                     # EXISTING analysis + designer/critic harness (reused)
  adapters/
    base.py                 # TargetAdapter Protocol (grammar/brief/realize/validate/serialize/qa)
    stepmania/
      __init__.py
      grammar.py            # panels (L,D,U,R), note types, row subdivisions
      quantize.py           # snap onset beats → legal rows per difficulty
      realize.py            # foot-flow-aware panel assignment (DP over foot-state)  ← core build
      footflow.py           # foot-state machine + comfort cost model + repair       ← core build
      design.py             # StepMania designer prompt + Gemini call
      difficulty.py         # METER estimate; RADARVALUES handling
      serialize.py          # build/write .ssc + package song folder (garcia/simfile)
      qa.py                 # metrics + critic pass + preview
      prompts/  schemas/
  __main__.py               # add: `stepforge <track> [--difficulties easy,medium,hard]`
build/stepmania/            # per-track design/QA artifacts + rendered previews
```

**REQ-ARCH-01 — Adapter isolation.** `StepManiaAdapter` implements `adapters/base.py::TargetAdapter` and touches nothing StepMania-specific outside `adapters/stepmania/`. The core passes it `analysis.json` + designer output; it returns a serialized song folder + QA report.
`Accept:` a stub `NullAdapter` satisfies the same Protocol; swapping adapters requires no change to `core/`. `git diff` shows zero edits under `core/` or the game's `src/core/`.

## 3. Reused from BEATFORGE (do NOT rebuild)

- **Analysis.** Measured float BPM + ms offset, beat/downbeat grid, stem-based onset inventory (IDs, strengths, band character, sustain flags), sections + per-bar energy — all from the existing Colab GPU job. StepMania consumes this as-is.
- **Onset-ID contract.** The designer references onsets by ID or `grid:<beat>`; it never emits a timestamp. Enforced by the existing parser.
- **Designer/critic harness + re-prompt loop + `thinking_level:"high"`** — reused; only the *prompt* and *output schema* differ (§6).
- **Gate framework** (fail-loud, structured re-prompt, artifacts on disk) — reused.

## 4. Workstream S1 — Panel grammar & row quantization

**Grammar (dance-single):** four panels `L,D,U,R`. Note tokens per `.sm/.ssc` row: `0` empty, `1` tap, `2` hold-head, `3` hold/roll-tail, `4` roll-head, `M` mine. A **jump** = two `1`s in one row. Rows are quantized to a legal per-measure subdivision ∈ {4,8,12,16,24,32,48,64,192}.

**REQ-SM-01 — Beat→row quantization.** `quantize.py` snaps each note's onset-derived beat to the coarsest legal subdivision allowed for its difficulty (§5 budgets) without exceeding the onset's snap tolerance (≤35 ms, inherited). Measures are emitted at the minimum subdivision that represents all their notes exactly (4/8/12/16/24/32/48/64/192).
`Accept:` every emitted measure's row count is a legal subdivision; a unit test round-trips known beats (e.g., a triplet run → 12ths, a 16th burst → 16ths) to the correct measure resolution.

**REQ-SM-02 — Timing from measured truth.** `#OFFSET` and `#BPMS` come from the analysis core's measured values (float BPM, ms offset), not guesses. Constant-tempo tracks emit a single `#BPMS:0.000=<bpm>;`.
`Accept:` the written `#OFFSET`/`#BPMS` match analysis.json within 0.5 BPM / 20 ms; the chart audibly locks in ITGmania (manual check) and passes the inherited onset-alignment gate.

## 5. Workstream S2 — Foot-flow ergonomics (THE build)

This is the part with no shortcut. A 4-panel chart is comfortable or awful depending on how the pattern maps to *two feet*. The core insight that keeps this deterministic: **the LLM chooses musical intent; a foot-flow-aware realizer chooses the concrete panels.** The model never hands you an uncomfortable pattern, because it doesn't place panels at all — it places *feel*, and the realizer solves for the lowest-discomfort panel assignment that honors it.

**Foot-state machine (`footflow.py`).** Track `(left_panel, right_panel, last_moved_foot)`. Enumerate the transition cost between consecutive notes as a sum of penalties:
- **double-step** (same foot twice in a row when alternation was possible): high penalty.
- **crossover** (left foot on R panel or right foot on L panel): medium penalty; tolerance rises with difficulty.
- **jack** (same panel, same foot, consecutive): high at low difficulty, allowed in short bursts high.
- **footswitch** (same panel, alternating feet): low-medium; only legal above a difficulty threshold.
- **bracket/large spin** (physically impossible or >180° twist): infinite (forbidden).
- **comfort bonus**: alternating feet on adjacent panels, natural L/R drift matching a melodic contour.

**REQ-SM-03 — Panel realizer (DP over foot-state).** `realize.py` takes the quantized note stream + per-phrase intent (§6) and assigns concrete panels by a Viterbi/DP lowest-cost path over the foot-state machine, constrained to honor the phrase intent (texture, movement direction, crossover tolerance, jump placements). Output: concrete `L/D/U/R` (and jumps) per note.
`Accept:` on a synthetic 8th-note stream the realizer produces strict foot alternation with zero double-steps; when intent requests "moderate crossovers," the path contains crossovers within the budget and none that require an impossible twist.

**REQ-SM-04 — Foot-flow validator + repair.** After realization, `footflow.py` scores the chart against the difficulty's comfort budget (below). Violations are repaired by local re-routing (re-solve the offending window with a tighter constraint) or, as a last resort, thinning the lowest-salience note. Repairs are logged; >15% of notes repaired → fail → structured re-prompt (inherited loop).
`Accept:` unit tests for each penalty (an induced double-step, an over-crossover run, an illegal low-diff footswitch, a forbidden twist) show detection and correct minimal repair; a clean chart passes with zero repairs.

**Difficulty budgets (hard constraints):**

| | Easy | Medium | Hard |
|---|---|---|---|
| finest row subdivision | 8th | 16th | 16th (24th/32nd bursts ok) |
| max sustained NPS (4s window) | 3 | 5 | 8 |
| crossovers | none | light | moderate |
| footswitches | none | none | allowed (sparse) |
| jacks | none | ≤2 | ≤4 burst |
| jumps | on strong downbeats only | on accents | free but not chorded spam |
| holds/rolls | 10–20% of notes | 5–15% | 5–12% |
| density vs energy (Spearman) | ≥0.55 | ≥0.55 | ≥0.55 |

## 6. Workstream S3 — StepMania designer (Gemini 3.5 Flash)

One designer call per (track, difficulty), `thinking_level:"high"`, audio + analysis + brief + budget + output contract.

**Output contract (strict JSON) — intent, not panels:**
```json
{
  "design_notes": "per-section: what the music does, what the pattern should feel like",
  "notes": [ {"ref":"p017","kind":"tap"},
             {"ref":"p041","kind":"hold","hold_beats":2},
             {"ref":"grid:64.0","kind":"mine"} ],
  "phrases": [ {"start_bar":16,"end_bar":24,"texture":"jumpstream",
                "movement":"drift_L_to_R","crossover":"light","jump_density":"accents",
                "intent":"the drop — drive it hard"} ]
}
```
`ref` = onset ID or `grid:<beat>` (inherited contract; **no timestamps, no panels**). `kind` ∈ tap|hold|roll|mine. Panel assignment is the realizer's job (§5), steered by the phrase's `texture/movement/crossover/jump_density`.

**REQ-SM-05 — Designer call.** Produces valid intent JSON for each (track, difficulty); every `ref` resolves to an onset in the inventory or a legal grid row; every phrase covers a contiguous bar range with no gaps.
`Accept:` 3 difficulties × N tracks each yield schema-valid intent; raw output stored to `build/stepmania/<track>.<diff>.design.json`.

**REQ-SM-06 — Texture vocabulary is closed.** `texture` ∈ {steps, stream, jumpstream, drill, runningman, jacks_sparse, stops_breather}; `movement` ∈ {static, drift_L_to_R, drift_R_to_L, zigzag, box}; `crossover` ∈ {none, light, moderate}. Anything else is a validation error, not interpreted.
`Accept:` a fixture with `texture:"freestyle"` is rejected with a specific error.

## 7. Workstream S4 — `.ssc` output via `simfile` (integrate)

**REQ-SM-07 — Serialize with `garcia/simfile`.** Build the song via the `simfile` library (`SSCSimfile`, `NoteData`, `TimingData`); never string-format the format by hand. Emit `.ssc` (preferred; `.sm` on request). Populate `TITLE/ARTIST/MUSIC/OFFSET/BPMS/SAMPLESTART/SAMPLELENGTH`, and one `#NOTEDATA` per difficulty with `STEPSTYPE:dance-single`, `DIFFICULTY`, `METER`, `CREDIT:STEPFORGE`.
`Accept:` output opens with `simfile.open()` and re-serializes byte-stable; it loads in ITGmania with zero parse warnings and all three difficulties selectable.

**REQ-SM-08 — Song-folder packaging.** Assemble `<Title>/` with the audio (copied/encoded to `.ogg`), the `.ssc`, and a `#SAMPLESTART` set to the track's highest-energy section (from analysis) so the preview music is the drop. Optional banner left blank.
`Accept:` dropping the folder into an ITGmania `Songs/<pack>/` directory makes the song appear and play end-to-end on all three difficulties.

## 8. Workstream S5 — Difficulty metering

**REQ-SM-09 — METER estimate.** Compute an integer meter per difficulty from objective features (sustained NPS percentiles, crossover/tech density, stream length). Ship a documented heuristic; keep it in one function.
`Accept:` meters are monotonic (Easy < Medium < Hard) for every track; the function is unit-tested on hand-labelled fixtures within ±1.

**REQ-SM-10 — RADARVALUES + external calc (evaluate, don't block).** Leave `RADARVALUES` for the engine to recompute on load by default. Investigate integrating an external difficulty calculator (Etterna MSD/MinaCalc, or radar via `barrysir/stepmania-parsing-code`) to cross-check METER; document findings, gate behind a flag, ship only if it agrees with the heuristic on the eval set.
`Accept:` a written note in `build/stepmania/` on the calc evaluation (even if the conclusion is "heuristic is sufficient for v1"); flag defaults off.

## 9. Workstream S6 — Validation, QA gates, critic, previews

**REQ-SM-11 — Schema + legality gate.** Every emitted chart: legal row subdivisions, sorted rows, valid hold/roll head-tail pairing (no orphans), jumps ≤2 panels, no note past the playable tail. Round-trip through `simfile` *and* through the real StepMania parser (`barrysir/stepmania-parsing-code`) as the final referee.
`Accept:` pytest + the StepMania-parser round-trip both accept every shipped chart; an orphaned hold fixture is caught.

**REQ-SM-12 — Objective QA metrics.** Per chart: onset alignment (≥90% of taps within ±35 ms of a detected onset; grid-only counted separately), panel balance (each panel 18–32%), foot-flow cost distribution (no note above the difficulty's per-transition ceiling after repair), hold share in-band, repair count ≤15%, density-vs-energy Spearman ≥0.55.
`Accept:` all metrics in the QA report; all thresholds pass for shipped charts.

**REQ-SM-13 — Critic pass (Author≠Judge).** Fresh-context Gemini 3.5 Flash call, `thinking_level:"high"`: audio + the realized chart rendered as a readable step sequence + the brief → musicality/playability review, score 0–10, specific issues ("bar 33 crossover run fights the vocal accent"). Ship ≥7; below → one targeted revision then human review.
`Accept:` critic reviews stored per shipped chart; PROVENANCE records designer vs. critic as separate contexts.

**REQ-SM-14 — Human-auditable previews.** Per chart: (a) a scrolling-notefield PNG (matplotlib: panels × time with onsets, holds, jumps, section bands) and (b) an assist-tick render (ffmpeg: audio + a tick per note) so you *hear* whether steps land on the music before shipping.
`Accept:` both artifacts exist per shipped chart; the tick render is the fastest ear-check — listen before release.

## 10. Workstream S7 — Engine integration & handoff

**REQ-SM-15 — CLI + batch.** `python -m beatforge stepforge <track> [--difficulties easy,medium,hard] [--format ssc|sm]` runs analysis (reusing cache) → design → realize → validate → serialize → package → QA, for one track or a folder. Reuses one Colab session per batch (inherited).
`Accept:` a 4-track batch yields four ITGmania-ready song folders + QA reports in `build/stepmania/`.

**REQ-SM-16 — Editor handoff documented.** README documents the workflow: generate draft → refine in **GrooveAuthor** or **ArrowVortex** → re-test in ITGmania. The generator produces a *strong draft*, not a claimed-final chart.
`Accept:` README section exists with the round-trip; a generated `.ssc` opens cleanly in ArrowVortex/GrooveAuthor (manual check).

## 11. Testing Strategy
- **pytest** (offline, deterministic; model + Colab behind fixtures): quantization (S1), the foot-flow cost model and realizer DP (S2/S3 — the highest-value tests: synthetic streams with known-optimal panelings), designer-intent parsing incl. no-timestamp/no-panel rejection, difficulty monotonicity, serializer legality.
- **Cross-language referee:** every emitted chart round-trips through `barrysir/stepmania-parsing-code` in CI (the engine's own parser is the schema authority).
- **Eval set (not training):** a handful of community charts (e.g., Club Fantastic) as ground truth to compare onset alignment and difficulty against — and as a benchmark vs. DDC/DDCL if you want the comparison.
- **Live smoke:** one full `stepforge <track> --difficulties easy,medium,hard` with real Vertex + Colab, artifacts committed as the reference run.
- **TEST-REQS:** add a `stepforge` section mapping REQ-SM-* to tests; extend trace-gate globs to `adapters/stepmania/tests/**`.

## 12. Order of Work
1. **`adapters/base.py` + grammar + quantize (S1)** — no LLM, no model; establishes the interface and row math.
2. **foot-flow + realizer (S2)** — the core build; fully testable with synthetic note streams, zero model calls. Get panel comfort right before any LLM is involved.
3. **serialize + packaging (S4)** — integrate `simfile`; now you can emit a playable (if dumb) chart and test it in ITGmania end-to-end.
4. **designer (S3)** — plug Gemini into a rig that already realizes + validates + serializes.
5. **difficulty + QA + critic + previews (S5/S6)** — the finish and the ear-check.
6. **CLI/batch + README/TEST-REQS (S7)** — ship.

## 13. Definition of Done
All REQ `Accept:` pass; zero diffs to BEATFORGE `core/` or game `src/core/`; four tracks × three difficulties ship as ITGmania-ready folders with QA reports, critic ≥7, previews rendered; assist-tick previews **sound locked to the music**; charts open in ArrowVortex/GrooveAuthor; the StepMania parser accepts every file; README documents the toolkit-adapter architecture and the editor handoff. The real gate: you drop the pack into ITGmania, play Medium on all four, and the feet feel the song.

---

## Appendix A — Designer prompt skeleton (`prompts/designer.md`)
> You are an expert StepMania (ITG-style) chart designer for a 4-panel dance pad (panels L, D, U, R; taps, holds, rolls, mines; jumps = two panels at once; casual-first — a miss breaks combo but never kills). You are given the track audio and a machine analysis (measured tempo, beat grid, an onset inventory with IDs/strengths/sustain, sections, per-bar energy). Design a {difficulty} chart as JSON per the contract. You choose WHICH onsets become notes, each note's KIND (tap/hold/roll/mine), and a per-phrase INTENT (texture, movement direction, crossover tolerance, jump density) — you do NOT place panels or times; a deterministic realizer turns your intent into comfortable steps. Chart the music: streams on runs, jumps on accents/downbeats, holds on sustained notes, breathers in the breaks, and escalate density into the drop. Respect every budget as a hard limit. Think through the section-by-section plan before emitting JSON.

## Appendix B — `.sm/.ssc` note-format reference (for the serializer)
- Chart body = measures separated by `,`, terminated by `;`. Each measure = R rows, R ∈ {4,8,12,16,24,32,48,64,192}, one line per row, 4 chars per row (dance-single), left→right = L,D,U,R.
- Row tokens: `0` none, `1` tap, `2` hold head, `3` hold/roll tail, `4` roll head, `M` mine. Jump = two `1`s in a row. Hold/roll = a `2`/`4` head with a matching `3` tail on the same panel in a later row.
- Per-difficulty header (SSC `#NOTEDATA`): `STEPSTYPE:dance-single; DIFFICULTY:{Beginner|Easy|Medium|Hard|Challenge}; METER:{int}; CREDIT:STEPFORGE;` then `#NOTES:`.
- Timing: `#OFFSET:{sec};` `#BPMS:{beat}={bpm},...;` `#STOPS:...;` from measured analysis. Prefer `.ssc`.

## Appendix C — Foot-flow cost reference (`footflow.py`)
State `(L_panel, R_panel, last_foot)`. Transition penalties (tune constants in `config.py`): double_step ≫ jack(low-diff) > crossover(medium, difficulty-scaled) > footswitch(threshold-gated) > slight-cross > 0 for clean alternation; +bonus for alternation matching melodic contour; +∞ for physically impossible twists/brackets. Realizer = min-cost DP path honoring phrase intent; validator = post-hoc budget check + local re-solve repair.