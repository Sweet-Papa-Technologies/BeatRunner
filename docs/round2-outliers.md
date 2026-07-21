# Round 2 — outlier forensics (REQ-R2-OUT-01 / OUT-02)

Two timing outliers and three dynamics outliers, diagnosed. Sources: Round 1's
`tools/chartbench/out/timing_probe.json` (which already separates *offset* error
from *jitter*), plus fresh offline analysis of all 13 benchmark tracks.

The decisive measurement in both timing cases is one Round 1 already had and did
not act on: **signed median vs residual**. A chart that is uniformly N ms late is
*offset* and one number fixes it. A chart with N ms of scatter is genuinely badly
timed and no single number helps.

---

## REQ-R2-OUT-01a — The Pools: **fixed** (offset bug)

| measurement | value | reading |
|---|---:|---|
| raw abs median error | 19.1 ms | the Round 1 headline |
| **signed** median | **−18.1 ms** | notes land *early*, consistently |
| residual after one global shift | 10.2 ms | fleet-normal |
| residual IQR | 12.0 ms | tight — not jitter |
| drift | −14.3 ms/min | modest, not the cause |
| onset snap error, median | **+25.3 ms** | onsets sit *late* of the grid |
| tempo confidence | 0.92 | the strongest in the fleet |

**Diagnosis: a wrong offset, and it is our bug.** Every indicator agrees. The
tempo is not in doubt (0.92 alignment score, by far the fleet's most confident
fit), there is no meaningful drift, and the residual is ordinary once one global
shift is removed. The chart is not badly timed — it is *displaced*.

**Root cause, precisely.** `dsp.fit_offset` maximizes summed onset-envelope
energy at grid times, sampling the envelope by frame index:
`np.round(grid * FRAME_RATE)`. With `HOP_LENGTH=256` at `SR=22050` a frame is
**11.6 ms**, so sweeping the offset at `OFFSET_STEP_MS=1.0` is aliased to frame
granularity — the estimator *cannot* resolve sub-frame beat phase, however fine
the sweep. On most tracks the leftover error is small and unbiased. On The Pools,
whose envelope peaks are broad, it lands consistently to one side: +25.3 ms.

Meanwhile `build_onsets` runs `_parabolic_refine` and resolves each onset to
**sub-frame** precision. The onsets were always a better clock than the estimator
that placed the grid — the information to fix this was already in the analysis,
unused.

**Fix (`dsp.refine_offset_from_onsets`).** A second-pass offset fit: after
building onsets, take the median snap error and, if it exceeds
`config.OFFSET_SNAP_CORRECTION_MIN_MS` (5 ms), shift the grid by it and rebuild
everything downstream. Below the threshold nothing moves — that median is noise,
and re-phasing on noise would jitter tracks that were already right.

**Effect, measured over all 13 benchmark tracks:**

| track | correction | onset snap median | within ±10 ms |
|---|---:|---|---|
| **the_pools** | **+25.3 ms** | 27.3 → **13.3 ms** | 15.6% → **37.2%** |
| song | +13.5 ms | 14.1 → 3.9 ms | 24.9% → **85.8%** |
| lucky_lucky | +6.7 ms | 10.2 → 6.9 ms | 49.2% → **70.8%** |
| the other 10 | none | unchanged | unchanged |

Three tracks corrected, ten untouched — the threshold does its job. `token_economy`
is correctly left alone (see below), which is a useful negative control: the fix
only moves tracks that have the defect.

**Status: pipeline bug, fixed.** OUT-01's bar is ≤12 ms on the harness. This
should clear it — the residual was already 10.2 ms and the residual is what
remains once the offset is right — but **that claim needs the harness re-run to
confirm, and I have not run it** (see "What is not verified" below).

---

## REQ-R2-OUT-01b — Token Economy: **documented, not fixed** (the audio)

| measurement | value | reading |
|---|---:|---|
| raw abs median error | 16.5 ms | the Round 1 headline |
| **signed** median | **+0.5 ms** | no displacement at all |
| residual after one global shift | 16.3 ms | **unchanged** — nothing to remove |
| residual IQR | 26.3 ms | wide: real scatter |
| drift | −0.3 ms/min | none |
| onset snap error, median | +0.5 ms | grid is centred correctly |
| onset snap error, **abs** median | **20.9 ms** | but individual onsets scatter |
| onsets within ±10 ms of grid | 23.1% | worst in the fleet |
| tempo confidence | **0.20** | weakest in the fleet |
| sections detected | 12 | most in the fleet |

