# In the Pocket

A neon **rhythm auto-runner** built on your own lo-fi tracks. Auto-run through a
pulsing synthwave city, hit **Jump / Duck / Strike** in time with obstacles that
arrive on the beat, build combo, and light the world up. Casual-first: missing the
beat never kills you — it just scores lower and breaks your combo.

Engine: **Phaser 3 + TypeScript + Vite**. Deterministic core: **framework-free TS**,
test-driven via the FoFo Agentic SDLC loop. Art + music: **generated on Vertex AI**
(Imagen 3 sprites/backgrounds, Gemini 2.5 Flash Image hero animation frames,
Lyria music).

![title](docs/screenshots/title.jpeg)
![gameplay](docs/screenshots/gameplay.jpeg)

## Run it

```bash
npm install
npm run dev        # http://localhost:5173
npm test           # vitest — the deterministic core suite
npm run build      # typecheck + production build to dist/
```

Controls: **SPACE/↑** Jump (GAP), **↓** Duck (BAR), **F** Strike (NOTE), **P** pause,
**M** mute metronome. Touch: bottom thirds = Jump / Duck / Strike.

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
VERTEX_PROJECT=<your-project> python3 tools/generate_assets.py all   # Imagen + Lyria
VERTEX_PROJECT=<your-project> python3 tools/generate_hero_anim.py    # Gemini hero frames
python3 tools/make_beatmaps.py                                       # author charts
```
