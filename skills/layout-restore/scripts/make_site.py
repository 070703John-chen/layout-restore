# -*- coding: utf-8 -*-
"""生成对比网站：原图 | 还原图 **横向并排** 的卡片 + 可放大的灯箱。

产出（建在 paths.project / site.dir 下）
    index.html      单文件站点（数据已内联 → 双击即可离线打开）
    full/<KEY>_*    全分辨率图（原图 / 活字 / 像素 / 热力图）
    thumbs/<KEY>_*  缩略图
    data.json       清单与指标

用法
    python make_site.py
    python make_site.py --out 别的目录
"""
import os
import sys
import json
import shutil
import argparse

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site_template.html")

README = """# 对比站

**双击 `index.html` 即可打开**（数据已内联，离线可用，不需要起服务器）。

| 操作 | 说明 |
|---|---|
| 卡片 | 每格 **左边原图 / 右边还原图 横向并排**，左下角有标签；右上角差异率，绿=达标(≤8%)、红=超差 |
| 点卡片 | 打开大图灯箱（滑块对比，可放大 1~4× 跟随鼠标、拖画面平移） |
| 顶部「卡片右侧显示」 | 一次把 50 张的右图全换成 活字版 / 像素层版 / 差异热力图 |
| ← → | 上一张 / 下一张 |
| 1 / 2 / 3 | 切版本 |
| 顶部筛选 | 全部 / 达标 / 超差 / 主图 / 附图 / 艺术字 |
| 搜索框 | 按 KEY 或文件名搜 |
"""


def _find_heatmap(cfg, od, key):
    """找差异热力图。

    ⚠ 两条路径都要找（2026-10-30 实测：只找一条 → 50 张热力图全丢，
      站点「差异热力图」按钮静默退化成显示活字版）：
      ① out/<KEY>/deliver/<KEY>_像素级还原/   —— 公开仓库版引擎把交付写在这里
      ② <paths.deliver>/<KEY>_像素级还原/    —— 共享引擎把交付写在这里（作品集）
    """
    cands = [os.path.join(od, "deliver")]
    dl = C.g(cfg, "paths.deliver", "")
    if dl:
        cands.append(dl)
    for root in cands:
        if not root or not os.path.isdir(root):
            continue
        for sub in os.listdir(root):
            if not sub.endswith("_像素级还原"):
                continue
            d = os.path.join(root, sub)
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if f.endswith("_差异热力图_活字版.png"):
                    return os.path.join(d, f)
    return None


def collect_assets(cfg, jobs, out_root):
    """把每张的原图/各版本图拷进 full/，并生成缩略。"""
    full = os.path.join(out_root, "full")
    th = os.path.join(out_root, "thumbs")
    os.makedirs(full, exist_ok=True)
    os.makedirs(th, exist_ok=True)
    thumb = int(C.g(cfg, "site.thumb", 420))
    entries = []
    for j in jobs:
        key = j["key"]
        od = os.path.join(C.path_of(cfg, "out"), key)
        ent = {"key": key, "name": j["name"], "dom": j["dom"],
               "cluster": j["cluster"], "src": j["src"]}
        pairs = [("orig", j["src"]), ("live", os.path.join(od, "_render_1x.png")),
                 ("px", os.path.join(od, "_render_px.png"))]
        hm = _find_heatmap(cfg, od, key)
        if hm:
            pairs.append(("hm", hm))
        for tag, p in pairs:
            if not os.path.exists(p):
                if tag in ("orig", "live"):
                    ent = None
                    break
                continue
            ext = ".jpg" if tag == "orig" else ".png"
            dst = os.path.join(full, "%s_%s%s" % (key, tag, ext))
            if not os.path.exists(dst):
                shutil.copy(p, dst)
            # ⚠ 图片路径用 img_ 前缀 —— 直接叫 live/px 会把同名的**指标数字**覆盖掉
            ent["img_" + tag] = "full/%s_%s%s" % (key, tag, ext)
        if not ent:
            continue
        # 缩略：原图 + 各版本
        try:
            im = Image.open(j["src"]).convert("RGB")
            im.thumbnail((thumb, thumb), Image.LANCZOS)
            im.save(os.path.join(th, "%s.jpg" % key), quality=86)
            ent["thumb"] = "thumbs/%s.jpg" % key
        except Exception as e:
            print("缩略失败 %s %r" % (key, e))
        for tag in ("live", "px", "hm"):
            rel = ent.get("img_" + tag)
            if not rel:
                continue
            try:
                im = Image.open(os.path.join(out_root, rel)).convert("RGB")
                im.thumbnail((thumb, thumb), Image.LANCZOS)
                fn = "%s_%s.jpg" % (key, tag)
                im.save(os.path.join(th, fn), quality=86)
                ent["thumb_" + tag] = "thumbs/" + fn
            except Exception as e:
                print("缩略失败 %s %s %r" % (key, tag, e))
        entries.append(ent)
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="站点输出目录")
    a = ap.parse_args()

    cfg = C.load_cfg()
    jobs = C.load_jobs(cfg)
    if not jobs:
        print("没有任务 —— 先跑 pick.py")
        return 2
    rows = {r["key"]: r for r in C.collect(cfg, [j["key"] for j in jobs])}
    out_root = os.path.abspath(a.out or os.path.join(
        C.path_of(cfg, "project"), C.g(cfg, "site.dir", "批量复刻50张_对比站")))
    if os.path.isdir(out_root):
        shutil.rmtree(out_root)
    os.makedirs(out_root, exist_ok=True)

    entries = collect_assets(cfg, jobs, out_root)
    for e in entries:
        m = rows.get(e["key"], {})
        e["live"] = m.get("live")
        e["px"] = m.get("px")
        e["psnr"] = m.get("psnr")
        e["n_text"] = m.get("n_text", 0)

    json.dump(entries, open(os.path.join(out_root, "data.json"), "w",
                             encoding="utf-8"), ensure_ascii=False, indent=1)

    html = open(TPL, encoding="utf-8").read()
    if "/*__DATA__*/[]" not in html:
        print("!! 模板缺少数据占位符")
        return 2
    html = html.replace("/*__DATA__*/[]", json.dumps(entries, ensure_ascii=False))
    open(os.path.join(out_root, "index.html"), "w", encoding="utf-8").write(html)
    open(os.path.join(out_root, "README.md"), "w", encoding="utf-8").write(README)

    n = sum(len(fs) for _, _, fs in os.walk(out_root))
    size = sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(out_root) for f in fs)
    print("站点 -> %s" % out_root)
    print("  %d 条 / %d 个文件 / %.1f MB" % (len(entries), n, size / 1048576.0))
    print("  打开：%s" % os.path.join(out_root, "index.html"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
