"""make_compare2.py — build the Round 2 rematch pack, "FoFo Test Compare 2".

Four charts of the same song, back to back in the wheel, over byte-identical audio:

    <Title> [AUTOSTEPPER]     phr00t's DSP stepper, 2018      (existing, copied)
    <Title> [DDC]             Dance Dance Convolution, 2017   (existing, copied)
    <Title> [STEPFORGE-R1]    ours, Round 1                   (existing, copied)
    <Title> [STEPFORGE-R2]    ours, Round 2                   (GENERATED HERE)

Only the fourth costs anything. The other three are lifted from the packs that
already exist so the comparison is against the *same* Round 1 charts that were
benchmarked, not a re-run of them.

Two phases:

    python3 make_compare2.py --copy        # instant, no model calls
    python3 make_compare2.py --generate    # ~20 min/song of Vertex calls

`--generate` writes progress to `_COMPARE2_STATUS.json` in the pack after every
song and drops `_DONE.txt` at the end, so the run is auditable without watching a
terminal. It also fires a macOS notification per song and at completion.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_pack import SONGS, SRC_PACK, TITLES, retitle          # noqa: E402

PACK = SONGS / "FoFo Test Compare 2"
COMPARE_PACK = SONGS / "FoFo-Compare-Mix"
BUILD = Path(__file__).resolve().parents[2] / "build" / "stepmania"

# --------------------------------------------------------------------------- #
# The four songs, chosen to spread the axes a chart generator can fail on:
# tempo, note supply, and how much dynamic contrast the music actually has.
#
#   lucky_lucky       110 BPM   531 onsets  cv 0.31  — slowest; sparse, laid back
#   the_pools         126 BPM  1337 onsets  cv 0.22  — Round 1's WORST chart
#                                                       (rho -0.15) and the track
#                                                       whose 25ms offset bug R2
#                                                       fixed. Biggest delta.
#   robo_fast_food    150 BPM   566 onsets  cv 0.38  — most dynamic contrast in
#                                                       the fleet; sparse but
#                                                       highly shaped
#   stay_awake_for_me 171 BPM  1601 onsets  cv 0.32  — fastest AND densest; the
#                                                       stress case for streams
# --------------------------------------------------------------------------- #
SELECTED = ["lucky_lucky", "the_pools", "robo_fast_food", "stay_awake_for_me"]

R2_LABEL = "STEPFORGE-R2"
R1_LABEL = "STEPFORGE-R1"


def notify(title: str, message: str) -> None:
    """Best-effort macOS notification. Never fatal — a missing popup must not
    take down a 20-minute-per-song run."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}" sound name "Glass"'],
            capture_output=True, timeout=10)
    except Exception:
        pass
    print(f"\a[notify] {title}: {message}", flush=True)


def _install(dest_name: str, base: str, label: str, src_files: list[Path],
             art_from: Path | None) -> bool:
    """Copy one song folder into the pack, retitling every simfile to carry the
    label so the song wheel shows four unambiguous entries."""
    dest = PACK / dest_name
    dest.mkdir(parents=True, exist_ok=True)

    ogg = None
    for f in src_files:
        if f.suffix == ".ogg":
            ogg = f
    if ogg is None:
        return False
    shutil.copyfile(ogg, dest / f"{base}.ogg")

    title = TITLES[base]
    wrote = False
    for f in src_files:
        if f.suffix not in (".sm", ".ssc"):
            continue
        (dest / f"{base}{f.suffix}").write_text(
            retitle(f.read_text(errors="replace"), title, label, f"{base}.ogg"),
            encoding="utf-8")
        wrote = True

    for suffix in ("-banner.png", "-bg.png"):
        for src in filter(None, [art_from]):
            art = src / f"{base}{suffix}"
            if art.exists():
                shutil.copyfile(art, dest / art.name)
    return wrote


def copy_existing() -> dict:
    """Phase 1: the three already-generated versions. No model calls, seconds."""
    PACK.mkdir(parents=True, exist_ok=True)
    result = {}
    for base in SELECTED:
        title = TITLES[base]
        result[base] = {}

        # AUTOSTEPPER / DDC — already labelled in FoFo-Compare-Mix, copy verbatim.
        for label in ("AUTOSTEPPER", "DDC"):
            src = COMPARE_PACK / f"{title} [{label}]"
            if src.is_dir():
                dst = PACK / f"{title} [{label}]"
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                result[base][label] = "copied"
                print(f"  [ok]   {title} [{label}]")
            else:
                result[base][label] = "MISSING"
                print(f"  [miss] {title} [{label}] — not in {COMPARE_PACK.name}")

        # STEPFORGE Round 1 — unlabelled in the founder pack; label it on the way in.
        src = SRC_PACK / title
        if src.is_dir():
            files = list(src.iterdir())
            ok = _install(f"{title} [{R1_LABEL}]", base, R1_LABEL, files, src)
            result[base][R1_LABEL] = "copied" if ok else "MISSING"
            print(f"  [{'ok' if ok else 'miss'}]   {title} [{R1_LABEL}]")
        else:
            result[base][R1_LABEL] = "MISSING"
            print(f"  [miss] {title} [{R1_LABEL}]")
    return result


