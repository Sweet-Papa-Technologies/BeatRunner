"""make_founders2.py — build "SweetPapa's Founders Mix #2" end to end.

Phases, each notifying as it finishes:
    1. art      — a distinct banner + background per song, plus a pack banner
    2. charts   — 5 difficulties per song via the Round 3 pipeline (gemini-3.6-flash)
    3. install  — assemble the ITGmania pack and copy it into the Songs folder
    4. score    — run the benchmark scorer and compare against every prior
                  iteration and both competitors

Designed to be run detached (`--daemon LOG`): it is a multi-hour job, so it
checkpoints after every song and can be re-run to resume.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

PACK_NAME = "SweetPapa's Founders Mix #2"
SONGS_DIR = Path("~/Library/Application Support/ITGmania/Songs").expanduser()
PACK = SONGS_DIR / PACK_NAME
STAGE = REPO / "build" / "founders2"
ART = REPO / "build" / "founders2_art"
ASSETFORGE = Path("~/.assetforge/assetforge.py").expanduser()
MODEL = os.environ.get("BEATFORGE_GEMINI_MODEL", "gemini-3.6-flash")

# base -> (title, artist, art direction). Art direction is per song on purpose:
# nine variations of "neon dance cover" would look like a template, which is the
# opposite of what a song wheel needs to feel like a curated mix.
TRACKS = {
    "fm2_banana_banana": ("Banana Banana", "Sweet Papa & the Tones",
        "stylised glowing neon bananas arranged in a rhythmic arc, deep purple to "
        "hot-pink gradient, halftone dots, retro arcade energy"),
    "fm2_do_it_for_me_now": ("Do It For Me Now", "Sweet Papa & the Tones",
        "urgent forward motion, speeding chevron arrows and light streaks racing "
        "right, electric cyan on charcoal, hard diagonal composition, sense of demand"),
    "fm2_lucky_lucky": ("Lucky Lucky", "Sweet Papa & the Tones",
        "fortune and luck: golden four-leaf clovers, tumbling dice and coin sparkles "
        "on emerald green and gold, glossy, celebratory, lucky-sevens slot-machine glow"),
    "fm2_smile_and_dance": ("Smile and Dance", "Sweet Papa & the Tones",
        "pure joy: silhouetted dancers mid-leap inside a burst of confetti and "
        "streamers, warm sunset orange to magenta, kinetic, buoyant, party energy"),
    "fm2_some_will_say": ("Some Will Say", "Sweet Papa & the Tones",
        "moody and contemplative: overlapping translucent speech-bubble shapes and "
        "concentric sound ripples on deep indigo and teal, quiet, introspective, "
        "cinematic rim light"),
    "fm2_stay_awake_for_me": ("Stay Awake For Me", "Sweet Papa & the Tones",
        "3am insomnia: a lone lit window above a rain-slicked neon city street, "
        "electric blue and amber reflections, moody nocturnal atmosphere, wet asphalt"),
    "fm2_streaming_is_the_life_for_me": ("Streaming Is The Life For Me", "Sweet Papa & the Tones",
        "broadcast culture: a wall of glowing screens and tangled cables radiating "
        "signal waves, lime green and electric violet, playful chaotic tech energy"),
    "fm2_token_economy": ("Token Economy", "Sweet Papa & the Tones",
        "arcade tokens and coins cascading through glowing circuit-board traces, "
        "gold on dark teal, crisp isometric geometry, satisfying mechanical wealth"),
    "fm2_kieteyuku": ("消えてゆく", "Sweet Papa & the Tones",
        "fading away: a figure dissolving into drifting sakura petals and soft "
        "particles, muted pastel pink and pale blue, Japanese minimalist aesthetic, "
        "melancholy, lots of negative space, ethereal"),
}
ORDER = list(TRACKS)

STYLE = ("high quality album cover art for a rhythm-game dance track, vibrant "
         "saturated colour, strong single focal point, clean graphic composition, "
         "dramatic lighting, no text, no letters, no words, no watermark")


def notify(title: str, msg: str) -> None:
    try:
        subprocess.run(["osascript", "-e",
            f'display notification "{msg}" with title "{title}" sound name "Glass"'],
            capture_output=True, timeout=10)
    except Exception:
        pass
    print(f"\a[notify] {title}: {msg}", flush=True)


def status(payload: dict) -> None:
    STAGE.mkdir(parents=True, exist_ok=True)
    (STAGE / "_STATUS.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def daemonize(logfile: Path) -> None:
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    logfile.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1); os.dup2(fd, 2)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    STAGE.mkdir(parents=True, exist_ok=True)
    (STAGE / "_PID.txt").write_text(f"{os.getpid()}\n")


def _image(prompt: str, out: Path, aspect: str) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 10000:
        return True                                   # resume: keep what we have
    r = subprocess.run([sys.executable, str(ASSETFORGE), "image", "--aspect", aspect,
                        "-o", str(out), prompt], capture_output=True, text=True, timeout=300)
    ok = out.exists() and out.stat().st_size > 10000
    if not ok:
        print(f"  [art] FAILED {out.name}: {r.stderr.strip()[:160]}")
    return ok


def phase_art() -> None:
    print("=== PHASE 1: art ===", flush=True)
    made = 0
    for base, (title, _artist, direction) in TRACKS.items():
        if _image(f"{direction}. {STYLE}", ART / f"{base}-bg.png", "16:9"):
            made += 1
        # the banner is what you actually read in the song wheel: same art
        # direction, but composed wide and simple so it survives being small.
        # NB: do NOT say "wide banner" — that makes the model draw literal
        # letterbox bars. Ask for a normal image, then crop it to 2:1 ourselves.
        if _image(f"{direction}. Bold and simple so it reads clearly at small "
                  f"size, subject centred. {STYLE}",
                  ART / f"{base}-banner.png", "16:9"):
            made += 1
        print(f"  [art] {title}", flush=True)
    _image("A premium rhythm-game music pack banner for a collection called "
           "SweetPapa's Founders Mix. Bold neon dance-floor energy, glowing "
           "equaliser bars and arrows radiating from a central burst, deep purple "
           "magenta and cyan, luxurious and iconic. " + STYLE,
           ART / "pack-banner.png", "16:9")
    # Trim any letterbox bars the model added and fit each image to the size
    # ITGmania actually wants (2:1 banners, 16:9 backgrounds).
    from fix_banners import process
    for img in sorted(ART.glob("*.png")):
        try:
            print("  [fit]", process(img), flush=True)
        except Exception as e:
            print(f"  [fit] FAILED {img.name}: {e}", flush=True)
    notify("Founders Mix #2", f"art done — {made} song images + pack banner")


def phase_charts(only: list[str] | None = None) -> dict:
    print("=== PHASE 2: charts ===", flush=True)
    todo = only or ORDER
    st = {"pack": PACK_NAME, "model": MODEL, "songs": todo,
          "done": [], "failed": [], "in_progress": None}
    status(st)
    for i, base in enumerate(todo, 1):
        title = TRACKS[base][0]
        out_dir = REPO / "build" / "stepmania" / base
        if (out_dir / f"{base}.ssc").exists():
            print(f"=== [{i}/{len(todo)}] {base} — already charted, skipping", flush=True)
            st["done"].append({"song": base, "title": title, "resumed": True})
            status(st); continue
        st["in_progress"] = base; status(st)
        print(f"\n=== [{i}/{len(todo)}] {base} ({title}) ===", flush=True)
        t0 = time.time()
        env = dict(os.environ, BEATFORGE_GEMINI_MODEL=MODEL, BEATFORGE_LLM_MIN_INTERVAL="3")
        p = subprocess.run([sys.executable, "-m", "beatforge", "stepforge",
                            "--track", base, "--difficulties",
                            "beginner,easy,medium,hard,challenge"],
                           cwd=str(REPO / "tools"), env=env)
        mins = (time.time() - t0) / 60
        ok = p.returncode == 0 and (out_dir / f"{base}.ssc").exists()
        (st["done"] if ok else st["failed"]).append(
            {"song": base, "title": title, "minutes": round(mins, 1), "rc": p.returncode})
        st["in_progress"] = None; status(st)
        notify("Founders Mix #2",
               f"{'charted' if ok else 'FAILED'}: {title} ({i}/{len(todo)}, {mins:.0f}m)")
    return st


def phase_install() -> int:
    print("=== PHASE 3: install pack ===", flush=True)
    PACK.mkdir(parents=True, exist_ok=True)
    n = 0
    for base, (title, artist, _d) in TRACKS.items():
        src = REPO / "build" / "stepmania" / base
        if not (src / f"{base}.ssc").exists():
            print(f"  [skip] {title} — no chart"); continue
        dest = PACK / title
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.suffix in (".ssc", ".sm", ".ogg"):
                shutil.copyfile(f, dest / f.name)
        for kind in ("banner", "bg"):
            a = ART / f"{base}-{kind}.png"
            if a.exists():
                shutil.copyfile(a, dest / a.name)
        # point the simfile at its art
        for sim in list(dest.glob("*.ssc")) + list(dest.glob("*.sm")):
            t = sim.read_text(errors="replace")
            import re
            for key, fn in (("BANNER", f"{base}-banner.png"), ("BACKGROUND", f"{base}-bg.png")):
                if (dest / fn).exists():
                    t = (re.sub(rf"#{key}:[^;]*;", f"#{key}:{fn};", t, count=1)
                         if re.search(rf"#{key}:[^;]*;", t) else t.rstrip() + f"\n#{key}:{fn};\n")
            sim.write_text(t, encoding="utf-8")
        n += 1
        print(f"  [ok] {title}")
    pb = ART / "pack-banner.png"
    if pb.exists():
        shutil.copyfile(pb, PACK / f"{PACK_NAME}.png")
    notify("Founders Mix #2", f"pack installed — {n} songs in ITGmania")
    return n


def phase_score() -> None:
    print("=== PHASE 4: score + compare ===", flush=True)
    here = Path(__file__).resolve().parent
    subprocess.run([sys.executable, "score.py", "--pack", PACK_NAME,
                    "--label", "FOUNDERS2"], cwd=str(here), check=False)
    subprocess.run([sys.executable, "founders2_report.py"], cwd=str(here), check=False)
    notify("Founders Mix #2", "benchmark + comparison complete")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", metavar="LOG")
    ap.add_argument("--only", help="comma list of bases (charts phase)")
    ap.add_argument("--phases", default="art,charts,install,score")
    a = ap.parse_args()
    if a.daemon:
        daemonize(Path(a.daemon).expanduser().resolve())
    ph = [p.strip() for p in a.phases.split(",")]
    t0 = time.time()
    notify("Founders Mix #2", f"starting — {len(ORDER)} songs, model {MODEL}")
    if "art" in ph:
        phase_art()
    if "charts" in ph:
        phase_charts(a.only.split(",") if a.only else None)
    if "install" in ph:
        phase_install()
    if "score" in ph:
        phase_score()
    mins = (time.time() - t0) / 60
    (STAGE / "_DONE.txt").write_text(
        f"SweetPapa's Founders Mix #2 — COMPLETE\n"
        f"finished {time.strftime('%Y-%m-%d %H:%M:%S')} ({mins:.0f} min)\n"
        f"model: {MODEL}\npack: {PACK}\n")
    notify("Founders Mix #2 — ALL DONE", f"complete in {mins:.0f} min")


if __name__ == "__main__":
    main()
