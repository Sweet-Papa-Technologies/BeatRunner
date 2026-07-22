# FoFo Test Compare 2 — five-way head to head

Songs compared (4): Lucky Lucky, Robo Fast Food, Stay Awake For Me, The Pools

All charts scored by the same `chartbench/score.py` over identical audio and identical DSP analysis. Only the chart differs.

| metric | AUTOSTEPPER | DDC | STEPFORGE-R1 | STEPFORGE-R2 | STEPFORGE-R3 |
|---|---:|---:|---:|---:|---:|
| **— is it DANCEABLE? (pad UX) —** |  |  |  |  |  |
| flow gate pass | 0% | 10% | 95% | 75% | 80% |
| flow_cost_max | 26.360 | 26.652 | 10.783 | 15.195 | 11.162 |
| flow_cost_mean | 9.236 | 8.330 | 6.873 | 6.859 | 7.369 |
| **— does it FOLLOW the song? —** |  |  |  |  |  |
| density rho | 0.106 | 0.375 | 0.279 | 0.662 | 0.647 |
| density gate pass | 5% | 25% | 30% | 80% | 75% |
| **— difficulty / vocabulary —** |  |  |  |  |  |
| notes per chart | 229 | 211 | 231 | 355 | 274 |
| jump_share | 0.039 | 0.083 | 0.074 | 0.112 | 0.043 |
| hold_share | 0.191 | 0.051 | 0.079 | 0.088 | 0.104 |
| panel_balance gate | 100% | 95% | 100% | 100% | 100% |
| **— rigged, do NOT cite (see round1.html) —** |  |  |  |  |  |
| onset_alignment ⚠ | 0.197 | 0.098 | 0.921 | 0.890 | 0.916 |

## Notes per chart, by difficulty

| difficulty | AUTOSTEPPER | DDC | STEPFORGE-R1 | STEPFORGE-R2 | STEPFORGE-R3 |
|---|---:|---:|---:|---:|---:|
| beginner | 136 | 56 | 121 | 153 | 122 |
| easy | 166 | 112 | 154 | 224 | 158 |
| medium | 226 | 165 | 228 | 300 | 248 |
| hard | 254 | 294 | 268 | 479 | 367 |
| challenge | 364 | 427 | 384 | 620 | 476 |
