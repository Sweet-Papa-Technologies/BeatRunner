"""model_report.py — quality-per-dollar across designer models.

Answers the only question that matters when a cheaper model appears: does it
chart as well, and what does it actually cost? Quality comes from the same
`score.py` metrics every generator is judged by; cost comes from the real
per-call ledger (`build/cost/<song>/cost_ledger.jsonl`), grouped by the model
string that actually went over the wire — not from config, and not from a
price-list estimate.

    python3 model_report.py --song lucky_lucky
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from beatforge import costreport, pricing                      # noqa: E402

# pack label -> the model that produced it
LABEL_MODEL = {
    "STEPFORGE-R3": "gemini-3.5-flash",
    "STEPFORGE-R3-G36": "gemini-3.6-flash",
    "STEPFORGE-R3-LITE": "gemini-3.5-flash-lite",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default="lucky_lucky")
    ap.add_argument("--title", help="pack title of --song (default: from make_pack.TITLES)")
    ap.add_argument("--scored", default="out/COMPARE2.json")
    a = ap.parse_args()

    here = Path(__file__).resolve().parent
    scored = json.loads((here / a.scored).read_text())["songs"]
    from make_pack import TITLES
    title = a.title or TITLES[a.song]

    # ---- cost, from the ledger, grouped by the model actually used ----------
    entries = [e for e in costreport.load_entries()
               if e.get("kind") == "model" and e.get("song") == a.song]
    by_model: dict[str, list] = {}
    for e in entries:
        by_model.setdefault(e.get("model", "?"), []).append(e)

    rows = []
    for label, model in LABEL_MODEL.items():
        # Quality must be restricted to the SAME song the cost is measured on.
        # Averaging a label's charts across every song it has, while billing only
        # this one, would compare a four-song average against a one-song bill.
        ch = [m for song, diffs in scored.items()
              if song == f"{title} [{label}]" for m in diffs.values()]
        led = by_model.get(model, [])
        if not ch and not led:
            continue

        def mean(key):
            v = [c[key] for c in ch if c.get(key) is not None]
            return statistics.fmean(v) if v else float("nan")

        def gate(key):
            v = [c["gates"][key] for c in ch if "gates" in c]
            return sum(v) / len(v) if v else float("nan")

        cost = sum(e["cost_usd"]["total"] for e in led)
        think = sum(e.get("thinking_tokens", 0) for e in led)
        rows.append({
            "label": label, "model": model, "charts": len(ch), "calls": len(led),
            "usd": cost, "usd_per_chart": cost / len(ch) if ch else float("nan"),
            "thinking": think,
            "latency_min": sum(e.get("latency_s", 0) for e in led) / 60.0,
            "flow_gate": gate("flow_ceiling"), "flow_max": mean("flow_cost_max"),
            "rho": mean("density_energy_spearman"),
            "density_gate": gate("density_energy"),
            "notes": mean("notes"), "jump": mean("jump_share"),
        })

    if not rows:
        print("no data yet — runs still in flight?")
        return

    L = [f"# Designer-model comparison — {a.song}", "",
         "Same pipeline, same audio, same DSP analysis, same scorer. Only the "
         "designer/critic MODEL differs. Cost is measured from the per-call "
         "ledger, not estimated from a price list.", "",
         f"Rates as of {pricing.PRICING_AS_OF} "
         f"(all three verified against the Vertex pricing page).", "",
         "| | " + " | ".join(r["model"] for r in rows) + " |",
         "|---|" + "---:|" * len(rows)]

    def row(lbl, key, fmt="{:.3f}"):
        L.append(f"| {lbl} | " + " | ".join(fmt.format(r[key]) for r in rows) + " |")

    L.append("| **— cost —** | " + " | ".join([""] * len(rows)) + " |")
    row("total $ (5 charts)", "usd", "${:.4f}")
    row("$ per chart", "usd_per_chart", "${:.4f}")
    row("model calls", "calls", "{:.0f}")
    row("thinking tokens", "thinking", "{:,.0f}")
    row("wall clock (min)", "latency_min", "{:.1f}")
    L.append("| **— is it DANCEABLE? —** | " + " | ".join([""] * len(rows)) + " |")
    row("flow gate pass", "flow_gate", "{:.0%}")
    row("flow_cost_max", "flow_max")
    L.append("| **— does it FOLLOW the song? —** | " + " | ".join([""] * len(rows)) + " |")
    row("density rho", "rho")
    row("density gate pass", "density_gate", "{:.0%}")
    L.append("| **— difficulty —** | " + " | ".join([""] * len(rows)) + " |")
    row("notes per chart", "notes", "{:.0f}")
    row("jump_share", "jump")

    base = next((r for r in rows if r["model"] == "gemini-3.5-flash"), None)
    if base and base["usd"]:
        L += ["", "## Cost relative to the incumbent (gemini-3.5-flash)", ""]
        for r in rows:
            if r["model"] == base["model"]:
                continue
            d = r["usd"] / base["usd"] - 1
            L.append(f"- **{r['model']}**: {d:+.0%} cost "
                     f"(${r['usd']:.4f} vs ${base['usd']:.4f}), "
                     f"rho {r['rho']:+.3f} vs {base['rho']:+.3f}, "
                     f"flow gate {r['flow_gate']:.0%} vs {base['flow_gate']:.0%}")

    md = "\n".join(L) + "\n"
    out = here.parents[1] / "docs" / "model-comparison.md"
    out.write_text(md)
    print(md)
    print(f"written -> {out}")


if __name__ == "__main__":
    main()
