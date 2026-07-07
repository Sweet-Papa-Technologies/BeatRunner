"""qa.py — objective QA metrics + critic + previews (STEPFORGE §9,
REQ-SM-12/13/14)."""
from __future__ import annotations

from . import footflow as ff
from .grammar import BUDGETS, PANELS
from .quantize import Placement


def chart_metrics(placements: list[Placement], analysis: dict, difficulty: str) -> dict:
    b = BUDGETS[difficulty]
    bpm, offset = analysis["bpm"], analysis["offset"]
    n = len(placements)
    onset_times = sorted(o["time"] for o in analysis.get("onsets", []))

    aligned = grid = 0
    for p in placements:
        t = offset + p.beat / bpm * 60
        if _near(t, onset_times, 0.035):
            aligned += 1
        else:
            grid += 1
    onset_alignment = aligned / n if n else 1.0

    # panel balance (each panel 18-32%)
    counts = [0, 0, 0, 0]
    for p in placements:
        for c in p.panels:
            counts[c] += 1
    total_cells = sum(counts) or 1
    balance = {PANELS[i]: round(counts[i] / total_cells, 3) for i in range(4)}

    holds = sum(1 for p in placements if p.hold_beats)
    jumps = sum(1 for p in placements if len(p.panels) > 1)

    # foot-flow cost distribution (re-score the realized chart)
    max_cost, mean_cost = _flow_costs(placements, b)

    # density vs energy (per-bar) Spearman
    spearman = _density_energy(placements, analysis)

    return {
        "notes": n,
        "onset_alignment": round(onset_alignment, 4),
        "grid_notes": grid,
        "panel_balance": balance,
        "hold_share": round(holds / n, 4) if n else 0.0,
        "jump_share": round(jumps / n, 4) if n else 0.0,
        "flow_cost_max": round(max_cost, 2),
        "flow_cost_mean": round(mean_cost, 2),
        "density_energy_spearman": spearman,
        "gates": _gates(onset_alignment, balance, holds / n if n else 0, b, max_cost, spearman, analysis),
    }


def _gates(align, balance, hold_share, b, max_cost, spearman, analysis):
    lo_h, hi_h = b.hold_share
    flat = analysis.get("energy_cv", 0.0) < config_cv()
    # hold-share only applies if the music actually offers sustains usable at this
    # difficulty (long enough, on-grid) — else there's nothing to hold.
    usable = _usable_sustains(analysis, b)
    # section-structure: the density-vs-energy gate needs >=2 sections with real
    # energy spread; a uniform loop can't have density "follow" a flat curve.
    sections = analysis.get("sections", [])
    spread = (max((s.get("energy_pct", 0) for s in sections), default=0)
              - min((s.get("energy_pct", 0) for s in sections), default=0))
    structured = len(sections) >= 2 and spread >= 0.15
    return {
        "onset_alignment": align >= 0.90 - 1e-6,
        "panel_balance": all(0.15 - 1e-6 <= v <= 0.35 + 1e-6 for v in balance.values()),
        "hold_share": (lo_h - 1e-6 <= hold_share <= hi_h + 1e-6) or usable == 0,
        "flow_ceiling": max_cost < ff.DOUBLE_STEP + ff.JACK + 1e-6,     # no forbidden-tier transition
        "density_energy": flat or not structured or (spearman is None) or spearman >= 0.55 - 1e-6,
    }


def _usable_sustains(analysis, b) -> int:
    lo = b.hold_len_beats[0]
    return sum(1 for o in analysis.get("onsets", [])
               if o.get("sustain") and o.get("sustain_beats", 0) >= lo - 1.0
               and abs(o["nearest_beat"] - round(o["nearest_beat"] / b.finest_subdiv) * b.finest_subdiv) <= 1e-3
               and abs(o.get("snap_error_ms", 0)) <= 35.0)


def config_cv():
    from ... import config
    return getattr(config, "DENSITY_GATE_MIN_CV", 0.12)


def _near(t, onset_times, tol):
    for ot in onset_times:
        if abs(ot - t) <= tol + 1e-9:
            return True
        if ot - t > tol:
            break
    return False


def _flow_costs(placements, b):
    if len(placements) < 2:
        return 0.0, 0.0
    state = ff.REST_STATE
    costs = []
    for p in placements:
        if len(p.panels) > 1:
            c, state = ff.jump_cost(state, p.panels[0], p.panels[1], b)
        else:
            foot = p.meta.get("foot", ff.LEFT)
            c, state = ff.step(state, foot, p.panels[0], b,
                              p.meta.get("movement", "static"), 0.0)
        costs.append(max(0.0, c))
    return max(costs), sum(costs) / len(costs)


def render_previews(placements, analysis, audio_path, out_stem):
    """REQ-SM-14 human-auditable previews: a notefield PNG (matplotlib, if
    available) + an assist-tick render (ffmpeg) — the fastest ear-check that the
    steps land on the music."""
    import shutil
    import subprocess
    from pathlib import Path
    out = {}
    bpm, offset = analysis["bpm"], analysis["offset"]
    times = [offset + p.beat / bpm * 60 for p in placements]

    png = Path(str(out_stem) + ".notefield.png")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(16, 3))
        for p, t in zip(placements, times):
            for c in p.panels:
                if p.hold_beats:
                    ax.plot([t, t + p.hold_beats / bpm * 60], [c, c], color="#ff2d95", lw=4)
                else:
                    ax.scatter([t], [c], color="#2de2e6", s=16)
        for s in analysis.get("sections", []):
            ax.axvline(offset + s["start_bar"] * 4 / bpm * 60, color="#b14cff", ls="--", lw=0.6)
        ax.set_yticks(range(4)); ax.set_yticklabels(list(PANELS)); ax.set_xlabel("s")
        fig.tight_layout(); fig.savefig(png, dpi=110); plt.close(fig)
        out["png"] = str(png)
    except Exception:
        pass

    click = Path(str(out_stem) + ".assist.ogg")
    if shutil.which("ffmpeg") and times:
        ticks = "+".join(f"(lt(abs(t-{t:.3f}),0.015))*sin(2*PI*2000*t)" for t in times[:500])
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", audio_path,
                 "-f", "lavfi", "-t", str(analysis["duration_s"]), "-i", f"aevalsrc='{ticks}':s=44100",
                 "-filter_complex", "[0:a]volume=0.8[a];[1:a]volume=0.5[b];[a][b]amix=inputs=2:duration=first[o]",
                 "-map", "[o]", "-c:a", "libvorbis", "-q:a", "5", str(click)],
                check=True, capture_output=True, timeout=120)
            out["assist"] = str(click)
        except Exception:
            pass
    return out


def _density_energy(placements, analysis):
    energy = analysis.get("energy_curve", [])
    if not energy or len(energy) < 3:
        return None
    meter = analysis.get("meter", 4)
    counts = [0] * len(energy)
    for p in placements:
        bar = int(p.beat // meter)
        if 0 <= bar < len(counts):
            counts[bar] += 1
    try:
        from scipy.stats import spearmanr
        rho, _ = spearmanr(counts, energy)
        return round(float(rho), 4) if rho == rho else None
    except Exception:
        return None
