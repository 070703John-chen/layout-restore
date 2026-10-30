# -*- coding: utf-8 -*-
"""用**修好的**引擎重新生成 examples/results/。

为什么要重生成：仓库里入库的 metrics.md 显示三个样例的
「活字版 diff」与「像素层版 diff」**完全相同**（3.64/3.64、3.53/3.53、5.11/5.11）
—— 像素层从来没生效（P0-1）。这批数字是**假的产品证明**，必须重出。

用法：python examples/regen_results.py
"""
import os
import sys
import glob
import json
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
OUT = os.path.join(ROOT, "out")
RES = os.path.join(ROOT, "examples", "results")
SAMPLES = ["demo_param_card", "demo_compare", "demo_brace_title"]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run(args):
    p = subprocess.run([PY] + args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    os.makedirs(RES, exist_ok=True)
    for key in SAMPLES:
        src = os.path.join(ROOT, "examples", "samples", "%s.png" % key)
        print("\n===== build %s =====" % key, flush=True)
        rc, o = run(["-m", "layout_restore.cli", "build", "--src", src,
                     "--key", key, "--out", OUT])
        if rc != 0:
            print(o[-2500:])
            print("!! %s build 失败" % key)
            return 2
        for l in o.splitlines():
            if any(k in l for k in ("ok ", "像素层", "降级", "diff>20")):
                print("   " + l, flush=True)

    # ---- 对比图 + 热力图（活字版）----
    for key in SAMPLES:
        d = os.path.join(OUT, key, "deliver")
        if not os.path.isdir(d):
            print("!! 找不到交付目录 %s" % d)
            continue
        for tag, pat in (("对比", "*_对比_原图左_还原右_活字版.png"),
                         ("热力图", "*_差异热力图_活字版.png")):
            # ⚠ 成品在 deliver/<key>_像素级还原/ **子目录**里，不是 deliver/ 根下
            hits = glob.glob(os.path.join(d, "**", pat), recursive=True)
            if not hits:
                print("!! %s 缺 %s（%s）" % (key, tag, pat))
                continue
            dst = os.path.join(RES, "%s_%s.png" % (key, tag))
            shutil.copy(hits[0], dst)
            print("  %s -> %s" % (os.path.basename(hits[0]), os.path.basename(dst)))
        # 清理验收留下的临时报告（不该进交付物）
        for stray in glob.glob(os.path.join(d, "**", "_verify.json"), recursive=True):
            os.remove(stray)
            print("  清理 %s" % os.path.basename(stray))

    # ---- 总览图 ----
    rc, o = run(["-m", "layout_restore.cli", "overview",
                 "--out", os.path.join(RES, "overview.png"), "--packs", OUT])
    print("overview rc=%d" % rc)
    if rc:
        print(o[-1500:])

    # ---- 指标表 ----
    rc, o = run(["-m", "layout_restore.cli", "report",
                 "--out", os.path.join(RES, "metrics.md"), "--packs", OUT])
    print("report rc=%d" % rc)
    if rc:
        print(o[-1500:])
    else:
        print(open(os.path.join(RES, "metrics.md"), encoding="utf-8").read())

    # ---- 自检：像素层必须真的优于活字版 ----
    bad = 0
    for key in SAMPLES:
        rp = os.path.join(OUT, key, "_report.json")
        if not os.path.exists(rp):
            continue
        rep = json.load(open(rp, encoding="utf-8"))
        live = rep.get("live", {}).get("diff_gt20_pct")
        px = rep.get("px", {}).get("diff_gt20_pct")
        n_px = len(glob.glob(os.path.join(OUT, key, "assets", "px_*.png")))
        print("%-18s live=%s px=%s px素材=%d" % (key, live, px, n_px))
        if live is not None and px is not None and px >= live:
            print("   !! 像素层没有优于活字版 —— 降级又空转了")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
