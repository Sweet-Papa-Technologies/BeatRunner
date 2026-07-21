# FoFo Test Compare 2 — five-way head to head

Songs compared (3): Robo Fast Food, Stay Awake For Me, The Pools

All charts scored by the same `chartbench/score.py` over identical audio and identical DSP analysis. Only the chart differs.

> **Excluded from every column:** Lucky Lucky — not every generator has it, and averaging over different song sets is not a comparison.

| metric | AUTOSTEPPER | DDC | STEPFORGE-R1 | STEPFORGE-R2 | STEPFORGE-R3 |
|---|---:|---:|---:|---:|---:|
| **— is it DANCEABLE? (pad UX) —** |  |  |  |  |  |
| flow gate pass | 0% | 7% | 93% | 80% | 80% |
| flow_cost_max | 26.660 | 25.783 | 11.537 | 14.707 | 10.110 |
| flow_cost_mean | 9.343 | 8.231 | 7.007 | 6.804 | 7.275 |
| **— does it FOLLOW the song? —** |  |  |  |  |  |
| density rho | 0.093 | 0.347 | 0.201 | 0.642 | 0.603 |
| density gate pass | 0% | 33% | 20% | 73% | 67% |
| **— difficulty / vocabulary —** |  |  |  |  |  |
| notes per chart | 266 | 230 | 263 | 417 | 320 |
| jump_share | 0.032 | 0.078 | 0.066 | 0.114 | 0.048 |
| hold_share | 0.239 | 0.043 | 0.076 | 0.083 | 0.102 |
| panel_balance gate | 100% | 93% | 100% | 100% | 100% |
| **— rigged, do NOT cite (see round1.html) —** |  |  |  |  |  |
| onset_alignment ⚠ | 0.234 | 0.101 | 0.895 | 0.870 | 0.912 |

## Notes per chart, by difficulty

| difficulty | AUTOSTEPPER | DDC | STEPFORGE-R1 | STEPFORGE-R2 | STEPFORGE-R3 |
|---|---:|---:|---:|---:|---:|
| beginner | 136 | 56 | 121 | 153 | 144 |
| easy | 166 | 112 | 154 | 224 | 185 |
| medium | 226 | 165 | 228 | 300 | 293 |
| hard | 254 | 294 | 268 | 479 | 427 |
| challenge | 364 | 427 | 384 | 620 | 554 |
