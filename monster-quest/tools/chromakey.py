#!/usr/bin/env python3
"""Global bright-green chroma key. Removes saturated chroma-green pixels anywhere
(including regions enclosed by the subject that edge flood-fill missed), while
leaving muted/olive greens (clothing, foliage creatures) intact. Then feathers
the new alpha edge by 1px for a clean composite."""
import sys
from PIL import Image, ImageFilter

def key(path):
    im = Image.open(path).convert("RGBA")
    px = im.load()
    w, h = im.size
    removed = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            # saturated chroma green: green clearly dominant & bright
            if g > 135 and (g - r) > 55 and (g - b) > 55:
                px[x, y] = (r, g, b, 0); removed += 1
            else:
                # light despill anywhere green slightly leads
                sp = g - max(r, b)
                if sp > 30:
                    px[x, y] = (r, max(r, b) + sp // 4, b, a)
    # feather alpha edge slightly to kill jaggies
    alpha = im.getchannel("A").filter(ImageFilter.GaussianBlur(0.6))
    im.putalpha(alpha)
    im.save(path)
    return removed

if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(f"keyed {p}: {key(p)} px removed")
