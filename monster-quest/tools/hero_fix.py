#!/usr/bin/env python3
"""Relaxed key for the hero: remove the muted-green chroma pocket trapped behind
the body while protecting his olive tunic (lower green dominance)."""
from PIL import Image, ImageFilter
im = Image.open("assets/sprites/hero.png").convert("RGBA")
px = im.load(); w, h = im.size; n = 0
for y in range(h):
    for x in range(w):
        r, g, b, a = px[x, y]
        if a == 0:
            continue
        # trapped chroma: green strongly dominant AND fairly bright, but not olive cloth
        if g > 110 and (g - r) > 50 and (g - b) > 50:
            px[x, y] = (r, g, b, 0); n += 1
im.putalpha(im.getchannel("A").filter(ImageFilter.GaussianBlur(0.6)))
im.save("assets/sprites/hero.png")
print("hero relaxed key removed", n, "px")
