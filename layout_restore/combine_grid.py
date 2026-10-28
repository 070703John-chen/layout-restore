# -*- coding: utf-8 -*-
r"""探针结果叠加到坐标网格上：一张图同时给出 坐标 / 内容 / 字色 / 底色。

用法
    python combine_grid.py --grid _grid_R2.png --probe _probe_R2.json --out _ov_R2.png
"""
import os
import sys
import json
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "assets", "NotoSansSC-VF.ttf")


def hx(c):
    if not c:
        return (128, 128, 128)
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", required=True)
    ap.add_argument("--probe", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default=None, help="只显示这些编号，逗号分隔")
    a = ap.parse_args()

    grid = Image.open(a.grid).convert("RGB")
    rep = json.load(open(a.probe, encoding="utf-8"))
    W, H = grid.size
    if (rep["canvas"][0], rep["canvas"][1]) != (W, H):
        print("!! grid %dx%d != probe canvas %s" % (W, H, rep["canvas"]))

    vis = grid.copy()
    d = ImageDraw.Draw(vis)
    try:
        f = ImageFont.truetype(FONT, 13)
        fs = ImageFont.truetype(FONT, 11)
    except Exception:
        f = fs = ImageFont.load_default()

    keep = None
    if a.only:
        keep = set(int(v) for v in a.only.split(","))

    for r in rep["rows"]:
        if keep is not None and r["i"] not in keep:
            continue
        x0, y0, x1, y1 = r["box"]
        col = hx(r.get("fill"))
        if r.get("stroke"):
            d.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], outline=col, width=3)
        else:
            d.rectangle([x0, y0, x1, y1], outline=col, width=2)
        # 编号
        tag = "#%d" % r["i"]
        bb = d.textbbox((0, 0), tag, font=f)
        d.rectangle([x0, max(0, y0 - 16), x0 + bb[2] - bb[0] + 6, max(14, y0)],
                    fill=(255, 255, 0))
        d.text((x0 + 3, max(0, y0 - 15)), tag, font=f, fill=(0, 0, 0))
        # 色块
        d.rectangle([x0, y1 + 1, x0 + 12, y1 + 11], fill=col)
        if r.get("bg"):
            d.rectangle([x0 + 14, y1 + 1, x0 + 26, y1 + 11], fill=hx(r["bg"]))
        # 内容
        t = str(r["text"])[:18]
        if t:
            d.text((x0 + 28, y1 - 1), t, font=fs,
                   fill=(255, 255, 255) if sum(col) < 300 else (0, 0, 0))

    # 色块候选
    for b in rep.get("blocks", [])[:12]:
        d.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]],
                    outline=(255, 0, 255), width=2)
        d.text((b["x"] + 3, b["y"] + 3), "P", font=f, fill=(255, 0, 255))

    vis.save(a.out)
    print("wrote", a.out, vis.size)


if __name__ == "__main__":
    main()
