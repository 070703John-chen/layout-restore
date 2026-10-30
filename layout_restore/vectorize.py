# -*- coding: utf-8 -*-
"""淘宝图专用：矢量结构层检测（色块 rects + 线条 lines）

为什么单独写
    通用海报拆解（版式工程\\probe_layers.py）只需要「照片层 + 美术层 + 文字层」。
    电商图多一层刚需：**背景结构**——
      · 标题条 / 按钮 / 标签块（纯色矩形，可能压着白字）
      · 参数表的表格线、尺寸标注线（1~2px 细线）
    这两类如果不抽出来当矢量，文字挖掉后背景回填会把它拖糊，整张图的结构感就塌了。
    抽成矢量后 → 改色值、改宽度、改线型都是改一个数，不用重画。

输出（可直接并进 spec.json）
    rects: [{"id":"bar","box":[x0,y0,x1,y1],"fill":"#RRGGBB","rx":0,"opacity":1.0}]
    lines: [{"id":"ln0","x1":..,"y1":..,"x2":..,"y2":..,"stroke":"#RRGGBB","w":1,"dash":"4 3"}]

用法
    python tb_vec.py --src refs\\TB_F1_sec_005.jpg --probe _work\\probe\\_probe_TBF1.json \\
        --out specs\\TBF1.json --merge
"""
import os
import sys
import json
import argparse

