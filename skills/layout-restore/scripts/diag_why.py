# -*- coding: utf-8 -*-
"""超差定性：回答「这张为什么差」。

判据链（每一步都有可验证的依据，不是猜）
    ① 分区复算 —— 残差在文字区还是非文字区？
         非文字区 ≥ 3%  → **分层/背景重建错**（工程缺陷，可修）
         非文字区 < 1%  → 分层是干净的，继续看 ②
    ② 文字区差异有多大？
         文字区 < 20%    → 文字本身还原得还行 → 可能是**字号/字距/局部**问题（工程缺陷，可修）
         文字区 ≥ 35%    → 字几乎全错 → 看 ③
    ③ 是「字体不可得」还是「取色/字重错」？
         · 残差集中在**产品上印的装饰字体**（字形明显不是同一种，且无 ≥85px 大字）
           → **素材限制**（字体不可得），当前引擎做不到
         · 残差集中在**有 ≥85px 的字** → 大概率是商业艺术字 → **素材限制**
         · 字色/字重明显不对（整块变深/变浅） → **工程缺陷**（可修）

输出
    每张一行定性 + 一张总表；同时把热点对比图裁出来（左右并排）供肉眼复核。

用法
    python diag_why.py KEY [KEY ...]
    python diag_why.py --batch batch_jobs.json
"""
import os
import sys
import json
import argparse

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as C

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _load(p):
    return np.asarray(Image.open(p).convert("RGB")).astype(int)


def _masks(spec, H, W):
    """文字掩膜 / 非文字掩膜（排除美术素材框）。"""
    txt = np.zeros((H, W), dtype=bool)
    for t in spec.get("text", []):
        b = t.get("box") or []
        if len(b) != 4:
            continue
        x0, y0, x1, y1 = [int(v) for v in b]
        x0 = max(0, x0 - 4); y0 = max(0, y0 - 4)
        x1 = min(W, x1 + 4); y1 = min(H, y1 + 4)
        if x1 > x0 and y1 > y0:
            txt[y0:y1, x0:x1] = True
    art = np.zeros((H, W), dtype=bool)
    for a in spec.get("art", []):
        b = a[1] if isinstance(a, (list, tuple)) and len(a) > 1 else a
        if isinstance(b, (list, tuple)) and len(b) == 4:
            x0, y0, x1, y1 = [int(v) for v in b]
            x0 = max(0, x0); y0 = max(0, y0); x1 = min(W, x1); y1 = min(H, y1)
            if x1 > x0 and y1 > y0:
                art[y0:y1, x0:x1] = True
    return txt, (~txt) & (~art)


def _solid_blobs(hot):
    """残差图里的「实心大块」——**物体丢失/重建错**的指纹。

    文字的残差是**细长条**（字的边缘），填充率低；
    一个装饰物（柠檬、花叶）整个消失 → 残差是**实心块**，填充率高。

    ⚠ 这条判据是必要的：非文字区差异率**低**不代表画面没问题 ——
      实测柠檬整个消失，非文字区差异率只有 0.26%，看着像「画面正常」。
    """
    import cv2
    m = (hot.astype(np.uint8)) * 255
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for k in range(1, n):
        x, y, w, h, a = stats[k]
        if a < 3000 or w < 40 or h < 40:
            continue
        fill = a / float(w * h)
        if fill >= 0.55:
            out.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h),
                        "area": int(a), "fill": round(fill, 2)})
    out.sort(key=lambda d: -d["area"])
    return out