**Diagnosis: the audio, not the pipeline.** This is the exact opposite profile to
The Pools and the offset fix correctly does nothing here. The grid is centred
(signed median +0.5 ms) and stable (no drift); the error is *dispersion*. Only
23% of onsets land within 10 ms of any grid line while their median is dead
centre — the transients genuinely do not sit on a constant-tempo grid.

Two corroborating signals. First, tempo salience is the fleet's weakest: the
chosen 172.27 BPM scores **0.20**, against 129.20 at 0.17 and 193.80 at 0.20 —
essentially a three-way tie, where The Pools' winner scored 0.92. Second, the
track fragments into 12 sections, the most of any benchmark track. Both point at
a rhythmically loose or non-quantized performance rather than a mis-fit.

At 173.5 BPM a 16th note is 86 ms and a 32nd is 43 ms, so a 21 ms scatter is a
genuine sub-32nd-note ambiguity in the source. **No single offset, and no single
BPM, can fix that** — the only thing that would is a variable `#BPMS` map, and
with drift measured at −0.3 ms/min there is no drift for a tempo map to track.
This is a track where 1,190 onsets over 122 s (≈9.8/s) means the notion of "the"
grid position for a transient is itself fuzzy.

**Status: documented as an audio property. No fix attempted, because there is no
pipeline defect to fix.** Chasing it would mean tuning the tempo estimator
against one track, which would risk the twelve that are already correct.

---

## REQ-R2-OUT-02 — the three dynamics outliers

Measured on the deterministic path over all 13 tracks, mean ρ across all five
difficulties, before vs after the shipped Round 2 density work:

| track | R1 ρ (reported) | before | after | Δ | offset fix |
|---|---:|---:|---:|---:|---:|
| **Room Smells Like Poo** | 0.19 | +0.209 | **+0.580** | +0.371 | — |
| **Bttr** | 0.14 | +0.200 | **+0.563** | +0.363 | — |
| **The Pools** | −0.15 | +0.195 | **+0.358** | +0.163 | +25.3 ms |

All three outliers are lifted, and every one of the other ten tracks improves too
(fleet mean ρ **0.266 → 0.501**; full table in `docs/round1-vs-round2.md`).

**Room Smells Like Poo — solved by the plan, nothing track-specific needed.**
ρ 0.209 → 0.580. Its energy CV is 0.152 — low, but real — across 6 sections. The
contrast was always in the music; the chart simply wasn't following it. This is
the cleanest confirmation that Round 1's diagnosis was right: dynamics was a
prompt instruction nothing enforced, and enforcing it was sufficient.

**Bttr — also solved, and it corrects a Round 1 assumption.** ρ 0.200 → 0.563.
I expected this one to be limited by onset supply (794 onsets over 87 s, with
tier filtering thinning the pool further) and to improve only partially. It did
not — the per-bar fill found enough real transients. Worth recording that the
inventory-starvation worry did not materialise here.

**The Pools — the two defects were interacting, and the timing fix moved the
dynamics number on its own.** This is the important finding of the section.
Round 1 measured ρ = **−0.15**, the only negative in the fleet, and treated it as
a dynamics pathology. It was substantially a *timing* artifact: the grid was
25.3 ms out of phase, so bar boundaries were misplaced, and the metric was
comparing note counts bucketed by a bad grid against an energy curve bucketed by
the same bad grid. Correcting the offset alone moves the baseline from −0.148 to
**+0.195** — a +0.34 swing with no dynamics work at all. The density plan then
takes it to +0.358 (its `challenge` chart is one of the few where the SACRED-03
flow guard deliberately forgoes a density gain).

The Pools remains the fleet's weakest track for dynamics, and its energy CV
(0.224) is mid-range, so there is genuine residual difficulty here. But **the
Round 1 −0.15 should not be used as a baseline for anything** — it was measuring
a mis-aligned chart against a mis-aligned energy curve. Any future work on this
track should start from +0.195.

---

## What is not verified

Everything above is measured, but measured **offline on the deterministic path**,
using the same `adapters/stepmania/qa.chart_metrics` that `chartbench/score.py`
calls and the same DSP analyses. What has **not** run:

- the full 13-song harness through the **Gemini** designer path (needs Vertex
  spend, which I have not incurred);
- `score.py` over a freshly generated Round 2 STEPFORGE pack;
- therefore SACRED-02's ≤9 ms / ≥80% Fantastic thresholds are **unconfirmed**.

SACRED-04 *is* confirmed empirically: re-scoring the untouched DDC pack against
the extended analysis gives **max |Δρ| = 0.000000** across all 65 DDC charts, and
identical `flow_cost_max` — the new `density_plan` field changed no existing
value. That check is worth repeating for STEPFORGE once the harness runs.
