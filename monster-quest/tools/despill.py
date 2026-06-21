#!/usr/bin/env python3
"""Edge-band green despill: removes the green chroma halo left by flood-fill cutout.
Only touches opaque pixels within a few px of a transparent pixel, so interior
art (hero's tunic, vine's body) is preserved."""
import sys
from PIL import Image

def despill(path):
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = im.load()
    a = [[px[x, y][3] for x in range(w)] for y in range(h)]
    # distance (in steps) to nearest transparent pixel, capped at 3
    INF = 99
    dist = [[0 if a[y][x] < 24 else INF for x in range(w)] for y in range(h)]
    for _ in range(3):
        changed = False
        for y in range(h):
            for x in range(w):
                if dist[y][x] == INF:
                    m = INF
                    if x > 0:   m = min(m, dist[y][x-1])
                    if x < w-1: m = min(m, dist[y][x+1])
                    if y > 0:   m = min(m, dist[y-1][x])
                    if y < h-1: m = min(m, dist[y+1][x])
                    if m + 1 < dist[y][x]:
                        dist[y][x] = m + 1; changed = True
        if not changed: break
    cleaned = 0
    for y in range(h):
        for x in range(w):
            r, g, b, al = px[x, y]
            if al == 0:
                continue
            d = dist[y][x]
            spill = g - max(r, b)
            if d <= 2 and spill > 18:           # edge ring & greenish -> despill
                ng = max(r, b)
                if spill > 90 and d <= 1:        # hard halo -> drop it
                    px[x, y] = (r, ng, b, 0); cleaned += 1
                else:
                    px[x, y] = (r, ng, b, al); cleaned += 1
            elif al < 235 and spill > 40:        # stray semi-transparent green wisp
                px[x, y] = (r, max(r, b), b, al // 2); cleaned += 1
    im.save(path)
    return cleaned

if __name__ == "__main__":
    for p in sys.argv[1:]:
        n = despill(p)
        print(f"despilled {p}: {n} px")
