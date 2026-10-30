# -*- coding: utf-8 -*-
"""环境自检：一条命令看清「这套流水线能不能跑、缺什么」。

执行前先跑这个 —— 与其跑到一半报 UnicodeEncodeError，不如先看清单。
也用来判断「这个 skill 现在能不能用」。

用法
    python doctor.py
    python doctor.py --verbose
"""
import os
import sys
import json
import glob
import shutil
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

OK = "[OK]  "
BAD = "[缺]  "
WARN = "[警]  "


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    cfg = C.load_cfg()
    bad = 0

    print("=" * 62)
    print("layout-restore · 环境自检")
    print("=" * 62)

    # 1. Python
    py = C.py_exe(cfg)
    if os.path.exists(py):
        print("%spython  %s" % (OK, py))
    else:
        print("%spython  %s（找不到）" % (BAD, py))
        bad += 1

    # 2. 还原引擎
    eng = C.g(cfg, "engine.restore", "")
    need = ["probe_layers.py", "autospec.py", "rebuild.py"]
    miss = [f for f in need if not os.path.exists(os.path.join(eng, f))]
    if not miss:
        print("%s还原引擎  %s" % (OK, eng))
    else:
        print("%s还原引擎  %s（缺 %s）" % (BAD, eng, ", ".join(miss)))
        bad += 1

    # 3. 关键 Python 包
    try:
        import numpy, PIL, cv2  # noqa
        print("%sPython 包  numpy / Pillow / opencv" % OK)
    except Exception as e:
        print("%sPython 包  %r" % (BAD, e))
        bad += 1
    try:
        import playwright  # noqa
        print("%spython 包  playwright" % OK)
    except Exception:
        print("%spython 包  playwright（出图必需）" % BAD)
        bad += 1

    # 4. chromium
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
        print("%schromium  可启动（出图 OK）" % OK)
    except Exception as e:
        print("%schromium  启动失败：%s" % (BAD, str(e)[:120]))
        print("      修：python -m playwright install chromium")
        bad += 1

    # 5. OCR
    try:
        import rapidocr_onnxruntime  # noqa
        print("%sOCR 包  rapidocr_onnxruntime" % OK)
    except Exception:
        print("%sOCR 包  rapidocr_onnxruntime（探针必需）" % BAD)
        bad += 1

    # 5.5 本机覆盖配置
    lp = C.local_cfg_path()
    if os.path.exists(lp):
        print("%s本机配置  %s 已加载" % (OK, os.path.basename(lp)))
    else:
        print("%s本机配置  没有 %s（路径全靠 config.yaml，"
              "仓库版是占位符）" % (WARN, os.path.basename(lp)))

    # 6. 原图库
    #    多品类批次（multicat.cats）：按品类目录查，每个品类要有 main + secondary
    mcats = C.g(cfg, "multicat.cats", {}) or {}
    if mcats:
        print("%s品类库  %d 个品类" % (OK, len(mcats)))
        for ck, cs in mcats.items():
            d = (cs or {}).get("dir", "")
            nm = len(glob.glob(os.path.join(d, "main", "*.jpg"))) if d else 0
            ns = len(glob.glob(os.path.join(d, "secondary", "*.jpg"))) if d else 0
            label = (cs or {}).get("label", ck)
            if nm and ns:
                print("   %s %-8s 主 %d / 附 %d" % (OK, label, nm, ns))
            else:
                print("   %s %-8s 主 %d / 附 %d  ← 至少各要 1 张"
                      % (BAD, label, nm, ns))
                bad += 1
    else:
        raw = C.path_of(cfg, "raw")
        if not raw:
            print("%s原图库  未配置（paths.raw —— 写进 config.local.yaml）" % BAD)
            bad += 1
        else:
            n = 0
            for sub in ("main", "secondary", "pool"):
                d = os.path.join(raw, sub)
                if os.path.isdir(d):
                    n += len([f for f in os.listdir(d)
                              if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))])
            if n:
                print("%s原图库  %s（%d 张）" % (OK, raw, n))
            else:
                print("%s原图库  %s（没图）" % (BAD, raw))
                bad += 1

    # 7. 族聚类产物（选片要用）；多品类批次走 pick_multicat.py，不需要
    if not mcats:
        for key, label in (("features", "特征表"), ("clusters", "簇表")):
            p = C.path_of(cfg, key)
            if p and os.path.exists(p):
                print("%s%s  %s" % (OK, label, p))
            else:
                print("%s%s  %s（选片要用；先用 tb_family.py 生成）"
                      % (BAD, label, p or "未配置"))
                bad += 1

    # 8. 工程脚本（tb_run 等）
    proj = C.path_of(cfg, "project")
    if not proj:
        print("%s工程脚本  paths.project 未配置" % BAD)
        bad += 1
    for f in ("tb_run.py", "tb_vec.py", "tb_px.py"):
        if proj and os.path.exists(os.path.join(proj, f)):
            print("%s工程脚本  %s" % (OK, f))
        else:
            print("%s工程脚本  %s" % (BAD, f))
            bad += 1

    # 9. 通用版 verify（公开仓库那份）
    vp = C.g(cfg, "paths.verify", "")
    if vp and os.path.exists(vp):
        print("%s通用 verify  %s" % (OK, vp))
    else:
        print("%s通用 verify  %s（验收要它；在 config.local.yaml 里配 paths.verify）"
              % (BAD, vp or "(未配置)"))
        bad += 1

    # 10. 已产出的批次
    out = C.path_of(cfg, "out")
    done = [d for d in os.listdir(out)
            if os.path.isdir(os.path.join(out, d))
            and os.path.exists(os.path.join(out, d, "_report.json"))] \
        if os.path.isdir(out) else []
    print("%s已产出  %d 个（%s）" % (OK if done else WARN, len(done), out))

    print()
    print("结论：%s" % ("可以跑" if bad == 0 else "缺 %d 项，先补齐再跑" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
