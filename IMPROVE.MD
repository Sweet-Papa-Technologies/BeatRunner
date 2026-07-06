# BEATFORGE — Music-Aware Track & Chart Pipeline for OVERDRIVE

**Spec version:** 1.0 · **Target repo:** `Sweet-Papa-Technologies/BeatRunner`
**Implementer:** Claude Code (local) with the `assetforge` SKILL (Vertex AI access: Lyria, Gemini, Imagen)
**Spec conventions:** requirement IDs match `REQ-[A-Z]+-\d+`; acceptance criteria are labelled `Accept:` (compatible with `spec-lint` / `trace-gate` in `gates.config` + `policy.json`).

---

## 0. Context & Diagnosis (why this exists)

The four demo tracks feel "okayish but not very playable." Root cause is **not** the audio — it's that the charts never listen to the audio. `tools/make_overdrive_maps.py` builds every map from a **hardcoded BPM/offset** and **arbitrary repeating lane arrays** placed at **fixed duration fractions**. Nothing detects a kick, a snare, a drop, or a melodic accent.

Measured ground truth (librosa, mono 22.05kHz) vs. what's hardcoded today:

| track | charted BPM | detected BPM | charted offset | first real onset | onsets in track | duration |
|---|---|---|---|---|---|---|
| overdrive_pulse.ogg | 120 | ~117.5 | 0.10 | 0.163s | 194 | 32.8s |
| midnight_run.ogg | 128 | ~129.2 | 0.10 | 0.209s | 148 | 32.8s |
| neon_nights.ogg | **92** | **~136** | 0.15 | 0.209s | 133 | 32.8s |
| sweetpapa_groove.ogg | 88 | ~89.1 | 0.20 | 0.070s | 99 | 32.8s |

Consequences: every note drifts against the audio by the offset error; `neon_nights` is charted on a grid that may be metrically wrong altogether; and 100–200 real musical onsets per track are ignored in favor of a metronome. The game's judgment windows are **Perfect ±50ms / Good ±120ms** (`src/core/timing.ts`, `DEFAULT_WINDOWS`), so a 50–100ms grid error alone eats the entire Perfect window.

**Note:** detected BPMs above are single-pass librosa estimates and carry octave/metric ambiguity (the 92-vs-136 case may be a 2:3 relationship). Do not copy these numbers into the game — the pipeline below measures them properly (REQ-DSP-02).

## 1. Mission, Pillars, Non-Goals

**Mission:** Every shipped track is (a) musically strong source audio and (b) charted so that hitting notes *feels like playing the music* — kicks, snares, melodic accents, builds, and drops land where the ear expects them.

**Pillars (Way of the FoFo, applied):**
1. **Deterministic-first.** All *timing truth* (tempo, beat grid, onsets, offsets) comes from DSP, is cached as JSON, and is reproducible. The LLM never invents a timestamp.
2. **Judgment where it belongs.** Gemini 3.5 Flash does what DSP can't: hear structure, feel, and intent — then makes *design decisions* (which onsets become notes, lanes, holds, density shaping) by **selecting from DSP-provided candidates by ID**, never emitting raw times. This is the core anti-hallucination mechanism of the whole spec.
3. **Author ≠ Judge.** The chart designer call and the chart critic call are separate model invocations with separate contexts. Deterministic gates referee both.
4. **Casual-first stays law.** Miss never kills; charts must be *fun to flow through*, not punishing. Density budgets are hard limits, not suggestions.
5. **Core is sacred.** Zero diffs under `src/core/`. `npm test` stays green untouched. Everything here is tools + data + thin shell/UI additions.

**Non-goals:** No new game mechanics beyond existing tap/hold; no networked features; no changing the beatmap schema (the `dur` field already covers holds); no Lyria RealTime streaming (batch generation only).

## 2. Architecture Overview

Compute is split across three backends (§3.5). `[V]` = Vertex-managed model call,
`[C]` = Colab GPU job via the Colab CLI, `[L]` = local CPU. **No local GPU is
used anywhere** — the user's RTX 4090 is intentionally off the table.

