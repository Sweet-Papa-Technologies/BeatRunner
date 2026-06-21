#!/usr/bin/env python3
"""Author OVERDRIVE beat-maps: lane-balanced, musically phrased, with occasional
holds. Density escalates through intro -> build -> drop -> break -> drop -> outro
and is scaled to BPM so fast tracks stay playable. Lanes map GAP=0/BAR=1/NOTE=2.

Sized to each track's REAL duration (ffprobe). Casual-first: never a wall of notes.
"""
import json, math, os, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANE_TYPE = {0: "GAP", 1: "BAR", 2: "NOTE"}


def duration(ogg):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", ogg], text=True).strip()
    return float(out)


def build(track, bpm, offset, dur):
    tail = 1.4
    last = int(math.floor(((dur - tail) - offset) * bpm / 60.0))
    fast = bpm >= 110
    events = []
    seen = set()

    def add(beat, lane, hold=0):
        b = round(beat, 3)
        if b < 4 or b > last:
            return
        key = (b, lane)
        if key in seen:
            return
        seen.add(key)
        e = {"beat": b, "type": LANE_TYPE[lane]}
        if hold:
            e["dur"] = hold
        events.append(e)

    # section boundaries (in beats)
    s1 = max(16, int(last * 0.16))   # intro end
    s2 = int(last * 0.40)            # build end
    s3 = int(last * 0.58)            # drop1 end
    s4 = int(last * 0.68)            # break end
    s5 = int(last * 0.90)            # drop2 end

    # --- intro: one call per bar, a gentle ascending sweep, a couple of holds ---
    seq = [1, 0, 2, 1]
    for i, beat in enumerate(range(8, s1, 4)):
        add(beat, seq[i % 4])
        if i % 2 == 1:
            add(beat + 2, (seq[i % 4] + 2) % 3, hold=2)

    # --- build: quarter notes, weaving across lanes ---
    weave = [0, 1, 2, 1, 2, 1, 0, 1]
    for i, beat in enumerate(range(s1, s2, 1)):
        add(beat, weave[i % len(weave)])

    # --- drop1: the hook. fast tracks get 8ths; all get a driving roll ---
    step = 0.5 if fast else 1.0
    roll = [0, 1, 2, 1, 2, 0, 1, 2, 1, 0, 2, 1]
    i = 0
    beat = s3 - (s3 - s2)  # = s2
    beat = float(s2)
    while beat < s3:
        add(beat, roll[i % len(roll)])
        # accent hold every 4 bars
        if i % 16 == 0 and i > 0:
            add(beat, 1, hold=4)
        beat += step
        i += 1

    # --- break: breathe. sparse mids + a long hold to recover ---
    bb = float(s3)
    j = 0
    while bb < s4:
        add(bb, [1, 0, 2][j % 3], hold=(4 if j % 2 == 0 else 0))
        bb += 2.0
        j += 1

    # --- drop2: hardest section, alternating hands, occasional double-time ---
    step2 = 0.5 if fast else 0.5
    drive = [0, 2, 1, 0, 2, 1, 2, 0, 1, 2, 0, 1, 2, 1, 0, 2]
    k = 0
    cb = float(s4)
    while cb < s5:
        add(cb, drive[k % len(drive)])
        cb += step2 if fast else 1.0
        k += 1

    # --- outro: cool down to single hits + a final big hold ---
    for m, beat in enumerate(range(s5, last + 1, 2)):
        add(beat, [2, 1, 0][m % 3])
    add(last - 4, 1, hold=4)

    events.sort(key=lambda e: (e["beat"], e["type"]))
    return {"track": track, "bpm": bpm, "offset": offset, "events": events}, last


MAPS = [
    ("overdrive_pulse.beatmap.json", "overdrive_pulse.ogg", 120, 0.10),
    ("midnight_run.beatmap.json", "midnight_run.ogg", 128, 0.10),
    ("neon_nights.beatmap.json", "neon_nights.ogg", 92, 0.15),
    ("sweetpapa_groove.beatmap.json", "sweetpapa_groove.ogg", 88, 0.20),
]

out_dir = os.path.join(ROOT, "public", "maps")
os.makedirs(out_dir, exist_ok=True)
for name, audio, bpm, offset in MAPS:
    ogg = os.path.join(ROOT, "public", "assets", "tracks", audio)
    dur = duration(ogg)
    m, last = build(audio, bpm, offset, dur)
    holds = sum(1 for e in m["events"] if "dur" in e)
    with open(os.path.join(out_dir, name), "w") as f:
        json.dump(m, f, indent=2)
    print(f"wrote maps/{name}: {len(m['events'])} events ({holds} holds), "
          f"bpm {bpm}, last beat {last}, track {dur:.1f}s")
