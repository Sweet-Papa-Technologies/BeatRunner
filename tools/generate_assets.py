#!/usr/bin/env python3
"""Generate In the Pocket art (Imagen 3) + music (Lyria) on Vertex AI.

Idempotent-ish: writes into assets/. Safe to re-run. Requires a gcloud access
token (active account must have aiplatform.user on the project).
"""
import base64, io, json, os, subprocess, sys, wave
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
            "parameters": {"sampleCount": 1, "aspectRatio": aspect, "personGeneration": "allow_all"}}
    d = post("imagen-3.0-generate-002", body)
    b64 = d["predictions"][0]["bytesBase64Encoded"]
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")

def chroma_key(img):
    """Remove a solid green background -> transparent, with a soft edge."""
    import numpy as np
    a = np.array(img).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    greenness = g - np.maximum(r, b)
    mask = (greenness > 50) & (g > 110)
    a[..., 3] = np.where(mask, 0, a[..., 3])
    # de-spill: pull green toward gray on semi-edges
    spill = (greenness > 15) & (greenness <= 50)
    a[..., 1] = np.where(spill, np.maximum(r, b), g)
    out = Image.fromarray(a.astype("uint8"), "RGBA")
    # feather alpha slightly
    alpha = out.split()[3].filter(ImageFilter.GaussianBlur(0.6))
    out.putalpha(alpha)
    return out

def save_png(img, rel, max_w=None):
    if max_w and img.width > max_w:
        h = round(img.height * max_w / img.width)
        img = img.resize((max_w, h), Image.LANCZOS)
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print(f"  wrote {rel} ({img.width}x{img.height})", flush=True)

IMAGES = [
    # (filename, prompt, aspect, keyed, max_w)
    ("assets/sprites/bg_sky.png",
     "wide 2.5D parallax BACKGROUND layer for a neon lo-fi night city, deep indigo to purple gradient sky, distant glowing skyline silhouette, soft bloom stars, retro synthwave, no characters, no text, flat illustration, seamless",
     "16:9", False, 1536),
    ("assets/sprites/bg_city.png",
     "wide parallax MIDGROUND layer, rows of neon cyberpunk buildings glowing teal and magenta, foggy haze, lo-fi vaporwave, transparent feel, dark base, no characters, no text, flat illustration",
     "16:9", False, 1536),
    ("assets/sprites/bg_near.png",
     "wide parallax FOREGROUND ground strip, dark neon-lit road with glowing magenta edge lines and reflective wet asphalt, lo-fi synthwave, no characters, no text, flat illustration",
     "16:9", False, 1536),
    ("assets/sprites/hero.png",
     "cute small chibi robot runner character mid-stride, glowing cyan visor, neon magenta accents, side profile facing right, energetic, simple clean vector mascot, isolated on SOLID CHROMA KEY GREEN background #00FF00, no shadow, no text",
     "1:1", True, 512),
    ("assets/sprites/ob_gap.png",
     "a low glowing hazard pit warning marker, neon red and orange energy spikes low to the ground, side view, simple game obstacle icon, isolated on SOLID CHROMA KEY GREEN background #00FF00, no text",
     "1:1", True, 384),
    ("assets/sprites/ob_bar.png",
     "a horizontal glowing neon overhead barrier bar, electric blue and white energy, side view game obstacle, isolated on SOLID CHROMA KEY GREEN background #00FF00, no text",
     "1:1", True, 384),
    ("assets/sprites/ob_note.png",
     "a single glowing musical note orb, bright yellow and magenta neon, sparkles, floating, side view game collectible, isolated on SOLID CHROMA KEY GREEN background #00FF00, no text",
     "1:1", True, 384),
    ("assets/sprites/glow.png",
     "a soft round radial glow particle, pure white center fading to transparent black edges, on solid BLACK background, for additive blending, no text",
     "1:1", False, 256),
]

# ---------- music ----------
TRACKS = [
    ("assets/tracks/sweetpapa_groove.wav",
     "warm chill lo-fi hip hop instrumental, mellow Rhodes piano, soft vinyl crackle, laid-back boom-bap drums, steady 88 bpm, cozy night vibe"),
    ("assets/tracks/neon_nights.wav",
     "dreamy synthwave lo-fi beat, glowing analog synth pads, gentle arpeggio, steady 92 bpm, neon city night, relaxed groove"),
]

def gen_music(prompt):
    d = post("lyria-002", {"instances": [{"prompt": prompt}], "parameters": {}})
    return base64.b64decode(d["predictions"][0]["bytesBase64Encoded"])

def wav_duration(path):
    with wave.open(path, "rb") as w:
        return round(w.getnframes() / float(w.getframerate()), 3)

def main():
    manifest = {"tracks": []}
    which = sys.argv[1] if len(sys.argv) > 1 else "all"

    if which in ("all", "images"):
        import time
        print("== images ==", flush=True)
        for rel, prompt, aspect, keyed, max_w in IMAGES:
            if os.path.exists(os.path.join(ROOT, rel)):
                print(f"  skip {rel} (exists)", flush=True)
                continue
            for attempt in range(5):
                try:
                    img = gen_image(prompt, aspect)
                    if keyed:
                        img = chroma_key(img)
                    save_png(img, rel, max_w)
                    break
                except Exception as e:
                    wait = 8 * (attempt + 1)
                    print(f"  retry {rel} in {wait}s ({e})", flush=True)
                    time.sleep(wait)
            time.sleep(6)  # throttle between images

    if which in ("all", "music"):
        print("== music ==", flush=True)
        for rel, prompt in TRACKS:
            try:
                data = gen_music(prompt)
                path = os.path.join(ROOT, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
                dur = wav_duration(path)
                ogg = path.rsplit(".", 1)[0] + ".ogg"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                                "-c:a", "libvorbis", "-q:a", "5", ogg], check=True)
                os.remove(path)
                print(f"  wrote {rel.replace('.wav','.ogg')} ({dur}s)", flush=True)
                manifest["tracks"].append({"file": os.path.basename(ogg), "duration": dur, "prompt": prompt})
            except Exception as e:
                print(f"  FAILED {rel}: {e}", flush=True)
        with open(os.path.join(ROOT, "assets/tracks/_manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)
        print("  wrote assets/tracks/_manifest.json", flush=True)

    print("DONE", flush=True)

if __name__ == "__main__":
    main()
