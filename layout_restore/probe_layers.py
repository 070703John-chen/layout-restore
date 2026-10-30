# -*- coding: utf-8 -*-
r"""人工分层探针 · 统一版（R2~R6 用）

为什么单独写：
    R1 复刻成功靠的是「人工标注」—— 但人工标注的前提是**先拿到靠谱的元素清单**。
    之前的 01_decompose.py 有三个硬伤：
      1) 不支持 4 边裁切（只裁顶部）→ R2/R3 的黑边坐标全错位
      2) OCR 漏检的字直接消失（深底细衬线 R4 只剩 6 框）
      3) 只给「框 + 色」，不给「建议字号 / 建议基线」，人工还得反推
    这个脚本一次给全：坐标 / 内容 / 字色 / 底色 / 建议字号 / 建议基线 / 描边 / 类型。

产出
    _probe_<KEY>.json   元素清单
    _probe_<KEY>.png    标注图（编号 + 框）

用法
    python probe_layers.py --src refs\R2_xxx.png --key R2 --crop 17,8,19,24
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import json
import argparse

import numpy as np
import cv2
from PIL import Image

# ------------------------------------------------------------------ OCR 引擎
_OCR_ENGINE = None


def ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def ocr_on(img_bgr, zoom=3, min_conf=0.45):
    """在 ndarray 上跑 OCR，不落任何临时文件（不写 codex 的目录）。"""
    h, w = img_bgr.shape[:2]
    big = cv2.resize(img_bgr, (w * zoom, h * zoom), interpolation=cv2.INTER_CUBIC)
    try:
        res, _ = ocr_engine()(big)
    except Exception:
        return []
    out = []
    for r in (res or []):
        try:
            box, txt, conf = r[0], r[1], float(r[2])
        except Exception:
            continue
        if conf < min_conf:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        out.append({"text": str(txt), "conf": round(conf, 3),
                    "x0": min(xs) / zoom, "y0": min(ys) / zoom,
                    "x1": max(xs) / zoom, "y1": max(ys) / zoom})
    return out


# ------------------------------------------------------------------ 颜色
def _hsv_of(pixels):
    if len(pixels) == 0:
        return np.zeros((0, 3), np.uint8)
    return cv2.cvtColor(pixels.reshape(-1, 1, 3).astype(np.uint8),
                        cv2.COLOR_BGR2HSV).reshape(-1, 3)


def _quant(pixels):
    hsv = _hsv_of(pixels)
    h = hsv[:, 0].astype(np.int32) // 15
    s = np.clip(hsv[:, 1].astype(np.int32) // 85, 0, 2)
    v = np.clip(hsv[:, 2].astype(np.int32) // 85, 0, 2)
    return h * 9 + s * 3 + v


def dominant_colors(pixels, top=6, skip_black=True):
    """返回 [(hex, pct)]，按像素占比降序。"""
    if len(pixels) == 0:
        return []
    key = _quant(pixels)
    vals, counts = np.unique(key, return_counts=True)
    order = np.argsort(-counts)
    out = []
    total = float(len(key))
    for i in order[:top]:
        k = int(vals[i])
        m = (key == k)
        bgr = np.median(pixels[m], axis=0).astype(int)
        hv = k // 9, (k % 9) // 3, k % 3
        if skip_black and hv[2] == 0 and hv[1] == 0:
            continue          # 纯黑
        out.append(("#%02X%02X%02X" % (int(bgr[2]), int(bgr[1]), int(bgr[0])),
                    round(100.0 * int(counts[i]) / total, 1)))
    return out


def ink_core_color(crop, bg_hex, frac=0.75):
    """取「笔画核心」的中位色作为字色。

    为什么不能只靠量化簇：
        dominant_colors 会**显式跳过纯黑**，于是「型号」这种真黑小字
        （实测原图 #010101）的墨色永远进不了候选，探针只能退而求其次
        给个抗锯齿中间灰 #868686 —— 重建出来整片发灰。
        小字里灰色边缘像素本来就比黑色核心多，按「簇占比」挑一定会挑中灰。

    正确做法：背景色已知 → 找**离背景最远**的那批像素（笔画核心）→ 取其中位色。
    不管它是不是纯黑。
    """
    b = np.array([int(bg_hex[5:7], 16), int(bg_hex[3:5], 16),
                  int(bg_hex[1:3], 16)], np.int32)
    d = np.abs(crop.astype(np.int32) - b).max(axis=1)
    dmax = int(d.max()) if len(d) else 0
    if dmax < 50:
        return None
    core = crop[d > frac * dmax]
    if len(core) < 6:
        core = crop[d > 0.5 * dmax]
    if len(core) < 3:
        return None
    med = np.median(core, axis=0).astype(int)
    return "#%02X%02X%02X" % (int(med[2]), int(med[1]), int(med[0]))


def fill_vs_stroke(crop, bg_hex, erode_iter=2, far=None, colbg=None):
    """分离字腔（填充色）与描边环（描边色）。

    crop: (h,w,3) BGR
    far:  预计算的「墨」掩膜（0/1）。给了就直接用，不再自己算。
    colbg: 逐列局部底色 (w,3)；给了就用它替代全局 bg 算距离。
    返回 (fill_hex, stroke_hex, stroke_w)；分离不出来时返回 (None, None, 0)。
    """
    if crop.size == 0:
        return None, None, 0
    h, w = crop.shape[:2]
    if far is None:
        if colbg is not None and len(colbg) == w:
            d = np.abs(crop.astype(np.int32) -
                       colbg[None, :, :].astype(np.int32)).max(axis=2)
        else:
            b = np.array([int(bg_hex[5:7], 16), int(bg_hex[3:5], 16),
                          int(bg_hex[1:3], 16)], np.int32)
            d = np.abs(crop.astype(np.int32) - b).max(axis=2)
        dmax = int(d.max())
        if dmax < 50:
            return None, None, 0
        far = (d > max(60, int(0.45 * dmax))).astype(np.uint8)
    far = (far > 0).astype(np.uint8)
    if far.sum() < 12:
        return None, None, 0
    k = np.ones((3, 3), np.uint8)
    er = cv2.erode(far, k, iterations=erode_iter)
    if er.sum() < 4:
        # 字腔太小（细笔画）→ 不做字腔/描边分离，整块当字色
        core = crop[far > 0]
        if len(core) < 3:
            return None, None, 0
        fill = np.median(core, axis=0).astype(int)
        return ("#%02X%02X%02X" % (int(fill[2]), int(fill[1]), int(fill[0])),
                None, 0)
    # 描边厚度 = 腐蚀到字腔消失所需的次数 - 1
    it = 1
    tmp = cv2.erode(far, k, iterations=1)
    while tmp.sum() >= 4 and it < 12:
        it += 1
        tmp = cv2.erode(far, k, iterations=it)
    sw = max(1, it - 1)
    core = crop[er > 0]
    fill = np.median(core, axis=0).astype(int)
    ring = ((far > 0) & (cv2.dilate(er, k, iterations=1) == 0))
    stroke = None
    if ring.sum() >= 3:
        sm = np.median(crop[ring], axis=0).astype(int)
        stroke = "#%02X%02X%02X" % (int(sm[2]), int(sm[1]), int(sm[0]))
    return ("#%02X%02X%02X" % (int(fill[2]), int(fill[1]), int(fill[0])),
            stroke, sw)


def hex2bgr(h):
    return np.array([int(h[3:5], 16), int(h[1:3], 16), int(h[5:7], 16)], np.int16)


# ------------------------------------------------------------------ 局部底色
def col_bg_map(crop2, outer=None, quant=16, smooth=3):
    """逐列局部底色 -> (w, 3) int32（BGR）。

    为什么需要它
        文字**横跨两种底色**时（电商图极常见：文字压在色块/蒙版的边界上），
        用单一全局 bg 算「离背景最远」，最远的其实是**另一种底色**而不是字 ——
        字色被取成底色。
        实测 F11「参数档案深色卡」：框 [458,360,638,387] 左半浅米 #CEC4B1、
        右半深棕 #463D37，全局 bg 取了浅米，于是深棕底(距离150)比白字(距离70)
        更「远」→ 字色取成 #453D37（那是底色）→ 白字被重绘成深棕。

    底色参照优先用**框外上下条带**（outer），不用框内
        框内众数在**粗体大字**上会被笔画本身污染 —— 一列里笔画占多数时，
        众数 = 字色，整列被当成「另一种底色」→ 误判跨底色。
        实测一个 67px 高的粗体大标题就是这样被误判的。
        框外条带是纯背景，与文字粗细无关 → 稳。
        没有条带（贴图边）时退回框内众数。

    crop2: (h, w, 3) BGR（框内）
    outer: (h2, w, 3) BGR（框外上下条带），可为 None
    """
    if crop2.size == 0:
        return np.zeros((0, 3), np.int32)
    h, w = crop2.shape[:2]
    src = outer if (outer is not None and outer.size and outer.shape[1] == w) else crop2
    col = src.astype(np.int32)
    q = col // quant
    key = q[:, :, 0] * 256 + q[:, :, 1] * 16 + q[:, :, 2]
    out = np.zeros((w, 3), np.int32)
    for x in range(w):
        kx = key[:, x]
        vals, counts = np.unique(kx, return_counts=True)
        sel = kx == vals[int(np.argmax(counts))]
        out[x] = np.median(col[sel, x], axis=0)
    if smooth and smooth > 1 and w >= smooth:
        k = smooth if smooth % 2 else smooth + 1
        half = k // 2
        pad = np.vstack([np.repeat(out[:1], half, axis=0), out,
                         np.repeat(out[-1:], half, axis=0)])
        win = np.lib.stride_tricks.sliding_window_view(pad, k, axis=0)
        out = np.median(win, axis=1).astype(np.int32)[:w]
    return out


def outer_strip(img_bgr, box, pad=4):
    """文字框**上下**的条带（背景参照）。返回 (h2, w, 3) 或 None。"""
    x0, y0, x1, y1 = [int(v) for v in box]
    H, W = img_bgr.shape[:2]
    x0 = max(0, x0); x1 = min(W, x1)
    parts = []
    if y0 - pad >= 0:
        parts.append(img_bgr[max(0, y0 - pad):y0, x0:x1])
    if y1 + pad <= H:
        parts.append(img_bgr[y1:min(H, y1 + pad), x0:x1])
    if not parts:
        return None
    return np.concatenate(parts, axis=0) if len(parts) > 1 else parts[0]


def bg_split(colbg, min_gap=55, min_side_ratio=0.12, max_resid=0.18):
    """列底色是不是「两段式」（中间一条硬边界）。

    返回 (是否跨底色, 边界列索引或 -1)。

    判据（**连续切分**，不是排序后找间隙）：
        在所有可能的切点里选一个，让「左段中位 / 右段中位」两组各自最齐；
        再要求 ① 两组亮度差够大（硬边界，不是渐变）
              ② 两组各占 >= min_side_ratio 的列
              ③ 切分后各段的**残差**足够小（说明真的是「一刀两断」）
    为什么要连续性：
        排序法会把「徽章边缘」这种**锯齿状**的列底色也判成两段 ——
        实测 TBM1「赠」字（红徽章上的白字）就是这样被误判成跨底色，
        局部底色把紫底当成了底色，字色整个取错。
        连续切分要求边界**只有一个**，锯齿状的不满足 → 不误判。
    """
    w = len(colbg)
    if w < 12:
        return False, -1
    lum = colbg.sum(axis=1).astype(int).astype(np.float64)
    best = None
    lo = max(2, int(min_side_ratio * w))
    for k in range(lo, w - lo):
        L, R = lum[:k], lum[k:]
        ml, mr = np.median(L), np.median(R)
        cost = float(np.abs(L - ml).sum() + np.abs(R - mr).sum())
        if best is None or cost < best[0]:
            best = (cost, k, ml, mr)
    if best is None:
        return False, -1
    cost, k, ml, mr = best
    if abs(ml - mr) < min_gap:
        return False, -1
    total = float(np.abs(lum - lum.mean()).sum())
    if total > 0 and cost / total > max_resid:
        # 各段内部太散 → 不是干净的「一刀两断」
        return False, -1
    return True, k


def _thickness(mask, max_iter=40):
    """连通块的「厚度」= 腐蚀到消失的次数。笔画细（几次就没），色块厚。"""
    it = 0
    tmp = mask
    while tmp.sum() >= 4 and it < max_iter:
        tmp = cv2.erode(tmp, np.ones((3, 3), np.uint8), iterations=1)
        it += 1
    return it


def ink_stroke_color(crop2, bg_hex, colbg=None, max_thick=10, min_area=12):
    """用**厚度**判据找字色。

    为什么不能用「离背景最远」
        文字压在色块/蒙版边界上时，「离全局背景最远」往往是**另一种底色**：
        实测 F11 参数档案卡，深棕块(距离150)比白字(距离70)更远 → 字色取成 #453D37。
        反过来也可能：字和某块底色**同色**（实测 TBM1「整箱」= 紫底白字，
        框角还压着白色灯板）→ 颜色分不开。

    可靠区别是**厚度**：笔画几 px 粗，实心色块几十 px 粗。
        → 只保留细连通块 → 它们才是字。

    colbg 不为 None 时用**逐列局部底色**（跨底色时用）。
    返回 (fill_hex, stroke_hex, stroke_w) 或 None。
    """
    if crop2.size == 0:
        return None
    h, w = crop2.shape[:2]
    if colbg is not None and len(colbg) == w:
        b = colbg[None, :, :].astype(np.int32)
        d = np.abs(crop2.astype(np.int32) - b).max(axis=2)
    else:
        bb = hex2bgr(bg_hex).astype(np.int32)
        d = np.abs(crop2.astype(np.int32) - bb).max(axis=2)
    dmax = int(d.max())
    if dmax < 50:
        return None
    # 跨底色时阈值压低一点：浅底上的白字与底色只差 ~70
    frac = 0.35 if colbg is not None else 0.45
    far = (d > max(45, int(frac * dmax))).astype(np.uint8) * 255
    n, lab, stats, _ = cv2.connectedComponentsWithStats(far, 8)
    keep = np.zeros_like(far)
    best_area = 0
    for k in range(1, n):
        area = int(stats[k, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        comp = (lab == k).astype(np.uint8)
        if _thickness(comp) > max_thick:
            continue                      # 太厚 → 实心色块，不是字
        keep[comp > 0] = 255
        best_area = max(best_area, area)
    if best_area == 0:
        return None
    # 在「笔画集合」上再做字腔/描边分离
    res = fill_vs_stroke(crop2, bg_hex, erode_iter=2, far=keep, colbg=colbg)
    if not res or res[0] is None:
        return None
    return res



def ink_color(img_bgr, box, bg_ref=None, mode="ring"):
    """取框内「离背景最远」的色簇作为字色。返回 (fill, bg, stroke_or_None)。

    mode="ring"（默认，R1~R6 沿用）：背景 = 框外一圈的中位色，字 = 框内离它最远的簇。
    mode="majority"（淘宝线用）：背景 = **框内像素的最大簇**，字 = 其余簇里离背景最远的。

    为什么电商图必须用 majority：
        深紫标题条上的白字，框外一圈（扩 40%）大半是下方白底 →
        ring 的中位色算成浅色 → 「离它最远」= 深紫 → **字色取反**，
        白字被画成深紫，落在深紫条上直接看不见。
        majority 不管框外长什么样，只看框内：底色占多数、字占少数 → 不会取反。
    """
    x0, y0, x1, y1 = [int(v) for v in box]
    H, W = img_bgr.shape[:2]
    x0 = max(0, x0); y0 = max(0, y0); x1 = min(W, x1); y1 = min(H, y1)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    crop2 = img_bgr[y0:y1, x0:x1]            # (h, w, 3)
    crop = crop2.reshape(-1, 3)

    if mode == "majority":
        # 背景 = 框内像素的最大簇（不过滤纯黑：黑底白字图里黑底就是背景）
        cols = dominant_colors(crop, top=8, skip_black=False)
        if not cols:
            return None
        bg_hex = cols[0][0]
        bg = hex2bgr(bg_hex).astype(np.int32)
        # ---- 跨底色检测：文字压在色块/蒙版边界上（电商图极常见）----
        colbg = col_bg_map(crop2, outer_strip(img_bgr, box))
        cross, split_x = bg_split(colbg)

        # ---- 老路：「离全局背景最远」+ 字腔/描边分离 ----
        fill_g = ink_core_color(crop, bg_hex)
        stroke_g, stroke_w_g = None, 0
        if fill_g is not None:
            # 带描边的大字：描边色可能比填充色「离背景更远」，
            # 直接用「最远簇」会把描边当字色 → 整行字变黑。
            # 用形态学腐蚀把字腔和描边环分开。
            f2, s2, sw2 = fill_vs_stroke(crop2, bg_hex)
            if f2 and s2 and f2 != s2:
                fill_g, stroke_g, stroke_w_g = f2, s2, sw2

        # ---- 厚度路：只保留「细」的连通块（笔画），剔除实心色块 ----
        fill_t, stroke_t, stroke_w_t = None, None, 0
        res = ink_stroke_color(crop2, bg_hex, colbg=colbg if cross else None)
        if res:
            fill_t, stroke_t, stroke_w_t = res

        # ---- 冲突仲裁 ----
        #   老路的失效形态：抓到的「墨色」其实是**另一种底色**。
        #   判据：这个墨色与某一列的局部底色几乎一样
        #   → 说明它抓的是底色而不是字 → 交给厚度路。
        #   ⚠ 厚度路**不能当主力**：照片底上的字用它会取浅（高光纹理混进来）。
        susp = False
        if fill_g and len(colbg):
            fg = hex2bgr(fill_g).astype(np.int32)
            if (np.abs(colbg - fg[None, :]).max(axis=1) < 30).any():
                susp = True
        if susp and fill_t and fill_t != fill_g:
            fill, stroke, stroke_w = fill_t, stroke_t, stroke_w_t
        elif fill_g is not None:
            fill, stroke, stroke_w = fill_g, stroke_g, stroke_w_g
        else:
            fill, stroke, stroke_w = fill_t, stroke_t, stroke_w_t
        if fill is None:
            return ink_color(img_bgr, box, bg_ref, mode="ring")
        fb = hex2bgr(fill).astype(np.int32)
        fill_dist = int(np.abs(fb - bg).max())
        # 备选色：其它离背景远的簇（供 fill 自动校准挑）
        alts = [(fill, 0, fill_dist)]
        for c, pct in cols[1:]:
            b = hex2bgr(c).astype(np.int32)
            d = int(np.abs(b - bg).max())
            if d < 50:
                continue
            if c == fill:
                continue
            if cross and (np.abs(colbg - b[None, :]).max(axis=1) < 45).any():
                # 跨底色时「另一种底色」不能当候选墨色，
                # 否则寻优会把字重绘成背景色。
                continue
            alts.append((c, pct, d))
        alts.sort(key=lambda t: (-t[2], -t[1]))
        if (not cross) and stroke is None and len(alts) > 1 and alts[0][2] - alts[1][2] < 30 \
                and alts[1][1] >= 8:
            stroke = alts[1][0]
        return {"fill": fill, "bg": bg_hex, "stroke": stroke,
                "stroke_w": stroke_w,
                "fill_dist_bg": fill_dist, "n_colors": len(cols),
                "cross_bg": cross, "split_x": split_x,
                "alts": list(dict.fromkeys([a[0] for a in alts[:5]]))}

    if bg_ref is None:
        pad = max(4, int(0.4 * max(x1 - x0, y1 - y0)))
        ring = img_bgr[max(0, y0 - pad):min(H, y1 + pad),
                       max(0, x0 - pad):min(W, x1 + pad)].reshape(-1, 3)
        bg = np.median(ring, axis=0).astype(np.int32)
    else:
        bg = np.array([int(bg_ref[3:5], 16), int(bg_ref[1:3], 16),
                        int(bg_ref[5:7], 16)], np.int32)
    dist = np.abs(crop.astype(np.int32) - bg).max(axis=1)
    fg = crop[dist > 42]
    if len(fg) < 10:
        return None
    cols = dominant_colors(fg, top=8)
    if not cols:
        return None
    bg_hex = "#%02X%02X%02X" % (int(bg[2]), int(bg[1]), int(bg[0]))
    scored = []
    for c, pct in cols:
        b = hex2bgr(c).astype(np.int32)
        scored.append((int(np.abs(b - bg).max()), c, pct))
    scored.sort(key=lambda s: -s[0])
    fill = scored[0][1]
    stroke = None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 30 and scored[1][2] >= 8:
        stroke = scored[1][1]        # 第二簇离背景也很远 → 可能是描边/双色
    return {"fill": fill, "bg": bg_hex, "stroke": stroke,
            "fill_dist_bg": scored[0][0], "n_colors": len(cols)}


# ------------------------------------------------------------------ 行候选（OCR 漏检兜底）
def candidate_lines(img_bgr, ocr_boxes, min_h=7, max_h=200):
    """形态学梯度找「文字样」连通域 -> 按行聚类 -> 排除已被 OCR 覆盖的。

    这解决了 R4/R5/R6 深底细衬线漏检的问题：
    OCR 只给 6 框的那张，梯度法能补出十几条线（内容再交给 OCR 读）。
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape[:2]
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    _, binimg = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    binimg = cv2.morphologyEx(binimg, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(binimg, 8)
    blobs = []
    for k in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[k, :5]]
        if h < min_h or h > max_h or w < 4:
            continue
        if area < 8:
            continue
        if w > 0.94 * W and h > 0.2 * H:
            continue
        blobs.append((x, y, w, h))
    # 按 y 聚类成行
    blobs.sort(key=lambda b: b[1])
    lines = []
    for b in blobs:
        placed = False
        for L in lines:
            cy = (L["y0"] + L["y1"]) / 2
            by = (b[1] + b[3] / 2)
            if abs(by - cy) <= max(4, 0.35 * L["h"]):
                L["x0"] = min(L["x0"], b[0])
                L["y0"] = min(L["y0"], b[1])
                L["x1"] = max(L["x1"], b[0] + b[2])
                L["y1"] = max(L["y1"], b[1] + b[3])
                L["h"] = L["y1"] - L["y0"]
                placed = True
                break
        if not placed:
            lines.append({"x0": b[0], "y0": b[1], "x1": b[0] + b[2],
                          "y1": b[1] + b[3], "h": b[3]})
    # 合并行
    lines.sort(key=lambda L: L["y0"])
    merged = []
    for L in lines:
        if merged and L["y0"] <= merged[-1]["y1"]:
            m = merged[-1]
            m["x0"] = min(m["x0"], L["x0"]); m["y0"] = min(m["y0"], L["y0"])
            m["x1"] = max(m["x1"], L["x1"]); m["y1"] = max(m["y1"], L["y1"])
            m["h"] = m["y1"] - m["y0"]
        else:
            merged.append(dict(L))
    # 丢掉被 OCR 覆盖 >=70% 的行
    out = []
    for L in merged:
        if L["x1"] - L["x0"] < 12 or L["h"] < min_h:
            continue
        inter = 0
        for ob in ocr_boxes:
            ix0 = max(L["x0"], ob["x0"]); iy0 = max(L["y0"], ob["y0"])
            ix1 = min(L["x1"], ob["x1"]); iy1 = min(L["y1"], ob["y1"])
            if ix1 > ix0 and iy1 > iy0:
                inter += (ix1 - ix0) * (iy1 - iy0)
        if inter > 0.7 * (L["x1"] - L["x0"]) * L["h"]:
            continue
        out.append(L)
    return out


