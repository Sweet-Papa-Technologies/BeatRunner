"""export_web.py — per-song, per-generator data for the comparison site.

Emits one JSON blob with everything the page needs: per-song timing-error
distributions, flow costs, density correlation, and declared-vs-true BPM. Computed
from the installed packs, so the site can never drift from the actual charts.
"""
from __future__ import annotations

import bisect
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatforge import config                                       # noqa: E402
from beatforge.analyze import analyze_track                        # noqa: E402
from beatforge.adapters.stepmania.qa import chart_metrics          # noqa: E402

import sm_parse                                                    # noqa: E402
from make_pack import TITLES                                       # noqa: E402

SONGS = Path("~/Library/Application Support/ITGmania/Songs").expanduser()
SP = SONGS / "SweetPapa Dream Mix - Founder Mix"
CM = SONGS / "FoFo-Compare-Mix"
GENS = ("STEPFORGE", "AUTOSTEPPER", "DDC")
TIERS = ("beginner", "easy", "medium", "hard", "challenge")
SLOT = {"Beginner": "beginner", "Easy": "easy", "Medium": "medium",
        "Hard": "hard", "Challenge": "challenge"}

# ITGmania's own judgment windows (seconds, +/-)
WINDOWS = {"fantastic": 0.021, "excellent": 0.043, "great": 0.102}


def sim_for(gen: str, base: str, title: str) -> Path | None:
    p = (SP / title / f"{base}.sm" if gen == "STEPFORGE"
         else CM / f"{title} [{gen}]" / f"{base}.sm")
    return p if p.exists() else None


def main():
    out = {"songs": [], "generators": list(GENS)}

    for base, title in TITLES.items():
        an = analyze_track(base, config.RunOptions(force=False))
        onsets = sorted(o["time"] for o in an["onsets"])

        def nearest(t: float) -> float:
            i = bisect.bisect_left(onsets, t)
            c = [onsets[j] for j in (i - 1, i) if 0 <= j < len(onsets)]
            return min(abs(t - x) for x in c) if c else 9.9

        song = {
            "title": title, "base": base,
            "true_bpm": round(an["bpm"], 1),
            "duration": round(an["duration_s"], 1),
            "onsets": len(onsets),
            "energy_cv": round(an.get("energy_cv", 0), 3),
            "gen": {},
        }

        for gen in GENS:
            sim = sim_for(gen, base, title)
            if not sim:
                continue
            text = sim.read_text(errors="replace")
            bpms = sm_parse.bpm_map(text)
            _, off, charts = sm_parse.parse(sim)

            errs_all, tiers = [], {}
            for c in charts:
                tier = SLOT.get(c.difficulty)
                if not tier:
                    continue
                rc = sm_parse.rebase(c, bpms, off, an["bpm"], an["offset"])
                m = chart_metrics(rc.placements, an, tier)
                errs = [nearest(an["offset"] + p.beat / an["bpm"] * 60)
                        for p in rc.placements]
                errs_all += errs
                tiers[tier] = {
                    "notes": len(rc.placements),
                    "meter": c.meter,
                    "flow_max": m["flow_cost_max"],
                    "flow_mean": m["flow_cost_mean"],
                    "rho": m["density_energy_spearman"],
                    "hold": m["hold_share"],
                    "jump": m["jump_share"],
                    "gates": m["gates"],
                    "median_err_ms": round(statistics.median(errs) * 1000, 1) if errs else None,
                }
            if not errs_all:
                continue
            n = len(errs_all)
            song["gen"][gen] = {
                "declared_bpm": round(bpms[0][1], 1),
                "notes": n,
                "median_err_ms": round(statistics.median(errs_all) * 1000, 1),
                "windows": {k: round(sum(e < w for e in errs_all) / n, 4)
                            for k, w in WINDOWS.items()},
                # histogram of |error| in 10ms buckets, 0-200ms+
                "hist": [sum(1 for e in errs_all if lo / 1000 <= e < (lo + 10) / 1000) / n
                         for lo in range(0, 200, 10)] + [sum(1 for e in errs_all if e >= 0.2) / n],
                "flow_max": round(statistics.mean(t["flow_max"] for t in tiers.values()), 2),
                "flow_mean": round(statistics.mean(t["flow_mean"] for t in tiers.values()), 2),
                "rho": round(statistics.mean(t["rho"] for t in tiers.values() if t["rho"] is not None), 3)
                       if any(t["rho"] is not None for t in tiers.values()) else None,
                "hold": round(statistics.mean(t["hold"] for t in tiers.values()), 4),
                "jump": round(statistics.mean(t["jump"] for t in tiers.values()), 4),
                "flow_gate": round(sum(t["gates"]["flow_ceiling"] for t in tiers.values())
                                   / len(tiers), 3),
                "density_gate": round(sum(t["gates"]["density_energy"] for t in tiers.values())
                                      / len(tiers), 3),
                "tiers": tiers,
            }
        out["songs"].append(song)
        print(f"  {title[:40]:<42} " +
              "  ".join(f"{g}:{song['gen'].get(g, {}).get('median_err_ms', '-')}ms" for g in GENS))

    dst = Path(__file__).parent / "out" / "web_data.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\nwrote {dst}  ({dst.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
