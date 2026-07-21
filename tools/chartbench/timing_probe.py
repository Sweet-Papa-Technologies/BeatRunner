"""timing_probe.py — decompose each generator's timing error.

Round 1 reported RAW absolute error and drew a causal conclusion from it. That was
sloppy: a chart that is uniformly 58ms late is not "badly timed", it is *offset*, and
one `#OFFSET` edit fixes it. A chart with 58ms of random jitter is genuinely badly
timed and cannot be fixed at all.

The raw number cannot tell those two apart. This can:

  signed median   — are the notes consistently EARLY (-) or LATE (+)?
  |raw| median    — what Round 1 reported.
  |residual|      — error AFTER removing one global per-song shift. THE number that
                    says whether a generator can actually place a note.
  drift           — ms of signed error gained per minute; a nonzero slope means the
                    time map diverges as the song goes on (a tempo error, not an offset).
  independent     — the same residual, but measured against an onset detector that has
                    nothing to do with our pipeline, to check we aren't grading against
                    our own reflection.
"""
from __future__ import annotations

import bisect
import json
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatforge import config                                       # noqa: E402
from beatforge.analyze import analyze_track                        # noqa: E402

import sm_parse                                                    # noqa: E402
from make_pack import TITLES                                       # noqa: E402

SONGS = Path("~/Library/Application Support/ITGmania/Songs").expanduser()
SP = SONGS / "SweetPapa Dream Mix - Founder Mix"
CM = SONGS / "FoFo-Compare-Mix"
GENS = ("STEPFORGE", "AUTOSTEPPER", "DDC")
AUDIO = Path(__file__).parent / "audio"


def independent_onsets(ogg: Path) -> list[float]:
    """An onset inventory built by librosa with stock parameters — NOT our dsp.py, and
    not tuned by us. If our conclusions only hold against our own detector, they aren't
    conclusions."""
    import librosa
    y, sr = librosa.load(str(ogg), sr=22050, mono=True)
    t = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=False)
    return sorted(float(x) for x in t)


def signed_nearest(t: float, onsets: list[float]) -> float | None:
    """Signed distance to the nearest onset: positive = the note is LATE."""
    if not onsets:
        return None
    i = bisect.bisect_left(onsets, t)
    cands = [onsets[j] for j in (i - 1, i) if 0 <= j < len(onsets)]
    return min((t - c for c in cands), key=abs)


def sim_for(gen: str, base: str, title: str) -> Path | None:
    p = (SP / title / f"{base}.sm" if gen == "STEPFORGE"
         else CM / f"{title} [{gen}]" / f"{base}.sm")
    return p if p.exists() else None


def note_times(sim: Path) -> list[float]:
    text = sim.read_text(errors="replace")
    bpms = sm_parse.bpm_map(text)
    _, off, charts = sm_parse.parse(sim)
    ts = []
    for c in charts:
        ts += [sm_parse.beat_to_time(p.beat, bpms, off) for p in c.placements]
    return sorted(ts)


def decompose(times: list[float], onsets: list[float]) -> dict | None:
    """Split raw error into (global offset) + (residual jitter) + (drift)."""
    e = [(t, signed_nearest(t, onsets)) for t in times]
    e = [(t, d) for t, d in e if d is not None and abs(d) < 0.25]   # ignore unmatched
    if len(e) < 30:
        return None
    ts = np.array([t for t, _ in e])
    ds = np.array([d for _, d in e])

    shift = float(np.median(ds))                     # the one global correction
    resid = ds - shift
    slope = float(np.polyfit(ts, ds, 1)[0]) if len(ts) > 50 else 0.0   # sec of err / sec

    return {
        "n": len(e),
        "signed_median_ms": round(shift * 1000, 1),
        "raw_abs_median_ms": round(float(np.median(np.abs(ds))) * 1000, 1),
        "residual_abs_median_ms": round(float(np.median(np.abs(resid))) * 1000, 1),
        "residual_iqr_ms": round(float(np.percentile(np.abs(resid), 75)
                                       - np.percentile(np.abs(resid), 25)) * 1000, 1),
        "drift_ms_per_min": round(slope * 60 * 1000, 1),
        "resid_within_21ms": round(float(np.mean(np.abs(resid) < 0.021)), 4),
    }


def main():
    rows = {g: {"ours": [], "indep": []} for g in GENS}
    detail = []

    for base, title in TITLES.items():
        an = analyze_track(base, config.RunOptions(force=False))
        ours = sorted(o["time"] for o in an["onsets"])
        indep = independent_onsets(AUDIO / f"{base}.ogg")

        rec = {"title": title, "true_bpm": round(an["bpm"], 1),
               "onsets_ours": len(ours), "onsets_indep": len(indep), "gen": {}}
        for g in GENS:
            sim = sim_for(g, base, title)
            if not sim:
                continue
            ts = note_times(sim)
            a = decompose(ts, ours)
            b = decompose(ts, indep)
            if a:
                rows[g]["ours"].append(a)
            if b:
                rows[g]["indep"].append(b)
            rec["gen"][g] = {"ours": a, "indep": b}
        detail.append(rec)
        print(f"  {title[:34]:<36}" + "  ".join(
            f"{g[:2]}:{rec['gen'].get(g, {}).get('ours', {}).get('residual_abs_median_ms', '-')}" for g in GENS))

    def agg(lst, key):
        v = [r[key] for r in lst if r and r.get(key) is not None]
        return round(statistics.mean(v), 1) if v else None

    print("\n" + "=" * 92)
    print(f"  {'':<14}{'signed':>10}{'raw |err|':>11}{'RESIDUAL':>11}{'resid IQR':>11}"
          f"{'drift':>10}{'resid<21ms':>12}")
    print(f"  {'':<14}{'median':>10}{'median':>11}{'median':>11}{'':>11}{'ms/min':>10}{'':>12}")
    print("=" * 92)
    for scope, lab in (("ours", "vs OUR onsets"), ("indep", "vs LIBROSA onsets (independent)")):
        print(f"  -- {lab} --")
        for g in GENS:
            L = rows[g][scope]
            if not L:
                continue
            print(f"  {g:<14}{agg(L,'signed_median_ms'):>9}ms{agg(L,'raw_abs_median_ms'):>10}ms"
                  f"{agg(L,'residual_abs_median_ms'):>10}ms{agg(L,'residual_iqr_ms'):>10}ms"
                  f"{agg(L,'drift_ms_per_min'):>10}{agg(L,'resid_within_21ms'):>12.1%}")
    print("=" * 92)

    out = Path(__file__).parent / "out" / "timing_probe.json"
    out.write_text(json.dumps({"songs": detail}, ensure_ascii=False, indent=1))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