```
                 WORKSTREAM A (audio quality loop)                    [V]
  prompt ──▶ Lyria-002 ──▶ candidates ──▶ Gemini 3.5 Flash (A&R critic)
     ▲                                        │ chartability scorecard
     └──────── prompt rewrite ◀───────────────┘ (iterate ≤3, pick best)
                                   │ winner .wav → loudnorm → .ogg   [L]
                                   ▼
                 WORKSTREAM B (deterministic ground truth)     [C] GPU job
  audio ──▶ beat/downbeat tracking ──▶ tempo disambiguation ──▶ offset fit
        ──▶ Demucs stem separation (GPU) ──▶ onset detection (stems + HPSS,
            strengths, IDs) ──▶ structure segmentation + per-bar energy curve
                                   │ analysis.json + stems (pulled back, cached)
                                   ▼
                 WORKSTREAM C (Gemini 3.5 Flash level designer)
  audio + analysis.json + design brief + difficulty budget
        ──▶ thinking_level=high ──▶ chart plan + events as {onset_id | grid_ref}
                                   │
                                   ▼
                 WORKSTREAM D (deterministic validate/repair/QA)
  ID→time resolution ──▶ schema parity with core/beatmap.ts ──▶ snap check
        ──▶ ergonomic lint ──▶ metric gates ──▶ (fail → structured re-prompt ≤3)
        ──▶ Gemini critic pass (fresh context, Author≠Judge) ──▶ ship/fail
                                   │ *.beatmap.json (3 difficulties)
                                   ▼
                 WORKSTREAM E (game integration)
  tracks.ts (measured BPM, difficulty map refs) + TrackSelect difficulty picker
```

New code lives in `tools/beatforge/` as a proper Python package with a CLI:

```
tools/beatforge/
  __main__.py        # python -m beatforge {generate|analyze|chart|validate|all} [--track id]
  config.py          # models, budgets, thresholds — ALL tunables in one place
  gen.py             # Workstream A: Lyria loop + Gemini A&R critic
  analyze.py         # Workstream B: orchestrates analysis via the compute backend
  design.py          # Workstream C: Gemini designer calls + prompt assembly
  validate.py        # Workstream D: schema parity, snap, ergonomics, repair
  qa.py              # Workstream D: metric gates + critic pass + reports
  vertex.py          # shared Vertex client (mirror tools/generate_overdrive_assets.py:
                     #   gcloud print-access-token, us-central1, VERTEX_PROJECT env)
  compute.py         # ComputeBackend interface + ColabBackend / LocalBackend (§3.5)
  jobs/
    analyze_job.py   # SELF-CONTAINED analysis script shipped to Colab via `colab exec -f`.
                     #   Reads audio, runs madmom + Demucs + librosa, writes analysis.json
                     #   + stems + previews to the remote CWD; no beatforge imports.
    requirements.lock # pinned deps installed on the Colab VM (madmom, demucs, torch, librosa…)
  schemas/           # JSON Schemas: analysis.json, designer output, scorecards
  prompts/           # designer / A&R critic / chart critic prompt templates (files, not inline strings)
build/analysis/      # cached per-track analysis JSON + stems + QA reports (committed)
```

`jobs/analyze_job.py` is deliberately standalone (stdlib + the pinned scientific
stack only) because the Colab CLI ships a file's *contents* to a remote kernel —
it cannot resolve local package imports. Treat it as a portable payload, not part
of the `beatforge` package graph.

Idempotent like the existing generators: every stage skips work whose output already exists unless `--force`. Every artifact (candidate audio, analysis, raw designer output, repair log, QA report) is written to disk so failed runs are debuggable.

## 3. Model & API Facts (verify before hardcoding)

- **Designer/critic model:** Gemini 3.5 Flash (GA, released May 2026). Multimodal input includes **audio**; 1M-token context, 65k max output. Reasoning is controlled by `thinking_level` (minimal/low/medium/high) — **the old `thinking_budget` param is superseded**, and the default level is now `medium`. This pipeline MUST request `thinking_level: "high"` for designer and critic calls (user directive: full thinking power). Google strongly recommends **not** changing `temperature`/`top_p`/`top_k` defaults for Gemini 3.x — leave them alone.
- **Structured output:** request JSON-only responses and validate against `schemas/`; strip code fences defensively; on parse failure retry once with the parse error included, then fail the stage.
- **Music generation:** `lyria-002` on Vertex (already used in `tools/generate_overdrive_assets.py`; outputs ~32.8s WAV via `bytesBase64Encoded`). Keep the same endpoint/auth pattern.
- **First implementation step:** use `assetforge` to list available model IDs in `us-central1` for the project and confirm the exact Gemini 3.5 Flash Vertex model string + audio-input support + `thinking_level` request shape. Record what you find in `tools/beatforge/config.py` comments. Do not guess IDs from this spec.

## 3.5 Compute Backends (Vertex / Colab / local)

Three backends, each doing only what it's best at. **No local GPU.**

