# SABERFORGE — Beat Saber Map Creator (BEATFORGE Target Adapter #2)

**Spec version:** 1.0 · **Target repo:** the toolkit repo (BEATFORGE core + adapters)
**Implementer / "FOREMAN":** Claude Code with the `assetforge` SKILL (Vertex: Gemini 3.5 Flash) + the Colab CLI compute backend (DSP/Demucs). Automate as much as possible; the sections below name the exact libraries/tools so FOREMAN integrates rather than reinvents.
**Depends on:** the BEATFORGE analysis core + designer/critic harness (reused wholesale) and the STEPFORGE `TargetAdapter` pattern (this is adapter #2).
**Conventions:** REQ IDs `REQ-[A-Z]+-\d+`, acceptance `Accept:` (spec-lint / trace-gate compatible). Full build.

---

## 0. Context, and a HARD positioning constraint

Same recipe, third instance: DSP timing truth + Gemini 3.5 Flash musical judgment + a deterministic realizer that guarantees playability. Beat Saber's realizer is a **swing-parity engine** — the analog of StepMania foot-flow and WaveSurf traceability, and the hardest of the three.

**Positioning is a design constraint, not marketing (enforced by REQs, not vibes):** the Beat Saber community explicitly rejects uploaded auto-generated maps (BSMG/BeastSaber). SABERFORGE is a **mapper's drafting assistant + personal-play generator**, never a BeatSaver upload farm. Concretely this means: (a) every output is a *refinable draft* handed to ChroMapper, not a claimed-final map; (b) generated maps are labelled AI-assisted in their metadata; (c) the default content lane is **the user's own (paid-plan Suno / original) music** to stay clear of song-copyright exposure; (d) no automated BeatSaver publishing is built. These are REQ-POS-01..03 below.

## 1. Mission, Pillars, Non-Goals

**Mission:** Given a track, produce a Beat Saber song folder whose Standard-mode maps follow the music AND are physically comfortable to swing — correct parity, legal patterns, sane note-jump-speed per difficulty — as a strong draft a human finishes in ChroMapper.

**Pillars (inherited + one new):** deterministic-first (DSP owns timing, the parity engine owns swing legality, the LLM owns taste); Author≠Judge; casual-first; core is sacred; **draft-and-refine, never dump** (the positioning constraint).

**Non-goals (v1):** no Chroma/Noodle/Mapping-Extensions modcharts; no 360°/90° or One-Saber/90 modes (Standard only); no lightshow *artistry* (v1 does templated basic lighting and hands off — §7); no `dance-double` analog; no automated upload/publish; no ranked-quality guarantee (we target "clean & playable," not ScoreSaber-ranked, though we lint against those criteria).

## 2. Architecture — Core + BeatSaberAdapter

```
     BEATFORGE CORE (reused) ─▶ analysis.json ─▶ designer/critic harness
                                   │  TargetAdapter (from STEPFORGE)
                                   ▼
     ┌──────────────────────────────────────────────────────────────┐
     │ BeatSaberAdapter                                               │
     │  grammar()        4×3 grid, cut dirs, colors, walls, bombs,   │
     │                   arcs (sliders), chains (burstSliders), NJS  │
     │  design_brief()   swing/parity craft rules → prompt           │
     │  realize()        intent → notes: parity-safe DP over swing   │  ← THE build
     │                   state for BOTH hands, joint swing-path safe  │
     │  parity_engine()  forehand/backhand state machine + legality  │  ← THE build
     │  validate_repair()ScoreSaber-criteria lint + reset insertion  │
     │  difficulty()     Easy…Expert+ budgets + NJS/offset per diff  │
     │  serialize()      → v3 .dat + Info.dat via BeatSaber-JSMap    │  ← integrate
     │  qa_metrics()     onset/parity/nps/hand-balance + previews    │
     └──────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
     song folder → CustomLevels/  → refine in ChroMapper → playtest in-headset
```

**Integrations (do NOT reinvent):**
- **Serialization:** `KivalEvan/BeatSaber-JSMap` (TypeScript, version-agnostic v2/v3/v4 core model). This is the Beat Saber `simfile`. Emit **v3** as primary (broadest editor/mod support; v4 is newer and community-editor support still lags) — JSMap keeps you version-agnostic to add v4 later.
- **Validation referees:** `GalaxyMaster Parity Checker` (parity-focused) and `Kival Evan Map Check` (general, more versatile than MMA2's built-in). Run BOTH as external referees on every emitted map (§9).
- **Corpus / eval / few-shot:** the **BeatSaver API** (filter to maps rated >70%, the same bar the ML tools use) for exemplars and A/B ground truth — never as training data uploads.
- **NPS/parse reference:** `khivus/BSMapInfo` (Python, computes NPS histograms) for metric parity.
- **Editors (handoff):** ChroMapper (primary) / Mediocre Map Assistant 2.

**REQ-ARCH-01.** `BeatSaberAdapter` implements the shared `TargetAdapter` protocol; nothing Beat-Saber-specific leaks outside `adapters/beatsaber/`.
`Accept:` swapping StepMania↔Beat Saber adapters needs no core change; `git diff` clean under `core/`.

**REQ-POS-01 — AI-assisted labelling.** Every emitted map writes an explicit AI-assisted marker into its metadata/description and a `credit` of `SABERFORGE (AI-assisted draft)`.
`Accept:` generated Info/description contain the marker; a test asserts its presence.

**REQ-POS-02 — Own-music default + no auto-publish.** The CLI defaults to a local-music workflow; there is NO BeatSaver upload/publish code path anywhere. Mapping third-party copyrighted audio requires an explicit `--i-have-rights` acknowledgement flag that prints the copyright caveat.
`Accept:` no network code targets beatsaver.com for publishing; the flag+caveat exist and are tested.

**REQ-POS-03 — Draft handoff.** Output is structured for ChroMapper refinement (clean v3, sorted objects, no floating-point snap errors — run an offset/sort pass equivalent to BSMG's Offset Remover / Note Sorter).
`Accept:` a generated map opens in ChroMapper with zero load errors and notes snapped to clean precisions.

## 3. Reused from BEATFORGE (do NOT rebuild)
Analysis (measured BPM/offset, beat grid, stem onset inventory w/ IDs+strengths+band+sustain, sections, per-bar energy); the onset-ID anti-hallucination contract; the Gemini designer/critic harness + `thinking_level:"high"` + structured re-prompt loop; the fail-loud gate framework. Only the prompt, output schema, realizer, and validator are new.

## 4. Workstream B1 — Grid grammar & object vocabulary

**Grid:** 4 columns `x∈0..3` (left→right), 3 rows `y∈0..2` (bottom→top) = 12 cells. **Colors:** `c=0` red/left saber, `c=1` blue/right saber. **Cut directions** `d`: 0=up,1=down,2=left,3=right,4=up-left,5=up-right,6=down-left,7=down-right,8=any(dot). `a` = additional angle offset (deg, v3).
**Objects:** color notes, bombs, obstacles/walls (`x,y,w,h,d=duration`), **arcs** (`sliders` — ease swing on sustained/连connected notes, magnetize to saber, ≤5 active per hand), **chains** (`burstSliders` — head note + `sc` slice count + `s` squish). **NJS** (note jump speed) + offset are per-difficulty and MUST be constant within a difficulty (ScoreSaber hard rule).

**REQ-BS-01 — Grammar module.** Encode the grid, cut-direction geometry (a unit vector per `d` for swing-path math), color→hand, and object types.
`Accept:` unit tests: each `d` maps to the correct swing vector; grid bounds enforced.

## 5. Workstream B2 — Swing-parity engine (THE build)

Beat Saber lives or dies on **parity**: each note is a forehand or backhand swing, and smooth play *alternates* them per hand. A **reset** (two same-parity swings in a row) forces extra motion at higher speed and is only acceptable when telegraphed and given time — the preferred telegraph is a **bomb reset** (a line of bombs that pushes the hand to neutral). This is the swing-flow analog of StepMania foot-flow, but for two hands with directional cuts and shared swing-path space.

### 5.1 Parity state machine (`parity_engine.py`/`.ts`)
Per hand track `(parity∈{forehand,backhand}, cut_dir, grid_cell)`. Transition legality/comfort between consecutive same-hand notes derives from encoded rules (below). Two hands are semi-independent but share the 4×3 space, so a **joint** constraint forbids one color's note sitting in the other color's pre-cut/follow-through swing path.

### 5.2 Encoded legality rules (from ScoreSaber Mapping Criteria — the ruleset)
The validator enforces, at minimum:
- Alternating parity by default; a parity break must be accompanied by a telegraphed reset (bomb reset preferred) with enough time to return to neutral.
- Angle discipline: at higher note precision prefer 180° (up/down) and 135° patterns; larger angle changes need proportionally more time (scale allowed Δangle by the inter-note time gap and BPM).
- Same-color notes on one swing must not be parallel and must lead into the next expected cut; same-snap same-color notes differ by ≤45°.
- No note in the pre-cut/follow-through swing path of an opposite-color note (unless same snap or there's time to clear); no swing path into a same-color note's bad-cut hitbox.
- Bombs never interfere with a swing path and never force the saber outside the 4×3 grid; bombs ≥20 ms apart.
- Arcs connect to a note, direction matches the arrow (dot arcs follow parity/neutral), ≤5 active per hand.
- Precision sanity: ≤1/16 up to 180 BPM, ≤1/8 up to 360 BPM (given adequate NJS).

**REQ-BS-02 — Parity realizer (DP over swing state).** `realize()` takes onset→hand assignments + note kinds + per-phrase intent (§6) and assigns concrete `(x,y,d)` per note by a lowest-cost search over per-hand parity state, honoring intent (lean/movement/tech) and the joint swing-path constraint, defaulting to clean alternation.
`Accept:` on a synthetic single-hand 1/8 stream the realizer produces strict parity alternation with zero resets; on a two-hand pattern it produces no opposite-color swing-path violation; when intent requests a deliberate reset, the realizer inserts a valid bomb reset with adequate lead time.

**REQ-BS-03 — Parity/legality validator + repair.** After realization, lint against §5.2. Repair by local re-routing (re-solve the window under tighter constraints) or inserting a telegraphed reset; last resort thins the lowest-salience note. >15% repaired → fail → structured re-prompt (inherited).
`Accept:` unit tests for each rule (a forced reset, a parallel same-color pair, an opposite-color swing-path intrusion, an over-large angle change at high BPM, bombs <20 ms) show detection + correct minimal repair.

**REQ-BS-04 — In-core swing simulator (beatable-by-construction gate).** A deterministic simulator "plays" the finished map, tracking both hands' parity/position through the whole note sequence, and reports any forced reset or impossible transition. Shippable maps must simulate clean. This is the SABERFORGE analog of the WaveSurf autopilot bot / StepMania bot.
`Accept:` the simulator runs headless in tests over every bundled map and reports zero forced resets; a hand-crafted bad-parity fixture is flagged.

**Difficulty budgets (hard constraints):**

| | Easy | Normal | Hard | Expert | Expert+ |
|---|---|---|---|---|---|
| max sustained NPS (4s) | 2 | 3.5 | 5 | 7 | 10 |
| finest precision | 1/4 | 1/8 | 1/8 | 1/16 | 1/16 |
| rows used | mostly bottom | bottom+mid | all 3 | all 3 | all 3 |
| resets | none | none | telegraphed only | telegraphed | telegraphed |
| doubles/stacks | rare, on accents | on accents | free | free | free |
| arcs/chains share | 0–5% | 5–10% | 5–15% | 5–15% | 5–12% |
| suggested NJS | ~10 | ~10 | ~12 | ~16 | ~18 |
| density vs energy Spearman | ≥0.55 | ≥0.55 | ≥0.55 | ≥0.55 | ≥0.55 |

## 6. Workstream B3 — Designer (Gemini 3.5 Flash: intent, not geometry)

One call per (track, difficulty), `thinking_level:"high"`, audio + analysis + brief + budget + contract. **The model never emits grid coordinates, cut directions, or parity** — only which onsets become notes, each note's kind, hand assignment, and a per-phrase feel. The parity realizer (§5) turns that into swing-legal geometry.

**Output contract (strict JSON):**
```json
{"design_notes": "per-section feel + what to emphasize (drums/vocal/lead)",
 "notes": [ {"ref":"p017","hand":"either","kind":"note"},
            {"ref":"p041","hand":"left","kind":"arc","tail_ref":"p049"},
            {"ref":"p055","hand":"right","kind":"chain","slices":3} ],
 "phrases": [ {"start_bar":16,"end_bar":24,"density":"driving","hand_balance":"even",
               "movement":"lean_in","tech":"flowy","emphasis":"kick+snare",
               "intent":"the drop — big two-handed energy"} ]}
```
`ref` = onset ID or `grid:<beat>` (inherited contract; NO coordinates/cutdirs). `kind` ∈ {note, arc, chain, bomb_reset}. `hand` ∈ {left, right, either} (the realizer resolves `either` for best flow). Closed phrase vocab: `density` {sparse, steady, driving, burst}, `movement` {static, lean_in, lean_out, sweep}, `tech` {flowy, tech, streamy}, plus `emphasis` naming the layer to chart. Section transitions get telegraphed feel changes.

**REQ-BS-05 — Designer call.** Valid intent JSON per (track, difficulty); every `ref` resolves; closed vocab enforced; raw stored under `build/saberforge/`.
`Accept:` fixtures containing a coordinate/cutdir field, an unknown vocab value, or an unresolvable ref are each rejected with specific errors.

## 7. Workstream B4 — Serialization + lighting via BeatSaber-JSMap

**REQ-BS-06 — Emit v3 via JSMap.** Build Info.dat + one beatmap `.dat` per difficulty using `BeatSaber-JSMap` (never hand-format JSON). Populate the three required top-level collections (`colorNotes`, `bombNotes`, `obstacles`) even when empty, per-difficulty NJS/offset, BPM, song metadata, and the AI-assisted marker (REQ-POS-01). Run a sort + offset-clean pass (REQ-POS-03).
`Accept:` output round-trips through JSMap byte-stable, loads in ChroMapper and in-game (CustomLevels) with all difficulties selectable and correct NPS shown.

**REQ-BS-07 — Templated lighting (honest scope).** v1 does NOT author artful lightshows. It emits **basic templated lighting** driven by analysis (on-downbeat flashes, section-colored washes, intensity riding the energy curve) as a *starting point*, and the README states lighting is expected to be finished by a human in ChroMapper.
`Accept:` maps have non-empty, beat-synced basic lighting that plays without error; README flags lighting as a refinement step.

## 8. Workstream B5 — Difficulty & NJS

**REQ-BS-08 — Difficulty set + NJS.** Emit the requested subset of Easy/Normal/Hard/Expert/Expert+, each with an NJS/offset per the budget table, constant within the difficulty (hard rule). NJS may auto-nudge for very high/low BPM so reaction time stays sane, then locked.
`Accept:` NJS constant within each difficulty; monotonic difficulty (NPS/precision/tech increase Easy→Expert+); a test checks constancy + monotonicity.

## 9. Workstream B6 — Validation, QA gates, critic, previews

**REQ-BS-09 — Triple-referee legality.** Every emitted map must pass: (1) the in-core validator (§5.2), (2) the in-core swing simulator (REQ-BS-04, zero forced resets), AND (3) both external checkers — **GalaxyMaster Parity Checker** and **Kival Evan Map Check** — invoked as subprocesses, with zero parity/critical errors. External-tool availability is a documented prerequisite; if absent, the build warns loudly and marks the map "unverified."
`Accept:` CI-style run invokes both external checkers on each bundled map and asserts clean; an intentionally bad-parity map fails all three.

**REQ-BS-10 — Objective QA metrics.** Per map: onset alignment (≥90% of notes within ±35 ms of a detected onset; grid-only counted separately), hand balance (each hand 40–60%), reset count (0 unforced), NPS curve, arc/chain share in-band, density-vs-energy Spearman ≥0.55, precision-vs-BPM within ScoreSaber limits.
`Accept:` metrics in the QA report; thresholds pass for shipped maps.

**REQ-BS-11 — Critic pass (Author≠Judge).** Fresh-context Gemini 3.5 Flash, `thinking_level:"high"`: audio + the realized map rendered as a readable per-hand swing sequence + the brief → flow/musicality review 0–10 with specific issues ("bar 33 the blue hand resets against the vocal — re-hand it"). Ship ≥7; below → one revision then human review.
`Accept:` reviews stored; PROVENANCE records designer/critic separation.

**REQ-BS-12 — Human previews.** Per map: (a) a grid-over-time PNG (both hands' notes/cuts, arcs, chains, bombs, section bands) and (b) an assist-tick audio render (tick per note) to *hear* alignment. Look + listen before shipping.
`Accept:` both artifacts exist per bundled map.

## 10. Workstream B7 — CLI, packaging, handoff

**REQ-BS-13 — CLI + batch.** `python -m saberforge <audio> [--difficulties expert,hard] [--njs ...] [--i-have-rights]` runs analysis (cached) → design → realize → validate → serialize → package → QA, one track or a folder, one Colab session per batch. Output = a `CustomLevels`-ready song folder.
`Accept:` one command yields a ChroMapper-openable, in-game-playable song folder + QA report; no manual edits needed to load.

**REQ-BS-14 — README + eval.** README documents: the assistant/draft-refine workflow, the ChroMapper handoff, the external-checker prerequisites, the own-music-first + copyright caveat, and an eval note comparing SABERFORGE onset-alignment/parity against a Beat Sage map and a >70%-rated human map on the same song (BeatSaver corpus).
`Accept:` README sections exist; one recorded A/B eval committed under `build/saberforge/`.

## 11. Testing
- **pytest / Vitest (offline; model + Colab + external checkers behind fixtures):** grammar/swing-vector math, the parity state machine and realizer DP (highest-value: synthetic streams with known-optimal parity), each legality rule (§5.2), the swing simulator, designer-intent parsing incl. no-coordinate/no-cutdir rejection, difficulty monotonicity + NJS constancy, JSMap round-trip.
- **External referees in CI:** GalaxyMaster Parity Checker + Kival Evan Map Check on every bundled map (the community's own tools are the final authority).
- **Eval set (not training):** BeatSaver maps >70% rated as A/B ground truth vs Beat Sage.
- **Live smoke:** one full `saberforge <track> --difficulties expert` with real Vertex + Colab, artifacts committed.
- **SDLC:** mirror gates.config/policy.json; add REQ-BS-* to TEST-REQS.yaml; PROVENANCE for assets + designer/critic.

## 12. Order of work
1. Grammar + swing-vector math + parity state machine (B1/B2 core) — no LLM, fully testable.
2. Parity realizer + validator + swing simulator (B2) — the hard build; prove parity correctness on synthetic streams before any model call.
3. Serialize via JSMap + external-checker integration (B4/B6) — now emit a (dumb but legal) map and load it in ChroMapper + in-game.
4. Designer (B3) — plug Gemini into a rig that already realizes, validates, and referees.
5. Difficulty/NJS + templated lighting + QA + critic + previews (B5/B7/B6).
6. CLI/batch + README/eval + PROVENANCE.

## 13. Definition of Done
All REQ `Accept:` pass; zero diffs to BEATFORGE `core/`. Bundled: ≥4 songs (own-music/Suno default) × chosen difficulties, each passing the in-core validator, the swing simulator (zero forced resets), AND both external checkers, with critic ≥7 and previews rendered. Every map opens in ChroMapper and plays in-headset from CustomLevels. AI-assisted labelling present; no auto-publish path exists; copyright flag works. The real gate: put on the headset, play an Expert draft, and the swings feel like the song and flow clean — then a human polishes lighting/edges in ChroMapper.

---

## Appendix A — Designer prompt skeleton (`prompts/designer.md`)
> You are an expert Beat Saber mapper drafting a Standard-mode {difficulty} map. Two sabers (red=left, blue=right) cut blocks on a 4×3 grid; smooth play alternates forehand/backhand swings (parity) per hand; resets are avoided unless telegraphed with a bomb reset; casual-first — a miss breaks combo but never kills. You get the track audio + a machine analysis (measured tempo, beat grid, onset inventory with IDs/strengths/sustain, sections, per-bar energy). Choose WHICH onsets become notes, each note's KIND (note/arc/chain/bomb_reset), its HAND, and a per-phrase FEEL (density, hand balance, movement/lean, tech level, which layer to emphasize). You do NOT place grid coordinates, cut directions, or parity — a deterministic parity engine turns your intent into swing-legal geometry with clean flow. Chart the music: emphasize the drums or the vocal as the section calls for, build density into the drop, breathe in breaks, and telegraph section changes. Respect every budget as a hard limit. Think through the song's arc before emitting JSON.

## Appendix B — v3 note-format reference (for the JSMap serializer)
- File per difficulty: `{"version":"3.0.0","bpmEvents":[…],"colorNotes":[{ "b":beat,"x":0..3,"y":0..2,"c":0|1,"d":0..8,"a":angle }],"bombNotes":[{ "b","x","y" }],"obstacles":[{ "b","d":dur,"x","y","w","h" }],"sliders":[…arcs…],"burstSliders":[…chains…],"basicBeatmapEvents":[…lighting…]}`.
- Cut dir `d`: 0=U,1=D,2=L,3=R,4=UL,5=UR,6=DL,7=DR,8=dot(any). Color `c`: 0=red/left, 1=blue/right.
- Info.dat (v2/v4 shapes differ): song metadata, per-difficulty `{beatmapFilename, njs, offset, difficultyRank}`, color schemes/environment. Emit v3 beatmaps; JSMap handles the Info shape. All three of colorNotes/bombNotes/obstacles must be present (even empty) for correct in-game stats.

## Appendix C — Parity/legality rules reference (encode in the validator; mirrors ScoreSaber Mapping Criteria)
Alternate parity by default; parity break ⇒ telegraphed bomb-reset with lead time. Prefer 180°/135° at high precision; scale allowed Δangle by inter-note gap × BPM. Same-color same-swing notes: not parallel, lead into next cut; same-snap ≤45° apart. No note in an opposite-color note's pre-cut/follow-through swing path (unless same snap or time to clear); no swing path into a same-color bad-cut hitbox. Bombs: never in a swing path, never force saber off the 4×3 grid, ≥20 ms apart. Arcs: connect to a note, direction matches arrow (dot ⇒ follow parity/neutral), ≤5 active/hand. NJS constant per difficulty. Precision: ≤1/16 ≤180 BPM, ≤1/8 ≤360 BPM. The in-core swing simulator (REQ-BS-04) plus GalaxyMaster Parity Checker + Kival Evan Map Check are the three referees.