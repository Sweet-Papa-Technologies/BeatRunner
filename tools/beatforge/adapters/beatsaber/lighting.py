"""lighting.py — templated basic lighting (SABERFORGE spec §7, REQ-BS-07).

HONEST SCOPE: v1 does NOT author an artful lightshow. It emits basic, beat-synced
templated lighting driven by the analysis — on-downbeat flashes, section-coloured
washes, and intensity riding the per-bar energy curve — as a *starting point* a
human finishes in ChroMapper. Output is v3 `basicBeatmapEvents`
{b, et (event type), i (value), f (float intensity)}.
"""
from __future__ import annotations

# v3 basic event types (vanilla environment lanes).
ET_BACK_LASERS = 0
ET_RING_LIGHTS = 1
ET_LEFT_LASERS = 2
ET_RIGHT_LASERS = 3
ET_CENTER_LIGHTS = 4
ET_RING_ROTATE = 8

# Light values: 0 off, 1 blue on, 2 blue flash, 3 blue fade, 5 red on, 6 red flash.
V_OFF, V_BLUE_ON, V_BLUE_FLASH, V_RED_ON, V_RED_FLASH = 0, 1, 2, 5, 6


def _playable(analysis):
    from ... import config
    bpm, offset = analysis["bpm"], analysis["offset"]
    lo = config.FIRST_PLAYABLE_BEAT
    hi = (analysis["duration_s"] - config.PLAYABLE_TAIL_S - offset) * bpm / 60.0
    return lo, hi


def basic_lighting(analysis: dict) -> list[dict]:
    """Build a basic, beat-synced lighting track from the analysis. Returns v3
    basicBeatmapEvents sorted by beat."""
    meter = analysis.get("meter", 4)
    lo, hi = _playable(analysis)
    sections = analysis.get("sections", [])
    energy = analysis.get("energy_curve", [])
    events: list[dict] = []

    def section_at(bar):
        for i, s in enumerate(sections):
            if s["start_bar"] <= bar < s["end_bar"]:
                return i, s
        return 0, None

    def energy_at(bar):
        if not energy:
            return 0.6
        return float(energy[min(len(energy) - 1, max(0, bar))])

    # Section-coloured wash at each section boundary + a ring rotation kick.
    for i, s in enumerate(sections):
        b = max(lo, s["start_bar"] * meter)
        if b > hi:
            continue
        color_on = V_RED_ON if i % 2 == 0 else V_BLUE_ON
        inten = round(0.4 + 0.6 * energy_at(s["start_bar"]), 3)
        events.append({"b": round(b, 3), "et": ET_BACK_LASERS, "i": color_on, "f": inten})
        events.append({"b": round(b, 3), "et": ET_RING_ROTATE, "i": 1, "f": 1.0})

    # On-downbeat flashes across the playable range, intensity riding energy.
    beat = float(int(lo / meter) * meter)
    if beat < lo:
        beat += meter
    while beat <= hi + 1e-6:
        bar = int(beat // meter)
        i, _ = section_at(bar)
        flash = V_RED_FLASH if i % 2 == 0 else V_BLUE_FLASH
        inten = round(0.5 + 0.5 * energy_at(bar), 3)
        events.append({"b": round(beat, 3), "et": ET_CENTER_LIGHTS, "i": flash, "f": inten})
        beat += meter

    events.sort(key=lambda e: (e["b"], e["et"]))
    return events
