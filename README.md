# OVERDRIVE

A **synthwave rhythm highway** built on your own tracks. Notes rush toward you
down a neon perspective road — strike them in time across **three lanes** (the
left / centre / right of the highway), chain holds, build combo, and make the
world pulse. Casual-first: missing never kills you — it just scores lower and
breaks your combo.

Engine: **Phaser 3 + TypeScript + Vite**. Deterministic core: **framework-free TS**,
test-driven via the FoFo Agentic SDLC loop. Art + music: **generated on Vertex AI**
(Imagen 3 backgrounds, Gemini 2.5 Flash Image mascot frames, Lyria music).

> Recycled from *In the Pocket*: the entire pure, unit-tested core
> (`timing` / `scoring` / `beatmap` / `run` / `AudioEngine`) is untouched — only
> the presentation and gameplay shell were rebuilt into the lane highway. The
> beat-map schema gained one backward-compatible optional field (`dur`) for holds.

![title](docs/screenshots/title.jpeg)
![gameplay](docs/screenshots/gameplay.jpeg)

## Run it

```bash
npm install
npm run dev        # http://localhost:5173
npm test           # vitest — the deterministic core suite
npm run build      # typecheck + production build to dist/
```

Controls: lanes are **◄ ▼ ►** / **A S D** / **J K L** (left / centre / right),
**P** pause, **M** mute metronome. Touch: left / middle / right thirds of the
screen. Hold a lane through a sustain note for bonus.

## Architecture

The whole game is a thin Phaser shell over a **pure, unit-tested core**. All timing
reads from `AudioContext.currentTime` (never `Date.now` / frame delta).

```
src/
  core/            # ZERO Phaser imports — fully unit-tested (Vitest)
    timing.ts      # beatTime, judgment windows, nearest-beat, injectable clock
    scoring.ts     # base points, combo, multiplier tiers, accuracy, grade
    beatmap.ts     # schema validation, ordering/dedupe, spawn lead
    run.ts         # lifecycle state machine + drift-free pause/resume clock
  audio/AudioEngine.ts   # Web Audio: track playback, beat-locked metronome, SFX
  game/            # config, track catalogue, reusable neon FX
  scenes/          # Boot, TrackSelect, Play, Results
maps/  (served from public/maps)   # *.beatmap.json
assets/ (served from public/assets) # tracks/, sprites/
tools/             # Vertex AI asset + beatmap generators
```

Add a song: drop an `.ogg` in `public/assets/tracks/`, author a
`public/maps/*.beatmap.json`, and add an entry to `src/game/tracks.ts`.

## Built with the FoFo Agentic SDLC

The deterministic core was built test-first with separated authorship:

- **Spec → `spec-lint`** (Phase 0): `in-the-pocket-spec.md` carries 15 `REQ-*` IDs
  with acceptance criteria.
- **Judge** (spec-only subagent) wrote `TEST-REQS.yaml` + the Vitest suite **before**
  any implementation existed — red for the right reason.
- **Author** (separate context) implemented the core to green, never editing the tests.
- **Referee** gate scripts graded code *and* tests: `trace-gate` (15/15 traced),
  `redgreen-gate`, `intent-gate` (no assertion-free/trivial tests).
- **Fresh-eyes reviewer** (third context) checked for cheating, correctness, and
  spec drift; its findings drove a test-hardening pass.

See `policy.json`, `gates.config`, `TEST-REQS.yaml`, `PROVENANCE.yaml`.

### Open Operator decisions (escalations)

- **`REQ-SCORE-05` "weighted" accuracy** — the spec says *weighted* but gives an
  *unweighted* formula. Shipped unweighted (matches the literal formula and the
  casual-first pillar). Change `accuracy()` + its tests if weighting is intended.
- **Phaser version** — spec says Phaser 4; shipped on the current stable **Phaser 3.90**
  (identical scene/audio API for everything used here).

## Regenerating assets (Vertex AI)

Requires a GCP project with Vertex AI enabled and `gcloud` auth:

```bash
VERTEX_PROJECT=<your-project> python3 tools/generate_overdrive_assets.py all  # Imagen sky/ridge/city + Lyria tracks
VERTEX_PROJECT=<your-project> python3 tools/generate_hero_anim.py             # Gemini mascot frames
```

## BEATFORGE — music-aware charts (canonical pipeline)

