# -*- coding: utf-8 -*-
"""像素层降级器 —— 把「字体替代还原不出来」的大字自动降级成像素层

为什么需要
    淘宝促销大字用的是商业字体（综艺体/粗黑体等），本机没有授权源。
    用 Noto Sans SC 替代时，**字形轮廓对不上** —— 边缘大量像素差异。
    实测 TBM1：非文字区差异 0.58%（背景/产品完全对上），
              但文字区差异 44~50%，占了 99% 的总差异。
    这是**字体不可得**造成的，不是版式拆解或坐标的问题。

    正确的工程解法不是硬凑字体，而是**双版本交付**：
      · 活字版：字是活的（可改价/改文案/改型号），字形用替代字体
      · 像素层版：字形用原图裁切（像素级一致），但那几处字不能改
    引擎本来就有像素层机制（spec 里 `px:true` + `px_asset` + `px_box`），
    只是以前靠人肉标「哪些该做像素层」。

本脚本把这个判断自动化
    跑完寻优后，逐个文字算它所在区域的差异率；
    差异率超阈值 ⇒ 这处字的**字形**还原不出来 ⇒ 标记为像素层。
    阈值可调；差异率低的（小字、正文）保持活字，不受影响。

用法
    python -m layout_restore.pixel_fallback --spec specs/demo.json --out out/demo --threshold 18
"""
import os
import sys
import json
import argparse

import numpy as np
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def region_diff(orig, rec, box, pad=4):
    H, W = orig.shape[:2]
    x0 = max(0, box[0] - pad)
    y0 = max(0, box[1] - pad)
    x1 = min(W, box[2] + pad)
    y1 = min(H, box[3] + pad)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return 0.0, 0
    d = np.abs(orig[y0:y1, x0:x1].astype(int) - rec[y0:y1, x0:x1].astype(int)).max(axis=2)
    n = int((d > 20).sum())
    return (100.0 * n / d.size), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=18.0,
                    help="区域差异率超过这个%% 就降级成像素层")
    ap.add_argument("--pad", type=int, default=4)
    a = ap.parse_args()

    # ⚠ 必须用**寻优后的** spec（out/<KEY>/_spec.json），不能用 specs/ 里的草稿 ——
    #    草稿没标定，二次重建会把字号/基线/字重/字色的寻优结果全丢掉，
    #    实测 TBF1 从 6.44% 退化到 8.42%。
    spec_path = a.spec
    cal = os.path.join(a.out, "_spec.json")
    if os.path.exists(cal):
        spec_path = cal
        print("用寻优后的 spec：%s" % cal)
    spec = json.load(open(spec_path, encoding="utf-8"))
    src = spec["src"]
    if not os.path.isabs(src):
        src = os.path.join(os.path.dirname(os.path.abspath(a.spec)), "..", src)
    orig = np.asarray(Image.open(src).convert("RGB")).astype(int)
    recp = os.path.join(a.out, "_render_1x.png")
    if not os.path.exists(recp):
        raise SystemExit("缺少渲染图 %s，先跑 rebuild" % recp)
    rec = np.asarray(Image.open(recp).convert("RGB")).astype(int)

    changed = []
    for t in spec["text"]:
        rate, n = region_diff(orig, rec, t["box"], a.pad)
        flag = ""
        if rate > a.threshold and not t.get("px"):
            t["px"] = True
            t["px_asset"] = "px_" + t.get("id", "t%02d" % spec["text"].index(t))
            t["px_box"] = [t["box"][0], t["box"][1], t["box"][2], t["box"][3]]
            t["px_pad"] = a.pad
            changed.append((t["text"][:18], rate))
            flag = "  -> 像素层"
        print("  %-20s 区域差异 %5.1f%%%s" % (t["text"][:18], rate, flag))

    # 回写到「寻优后的 spec」和「族级配方 specs/」两处：
    #   out/_spec.json  = 本次渲染用的标定结果
    #   specs/<KEY>.json = **族级配方**（标定后的版本，换产品时直接用）
    for p in (spec_path, a.spec):
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            json.dump(spec, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e:
            print("  回写失败 %s：%s" % (p, e))
    print("\n降级 %d 处 -> %s" % (len(changed), spec_path))
    for c, r in changed:
        print("   %-20s %.1f%%" % (c, r))
    return len(changed)


if __name__ == "__main__":
    sys.exit(main())
