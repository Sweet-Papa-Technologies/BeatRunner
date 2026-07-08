"""_analyze_pack.py — parse .sm/.ssc via the simfile lib and compute the metrics
that capture 'stream' and 'variance', to compare the reference DDR pack against
our generated FoFoSongs output and see what the formula is missing.

Quantization is taken from EXACT beat fractions (denominator of beat-mod-1), so
8ths/12ths/16ths/24ths are classified correctly. A 'stream' is a run of notes at
a constant 16th (0.25 beat) spacing.
"""
from __future__ import annotations
import glob, os, statistics, json
from fractions import Fraction
from collections import Counter, defaultdict

import simfile
from simfile.notes import NoteData, NoteType

STEP_TYPES = {NoteType.TAP, NoteType.HOLD_HEAD, NoteType.ROLL_HEAD}


def quant_label(beat: Fraction) -> str:
    frac = Fraction(beat) % 1
    d = frac.limit_denominator(48).denominator
    return {1: "4", 2: "8", 3: "12", 4: "16", 6: "24", 8: "32"}.get(d, "other")


def analyze_chart(chart, bpm):
    nd = NoteData(chart)
    rows = defaultdict(list)          # beat -> columns with a step
    holds = 0
    for n in nd:
        if n.note_type not in STEP_TYPES:
            continue
        rows[Fraction(n.beat)].append(n.column)
        if n.note_type in (NoteType.HOLD_HEAD, NoteType.ROLL_HEAD):
            holds += 1
    if not rows:
        return None
    beats = sorted(rows)
    notes = sum(len(v) for v in rows.values())
    jumps = sum(1 for b in beats if len(rows[b]) >= 2)
    quant = Counter(quant_label(b) for b in beats)

    # streams: longest run of consecutive rows at a CONSTANT fast spacing.
    #   16th run = delta 1/4 beat ; 8th run = delta 1/2 beat. DDR 'streams' are
    #   often 8ths at high bpm, so track both plus 'any constant fast spacing'.
    def longest_run(spacing):
        best = cur = 1
        for i in range(1, len(beats)):
            cur = cur + 1 if beats[i] - beats[i-1] == spacing else 1
            best = max(best, cur)
        return best
    longest16 = longest_run(Fraction(1, 4))
    longest8 = longest_run(Fraction(1, 2))
    # any-constant-spacing run (the felt 'stream'): same delta repeated
    best = cur = 1
    for i in range(1, len(beats)):
        same = i >= 2 and (beats[i] - beats[i-1]) == (beats[i-1] - beats[i-2])
        fast = (beats[i] - beats[i-1]) <= Fraction(1, 2)
        cur = cur + 1 if (same and fast) else 1
        best = max(best, cur)
    longest_any = best
    QUARTER = Fraction(1, 4)
    runs = []
    c = 1
    for i in range(1, len(beats)):
        c = c + 1 if beats[i] - beats[i-1] == QUARTER else (runs.append(c) or 1)
    runs.append(c)
    stream_rows = sum(r for r in runs if r >= 8)      # >=8 sixteenths = >=2 beats

    # density variance across 4-beat measures
    span = float(beats[-1]) if beats else 1
    per_measure = Counter(int(float(b) // 4) for b in beats for _ in rows[b])
    counts = [per_measure[m] for m in range(int(span // 4) + 1)]
    nz = [c for c in counts if c > 0]
    cv = (statistics.pstdev(nz) / statistics.mean(nz)) if len(nz) > 1 and statistics.mean(nz) else 0

    dur_s = span * 60.0 / bpm if bpm else 1
    # nps peak over any 8-beat window (approx, constant bpm)
    win = 8
    peak_rows = 0
    for i, b in enumerate(beats):
        j = i
        while j < len(beats) and beats[j] - b < win:
            j += 1
        peak_rows = max(peak_rows, sum(len(rows[beats[k]]) for k in range(i, j)))
    nps_peak = peak_rows / (win * 60.0 / bpm) if bpm else 0

    tot = sum(quant.values()) or 1
    return {
        "notes": notes, "dur_s": round(dur_s, 1), "nps_peak": round(nps_peak, 2),
        "quant_pct": {k: round(100*quant.get(k, 0)/tot) for k in ("4","8","12","16","24","32","other")},
        "longest_stream16": longest16,
        "longest_stream8": longest8,
        "longest_run_any": longest_any,
        "stream16_frac": round(stream_rows / (len(beats) or 1), 2),
        "jump_frac": round(jumps / (len(beats) or 1), 2),
        "hold_frac": round(holds / (notes or 1), 2),
        "measure_cv": round(cv, 2),
    }


def first_bpm(sf):
    try:
        return float(str(sf.bpms).split("=")[1].split(",")[0])
    except Exception:
        return 150.0


def collect(paths, diff_filter=None):
    charts = []
    for p in paths:
        try:
            sf = simfile.open(p)
            bpm = first_bpm(sf)
            for c in sf.charts:
                if "single" not in (c.stepstype or ""):
                    continue
                if diff_filter and (c.difficulty or "").lower() not in diff_filter:
                    continue
                m = analyze_chart(c, bpm)
                if m:
                    m["_diff"] = c.difficulty; m["_meter"] = c.meter
                    m["_song"] = os.path.basename(os.path.dirname(p))
                    charts.append(m)
        except Exception as e:
            print(f"  parse fail {os.path.basename(p)}: {str(e)[:80]}")
    return charts


def summarize(charts):
    if not charts:
        return {"n_charts": 0}
    kn = ["notes","nps_peak","longest_stream16","longest_stream8","longest_run_any",
          "stream16_frac","jump_frac","hold_frac","measure_cv"]
    agg = {k: round(statistics.mean(c[k] for c in charts), 2) for k in kn}
    agg["quant_pct_avg"] = {s: round(statistics.mean(c["quant_pct"][s] for c in charts))
                            for s in ("4","8","12","16","24","32","other")}
    # distribution of the felt-stream length across charts (find flat charts)
    runs = sorted(c["longest_run_any"] for c in charts)
    agg["run_any_p10_med_p90"] = [runs[len(runs)//10], runs[len(runs)//2], runs[min(len(runs)-1, 9*len(runs)//10)]]
    agg["n_charts"] = len(charts)
    return agg


def show(label, charts):
    print(f"\n=== {label}: {len(charts)} charts ===")
    print(json.dumps(summarize(charts), indent=2))


if __name__ == "__main__":
    REF = glob.glob("/Users/fterry/Downloads/pack_41_0ff7d6/*/*.sm")
    OURS = (glob.glob("/Users/fterry/Library/Application Support/ITGmania/Songs/FoFoSongs/*/*.ssc")
            or glob.glob("/Users/fterry/Library/Application Support/ITGmania/Songs/FoFoSongs/*/*.sm"))
    show("REFERENCE DDR (all diffs)", collect(REF))
    show("OUR FoFoSongs (all diffs)", collect(OURS))
    show("REFERENCE hardest (Heavy/Challenge)", collect(REF, {"heavy","challenge","oni","expert"}))
    show("OUR hard", collect(OURS, {"hard","challenge"}))
