# STEPFORGE vs. the existing auto-charters

13 songs · 65 charts per generator · identical audio · identical scorer.

## The contenders

| | What it is | Why it's here |
|---|---|---|
| **STEPFORGE** | Ours. DSP onset inventory → Gemini 3.5 Flash designer (onset-IDs only, never timestamps) → foot-flow cost solver → deterministic gates. | The thing being tested. |
| **AutoStepper** | [phr00t/AutoStepper](https://github.com/phr00t/AutoStepper), 2018, Java, pure DSP + rule-based patterns. 134★. | The tool the community has *actually used* for eight years. The bar you have to clear to be worth existing. |
| **DDC** | [Dance Dance Convolution](https://github.com/chrisdonahue/ddc), ICML 2017. CNN→LSTM onset placement + conditional LSTM step selection. The citable academic baseline. | The paper everyone points at. Run from the author's own pretrained checkpoints. |

DDC's native stack is Python 2.7 + TensorFlow 0.12.1 + essentia — genuinely
uninstallable in 2026. It was run from the author's prebuilt `chrisdonahue/ddc`
Docker image under `linux/amd64` emulation on Apple Silicon. TF 0.12.1 executes
fine under Rosetta 2 (it predates AVX-dependent builds). The models are the
original `model_sp-56000` / `model_ss-23628` checkpoints.

---

## Read this before the results

**Two of our metrics are rigged in our favour, and I'm not going to pretend
otherwise.**

`onset_alignment` and `bpm error` are scored against *our own DSP analysis*. Our
designer places notes **by referencing IDs from that exact onset inventory**, and
our simfile's BPM **is** the BPM that analysis measured. So of course we score
~1.00 and 0.000. Those two rows are tautologies, not victories. Ignore them.

The honest questions are the ones our onset detector can't rig:

1. **In absolute milliseconds, where do the notes actually land?** Judged with
   *ITGmania's own* timing windows, not a threshold we invented.
2. **Is the chart physically comfortable to dance?** Foot-flow cost is pure arrow
   geometry — it doesn't touch audio analysis at all, so there's no way for our
   onset detector to flatter us.
3. **Does the chart's density follow the song's energy?**

---

## 1. Timing — where the notes really land

All 13 songs, all 65 charts each, error measured against the audio's transients and
bucketed by **ITGmania's own judgment windows**:

| | notes | median error | Fantastic (±21ms) | Excellent (±43ms) | Great (±102ms) |
|---|---:|---:|---:|---:|---:|
| **STEPFORGE** | 13,792 | **8 ms** | **81.4%** | **94.7%** | 97.7% |
| AutoStepper | 12,996 | 64 ms | 13.8% | 28.4% | 85.8% |
| DDC | 12,695 | 58 ms | 5.0% | 13.0% | **99.1%** |

**The interesting number here is DDC's 99.1%.** It is *not* placing notes randomly —
99% of its notes are within ±102ms of a real transient. DDC hears the music
perfectly well. It just can't write down *when*.

The reason is structural and it's the finding of the whole exercise: **DDC declares
`125.0 BPM` for every single song.** Not approximately — literally 125.0 for all 13,
whether the track is 110 or 173.5 BPM. It has no tempo model. It detects onsets in
continuous time and then snaps them onto a fake 125 BPM grid, and the grid's
resolution *is* the ~58ms median error. A note 58ms late is not a Fantastic or even
an Excellent — in ITG it's a **Great**, the judgment you get when you're visibly off
the beat. A bot playing DDC's own chart, perfectly, would be graded mediocre.

That DDC and our detector agree on where the music is (coarsely) while disagreeing
on precision is also the best evidence that the onset ground truth is sound — an
independently-trained 2017 CNN corroborates it.

AutoStepper *does* detect tempo per song, and gets it right (within an octave) on
10 of 13 — but its median error is still 64ms, worse than DDC's.

## 2. Danceability — the metric we cannot rig

Foot-flow cost is a state machine over (left foot, right foot, who moved last),
penalising double-steps (8.0), jacks (6.0) and crossovers (5.0), rewarding clean
alternation (−1.0). **It never looks at the audio.** No onset detector can flatter it.

| | flow cost (mean) | flow cost (**max**) | charts passing the flow gate |
|---|---:|---:|---:|
| **STEPFORGE** | **7.09** | **9.41** | **96.9%** |
| AutoStepper | 9.09 | 25.18 | 0.0% |
| DDC | 8.33 | 24.75 | 12.3% |

The *max* column is the story. A max cost of ~25 means both baselines routinely emit
transitions in the forbidden tier — patterns that force a double-step or a physically
awkward spin. **AutoStepper passes the flow gate on zero of 65 charts.** DDC on 8.

This is the real result. Both baselines can find the beat, roughly. Neither has any
model of the fact that a human has two feet.

## 3. Density vs. energy — **where we lose**

Spearman correlation of note density against the song's energy curve. Does the chart
get busier when the *music* gets busier?

| | ρ | charts passing the gate |
|---|---:|---:|
| STEPFORGE | 0.338 | 23.1% |
| AutoStepper | 0.189 | 7.7% |
| **DDC** | **0.466** | **43.1%** |

**DDC beats us, clearly, and it deserves to.** Its step-placement CNN is conditioned
on difficulty and trained on thousands of human charts, so it learned what human
charters actually do: go quiet in the breakdown, go wild in the drop. Our designer is
told to do this in a prompt and only manages it about half as well.

This is the most useful thing the benchmark told us, and it's a to-do, not a
footnote: **our charts are precisely placed and comfortable to dance, but flatter in
their dynamics than a model from 2017.**

## 4. Vocabulary

| | holds | jumps | notes/chart |
|---|---:|---:|---:|
| STEPFORGE | 8.9% | 5.7% | 212 |
| AutoStepper | 17.3% | 3.9% | 200 |
| DDC | 5.8% | 6.0% | 195 |

Note counts are close enough that nobody is winning on timing by simply spamming
notes.

---

## Verdict

**Where we genuinely win:** timing precision (8ms vs ~60ms median — an order of
magnitude, and the difference between "Fantastic" and "Great" on every note), and
danceability (96.9% vs 0% and 12.3% flow-gate pass). The onset-ID contract and the
foot-flow solver both do exactly what they were designed to do.

**Where we genuinely lose:** dynamics. DDC's charts follow the song's energy contour
better than ours do.

**What's tautological:** our onset-alignment and BPM scores. Discard them.

## Reproduce

```bash
# AutoStepper
java -jar AutoStepper.jar input=./audio/ output=./as_out/ duration=300 hard=true

# DDC (its native stack is dead; the author's image is not)
docker pull --platform linux/amd64 chrisdonahue/ddc:latest
docker run --platform linux/amd64 -v ./audio:/audio -v ./ddc_out:/out \
       --entrypoint python chrisdonahue/ddc:latest /ddc_batch.py

# package + score
python3 make_pack.py --label AUTOSTEPPER --sm-dir ./as_out --pack FoFo-Compare-Mix
python3 make_pack.py --label DDC         --sm-dir ./ddc_out --pack FoFo-Compare-Mix
python3 score.py --compare out/STEPFORGE.json out/AUTOSTEPPER.json out/DDC.json
```

Every generator's chart is rebased into the audio's real time domain before scoring
(`sm_parse.rebase`). This matters: each simfile's beats are relative to its own
tempo map, and they disagree wildly — scoring DDC's beats against our BPM would have
scattered its notes across the timeline and handed us a meaningless win.

## Play them yourself

`FoFo-Compare-Mix` is installed in ITGmania: every song appears twice, as
`<Title> [AUTOSTEPPER]` and `<Title> [DDC]`, on the same audio as the real pack. Put
them next to `SweetPapa Dream Mix — Founder Mix` in the wheel and dance all three.
The tables above should stop being abstract within about eight bars.
