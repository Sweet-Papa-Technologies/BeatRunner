"""sm_parse.py — read ANY StepMania .sm/.ssc into beatforge's internal note model.

This is what makes the benchmark fair. beatforge can already score a chart on
objective axes (onset alignment, panel balance, hold share, density-vs-energy, and
the foot-flow comfort cost). Those scorers take `list[Placement]`. So if we can
turn a *foreign* simfile — one produced by DDC, StepCOVNet, whatever — into the
same `Placement` list, we can run it through the exact same gates and critic that
judge our own charts, and nobody gets a home-field advantage.

Deliberately tolerant: other generators emit simfiles with quirks (missing radar
values, `#NOTES:` bodies with comments, unmatched hold tails). Anything we can't
make sense of is dropped with a warning rather than raising, because a benchmark
that dies on one weird file is useless.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from beatforge.adapters.stepmania.quantize import Placement   # noqa: E402

TAP, HOLD_HEAD, TAIL, ROLL_HEAD, MINE = "1", "2", "3", "4", "M"


@dataclass
class Chart:
    difficulty: str          # StepMania slot: Beginner/Easy/Medium/Hard/Challenge
    meter: int
    steps_type: str
    placements: list[Placement]

    @property
    def notes(self) -> int:
        return len(self.placements)


def _headers(text: str) -> dict[str, str]:
    return {m.group(1).upper(): m.group(2).strip()
            for m in re.finditer(r"#([A-Z_]+):([^;]*);", text, re.I)}


def bpm_map(text: str) -> list[tuple[float, float]]:
    """The full #BPMS map as [(beat, bpm), ...], sorted. Not just the first entry:
    some generators (Autostepper-Python) emit a real multi-segment tempo map, and
    collapsing it to one value would misplace every note after the first change."""
    h = _headers(text)
    out: list[tuple[float, float]] = []
    for pair in h.get("BPMS", "").split(","):
        if "=" not in pair:
            continue
        b, v = pair.split("=", 1)
        try:
            out.append((float(b), float(v)))
        except ValueError:
            continue
    return sorted(out) or [(0.0, 120.0)]


def bpm_offset(text: str) -> tuple[float, float]:
    """Returns (first bpm, offset-as-beatforge-means-it). beatforge's `offset` is the
    TIME OF BEAT 0; StepMania's #OFFSET is the negative of that, so flip the sign."""
    return bpm_map(text)[0][1], -float(_headers(text).get("OFFSET", "0") or 0)


def beat_to_time(beat: float, bpms: list[tuple[float, float]], offset: float) -> float:
    """Absolute seconds for a beat, walking the tempo map.

    This is THE function that makes cross-generator scoring honest. Every simfile's
    beat numbers are relative to its OWN tempo map — AutoStepper called one of these
    songs 130 BPM where our DSP measures 173.5. Converting its beats with our BPM
    would put every note in the wrong place and score it as garbage. Convert to
    seconds using the chart's own map first; compare in the time domain.
    """
    t = offset
    for i, (seg_beat, seg_bpm) in enumerate(bpms):
        nxt = bpms[i + 1][0] if i + 1 < len(bpms) else float("inf")
        if beat <= seg_beat:
            break
        span = min(beat, nxt) - seg_beat
        t += span * 60.0 / seg_bpm
        if beat <= nxt:
            break
    return t


def _parse_notes_block(body: str) -> list[Placement]:
    """One #NOTES body (the measure data after the 5 metadata fields)."""
    measures = [m for m in body.split(",")]
    placements: list[Placement] = []
    open_holds: dict[int, tuple[float, str]] = {}   # col -> (start_beat, kind)

    for mi, measure in enumerate(measures):
        rows = [r.strip() for r in measure.splitlines()
                if r.strip() and not r.strip().startswith("//")]
        if not rows:
            continue
        n = len(rows)
        for ri, row in enumerate(rows):
            beat = mi * 4.0 + (ri / n) * 4.0
            taps: list[int] = []
            for col, ch in enumerate(row[:4]):
                if ch == TAP:
                    taps.append(col)
                elif ch in (HOLD_HEAD, ROLL_HEAD):
                    open_holds[col] = (beat, "hold" if ch == HOLD_HEAD else "roll")
                elif ch == TAIL:
                    if col in open_holds:
                        start, kind = open_holds.pop(col)
                        placements.append(Placement(beat=start, panels=(col,), kind=kind,
                                                    hold_beats=max(0.0, beat - start)))
                elif ch == MINE:
                    placements.append(Placement(beat=beat, panels=(col,), kind="mine"))
            if taps:
                # Simultaneous taps are one event with >1 panel — that's what makes
                # it a jump, and jump_share depends on getting this right.
                placements.append(Placement(beat=beat, panels=tuple(taps), kind="tap"))

    placements.sort(key=lambda p: (p.beat, p.panels))
    return placements


def rebase(chart: Chart, bpms: list[tuple[float, float]], offset: float,
           to_bpm: float, to_offset: float) -> Chart:
    """Re-express a chart's beats in ANOTHER tempo frame, preserving wall-clock time.

    Used to move a foreign generator's chart into our DSP analysis's beat space, so
    that `chart_metrics` — which converts beats to seconds using OUR bpm/offset —
    computes the times the notes actually occur at.
    """
    out = []
    for p in chart.placements:
        t = beat_to_time(p.beat, bpms, offset)
        new_beat = (t - to_offset) * to_bpm / 60.0
        new_hold = None
        if p.hold_beats:
            t_end = beat_to_time(p.beat + p.hold_beats, bpms, offset)
            new_hold = max(0.0, (t_end - t) * to_bpm / 60.0)
        out.append(Placement(beat=new_beat, panels=p.panels, kind=p.kind,
                             hold_beats=new_hold, meta=p.meta))
    return Chart(difficulty=chart.difficulty, meter=chart.meter,
                 steps_type=chart.steps_type, placements=out)


def parse(path: str | Path) -> tuple[float, float, list[Chart]]:
    """-> (bpm, offset, charts). Only dance-single charts are returned."""
    text = Path(path).read_text(errors="replace")
    bpm, offset = bpm_offset(text)

    charts: list[Chart] = []
    # #NOTES: <type>: <author>: <difficulty>: <meter>: <radar>: <measure data>;
    for m in re.finditer(r"#NOTES:(.*?);", text, re.S):
        block = m.group(1)
        parts = block.split(":")
        if len(parts) < 6:
            continue
        steps_type, _author, diff, meter, _radar = (p.strip() for p in parts[:5])
        if "single" not in steps_type.lower():
            continue           # doubles/solo aren't comparable to what we generate
        body = ":".join(parts[5:])
        try:
            placements = _parse_notes_block(body)
        except Exception as e:                     # noqa: BLE001
            print(f"  [warn] {Path(path).name} {diff}: unparseable ({e})", file=sys.stderr)
            continue
        if not placements:
            continue
        charts.append(Chart(difficulty=diff or "?",
                            meter=int(float(meter)) if meter.replace(".", "").isdigit() else 0,
                            steps_type=steps_type, placements=placements))
    return bpm, offset, charts


if __name__ == "__main__":
    for f in sys.argv[1:]:
        bpm, offset, charts = parse(f)
        print(f"{Path(f).name}: bpm={bpm:.1f} offset={offset:.3f}")
        for c in charts:
            jumps = sum(1 for p in c.placements if len(p.panels) > 1)
            holds = sum(1 for p in c.placements if p.hold_beats)
            print(f"   {c.difficulty:<10} meter {c.meter:>2}  {c.notes:>4} notes  "
                  f"{jumps:>3} jumps  {holds:>3} holds")
