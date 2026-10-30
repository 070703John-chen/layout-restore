# -*- coding: utf-8 -*-
"""按品类分组选片：每个品类挑 N 个「组」，每组 = 1 主图 + M 附图。

为什么要有这个脚本
    之前的 `pick.py` 是**全局**配额：主图全要 + 附图按簇比例。
    但「每品类三组主图和附图」这种需求是**分品类**的 ——
    全局配额会把某些品类抽成 0 张，或者让某一品类吃掉全部名额。
    ⇒ 每个品类独立聚类、独立分配组数。

「组」是什么
    ⚠ 抓图走的是**通道 B**（必应图片索引 → alicdn 直链），
      拿到的图是**散图，没有商品结构** —— 不知道哪张附图属于哪张主图。
    所以这里的「组」= **同一品类下视觉特征相近的一簇图**（版式族）：
    组内 1 张最典型的作主图，其余作附图。
    ⇒ 这不是「同一商品的主图+附图」，是「同一版式的图组」。
    想要真实商品结构，得开带登录态的浏览器走通道 A。

用法
    python pick_multicat.py
    python pick_multicat.py --dry-run
    LAYOUT_RESTORE_PROFILE=multicat python pick_multicat.py
"""
import os
import sys
import glob
import json
import argparse
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C


def _load_feat_extractor(cfg, fast_ocr=True):
    """取 12 维特征提取器（复用 tb_family.py 的 feat_one，单一事实源）。

    ⚠ fast_ocr：给 ocr_lines 套一层「先缩到 max_side 再 OCR」的快通道。
      原实现对小图会**放大 2 倍**再 OCR，大图跑满 2600px 宽 →
      每张 3~5 秒 → 4 品类 221 张 ≈ 15 分钟，根本跑不完。
      缩到 max_side=900 后 OCR 成本降到 1/4，特征语义不变：
      `text_lines`（行数）和 `text_cover`（覆盖面积占比）都是尺度不敏感的。
      ⚠ 这是**只读快通道**，不改 tb_family.py 原文件。
    """
    home = C.g(cfg, "paths.tbhome", "")
    if not home or not os.path.isdir(home):
        raise SystemExit("paths.tbhome 没配 —— 指到含 tb_family.py 的目录")
    sys.path.insert(0, home)
    try:
        import tb_family
    except Exception as e:
        raise SystemExit("导入 tb_family 失败：%r" % (e,))
    if fast_ocr:
        import cv2
        orig = tb_family.ocr_lines

        def fast(img_bgr, zoom=1, min_conf=0.45):
            h, w = img_bgr.shape[:2]
            if max(h, w) > 900:
                s = 900.0 / max(h, w)
                img_bgr = cv2.resize(img_bgr, (int(w * s), int(h * s)),
                                     interpolation=cv2.INTER_AREA)
            return orig(img_bgr, zoom=1, min_conf=min_conf)

        tb_family.ocr_lines = fast
    return tb_family.feat_one, tb_family.FEAT_NAMES


def _cluster(X, kmin=2, kmax=6, seed=7):
    """KMeans + 轮廓系数选 k。逻辑与 tb_family.py 保持一致。"""
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import silhouette_score
    Xs = StandardScaler().fit_transform(X)
    best = None
    for k in range(kmin, kmax + 1):
        if len(X) < k + 1:
            break
        km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(Xs)
        sil = -1 if k == 2 else silhouette_score(Xs, km.labels_)
        if best is None or sil > best[1]:
            best = (k, sil, km)
    return best


def _pick_groups(recs, n_groups, per_main, per_sec):
    """从一批记录里挑 n_groups 个组：每组 1 主 + per_sec 附。

    组按**簇大小**降序取（大的簇版式更典型），组内按「离簇心最近」排。
    """
    if not recs:
        return []
    X = np.array([[r[f] for f in FEAT_NAMES] for r in recs], dtype=float)
    k, sil, km = _cluster(X)
    k = min(k, n_groups, len(recs))
    groups = []
    for cid in range(k):
        idx = np.where(km.labels_ == cid)[0]
        members = [recs[i] for i in idx]
        groups.append(members)
    groups.sort(key=len, reverse=True)
    groups = groups[:n_groups]
    return groups


