# The $80 autopsy

**Question:** 30 songs cost ~$80 (~$2.67/song, ~$0.53/chart at 5 difficulties).
Where did the money go?

**Status of this document.** A **live instrumented run has now been performed** —
`the_pools`, Gemini designer path, 18 model calls, $4.28 — so most of what draft 1
labelled "pending ledger" is now measured. Where a modelled estimate and a measured
value disagree, the measured value wins and the disagreement is called out rather
than quietly overwritten (see the Headline). Nothing here is
estimated-and-presented-as-measured.

The instrumentation:
`tools/beatforge/ledger.py`, `tools/beatforge/pricing.py`,
`tools/beatforge/costreport.py`, `beatforge cost-report`. Running one song end to end
now writes `build/cost/<song>/cost_ledger.jsonl` with one line per model call.

**Method for the measured numbers.** All 13 benchmark tracks were re-analyzed offline
(`analyze_track`, local DSP backend). Onset counts reproduce Round 1 exactly
(444–1601, matching `FOREMAN-ROUND-1.md`), so these are the same analyses the Round 1
charts were designed from. Designer prompts were then built with the real
`adapters/stepmania/design.designer_prompt()` for all 5 difficulties × 13 songs and
measured. Token counts from prompt bytes use 4 bytes/token; audio tokens use Gemini's
32 tokens/second of audio. Dollars use `pricing.py` @ `pricing_as_of 2026-07-21`.

> **Rates are now VERIFIED** (2026-07-21, against
> `cloud.google.com/vertex-ai/generative-ai/pricing`). The first draft of this
> report used placeholder rates carried over from Gemini 2.5 Flash, and **they were
> badly wrong** — see "The price table was wrong" below. Everything here has been
> recomputed. `pricing.py` now ships `verified=True` for `gemini-3.5-flash`.

---

## The price table was wrong, and that is half the answer

The verified `gemini-3.5-flash` rates (global endpoint — which is what
`vertex.py::_endpoint` routes every `gemini-3*` model to):

| component | placeholder used in draft 1 | **verified** | error |
|---|---:|---:|---:|
| text input | $0.30 /M | **$1.50 /M** | **5.0× too low** |
| audio input | $1.00 /M | **$1.50 /M** | 1.5× too low |
| output *(incl. reasoning)* | $2.50 /M | **$9.00 /M** | **3.6× too low** |
| cached input | $0.075 /M | **$0.15 /M** | 2× too low |

Two of these change conclusions, not just magnitudes:

1. **Audio is not priced at a premium on this model.** 3.5 Flash bills
   "Text/Image/Video/**Audio** input" as a single $1.50 line. The draft assumed
   audio cost 3.3× text and still found it immaterial; it is actually **1.0×
   text**, so audio is even less of a driver than already concluded. (Note this is
   model-specific: `gemini-3-flash-preview` *does* charge 2× for audio.)
2. **Reasoning tokens bill at the output rate — $9.00/M, six times the input
   rate.** A thinking token is the single most expensive token this pipeline can
   emit, and `thinking_level="high"` is set on every call with no cap.

---

## Headline — now from a REAL instrumented run

`the_pools` was run end to end through the Gemini designer path with the ledger
live: **18 model calls, 21.8 minutes, $4.28**, covering beginner/easy/medium/hard
plus a partial challenge (the process was killed during challenge, so the true
full-song figure is somewhat higher). Every number in this section is measured,
not modelled.

**Where the money went:**

| component | cost | share |
|---|---:|---:|
| **thinking (reasoning) tokens** | $1.9584 | **45.8%** |
| text input | $1.3403 | 31.3% |
| visible output | $0.8906 | 20.8% |
| **audio input** | $0.0877 | **2.1%** |
| cached input | $0.0000 | 0.0% |

| stage | calls | cost | share |
|---|---:|---:|---:|
| designer | 5 | $1.8478 | 43.2% |
| **re-prompt (gate/intent retries)** | 4 | $1.4698 | **34.4%** |
| re-prompt (density, new in R2) | 1 | $0.6141 | 14.4% |
| critic | 8 | $0.3453 | 8.1% |

**Thinking tokens per call, measured:** designer mean **18,780** (range
11,953–40,130), re-prompt mean 16,974, critic mean 3,092.

**My prediction was 14,000–25,000 per designer call. The measured mean is 18,780 —
inside the band.** Hypothesis #5 is confirmed on real data, not arithmetic:
reasoning is the single largest component of the bill at 45.8%.

