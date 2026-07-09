"""batch_stepforge.py — batch a folder of audio into a StepMania song pack.

For each audio file: transcode -> ogg, register as a track, generate banner +
background art via assetforge (best-effort), chart all difficulties with the
STEPFORGE adapter (Gemini 3.5 Flash, foot-flow realizer, gap-fill), and copy the
finished song folder into an ITGmania pack.

RESUMABLE: a song whose pack folder already holds a `.ssc` is skipped, so the
batch can be re-run after any interruption and continues where it left off.
RATE-SAFE: songs are processed strictly one at a time and model calls are paced
by BEATFORGE_LLM_MIN_INTERVAL (see vertex._pace).

Usage:
  BEATFORGE_LLM_MIN_INTERVAL=3 python -m beatforge.batch_stepforge \
     --src "/path/to/folder" --pack FoFoSongs \
     --dest "~/Library/Application Support/ITGmania/Songs"
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import shutil
import sys
import time
from pathlib import Path

from . import config
from .adapters.stepmania.adapter import build_song

AUDIO_EXT = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}
ASSETFORGE = Path("~/.assetforge/assetforge.py").expanduser()


def clean_title(name: str) -> str:
    """Human title from a messy filename: drop ext, leading track numbers,
    version/date/time tags, junk parentheticals, underscores -> spaces, title."""
    orig = Path(name).stem
    t = orig
    t = re.sub(r"^\s*\d{1,2}[\s._-]+", "", t)                     # leading track number
    t = re.sub(r"\[[^\]]*\]", "", t)                             # [Demo] [Bonus] groups
    # parentheticals that are pure noise (versions, "untitled 3", u1, dates)
    t = re.sub(r"\((?:[^)]*(?:untitled|master|normal|\bv\d+|\bu\d+|\d+[_/]\d+)[^)]*)\)",
               "", t, flags=re.I)
    # trailing " - <date/version/remix/master>" junk after a dash
    t = re.sub(r"\s*-\s*(?:\(?)(?:master|normal|demo|v\d+|.*\d+[_/]\d+.*|"
               r".*\d{1,2}\.\d{2}\s*[ap]m.*|.*remix.*)$", "", t, flags=re.I)
    t = re.sub(r"[_]+", " ", t)
    t = re.sub(r"\s+", " ", t)
    # strip any dangling unmatched bracket/paren left at the ends
    t = re.sub(r"\s*[([\[]\s*$", "", t)
    t = t.strip(" -_([")
    return (t or orig).title()


def safe_base(title: str) -> str:
    b = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return b or "song"


def transcode(src: Path, base: str) -> Path:
    out = config.TRACKS_PUB / f"{base}.ogg"
    if not out.exists():
        # -vn / -map 0:a:0: take ONLY the audio. Many source files have embedded
        # album art, which ffmpeg would otherwise write as a theora video stream
        # into the ogg — and libsndfile/soundfile can't decode that.
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                        "-vn", "-map", "0:a:0", "-c:a", "libvorbis", "-q:a", "6", str(out)],
                       check=True, capture_output=True)
    shutil.copyfile(out, config.TRACKS_SRC / f"{base}.ogg")
    return out


def make_art(title: str, base: str, out_dir: Path) -> None:
    """Best-effort banner + background via assetforge (Imagen). Never blocks."""
    jobs = [
        (f"{base}-banner.png", "16:9",
         f"Widescreen song banner art for a rhythm game track titled '{title}'. "
         f"Moody synthwave/retro aesthetic, neon gradient, cinematic, no text, high detail"),
        (f"{base}-bg.png", "16:9",
         f"Full-screen 16:9 gameplay background for a rhythm game track '{title}'. "
         f"Atmospheric neon retro scene, dark enough for a note overlay, no text"),
    ]
    for fname, aspect, prompt in jobs:
        dst = out_dir / fname
        if dst.exists():
            continue
        try:
            subprocess.run([sys.executable, str(ASSETFORGE), "image", prompt,
                            "--aspect", aspect, "-o", str(dst)],
                           check=True, capture_output=True, timeout=180)
            time.sleep(2)   # gentle pacing for the image quota
        except Exception as e:
            print(f"    [art] {fname} skipped: {str(e)[:80]}")


def clone_to_pack(base: str, title: str, src_dir: Path, pack_dir: Path) -> Path:
    dest = pack_dir / title
    dest.mkdir(parents=True, exist_ok=True)
    for suffix in (".ssc", ".sm", ".ogg", "-banner.png", "-bg.png"):
        f = src_dir / f"{base}{suffix}"
        if f.exists():
            shutil.copyfile(f, dest / f.name)
    return dest


def run(src: str, pack: str, dest: str, difficulties, limit: int | None,
        deterministic: bool = False):
    src_dir = Path(src).expanduser()
    pack_dir = Path(dest).expanduser() / pack
    pack_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in src_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in AUDIO_EXT)
    if limit:
        files = files[:limit]
    manifest = pack_dir / "_batch_manifest.json"
    done = json.loads(manifest.read_text()) if manifest.exists() else {}

    print(f"[batch] {len(files)} songs -> pack '{pack}' at {pack_dir}")
    for i, f in enumerate(files, 1):
        title = clean_title(f.name)
        base = safe_base(title)
        song_dest = pack_dir / title
        if (song_dest / f"{base}.ssc").exists():
            print(f"[{i}/{len(files)}] SKIP (done): {title}")
            done[f.name] = {"title": title, "base": base, "status": "done"}
            continue
        print(f"[{i}/{len(files)}] {title}  ({f.name})")
        try:
            transcode(f, base)
            config.TRACK_CATALOGUE[base] = base
            config.TRACK_META[base] = (title, "FoFo")
            out_dir = config.STEPMANIA_DIR / base
            out_dir.mkdir(parents=True, exist_ok=True)
            if not deterministic:
                make_art(title, base, out_dir)                   # art before serialize
            report = build_song(base, config.RunOptions(force=True),
                                difficulties=difficulties, deterministic=deterministic,
                                client=None if deterministic else _client())
            clone_to_pack(base, title, out_dir, pack_dir)
            charts = {d: (c.get("notes"), c.get("meter"),
                          (c.get("critic") or {}).get("score")) for d, c in report["charts"].items()}
            done[f.name] = {"title": title, "base": base, "status": "done", "charts": charts}
            print(f"    -> {charts}")
        except Exception as e:
            done[f.name] = {"title": title, "base": base, "status": "error", "error": str(e)[:300]}
            print(f"    !! FAILED: {str(e)[:200]}")
        manifest.write_text(json.dumps(done, indent=2))
    ok = sum(1 for v in done.values() if v.get("status") == "done")
    print(f"[batch] complete: {ok}/{len(done)} songs charted into '{pack}'")


_CLIENT: list = [None]


def _client():
    if _CLIENT[0] is None:
        from .llm import make_llm_client
        _CLIENT[0] = make_llm_client()
    return _CLIENT[0]


def main(argv=None):
    p = argparse.ArgumentParser(prog="beatforge.batch_stepforge")
    p.add_argument("--src", required=True)
    p.add_argument("--pack", default="FoFoSongs")
    p.add_argument("--dest", default="~/Library/Application Support/ITGmania/Songs")
    p.add_argument("--difficulties", default="easy,medium,hard")
    p.add_argument("--limit", type=int)
    p.add_argument("--deterministic", action="store_true",
                   help="DSP-only note placement, no Vertex/Gemini (offline)")
    a = p.parse_args(argv)
    run(a.src, a.pack, a.dest, tuple(a.difficulties.split(",")), a.limit, a.deterministic)


if __name__ == "__main__":
    main()
