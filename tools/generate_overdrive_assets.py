#!/usr/bin/env python3
"""Generate OVERDRIVE art (Imagen 3) + high-energy synthwave music (Lyria) on Vertex.

OVERDRIVE is a 3-lane neon rhythm HIGHWAY: notes rush down a perspective
synthwave road toward a hit-line. We generate parallax background layers and a
couple of driving synthwave tracks. Lanes / notes / grid are drawn procedurally
in-engine, so this only needs the deep-background atmosphere.

Writes to BOTH assets/ (source of truth) and public/assets/ (served by Vite).
Idempotent: skips anything already present. Safe to re-run.
"""
import base64, io, json, os, shutil, subprocess, sys, time, wave
from PIL import Image, ImageFilter

PROJECT = os.environ.get("VERTEX_PROJECT", "sweet-papa-technologies")
LOCATION = "us-central1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}/publishers/google/models"


def token():
    return subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()


def post(model, body):
    import urllib.request
    req = urllib.request.Request(
        f"{BASE}/{model}:predict",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


# ---------- image ----------
def gen_image(prompt, aspect):
    body = {"instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": aspect, "personGeneration": "dont_allow"}}
    d = post("imagen-3.0-generate-002", body)
    b64 = d["predictions"][0]["bytesBase64Encoded"]
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")


def save_png(img, rel, max_w=None):
    if max_w and img.width > max_w:
        h = round(img.height * max_w / img.width)
        img = img.resize((max_w, h), Image.LANCZOS)
    for base in ("assets", "public/assets"):
        path = os.path.join(ROOT, base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path)
    print(f"  wrote {rel} ({img.width}x{img.height})", flush=True)


# Deep background only — the road grid, lanes, notes, hit-line are procedural.
IMAGES = [
    ("sprites/od_sky.png",
     "wide synthwave retrowave sky background, deep indigo-to-magenta vertical gradient, a huge glowing retro sun with horizontal scanline bands sitting low on the horizon, soft pink and cyan atmospheric haze, scattered bright stars, dreamy outrun aesthetic, no ground, no grid, no road, no characters, no text, flat clean digital illustration, seamless horizontal tile",
     "16:9", 1600),
    ("sprites/od_ridge.png",
     "distant neon wireframe mountain ridge silhouette against transparent dark sky, glowing cyan and magenta outline peaks, retrowave outrun horizon layer, very dark near-black base, no sun, no grid, no characters, no text, flat clean illustration, seamless horizontal tile",
     "16:9", 1600),
    ("sprites/od_city.png",
     "row of distant glowing neon skyscraper silhouettes, cyberpunk synthwave city skyline at night, teal and magenta window lights, dark base, parallax midground layer, no foreground road, no characters, no text, flat clean illustration, seamless horizontal tile",
     "16:9", 1600),
]


# ---------- music ----------
TRACKS = [
    ("tracks/overdrive_pulse.wav",
     "high energy driving synthwave instrumental, pulsing analog bass arpeggio, punchy four-on-the-floor electronic drums, bright lead synth, retro outrun night drive, steady 120 bpm, euphoric and propulsive"),
    ("tracks/midnight_run.wav",
     "energetic darksynth retrowave instrumental, gated reverb drums, gritty saw bass, soaring neon lead, cyberpunk chase momentum, steady 128 bpm, intense and cinematic"),
]


def gen_music(prompt):
    d = post("lyria-002", {"instances": [{"prompt": prompt}], "parameters": {}})
    return base64.b64decode(d["predictions"][0]["bytesBase64Encoded"])


def wav_duration(path):
    with wave.open(path, "rb") as w:
        return round(w.getnframes() / float(w.getframerate()), 3)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"

    if which in ("all", "images"):
        print("== images ==", flush=True)
        for rel, prompt, aspect, max_w in IMAGES:
            if os.path.exists(os.path.join(ROOT, "public/assets", rel)):
                print(f"  skip {rel} (exists)", flush=True)
                continue
            for attempt in range(5):
                try:
                    img = gen_image(prompt, aspect)
                    save_png(img, rel, max_w)
                    break
                except Exception as e:
                    wait = 8 * (attempt + 1)
                    print(f"  retry {rel} in {wait}s ({e})", flush=True)
                    time.sleep(wait)
            time.sleep(5)

    if which in ("all", "music"):
        print("== music ==", flush=True)
        manifest = {"tracks": []}
        for rel, prompt in TRACKS:
            ogg_rel = rel.rsplit(".", 1)[0] + ".ogg"
            if os.path.exists(os.path.join(ROOT, "public/assets", ogg_rel)):
                print(f"  skip {ogg_rel} (exists)", flush=True)
                continue
            try:
                data = gen_music(prompt)
                tmp = os.path.join(ROOT, "assets", rel)
                os.makedirs(os.path.dirname(tmp), exist_ok=True)
                with open(tmp, "wb") as f:
                    f.write(data)
                dur = wav_duration(tmp)
                for base in ("assets", "public/assets"):
                    ogg = os.path.join(ROOT, base, ogg_rel)
                    os.makedirs(os.path.dirname(ogg), exist_ok=True)
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
                                    "-c:a", "libvorbis", "-q:a", "5", ogg], check=True)
                os.remove(tmp)
                print(f"  wrote {ogg_rel} ({dur}s)", flush=True)
                manifest["tracks"].append({"file": os.path.basename(ogg_rel), "duration": dur, "prompt": prompt})
            except Exception as e:
                print(f"  FAILED {rel}: {e}", flush=True)
        with open(os.path.join(ROOT, "assets/tracks/_overdrive_manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

    print("DONE", flush=True)


if __name__ == "__main__":
    main()
