# SweetPapa's Founders Mix #2 — benchmark

Scored by `chartbench/score.py`, the same scorer used for every previous round and both competitors.

> **Read this before quoting the table.** The competitor and R1/R2/R3 rows were scored on *different songs* (the 13-song benchmark and the 4-song compare pack). Founders Mix #2 is 9 new masters. This shows how the new pack scores beside how those scored — it is not a song-matched head to head. For that, see `docs/compare2-five-way.md`.

| generator | songs | charts | flow gate | flow_max | rho | density gate | notes | jump |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Founders Mix #2 (R3, 3.6-flash) | 9 new masters | 45 | 89% | 10.99 | +0.089 | 11% | 245 | 0.061 |
| STEPFORGE-R3 (compare pack) | 4 songs | 20 | 80% | 11.16 | +0.647 | 75% | 274 | 0.043 |
| STEPFORGE-R2 (compare pack) | 4 songs | 20 | 75% | 15.19 | +0.662 | 80% | 355 | 0.112 |
| STEPFORGE-R1 (compare pack) | 4 songs | 20 | 95% | 10.78 | +0.279 | 30% | 231 | 0.074 |
| DDC (2017, learned) | 4 songs | 20 | 10% | 26.65 | +0.375 | 25% | 211 | 0.083 |
| AutoStepper (2018, DSP) | 4 songs | 20 | 0% | 26.36 | +0.106 | 5% | 229 | 0.039 |

## Where the new pack lands

- vs **STEPFORGE-R3 (compare pack)**: flow gate 89% vs 80%, rho +0.089 vs +0.647, notes 245 vs 274
- vs **STEPFORGE-R2 (compare pack)**: flow gate 89% vs 75%, rho +0.089 vs +0.662, notes 245 vs 355
- vs **STEPFORGE-R1 (compare pack)**: flow gate 89% vs 95%, rho +0.089 vs +0.279, notes 245 vs 231
- vs **DDC (2017, learned)**: flow gate 89% vs 10%, rho +0.089 vs +0.375, notes 245 vs 211
- vs **AutoStepper (2018, DSP)**: flow gate 89% vs 0%, rho +0.089 vs +0.106, notes 245 vs 229

## What it cost (measured, from the per-call ledger)

- **$18.02** total across 9 songs / 45 charts (131 model calls)
- **$2.00/song**, **$0.40/chart**
- model(s) actually used: gemini-3.6-flash
