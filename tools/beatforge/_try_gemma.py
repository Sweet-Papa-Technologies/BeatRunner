"""One-off scratch: register the Pizza Party song and A/B Gemma-4-12B vs Gemini."""
import sys, json, time
from pathlib import Path
from beatforge import config
from beatforge.batch_stepforge import clean_title, safe_base, transcode
from beatforge.analyze import analyze_track
from beatforge.compare import audio_probe
from beatforge.llm import OpenAICompatClient, OpenAICompatError, VertexClient
from beatforge.vertex import VertexError

SONG = Path("/Users/fterry/Downloads/Pizza Party for Two - Don't Wanna Be Wrong - Demo.mp3")
title = clean_title(SONG.name)
base = safe_base(title)
print(f"title={title!r} base={base!r}")

transcode(SONG, base)                         # -> TRACKS_PUB/base.ogg (+ SRC copy)
config.TRACK_CATALOGUE[base] = base
config.TRACK_META[base] = (title, "FoFo")

analysis = analyze_track(base, config.RunOptions(force=True))
audio = str(config.TRACKS_PUB / f"{base}.ogg")
print(f"measured bpm={analysis['bpm']:.2f} onsets={len(analysis.get('onsets',[]))} "
      f"dur={analysis['duration_s']:.1f}s")

gemini, gemma = VertexClient(), OpenAICompatClient()
print(f"\ngemma endpoint: {gemma.base_url} model={gemma.model} audio_fmt={gemma.audio_format} "
      f"timeout={gemma.timeout}s")

for name, client in (("gemini", gemini), ("gemma", gemma)):
    try:
        p = audio_probe(client, audio)
        err = abs(float(p.get("tempo_bpm", 0)) - analysis["bpm"])
        print(f"[{name}] bpm={p.get('tempo_bpm')} (err {err:.1f}) kick={p.get('has_kick')} "
              f"sections={p.get('section_count')} {p.get('_latency_s')}s "
              f"| {str(p.get('one_line',''))[:80]}")
    except (VertexError, OpenAICompatError, ValueError) as e:
        print(f"[{name}] PROBE ERROR: {str(e)[:280]}")

# ---- full StepMania build: same difficulty, both backends ----
from beatforge.adapters.stepmania.adapter import build_song
from beatforge.batch_stepforge import clone_to_pack
DIFF = ("easy", "medium", "hard")
PACK_ROOT = Path("/Users/fterry/Library/Application Support/ITGmania/Songs")

for name, client in (("gemma", gemma), ("gemini", gemini)):
    print(f"\n=== {name} StepMania build ({','.join(DIFF)}) ===")
    t0 = time.monotonic()
    try:
        rep = build_song(base, config.RunOptions(force=True), difficulties=DIFF,
                         deterministic=False, client=client)
        for d, c in rep["charts"].items():
            crit = (c.get("critic") or {}).get("score")
            print(f"  {name}/{d}: notes={c['notes']} meter={c['meter']} "
                  f"jumps={c['jumps']} holds={c['holds']} critic={crit}")
        pack = f"GemmaTest_{name}"
        dest = clone_to_pack(base, title, config.STEPMANIA_DIR / base, PACK_ROOT / pack)
        print(f"  -> cloned to pack '{pack}'  ({time.monotonic()-t0:.0f}s)")
    except Exception as e:
        print(f"  {name} BUILD ERROR: {str(e)[:280]}")
print(f"\nregistered base: {base}")
