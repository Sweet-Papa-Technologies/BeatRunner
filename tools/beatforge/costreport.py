"""costreport.py — roll per-call ledgers up into an answerable bill
(REQ-R2-COST-03).

`beatforge cost-report` reads every `build/cost/<song>/cost_ledger.jsonl` and
emits markdown + JSON covering: $/song, $/chart, $ by stage, the token breakdown
split text/audio/cached/thinking/out, and the five most expensive individual
calls with the byte size of the prompt that produced them.

The rollup deliberately computes more than the report renders, because the
autopsy (REQ-R2-COST-04) has to answer six specific hypotheses with numbers, and
a report that can't produce those numbers just moves the hand-waving downstream.
So `aggregate()` also returns: the calls-per-chart distribution (not the mean),
every distinct model string actually seen, thinking-token spend, and the
Vertex-vs-compute split.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from . import config, ledger, pricing

# Stages the brief names explicitly; anything else rolls into "other" but keeps
# its own line so a surprise stage is visible rather than absorbed.
KNOWN_STAGES = ("analysis", "designer", "critic", "reprompt")


def _cost(e: dict) -> float:
    return float((e.get("cost_usd") or {}).get("total", 0.0))


def aggregate(entries: list[dict]) -> dict:
    """Roll a flat entry list into the report structure. Pure — no I/O."""
    model_calls = [e for e in entries if e.get("kind") == "model"]
    compute = [e for e in entries if e.get("kind") == "compute"]

    songs = sorted({str(e["song"]) for e in entries if e.get("song")})
    # A "chart" is one (song, difficulty) pair that actually saw a model call.
    charts = {(e.get("song"), e.get("difficulty")) for e in model_calls
              if e.get("difficulty")}

    by_stage: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "usd": 0.0, "text_in": 0, "audio_in": 0, "out": 0,
                 "cached_in": 0, "thinking": 0, "latency_s": 0.0})
    for e in entries:
        s = e.get("stage") or "unattributed"
        if s not in KNOWN_STAGES and e.get("kind") == "model":
            s = s if s != "song" else "other"
        b = by_stage[s]
        b["calls"] += 1
        b["usd"] += _cost(e)
        b["latency_s"] += float(e.get("latency_s", 0.0) or 0.0)
        b["text_in"] += int(e.get("text_tokens", 0) or 0)
        b["audio_in"] += int(e.get("audio_tokens", 0) or 0)
        b["out"] += int(e.get("output_tokens", 0) or 0)
        b["cached_in"] += int(e.get("cached_tokens", 0) or 0)
        b["thinking"] += int(e.get("thinking_tokens", 0) or 0)

    tokens: dict[str, float] = {
        "text_in": sum(int(e.get("text_tokens", 0) or 0) for e in model_calls),
        "audio_in": sum(int(e.get("audio_tokens", 0) or 0) for e in model_calls),
        "cached_in": sum(int(e.get("cached_tokens", 0) or 0) for e in model_calls),
        "out": sum(int(e.get("output_tokens", 0) or 0) for e in model_calls),
        "thinking": sum(int(e.get("thinking_tokens", 0) or 0) for e in model_calls),
    }
    tokens["total_in"] = tokens["text_in"] + tokens["audio_in"] + tokens["cached_in"]
    total_in = tokens["total_in"] or 1
    tokens["audio_share_of_input"] = round(tokens["audio_in"] / total_in, 4)

    llm_usd = round(sum(_cost(e) for e in model_calls), 6)
    compute_usd = round(sum(_cost(e) for e in compute), 6)
    total_usd = round(llm_usd + compute_usd, 6)

    # Calls per chart — the DISTRIBUTION, per autopsy hypothesis #3. An average
    # of "2.3 calls" hides the chart that burned nine.
    per_chart = Counter((e.get("song"), e.get("difficulty")) for e in model_calls
                        if e.get("difficulty"))
    counts = sorted(per_chart.values())
    dist = {
        "n_charts": len(counts),
        "min": counts[0] if counts else 0,
        "median": statistics.median(counts) if counts else 0,
        "max": counts[-1] if counts else 0,
        "mean": round(statistics.fmean(counts), 2) if counts else 0.0,
        "histogram": dict(sorted(Counter(counts).items())),
    }

    # Every model string that actually went over the wire (hypothesis #4).
    models = Counter(e.get("model") for e in model_calls)
    unexpected = sorted(m for m in models if m and not str(m).startswith(config.GEMINI_MODEL)
                        and not str(m).startswith("lyria"))

    per_song: dict[str, dict] = {}
    for song in songs:
        se = [e for e in entries if e.get("song") == song]
        sc = {(x.get("difficulty")) for x in se
              if x.get("kind") == "model" and x.get("difficulty")}
        per_song[song] = {
            "usd": round(sum(_cost(e) for e in se), 6),
            "llm_usd": round(sum(_cost(e) for e in se if e.get("kind") == "model"), 6),
            "compute_usd": round(sum(_cost(e) for e in se if e.get("kind") == "compute"), 6),
            "model_calls": sum(1 for e in se if e.get("kind") == "model"),
            "charts": len(sc),
            "audio_tokens": sum(int(e.get("audio_tokens", 0) or 0) for e in se),
            "cache_hit_analysis": any(e.get("cache_hit") for e in se
                                      if e.get("kind") == "compute"),
        }

    top = sorted(model_calls, key=_cost, reverse=True)[:5]
    top_calls = [{
        "song": e.get("song"), "difficulty": e.get("difficulty"),
        "stage": e.get("stage"), "attempt": e.get("attempt"),
        "model": e.get("model"), "usd": round(_cost(e), 6),
        "prompt_bytes": e.get("prompt_bytes", 0),
        "audio_attached": e.get("audio_attached", False),
        "audio_tokens": e.get("audio_tokens", 0),
        "text_tokens": e.get("text_tokens", 0),
        "output_tokens": e.get("output_tokens", 0),
        "thinking_tokens": e.get("thinking_tokens", 0),
        "latency_s": e.get("latency_s"),
    } for e in top]

    n_songs = len(songs) or 1
    n_charts = len(charts) or 1
    return {
        "pricing_as_of": pricing.PRICING_AS_OF,
        "price_table": pricing.table_snapshot(),
        "unverified_rates": pricing.unverified_models(),
        "totals": {
            "usd": total_usd, "llm_usd": llm_usd, "compute_usd": compute_usd,
            "songs": len(songs), "charts": len(charts),
            "model_calls": len(model_calls), "compute_events": len(compute),
            "usd_per_song": round(total_usd / n_songs, 6),
            "usd_per_chart": round(total_usd / n_charts, 6),
            "compute_share": round(compute_usd / total_usd, 4) if total_usd else 0.0,
        },
        "by_stage": {k: {**v, "usd": round(v["usd"], 6),
                         "latency_s": round(v["latency_s"], 1)}
                     for k, v in sorted(by_stage.items(),
                                        key=lambda kv: -kv[1]["usd"])},
        "tokens": tokens,
        "calls_per_chart": dist,
        "models_seen": dict(models),
        "unexpected_models": unexpected,
        "per_song": per_song,
        "top_calls": top_calls,
        "errors": [{"song": e.get("song"), "stage": e.get("stage"),
                    "error": e.get("error")} for e in model_calls if e.get("error")],
        "modality_breakdown_missing": sum(
            1 for e in model_calls if not e.get("modality_breakdown_available")),
    }


def load_entries(song: str | None = None) -> list[dict]:
    paths = ([ledger.ledger_path(song)] if song else ledger.all_ledgers())
    out: list[dict] = []
    for p in paths:
        out.extend(ledger.read_ledger(p))
    return out


def render_markdown(r: dict) -> str:
    t = r["totals"]
    L: list[str] = []
    L.append("# beatforge cost report")
    L.append("")
    L.append(f"Price table as of **{r['pricing_as_of']}** "
             f"(`tools/beatforge/pricing.py`).")
    if r["unverified_rates"]:
        L.append("")
        L.append(f"> **Rates unverified:** {', '.join(r['unverified_rates'])}. "
                 f"Dollar figures below are directionally useful but must not be "
                 f"quoted externally until the rates are checked against the live "
                 f"pricing page and `verified=True` is set.")
    if r["modality_breakdown_missing"]:
        L.append("")
        L.append(f"> **{r['modality_breakdown_missing']} call(s)** returned no "
                 f"per-modality token breakdown; their audio tokens are folded into "
                 f"text and the audio share below is an UNDER-count.")
    L.append("")
    L.append("## Totals")
    L.append("")
    L.append("| metric | value |")
    L.append("|---|---:|")
    L.append(f"| total | ${t['usd']:.4f} |")
    L.append(f"| $/song | ${t['usd_per_song']:.4f} |")
    L.append(f"| $/chart | ${t['usd_per_chart']:.4f} |")
    L.append(f"| songs / charts | {t['songs']} / {t['charts']} |")
    L.append(f"| model calls | {t['model_calls']} |")
    L.append(f"| LLM vs compute | ${t['llm_usd']:.4f} vs ${t['compute_usd']:.4f} "
             f"({t['compute_share']:.1%} compute) |")

    L.append("")
    L.append("## $ by stage")
    L.append("")
    L.append("| stage | calls | $ | share | text-in | audio-in | out | thinking |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, b in r["by_stage"].items():
        share = b["usd"] / t["usd"] if t["usd"] else 0.0
        L.append(f"| {name} | {b['calls']} | ${b['usd']:.4f} | {share:.1%} | "
                 f"{b['text_in']:,} | {b['audio_in']:,} | {b['out']:,} | "
                 f"{b['thinking']:,} |")

    tok = r["tokens"]
    L.append("")
    L.append("## Token breakdown")
    L.append("")
    L.append("| kind | tokens |")
    L.append("|---|---:|")
    for k in ("text_in", "audio_in", "cached_in", "out", "thinking"):
        L.append(f"| {k} | {tok[k]:,} |")
    L.append(f"| **audio share of input** | **{tok['audio_share_of_input']:.1%}** |")

    d = r["calls_per_chart"]
    L.append("")
    L.append("## Model calls per chart (distribution, not average)")
    L.append("")
    L.append(f"min {d['min']} / median {d['median']} / mean {d['mean']} / "
             f"max {d['max']} over {d['n_charts']} charts")
    L.append("")
    L.append("| calls | charts |")
    L.append("|---:|---:|")
    for calls, n in d["histogram"].items():
        L.append(f"| {calls} | {n} |")

    L.append("")
    L.append("## Models actually used")
    L.append("")
    for m, n in sorted(r["models_seen"].items(), key=lambda kv: -kv[1]):
        L.append(f"- `{m}` — {n} call(s)")
    if r["unexpected_models"]:
        L.append("")
        L.append(f"> **Model mismatch:** {', '.join(r['unexpected_models'])} was used "
                 f"but `config.GEMINI_MODEL` is `{config.GEMINI_MODEL}`.")

    L.append("")
    L.append("## Top 5 most expensive calls")
    L.append("")
    L.append("| $ | song | diff | stage | att | prompt bytes | audio tok | text tok | out |")
    L.append("|---:|---|---|---|---:|---:|---:|---:|---:|")
    for c in r["top_calls"]:
        L.append(f"| ${c['usd']:.4f} | {c['song']} | {c['difficulty'] or '-'} | "
                 f"{c['stage']} | {c['attempt'] or '-'} | {c['prompt_bytes']:,} | "
                 f"{c['audio_tokens']:,} | {c['text_tokens']:,} | {c['output_tokens']:,} |")

    L.append("")
    L.append("## Per song")
    L.append("")
    L.append("| song | $ | charts | calls | audio tok | analysis cached |")
    L.append("|---|---:|---:|---:|---:|:--:|")
    for song, s in sorted(r["per_song"].items(), key=lambda kv: -kv[1]["usd"]):
        L.append(f"| {song} | ${s['usd']:.4f} | {s['charts']} | {s['model_calls']} | "
                 f"{s['audio_tokens']:,} | {'yes' if s['cache_hit_analysis'] else 'no'} |")

    if r["errors"]:
        L.append("")
        L.append("## Failed calls (still billed)")
        L.append("")
        for e in r["errors"]:
            L.append(f"- {e['song']}/{e['stage']}: {e['error']}")
    L.append("")
    return "\n".join(L)


def write_report(song: str | None = None, out_dir: Path | None = None) -> dict:
    entries = load_entries(song)
    rollup = aggregate(entries)
    out_dir = out_dir or config.COST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cost-report.json").write_text(json.dumps(rollup, indent=2))
    (out_dir / "cost-report.md").write_text(render_markdown(rollup))
    return rollup
