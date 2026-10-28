# -*- coding: utf-8 -*-
r"""在指定区域里，按目标色找连通域，输出每个文字块的精确包围盒。

OCR 框不准（会把相邻两段合并、会溢出），人工标注要的是「墨迹块」的真实范围，
这个脚本直接量像素，不用肉眼。

用法
    python cc_color.py --src refs\\R2.png --crop 17,8,19,24 \
        --region 0,0,280,34 --color "#FFFFFF" --tol 60 --merge 6
"""
import argparse
import numpy as np
import cv2
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--crop", default="0,0,0,0")
    ap.add_argument("--region", required=True)
    ap.add_argument("--color", required=True)
    ap.add_argument("--tol", type=int, default=60)
    ap.add_argument("--minarea", type=int, default=12)
    ap.add_argument("--merge", type=int, default=6, help="横向间距小于该值的块合并")
    ap.add_argument("--grow", type=int, default=0, help="包围盒向外扩 N px")
    a = ap.parse_args()

    t, b, l, r = [int(v) for v in a.crop.split(",")]
    A = np.asarray(Image.open(a.src).convert("RGB")).astype(np.int16)
    H0, W0 = A.shape[:2]
    A = A[t:H0 - b if b else H0, l:W0 - r if r else W0]
    x0, y0, x1, y1 = [int(v) for v in a.region.split(",")]
    reg = A[y0:y1, x0:x1]

    c = a.color.lstrip("#")
    tgt = np.array([int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)], np.int16)
    d = np.abs(reg - tgt).max(axis=2)
    mask = (d < a.tol).astype(np.uint8) * 255

    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for k in range(1, n):
        area = int(stats[k, cv2.CC_STAT_AREA])
        if area < a.minarea:
            continue
        bx, by, bw, bh = [int(v) for v in stats[k, :4]]
        boxes.append([x0 + bx, y0 + by, x0 + bx + bw, y0 + by + bh, area])
    boxes.sort(key=lambda z: z[0])

    # 横向合并
    merged = []
    for bx in boxes:
        if merged and bx[0] - merged[-1][2] <= a.merge:
            m = merged[-1]
            m[0] = min(m[0], bx[0]); m[1] = min(m[1], bx[1])
            m[2] = max(m[2], bx[2]); m[3] = max(m[3], bx[3])
            m[4] += bx[4]
        else:
            merged.append(list(bx))

    print("color=%s tol=%d region=%s  -> %d block(s)" %
          (a.color, a.tol, a.region, len(merged)))
    for bx in merged:
        g = a.grow
        print("   [%4d, %4d, %4d, %4d]  w=%3d h=%3d px=%5d" %
              (bx[0] - g, bx[1] - g, bx[2] + g, bx[3] + g,
               bx[2] - bx[0], bx[3] - bx[1], bx[4]))


if __name__ == "__main__":
    main()
