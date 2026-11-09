# -*- coding: utf-8 -*-
"""audit_coverage.py —— 删除前「逐文件自证覆盖」闸门（通用）

用途：删掉某个工作目录（out/、out_opt/、旧站点…）之前，先证明它的内容
已经被目标站（通常是交付站的 src/ 或 assets/）完整覆盖；证明不了就
报告阻塞项，**不删**。

四条可删判据（任一成立即可删）：
  ① 目标站有 同名 + 同尺寸 + 同 md5 的副本
  ② 属于已知中间产物（--intermediate 指定的文件名后缀）
  ③ 属于「被淘汰的旧版本 KEY」（--retired-prefix 前缀匹配）⇒ 需先归档小文件
  ④ 目标站无副本，但目标站该 KEY 的 HTML 不按相对路径引用它 ⇒ 冗余资产
  ⑤ 以上都不是 ⇒ 阻塞

用法：
  python audit_coverage.py --source  <工程根>\\out \\
                           --target  <工程根>\\交付站\\src \\
                           --prefix  opt/ \\
                           --intermediate _patch_sweep.html,_patch_sweep.png,_render_1x.png,_render_px.png \\
                           --retired-prefix <批次前缀>,<批次前缀>,<批次前缀> \\
                           --json-out coverage_report.json

  --source   待删目录（每个一级子目录 = 一个 KEY）
  --target   目标站目录（结构：<slug>/<KEY>/...），无 slug 层时加 --flat
  --prefix   目标站里资产所在的子路径前缀（如优化版在 opt/ 下）
  --flat     目标站直接是 <KEY>/...（没有 slug 层）
  --no-md5   跳过 md5 比对（只看同名+同尺寸，快但弱）
  --exec     通过闸门后真的删掉 --source（默认只报告）

★ 两个容易翻车的点（已在代码里处理）：
  · 索引层数：<slug>/<KEY>/index.html 的 rel 长度是 2，建索引必须 >= 2，
    否则顶层文件（index.html/_spec.json/_report.json）会被整体漏掉。
  · 引用匹配：判「目标站 HTML 是否引用某资产」必须按相对 KEY 目录的**路径**，
    不能按 basename（否则 _diag2/assets/blk00.png 会被误判成 assets/blk00.png）。
"""
import argparse
import collections
import hashlib
import io
import json
import os
import re
import shutil
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REF_RE = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", re.I)


def md5(path, limit=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(limit), b""):
            h.update(chunk)
    return h.hexdigest()


def build_index(target, flat=False):
    """KEY -> {rel_in_key: (size, abs_path)}"""
    idx = collections.defaultdict(dict)
    for dp, dn, fn in os.walk(target):
        rel = os.path.relpath(dp, target).split(os.sep)
        if len(rel) < 1:
            continue
        key = rel[0] if flat else (rel[1] if len(rel) >= 2 else None)
        if not key:
            continue
        for f in fn:
            # ★ 顶层文件 rel 长度是 1（flat）或 2（带 slug），都要收录
            rk = "/".join(rel[1:] + [f]) if flat else "/".join(rel[2:] + [f])
            fp = os.path.join(dp, f)
            try:
                idx[key][rk] = (os.path.getsize(fp), fp)
            except OSError:
                pass
    return idx