- **`[V]` Vertex** — managed model inference: Lyria-002 (music) and Gemini 3.5 Flash (A&R critic, designer, chart critic). Called from the developer's machine via the existing `gcloud`-token pattern. No GPU management, no provisioning.
- **`[C]` Colab GPU** — the compute-heavy DSP that used to want the 4090: **Demucs (htdemucs) stem separation** and **madmom** DBN beat/downbeat tracking (whose local install is notoriously fussy). Run via the official **Google Colab CLI** (`googlecolab/google-colab-cli`, GA June 2026), which connects the local terminal to an ephemeral remote Colab runtime.
- **`[L]` Local CPU** — light glue that needs no accelerator: prompt assembly, JSON validation/repair, ergonomic lint, metric computation, `ffmpeg loudnorm`/encode, and matplotlib/ffmpeg previews. Runs wherever Claude Code runs.

**Colab CLI facts (verified; confirm exact flags with `colab <cmd> --help` before hardcoding):**
- Install: `uv tool install git+https://github.com/googlecolab/google-colab-cli` (pip fallback). Linux/macOS only.
- Session lifecycle: `colab new [--gpu T4|L4|A100|H100] [-s <name>]` → `colab install <pkgs>` → `colab exec -f <script.py>` (ships the *file contents* to the remote kernel; **no separate upload of the script needed**) → `colab download <remote_path>` → `colab log -o <file>` → `colab stop`.
- File movement: `colab upload` / `colab download` move data both ways; `colab drivemount` mounts Drive at `/content/drive`; `colab auth` authenticates the VM for Google Cloud.
- **Ephemeral job runner:** `colab run` provisions a fresh VM, runs a local script with forwarded args, retrieves output files, and tears the runtime down — in one command. This is the preferred entry point for the analysis job (fewest moving parts, guaranteed teardown).
- The CLI ships a `COLAB_SKILL.md` for agents; the implementer should read it and prefer it over this summary where they differ.

**Backend routing rule (put in `compute.py`):** an operation runs on Colab **iff** it needs a GPU *or* a dependency that's painful/non-deterministic to install locally (Demucs, madmom). Everything else is local. Vertex is never replaced by Colab for model calls — though note `colab auth` means the Colab VM *could* call Vertex directly if co-location ever helps; not needed for v1.

**REQ-COMPUTE-01 — Backend abstraction.** `compute.py` defines a `ComputeBackend` protocol with `run_analysis(audio_path, opts) -> AnalysisResult` returning `analysis.json` + stem paths + preview paths. Provide `ColabBackend` (default) and `LocalCpuBackend` (no stems, madmom optional → librosa fallback per REQ-DSP-01). Selected via `config.py` / `--backend {colab,local}`. Callers in `analyze.py` never touch the CLI or librosa directly — only the backend.
`Accept:` a fake `InMemoryBackend` fixture satisfies the protocol and lets Workstreams C/D run in tests with zero network; swapping backends changes no caller code.

**REQ-COMPUTE-02 — Colab job contract.** `ColabBackend` provisions a GPU session (`--gpu`, type from config, default T4; escalate to L4/A100 only if T4 OOMs on Demucs), installs `jobs/requirements.lock`, uploads the track audio, runs `jobs/analyze_job.py` via `colab exec -f` (or `colab run`), then downloads `analysis.json`, the four Demucs stems, and any previews. The remote script writes a `job_meta.json` (backend versions, GPU type, wall-clock, package hashes) that is stored beside the analysis.
`Accept:` one live run against `overdrive_pulse.ogg` produces `build/analysis/overdrive_pulse.analysis.json` + stems + `job_meta.json`; the QA report names the GPU used and the madmom/Demucs/torch versions.

