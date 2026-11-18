#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""像素层断言 —— 检查「像素层降级」这件事有没有真的发生

背景
    像素层是**兜底**：只有"字体替代还原不出来"的文字（区域差异 > px_threshold）
    才降级成像素层。所以：

      · 有降级 → 必须产出 px_*.png 素材，且像素层版必须优于活字版
      · 无降级 → 活字版本身就达标（所有文字区域差异都在阈值以下）

    原来那道断言是无条件的「必须产出 px 素材」，于是：
      · 在还原得好的机器/平台上（Ubuntu 实测：活字版 diff 0.11%，无一处超 18%）
        → 0 处降级 → 0 张素材 → **假失败**
      · 而它本来要抓的真 bug（决定降级了、却没产出素材 = 空转）反而没被覆盖到

    现在按标记文件分支，两条路都断言：
      changed > 0  →  素材数 == changed  且  像素层版 diff < 活字版 diff
      changed == 0 →  活字版 diff <= MAX_LIVE_DIFF（还原质量达标，本来就不需要兜底）

用法
    python tests/check_pixel_layer.py --out out/demo_param_card
退出码
    0 = 通过    1 = 不通过
"""

import argparse
import glob
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 活字版的整体差异上限（%）：没有像素层兜底时，还原本身必须到这个水平
MAX_LIVE_DIFF = 5.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="run 目录，例如 out/demo_param_card")
    a = ap.parse_args()

    marker_path = os.path.join(a.out, "_px_fallback.json")
    report_path = os.path.join(a.out, "_report.json")
    for p in (marker_path, report_path):
        if not os.path.isfile(p):
            print("FAIL: 缺少 %s（build 跑完了吗）" % p)
            return 1

    marker = json.load(open(marker_path, encoding="utf-8"))
    changed = int(marker.get("changed", 0))
    rep = json.load(open(report_path, encoding="utf-8"))
    live = float(rep["live"]["diff_gt20_pct"])
    pxr = float(rep["px"]["diff_gt20_pct"])

    print("像素层降级处数 : %d" % changed)
    print("活字版 diff>20 : %.2f%%" % live)
    print("像素层版 diff>20: %.2f%%" % pxr)

    packs = glob.glob(os.path.join(a.out, "deliver", "*_源件包"))
    if not packs:
        print("FAIL: 交付包不存在：%s" % os.path.join(a.out, "deliver", "*_源件包"))
        return 1
    pack = packs[0]
    px = glob.glob(os.path.join(pack, "assets", "px_*.png"))
    print("交付包 px 素材 : %d 张" % len(px))

    if changed:
        # 有降级 —— 必须真的产出素材，且像素层必须更好
        if not px:
            print("FAIL: 标记有 %d 处降级，交付包里却一张 px 素材都没有 —— 降级逻辑空转了" % changed)
            return 1
        if len(px) != changed:
            print("FAIL: 标记的降级处数(%d) != px 素材数(%d)" % (changed, len(px)))
            return 1
        if not pxr < live:
            print("FAIL: 像素层版(%.2f%%)没有优于活字版(%.2f%%)" % (pxr, live))
            return 1
        print("PASS: %d 处降级，%d 张 px 素材，像素层版优于活字版" % (changed, len(px)))
        return 0

    # 无降级 —— 活字版必须自己达标（说明确实没有还原不出来的字形）
    if live > MAX_LIVE_DIFF:
        print("FAIL: 没有像素层降级，但活字版差异 %.2f%% 超过 %.1f%% —— "
              "说明有文字还原不出来，却没触发降级" % (live, MAX_LIVE_DIFF))
        return 1
    print("PASS: 无需降级（所有文字区域差异都在阈值下），活字版 %.2f%% 已达标" % live)
    return 0


if __name__ == "__main__":
    sys.exit(main())