def _status(payload: dict) -> None:
    PACK.mkdir(parents=True, exist_ok=True)
    (PACK / "_COMPARE2_STATUS.json").write_text(json.dumps(payload, indent=2))


def generate() -> None:
    """Phase 2: run the Round 2 pipeline per song and install the result.

    One song at a time, installing immediately after each, so a failure or a kill
    partway through still leaves every completed song playable in the pack.
    """
    t0 = time.time()
    state = {"pack": str(PACK), "songs": SELECTED, "label": R2_LABEL,
             "started": time.strftime("%Y-%m-%d %H:%M:%S"), "done": [],
             "failed": [], "in_progress": None, "complete": False}
    _status(state)
    notify("FoFo Compare 2", f"Round 2 generation started — {len(SELECTED)} songs")

    for i, base in enumerate(SELECTED, 1):
        # Resume: a previous run that was killed partway leaves finished songs
        # installed. Re-running skips them rather than paying for them twice.
        already = PACK / f"{TITLES[base]} [{R2_LABEL}]"
        if any(already.glob("*.ssc")) or any(already.glob("*.sm")):
            print(f"=== [{i}/{len(SELECTED)}] {base} — already installed, skipping",
                  flush=True)
            state["done"].append({"song": base, "title": TITLES[base],
                                  "minutes": 0.0, "returncode": 0,
                                  "installed": True, "resumed": True})
            _status(state)
            continue

        state["in_progress"] = base
        _status(state)
        print(f"\n=== [{i}/{len(SELECTED)}] {base} ===", flush=True)
        song_t0 = time.time()
        proc = subprocess.run(
            [sys.executable, "-m", "beatforge", "stepforge", "--track", base,
             "--difficulties", "beginner,easy,medium,hard,challenge"],
            cwd=str(Path(__file__).resolve().parents[1]))

        out_dir = BUILD / base
        installed = False
        if proc.returncode == 0 and out_dir.is_dir():
            files = list(out_dir.iterdir()) + [Path(__file__).parent / "audio" / f"{base}.ogg"]
            installed = _install(f"{TITLES[base]} [{R2_LABEL}]", base, R2_LABEL,
                                 files, SRC_PACK / TITLES[base])

        mins = (time.time() - song_t0) / 60
        entry = {"song": base, "title": TITLES[base], "minutes": round(mins, 1),
                 "returncode": proc.returncode, "installed": installed}
        if installed:
            state["done"].append(entry)
            notify("FoFo Compare 2", f"{TITLES[base]} done ({i}/{len(SELECTED)}, {mins:.0f}m)")
        else:
            state["failed"].append(entry)
            notify("FoFo Compare 2", f"FAILED: {TITLES[base]} (rc={proc.returncode})")
        state["in_progress"] = None
        _status(state)

    state["complete"] = True
    state["total_minutes"] = round((time.time() - t0) / 60, 1)
    state["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _status(state)

    lines = [
        "FoFo Test Compare 2 — Round 2 generation COMPLETE",
        f"finished: {state['finished']}   ({state['total_minutes']} min total)",
        "",
        f"pack: {PACK}",
        "",
        "Each song appears four times in the wheel, same audio, different chart:",
        "  [AUTOSTEPPER]   phr00t, 2018 (DSP)",
        "  [DDC]           Dance Dance Convolution, 2017 (learned)",
        "  [STEPFORGE-R1]  ours, Round 1",
        "  [STEPFORGE-R2]  ours, Round 2  <-- the new one",
        "",
        f"generated OK ({len(state['done'])}):",
    ]
    lines += [f"  - {e['title']}  ({e['minutes']} min)" for e in state["done"]]
    if state["failed"]:
        lines += ["", f"FAILED ({len(state['failed'])}):"]
        lines += [f"  - {e['title']}  rc={e['returncode']}" for e in state["failed"]]
    (PACK / "_DONE.txt").write_text("\n".join(lines) + "\n")

    notify("FoFo Compare 2 — ALL DONE",
           f"{len(state['done'])}/{len(SELECTED)} songs in {state['total_minutes']:.0f} min")
    print("\n" + "\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", action="store_true", help="install the 3 existing versions")
    ap.add_argument("--generate", action="store_true", help="run Round 2 and install it")
    a = ap.parse_args()
    if not (a.copy or a.generate):
        ap.error("pass --copy and/or --generate")
    if a.copy:
        print(f"Installing existing versions into '{PACK.name}'…")
        copy_existing()
    if a.generate:
        generate()


if __name__ == "__main__":
    main()
