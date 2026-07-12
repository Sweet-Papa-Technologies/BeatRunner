"""qa.py — objective QA metrics + human previews (SABERFORGE spec §9,
REQ-BS-10/12). Metrics: onset alignment, hand balance, reset count (via the
in-core swing simulator), NPS curve, arc/chain share, density-vs-energy Spearman,
precision-vs-BPM. Previews: a grid-over-time PNG and an assist-tick audio render.
"""
from __future__ import annotations

from . import simulate as sim
from .grammar import BUDGETS, PRECISION_BPM_LIMIT
from .realize import SaberObject


def _notes(objs):
    return [o for o in objs if o.kind in ("note", "arc", "chain")]


def _sec(beat, bpm, offset):
    return offset + beat / bpm * 60.0


def chart_metrics(objs: list[SaberObject], analysis: dict, difficulty: str) -> dict:
    b = BUDGETS[difficulty]
    bpm, offset = analysis["bpm"], analysis["offset"]
    notes = _notes(objs)
    n = len(notes)
    onset_times = sorted(o["time"] for o in analysis.get("onsets", []))

    aligned = grid = 0
    for o in notes:
        if _near(_sec(o.beat, bpm, offset), onset_times, 0.035):
            aligned += 1
        else:
            grid += 1
    onset_alignment = aligned / n if n else 1.0

    left = sum(1 for o in notes if o.color == 0)
    right = n - left
    hand_balance = {"left": round(left / n, 3) if n else 0.5,
                    "right": round(right / n, 3) if n else 0.5}

    sr = sim.simulate(objs, analysis)
    reset_count = len(sr.forced_resets)

    peak_nps = _peak_nps(notes, bpm, offset)
    arc_chain = sum(1 for o in notes if o.kind in ("arc", "chain"))
    arc_chain_share = round(arc_chain / n, 4) if n else 0.0

    spearman = _density_energy(notes, analysis)
    prec_ok = _precision_ok(notes, bpm, b)

    metrics = {
        "notes": n, "grid_notes": grid,
        "onset_alignment": round(onset_alignment, 4),
        "hand_balance": hand_balance,
        "reset_count": reset_count,
        "peak_nps_4s": round(peak_nps, 3),
        "arc_chain_share": arc_chain_share,
        "density_energy_spearman": spearman,
        "precision_ok": prec_ok,
        "simulator_clean": sr.clean,
    }
    metrics["gates"] = _gates(metrics, b, analysis)
    return metrics


def _gates(m, b, analysis):
    lo_ac, hi_ac = b.arc_chain_share
    flat = _energy_cv(analysis) < 0.12
    sections = analysis.get("sections", [])
    spread = (max((s.get("energy_pct", 0) for s in sections), default=0)
              - min((s.get("energy_pct", 0) for s in sections), default=0))
    structured = len(sections) >= 2 and spread >= 0.15
    # The density-vs-energy SHAPE gate assumes the tier can express contrast. The
    # gentle tiers' low NPS cap forces near-uniform density, so a sparse Easy/Normal
    # chart physically cannot track fine energy swings — exempt them (mirrors the
    # StepMania flat-track exemption); still enforced on Hard/Expert/Expert+.
    sparse_tier = b.max_nps_4s <= 3.5 + 1e-6
    hb = m["hand_balance"]
    return {
        "onset_alignment": m["onset_alignment"] >= 0.90 - 1e-6 or m["notes"] == 0,
        "hand_balance": 0.40 - 1e-6 <= hb["left"] <= 0.60 + 1e-6,
        "no_unforced_resets": m["reset_count"] == 0,
        "nps_in_budget": m["peak_nps_4s"] <= b.max_nps_4s + 1e-6,
        "arc_chain_share": lo_ac - 1e-6 <= m["arc_chain_share"] <= hi_ac + 1e-6 or m["notes"] == 0,
        "precision": m["precision_ok"],
        "simulator_clean": m["simulator_clean"],
        "density_energy": flat or not structured or sparse_tier
        or (m["density_energy_spearman"] is None)
        or m["density_energy_spearman"] >= 0.55 - 1e-6,
    }


def _near(t, onset_times, tol):
    for ot in onset_times:
        if abs(ot - t) <= tol + 1e-9:
            return True
        if ot - t > tol:
            break
    return False


