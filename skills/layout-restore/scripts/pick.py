# -*- coding: utf-8 -*-
"""选片：从版式族聚类结果里挑一批**版式覆盖最广**的图。

为什么不能随机抽
    随机抽 50 张 → 里面一堆长得差不多的 → 达标率被相似图稀释，
    测出来的数字代表不了工具的真实水平。
    所以：**按版式簇分配配额**，簇内再用**最远点采样**挑互相差异最大的。

用法
    python pick.py                 # 选 50 张，写到 <work>/batch_jobs.json
    python pick.py --target 30
    python pick.py --dry-run
"""
import os
import sys
import json
import argparse

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

FEAT_KEYS = ["aspect", "white_ratio", "dark_ratio", "photo_ratio",
             "text_lines", "text_cover", "sat_blocks", "table_lines",
             "border_std", "mean_sat", "mean_val", "art_ratio"]


def vec(rec):
    v = []
    for k in FEAT_KEYS:
        x = rec.get(k, 0.0)
        v.append(float(x) if isinstance(x, (int, float)) else 0.0)
    return np.array(v, dtype=np.float64)


def fps_select(recs, k):
    """最远点采样：挑 k 个互相差异最大的。"""
    if k >= len(recs):
        return list(recs)
    X = np.array([vec(r) for r in recs])
    X = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-6)
    c = X.mean(axis=0)
    first = int(np.argmax(((X - c) ** 2).sum(axis=1)))
    picked = [first]
    d = ((X - X[first]) ** 2).sum(axis=1)
    while len(picked) < k:
        nxt = int(np.argmax(d))
        if nxt in picked:
            break
        picked.append(nxt)
        d = np.minimum(d, ((X - X[nxt]) ** 2).sum(axis=1))
    return [recs[i] for i in picked]


def allocate(total, sizes):
    """按大小比例分配配额，每份至少 1。"""
    n = len(sizes)
    base = [max(1, total // n)] * n
    rem = total - sum(base)
    order = sorted(range(n), key=lambda i: -sizes[i])
    i = 0
    while rem > 0:
        base[order[i % n]] += 1
        rem -= 1
        i += 1
    return base


def member_path(m, pathmap):
    """簇成员是**纯文件名**（如 'tb_main_015.jpg'），要用 features 表还原全路径。"""
    p = (m.get("path") or "") if isinstance(m, dict) else str(m)
    if os.path.isabs(p) and os.path.exists(p):
        return p
    return pathmap.get(os.path.basename(p), p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg = C.load_cfg()
    target = a.target or C.g(cfg, "batch.target", 50)
    fp = C.path_of(cfg, "features")
    cp = C.path_of(cfg, "clusters")
    for p in (fp, cp):
        if not os.path.exists(p):
            print("缺少文件：%s" % p)
            print("（族聚类产物要先用 tb_family.py 跑出来）")
            return 2
    feats = json.load(open(fp, encoding="utf-8"))
    clus = json.load(open(cp, encoding="utf-8"))

    pathmap = {}
    for dom in ("主图", "附图"):
        for r in feats.get(dom, []):
            pathmap[r["name"]] = r["path"]

    jobs = []
    # ---- 主图：全要 ----
    if C.g(cfg, "batch.pick.main_all", True):
        recs = {r["name"]: r for r in feats.get("主图", [])}
        n = 0
        for cid, members in sorted(clus.get("主图", {}).items()):
            for m in members:
                p = member_path(m, pathmap)
                if os.path.basename(p) not in recs:
                    continue
                n += 1
                jobs.append({"key": "M%02d" % n, "src": p,
                             "name": os.path.basename(p), "dom": "主图",
                             "cluster": cid,
                             "title": os.path.splitext(os.path.basename(p))[0]})

    # ---- 附图：按簇配额 ----
    sec_recs = {r["name"]: r for r in feats.get("附图", [])}
    sec_cl = clus.get("附图", {})
    want = min(C.g(cfg, "batch.pick.secondary", 29),
               max(0, target - len(jobs)))
    if C.g(cfg, "batch.pick.cluster_quota", True) and sec_cl:
        cids = sorted(sec_cl, key=lambda c: -len(sec_cl[c]))
        quota = allocate(want, [len(sec_cl[c]) for c in cids])
    else:
        cids, quota = list(sec_cl.keys()), [want]
    sec_jobs = []
    taken = set()
    for cid, q in zip(cids, quota):
        members = []
        for m in sec_cl[cid]:
            p = member_path(m, pathmap)
            r = sec_recs.get(os.path.basename(p))
            if r and p not in taken:
                r = dict(r)
                r["path"] = p
                members.append(r)
        for rec in fps_select(members, q):
            sec_jobs.append({"key": "S%02d" % (len(sec_jobs) + 1),
                             "src": rec["path"], "name": rec["name"],
                             "dom": "附图", "cluster": cid,
                             "title": os.path.splitext(rec["name"])[0]})
            taken.add(rec["path"])
    # 配额没填满（小簇成员不够）→ 从最大的簇补齐
    if len(sec_jobs) < want:
        for cid in cids:
            if len(sec_jobs) >= want:
                break
            members = []
            for m in sec_cl[cid]:
                p = member_path(m, pathmap)
                r = sec_recs.get(os.path.basename(p))
                if r and p not in taken:
                    r = dict(r)
                    r["path"] = p
                    members.append(r)
            for rec in fps_select(members, min(len(members), want - len(sec_jobs))):
                sec_jobs.append({"key": "S%02d" % (len(sec_jobs) + 1),
                                 "src": rec["path"], "name": rec["name"],
                                 "dom": "附图", "cluster": cid,
                                 "title": os.path.splitext(rec["name"])[0]})
                taken.add(rec["path"])
    jobs += sec_jobs

    missing = [j["key"] for j in jobs if not os.path.exists(j["src"])]
    print("共选 %d 张（主图 %d / 附图 %d），路径缺失 %d"
          % (len(jobs), len([j for j in jobs if j["dom"] == "主图"]),
             len([j for j in jobs if j["dom"] == "附图"]), len(missing)))
    from collections import Counter
    for (dom, cid), n in sorted(Counter((j["dom"], j["cluster"]) for j in jobs).items()):
        print("  %-4s 簇%-2s 选 %2d / 共 %2d"
              % (dom, cid, n, len(clus.get(dom, {}).get(cid, []))))
    if missing:
        print("  缺图:", missing)
    if a.dry_run:
        return 0
    p = C.save_jobs(cfg, jobs)
    print("-> %s" % p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
