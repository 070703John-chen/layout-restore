# -*- coding: utf-8 -*-
"""生成指标表 Markdown（活字版 / 像素层版 的差异率与 PSNR）。

用法
    python -m layout_restore.report --out metrics.md --packs out
"""
import os
import sys
import glob
import json
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def collect(packs):
    out = []
    for p in packs.split(","):
        p = p.strip()
        if not p or not os.path.isdir(p):
            continue
        cands = [p] if os.path.isdir(os.path.join(p, "deliver")) else \
            sorted(glob.glob(os.path.join(p, "*")))
        for d in cands:
            rp = os.path.join(d, "_report.json")
            if not os.path.exists(rp):
                continue
            try:
                rep = json.load(open(rp, encoding="utf-8"))
            except Exception:
                continue
            live = rep.get("live") or rep.get("活字版") or {}
            px = rep.get("px") or rep.get("像素层版") or {}
            out.append({
                "key": os.path.basename(d.rstrip(os.sep)),
                "live": live.get("diff_gt20_pct"),
                "px": px.get("diff_gt20_pct"),
                "live_psnr": live.get("psnr"),
                "px_psnr": px.get("psnr"),
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--packs", default="out")
    ap.add_argument("--title", default="layout-restore · 还原指标")
    a = ap.parse_args()

    rows = collect(a.packs)
    L = ["# %s" % a.title, "",
         "| KEY | 活字版 diff>20 % | 像素层版 diff>20 % | 活字 PSNR | 像素 PSNR |",
         "|---|---|---|---|---|"]
    for r in rows:
        L.append("| %s | %s | %s | %s | %s |" % (
            r["key"],
            ("%.2f" % r["live"]) if r["live"] is not None else "—",
            ("%.2f" % r["px"]) if r["px"] is not None else "—",
            ("%.2f" % r["live_psnr"]) if r["live_psnr"] is not None else "—",
            ("%.2f" % r["px_psnr"]) if r["px_psnr"] is not None else "—"))
    if not rows:
        L.append("| （还没有产物） | | | | |")
    L.append("")
    L.append("> `diff>20 %` = 通道最大差 > 20 的像素占比，越小越接近原图。")
    L.append("> 活字版 = 文字是**活的**（可改价/改文案）；像素层版 = 字形用原图裁切，逐像素一致。")
    open(a.out, "w", encoding="utf-8").write("\n".join(L))
    print("wrote %s  (%d 行)" % (a.out, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
