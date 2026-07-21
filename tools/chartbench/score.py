"""score.py — grade ANY StepMania pack with beatforge's objective chart metrics.

The point of the benchmark: run our charts and a baseline generator's charts through
the *identical* scorer, over the *identical* audio, using the *identical* DSP
analysis. No home-field advantage. Whatever the numbers say, they say.

    python3 score.py --pack "SweetPapa Dream Mix - Founder Mix" --label STEPFORGE
    python3 score.py --pack "FoFo-Compare-Mix" --label DDC
    python3 score.py --compare out/STEPFORGE.json out/DDC.json

The metrics (all from beatforge/adapters/stepmania/qa.py, unchanged):

  onset_alignment   fraction of notes landing within 35ms of a real audio transient.
                    THE headline number: is the chart on the music, or on a grid?
  panel_balance     share of notes per panel. A chart that lives on two arrows is bad.
  flow_cost_mean    foot-flow comfort. Penalises double-steps (8.0), jacks (6.0),
  flow_cost_max     crossovers (5.0); rewards clean alternation (-1.0). This is the
                    one that measures whether a chart is pleasant to actually dance.
  density_energy    Spearman correlation of note density against the song's energy
                    curve. Does the chart get busy when the MUSIC gets busy?
  hold/jump_share   vocabulary richness.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatforge import config                                        # noqa: E402
from beatforge.analyze import analyze_track                         # noqa: E402
from beatforge.adapters.stepmania.qa import chart_metrics           # noqa: E402

import sm_parse                                                     # noqa: E402

SONGS = Path("~/Library/Application Support/ITGmania/Songs").expanduser()
OUT = Path(__file__).parent / "out"

# StepMania slot -> beatforge budget tier. Generators that emit only a subset (DDC
# ships Beginner..Challenge too) still line up.
SLOT = {"Beginner": "beginner", "Easy": "easy", "Medium": "medium",
        "Hard": "hard", "Challenge": "challenge",
        # DDC and friends sometimes use the older names
        "Basic": "easy", "Another": "medium", "Maniac": "hard", "Edit": "challenge"}


def analysis_for(ogg: Path, base: str) -> dict:
    """DSP analysis of the ACTUAL audio. Deterministic, offline, cached — and the
    same analysis object is used to score every generator's chart for this song, so
    'onset alignment' means the same thing for all of them."""
    dst = config.TRACKS_SRC / f"{base}.ogg"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        dst.write_bytes(ogg.read_bytes())
    return analyze_track(base, config.RunOptions(force=False))


def score_pack(pack: str, label: str) -> dict:
    pack_dir = SONGS / pack
    if not pack_dir.is_dir():
        raise SystemExit(f"no pack at {pack_dir}")

    songs = {}
    for song_dir in sorted(p for p in pack_dir.iterdir() if p.is_dir()):
        sim = next(iter(sorted(song_dir.glob("*.sm")) + sorted(song_dir.glob("*.ssc"))), None)
        ogg = next(iter(song_dir.glob("*.ogg")), None)
        if not sim or not ogg:
            continue
        base = ogg.stem
        try:
            an = analysis_for(ogg, base)
        except Exception as e:                                       # noqa: BLE001
            print(f"  [skip] {song_dir.name}: analysis failed ({e})", file=sys.stderr)
            continue

        # Rebase the chart into OUR analysis's tempo frame before scoring.
        #
        # Every generator writes beats relative to its own detected BPM/offset, and
        # they disagree — AutoStepper calls one of these songs 130 BPM where our DSP
        # measures 173.5. chart_metrics converts beats->seconds with OUR bpm, so
        # feeding it foreign beats verbatim would scatter their notes across the
        # timeline and hand us a flattering, meaningless win.
        text = Path(sim).read_text(errors="replace")
        bpms = sm_parse.bpm_map(text)
        _, sm_off, charts = sm_parse.parse(sim)

        per_diff = {}
        for c in charts:
            tier = SLOT.get(c.difficulty)
            if not tier:
                continue
            rc = sm_parse.rebase(c, bpms, sm_off, an["bpm"], an["offset"])
            m = chart_metrics(rc.placements, an, tier)
            m["meter"] = c.meter
            m["declared_bpm"] = round(bpms[0][1], 2)
            m["true_bpm"] = round(an["bpm"], 2)
            per_diff[tier] = m
        if per_diff:
            songs[song_dir.name] = per_diff
            print(f"  {label:<10} {song_dir.name[:44]:<45} "
                  f"{len(per_diff)} charts")
    return {"label": label, "pack": pack, "songs": songs}


def _collect(result: dict, key: str, tier: str | None = None) -> list[float]:
    vals = []
    for diffs in result["songs"].values():
        for t, m in diffs.items():
            if tier and t != tier:
                continue
            v = m.get(key)
            if isinstance(v, (int, float)):
                vals.append(float(v))
    return vals


def _gate_rate(result: dict, gate: str) -> float:
    hits = tot = 0
    for diffs in result["songs"].values():
        for m in diffs.values():
            g = m.get("gates", {})
            if gate in g:
                tot += 1
                hits += bool(g[gate])
    return hits / tot if tot else 0.0


def summarize(results: list[dict]) -> None:
    def row(name, fn, fmt="{:.3f}"):
        cells = "".join(f"{fmt.format(fn(r)):>16}" for r in results)
        print(f"  {name:<26}{cells}")

    def mean(key):
        return lambda r: statistics.mean(_collect(r, key)) if _collect(r, key) else 0.0

    print("\n" + "=" * (28 + 16 * len(results)))
    hdr = "".join(f"{r['label']:>16}" for r in results)
    print(f"  {'METRIC':<26}{hdr}")
    print("=" * (28 + 16 * len(results)))

    print("  -- charts scored --")
    row("songs", lambda r: len(r["songs"]), "{:.0f}")
    row("charts", lambda r: sum(len(d) for d in r["songs"].values()), "{:.0f}")

    print("  -- did it even hear the TEMPO? --")

    def bpm_err(r):
        errs = []
        for diffs in r["songs"].values():
            m = next(iter(diffs.values()), None)
            if m and m.get("declared_bpm") and m.get("true_bpm"):
                errs.append(abs(m["declared_bpm"] - m["true_bpm"]) / m["true_bpm"])
        return statistics.mean(errs) if errs else 0.0

    def bpm_ok(r):
        """Within 2%, allowing octave errors (half/double time is a defensible
        reading of a tempo, not a failure to hear one)."""
        hits = tot = 0
        for diffs in r["songs"].values():
            m = next(iter(diffs.values()), None)
            if not (m and m.get("declared_bpm") and m.get("true_bpm")):
                continue
            tot += 1
            d, t = m["declared_bpm"], m["true_bpm"]
            hits += any(abs(d * k - t) / t < 0.02 for k in (0.5, 1, 2))
        return hits / tot if tot else 0.0

    row("bpm rel. error", bpm_err)
    row("bpm correct (±oct)", bpm_ok)

    print("  -- is it ON the music? --")
    row("onset_alignment", mean("onset_alignment"))
    row("  gate pass rate", lambda r: _gate_rate(r, "onset_alignment"))

    print("  -- is it DANCEABLE? --")
    row("flow_cost_mean", mean("flow_cost_mean"), "{:.2f}")
    row("flow_cost_max", mean("flow_cost_max"), "{:.2f}")
    row("  flow gate pass", lambda r: _gate_rate(r, "flow_ceiling"))

    print("  -- does it FOLLOW the song? --")
    row("density_energy_rho", mean("density_energy_spearman"))
    row("  gate pass rate", lambda r: _gate_rate(r, "density_energy"))

    print("  -- vocabulary / balance --")
    row("hold_share", mean("hold_share"))
    row("jump_share", mean("jump_share"))
    row("panel_balance gate", lambda r: _gate_rate(r, "panel_balance"))
    row("notes / chart", mean("notes"), "{:.0f}")
    print("=" * (28 + 16 * len(results)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pack")
    p.add_argument("--label")
    p.add_argument("--compare", nargs="+", metavar="JSON")
    a = p.parse_args()

    OUT.mkdir(exist_ok=True)
    if a.compare:
        summarize([json.loads(Path(f).read_text()) for f in a.compare])
        return

    if not a.pack:
        raise SystemExit("need --pack or --compare")
    label = a.label or a.pack
    res = score_pack(a.pack, label)
    dst = OUT / f"{label}.json"
    dst.write_text(json.dumps(res, indent=1))
    print(f"\nwrote {dst}")
    summarize([res])


if __name__ == "__main__":
    main()