import numpy as np
import cv2

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ------------------------------------------------------------------ 色块
def detect_rects(img_bgr, min_area_ratio=0.010, top_bins=14, fill_min=0.93,
                 max_cstd=12.0):
    H, W = img_bgr.shape[:2]
    area = float(H * W)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    lap = np.abs(cv2.Laplacian(gray, cv2.CV_64F))
    q = (img_bgr.astype(np.int32) // 16)
    key = q[:, :, 0] * 256 + q[:, :, 1] * 16 + q[:, :, 2]
    vals, counts = np.unique(key, return_counts=True)
    order = np.argsort(-counts)[:top_bins]

    out = []
    for vi in order:
        if counts[vi] < min_area_ratio * area / 6:
            continue
        mask = (key == vals[vi]).astype(np.uint8) * 255
        # 闭运算把被文字打断的色块接起来
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for k in range(1, n):
            a = int(stats[k, cv2.CC_STAT_AREA])
            if a < min_area_ratio * area:
                continue
            x, y, w, h = [int(v) for v in stats[k, :4]]
            fill = a / float(max(1, w * h))
            # 判据一：**直边矩形**（bbox 填充率）。
            #   产品灯面那种「平坦但形状是椭圆」的区域填充率只有 0.78，
            #   标题条这种真色块是 1.00 —— 这一条比任何边缘算子都可靠。
            if fill < fill_min:
                continue
            # 判据二：块内**色彩离散度**低（不用边缘算子）。
            #   边缘算子会被 JPEG 白字振铃骗（色块上压字 → 边缘密度高 → 误杀），
            #   色彩离散度只看色块自身的像素，不受压字影响。
            #   ⚠ 取色必须用**原始 bin 像素**，不能用形态学闭运算后的掩膜 ——
            #   闭运算会把色块上的白字笔画桥接进来（9×9 核足以跨过 3~6px 宽的字），
            #   于是白字被算进色块，cstd 从 4 飙到 39，真色块反被误杀。
            keyc = key[y:y + h, x:x + w]
            comp = (lab[y:y + h, x:x + w] == k) & (keyc == vals[vi])
            if comp.sum() < 50:
                continue
            px = img_bgr[y:y + h, x:x + w][comp].reshape(-1, 3)
            cstd = float(np.mean(px.std(axis=0)))
            if cstd > max_cstd:
                continue
            med = np.median(px, axis=0).astype(int)
            r, g, b = int(med[2]), int(med[1]), int(med[0])
            # 纯白 = 背景，跳过
            if r > 242 and g > 242 and b > 242:
                continue
            # 近黑且面积大 = 可能是深底图本身，跳过（交给照片层）
            if r < 22 and g < 22 and b < 22 and a > 0.35 * area:
                continue
            comp = (lab[y:y + h, x:x + w] == k)
            sub = lap[y:y + h, x:x + w][comp]
            rough = float(np.mean(sub)) if sub.size else 99.0
            out.append({"box": [x, y, x + w, y + h], "fill": "#%02X%02X%02X" % (r, g, b),
                        "area": a, "fill_ratio": round(fill, 3),
                        "rough": round(rough, 2), "cstd": round(cstd, 2),
                        "color": "#%02X%02X%02X" % (r, g, b)})
    # 去重（不同 bin 可能命中同一块）
    out.sort(key=lambda d: -d["area"])
    keep = []
    for d in out:
        dup = False
        for k2 in keep:
            ax0, ay0, ax1, ay1 = d["box"]
            bx0, by0, bx1, by1 = k2["box"]
            ix = max(0, min(ax1, bx1) - max(ax0, bx0))
            iy = max(0, min(ay1, by1) - max(ay0, by0))
            inter = ix * iy
            small = min(d["area"], k2["area"])
            if small > 0 and inter / small > 0.55:
                dup = True
                break
        if not dup:
            keep.append(d)
    return keep


# ------------------------------------------------------------------ 线条
def _text_hit_ratio(line, text_boxes):
    """这条线有多少比例落在文字框里（文字笔画会被当成竖线/横线）。"""
    if not text_boxes:
        return 0.0
    if line["axis"] == "h":
        ys = set(range(line["y1"], line["y2"] + 1))
        xs = range(line["x1"], line["x2"] + 1)
        pts = [(x, y) for y in ys for x in xs]
    else:
        xs = set(range(line["x1"], line["x2"] + 1))
        ys = range(line["y1"], line["y2"] + 1)
        pts = [(x, y) for y in ys for x in xs]
    if not pts:
        return 0.0
    hit = 0
    for (x, y) in pts:
        for (bx0, by0, bx1, by1) in text_boxes:
            if bx0 - 3 <= x <= bx1 + 3 and by0 - 3 <= y <= by1 + 3:
                hit += 1
                break
    return hit / float(len(pts))


def detect_lines(img_bgr, min_len_ratio=0.020, max_thick=4, text_boxes=None,
                 rects=None):
    """找表格线 / 标注线：细长 + 颜色统一 + 长度够。"""
    H, W = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    rect_boxes = [(r["box"][0], r["box"][1], r["box"][2], r["box"][3]) for r in (rects or [])]
    out = []
    for axis in ("h", "v"):
        # 非背景像素（比纯白明显暗或比纯黑明显亮）
        if axis == "h":
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, int(W * 0.03)), 1))
        else:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(9, int(H * 0.03))))
        dark = (gray < 235).astype(np.uint8) * 255
        op = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel)
        cnts, _ = cv2.findContours(op, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            if axis == "h":
                if w < min_len_ratio * W or h > max_thick:
                    continue
            else:
                if h < min_len_ratio * H or w > max_thick:
                    continue
            # 线色：取中段像素的中位数
            if axis == "h":
                yy = min(H - 1, max(0, y + h // 2))
                seg = img_bgr[yy, x:x + w].reshape(-1, 3)
            else:
                xx = min(W - 1, max(0, x + w // 2))
                seg = img_bgr[y:y + h, xx].reshape(-1, 3)
            if len(seg) == 0:
                continue
            med = np.median(seg, axis=0).astype(int)
            r, g, b = int(med[2]), int(med[1]), int(med[0])
            if r > 244 and g > 244 and b > 244:
                continue
            cand = {"axis": axis, "x1": x, "y1": y,
                    "x2": (x + w) if axis == "h" else (x + w - 1),
                    "y2": (y + h - 1) if axis == "h" else (y + h),
                    "stroke": "#%02X%02X%02X" % (r, g, b),
                    "w": max(1, h if axis == "h" else w),
                    "len": w if axis == "h" else h}
            # 文字笔画会伪装成线：落在文字框里的比例 >50% 就丢
            if _text_hit_ratio(cand, text_boxes or []) > 0.5:
                continue
            # 落在色块（标题条/标签块）里的线 = 压在色块上的字笔画，不是结构线
            mid = ((cand["x1"] + cand["x2"]) // 2, (cand["y1"] + cand["y2"]) // 2)
            inside_rect = False
            for (rx0, ry0, rx1, ry1) in rect_boxes:
                if rx0 <= mid[0] <= rx1 and ry0 <= mid[1] <= ry1:
                    inside_rect = True
                    break
            if inside_rect:
                continue
            out.append(cand)
    # 同轴同位置合并
    out.sort(key=lambda d: (d["axis"], d["x1"], d["y1"]))
    merged = []
    for d in out:
        same = False
        for m in merged:
            if (m["axis"] == d["axis"] and abs(m["x1"] - d["x1"]) <= 3
                    and abs(m["y1"] - d["y1"]) <= 3):
                m["x2"] = max(m["x2"], d["x2"])
                m["y2"] = max(m["y2"], d["y2"])
                same = True
                break
        if not same:
            merged.append(d)
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--probe", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--min-area", type=float, default=0.010)
    a = ap.parse_args()

    from PIL import Image
    raw = np.asarray(Image.open(a.src).convert("RGB")).astype(np.uint8)
    bgr = cv2.cvtColor(raw, cv2.COLOR_RGB2BGR)

    text_boxes = []
    if a.probe and os.path.exists(a.probe):
        pr = json.load(open(a.probe, encoding="utf-8"))
        for row in pr.get("rows", []):
            if row.get("src") == "ocr":
                text_boxes.append(tuple(row["box"]))
    print("文字框 %d 个（用于过滤笔画伪线）" % len(text_boxes))

    rects = detect_rects(bgr, min_area_ratio=a.min_area)
    lines = detect_lines(bgr, text_boxes=text_boxes, rects=rects)

    print("== 色块 rects (%d) ==" % len(rects))
    for i, r in enumerate(rects):
        print("  #%d box=%-26s %s  area=%d fill=%.2f rough=%.2f"
              % (i, r["box"], r["fill"], r["area"], r["fill_ratio"], r["rough"]))
    print("== 线条 lines (%d) ==" % len(lines))
    for i, l in enumerate(lines):
        print("  #%d %s (%d,%d)->(%d,%d) %s w=%d"
              % (i, l["axis"], l["x1"], l["y1"], l["x2"], l["y2"], l["stroke"], l["w"]))

    spec_rects = [{"id": "r%02d" % i, "box": r["box"], "fill": r["fill"],
                   "rx": 0, "opacity": 1.0} for i, r in enumerate(rects)]
    spec_lines = [{"id": "l%02d" % i, "x1": l["x1"], "y1": l["y1"],
                   "x2": l["x2"], "y2": l["y2"], "stroke": l["stroke"],
                   "w": l["w"]} for i, l in enumerate(lines)]

    if a.merge:
        spec = json.load(open(a.out, encoding="utf-8"))
        spec["rects"] = spec_rects
        spec["lines"] = spec_lines
        json.dump(spec, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("已并入 %s" % a.out)
    else:
        json.dump({"rects": spec_rects, "lines": spec_lines},
                  open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("已写 %s" % a.out)


if __name__ == "__main__":
    main()
