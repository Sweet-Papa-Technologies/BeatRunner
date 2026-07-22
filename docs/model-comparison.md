# Designer-model comparison — lucky_lucky

Same pipeline, same audio, same DSP analysis, same scorer. Only the designer/critic MODEL differs. Cost is measured from the per-call ledger, not estimated from a price list.

Rates as of 2026-07-21 (all three verified against the Vertex pricing page).

| | gemini-3.5-flash | gemini-3.6-flash | gemini-3.5-flash-lite |
|---|---:|---:|---:|
| **— cost —** |  |  |  |
| total $ (5 charts) | $2.0473 | $1.2671 | $0.2818 |
| $ per chart | $0.4095 | $0.2534 | $0.0564 |
| model calls | 16 | 14 | 11 |
| thinking tokens | 149,818 | 97,116 | 66,391 |
| wall clock (min) | 12.6 | 6.4 | 3.4 |
| **— is it DANCEABLE? —** |  |  |  |
| flow gate pass | 80% | 80% | 80% |
| flow_cost_max | 14.320 | 9.350 | 15.830 |
| **— does it FOLLOW the song? —** |  |  |  |
| density rho | 0.781 | 0.796 | 0.766 |
| density gate pass | 100% | 100% | 100% |
| **— difficulty —** |  |  |  |
| notes per chart | 136 | 125 | 112 |
| jump_share | 0.027 | 0.046 | 0.267 |

## Cost relative to the incumbent (gemini-3.5-flash)

- **gemini-3.6-flash**: -38% cost ($1.2671 vs $2.0473), rho +0.796 vs +0.781, flow gate 80% vs 80%
- **gemini-3.5-flash-lite**: -86% cost ($0.2818 vs $2.0473), rho +0.766 vs +0.781, flow gate 80% vs 80%
