# -*- coding: utf-8 -*-
r"""量一段文字的墨迹颜色分布（分上下几段），用来判断是不是渐变填充。

用法
    python sample_ink.py --src refs\\R4.png --box 241,162,996,466 --mode bright --bands 4
"""
import argparse
import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--crop", default="0,0,0,0")
    ap.add_argument("--box", required=True)
    ap.add_argument("--mode", default="bright", choices=["bright", "dark"])
    ap.add_argument("--bands", type=int, default=4)
    ap.add_argument("--tol", type=int, default=40)
    a = ap.parse_args()

    t, b, l, r = [int(v) for v in a.crop.split(",")]
    A = np.asarray(Image.open(a.src).convert("RGB")).astype(np.int16)
    H0, W0 = A.shape[:2]
    A = A[t:H0 - b if b else H0, l:W0 - r if r else W0]
    x0, y0, x1, y1 = [int(v) for v in a.box.split(",")]
    reg = A[y0:y1, x0:x1]
    v = reg.max(axis=2)
    m = (v > 150) if a.mode == "bright" else (v < 90)
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        print("no ink")
        return
    print("ink px = %d  y range %d..%d" % (len(ys), y0 + ys.min(), y0 + ys.max()))
    h = ys.max() - ys.min() + 1
    for i in range(a.bands):
        lo = ys.min() + int(h * i / a.bands)
        hi = ys.min() + int(h * (i + 1) / a.bands)
        sel = (ys >= lo) & (ys < hi)
        if sel.sum() < 20:
            continue
        px = reg[ys[sel], xs[sel]]
        med = np.median(px, axis=0).astype(int)
        p90 = np.percentile(px, 85, axis=0).astype(int)
        print("  band %d (y %d..%d) n=%5d  median=#%02X%02X%02X  p85=#%02X%02X%02X"
              % (i, y0 + lo, y0 + hi, sel.sum(),
                 med[0], med[1], med[2], p90[0], p90[1], p90[2]))


if __name__ == "__main__":
    main()
