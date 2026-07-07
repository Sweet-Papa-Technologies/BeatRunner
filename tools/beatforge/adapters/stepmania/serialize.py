"""serialize.py — write .ssc/.sm via garcia/simfile and package the song folder
(STEPFORGE §7, REQ-SM-07/08). Never hand-formats the file; simfile owns the
grammar, we own the timing/metadata + note objects."""
from __future__ import annotations

import shutil
from pathlib import Path

import simfile
from simfile.sm import SMChart, SMSimfile
from simfile.ssc import SSCChart, SSCSimfile

from .grammar import BUDGETS
from .quantize import to_simfile_notes


def _sample_start(analysis: dict) -> float:
    bpm, offset = analysis["bpm"], analysis["offset"]
    best = max(analysis.get("sections", []),
               key=lambda s: s.get("energy_pct", 0), default=None)
    if not best:
        return 0.0
    return round(offset + best["start_bar"] * 4 / bpm * 60, 3)


def build_simfile(track_meta: dict, analysis: dict, charts_by_diff: dict,
                  ssc: bool = True, banner: str | None = None, background: str | None = None):
    """charts_by_diff: {difficulty_key: (meter, [Placement, ...])}."""
    sf = SSCSimfile.blank() if ssc else SMSimfile.blank()
    sf.title = track_meta["title"]
    sf.artist = track_meta["artist"]
    sf.music = track_meta["music"]
    sf.offset = f"{-round(analysis['offset'], 3):.3f}"      # #OFFSET = -(beat0 time)
    sf.bpms = f"0.000={analysis['bpm']:.3f}"
    sf.samplestart = f"{_sample_start(analysis):.3f}"
    sf.samplelength = "12.000"
    sf.selectable = "YES"
    sf.credit = "STEPFORGE"
    if banner:
        sf.banner = banner
    if background:
        sf.background = background

    for key, (meter, placements) in charts_by_diff.items():
        budget = BUDGETS[key]
        note_str = str(to_simfile_notes(placements, budget.finest_subdiv))
        chart = (SSCChart if ssc else SMChart).blank()
        chart.stepstype = "dance-single"
        chart.difficulty = budget.sm_difficulty
        chart.meter = str(meter)
        chart.description = "STEPFORGE"
        if ssc:
            chart.credit = "STEPFORGE"
        chart.notes = note_str
        sf.charts.append(chart)
    return sf


def write_song_folder(track_meta: dict, analysis: dict, charts_by_diff: dict,
                      audio_src: str, out_dir: Path, formats=("ssc",)) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Path(track_meta["music"]).stem
    # pick up song art if present in the folder (assetforge-generated)
    banner = next((p.name for p in (out_dir / f"{base}-banner.png",
                                    out_dir / "banner.png") if p.exists()), None)
    background = next((p.name for p in (out_dir / f"{base}-bg.png",
                                       out_dir / "background.png") if p.exists()), None)
    written = {}
    for fmt in formats:
        sf = build_simfile(track_meta, analysis, charts_by_diff, ssc=(fmt == "ssc"),
                          banner=banner, background=background)
        path = out_dir / f"{base}.{fmt}"
        path.write_text(str(sf))
        # round-trip referee: simfile must re-open its own output (REQ-SM-11)
        with open(path) as fh:
            reopened = simfile.load(fh)
        assert len(reopened.charts) == len(charts_by_diff), "chart count changed on reload"
        written[fmt] = str(path)
    audio_dst = out_dir / track_meta["music"]
    if Path(audio_src).resolve() != audio_dst.resolve():
        shutil.copyfile(audio_src, audio_dst)
    written["audio"] = str(audio_dst)
    return written
