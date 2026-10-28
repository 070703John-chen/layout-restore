# -*- coding: utf-8 -*-
r"""在指定区域内，量出「与区域主背景色不同」的像素包围盒 —— 用来定美术素材的准确裁切框。

用法
    python bbox_fg.py --src refs\\R2.png --crop 17,8,19,24 --region 228,60,410,160 --tol 26
"""
import argparse
import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--crop", default="0,0,0,0")
    ap.add_argument("--region", required=True)
    ap.add_argument("--tol", type=int, default=26)
    ap.add_argument("--dump", default=None, help="逐行输出前景列范围")
    a = ap.parse_args()

    t, b, l, r = [int(v) for v in a.crop.split(",")]
    A = np.asarray(Image.open(a.src).convert("RGB")).astype(np.int16)
    H0, W0 = A.shape[:2]
    A = A[t:H0 - b if b else H0, l:W0 - r if r else W0]
    x0, y0, x1, y1 = [int(v) for v in a.region.split(",")]
    reg = A[y0:y1, x0:x1]

    flat = reg.reshape(-1, 3)
    cols, counts = np.unique(flat, axis=0, return_counts=True)
    bg = cols[int(np.argmax(counts))]
    d = np.abs(reg - bg).max(axis=2)
    fg = d > a.tol
    ys, xs = np.nonzero(fg)
    if len(xs) == 0:
        print("no foreground")
        return
    print("bg=#%02X%02X%02X  fg_px=%d" % (bg[0], bg[1], bg[2], len(xs)))
    print("bbox in canvas = [%d, %d, %d, %d]  (region was %s)" %
          (x0 + xs.min(), y0 + ys.min(), x0 + xs.max() + 1, y0 + ys.max() + 1,
           a.region))
    if a.dump:
        rows = np.nonzero(fg.any(axis=1))[0]
        for yy in rows:
            xr = np.nonzero(fg[yy])[0]
            print("  y=%4d  x %4d..%4d  (%d px)" %
                  (y0 + yy, x0 + xr.min(), x0 + xr.max(), len(xr)))


if __name__ == "__main__":
    main()
