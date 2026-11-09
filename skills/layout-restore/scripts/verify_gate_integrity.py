# -*- coding: utf-8 -*-
"""★ OCR 品类校验闸门 —— **完整性自检**（不跑 OCR，只查已落盘的结果是否可信）。

★ 为什么要有这个（实测过的坑）：
  OCR 的结果写在增量 jsonl 里，靠 `--resume` 跳过「已判过的 key」。
  但 **resume 只认 key，不认图** ⇒ 如果某个 key 的原图后来被换掉了
  （重采 / 修正错误品类），jsonl 里那条旧结果仍然在，`--resume` 会直接跳过
  ⇒ **结果跑在旧图上，而闸门显示「已校验」**。
  本项目真踩过：手机 P2 五张错类图被换成真机图后，这 5 条 OCR 记录就是旧的。

★ 判四项：
  ① 覆盖：manifest 里的每个 key 是否都有结果（缺的 = 没校验）
  ② 重复：同一 key 是否有多条结果（多 = 重跑过，取最后一条，但要报出来）
  ③ **图变了**：结果里记的 path 是否仍等于 manifest 里的 src
     （不等 = 结果作废，必须重跑）
  ④ 判定分布：PASS / REVIEW / FAIL 各多少（FAIL 才是错类的强信号）

用法
    python verify_gate_integrity.py --manifest <jobs.json> --jsonl <result.jsonl>
退出码
    0 = 全部可信（覆盖齐 + 无旧图）
    1 = 有问题（缺 key / 有旧图 / 有 FAIL）
"""
import argparse
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def norm(p):
    try:
        return os.path.normcase(os.path.abspath(p))
    except Exception:
        return os.path.abspath(p)


def load_jsonl(path):
    """读增量结果。同一 key 多条时保留最后一条（后写的通常是重跑）。"""
    rows, dup = [], {}
    if not os.path.isfile(path):
        return {}, dup
    for i, line in enumerate(io.open(path, encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception as e:
            print("[坏行] %s 第 %d 行解析失败：%s" % (path, i, e))
            continue
        rows.append(d)
        k = d.get("key")
        dup[k] = dup.get(k, 0) + 1
    last = {}
    for d in rows:
        last[d.get("key")] = d
    return last, dup


def main():
    ap = argparse.ArgumentParser(description="OCR 闸门结果完整性自检")
    ap.add_argument("--manifest", required=True, help="jobs json")
    ap.add_argument("--jsonl", required=True, help="OCR 增量结果")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    jobs = json.load(io.open(a.manifest, encoding="utf-8"))
    src = {j["key"]: j.get("src", "") for j in jobs}
    last, dup = load_jsonl(a.jsonl)

    missing = [k for k in src if k not in last]
    extra = [k for k in last if k not in src]
    repeated = {k: v for k, v in dup.items() if v > 1}
    stale = []
    for k, d in last.items():
        s = src.get(k)
        rec = d.get("path") or ""
        if not s or not rec:
            continue
        if norm(rec) != norm(s):
            stale.append(k)

    verd = {}
    for d in last.values():
        v = (d.get("verdict") or "?").upper()
        verd[v] = verd.get(v, 0) + 1
    fails = [k for k, d in last.items() if (d.get("verdict") or "").upper() == "FAIL"]

    print("=" * 68)
    print("OCR 闸门完整性自检")
    print("  manifest : %s（%d 条）" % (a.manifest, len(jobs)))
    print("  jsonl    : %s（%d 行 / 唯一 %d）" % (a.jsonl, sum(dup.values()), len(last)))
    print("-" * 68)
    print("  覆盖     : %d / %d%s" % (len(last) - len(missing), len(jobs),
                                    "" if not missing else "  ★ 缺 %d 个：%s"
                                    % (len(missing), ", ".join(sorted(missing)[:12]))))
    print("  判定分布 : %s" % ("  ".join("%s %d" % (k, v) for k, v in sorted(verd.items()))
                                or "—"))
    print("  重复 key : %s" % (repeated or "无"))
    print("  多余 key : %s" % (extra or "无"))
    print("  ★ 旧图   : %s" % (("无") if not stale else
                              ("%d 条结果跑在旧图上，必须重跑：%s"
                               % (len(stale), ", ".join(sorted(stale)[:12])))))
    if fails:
        print("  ★ FAIL   : %d 条错类信号：%s" % (len(fails), ", ".join(sorted(fails)[:12])))

    bad = bool(missing or stale or fails)
    if a.verbose and repeated:
        print("  重复明细 : %s" % repeated)
    print("=" * 68)
    if bad:
        print("结论：★ 不通过 —— 需要重跑（用 --only-keys 跑掉 stale/missing 的 key）")
        return 1
    print("结论：通过 —— 结果覆盖完整、无旧图、无错类强信号")
    return 0


if __name__ == "__main__":
    sys.exit(main())