**REQ-COMPUTE-03 — Teardown & cost hygiene.** Every provisioned session is stopped in a `finally` (or via `colab run`'s auto-teardown) even on failure; the backend never leaves a runtime alive. A batch (`beatforge all`) reuses **one** session for all four tracks rather than provisioning per track. Session name is namespaced (`beatforge-<runid>`); `colab stop` is idempotent and logged.
`Accept:` an integration test simulating a mid-job exception asserts teardown was invoked; a 4-track batch provisions exactly one session (assert via the backend's session log).

**REQ-COMPUTE-04 — Determinism across the wire.** `jobs/requirements.lock` pins exact versions (torch, torchaudio, demucs, madmom, numpy, librosa); the job sets `PYTHONHASHSEED`, `torch.manual_seed`, and forces Demucs deterministic inference. Re-running analysis on the same audio with the same lock yields byte-identical `analysis.json` (modulo the `job_meta` timing fields, which are excluded from the equality check). Results are cached locally by `(audio_sha256, lock_sha256)` so re-runs never re-provision unless `--force`.
`Accept:` two consecutive live runs of the same track produce identical `analysis.json` (excluding `job_meta`); a third run with an unchanged cache key provisions no Colab session at all.

**REQ-COMPUTE-05 — Graceful degradation, never silent.** If Colab is unavailable (no auth, quota exhausted, provisioning failure), the backend fails loudly with a clear message and, only when `--allow-local-fallback` is set, drops to `LocalCpuBackend` (HPSS-only, no stems) and **stamps the analysis + every chart built from it** with `"stem_source": "none"` so QA (REQ-QA-01) and the user can see the reduced-fidelity path was taken.
`Accept:` with Colab forced-unavailable and the flag unset, the pipeline exits non-zero with an actionable error; with the flag set, it completes and every downstream artifact carries the degradation stamp.

## 4. Workstream A — Better Source Tracks (Lyria × Gemini A&R loop)

The current tracks were single-shot Lyria generations. "Better tracks" = generate **candidates**, have Gemini 3.5 Flash *listen* and score them for **chartability**, and iterate the Lyria prompt against the weaknesses it hears. Music understanding is exactly where this model earns its keep — use it as the A&R ear, not the composer.

**REQ-GEN-01 — Candidate fan-out.** For each catalogue track, generate N=4 Lyria candidates per round (distinct seeds/prompt variants), up to K=3 rounds.
`Accept:` a `gen` run for one track produces ≥4 candidate WAVs on disk with a `round-N` naming scheme, and stops early if any candidate reaches the ship threshold (REQ-GEN-03).

**REQ-GEN-02 — Chartability scorecard.** Gemini 3.5 Flash receives each candidate's audio and returns a strict-JSON scorecard scoring 0–10 on: tempo stability, transient clarity (kick/snare definition), structural contrast within ~33s (identifiable build→drop or verse→hook), intro cleanliness (no long silence/fade-in), mix punch (drums not buried), and genre fit to the track's brief. Plus a one-paragraph "what I'd change" critique.
`Accept:` scorecards validate against `schemas/scorecard.json`; a deliberately degraded input (e.g., 3s of prepended silence) scores measurably lower on intro cleanliness in a recorded fixture run.

**REQ-GEN-03 — Prompt rewrite loop.** If no candidate's weighted score ≥ 8.0, Gemini rewrites the Lyria prompt targeting the two lowest rubric dimensions (e.g., "punchier four-on-the-floor kick, drums forward in the mix, clear 8-bar build into a drop at the midpoint") and the next round runs. Winner = highest weighted score across all rounds.
`Accept:` the loop terminates in ≤3 rounds, logs every prompt + scorecard to `build/analysis/<track>.gen-log.json`, and the selected winner's scorecard is stored alongside the shipped audio.

**REQ-GEN-04 — Mastering normalization.** Winner WAV is post-processed deterministically: trim leading silence to ≤120ms before first transient, loudness-normalize to −14 LUFS integrated (ffmpeg `loudnorm`, two-pass), true-peak ≤ −1.0 dBTP, encode to `.ogg` (libvorbis q6) into `assets/tracks/` + `public/assets/tracks/`, update `_manifest.json`.
`Accept:` `ffmpeg loudnorm` analysis of every shipped `.ogg` reports integrated loudness within ±1 LU of −14 and true peak ≤ −1.0 dBTP; first onset (per Workstream B) occurs within 0.30s of file start.

**REQ-GEN-05 — Keep-the-hits option.** The loop must be runnable per-track. Existing tracks the user likes can be kept as-is and flow straight into Workstreams B–D (`beatforge all --skip-gen`).
`Accept:` running `python -m beatforge all --skip-gen` recharts the four existing `.ogg` files without touching audio.

**Stretch (do not block v1): REQ-GEN-06 — Longer tracks.** Investigate multi-segment generation (generate 2–3 Lyria clips from continuation-style prompts, beat-align and crossfade at downbeats to reach ~60–90s). Gate behind a config flag; ship only if the seam passes the A&R scorecard.
`Accept:` documented findings in the gen-log even if the answer is "not viable with lyria-002"; feature flag defaults off.

## 5. Workstream B — Deterministic Audio Ground Truth

All timing truth is computed here, once, cached, and versioned. This is the layer that fixes the drift and the wrong-tempo chart *even before any LLM is involved*.

**REQ-DSP-01 — Beat & downbeat tracking.** Primary: `madmom` `DBNBeatTrackingProcessor` + `DBNDownBeatTrackingProcessor` (state of the art, deterministic), run **inside the Colab job** (`jobs/analyze_job.py`) where its fussy Cython/numpy pinning is baked into `requirements.lock` once and never fought locally. Fallback (only on the `LocalCpuBackend` degraded path, REQ-COMPUTE-05): `librosa.beat.beat_track` with `tightness` tuned, plus autocorrelation downbeat inference. The method actually used is recorded in the analysis JSON (`"beat_backend": "madmom_dbn" | "librosa"`).
`Accept:` analysis JSON contains an ordered beat-time array and downbeat indices; re-running analysis on the same file byte-identically reproduces the JSON (deterministic seeds/settings).

**REQ-DSP-02 — Tempo octave/metre disambiguation.** From the raw tempo estimate T, evaluate candidates {T/2, 2T/3, 3T/4, T, 4T/3, 3T/2, 2T}: for each, fit the best phase offset and score = mean onset-envelope strength sampled at the candidate grid, normalized. Pick the max; tie-break toward the 84–150 BPM band (genre prior for synthwave). Store the winner as float BPM (e.g., 117.48) plus the per-candidate score table.
`Accept:` for `neon_nights.ogg` the analysis emits the score table and a resolved BPM whose grid alignment score beats the hardcoded 92-BPM grid; a unit test covers the disambiguation math on a synthetic click track at a known tempo.

**REQ-DSP-03 — Offset fit.** Offset = time of the first downbeat, refined by maximizing onset-envelope energy at grid times over a ±60ms sweep in 1ms steps. Stored at ms precision. The `beatTime(n, bpm, offset)` formula in `src/core/timing.ts` is the contract: `offset + n/bpm*60` must land grid lines on the music.
`Accept:` for every shipped track, ≥85% of detected percussive onsets lie within ±35ms of some grid line at subdivision ≤ 1/4 beat (this is the empirical proof the grid is right).

**REQ-DSP-04 — Onset inventory with IDs.** Run HPSS; detect onsets separately on the percussive component (rhythm candidates) and full mix (melodic/accent candidates). Each onset gets: stable `id` (e.g., `p017`, `m042`), time (s), nearest grid beat (float, at 1/4-beat resolution) + snap error (ms), strength (normalized 0–1), band energy split (low/mid/high — proxy for kick vs snare/clap vs hat/lead), and a `sustain` flag with duration for harmonic-energy plateaus ≥1 beat (hold candidates, from harmonic RMS).
`Accept:` analysis JSON validates against `schemas/analysis.json`; every onset's `nearest_beat` reproduces its time within |snap error| via the track's bpm/offset; counts are in the same order of magnitude as the diagnosis table (sanity gate: 50–400 onsets for a ~33s track).

**REQ-DSP-05 — Structure & energy.** Segment the track (`librosa.segment` spectral-clustering novelty approach) into labelled sections; compute per-bar RMS energy and a normalized energy curve; label each section with an energy percentile and a coarse role guess (`intro|build|drop|break|outro`) by heuristic (position + energy + novelty). These are *hints* for the designer, clearly marked as heuristic in the JSON.
`Accept:` analysis JSON lists sections with bar-aligned boundaries covering the full duration, plus a per-bar energy array whose length equals the bar count.

**REQ-DSP-06 — Stem-level truth (Tier 2, default ON via Colab GPU).** Inside the same Colab job, run Demucs (htdemucs) stem separation on the GPU; compute drum-stem onsets (highest-confidence rhythm) and other/lead-stem sustained notes (highest-confidence hold candidates), merged into the onset inventory with a `source: stem_drums|stem_lead|mix` tag. This is the work that previously wanted the local 4090 — it now runs on a Colab T4/L4/A100 (`[C]`, REQ-COMPUTE-02) and its stems are pulled back and cached. On the degraded `LocalCpuBackend` path only, stems are absent and HPSS-only (REQ-DSP-04) is the truth source, stamped `stem_source: none`.
`Accept:` on the Colab backend the onset inventory contains stem-tagged entries, the four stems are cached under `build/analysis/`, and the QA report names the GPU + Demucs version; on the forced-local path the pipeline still completes with `stem_source: none`.

## 6. Workstream C — Gemini 3.5 Flash as Level Designer

The designer call is the heart of the "music nuance" bet. It gets to *hear the actual audio* AND read the DSP facts, then makes design decisions — but it can only place notes by **referencing candidates the DSP layer provided**. It never writes a raw timestamp.

**Designer inputs (one call per track × difficulty):**
1. The track audio itself (multimodal part).
2. `analysis.json` (bpm, offset, beats, onset inventory with IDs, sections, energy curve).
3. The design brief (`prompts/designer.md`): game description, lane grammar, judgment windows (Perfect ±50ms / Good ±120ms), casual-first pillar, hold mechanics (`dur` beats, press-and-hold one lane).
4. The difficulty budget table (below) as hard constraints.
5. The output contract (`schemas/designer-output.json`).

**Lane grammar (from `make_overdrive_maps.py` `LANE_TYPE` — schema `type` encodes the lane):** `GAP` = left lane, `BAR` = center lane, `NOTE` = right lane. Musical mapping guidance for the brief: kicks bias center; snares/claps alternate the outer lanes; melodic runs map pitch contour to lane movement (rising = left→right); holds go on `sustain`-flagged candidates (pads, held lead notes); section transitions get a telegraphed accent (a hold or a distinctive 3-note sweep). Symmetry and flow matter more than novelty.

**Output contract (strict JSON):**
```json
{
  "design_notes": "1 short paragraph per section: what the music does, what the pattern does",
  "sections": [ { "name": "...", "start_bar": 0, "intent": "..." } ],
  "events": [
    { "ref": "p017", "lane": "BAR" },
    { "ref": "grid:36.5", "lane": "NOTE" },
    { "ref": "m042", "lane": "GAP", "hold_beats": 4 }
  ]
}
```
`ref` is either an onset ID from the inventory or `grid:<beat>` for a grid-line placement (subdivision limited by difficulty). `hold_beats` must correspond to a `sustain` candidate's duration (±1 beat). Anything else is a validation error, not a negotiation.

**Difficulty budgets (hard constraints, enforced in Workstream D):**

| | Casual | Standard | Overdrive |
|---|---|---|---|
| min gap between events | ≥ 1 beat AND ≥ 350ms | ≥ 0.5 beat AND ≥ 200ms | ≥ 0.25 beat AND ≥ 120ms |
| finest grid subdivision | 1 beat | 1/2 beat | 1/4 beat |
| max sustained NPS (any 4s window) | 2.0 | 4.0 | 7.0 |
| same-lane consecutive (jack) limit | 2 | 3 | 4 |
| taps in other lanes during a hold | none | 1 other lane only | 2 other lanes, no chords |
| simultaneous events (chords) | never | never | never (holds+tap per above only) |
| hold length | 2–8 beats | 1–8 beats | 1–8 beats |
| share of events that are holds | 10–20% | 5–15% | 5–12% |
| density vs. energy | must rise into high-energy sections and breathe in breaks (QA metric REQ-QA-02) | same | same |

**REQ-CHART-01 — Designer call.** Implement the designer as one Gemini 3.5 Flash call per (track, difficulty) with `thinking_level: "high"`, audio + analysis + brief + budget + contract as above; parse and store the raw response to `build/analysis/<track>.<difficulty>.design.json`.
`Accept:` for each of the 4 tracks × 3 difficulties, a design JSON exists that validates against the output schema; every `ref` resolves against the track's onset inventory or a legal grid subdivision for that difficulty.

**REQ-CHART-02 — No raw timestamps.** The designer prompt forbids, and the parser rejects, any event carrying a numeric time field. Times enter the beatmap only via deterministic resolution of `ref` → onset time → `nearest_beat` (or `grid:<beat>` directly).
`Accept:` a unit test feeds a fixture designer-output containing `{"time": 12.34}` and the parser rejects it with a specific error.

**REQ-CHART-03 — Musical intent is recorded.** `design_notes` and `sections` from every shipped chart are preserved in the build artifacts (not the beatmap — schema stays untouched) so a human can audit *why* the chart looks the way it does.
`Accept:` `build/analysis/` contains design notes for every shipped chart; README gains a short "how charts are made" section pointing at them.

## 7. Workstream D — Deterministic Validation, Repair, QA Gates

**REQ-VAL-01 — Schema parity.** A Python validator with semantics identical to `src/core/beatmap.ts` `parseBeatmap`: required fields/types, `events` sorted ascending, same-(beat,type) dedupe, `dur` optional and > 0 when present. The emitted `*.beatmap.json` must load in the game with zero warnings.
`Accept:` pytest round-trips every emitted map through the validator; additionally a Node one-liner (`npx tsx`) imports the real `parseBeatmap` and parses every emitted map in CI fashion — the TS core is the final referee of its own schema.

**REQ-VAL-02 — Grid & snap integrity.** Every resolved event beat must (a) lie on a legal subdivision for its difficulty and (b) if it came from an onset ref, have |snap error| ≤ 35ms. Events before beat 4 or after the last playable beat (track duration − 1.4s tail, mirroring the existing generator) are dropped with a logged repair.
`Accept:` the QA report lists snap statistics per chart; max |snap error| ≤ 35ms; zero events outside the playable window.

**REQ-VAL-03 — Ergonomic lint + salience repair.** Enforce the full difficulty budget table. On violation, repair by removing the lowest-salience offending notes (salience = onset strength; grid-only notes are lowest) rather than failing — then re-lint. Repairs are logged with reasons. If >15% of a chart's events get repaired away, the chart fails and triggers the re-prompt loop (REQ-QA-03).
`Accept:` unit tests cover each budget rule with minimal fixtures (a jack chain, a too-dense burst, a chord, an illegal tap-during-hold) demonstrating detection and correct minimal repair.

**REQ-QA-01 — Objective chart metrics.** Compute per chart: onset alignment (% of events whose resolved time is within ±35ms of a detected onset — grid-only events excluded and separately counted), lane balance (each lane's share), hold share, NPS curve, and repair count.
`Accept:` shipped charts satisfy: onset alignment ≥ 90% (Casual may be ≥ 80% since sparse charts skip onsets, not miss them); every lane 22–45%; hold share within the difficulty band; ≤ 15% repaired.

**REQ-QA-02 — Density follows the music.** Spearman correlation between the per-bar event count and the per-bar energy curve must be ≥ 0.55, AND the highest-energy section must contain the chart's peak 4s NPS window, AND at least one section with energy below the 30th percentile has event density below the chart median (the chart *breathes*).
`Accept:` metrics in the QA report; all three conditions hold for every shipped chart.

**REQ-QA-03 — Structured re-prompt loop.** If gates fail, re-invoke the designer with the original context + the machine-readable violation report ("chart failed: NPS 8.2 in window 14.0–18.0s exceeds 7.0; lane GAP at 12% below 22% floor…"). Max 3 attempts per (track, difficulty); then fail the pipeline loudly with all artifacts preserved. No silent degradation.
`Accept:` an integration test with an artificially strict budget shows the loop feeding violations back and either converging or failing after 3 attempts.

**REQ-QA-04 — Critic pass (Author ≠ Judge).** A *fresh-context* Gemini 3.5 Flash call (`thinking_level: "high"`) receives the audio + the final resolved chart (beats→times rendered for it) + the design brief, and returns a musicality review: score 0–10, plus specific issues ("the drop at bar 17 starts two beats late relative to the kick pattern"). Ship threshold ≥ 7. Below threshold → one targeted designer revision, then human review (report to user, don't loop forever).
`Accept:` critic reviews stored per shipped chart; PROVENANCE.yaml gains entries recording designer vs. critic as separate contexts, matching the existing Author/Judge convention.

**REQ-QA-05 — Human-auditable preview.** Emit a per-chart preview: a rendered PNG timeline (matplotlib: waveform + onsets + placed events by lane + section boundaries) and a click-track render (ffmpeg: original audio + tick at each event) as `build/analysis/<track>.<difficulty>.preview.{png,ogg}`.
`Accept:` previews exist for every shipped chart; the click-track is the fastest possible human verification that notes land on the music — listen before shipping.

## 8. Workstream E — Game Integration

**REQ-INT-01 — Measured BPM/offset become truth.** All four `tracks.ts` entries and all emitted beatmaps use the measured float BPM and ms-precision offset from Workstream B. The display BPM in TrackSelect may round to integer; the map values must not.
`Accept:` grep shows no chart carrying the old hardcoded values where measurement disagrees by >0.5 BPM or >20ms; `neon_nights` in particular ships on its resolved grid.

**REQ-INT-02 — Three difficulties, additive schema.** Emit `public/maps/<track>.casual.beatmap.json`, `.standard.`, `.overdrive.`. Extend `TrackDef` with an optional `maps?: { casual: string; standard: string; overdrive: string }` while keeping the existing `map` field pointing at the standard chart (backward compatible — nothing in `src/core` changes).
`Accept:` `npm run build` passes; a track entry without `maps` still works exactly as before.

**REQ-INT-03 — Difficulty picker.** Minimal TrackSelect addition: a 3-state difficulty toggle (default Standard) that selects which map URL Play loads. Styling consistent with the existing neon UI; keyboard: left/right on a focused card or number keys 1/2/3.
`Accept:` playable end-to-end on all three difficulties for all four tracks in `npm run dev`; pause/resume and results flow unchanged.

**REQ-INT-04 — Legacy generators preserved.** `make_overdrive_maps.py` / `make_beatmaps.py` stay for provenance (as the README already promises) but README's "Regenerating assets" section is updated to present `python -m beatforge all` as the canonical path.
`Accept:` README documents the new pipeline: prerequisites (VERTEX_PROJECT, gcloud auth, ffmpeg, local Python deps + pins, **Colab CLI installed and authed — `uv tool install git+https://github.com/googlecolab/google-colab-cli` then `colab new` once to confirm auth**), the CLI verbs, the compute-backend split (`[V]`/`[C]`/`[L]`), and where artifacts land.

**REQ-INT-05 — Core untouched, suite green.** Zero diffs under `src/core/` and `tests/`. `npm test` and `npm run build` pass.
`Accept:` `git diff --stat` shows no changes in `src/core/**` or `tests/**`; CI-equivalent local run is green.

## 9. Testing Strategy

- **Python:** pytest for `tools/beatforge/` — tempo disambiguation on synthetic click tracks (REQ-DSP-02), snap math, every ergonomic rule (REQ-VAL-03), designer-output parsing incl. the raw-timestamp rejection (REQ-CHART-02), schema parity fixtures, and backend teardown/degradation (REQ-COMPUTE-03/05). All model calls *and the compute backend* sit behind interfaces with recorded-fixture fakes (`InMemoryBackend`, recorded `analysis.json`), so the whole suite runs offline, deterministic, and **without ever provisioning a Colab runtime**. `jobs/analyze_job.py` gets its own focused tests run in-process on a tiny synthetic clip (the DSP math is testable without the CLI).
- **TS:** no new core tests needed (core untouched); the Node `parseBeatmap` round-trip of emitted maps (REQ-VAL-01) is the cross-language contract test.
- **Live smoke:** one `--track overdrive --difficulty standard` end-to-end run with real Vertex calls, artifacts committed under `build/analysis/` as the reference run.
- **SDLC hookup:** add this spec's REQ IDs to `TEST-REQS.yaml` mapping (new `beatforge` section); `trace-gate` should trace REQ-DSP/VAL/CHART parse rules to pytest tests (extend `test_glob` in `policy.json` with `tools/beatforge/tests/**/*.py` or run the Python trace equivalently — implementer's choice, documented).

## 10. Order of Work (suggested)

0. **Compute backend + Colab job** (`compute.py`, `jobs/analyze_job.py`, `requirements.lock`): stand this up first with a throwaway "hello GPU" `colab exec` to confirm auth/quota (the community's noted failure mode is the browser auth loop — flush it out on day one, not during the first real run). Build `jobs/analyze_job.py` against a local tiny clip in-process before wiring the CLI.
1. **B** (analyze.py orchestration over the backend + schemas + tests): needs no LLM, immediately fixes BPM/offset truth via the Colab job, and everything else depends on it.
2. **D validators** (validate.py + qa.py metrics): LLM-free; lets you test the whole contract with hand-written fixture designs.
3. **C designer** (design.py + prompts): now the model plugs into a rig that already referees it.
4. **E integration** (charts in game, difficulty picker) — first playable "wow" moment; playtest here.
5. **A generation loop** (gen.py) — improves the audio itself last, since B–D make even the current audio dramatically more playable.
6. **QA critic + previews + README/TEST-REQS** — finish line.

## 11. Definition of Done

All REQ `Accept:` criteria pass; `npm test`/`npm run build` green with zero core diffs; four tracks × three difficulties ship with QA reports, critic reviews ≥ 7, previews rendered; the click-track previews *sound locked to the music by ear*; README updated; PROVENANCE.yaml records designer/critic separation. The user playtests Standard on all four tracks and the charts feel like the music — that's the real gate.

---

## Appendix A — Designer prompt skeleton (`prompts/designer.md`)

> You are the level designer for OVERDRIVE, a 3-lane synthwave rhythm highway (lanes: GAP=left, BAR=center, NOTE=right; taps and holds; judgment: Perfect ±50ms, Good ±120ms; casual-first — missing breaks combo but never kills). You are given the track's audio and a machine analysis: tempo, beat grid, an onset inventory (each onset has an ID, grid position, strength, band character, and sustain info), sections, and a per-bar energy curve. Listen to the audio. Then design a {difficulty} chart as a JSON object per the contract.
> Rules: you may only place events by onset ID or `grid:<beat>` at legal subdivisions; never output times. Chart the music, not a metronome: kicks bias center, snares alternate outer lanes, melody contour steers lane movement, sustained notes become holds, section transitions get telegraphed accents. Respect every budget limit — they are hard constraints. Make the drop feel like the drop and let the breaks breathe. Before emitting JSON, think through the section-by-section plan.

## Appendix B — Diagnosis reproduction

The numbers in §0 came from: librosa 22.05kHz mono load of each `public/assets/tracks/*.ogg`; `librosa.feature.tempo` for BPM; `librosa.onset.onset_detect(units="time")` for onsets. Reproduce anytime to sanity-check Workstream B against a naive baseline — B must beat this baseline, not merely match it.