def diagnose(key, out_dir=None, threshold=8.0, cfg=None):
    cfg = cfg or C.load_cfg()
    d = C.out_dir(cfg, key)
    sp = os.path.join(d, "_spec.json")
    rp = os.path.join(d, "_report.json")
    if not (os.path.exists(sp) and os.path.exists(rp)):
        return {"key": key, "err": "缺 _spec/_report"}
    spec = json.load(open(sp, encoding="utf-8"))
    rep = json.load(open(rp, encoding="utf-8"))
    src = spec.get("src")
    render = os.path.join(d, "_render_1x.png")
    if not (src and os.path.exists(src) and os.path.exists(render)):
        return {"key": key, "err": "缺原图或渲染图"}
    O = _load(src)
    B = _load(render)
    if O.shape != B.shape:
        return {"key": key, "err": "尺寸不一致"}
    H, W = O.shape[:2]
    hot = np.abs(O - B).max(axis=2) > 20
    total = int(hot.sum())
    txtm, nonm = _masks(spec, H, W)
    ta, na = int(txtm.sum()), int(nonm.sum())
    th = int((hot & txtm).sum())
    nh = int((hot & nonm).sum())
    live = (rep.get("live") or {}).get("diff_gt20_pct")
    overall = round(100.0 * total / hot.size, 2)
    text_pct = round(100.0 * th / ta, 2) if ta else None
    non_pct = round(100.0 * nh / na, 2) if na else None
    non_share = round(100.0 * nh / total, 1) if total else None
    sizes = [(t["box"][3] - t["box"][1]) for t in spec.get("text", [])
             if isinstance(t.get("box"), list) and len(t["box"]) == 4]
    n_big = sum(1 for s in sizes if s >= 85)
    max_h = max(sizes) if sizes else 0
    # 文字颜色是否「整体偏深/偏浅」→ 取色问题
    dark_mismatch = 0
    for t in spec.get("text", []):
        b = t.get("box") or []
        if len(b) != 4:
            continue
        x0, y0, x1, y1 = [int(v) for v in b]
        x0 = max(0, x0); y0 = max(0, y0); x1 = min(W, x1); y1 = min(H, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        ob = O[y0:y1, x0:x1].reshape(-1, 3)
        bb = B[y0:y1, x0:x1].reshape(-1, 3)
        d = np.abs(ob - bb).max(axis=1)
        # 原图里「最亮的 10%」是不是字（说明字是浅色）→ 还原里对应区域是否明显更暗
        lum = ob.sum(axis=1)
        thr = np.percentile(lum, 90)
        bright = ob[lum >= thr]
        if len(bright) < 8:
            continue
        bc = bright.mean(axis=0)
        # 渲染区里最亮的 10%
        lb = bb.sum(axis=1)
        t2 = np.percentile(lb, 90)
        brightb = bb[lb >= t2]
        if len(brightb) < 8:
            continue
        if np.abs(brightb.mean(axis=0) - bc).max() > 40:
            dark_mismatch += 1

    # ---- 定性 ----
    blobs = _solid_blobs(hot)
    # 原图里的美术素材（art 层）在还原图里应该还在 → 丢失即「物体缺失」
    lost = []
    for a in spec.get("art", []):
        b = a[1] if isinstance(a, (list, tuple)) and len(a) > 1 else a
        if not (isinstance(b, (list, tuple)) and len(b) == 4):
            continue
        x0, y0, x1, y1 = [int(v) for v in b]
        x0 = max(0, x0); y0 = max(0, y0); x1 = min(W, x1); y1 = min(H, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        seg = hot[y0:y1, x0:x1]
        if seg.mean() > 0.25:
            lost.append({"art": a[0] if isinstance(a, list) else str(a),
                         "box": [x0, y0, x1, y1],
                         "missing_pct": round(100.0 * float(seg.mean()), 1)})

    if live is None:
        verdict = "无指标"
    elif live <= threshold:
        verdict = "达标"
    elif lost or blobs:
        verdict = "工程缺陷：美术素材丢失/物体重建错"
    elif (non_pct or 0) >= 3.0:
        verdict = "工程缺陷：分层/背景重建错"
    elif text_pct is not None and text_pct >= 35.0:
        if n_big > 0:
            verdict = "素材限制：大字艺术字体不可得"
        elif dark_mismatch >= max(2, len(sizes) // 3):
            verdict = "工程缺陷：字色/字重取错"
        else:
            verdict = "素材限制：字形不可得（产品丝印/装饰字体）"
    elif text_pct is not None and text_pct >= 20.0:
        verdict = "工程缺陷：字号/字距/局部错位"
    else:
        verdict = "工程缺陷：其它（看热点图）"

    res = {"key": key, "overall": overall, "live": live,
           "text_area_pct": round(100.0 * ta / hot.size, 1),
           "text_diff_pct": text_pct,
           "text_share_of_resid": round(100.0 * th / total, 1) if total else None,
           "nontext_diff_pct": non_pct,
           "nontext_share_of_resid": non_share,
           "n_text": len(sizes), "n_big_text": n_big, "max_text_h": max_h,
           "color_mismatch_texts": dark_mismatch,
           "solid_blobs": blobs[:4], "lost_art": lost,
           "verdict": verdict}
    if out_dir:
        res["crop"] = crop_hotspots(key, d, O, B, out_dir)
    return res


def crop_hotspots(key, d, O, B, out_dir):
    """把残差最集中的 3 块裁出来，原图|还原图 并排。"""
    H, W = O.shape[:2]
    hot = np.abs(O - B).max(axis=2) > 20
    bs = 40
    cells = []
    for y in range(0, H - bs + 1, bs):
        for x in range(0, W - bs + 1, bs):
            n = int(hot[y:y + bs, x:x + bs].sum())
            if n > bs * bs * 0.25:
                cells.append((n, x, y))
    cells.sort(reverse=True)
    cells = cells[:3]
    if not cells:
        return None
    os.makedirs(out_dir, exist_ok=True)
    patches = []
    for cnt, x, y in cells:
        half = 110
        x0 = max(0, x - half); y0 = max(0, y - half)
        x1 = min(W, x + bs + half); y1 = min(H, y + bs + half)
        patches.append((Image.fromarray(O[y0:y1, x0:x1].astype(np.uint8)),
                        Image.fromarray(B[y0:y1, x0:x1].astype(np.uint8)),
                        (x, y)))
    aw, ah = patches[0][0].size
    sheet = Image.new("RGB", (aw * 2 + 30, ah * len(patches) + 30 * len(patches)),
                      (24, 24, 28))
    dr = ImageDraw.Draw(sheet)
    for i, (a, b, pos) in enumerate(patches):
        yy = 20 + i * (ah + 30)
        sheet.paste(a, (10, yy)); sheet.paste(b, (aw + 20, yy))
        dr.text((10, yy - 14), "KEY %s  hotspot@%d,%d   LEFT=original  RIGHT=rebuilt"
                % (key, pos[0], pos[1]), fill=(255, 220, 120))
    p = os.path.join(out_dir, "%s_热点对比.png" % key)
    sheet.save(p)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keys", nargs="*")
    ap.add_argument("--batch", default=None, help="jobs json（取其中的 key）")
    ap.add_argument("--crops", default=None, help="热点图输出目录")
    ap.add_argument("--out", default=None, help="结果 JSON")
    a = ap.parse_args()
    keys = list(a.keys)
    if a.batch and os.path.exists(a.batch):
        keys += [j["key"] for j in json.load(open(a.batch, encoding="utf-8"))]
    if not keys:
        print("用法：python diag_why.py KEY [KEY ...] | --batch jobs.json")
        return 2
    cfg = C.load_cfg()
    rows = []
    for k in keys:
        r = diagnose(k, a.crops)
        rows.append(r)
        if r.get("err"):
            print("%-9s !! %s" % (k, r["err"]))
            continue
        print("%-9s %6.2f%% | 文字区差异%6s%% 占残差%5s%% | 非文字区差异%6s%% | "
              "大字%2d/%2d 最多%3dpx | 色差字%2d → %s"
              % (k, r["live"], r["text_diff_pct"], r["text_share_of_resid"],
                 r["nontext_diff_pct"], r["n_big_text"], r["n_text"],
                 r["max_text_h"], r["color_mismatch_texts"], r["verdict"]))
    from collections import Counter
    print("\n=== 定性汇总 ===")
    for v, n in Counter(r["verdict"] for r in rows if not r.get("err")).most_common():
        print("  %-32s %d 张" % (v, n))
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        json.dump(rows, open(a.out, "w", encoding="utf-8"), ensure_ascii=False,
                  indent=1)
        print("\n-> %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
