# -*- coding: utf-8 -*-
r"""把若干区域放大拼成一张图（带编号），一次 read 就能看清细节。

用法
    python zoom_regions.py --src refs\\R2.png --crop 17,8,19,24 \
        --regions "[[0,0,462,40],[10,60,220,165],[20,130,210,205],[220,30,410,150],[30,500,420,560]]" \
        --out _zoom_R2.png --scale 3
"""
import os
import json
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "assets", "NotoSansSC-VF.ttf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--crop", default="0,0,0,0")
    ap.add_argument("--regions", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=float, default=3.0)
    a = ap.parse_args()

    t, b, l, r = [int(v) for v in a.crop.split(",")]
    A = Image.open(a.src).convert("RGB")
    W0, H0 = A.size
    A = A.crop((l, t, W0 - r if r else W0, H0 - b if b else H0))

    regions = json.loads(a.regions)
    try:
        f = ImageFont.truetype(FONT, 16)
    except Exception:
        f = ImageFont.load_default()

    tiles = []
    for i, reg in enumerate(regions):
        x0, y0, x1, y1 = [int(v) for v in reg]
        c = A.crop((x0, y0, x1, y1))
        s = a.scale
        c = c.resize((max(1, int(c.width * s)), max(1, int(c.height * s))), Image.LANCZOS)
        lab = Image.new("RGB", (c.width, 24), (20, 20, 20))
        d = ImageDraw.Draw(lab)
        d.text((4, 3), "#%d  %s" % (i, reg), font=f, fill=(255, 230, 0))
        tile = Image.new("RGB", (c.width, c.height + 24), (0, 0, 0))
        tile.paste(lab, (0, 0))
        tile.paste(c, (0, 24))
        tiles.append(tile)

    gap = 10
    Wsum = sum(t.width for t in tiles) + gap * (len(tiles) - 1)
    Hsum = max(t.height for t in tiles)
    out = Image.new("RGB", (Wsum, Hsum), (40, 40, 40))
    x = 0
    for t in tiles:
        out.paste(t, (x, 0))
        x += t.width + gap
    out.save(a.out)
    print("wrote", a.out, out.size)


if __name__ == "__main__":
    main()
