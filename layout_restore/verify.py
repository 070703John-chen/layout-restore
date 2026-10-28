# -*- coding: utf-8 -*-
r"""验收：从**交付出去的源件包**重新渲染，和原图对账。

为什么必须这么验
    验收要验的是「客户拿到包之后打开的效果」，不是中间目录。
    中间目录和交付包不一致时，中间目录的指标是**假的**。
    （2026-10-24 第一次跑就抓到两个回写 bug：
      同名文字用 hits[0] 匹配 → 两处同名文字全写成第一处的值；
      文本含 & 时 HTML 里是 &amp; → 匹配不上，寻优值没回写。）

用法
    python -m layout_restore.verify --pack out/XCAT_D --ref refs/XCAT_D.jpg
    python -m layout_restore.verify --pack out/XCAT_D      # ref 从 _spec.json 里读

退出码
    0 = 全部一致；1 = 有不一致
"""
import os
import sys
import json
import argparse

import numpy as np
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def crop_orig(src, crop):
    im = Image.open(src).convert("RGB")
    t, b, l, r = (crop or [0, 0, 0, 0])
    W, H = im.size
    return im.crop((l, t, W - r if r else W, H - b if b else H))


def _render_with_browser(html_path, w, h, br, tmp):
    from playwright.sync_api import sync_playwright  # noqa: F401
    page = br.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
    page.goto("file:///" + html_path.replace("\\", "/"))
    try:
        page.evaluate("async () => { await document.fonts.ready; }")
    except Exception:
        pass
    page.wait_for_timeout(250)
    page.locator("#poster").screenshot(path=tmp)
    page.close()
    return np.asarray(Image.open(tmp).convert("RGB")).astype(int)


def compare(orig, built):
    d = np.abs(orig - built).max(axis=2)
    pct = round(100.0 * float((d > 20).sum()) / d.size, 2)
    mean = round(float(np.abs(orig - built).mean()), 3)
    mse = float(((orig - built) ** 2).mean())
    psnr = 99.0 if mse == 0 else round(float(10.0 * np.log10(255.0 ** 2 / mse)), 2)
    return {"diff_gt20_pct": pct, "mean_abs": mean, "psnr": psnr}


def main():
    ap = argparse.ArgumentParser(description="从交付源件包重渲并对账")
    ap.add_argument("--pack", required=True, help="源件包目录（含 index.html / index_px.html）")
    ap.add_argument("--ref", default=None, help="原图；不给则从 _spec.json 的 src 读")
    ap.add_argument("--report", default=None, help="报告输出路径（默认 <pack>/_verify.json）")
    ap.add_argument("--tol", type=float, default=0.15,
                    help="与 _report.json 记录的差异率允许的偏差（百分点）")
    a = ap.parse_args()

    pack = os.path.abspath(a.pack)
    spec_p = os.path.join(pack, "_spec.json")
    spec = {}
    if os.path.exists(spec_p):
        spec = json.load(open(spec_p, encoding="utf-8"))

    ref = a.ref
    if not ref:
        ref = spec.get("src")
        if ref and not os.path.isabs(ref):
            for cand in (os.path.join(os.getcwd(), ref),
                         os.path.join(os.path.dirname(pack), ref)):
                if os.path.exists(cand):
                    ref = cand
                    break
    if not ref or not os.path.exists(ref):
        print("找不到原图：给 --ref 或在 _spec.json 里写 src")
        return 2

    crop = spec.get("crop", [0, 0, 0, 0])
    O = np.asarray(crop_orig(ref, crop)).astype(int)
    H, W = O.shape[:2]
    expect = {}
    rp = os.path.join(pack, "_report.json")
    if os.path.exists(rp):
        try:
            expect = json.load(open(rp, encoding="utf-8"))
        except Exception:
            pass

    from playwright.sync_api import sync_playwright
    tmp = os.path.join(pack, "_verify_render.png")
    bad = 0
    out = {"pack": pack, "ref": ref, "live": None, "px": None}
    with sync_playwright() as p:
        br = p.chromium.launch()
        for tag, html in (("live", "index.html"), ("px", "index_px.html")):
            hp = os.path.join(pack, html)
            if not os.path.exists(hp):
                print("  %-5s 缺 %s（跳过）" % (tag, html))
                continue
            B = _render_with_browser(hp, W, H, br, tmp)
            m = compare(O, B)
            out[tag] = m
            # 与 rebuild 时记录的指标对账（差异只应来自重渲环境）
            exp = (expect.get(tag) or expect.get({"live": "活字版", "px": "像素层版"}[tag]) or {})
            ep = exp.get("diff_gt20_pct")
            note = ""
            if ep is not None:
                if abs(m["diff_gt20_pct"] - ep) <= a.tol:
                    note = "OK"
                else:
                    note = "!! MISMATCH"
                    bad += 1
            print("  %-5s diff>20 = %6.2f%%   mean_abs=%-8s psnr=%-7s %s"
                  % (tag, m["diff_gt20_pct"], m["mean_abs"], m["psnr"], note))
        br.close()
    try:
        os.remove(tmp)
    except Exception:
        pass

    dest = a.report or os.path.join(pack, "_verify.json")
    json.dump(out, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("报告 -> %s" % dest)
    if bad == 0:
        print("全部一致 [OK]")
    else:
        print("%d 处不一致 [FAIL]" % bad)
    return bad


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
