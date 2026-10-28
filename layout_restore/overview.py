# -*- coding: utf-8 -*-
r"""把多个 run 的「原图 / 活字版 / 像素层版 / 差异热力图」拼成一张总览对比图。

用法
    python -m layout_restore.overview --out overview.png --packs out
    python -m layout_restore.overview --out overview.png --packs out/A,out/B

「packs」可以是：
    · 一个目录（扫描它的子目录，每个子目录里找 deliver/*_像素级还原/）
    · 逗号分隔的多个目录
    · 一个含 deliver/ 的 run 目录本身
"""
import os
import sys
import glob
import json
import argparse

from PIL import Image, ImageDraw, ImageFont

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "assets", "NotoSansSC-VF.ttf")


def _font(sz):
    try:
        return ImageFont.truetype(FONT, sz)
    except Exception:
        return ImageFont.load_default()


def crop_orig(src, crop):
    im = Image.open(src).convert("RGB")
    t, b, l, r = (crop or [0, 0, 0, 0])
    W, H = im.size
    return im.crop((l, t, W - r if r else W, H - b if b else H))


def find_run_dirs(packs):
    """把 --packs 解析成一组 run 目录（含 deliver/ 的那一层）。"""
    out = []
    for p in packs.split(","):
        p = p.strip()
        if not p:
            continue
        if not os.path.isdir(p):
            continue
        if os.path.isdir(os.path.join(p, "deliver")):
            out.append(p)
            continue
        for d in sorted(glob.glob(os.path.join(p, "*"))):
            if os.path.isdir(os.path.join(d, "deliver")):
                out.append(d)
    return out


def collect(run_dir):
    """从一个 run 目录里收集四张图 + 指标。"""
    dl = os.path.join(run_dir, "deliver")
    dests = sorted(glob.glob(os.path.join(dl, "*_像素级还原")))
    if not dests:
        return None
    dest = dests[0]
    rp = os.path.join(dest, "_report.json")
    rep = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else {}
    live = rep.get("活字版") or rep.get("live") or {}
    px = rep.get("像素层版") or rep.get("px") or {}

    def first(pattern):
        g = sorted(glob.glob(os.path.join(dest, pattern)))
        return g[0] if g else None

    p_live = first("*_还原_活字版_1x.png")
    p_px = first("*_还原_像素层版_1x.png")
    p_hm = first("*_差异热力图_活字版.png")
    spec_p = os.path.join(run_dir, "_spec.json")
    src = None
    crop = [0, 0, 0, 0]
    if os.path.exists(spec_p):
        s = json.load(open(spec_p, encoding="utf-8"))
        src = s.get("src")
        crop = s.get("crop", crop)
        if src and not os.path.isabs(src):
            for cand in (os.path.join(os.getcwd(), src),
                         os.path.join(os.path.dirname(run_dir), src)):
                if os.path.exists(cand):
                    src = cand
                    break
    if not src or not os.path.exists(src):
        return None
    imgs = [("原图", crop_orig(src, crop))]
    for cap, p in (("活字版(可编辑)", p_live), ("像素层版", p_px), ("差异热力图", p_hm)):
        if p:
            imgs.append((cap, Image.open(p).convert("RGB")))
    if len(imgs) < 2:
        return None
    return {"name": os.path.basename(run_dir), "imgs": imgs,
            "live": live, "px": px}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--packs", default="out")
    ap.add_argument("--cell-h", type=int, default=560)
    a = ap.parse_args()

    runs = find_run_dirs(a.packs)
    rows = []
    for r in runs:
        c = collect(r)
        if c:
            rows.append(c)
    if not rows:
        print("没找到可拼的 run 目录（要含 deliver/*_像素级还原/）")
        return 2

    CW = a.cell_h
    lab_w = 200
    gap = 12
    header_h = 46
    ncol = max(len(r["imgs"]) for r in rows)
    total_w = lab_w + ncol * (CW + gap) + gap
    row_h = []
    for r in rows:
        w, h = r["imgs"][0][1].size
        row_h.append(int(round(CW * h / w)))
    total_h = header_h + sum(h + gap + 40 for h in row_h) + 20

    canvas = Image.new("RGB", (total_w, total_h), (18, 18, 20))
    d = ImageDraw.Draw(canvas)
    f, fs = _font(20), _font(15)
    heads = ["原图", "活字版（可编辑）", "像素层版", "差异热力图"]
    for i, h in enumerate(heads[:ncol]):
        d.text((lab_w + i * (CW + gap) + 8, 12), h, font=f, fill=(255, 220, 120))

    y = header_h
    for r, rh in zip(rows, row_h):
        d.text((10, y + 4), r["name"][:24], font=fs, fill=(240, 240, 240))
        lv = r["live"].get("diff_gt20_pct")
        pv = r["px"].get("diff_gt20_pct")
        d.text((10, y + 26), ("活字 %.2f%%" % lv) if lv is not None else "活字 —",
               font=fs, fill=(120, 220, 255))
        d.text((10, y + 46), ("像素 %.2f%%" % pv) if pv is not None else "像素 —",
               font=fs, fill=(150, 255, 170))
        for i, (cap, im) in enumerate(r["imgs"]):
            im2 = im.resize((CW, rh), Image.LANCZOS)
            canvas.paste(im2, (lab_w + i * (CW + gap), y))
        y += rh + gap + 40

    canvas.save(a.out)
    print("wrote %s %s  (%d 个 run)" % (a.out, canvas.size, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
