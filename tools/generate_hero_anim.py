#!/usr/bin/env python3
"""Generate a consistent hero animation set by EDITING the base hero with
Gemini 2.5 Flash Image (nano banana). Each frame is cut to transparent and
normalized (trimmed + bottom-center aligned on a fixed canvas) so the run cycle
doesn't jitter."""
import base64, json, os, subprocess, time, urllib.request
from collections import deque
import numpy as np
from PIL import Image, ImageFilter

PROJECT = os.environ.get("VERTEX_PROJECT", "sweet-papa-technologies")
LOCATION = "us-central1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPRITES = os.path.join(ROOT, "assets", "sprites")
MODEL = "gemini-2.5-flash-image"
URL = (f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
       f"/locations/{LOCATION}/publishers/google/models/{MODEL}:generateContent")
CANVAS = 512
THRESH = 62.0

BASE_DESC = ("the SAME chibi robot runner character, identical design and colors: "
             "glowing cyan visor, magenta and silver accents, chunky limbs, "
             "side view facing right. Keep the style and proportions identical. "
             "Place it isolated on a solid flat pure green #00FF00 background. "
             "Output only the image.")

FRAMES = [
    ("hero_run2", "Show it in the OPPOSITE running stride: the other leg forward, arms swapped. " + BASE_DESC),
    ("hero_run3", "Show it mid-run with both legs passing close together under the body, a slight upward bounce. " + BASE_DESC),
    ("hero_run4", "Show it in a wide fast leaping running stride, legs far apart, leaning forward. " + BASE_DESC),
    ("hero_jump", "Show it in a dynamic mid-air JUMP: knees tucked up, arms raised triumphantly, joyful. " + BASE_DESC),
    ("hero_duck", "Show it in a low DUCK / baseball-slide: crouched and leaning back close to the ground, one arm trailing. " + BASE_DESC),
    ("hero_strike", "Show it in a dynamic STRIKE: punching one glowing fist forward with energy and motion. " + BASE_DESC),
]

def token():
    return subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()

def edit(base_b64, prompt):
    body = {
        "contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": "image/png", "data": base_b64}},
            {"text": prompt},
        ]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                headers={"Authorization": f"Bearer {token()}",
                                         "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    for p in d["candidates"][0]["content"]["parts"]:
        if "inlineData" in p:
            return Image.open(__import__("io").BytesIO(base64.b64decode(p["inlineData"]["data"]))).convert("RGBA")
    raise RuntimeError("no image in response")

def cut_and_normalize(img):
    a = np.array(img)
    h, w = a.shape[:2]
    rgb = a[..., :3].astype(np.float32)
    frame = np.concatenate([rgb[0:6].reshape(-1, 3), rgb[h-6:h].reshape(-1, 3),
                            rgb[:, 0:6].reshape(-1, 3), rgb[:, w-6:w].reshape(-1, 3)])
    bg = np.median(frame, axis=0)
    similar = np.sqrt(((rgb - bg) ** 2).sum(axis=2)) < THRESH
    removed = np.zeros((h, w), bool)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if similar[y, x] and not removed[y, x]:
                removed[y, x] = True; q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if similar[y, x] and not removed[y, x]:
                removed[y, x] = True; q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not removed[ny, nx] and similar[ny, nx]:
                removed[ny, nx] = True; q.append((ny, nx))
    a[..., 3][removed] = 0
    res = Image.fromarray(a, "RGBA")
    res.putalpha(res.split()[3].filter(ImageFilter.GaussianBlur(0.8)))

    # trim to content bbox, then paste bottom-centered on a square canvas
    bbox = res.getbbox()
    if bbox:
        res = res.crop(bbox)
    scale = min((CANVAS - 40) / res.width, (CANVAS - 30) / res.height, 1.0)
    if scale < 1.0:
        res = res.resize((max(1, int(res.width * scale)), max(1, int(res.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    x = (CANVAS - res.width) // 2
    y = CANVAS - res.height - 12  # feet near the bottom
    canvas.alpha_composite(res, (x, y))
    return canvas

def main():
    base_b64 = base64.b64encode(open(os.path.join(SPRITES, "hero.png"), "rb").read()).decode()

    # normalize the existing base as run1
    run1 = cut_and_normalize(Image.open(os.path.join(SPRITES, "hero.png")).convert("RGBA"))
    run1.save(os.path.join(SPRITES, "hero_run1.png"))
    print("  wrote hero_run1 (from base)", flush=True)

    for key, prompt in FRAMES:
        out = os.path.join(SPRITES, f"{key}.png")
        if os.path.exists(out):
            print(f"  skip {key}", flush=True); continue
        for attempt in range(5):
            try:
                img = edit(base_b64, prompt)
                cut_and_normalize(img).save(out)
                print(f"  wrote {key}", flush=True)
                break
            except Exception as e:
                wait = 8 * (attempt + 1)
                print(f"  retry {key} in {wait}s ({e})", flush=True)
                time.sleep(wait)
        time.sleep(7)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