def _feats_for(cat, d, feat_one, cache_dir):
    """算/读某品类的特征（带缓存）。

    ⚠ 必须缓存：feat_one 里的 OCR 每张要 ~1.5s，4 品类 ~400 张 = 10 分钟。
      改配置重跑时不该再等一遍。
    """
    os.makedirs(cache_dir, exist_ok=True)
    cp = os.path.join(cache_dir, "feats_%s.json" % cat)
    files = {}
    for sub in ("main", "secondary"):
        for f in sorted(glob.glob(os.path.join(d, sub, "*.jpg"))):
            files[os.path.basename(f)] = f
    if os.path.exists(cp):
        try:
            cached = json.load(open(cp, encoding="utf-8"))
            if set(cached.get("files", {}).keys()) == set(files.keys()):
                recs = {k: v for k, v in cached["recs"].items()}
                print("%-12s 特征命中缓存 %d 条" % (cat, len(recs)))
                return recs
        except Exception:
            pass
    recs = {}
    for i, (name, path) in enumerate(sorted(files.items())):
        try:
            ft = feat_one(path)
        except Exception as e:
            print("  FAIL %s %r" % (name, e))
            continue
        ft["name"] = name
        ft["path"] = path
        recs[name] = ft
        if (i + 1) % 20 == 0:
            print("   ...%d/%d" % (i + 1, len(files)), flush=True)
    try:
        json.dump({"files": files, "recs": recs},
                  open(cp, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("  缓存写入失败：%r" % (e,))
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--jobs-file", default="batch_jobs.json")
    ap.add_argument("--groups", type=int, default=None, help="每品类几个组")
    a = ap.parse_args()

    cfg = C.load_cfg()
    cats = C.g(cfg, "multicat.cats", {}) or {}
    if not cats:
        print("配置里没有 multicat.cats —— 在 config.local.%s.yaml 里写品类目录"
              % (C.profile_name() or "<无>"))
        return 2
    n_groups = a.groups or C.g(cfg, "multicat.groups", 3)
    per_main = C.g(cfg, "multicat.per_group_main", 1)
    per_sec = C.g(cfg, "multicat.per_group_secondary", 2)

    global FEAT_NAMES
    feat_one, FEAT_NAMES = _load_feat_extractor(cfg)

    jobs = []
    stats = []
    for cat, spec in cats.items():
        label = (spec or {}).get("label", cat)
        d = (spec or {}).get("dir", "")
        if not d or not os.path.isdir(d):
            print("跳过 %s：目录不存在 %s" % (cat, d))
            continue

        # ---- 特征（带缓存）----
        cache_dir = os.path.join(C.path_of(cfg, "work"), "_feats")
        allf = _feats_for(cat, d, feat_one, cache_dir)
        feats = {"主图": [], "附图": []}
        for name, ft in allf.items():
            dom = "主图" if os.path.basename(os.path.dirname(ft["path"])) == "main" \
                else "附图"
            feats[dom].append(ft)
        for dom in ("主图", "附图"):
            feats[dom].sort(key=lambda r: r["name"])
            print("%-12s %-4s %d 张" % (cat, dom, len(feats[dom])), flush=True)

        # ---- 分组（主/附各自聚类，再按簇号配对）----
        mains = _pick_groups(feats["主图"], n_groups, per_main, per_sec)
        secs = _pick_groups(feats["附图"], n_groups, per_main, per_sec)
        if not mains:
            print("  !! %s 没有可用主图" % cat)
            continue

        n = 0
        for gi, mgroup in enumerate(mains, 1):
            # 主图：组内最接近簇心的那张
            for j, rec in enumerate(mgroup[:per_main]):
                key = "%s%02d" % (cat.upper()[:3], gi)
                if j:
                    key += "_%d" % (j + 1)
                jobs.append({"key": key, "src": rec["path"],
                             "name": rec["name"], "dom": "主图",
                             "cluster": "%s#%d" % (cat, gi),
                             "cat": label, "cat_key": cat,
                             "title": os.path.splitext(rec["name"])[0]})
                n += 1
            # 附图：同编号的簇
            if gi - 1 < len(secs):
                for j, rec in enumerate(secs[gi - 1][:per_sec]):
                    key = "%s%02d_%d" % (cat.upper()[:3], gi, j + 1)
                    jobs.append({"key": key, "src": rec["path"],
                                 "name": rec["name"], "dom": "附图",
                                 "cluster": "%s#%d" % (cat, gi),
                                 "cat": label, "cat_key": cat,
                                 "title": os.path.splitext(rec["name"])[0]})
                    n += 1
        stats.append((cat, label, n))

    print("\n共选 %d 张" % len(jobs))
    for cat, label, n in stats:
        print("  %-12s %-10s %d 张" % (cat, label, n))
    for (dom, cat), n in sorted(Counter((j["dom"], j["cat"]) for j in jobs).items()):
        print("    %-4s %-10s %d" % (dom, cat, n))
    if a.dry_run:
        return 0
    p = C.save_jobs(cfg, jobs, a.jobs_file)
    print("-> %s" % p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