**Two things the modelling got wrong, stated plainly:**

1. **I under-modelled text input by ~5×.** My estimate was ~158,000 text tokens
   per song; the real run consumed **784,659**. The cause is retries — my model
   assumed 5 designer + 5 critic calls with no re-prompts, and the real run made
   **18 calls**, each re-sending the full uncached inventory.
2. **Re-prompts are a top-tier driver, which I had ranked as a deferred TODO.**
   The two re-prompt paths together are **48.8% of spend** — more than the initial
   designer calls. I listed "cap the critic-revision loop" as a *deferred* item
   pending the call distribution. The distribution is now in, and it promotes that
   item to the top tier.

What held up: audio really is negligible (**2.1%**, even lower than the 9.7% I
projected), caching really is absent (`cached_tokens: 0` on all 18 calls), and the
model string really was `gemini-3.5-flash` on all 18 — no silent swap.

---

## 1. Is audio attached to designer and/or critic calls, and what fraction of input tokens is audio?

**Attachment: CONFIRMED (measured, from code).** Audio is attached to *every* designer
call and *every* critic call, on both the StepMania adapter and the core pipeline:

- `adapters/stepmania/design.py::design_intent` → `client.generate_json(prompt, audio_path=audio)`
- `adapters/stepmania/design.py::critic_review` → `client.generate_json(prompt, audio_path=audio)`
- `design.py::design_chart` and `design.py::critic_pass` — same.

Additionally, `vertex.py::generate_json` re-sends **the same audio part** on its
JSON-parse retry, so a malformed reply doubles that call's audio cost.

**Dominance: FALSIFIED (measured).** The brief's premise — "a ~3-min track attached to
every call across 5 difficulties × critic × retries would dominate everything" —
rests on a track length the benchmark does not have. The 13 benchmark tracks average
**92.8 seconds**, not three minutes:

| | value |
|---|---:|
| mean track duration | 92.8 s |
| mean audio tokens per attachment (@32 tok/s) | 2,971 |
| attachments per song (5 designer + 5 critic) | 10 |
| audio tokens per song | 29,707 |
| text tokens per song | 158,030 |
| **audio share of input tokens** | **15.8%** |
| audio cost per song @ verified $1.50/M | **$0.045** |
| **audio share of the visible-token bill** | **9.7%** |

Note the verified rate makes this case *stronger*, not weaker: 3.5 Flash charges
the same $1.50 for audio as for text, so audio's share of the bill (9.7%) is
actually **lower** than its share of input tokens (15.8%) — because output tokens,
which carry no audio, are billed at $9.00.

**MEASURED on the live run: audio is 6.2% of input tokens and $0.0877 — 2.1% of
spend.** Both projections above were, if anything, too generous to this
hypothesis; retries inflate text far faster than they inflate audio, so audio's
share fell further as call count rose.

**Verdict: audio is attached everywhere (a real finding), but at 2.1% of measured
spend it is not a cost driver.** Removing it would save one fiftieth of the bill
and would cost the critic its entire reason for existing (Author≠Judge judging musicality *by ear*). **Do not remove the audio
attachment.** This hypothesis is closed.

---

## 2. How large is the serialized onset inventory per call, and is it resent verbatim for every difficulty and every critic pass instead of cached?

**CONFIRMED, and it is the largest *visible* line item.**

The onset inventory is **93–97% of every designer prompt.** Measured on `the_pools`
(1,337 onsets, the second-densest track):

| difficulty | prompt | ≈tokens | onsets offered | inventory bytes | inventory share |
|---|---:|---:|---:|---:|---:|
| beginner | 57,442 B | 14,360 | 371 | 53,416 B | 93% |
| easy | 99,878 B | 24,970 | 666 | 95,860 B | 96% |
| medium | 99,880 B | 24,970 | 666 | 95,860 B | 96% |
| hard | 123,952 B | 30,988 | 832 | 119,922 B | 97% |
| challenge | 123,963 B | 30,991 | 832 | 119,922 B | 97% |

For scale, the entire per-bar energy curve — the thing that is supposed to drive
dynamics — is **541 bytes**, 0.4% of the prompt. We are spending 97% of the designer's
context on the note menu and 0.4% on the musical shape. That is worth noting for
Workstream B independently of cost.

