# -*- coding: utf-8 -*-
"""指标汇总 + 达标率。

★ 三条口径必须分开报，否则数字会骗人：
    ① 交付达标率   = 活字版**或**像素层版达标（交付本来就给两个版本，这才是「能不能用」）
    ② 活字版达标率 = 活字版自身达标
    ③ 有效复刻达标率 = 只统计文字元素 ≥ real_text_min 的图
       （文字太少的图多为纯产品照，差异率≈0 是因为**没活干**，不能算复刻能力的证明）

用法
    python report.py
    python report.py --out 报告.md
"""
import os
import sys
import json
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C


def bucket(v, th):
    if v is None:
        return "无产物"
    if v <= 3:
        return "≤3%"
    if v <= th:
        return "3~%.0f%%" % th
    if v <= 15:
        return "%.0f~15%%" % th
    return ">15%"


def px_all(cfg, rows):
    """全部文字都被 px 化的样本 —— 像素层版的 0% 差异是**构造出来的**，不是质量。

    实测 47/62 交付样本是这种：每个字都换成原图裁切块，
    像素层版当然逐像素相同 —— 但那是「没做活」，不能当达成度报出去。
    """
    out = []
    for r in rows:
        sp = C.spec_path(cfg, r["key"])
        if not os.path.exists(sp):
            continue
        try:
            s = json.load(open(sp, encoding="utf-8"))
        except Exception:
            continue
        ts = s.get("text", [])
        if ts and all(t.get("px") for t in ts):
            out.append(r["key"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="Markdown 报告路径")
    ap.add_argument("--json", default=None, help="指标明细 JSON 路径")
    ap.add_argument("--jobs-file", default="batch_jobs.json",
                    help="任务清单文件名（pick.py --target N 时是 batch_jobs_N.json）")
    a = ap.parse_args()

    cfg = C.load_cfg()
    th = C.g(cfg, "report.pass_threshold", 8.0)
    rt = C.g(cfg, "report.real_text_min", 3)
    jobs = C.load_jobs(cfg, a.jobs_file)
    meta = {j["key"]: j for j in jobs}
    rows = C.collect(cfg, [j["key"] for j in jobs] if jobs else None)
    for r in rows:
        j = meta.get(r["key"])
        if j:
            r["name"] = j["name"]
            r["dom"] = j["dom"]
            r["cluster"] = j["cluster"]
            r["cat"] = j.get("cat", "")

    ok = [r for r in rows if r["live"] is not None]
    n = len(ok)
    hit = [r for r in ok if r["live"] <= th]
    pxs = [r for r in ok if r["px"] is not None and r["px"] <= th]
    deliv = [r for r in ok if (r["live"] is not None and r["live"] <= th)
             or (r["px"] is not None and r["px"] <= th)]
    real = [r for r in ok if r["n_text"] >= rt]
    realhit = [r for r in real if r["live"] <= th]
    vf = [r for r in ok if r["verify_ok"] is not None]
    vok = [r for r in vf if r["verify_ok"]]
    art = [r for r in ok if (r["live"] is not None and r["live"] > th)
           and (r["px"] is not None and r["px"] <= th)]
    trivial = px_all(cfg, ok)

    print("=" * 68)
    print("批量复刻 · 达标率")
    print("=" * 68)
    print("总数 %d / 产出成功 %d" % (len(rows), n))
    print()
    print("★ 交付达标率（活字或像素任一 ≤%.0f%%）： %d / %d = %.1f%%"
          % (th, len(deliv), n, 100.0 * len(deliv) / max(1, n)))
    print("★ 活字版 ≤%.0f%% 达标率（全部）：         %d / %d = %.1f%%"
          % (th, len(hit), n, 100.0 * len(hit) / max(1, n)))
    print("★ 活字版 ≤%.0f%% 达标率（有效复刻 文字≥%d）： %d / %d = %.1f%%"
          % (th, rt, len(realhit), len(real),
             100.0 * len(realhit) / max(1, len(real))))
    print("  另有 %d 张文字元素 <%d（多为纯产品照，差异率≈0 是因为没活干）"
          % (len([r for r in ok if r["n_text"] < rt]), rt))
    if pxs:
        print("  像素层版 ≤%.0f%%：                    %d / %d = %.1f%%"
              % (th, len(pxs), n, 100.0 * len(pxs) / max(1, n)))
    if vf:
        print("  verify 包自洽率：                    %d / %d = %.1f%%"
              % (len(vok), len(vf), 100.0 * len(vok) / len(vf)))
    print("  艺术字（活字超差/像素达标）：          %d 张" % len(art))
    if art:
        print("    " + " ".join(r["key"] for r in art))
    if trivial:
        print("  ⚠ 全部文字已像素化的样本：              %d 张" % len(trivial))
        print("    它们的像素层版 0% 差异是**构造出来的**（每字都换成原图裁切块），"
              "不能当达成度报出去")
        print("    " + " ".join(trivial[:30]) + (" …" if len(trivial) > 30 else ""))

    b = defaultdict(list)
    for r in ok:
        b[bucket(r["live"], th)].append(r)
    print("\n--- 分布 ---")
    for k in ("≤3%", "3~%.0f%%" % th, "%.0f~15%%" % th, ">15%"):
        if k in b:
            print("  %-8s %2d 张  %s" % (k, len(b[k]),
                                         " ".join(x["key"] for x in b[k])))
    print("\n--- 按域 ---")
    for dom in ("主图", "附图"):
        g = [r for r in ok if r["dom"] == dom]
        if g:
            gh = [r for r in g if r["live"] <= th]
            avg = sum(r["live"] for r in g) / len(g)
            med = sorted(r["live"] for r in g)[len(g) // 2]
            print("  %-4s %2d 张  达标 %2d (%.0f%%)  平均 %.2f%%  中位 %.2f%%"
                  % (dom, len(g), len(gh), 100.0 * len(gh) / len(g), avg, med))
    # 按品类（多品类批次）
    bycat = defaultdict(list)
    for r in ok:
        if r.get("cat"):
            bycat[r["cat"]].append(r)
    if bycat:
        print("\n--- 按品类 ---")
        for cat in sorted(bycat):
            g = bycat[cat]
            gh = [r for r in g if r["live"] <= th]
            avg = sum(r["live"] for r in g) / len(g)
            print("  %-8s %2d 张  达标 %2d (%.0f%%)  平均 %.2f%%"
                  % (cat, len(g), len(gh), 100.0 * len(gh) / len(g), avg))
    print("\n--- 按簇 ---")
    byc = defaultdict(list)
    for r in ok:
        byc[(r["dom"], r["cluster"])].append(r)
    for k in sorted(byc):
        g = byc[k]
        gh = [r for r in g if r["live"] <= th]
        print("  %-4s 簇%-2s %d 张  达标 %d  %s"
              % (k[0], k[1], len(g), len(gh),
                 " ".join("%.1f" % r["live"] for r in
                          sorted(g, key=lambda x: x["live"]))))

    # ---- 落盘 ----
    md = a.out or os.path.join(C.path_of(cfg, "work"), "batch_report.md")
    L = ["# 批量复刻 · 达标率", "",
         "- 达标口径：活字版 `diff_gt20_pct` ≤ %.0f%%" % th,
         "- 产出成功 %d / 计划 %d" % (n, len(rows)), "",
         "> **三条口径必须分开看**：",
         "> · 交付达标率 = 活字或像素任一达标（交付本来就给两个版本）",
         "> · 活字版达标率 = 文字真的用替代字体重建时能到多少",
         "> · 有效复刻达标率 = 只统计文字元素 ≥%d 的图（纯产品照差异率≈0 是因为没活干）"
         % rt, "",
         "## 结果", "", "| 指标 | 值 |", "|---|---|",
         "| **交付达标率** | **%d / %d = %.1f%%** |"
         % (len(deliv), n, 100.0 * len(deliv) / max(1, n)),
         "| 活字版达标率 | %d / %d = %.1f%% |"
         % (len(hit), n, 100.0 * len(hit) / max(1, n)),
         "| 有效复刻达标率（文字≥%d） | %d / %d = %.1f%% |"
         % (rt, len(realhit), len(real), 100.0 * len(realhit) / max(1, len(real))),
         "| 像素层版达标率 | %d / %d = %.1f%% |"
         % (len(pxs), n, 100.0 * len(pxs) / max(1, n)),
         "| 艺术字（活字超差 / 像素达标） | %d |" % len(art),
         # ⚠ 中文里的字面 % 必须写成 %% —— 否则 "0% 是构造的" 里的 %s 被当成格式符，
         #   整份报告在**构造 L 列表时**就 ValueError 崩掉，
         #   stdout 的数字还打完了（看着像成功），但 .md 根本没落盘。
         #   2026-10-30 修（此前 batch_report.md 一直是旧文件，缺这一口径行）。
         "| ⚠ 全部文字已像素化（像素层 0%% 是构造的） | %d |" % len(trivial),
         "| verify 包自洽率 | %d / %d = %.1f%% |"
         % (len(vok), len(vf), 100.0 * len(vok) / max(1, len(vf))),
         "", "## 分布", "", "| 区间 | 张数 | KEY |", "|---|---|---|"]
    for k in ("≤3%", "3~%.0f%%" % th, "%.0f~15%%" % th, ">15%"):
        if k in b:
            L.append("| %s | %d | %s |" % (k, len(b[k]),
                                          " ".join(x["key"] for x in b[k])))
    # 按品类（多品类批次才有）
    bycat_md = defaultdict(list)
    for r in ok:
        if r.get("cat"):
            bycat_md[r["cat"]].append(r)
    if bycat_md:
        L += ["", "## 按品类", "", "| 品类 | 张数 | 达标 | 达标率 | 平均差异% | 达标的 KEY |",
              "|---|---|---|---|---|---|"]
        for cat in sorted(bycat_md):
            g = bycat_md[cat]
            gh = [r for r in g if r["live"] <= th]
            L.append("| %s | %d | %d | %.0f%% | %.2f | %s |" % (
                cat, len(g), len(gh), 100.0 * len(gh) / max(1, len(g)),
                sum(r["live"] for r in g) / len(g),
                " ".join(r["key"] for r in sorted(gh, key=lambda x: x["live"]))))
    L += ["", "## 逐张明细", "",
          "| KEY | 品类 | 原图 | 域/簇 | 文字元素 | 活字% | 像素% | PSNR |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append("| %s | %s | %s | %s/%s | %d | %s | %s | %s |" % (
            r["key"], r.get("cat", ""), r["name"], r["dom"], r["cluster"], r["n_text"],
            ("%.2f" % r["live"]) if r["live"] is not None else "—",
            ("%.2f" % r["px"]) if r["px"] is not None else "—",
            ("%.1f" % r["psnr"]) if r["psnr"] is not None else "—"))
    # ⚠ dirname 可能是空串（--out 报告.md 相对路径）→ makedirs('') 直接 FileNotFoundError
    d = os.path.dirname(os.path.abspath(md))
    os.makedirs(d, exist_ok=True)
    open(md, "w", encoding="utf-8").write("\n".join(L))
    print("\n报告 -> %s" % md)

    jp = a.json or os.path.join(C.path_of(cfg, "work"), "batch_metrics.json")
    os.makedirs(os.path.dirname(os.path.abspath(jp)), exist_ok=True)
    json.dump(rows, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("指标 -> %s" % jp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