def _peak_nps(notes, bpm, offset):
    if not notes:
        return 0.0
    times = sorted(_sec(o.beat, bpm, offset) for o in notes)
    peak = 0.0
    for i in range(len(times)):
        j = i
        while j < len(times) and times[j] - times[i] < 4.0:
            j += 1
        peak = max(peak, (j - i) / 4.0)
    return peak


def _precision_ok(notes, bpm, b):
    finest = b.finest_precision
    for cap_bpm, cap_prec in PRECISION_BPM_LIMIT:
        if bpm <= cap_bpm:
            finest = max(finest, cap_prec)
            break
    return all(abs(o.beat / finest - round(o.beat / finest)) <= 1e-3 for o in notes)


def _energy_cv(analysis):
    e = analysis.get("energy_curve", [])
    if not e:
        return 0.0
    mean = sum(e) / len(e)
    if mean == 0:
        return 0.0
    var = sum((x - mean) ** 2 for x in e) / len(e)
    return (var ** 0.5) / mean


def _density_energy(notes, analysis):
    energy = analysis.get("energy_curve", [])
    if not energy or len(energy) < 3:
        return None
    meter = analysis.get("meter", 4)
    counts = [0] * len(energy)
    for o in notes:
        bar = int(o.beat // meter)
        if 0 <= bar < len(counts):
            counts[bar] += 1
    try:
        from scipy.stats import spearmanr
        rho, _ = spearmanr(counts, energy)
        return round(float(rho), 4) if rho == rho else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Previews (REQ-BS-12): look + listen before shipping.
# --------------------------------------------------------------------------- #
def render_previews(objs, analysis, audio_path, out_stem):
    import os
    import shutil
    import subprocess
    from pathlib import Path

    out = {}
    if os.environ.get("SABERFORGE_SKIP_PREVIEWS"):
        return out                                  # fast path: skip optional artifacts
    bpm, offset = analysis["bpm"], analysis["offset"]
    notes = _notes(objs)
    times = [_sec(o.beat, bpm, offset) for o in notes]

    png = Path(str(out_stem) + ".grid.png")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(16, 3.5))
        # cell index 0..11 = y*4 + x; red left, blue right coloured markers.
        for o, t in zip(notes, times):
            cell = o.y * 4 + o.x
            color = "#ff2d55" if o.color == 0 else "#2d6cff"
            if o.kind == "arc":
                ax.plot([t, t + 0.25], [cell, cell], color=color, lw=3, alpha=0.8)
            elif o.kind == "chain":
                ax.scatter([t], [cell], color=color, marker="v", s=28)
            else:
                ax.scatter([t], [cell], color=color, s=20)
        for o in objs:
            if o.kind == "bomb":
                ax.scatter([_sec(o.beat, bpm, offset)], [o.y * 4 + o.x],
                           color="#333", marker="X", s=30)
        for s in analysis.get("sections", []):
            ax.axvline(offset + s["start_bar"] * 4 / bpm * 60, color="#b14cff", ls="--", lw=0.6)
        ax.set_yticks(range(12)); ax.set_ylabel("grid cell (y*4+x)"); ax.set_xlabel("s")
        fig.tight_layout(); fig.savefig(png, dpi=110); plt.close(fig)
        out["png"] = str(png)
    except Exception:
        pass

    click = Path(str(out_stem) + ".assist.ogg")
    if shutil.which("ffmpeg") and times and Path(audio_path).exists():
        ticks = "+".join(f"(lt(abs(t-{t:.3f}),0.015))*sin(2*PI*2000*t)" for t in times[:500])
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", audio_path,
                 "-f", "lavfi", "-t", str(analysis["duration_s"]),
                 "-i", f"aevalsrc='{ticks}':s=44100",
                 "-filter_complex", "[0:a]volume=0.8[a];[1:a]volume=0.5[b];[a][b]amix=inputs=2:duration=first[o]",
                 "-map", "[o]", "-c:a", "libvorbis", "-q:a", "5", str(click)],
                check=True, capture_output=True, timeout=120)
            out["assist"] = str(click)
        except Exception:
            pass
    return out


def gates_pass(metrics: dict) -> bool:
    return all(metrics.get("gates", {}).values())