Charts are no longer hand-authored on a hardcoded BPM. **beatforge** measures each
track's real tempo/grid/onsets with DSP, then **Gemini 3.5 Flash *listens* to the
audio** and designs three difficulties by *selecting DSP-provided onset candidates
by ID* — it never invents a timestamp. Deterministic gates referee every chart, and
a separate fresh-context Gemini critic judges musicality (Author ≠ Judge). Spec:
[`IMPROVE.MD`](IMPROVE.MD).

```bash
# Prereqs: VERTEX_PROJECT + gcloud auth (or ~/.assetforge/sa-key.json), ffmpeg,
# and local python deps numpy/scipy/soundfile (+ matplotlib for PNG previews).
# Optional higher-fidelity DSP on a GPU: the Colab CLI —
#   uv tool install git+https://github.com/googlecolab/google-colab-cli
#   colab new    # once, to flush the browser-auth loop
PYTHONPATH=tools python3 -m beatforge all            # analyze + chart 4 tracks × 3 difficulties
PYTHONPATH=tools python3 -m beatforge analyze        # Workstream B only (DSP truth, no LLM)
PYTHONPATH=tools python3 -m beatforge chart --track neon --difficulty standard
PYTHONPATH=tools python3 -m beatforge validate       # re-parse emitted maps (schema parity)
PYTHONPATH=tools python3 -m beatforge all --with-gen  # also run the Lyria×Gemini A&R audio loop
```

**Compute split** — `[V]` Vertex (Gemini 3.5 Flash designer/critic + Lyria, reached
via the `global`/`v1beta1` endpoint), `[C]` Colab GPU (optional: madmom + Demucs
stems, `--backend colab`), `[L]` local CPU (default: numpy/scipy DSP, HPSS-only,
stamped `stem_source: none`). Backend is abstracted in `tools/beatforge/compute.py`;
Colab failures fail loudly unless `--allow-local-fallback`.

**How charts are made / auditing them** — every run writes to `build/analysis/`:
`<track>.analysis.json` (measured bpm/offset/onsets/sections), per-difficulty
`.design.json` (the designer's raw output + `design_notes` explaining each section),
`.critic.json` (the independent musicality review), `.qa.json` (objective metrics +
gate results), and `.preview.png` / `.preview.ogg` (a timeline image and a
click-track — *listen to the click-track to verify notes land on the music*).
Emitted maps land in `public/maps/<track>.<difficulty>.beatmap.json`.

### Swapping the audio LLM (Gemini ⇄ a self-hosted model)

The designer/critic model is behind one interface (`tools/beatforge/llm.py`), so an
alternative audio-capable model on any **OpenAI-compatible** server (vLLM,
llama.cpp, …) can be dropped in and benchmarked. Lyria (music gen) stays on Vertex.

```bash
# Point at your server and select the backend:
export BEATFORGE_LLM_BACKEND=openai
export BEATFORGE_OPENAI_BASE_URL=http://<host>:8000/v1
export BEATFORGE_OPENAI_MODEL=$(curl -s http://<host>:8000/v1/models | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"][0]["id"])')
python3 -m beatforge chart --track overdrive --difficulty standard   # now uses your model

# Head-to-head vs Gemini 3.5 Flash (audio-understanding probe + designer, one Gemini critic judges both):
python3 -m beatforge compare --track overdrive --difficulty standard
python3 -m beatforge compare --track overdrive --probe-only          # just the audio probe
```

Audio is sent as an OpenAI `input_audio` content part (`.ogg` transcoded to
`BEATFORGE_OPENAI_AUDIO_FORMAT`, default `wav`). The client is covered end-to-end
by `tests/test_llm.py` against a local mock. NB: the server must be reachable from
wherever you run this — a box on a different LAN segment (e.g. `192.168.1.x` when
you're on `192.168.3.x`) will not route.

Local-model knobs (the designer call is far heavier than the probe — big audio +
analysis in, a full chart JSON out — so a small local model can be slow or loop):
- `BEATFORGE_OPENAI_MAX_TOKENS` (default 4096) — caps generation; a chart is
  ~2.5-4k tokens, so this fits with margin and stops runaway output filling VRAM.
- `BEATFORGE_OPENAI_TIMEOUT` (default 300s) — raise for slow hardware.
- `BEATFORGE_OPENAI_TEMPERATURE` (default 0.7) — a little sampling avoids the
  greedy-decode repetition loops that stall structured JSON on local models.
A read timeout now surfaces as a clean per-model error (the comparison keeps its
probe + Gemini results instead of crashing). Start with `compare --probe-only` —
it's the light test that answers "does it hear the audio?" without the heavy design.

The original generators (`make_overdrive_maps.py`, `make_beatmaps.py`,
`generate_assets.py`) are kept for provenance; beatforge is the canonical path.