**Caching: none, anywhere.** `vertex.py` sends `contents` inline on every call with no
`cachedContent` reference and no `CachedContent` creation path. The inventory is
re-serialized and re-sent verbatim for each of the 5 difficulties, on every retry, and
the chart is re-serialized for each critic pass.

**Free money, measured.** Look at the table again: `easy` and `medium` prompts are
byte-identical (99,878 vs 99,880 — differing only in the difficulty word), and so are
`hard` and `challenge`. Both pairs share a `finest_subdiv`, so `_compact_analysis`
filters to the *same* onset set. Across the benchmark:

| | tokens |
|---|---:|
| designer inventory tokens, 13 songs × 5 difficulties | 1,457,497 |
| after de-duplicating byte-identical inventories | 992,922 |
| **redundant** | **464,575 (32%)** |

**Verdict: CONFIRMED — and the verified rates promote this from "embarrassing" to
"the best structural fix available".**

Two numbers changed the priority here:

- **Cached input is $0.15/M against $1.50/M for fresh input — a 10× discount.**
  The per-song analysis block is ~90% of designer text, ≈142,000 tokens/song.
  Context-caching it across the 5 difficulties and the critic passes would save
  ≈**$0.192/song — 42% of the entire visible-token bill.**
- The pure de-duplication win (easy≡medium, hard≡challenge) is ~464,600 tokens
  across the benchmark, now worth ~$0.70 rather than the ~$0.14 the wrong table
  implied.

This is no longer a tidy-up. It is the largest fix that does not require touching
generation config.

---

## 3. How many model calls per chart, actually? (Distribution, not average.)

**Bounds: measured from code. Distribution: PENDING LEDGER.**

Tracing `adapters/stepmania/adapter.py`:

| path | calls |
|---|---:|
| designer, first attempt | 1 |
| designer re-prompt on `IntentError` | up to +2 (`attempts = 3`) |
| critic (Author≠Judge) | +1 |
| critic revision when score < 7 → full re-design | up to +3 |
| critic re-score of the revision | +1 |
| **minimum per chart** | **2** |
| **maximum per chart** | **8** |

And a multiplier on top: `vertex.py::generate_json` retries once on a JSON parse
failure, re-sending prompt *and* audio. Any of those 8 can become 2. **Theoretical
worst case per chart: 16 calls.**

**MEASURED on the real `the_pools` run — 18 calls across 5 charts:**

| difficulty | model calls |
|---|---:|
| beginner | 2 |
| easy | 4 |
| medium | 5 |
| hard | 4 |
| challenge | 3 *(incomplete — process killed mid-chart)* |

min 2 / **median 4** / mean 3.6 / max 5.

**Verdict: CONFIRMED, and materially worse than a naive read.** The happy path is
2 calls; the observed median is **4**. Only one chart of five ran clean. Retries
are not an edge case here — they are the normal case, and they carry **48.8% of
the bill** because every retry re-sends the entire uncached inventory.

This reverses my own draft-1 ranking. I wrote "call count multiplies whatever the
per-call cost is but cannot by itself reach $2.67" and deferred the fix. That was
wrong: at 4 calls per chart with a 100k-token prompt each, call count *is* a
first-order driver.

---

## 4. Is any stage silently using a model other than the configured Gemini 3.5 Flash?

**RESOLVED — `gemini-3.5-flash` on all 18 calls of the real run. No silent swap.**

The census below is what the ledger recorded, not what config claims.

What the code says: `config.GEMINI_MODEL = "gemini-3.5-flash"`, and no designer or
critic call site passes a `model=` override. `llm.make_llm_client()` returns a
`VertexClient` unless `BEATFORGE_LLM_BACKEND=openai`. On that reading, everything is
3.5 Flash.

**That reading is worth exactly nothing here**, because the governance incident this
question exists for was precisely a case of config not matching reality. So:
`ledger.record_model_call` records the model string **passed to the request builder**,
not `config.GEMINI_MODEL`, and `cost-report` renders a `models_seen` census plus an
explicit `unexpected_models` warning when anything other than the configured model
appears. `test_cost.py::test_model_string_recorded_is_the_one_sent_not_the_config`
locks that behaviour in.

**Verdict: CLEAN.** `models_seen` = `{gemini-3.5-flash: 18}`, `unexpected_models`
empty. The mechanism that would have caught a swap is in place and was exercised;
it simply found nothing to report. That is the correct outcome for this question,
and unlike draft 1 it is now a measurement rather than a reading of config.

---

