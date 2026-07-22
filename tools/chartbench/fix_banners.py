"""fix_banners.py — make generated art usable as StepMania assets.

Two problems with raw Imagen output:

  1. Asking for a "wide banner composition" makes the model draw literal
     letterbox bars — flat white/black strips top and bottom. In a song wheel
     that reads as a broken image, so they get cropped off.
  2. StepMania banners are ~2:1 and backgrounds ~16:9. Feeding it a raw 16:9
     banner leaves the wheel to squash it.

So: trim uniform borders, centre-crop to the target aspect, resize.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

BANNER = (512, 256)      # 2:1, the ITGmania wheel banner
BG = (1280, 720)         # 16:9


def trim_uniform_borders(im: Image.Image, tol: int = 12) -> Image.Image:
    """Drop flat rows/cols at the edges (the letterbox bars), keep the art."""
    g = im.convert("RGB")
    w, h = g.size
    px = g.load()

    def flat_row(y):
        r0, g0, b0 = px[0, y]
        return all(abs(px[x, y][0] - r0) <= tol and abs(px[x, y][1] - g0) <= tol
                   and abs(px[x, y][2] - b0) <= tol for x in range(0, w, max(1, w // 60)))

    def flat_col(x):
        r0, g0, b0 = px[x, 0]
        return all(abs(px[x, y][0] - r0) <= tol and abs(px[x, y][1] - g0) <= tol
                   and abs(px[x, y][2] - b0) <= tol for y in range(0, h, max(1, h // 60)))

    top = 0
    while top < h - 1 and flat_row(top):
        top += 1
    bot = h - 1
    while bot > top and flat_row(bot):
        bot -= 1
    left = 0
    while left < w - 1 and flat_col(left):
        left += 1
    right = w - 1
    while right > left and flat_col(right):
        right -= 1
    if right - left < w * 0.3 or bot - top < h * 0.15:
        return im                                    # refused: would gut the image
    return im.crop((left, top, right + 1, bot + 1))


def fit(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    tw, th = size
    w, h = im.size
    target, cur = tw / th, w / h
    if cur > target:                                  # too wide -> crop sides
        nw = int(h * target)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:                                             # too tall -> crop top/bottom
        nh = int(w / target)
        im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return im.resize(size, Image.LANCZOS)


def process(path: Path) -> str:
    im = Image.open(path)
    before = im.size
    im = trim_uniform_borders(im)
    im = fit(im, BANNER if "banner" in path.name else BG)
    im.save(path)
    return f"{path.name}: {before} -> {im.size}"


if __name__ == "__main__":
    d = Path(sys.argv[1])
    for p in sorted(d.glob("*.png")):
        print(" ", process(p))
