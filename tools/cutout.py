#!/usr/bin/env python3
"""Remove a uniform, edge-connected background from sprite PNGs via flood fill
from the borders. Robust to any solid-ish bg color (Imagen ignored chroma green)."""
import os, sys
from collections import deque
import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = ["hero", "ob_gap", "ob_bar", "ob_note"]
THRESH = 62.0

def cutout(path):
    img = Image.open(path).convert("RGBA")
    a = np.array(img)
    h, w = a.shape[:2]
    rgb = a[..., :3].astype(np.float32)

    # background color = median of a border frame
    frame = np.concatenate([
        rgb[0:6, :, :].reshape(-1, 3), rgb[h - 6:h, :, :].reshape(-1, 3),
        rgb[:, 0:6, :].reshape(-1, 3), rgb[:, w - 6:w, :].reshape(-1, 3),
    ])
    bg = np.median(frame, axis=0)

    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
    similar = dist < THRESH

    removed = np.zeros((h, w), dtype=bool)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if similar[y, x] and not removed[y, x]:
                removed[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if similar[y, x] and not removed[y, x]:
                removed[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not removed[ny, nx] and similar[ny, nx]:
                removed[ny, nx] = True
                q.append((ny, nx))

    alpha = a[..., 3].copy()
    alpha[removed] = 0
    out = a.copy()
    out[..., 3] = alpha
    res = Image.fromarray(out, "RGBA")
    # feather + slight erode of halo
    am = res.split()[3].filter(ImageFilter.GaussianBlur(0.8))
    res.putalpha(am)
    res.save(path)
    kept = int((alpha > 0).sum())
    print(f"  cut {os.path.basename(path)} bg~{bg.astype(int).tolist()} kept {kept*100//(h*w)}%", flush=True)

def main():
    names = sys.argv[1:] or TARGETS
    for n in names:
        p = os.path.join(ROOT, "assets", "sprites", f"{n}.png")
        if os.path.exists(p):
            cutout(p)
        else:
            print(f"  missing {p}", flush=True)

if __name__ == "__main__":
    main()
