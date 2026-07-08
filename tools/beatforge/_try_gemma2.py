"""Gemma-only retry WITH the 16kHz-mono audio fix + improved realizer. Builds one
difficulty at a time on Pizza Party, timing each, so we see if Gemma is viable now."""
import sys, time
from pathlib import Path
from beatforge import config
from beatforge.batch_stepforge import clean_title, safe_base, transcode, clone_to_pack
from beatforge.analyze import analyze_track
from beatforge.adapters.stepmania.adapter import build_song
from beatforge.llm import OpenAICompatClient

SONG = Path("/Users/fterry/Downloads/Pizza Party for Two - Don't Wanna Be Wrong - Demo.mp3")
title = clean_title(SONG.name); base = safe_base(title)
transcode(SONG, base)
config.TRACK_CATALOGUE[base] = base
config.TRACK_META[base] = (title, "FoFo")

gemma = OpenAICompatClient()
print(f"gemma {gemma.base_url} model={gemma.model} audio={config.OPENAI_AUDIO_SR}Hz "
      f"mono={config.OPENAI_AUDIO_MONO} max_tokens={config.OPENAI_MAX_TOKENS} "
      f"timeout={gemma.timeout}s", flush=True)

# one difficulty at a time — easiest first (smallest intent JSON = best shot)
for diff in ("easy", "medium", "hard"):
    print(f"\n=== gemma build: {diff} ===", flush=True)
    t0 = time.monotonic()
    try:
        rep = build_song(base, config.RunOptions(force=True), difficulties=(diff,),
                         deterministic=False, client=gemma)
        c = rep["charts"][diff]
        dt = time.monotonic() - t0
        print(f"  OK {diff}: notes={c['notes']} meter={c['meter']} jumps={c['jumps']} "
              f"holds={c['holds']} critic={(c.get('critic') or {}).get('score')} "
              f"in {dt:.0f}s", flush=True)
        clone_to_pack(base, title, config.STEPMANIA_DIR / base,
                      Path("/Users/fterry/Library/Application Support/ITGmania/Songs") / "GemmaTest")
    except Exception as e:
        print(f"  FAIL {diff} after {time.monotonic()-t0:.0f}s: {str(e)[:220]}", flush=True)
print("\ndone", flush=True)
