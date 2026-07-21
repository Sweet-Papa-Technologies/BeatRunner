"""make_pack.py — assemble a baseline generator's charts into a playable ITGmania pack.

Every song folder is named "<Title> [LABEL]" so that in the song wheel you can play
STEPFORGE's chart and the baseline's chart of the same track back to back and feel
the difference, not just read it in a table.

The AUDIO is always our original .ogg master — identical bytes for every generator.
Only the chart differs. That's the whole experiment.

    python3 make_pack.py --label AUTOSTEPPER --sm-dir /tmp/as_out --pack FoFo-Compare-Mix
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

SONGS = Path("~/Library/Application Support/ITGmania/Songs").expanduser()
SRC_PACK = SONGS / "SweetPapa Dream Mix - Founder Mix"
AUDIO = Path(__file__).parent / "audio"

# base -> the human title we used in the real pack
TITLES = {
    "banana_banana": "Banana Banana",
    "bttr": "Bttr",
    "do_it_for_me_now": "Do It For Me Now",
    "explicit_fast_and_free": "Explicit - Fast And Free",
    "lucky_lucky": "Lucky Lucky",
    "robo_fast_food": "Robo Fast Food",
    "room_smells_like_poo_the_dog_just_took_a_crap_on_the_floor":
        "Room Smells Like Poo (The Dog Just Took A Crap On The Floor)",
    "smile_and_dance": "Smile And Dance",
    "stay_awake_for_me": "Stay Awake For Me",
    "streaming_is_the_life_for_me": "Streaming Is The Life For Me",
    "the_pools": "The Pools",
    "token_economy": "Token Economy",
    "song": "消えてゆく",
}


def find_sm(sm_dir: Path, base: str) -> Path | None:
    """Baselines name their output inconsistently (AutoStepper emits
    '<base>.wav_dir/<base>.wav.sm'). Search rather than assume."""
    for p in sm_dir.rglob("*.sm"):
        stem = p.stem.replace(".wav", "").replace(".ogg", "")
        if stem == base or p.parent.name.replace(".wav_dir", "") == base:
            return p
    return None


def retitle(text: str, title: str, label: str, music: str) -> str:
    """Point the simfile at our audio and our art, and stamp the generator's name
    into TITLE/CREDIT so there is no ambiguity about whose chart you're playing."""
    def setk(t, key, val):
        if re.search(rf"#{key}:[^;]*;", t):
            return re.sub(rf"#{key}:[^;]*;", f"#{key}:{val};", t, count=1)
        return t.rstrip() + f"\n#{key}:{val};\n"

    text = setk(text, "TITLE", f"{title} [{label}]")
    text = setk(text, "MUSIC", music)
    text = setk(text, "CREDIT", label)
    text = setk(text, "SUBTITLE", label)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="e.g. AUTOSTEPPER, DDC")
    ap.add_argument("--sm-dir", required=True, help="where the generator wrote its .sm files")
    ap.add_argument("--pack", default="FoFo-Compare-Mix")
    a = ap.parse_args()

    pack = SONGS / a.pack
    pack.mkdir(parents=True, exist_ok=True)
    sm_dir = Path(a.sm_dir).expanduser()

    made = missing = 0
    for base, title in TITLES.items():
        sm = find_sm(sm_dir, base)
        ogg = AUDIO / f"{base}.ogg"
        if not sm or not ogg.exists():
            print(f"  [miss] {title} — no chart from {a.label}")
            missing += 1
            continue

        dest = pack / f"{title} [{a.label}]"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ogg, dest / f"{base}.ogg")
        (dest / f"{base}.sm").write_text(
            retitle(sm.read_text(errors="replace"), title, a.label, f"{base}.ogg"),
            encoding="utf-8")

        # Reuse our banner/background so the wheel doesn't look broken. The art has
        # nothing to do with the charting and is identical across generators.
        src_song = SRC_PACK / title
        for suffix in ("-banner.png", "-bg.png"):
            art = src_song / f"{base}{suffix}"
            if art.exists():
                shutil.copyfile(art, dest / art.name)
        made += 1
        print(f"  [ok]   {title} [{a.label}]")

    print(f"\n{a.label}: {made} songs into '{a.pack}'"
          + (f", {missing} missing" if missing else ""))


if __name__ == "__main__":
    main()