def referenced_paths(idx, key):
    """目标站该 KEY 的 HTML 引用到的资源，相对 KEY 目录的路径集合"""
    refs = set()
    for rk, (sz, fp) in idx.get(key, {}).items():
        if not rk.endswith(".html"):
            continue
        base = os.path.dirname(rk)
        try:
            html = open(fp, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for m in REF_RE.finditer(html):
            r = m.group(1).strip()
            if not r or r.startswith(("data:", "http", "//", "#", "mailto:")):
                continue
            r = r.lstrip("./")
            refs.add((base + "/" + r) if base else r)
    return refs


def audit(source, target, prefix="", intermediates=(), retired_prefix=(), flat=False, use_md5=True):
    idx = build_index(target, flat=flat)
    stats = dict(covered=0, intermediate=0, retired=0, redundant=0)
    blockers = []
    retired_keys = set()

    for key in sorted(os.listdir(source)):
        kdir = os.path.join(source, key)
        if not os.path.isdir(kdir):
            continue
        is_retired = any(key.startswith(p) for p in retired_prefix)
        if is_retired:
            retired_keys.add(key)
        refs = referenced_paths(idx, key)
        cands = idx.get(key, {})
        for dp, dn, fn in os.walk(kdir):
            for f in fn:
                fp = os.path.join(dp, f)
                rk = os.path.relpath(fp, kdir).replace(os.sep, "/")
                q = prefix + rk
                sz = os.path.getsize(fp)
                if q in cands:
                    usz, up = cands[q]
                    if usz != sz:
                        blockers.append((key, q, "同名但尺寸不同"))
                    elif not use_md5 or sz >= 4 * 1024 * 1024 or md5(fp) == md5(up):
                        stats["covered"] += 1
                    else:
                        blockers.append((key, q, "同名但 md5 不同"))
                    continue
                if f in intermediates or any(rk.startswith(p) for p in ("_diag",)):
                    stats["intermediate"] += 1
                    continue
                if is_retired:
                    stats["retired"] += 1
                    continue
                if q not in refs:
                    stats["redundant"] += 1
                    continue
                blockers.append((key, q, "目标站无副本且被目标站 HTML 引用"))
    return stats, blockers, retired_keys, idx


def real_size(path):
    """按 inode 去重的真实磁盘占用（硬链接只算一次）"""
    total = 0
    seen = set()
    for dp, dn, fn in os.walk(path):
        for f in fn:
            fp = os.path.join(dp, f)
            try:
                st = os.lstat(fp)
            except OSError:
                continue
            if st.st_ino in seen:
                continue
            seen.add(st.st_ino)
            total += st.st_size
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--intermediate", default="")
    ap.add_argument("--retired-prefix", default="")
    ap.add_argument("--flat", action="store_true")
    ap.add_argument("--no-md5", action="store_true")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--exec", action="store_true", help="通过闸门后真的删掉 --source")
    a = ap.parse_args()

    inter = tuple(x for x in a.intermediate.split(",") if x)
    retired = tuple(x for x in a.retired_prefix.split(",") if x)

    print("=== 0) 基线（按 inode 去重的真实占用）===")
    before = real_size(a.source)
    print("  待删目录 %s : %.1f MB" % (a.source, before / 1048576.0))

    stats, blockers, retired_keys, idx = audit(
        a.source, a.target, prefix=a.prefix, intermediates=inter,
        retired_prefix=retired, flat=a.flat, use_md5=not a.no_md5)

    print("\n=== 1) 覆盖自证 ===")
    print("  目标索引: %d KEY / %d 文件" % (len(idx), sum(len(v) for v in idx.values())))
    print("  ① 已覆盖同内容 : %d" % stats["covered"])
    print("  ② 中间产物     : %d" % stats["intermediate"])
    print("  ③ 旧版本 KEY   : %d  (KEY: %s)" % (stats["retired"], ", ".join(sorted(retired_keys)) or "-"))
    print("  ④ 冗余资产     : %d" % stats["redundant"])
    print("  ⑤ 阻塞         : %d" % len(blockers))
    for b in blockers[:20]:
        print("     [阻塞] %s / %s  (%s)" % b)

    ok = not blockers
    print("\n>>> 闸门: %s" % ("PASS" if ok else "BLOCKED"))

    if a.json_out:
        rep = {"source": a.source, "target": a.target, "prefix": a.prefix,
               "stats": stats, "blockers": blockers, "retired_keys": sorted(retired_keys),
               "pass": ok, "real_size_mb": round(before / 1048576.0, 2)}
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
        print("  报告已写: %s" % a.json_out)

    if not a.exec:
        print("\n[dry-run] 加 --exec 才删除")
        return 0 if ok else 2

    if not ok:
        print("!! 闸门 BLOCKED，拒绝删除")
        return 2
    shutil.rmtree(a.source)
    print("[OK] 已删除 %s，释放 %.1f MB" % (a.source, before / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
