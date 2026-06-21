#!/usr/bin/env python3
"""Author beat-maps sized to the ACTUAL track duration. Density escalates then
cools down. Casual-first: never too dense; types telegraphed by rhythmic role."""
import json, math, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DURATION = 32.768  # real Lyria track length (seconds)

def last_playable_beat(bpm, offset, tail=1.2):
    return int(math.floor(((DURATION - tail) - offset) * bpm / 60.0))

def build(track, bpm, offset):
    last = last_playable_beat(bpm, offset)
    events = []
    def add(beat, typ):
        if 4 <= beat <= last:
            events.append({"beat": beat, "type": typ})

    a_end = max(12, int(last * 0.32))
    b_end = max(a_end + 4, int(last * 0.62))
    c_end = max(b_end + 4, last - 3)

    # Phase A: gentle intro — a call every 4 beats
    cycle = ["GAP", "NOTE", "BAR", "NOTE"]
    for i, beat in enumerate(range(8, a_end, 4)):
        add(beat, cycle[i % len(cycle)])

    # Phase B: every 2 beats with a little syncopation
    patt = ["GAP", "NOTE", "BAR", "NOTE", "GAP", "NOTE"]
    for i, beat in enumerate(range(a_end, b_end, 2)):
        add(beat, patt[i % len(patt)])
        if i % 3 == 2:
            add(beat + 1, "NOTE")

    # Phase C: the drop — driving, all three types
    drive = ["GAP", "NOTE", "BAR", "NOTE", "NOTE", "BAR", "GAP", "NOTE"]
    for i, beat in enumerate(range(b_end, c_end, 2)):
        add(beat, drive[i % len(drive)])
        if i % 4 == 3:
            add(beat + 1, "NOTE")

    # Cooldown: sparse finish
    for beat in range(c_end, last + 1, 2):
        add(beat, "NOTE")

    seen, clean = set(), []
    for e in sorted(events, key=lambda e: e["beat"]):
        key = (e["beat"], e["type"])
        if key in seen:
            continue
        seen.add(key)
        clean.append(e)
    return {"track": track, "bpm": bpm, "offset": offset, "events": clean}, last

MAPS = [
    ("sweetpapa_groove.beatmap.json", "sweetpapa_groove.ogg", 88, 0.20),
    ("neon_nights.beatmap.json", "neon_nights.ogg", 92, 0.15),
]

out_dir = os.path.join(ROOT, "public", "maps")
os.makedirs(out_dir, exist_ok=True)
for name, track, bpm, offset in MAPS:
    m, last = build(track, bpm, offset)
    last_t = round(offset + last * 60.0 / bpm, 2)
    with open(os.path.join(out_dir, name), "w") as f:
        json.dump(m, f, indent=2)
    print(f"wrote public/maps/{name}: {len(m['events'])} events, bpm {bpm}, "
          f"last beat {last} @ {last_t}s (track {DURATION}s)")
