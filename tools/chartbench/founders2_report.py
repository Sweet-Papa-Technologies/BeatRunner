"""founders2_report.py — how does the new mix score against everything before it?

Compares SweetPapa's Founders Mix #2 (Round 3 pipeline, gemini-3.6-flash) against
every prior iteration and both external competitors, using the same scorer.

An honest caveat this report states rather than hides: the competitor and R1/R2
numbers come from a DIFFERENT song set (the 13-song benchmark / the 4-song compare
pack). Founders Mix #2 is 9 new masters. So this is "how does the new pack score"
next to "how did those score" — a fleet-level comparison, not a song-matched one.
Where a song-matched comparison exists, `docs/compare2-five-way.md` is the one to
trust for head-to-head claims.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "out"


def load(fn):
    p = OUT / fn
    return json.loads(p.read_text())["songs"] if p.exists() else {}


def agg(songs, label_filter=None):
    ch = []
    for song, diffs in songs.items():
        if label_filter and not song.endswith(f"[{label_filter}]"):
            continue
        ch.extend(diffs.values())
    if not ch:
        return None

    def mean(k):
        v = [c[k] for c in ch if c.get(k) is not None]
        return statistics.fmean(v) if v else float("nan")

    def gate(k):
        v = [c["gates"][k] for c in ch if "gates" in c]
        return sum(v) / len(v) if v else float("nan")

    return {"charts": len(ch), "flow_gate": gate("flow_ceiling"),
            "flow_max": mean("flow_cost_max"), "rho": mean("density_energy_spearman"),
            "density_gate": gate("density_energy"), "notes": mean("notes"),
            "jump": mean("jump_share"), "hold": mean("hold_share")}


def main():
    cmp2 = load("COMPARE2.json")
    rows = [
        ("Founders Mix #2 (R3, 3.6-flash)", agg(load("FOUNDERS2.json")), "9 new masters"),
        ("STEPFORGE-R3 (compare pack)", agg(cmp2, "STEPFORGE-R3"), "4 songs"),
        ("STEPFORGE-R2 (compare pack)", agg(cmp2, "STEPFORGE-R2"), "4 songs"),
        ("STEPFORGE-R1 (compare pack)", agg(cmp2, "STEPFORGE-R1"), "4 songs"),
        ("DDC (2017, learned)", agg(cmp2, "DDC"), "4 songs"),
        ("AutoStepper (2018, DSP)", agg(cmp2, "AUTOSTEPPER"), "4 songs"),
    ]
    rows = [(n, r, note) for n, r, note in rows if r]
    if not rows:
        print("no scored data found"); return

    L = ["# SweetPapa's Founders Mix #2 — benchmark", "",
         "Scored by `chartbench/score.py`, the same scorer used for every previous "
         "round and both competitors.", "",
         "> **Read this before quoting the table.** The competitor and R1/R2/R3 rows "
         "were scored on *different songs* (the 13-song benchmark and the 4-song "
         "compare pack). Founders Mix #2 is 9 new masters. This shows how the new "
         "pack scores beside how those scored — it is not a song-matched head to "
         "head. For that, see `docs/compare2-five-way.md`.", "",
         "| generator | songs | charts | flow gate | flow_max | rho | density gate | notes | jump |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, r, note in rows:
        L.append(f"| {name} | {note} | {r['charts']} | {r['flow_gate']:.0%} | "
                 f"{r['flow_max']:.2f} | {r['rho']:+.3f} | {r['density_gate']:.0%} | "
                 f"{r['notes']:.0f} | {r['jump']:.3f} |")

    f2 = rows[0][1]
    L += ["", "## Where the new pack lands", ""]
    for name, r, _ in rows[1:]:
        L.append(f"- vs **{name}**: flow gate {f2['flow_gate']:.0%} vs {r['flow_gate']:.0%}, "
                 f"rho {f2['rho']:+.3f} vs {r['rho']:+.3f}, "
                 f"notes {f2['notes']:.0f} vs {r['notes']:.0f}")

    # cost, straight from the ledger
    sys.path.insert(0, str(REPO / "tools"))
    try:
        from beatforge import costreport
        e = [x for x in costreport.load_entries()
             if x.get("kind") == "model" and str(x.get("song", "")).startswith("fm2_")]
        if e:
            usd = sum(x["cost_usd"]["total"] for x in e)
            songs = len({x["song"] for x in e})
            charts = len({(x["song"], x["difficulty"]) for x in e if x.get("difficulty")})
            models = sorted({x["model"] for x in e})
            L += ["", "## What it cost (measured, from the per-call ledger)", "",
                  f"- **${usd:.2f}** total across {songs} songs / {charts} charts "
                  f"({len(e)} model calls)",
                  f"- **${usd/max(1,songs):.2f}/song**, **${usd/max(1,charts):.2f}/chart**",
                  f"- model(s) actually used: {', '.join(models)}"]
    except Exception as ex:
        L += ["", f"_(cost unavailable: {ex})_"]

    md = "\n".join(L) + "\n"
    (REPO / "docs" / "founders-mix-2-benchmark.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
