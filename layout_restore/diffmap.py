# -*- coding: utf-8 -*-
r"""差异地图：把重建图与原图的差异按块统计，回答「剩下的误差到底在哪」。

用法
    python diffmap.py --spec specs/R3.json --render r3_rebuild\_render_px.png [--exclude-text]
"""
import argparse
import json
import os

import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--render", required=True)
    ap.add_argument("--exclude-text", action="store_true")
    ap.add_argument("--block", type=int, default=40)
    a = ap.parse_args()

    spec = json.load(open(a.spec, encoding="utf-8"))
    src = spec["src"]
    t, b, l, r = spec.get("crop", [0, 0, 0, 0])
    raw = np.asarray(Image.open(src).convert("RGB")).astype(np.int16)
    H0, W0 = raw.shape[:2]
    O = raw[t:H0 - b if b else H0, l:W0 - r if r else W0]
    B = np.asarray(Image.open(a.render).convert("RGB")).astype(np.int16)
    H, W = O.shape[:2]
    if B.shape[:2] != (H, W):
        print("size mismatch", O.shape, B.shape)
        return
    d = np.abs(O - B).max(axis=2)

    m = np.zeros((H, W), bool)
    if a.exclude_text:
        for e in spec["text"]:
            x0, y0, x1, y1 = e["box"]
            m[max(0, y0 - 8):y1 + 8, max(0, x0 - 8):x1 + 8] = True
    rest = d.copy()
    rest[m] = 0

    print("total diff>20 : %d px (%.2f%%)   non-text: %d px (%.2f%%)   max=%d"
          % ((d > 20).sum(), 100.0 * (d > 20).sum() / d.size,
             (rest > 20).sum(), 100.0 * (rest > 20).sum() / d.size, rest.max()))
    print("\n-- 差异最重的块（%dx%d 网格）--" % (a.block, a.block))
    rows = []
    for by in range(0, H, a.block):
        for bx in range(0, W, a.block):
            blk = rest[by:by + a.block, bx:bx + a.block]
            n = int((blk > 20).sum())
            if n > 60:
                rows.append((n, bx, by, int(blk.max())))
    rows.sort(reverse=True)
    for n, bx, by, mx in rows[:20]:
        print("   x=%4d y=%4d  n>20=%5d  max=%3d" % (bx, by, n, mx))
    if not rows:
        print("   （无超过 60 px 的块）")


if __name__ == "__main__":
    main()