## 5. Are thinking/reasoning tokens enabled anywhere, and what do they cost?

**Enabled: CONFIRMED (measured, from code). Cost: THE PRIME SUSPECT.**

`config.THINKING_LEVEL = "high"`, and `vertex.py::_thinking_config` applies it to
**every single call** — designer, critic, retries, all of them:

- Gemini 3.x → `thinkingConfig.thinkingLevel = "high"`
- Gemini 2.5 → `thinkingConfig.thinkingBudget = -1` (*unbounded*: "think as much as
  you need")

Nothing anywhere lowers it for the critic, which is a scoring task, or for retries.
There is no budget cap and no per-stage override.

**Why this is the prime suspect.** Reasoning tokens bill at the **output** rate —
**$9.00/M verified, six times the input rate** — and are invisible in the prompt.
They are the only component of the bill the prompt-side arithmetic cannot see.
Closing the gap requires:

| to reach the observed $2.67/song | thinking tokens |
|---|---:|
| visible-token cost at verified rates | $0.457 |
| unexplained spend | $2.213 |
| ÷ $9.00/M output rate | **245,900 tokens/song** |
| across 10 calls | **24,600 per call** |
| across ~18 calls (with retries) | **13,700 per call** |

**This is the finding that verifying the price table bought.** Under the draft's
wrong rates the residual demanded 57,000–102,000 reasoning tokens *per call* —
possible, but strained. At verified rates it demands **~14,000–25,000 per call**,
which is an unremarkable `thinkingLevel: high` load for a task that hands the model
a 25,000–31,000-token onset menu and asks it to select and structure a chart.

The draft listed two competing explanations — "thinking is the bill" vs "the price
table is wrong" — and could not separate them. **Both were true, and together they
close the gap without strain:** the table was 3.6× low on output, and unbounded
reasoning supplies the rest at a believable per-call volume.

**Verdict: CONFIRMED as the dominant driver, pending one ledger run to read the
actual `thoughtsTokenCount`.** That field is already parsed by
`ledger.usage_from_vertex` and rendered as a per-stage `thinking` column, so a
single instrumented song either confirms ~14–25k/call or falsifies it outright.

---

## 6. What share is Colab/GPU vs Vertex?

**PENDING LEDGER, but bounded (measured, from code).**

Analysis runs **once per song**, not per chart, and is cached by
`(audio_sha256, BEAT_ANALYSIS_VERSION)` — a re-run with an unchanged cache key
provisions nothing. So GPU spend is at most one Demucs/madmom job per song per
analysis-schema change, against ten model calls per song.

`ledger.record_compute` now logs every analysis with `gpu`, `gpu_minutes`,
`cache_hit`, and `minutes_estimated` (set when the backend cannot self-report and we
fall back to wall clock). Cache hits are logged as explicit **$0** entries, so
"re-runs cost nothing for analysis" becomes provable rather than merely claimed
(`test_analyze_track_ledgers_a_cache_hit`).

**Partial real-run evidence, from this session.** Re-analyzing the 13 benchmark
tracks produced **303 real compute ledger entries** — **265 cache hits and 38 fresh
analyses** — across 13 songs, every one distinguishable in the report. That
confirms the *mechanism* end to end on real runs rather than only in tests, and it
confirms the caching claim: the overwhelming majority of analysis calls in normal
work cost nothing. It does **not** answer the dollar question, because these ran on
the local CPU backend (`gpu=none`, rate $0) whereas the $80 figure came from Colab.

**MEASURED on the real run: compute $0.0000 vs Vertex $4.2770 — a 0.0% compute
share.** The analysis was a cache hit (the track had already been analyzed), which
is itself the point: on any re-run, analysis is free and 100% of the money is
Vertex.

**Verdict: for the local/cached path, Vertex is 100% of spend — Colab is not the
problem.** A cold Colab-backed analysis would add GPU minutes once per song
against ~$4 of model calls, so the share would still be small, but that specific
number remains unmeasured. Per the brief's escalation rule, **if
that run shows Demucs/Colab dominating rather than Vertex, that is an architecture
conversation and I will escalate rather than patch.**

---

## The top 2 cost drivers

All three now rest on measured data from the live run, not arithmetic.

1. **Unbounded reasoning tokens at `thinking_level="high"` on every call**
   (hypothesis #5) — **45.8% of measured spend**, 18,780 tokens on the mean
   designer call, billed at the $9.00/M output rate. Nothing in the config caps
   it, and the critic — a *scoring* task — is thinking 3,092 tokens a call.
2. **The re-prompt loops** (hypothesis #3) — **48.8% of measured spend across 5
   calls**, against a median of 4 model calls per chart where the happy path is 2.
   Each retry re-sends the entire uncached ~100k-token inventory. **I had this as
   a deferred TODO in draft 1 and was wrong to.**
3. **The uncached onset inventory** (hypothesis #2) — 93–97% of every designer
   prompt, `cached_tokens: 0` on all 18 calls. At the verified 10× cache discount
   ($1.50 → $0.15/M) this is what makes #2 compound with #3: caching would blunt
   the cost of every retry as well as every first attempt.

Note #2 and #3 multiply each other. The expensive thing is not "a retry" or "a
big prompt" — it is *a big prompt re-sent uncached on every retry*.

Audio attachment (#1) is real but immaterial at **2.1% of measured spend**, and
removing it would break the critic. Model substitution (#4) is **resolved clean** —
`gemini-3.5-flash` on all 18 calls. The GPU share (#6) measured **0.0%** on a
cache-hit run; a cold Colab analysis remains unmeasured but is bounded to one job
per song against ~$4 of model calls.

---

## What I recommend, and what I am NOT doing yet

Per REQ-R2-COST-05 reductions are gated on this autopsy, and per §5 of the brief this
report ships **before** reductions start. I have implemented no cost reductions.

**Both prerequisites from draft 1 are now DONE:** the `gemini-3.5-flash` rate is
verified, and one song has been run end to end with the ledger live. Between them
they moved the driver ranking twice and cost about half an hour and $4.28.

**The reductions the measured data justifies**, ranked:

| # | fix | targets | confidence |
|---|---|---|---|
| 1 | **Cap `thinking_level` per stage.** `high` for the designer only; `low`/`minimal` for the critic (a scoring task thinking 3,092 tokens/call) and for every retry. Add a per-call reasoning budget. | the **45.8%** of spend that is reasoning | high — measured, and the critic/retry case is hard to argue against |
| 2 | **Cap and cheapen the re-prompt loops.** Median 4 calls/chart against a happy path of 2. Make retries reuse a cached context rather than re-sending 100k tokens, and add budget awareness before the 3rd attempt. | the **48.8%** of spend in re-prompts | high — measured |
| 3 | **Vertex context caching of the per-song analysis block** across difficulties, retries and critic passes, + de-duplicate the byte-identical easy≡medium and hard≡challenge inventories. | the **31.3%** that is text input, and it multiplies fix #2 | high — 10× cache discount, `cached_tokens: 0` confirmed live |

These compose rather than overlap: #1 attacks output-rate tokens, #3 attacks
input-rate tokens, #2 attacks the call multiplier that makes both worse.

**A caution on sequencing.** Fixes #2 and #3 interact: capping retries reduces the
value of caching, and caching reduces the cost of retries. Measure after each, not
after both, or the attribution will be unrecoverable — which is the mistake this
whole report exists to correct.

**Ranked TODO, not being implemented now** (no speculative optimization):

| fix | projected saving | why deferred |
|---|---:|---|
| Trim the onset inventory handed to low difficulties (beginner is offered 371 of 1,337 onsets and needs far fewer) | ~10–15% of designer text | needs a chart-quality check first; fewer candidates could hurt timing, which is SACRED-02. **Note Round 2's timing fix pushed the other way** — re-phasing the grid admits more onsets (see `round1-vs-round2.md`), so this is now worth more and also riskier |
| Cap the critic-revision loop with budget awareness (a second full re-design is the most expensive single decision in the pipeline) | up to 3 calls/chart in the tail | needs the calls-per-chart distribution to size |
| Drop the JSON-parse retry's audio re-send (the audio was already understood; only the format was wrong) | ~1% | trivial saving, real correctness risk |
| Compress the inventory encoding (arrays instead of per-onset JSON objects with repeated keys) | ~30–40% of inventory bytes | changes the designer's input format — a prompt-quality change disguised as a cost fix; do it after Workstream B lands |

**Sacred-core note.** Nothing proposed here routes audio analysis through an LLM or
changes what the designer may emit, so REQ-R2-SACRED-01 is untouched. The two
recommended reductions are a generation-config change and a transport-level cache;
neither alters chart content, so SACRED-02/03 should be unaffected — but both will be
re-validated against the harness before shipping, not assumed.
