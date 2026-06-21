# IN THE POCKET — Game Spec

### A rhythm auto-runner built on your own lo-fi tracks

**Working title:** *In the Pocket* (a drummer's term for locking to the groove — rename freely)
**Engine:** Phaser 4 + TypeScript, 2.5D
**Author:** Sweet Papa Technologies
**Doc role:** Game design spec **and** Phase 0 `SPEC.md` / `REQUIREMENTS.md` for the FoFo Agentic SDLC skill. Every testable rule below carries a stable **REQ-ID** and acceptance criteria so an independent Judge context can write tests against it before any code exists.

---

## 1. The hook

You auto-run through a neon lo-fi world that pulses to the music. Obstacles arrive *on the beat* of the track. Tap **Jump**, **Duck**, or **Strike** in time and you score, build combo, and the world lights up. The killer feature: **levels are your own "Sweet Papa and the Tones" tracks** — each song ships with a beat-map, so the game is literally playable music.

It's casual by design: missing the beat never kills you. It just scores lower and breaks your combo. Rhythm is a *scoring overlay* on a forgiving runner, not a fail-state.

## 2. Design pillars

- **Casual first.** No hard fail in MVP. Forgiving input (buffering, generous windows). Anyone can finish a song.
- **Music-forward.** The track is the level. Everything syncs to the audio clock, not the render loop.
- **Yours.** Drop in any track + beat-map. Your music, your game.
- **Juice is the reward.** Hitting *in the pocket* should feel incredible — flashes, shake, particles, the world breathing on the beat.

## 3. Core loop

Pick a track → countdown → auto-run while obstacles spawn on the beat → tap the right action in time → score/combo build → track ends → results screen with grade. Replay to beat your score.

## 4. Mechanics (MVP)

The hero auto-runs left-to-right at a constant scroll. Three actions, each tied to one obstacle type:

| Action | Obstacle (event type) | On-beat result | Off-beat (within Good) | Miss |
|---|---|---|---|---|
| **Jump** | `GAP` (low gap to clear) | Perfect clear + points | clears, fewer points | stumble: combo reset, brief slow |
| **Duck** | `BAR` (overhead bar) | Perfect slide + points | slides, fewer points | stumble |
| **Strike** | `NOTE` (floating note to hit) | Perfect hit + points | hits, fewer points | note missed, combo reset |

"Stumble" is the casual failure: lose combo, tiny speed dip, visual wobble — never death. Track always plays to the end.

---

## 5. The deterministic core — testable requirements

> This is the heart of the skill test. These rules are pure functions / small state machines and **must live in framework-free TypeScript modules** (`timing.ts`, `scoring.ts`, `beatmap.ts`, `run.ts`) so they're unit-testable without booting Phaser. The Judge writes tests against these IDs before implementation.

### 5.1 Timing & judgment — `timing.ts`

- **REQ-TIME-01 — Beat time.** `beatTime(n, bpm, offset) = offset + (n / bpm) * 60`, seconds.
  *Accept:* bpm=120, offset=0 → `beatTime(0)=0`, `beatTime(4)=2.0`. Fractional bpm (e.g. 93.5) computes without rounding error beyond float epsilon.
- **REQ-TIME-02 — Judgment windows.** Classify input at time `t` against target beat time `b` by `d=|t-b|`: `d ≤ 0.050s` → **Perfect**; `d ≤ 0.120s` → **Good**; else **Miss**. Windows are config constants.
  *Accept:* d=0.050 → Perfect (inclusive); d=0.051 → Good; d=0.120 → Good; d=0.121 → Miss.
- **REQ-TIME-03 — Nearest-beat selection.** Judgment compares against the *closest* candidate event, not merely the next. Tie (exactly equidistant) resolves to the **earlier** beat.
  *Accept:* given beats at 1.00 and 1.50 and input at 1.25, judged against 1.00.
- **REQ-TIME-04 — Audio-clock source of truth.** All timing reads from the audio context clock (`AudioContext.currentTime`), never `Date.now()` or frame delta. (Architectural requirement; verified by review + a clock-injection test.)
  *Accept:* the timing module accepts an injected `now()` clock; tests drive it deterministically with no real audio.

### 5.2 Scoring & combo — `scoring.ts`

- **REQ-SCORE-01 — Base points.** Perfect=100, Good=50, Miss=0.
  *Accept:* exact table.
- **REQ-SCORE-02 — Combo.** Increments by 1 on Perfect or Good; resets to 0 on Miss.
  *Accept:* sequence P,G,M,P → combo 1,2,0,1.
- **REQ-SCORE-03 — Multiplier tiers.** ×1 for combo 0–9, ×2 for 10–19, ×3 for 20–29, ×4 for 30+. Applied to base points of the *current* hit.
  *Accept:* a Perfect landed while combo is 12 awards 100×2 = 200.
- **REQ-SCORE-04 — Run total.** Score is the running sum of awarded points; strictly non-decreasing across a run.
  *Accept:* property test — score after any event ≥ score before it.
- **REQ-SCORE-05 — Grade.** Final grade from accuracy% (perfects+goods / total events, weighted): S ≥ 95, A ≥ 85, B ≥ 70, C ≥ 50, else D. Thresholds config.
  *Accept:* boundary tests at each threshold.

### 5.3 Beat-map — `beatmap.ts`

- **REQ-MAP-01 — Schema validation.** A beat-map has `{ track:string, bpm:number>0, offset:number≥0, events: Event[] }`; each `Event = { beat:number≥0, type:'GAP'|'BAR'|'NOTE' }`. Loader rejects missing/invalid fields with a typed error.
  *Accept:* valid map loads; map with bpm≤0, negative beat, or unknown type is rejected with a clear error.
- **REQ-MAP-02 — Ordering.** Loader returns events sorted ascending by `beat`; duplicate beats with the same type are de-duplicated; different types at the same beat are allowed.
  *Accept:* unsorted input comes back sorted; dup same-type collapses; dup different-type kept.
- **REQ-MAP-03 — Spawn lead.** An event at beat `n` must reach the action point at `beatTime(n)`, so it spawns at `spawnTime = beatTime(n) − leadTime` (leadTime derived from scroll speed + spawn distance).
  *Accept:* leadTime=2.0s, bpm=120, event at beat 8 (=4.0s) → spawnTime=2.0s; events with spawnTime<0 are pre-spawned at t=0.

### 5.4 Run lifecycle — `run.ts`

- **REQ-RUN-01 — States.** `Loading → Countdown → Playing → Results`, transitions one-way except Results→Loading (retry).
  *Accept:* illegal transitions rejected.
- **REQ-RUN-02 — Pause/resume sync.** On pause, store the audio-clock offset; on resume, the event cursor and audio clock advance from the same offset with no drift.
  *Accept:* pause at t=10.0s then resume — next judged event uses the same beat grid; no events skipped or double-fired.
- **REQ-RUN-03 — End condition.** Run ends when the audio track ends. No health/death in MVP.
  *Accept:* run reaches Results exactly once, at track end.

---

## 6. Beat-map format (concrete)

```json
{
  "track": "sweetpapa_groove_01.mp3",
  "bpm": 92,
  "offset": 0.30,
  "events": [
    { "beat": 4,  "type": "GAP" },
    { "beat": 6,  "type": "NOTE" },
    { "beat": 8,  "type": "BAR" },
    { "beat": 10, "type": "NOTE" },
    { "beat": 12, "type": "GAP" }
  ]
}
```

MVP authoring is by hand. A later tool can generate maps from BPM + onset detection — out of scope for v1.

## 7. Tech approach

- **Phaser 4 + TypeScript**, Vite dev server. (Phaser 4 shipped April 2026 and is current; it's a 2D renderer, which is all the 2.5D look needs.)
- **2.5D look, pure Phaser:** parallax background layers, scale-for-depth on the hero/obstacles, additive-blend neon glow, beat-driven camera shake + bloom. No Enable3D/Three.js for MVP — revisit only if you want true 3D later (that's where the Phaser-3/Enable3D-vs-Three.js decision returns).
- **Audio:** load the track via Web Audio; **drive all timing off `AudioContext.currentTime`.** Treat Phaser's render loop as *display only*. This is the single most important technical decision and the most valuable mutation-test target.
- **Architecture rule (and skill enabler):** keep `timing.ts`, `scoring.ts`, `beatmap.ts`, `run.ts` as **pure modules with zero Phaser imports.** Phaser scenes call into them. This is what lets the suite test the whole deterministic core headless, with an injected clock — exactly what the SDLC skill's tests-first loop needs.
- **Tests:** Vitest for the pure modules.

Suggested structure:
```
in-the-pocket/
├── src/
│   ├── core/         # pure, framework-free, fully unit-tested
│   │   ├── timing.ts
│   │   ├── scoring.ts
│   │   ├── beatmap.ts
│   │   └── run.ts
│   ├── scenes/       # Phaser: Boot, Track, Play, Results
│   ├── audio/        # AudioContext clock + loader
│   └── main.ts
├── assets/{tracks,sprites,sfx}/
├── maps/             # *.beatmap.json
└── tests/            # vitest, targets src/core
```

## 8. Juice / feel (polish, non-blocking)

On-beat world pulse; particle burst + screen flash on Perfect; combo-tier color shifts; camera shake scaled to hit strength; a subtle ghost-trail on the hero; results screen that replays your best run's score climbing. None of this gates the core; all of it sells the groove.

## 9. Build milestones (minimum viable first)

1. **Core, headless.** `timing` + `scoring` + `beatmap` + `run` as pure modules, fully tested. No graphics. *This alone is a complete skill-test target.*
2. **Playable shell.** Phaser Play scene: auto-scroll, one track, hand-authored map, the three actions, judgment wired to the audio clock, on-screen score/combo.
3. **The three obstacle types** with real art + the stumble feedback.
4. **Results + grade + retry.**
5. **Juice pass.**
6. **Track-select** + drop-in support for multiple of your songs.

Ship 1–2 before touching 5. Each milestone is independently playable/testable.

## 10. Why it's the right skill test

The deterministic core is small, pure, and crisply spec'd — every REQ-ID above is a testable contract with exact boundaries. The Judge can write airtight window/scoring/combo tests from this doc *before* any code exists; mutation testing will hunt the off-by-one and boundary bugs that rhythm logic is famous for; and the Phaser scene code stays a thin shell over a tested core. The game and the skill validate each other.

---

*Next: when the skill is built, this file is its first `SPEC.md`. Feed it in at Phase 0 and let the loop run.*