# ------------------------------------------------------------------ 面板色块
def sat_blocks(img_bgr, min_area=900, top=26):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    H, W = hsv.shape[:2]
    sm = cv2.erode(hsv, np.ones((7, 7), np.uint8))
    mask = np.zeros((H, W), np.uint8)
    mask[sm[:, :, 1] > 85] = 255
    mask[sm[:, :, 2] > 238] = 0
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for k in range(1, n):
        area = int(stats[k, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        x, y, w, h = [int(v) for v in stats[k, :4]]
        bgr = np.median(img_bgr[lab == k], axis=0).astype(int)
        out.append({"x": x, "y": y, "w": w, "h": h, "area": area,
                    "color": "#%02X%02X%02X" % (int(bgr[2]), int(bgr[1]), int(bgr[0]))})
    out.sort(key=lambda b: -b["area"])
    return out[:top]


# ------------------------------------------------------------------ 主流程
def probe(src, key, crop=(0, 0, 0, 0), outdir=None, ink_mode="ring"):
    raw = np.asarray(Image.open(src).convert("RGB")).astype(np.uint8)
    t, b, l, r = crop
    H0, W0 = raw.shape[:2]
    A = raw[t:H0 - b if b else H0, l:W0 - r if r else W0]
    H, W = A.shape[:2]
    bgr = cv2.cvtColor(A, cv2.COLOR_RGB2BGR)

    boxes = ocr_on(bgr, zoom=3, min_conf=0.45)
    for bx in boxes:
        bx["x0"], bx["y0"] = int(round(bx["x0"])), int(round(bx["y0"]))
        bx["x1"], bx["y1"] = int(round(bx["x1"])), int(round(bx["y1"]))
    boxes.sort(key=lambda x: (x["y0"], x["x0"]))

    extra = candidate_lines(bgr, boxes)
    extra_ocr = []
    for L in extra:
        pad = 3
        x0 = max(0, L["x0"] - pad); y0 = max(0, L["y0"] - pad)
        x1 = min(W, L["x1"] + pad); y1 = min(H, L["y1"] + pad)
        crop_img = bgr[y0:y1, x0:x1]
        # 对比度增强后重读一次（细衬线/低对比文字）
        g = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
        g = cv2.createCLAHE(3.0, (8, 8)).apply(g)
        v = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
        cand = ocr_on(v, zoom=4, min_conf=0.30)
        best = None
        for c in cand:
            w = c["x1"] - c["x0"]
            if best is None or w > (best["x1"] - best["x0"]):
                best = c
        if best and best["x1"] - best["x0"] > 8:
            extra_ocr.append({"text": best["text"], "conf": best["conf"],
                              "x0": x0 + int(best["x0"]), "y0": y0 + int(best["y0"]),
                              "x1": x0 + int(best["x1"]), "y1": y0 + int(best["y1"]),
                              "src": "line"})
        else:
            extra_ocr.append({"text": "", "conf": 0.0,
                              "x0": L["x0"], "y0": L["y0"], "x1": L["x1"], "y1": L["y1"],
                              "src": "line"})
    extra_ocr.sort(key=lambda x: (x["y0"], x["x0"]))

    rows = []
    for i, bx in enumerate(boxes):
        c = ink_color(bgr, [bx["x0"], bx["y0"], bx["x1"], bx["y1"]], mode=ink_mode)
        h = bx["y1"] - bx["y0"]
        rows.append({"i": i, "text": bx["text"], "conf": bx["conf"],
                     "box": [bx["x0"], bx["y0"], bx["x1"], bx["y1"]],
                     "h": h, "w": bx["x1"] - bx["x0"],
                     "fill": (c or {}).get("fill"), "bg": (c or {}).get("bg"),
                     "stroke": (c or {}).get("stroke"),
                     "alts": (c or {}).get("alts"),
                     "cross_bg": (c or {}).get("cross_bg"),
                     "split_x": (c or {}).get("split_x"),
                     "src": "ocr"})
    for i, bx in enumerate(extra_ocr):
        c = ink_color(bgr, [bx["x0"], bx["y0"], bx["x1"], bx["y1"]], mode=ink_mode)
        h = bx["y1"] - bx["y0"]
        rows.append({"i": len(boxes) + i, "text": bx["text"], "conf": bx["conf"],
                     "box": [bx["x0"], bx["y0"], bx["x1"], bx["y1"]],
                     "h": h, "w": bx["x1"] - bx["x0"],
                     "fill": (c or {}).get("fill"), "bg": (c or {}).get("bg"),
                     "stroke": (c or {}).get("stroke"),
                     "alts": (c or {}).get("alts"),
                     "cross_bg": (c or {}).get("cross_bg"),
                     "split_x": (c or {}).get("split_x"),
                     "src": bx["src"]})

    # 建议字号：CJK 墨迹高 ≈ 字号；拉丁/数字 ≈ 0.72 字号
    for rw in rows:
        h = rw["h"]
        txt = rw["text"]
        cjk = sum(1 for ch in txt if ord(ch) > 0x2E80)
        ratio = 1.0 if (cjk and cjk >= len(txt) * 0.5) else 0.74
        rw["size_guess"] = round(h / ratio, 1)
        rw["base_guess"] = rw["box"][3]

    blocks = sat_blocks(bgr)

    # 标注图
    vis = bgr.copy()
    for rw in rows:
        x0, y0, x1, y1 = rw["box"]
        col = (0, 255, 255) if rw["src"] == "ocr" else (0, 128, 255)
        cv2.rectangle(vis, (x0, y0), (x1, y1), col, 2)
        cv2.putText(vis, "#%d" % rw["i"], (x0, max(14, y0 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 255), 2, cv2.LINE_AA)

    outdir = outdir or os.path.dirname(os.path.abspath(src))
    jp = os.path.join(outdir, "_probe_%s.json" % key)
    ip = os.path.join(outdir, "_probe_%s.png" % key)
    json.dump({"key": key, "src": src, "crop": list(crop),
               "canvas": [W, H], "orig": [W0, H0],
               "rows": rows, "blocks": blocks},
              open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    cv2.imencode(".png", vis)[1].tofile(ip)

    lines = ["== %s canvas=%dx%d (orig %dx%d, crop t%d b%d l%d r%d) ==" %
             (key, W, H, W0, H0, t, b, l, r)]
    for r in rows:
        lines.append("#%-2d [%-4s] %-26s box=%-22s h=%-4s size~%-6s fill=%-8s bg=%-8s stroke=%s"
                     % (r["i"], r["src"], str(r["text"])[:26], str(r["box"]),
                        r["h"], r["size_guess"], r["fill"], r["bg"], r["stroke"]))
    lines.append("-- 高饱和色块 --")
    for bl in blocks[:16]:
        lines.append("   x=%4d y=%4d w=%4d h=%4d area=%7d %s"
                     % (bl["x"], bl["y"], bl["w"], bl["h"], bl["area"], bl["color"]))
    txt = "\n".join(lines)
    open(os.path.join(outdir, "_probe_%s.txt" % key), "w", encoding="utf-8").write(txt)
    print("wrote", jp, ip)
    return jp


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--crop", default="0,0,0,0")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--ink-mode", default="ring", choices=["ring", "majority"])
    a = ap.parse_args()
    c = tuple(int(v) for v in a.crop.split(","))
    probe(a.src, a.key, c, a.outdir, ink_mode=a.ink_mode)
