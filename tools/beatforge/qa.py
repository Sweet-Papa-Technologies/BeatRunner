"""qa.py — Workstream D objective metrics, gates, and previews (REQ-QA-01/02/05).

All deterministic. The metrics feed both the ship decision and the machine-
readable violation report that drives the re-prompt loop (REQ-QA-03).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import config
from .validate import ValidationResult, _t


# --------------------------------------------------------------------------- #
# Metrics (REQ-QA-01)
# --------------------------------------------------------------------------- #
def compute_metrics(vr: ValidationResult, analysis: dict, difficulty: str) -> dict:
    budget = config.BUDGETS[difficulty]
    bpm, offset = analysis["bpm"], analysis["offset"]
    events = vr.events
    n = len(events)
    onset_times = sorted(o["time"] for o in analysis.get("onsets", []))

    # onset alignment: onset-ref events within ±35ms of a detected onset.
    onset_evts = [e for e in vr.resolved if e.is_onset]
    grid_evts = [e for e in vr.resolved if not e.is_onset]
    aligned = sum(1 for e in onset_evts
                  if _near_onset(_t(e.beat, bpm, offset), onset_times))
    onset_alignment = aligned / len(onset_evts) if onset_evts else 1.0

    # lane balance
    lanes = {t: 0 for t in ("GAP", "BAR", "NOTE")}
    for e in events:
        lanes[e["type"]] += 1
    lane_share = {k: (v / n if n else 0.0) for k, v in lanes.items()}

    # hold share
    holds = sum(1 for e in events if e.get("dur"))
    hold_share = holds / n if n else 0.0

    # per-bar event count + NPS curve
    per_bar_counts, per_bar_energy = _per_bar(events, analysis, bpm, offset)
    peak_nps, peak_window = _peak_nps(events, bpm, offset)

    metrics = {
        "difficulty": difficulty,
        "event_count": n,
        "onset_events": len(onset_evts),
        "grid_events": len(grid_evts),
        "onset_alignment": round(onset_alignment, 4),
        "lane_share": {k: round(v, 4) for k, v in lane_share.items()},
        "hold_share": round(hold_share, 4),
        "sustain_available": analysis.get("sustain_available", 0),
        "peak_nps_4s": round(peak_nps, 3),
        "peak_nps_window_s": [round(x, 2) for x in peak_window],
        "repaired": vr.original_count - n,
        "repaired_fraction": round((vr.original_count - n) / vr.original_count, 4) if vr.original_count else 0.0,
        "dropped": {"window": vr.dropped_window, "grid": vr.dropped_grid, "snap": vr.dropped_snap},
        "per_bar_counts": per_bar_counts,
    }
    metrics["density_energy"] = _density_energy(per_bar_counts, per_bar_energy,
                                               events, analysis, bpm, offset, peak_window)
    metrics["gates"] = _evaluate_gates(metrics, budget, analysis)
    return metrics


def _near_onset(t: float, onset_times: list[float], tol: float | None = None) -> bool:
    tol = tol if tol is not None else config.ONSET_SNAP_MAX_MS / 1000.0
    # binary search would be faster; linear is fine for a few hundred onsets
    for ot in onset_times:
        if abs(ot - t) <= tol + 1e-6:
            return True
        if ot - t > tol:
            break
    return False


def _per_bar(events, analysis, bpm, offset):
    meter = analysis.get("meter", 4)
    bar_beats = meter
    energy = analysis.get("energy_curve", [])
    n_bars = len(energy) if energy else max(1, int(analysis["duration_s"] * bpm / 60 / bar_beats))
    counts = [0] * n_bars
    for e in events:
        b = int((e["beat"]) // bar_beats)
        if 0 <= b < n_bars:
            counts[b] += 1
    return counts, energy[:n_bars] if energy else [0.0] * n_bars


def _peak_nps(events, bpm, offset, win=4.0):
    if not events:
        return 0.0, (0.0, win)
    times = sorted(_t(e["beat"], bpm, offset) for e in events)
    best, best_win = 0.0, (0.0, win)
    for i in range(len(times)):
        j = i
        while j < len(times) and times[j] - times[i] < win:
            j += 1
        nps = (j - i) / win
        if nps > best:
            best, best_win = nps, (times[i], times[i] + win)
    return best, best_win


def _density_energy(counts, energy, events, analysis, bpm, offset, peak_window):
    """REQ-QA-02: (a) Spearman(counts, energy) >= 0.55, (b) peak NPS window falls
    in the highest-energy section, (c) some low-energy section breathes."""
    result = {}
    try:
        from scipy.stats import spearmanr
        if len(counts) >= 3 and any(counts) and any(energy):
            rho, _ = spearmanr(counts, energy)
            result["spearman"] = round(float(rho), 4) if rho == rho else 0.0
        else:
            result["spearman"] = 0.0
    except Exception:
        result["spearman"] = 0.0

    # (b) peak NPS window within the highest-energy section
    sections = analysis.get("sections", [])
    result["peak_in_top_section"] = _peak_in_top_energy_section(
        sections, analysis, bpm, offset, peak_window)

    # (c) breathing: a section below the 30th energy pct with density below median
    result["breathes"] = _breathes(counts, energy, sections)
    return result


def _peak_in_top_energy_section(sections, analysis, bpm, offset, peak_window):
    if not sections:
        return False
    top = max(sections, key=lambda s: s.get("energy_pct", 0))
    meter = analysis.get("meter", 4)
    t0 = _t(top["start_bar"] * meter, bpm, offset)
    t1 = _t(top["end_bar"] * meter, bpm, offset)
    center = (peak_window[0] + peak_window[1]) / 2
    return t0 - 1e-6 <= center <= t1 + 1e-6


def _breathes(counts, energy, sections):
    if not sections or not counts or not energy:
        return False
    median = sorted(counts)[len(counts) // 2]
    e_sorted = sorted(energy)
    p30 = e_sorted[max(0, int(0.30 * len(e_sorted)) - 1)]
    for s in sections:
        s0, s1 = s["start_bar"], s["end_bar"]
        seg_e = energy[s0:s1]
        seg_c = counts[s0:s1]
        if seg_e and sum(seg_e) / len(seg_e) <= p30:
            if seg_c and sum(seg_c) / len(seg_c) < median:
                return True
    return False


# --------------------------------------------------------------------------- #
# Gate evaluation + violation report (REQ-QA-01/02/03)
# --------------------------------------------------------------------------- #
def _evaluate_gates(metrics: dict, budget, analysis: dict) -> dict:
    lo_lane, hi_lane = config.LANE_BALANCE_RANGE
    lane_ok = all(lo_lane - 1e-6 <= v <= hi_lane + 1e-6
                  for v in metrics["lane_share"].values())
    # hold share: within band, OR the music offers no sustain candidate that can
    # legally become a hold at this difficulty (e.g. only ~1-beat pads on casual).
    from .validate import usable_sustain_count
    lo_h, hi_h = budget.hold_share
    hs = metrics["hold_share"]
    usable = usable_sustain_count(analysis, budget.name)
    metrics["usable_sustains"] = usable
    hold_ok = (lo_h - 1e-6 <= hs <= hi_h + 1e-6) or usable == 0
    de = metrics["density_energy"]
    # Flat tracks (low bar-level energy variance) are exempt from ALL density-SHAPE
    # gates (see config note). The Spearman gate rides on the per-BAR energy curve
    # so it still applies to any non-flat track. The peak-in-drop and breathes
    # gates are SECTION-level, so they only make sense when the track actually has
    # sections with distinct energy (an intro→drop shape). A steady groove that
    # oscillates loud/quiet every bar has high energy_cv but only one uniform
    # section — there is no quiet SECTION to breathe, so those two gates exempt.
    flat = analysis.get("energy_cv", 0.0) < config.DENSITY_GATE_MIN_CV
    sections = analysis.get("sections", [])
    if sections:
        spread = max(s.get("energy_pct", 0) for s in sections) - min(s.get("energy_pct", 0) for s in sections)
    else:
        spread = 0.0
    section_structured = len(sections) >= 2 and spread >= config.SECTION_STRUCTURE_MIN_SPREAD
    metrics["flat_track_exempt"] = flat
    metrics["section_structured"] = section_structured
    return {
        "onset_alignment": metrics["onset_alignment"] >= budget.onset_align_min - 1e-6,
        "lane_balance": lane_ok,
        "hold_share": hold_ok,
        "nps": metrics["peak_nps_4s"] <= budget.max_nps_4s + 1e-6,
        "repaired": metrics["repaired_fraction"] <= config.MAX_REPAIR_FRACTION + 1e-6,
        "density_spearman": flat or de["spearman"] >= config.DENSITY_ENERGY_SPEARMAN_MIN - 1e-6,
        "density_peak": flat or not section_structured or de["peak_in_top_section"],
        "density_breathes": flat or not section_structured or de["breathes"],
    }


def gates_pass(metrics: dict) -> bool:
    return all(metrics["gates"].values())


def violation_report(metrics: dict, difficulty: str) -> str:
    """Machine-readable failure summary fed back to the designer (REQ-QA-03)."""
    budget = config.BUDGETS[difficulty]
    g = metrics["gates"]
    lines = []
    if not g["onset_alignment"]:
        lines.append(f"onset alignment {metrics['onset_alignment']:.0%} below "
                     f"{budget.onset_align_min:.0%} floor — place notes on detected onsets, not bare grid.")
    if not g["lane_balance"]:
        shares = ", ".join(f"{k}={v:.0%}" for k, v in metrics["lane_share"].items())
        lines.append(f"lane balance out of 22-45% band ({shares}) — spread notes across lanes.")
    if not g["hold_share"]:
        lo, hi = budget.hold_share
        lines.append(f"hold share {metrics['hold_share']:.0%} outside {lo:.0%}-{hi:.0%} "
                     f"(sustain candidates available: {metrics['sustain_available']}).")
    if not g["nps"]:
        w = metrics["peak_nps_window_s"]
        lines.append(f"peak NPS {metrics['peak_nps_4s']:.1f} in window {w[0]}-{w[1]}s "
                     f"exceeds {budget.max_nps_4s} — thin out that burst.")
    if not g["repaired"]:
        lines.append(f"{metrics['repaired_fraction']:.0%} of events were repaired away "
                     f"(>{config.MAX_REPAIR_FRACTION:.0%}) — too many budget violations.")
    if not g["density_spearman"]:
        lines.append(f"density/energy correlation {metrics['density_energy']['spearman']:.2f} "
                     f"below {config.DENSITY_ENERGY_SPEARMAN_MIN} — make density follow the energy curve.")
    if not g["density_peak"]:
        lines.append("chart's densest 4s is not in the highest-energy section — "
                     "put the peak intensity on the drop.")
    if not g["density_breathes"]:
        lines.append("no low-energy section breathes — thin out a break/quiet section.")
    return "; ".join(lines) if lines else "all gates pass"


# --------------------------------------------------------------------------- #
# Previews (REQ-QA-05): PNG timeline + click-track (best-effort)
# --------------------------------------------------------------------------- #
def render_previews(track_file: str, audio_path: str, beatmap: dict, analysis: dict,
                    out_stem: Path) -> dict:
    # NB: out_stem is like ".../overdrive_pulse.casual" — do NOT use with_suffix
    # (it would strip ".casual"). Build the preview names explicitly so each
    # difficulty gets <track>.<difficulty>.preview.{png,ogg} (REQ-QA-05).
    out = {}
    png = Path(str(out_stem) + ".preview.png")
    if _render_png(beatmap, analysis, png):
        out["png"] = str(png)
    click = Path(str(out_stem) + ".preview.ogg")
    if _render_click(audio_path, beatmap, analysis, click):
        out["click"] = str(click)
    return out


def _render_png(beatmap, analysis, path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    bpm, offset = analysis["bpm"], analysis["offset"]
    lane_y = {"GAP": 0, "BAR": 1, "NOTE": 2}
    fig, ax = plt.subplots(figsize=(14, 3))
    # onsets as light ticks
    for o in analysis.get("onsets", []):
        ax.axvline(o["time"], color="#dddddd", lw=0.4, zorder=0)
    for e in beatmap["events"]:
        t = offset + e["beat"] / bpm * 60
        y = lane_y[e["type"]]
        if e.get("dur"):
            ax.plot([t, t + e["dur"] / bpm * 60], [y, y], color="#ff2d95", lw=4, zorder=3)
        else:
            ax.scatter([t], [y], color="#2de2e6", s=20, zorder=4)
    for s in analysis.get("sections", []):
        ax.axvline(offset + s["start_bar"] * analysis.get("meter", 4) / bpm * 60,
                   color="#b14cff", ls="--", lw=0.8)
    ax.set_yticks([0, 1, 2]); ax.set_yticklabels(["GAP", "BAR", "NOTE"])
    ax.set_xlabel("time (s)"); ax.set_title(path.stem)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)
    return True


def _render_click(audio_path, beatmap, analysis, path: Path) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    bpm, offset = analysis["bpm"], analysis["offset"]
    times = [offset + e["beat"] / bpm * 60 for e in beatmap["events"]]
    if not times:
        return False
    # build a click bed with sine bursts, then mix with the source at -6dB
    # aevalsrc per-tick is heavy; instead synth a click track via a filter graph.
    ticks = "+".join(
        f"(lt(abs(t-{t:.3f}),0.02))*sin(2*PI*1500*t)" for t in times[:400])
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", audio_path,
             "-f", "lavfi", "-t", str(analysis["duration_s"]),
             "-i", f"aevalsrc='{ticks}':s=44100",
             "-filter_complex", "[0:a]volume=0.8[a];[1:a]volume=0.6[b];[a][b]amix=inputs=2:duration=first[out]",
             "-map", "[out]", "-c:a", "libvorbis", "-q:a", "5", str(path)],
            check=True, capture_output=True, timeout=120)
        return path.exists()
    except Exception:
        return False
