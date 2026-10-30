# -*- coding: utf-8 -*-
"""扫仓库里的残留绝对路径 / 项目耦合（发布前自检）。"""
import os
import re
import sys
import glob

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAT = re.compile(r"[A-Za-z]:[\\/]{1,2}(?![\\/])[^\s\"'<>|]*")
SKIP_LINES = ("http://", "https://", "xmlns", "file:///", "svg", "viewBox")
# 真正敏感的东西：私人路径 / 私人品牌 / 他人的产品名 / 私人邮箱
# （GitHub handle 是公开的，仓库 URL 里本来就有，不算敏感）
#
# ⚠ **正斜杠和反斜杠都要匹配**（2026-10-30 修）。
#   原来只写反斜杠形式（"D:\\云端全存档"），而 yaml 里全是正斜杠
#   （"D:/云端全存档/..."）→ 一条都匹配不上 → 自检报「0 处残留」，
#   实际有 7 条本机绝对路径躺在 skills/layout-restore/config.yaml 里。
#   ⇒ 自检本身也会骗人，这是最危险的一类。
#   修法：每个关键字同时存两种斜杠形式。
BANNED_BASE = ("D:/云端全存档", "D:/电商素材", "C:/Users", "D:/Python311",
               "AL-LED", "小熊电煮锅", "小熊", "陈明令", "2913454968")
BANNED = []
for _k in BANNED_BASE:
    BANNED.append(_k)
    BANNED.append(_k.replace("/", "\\"))
# 自检脚本自己含这些字样，跳过
SELF_SKIP = {"tests/check_no_private_paths.py"}
# 运行产物目录（.gitignore 已排除，不入库 → 不算发布残留）
IGNORED_DIRS = ("out", "specs", ".work", "runs", ".git", "__pycache__",
                "node_modules", ".venv", "venv", "build", "dist")


def _skip(rel):
    """入库相关才查；运行产物目录跳过。"""
    if rel in SELF_SKIP:
        return True
    return any(seg in IGNORED_DIRS for seg in rel.split("/"))


def _selftest():
    """阴性对照：确认本脚本**能**抓到已知违规。

    为什么必须做：原来 BANNED 只匹配反斜杠形式，而 yaml 里全是正斜杠
    → 一条都没匹配上 → 报「0 残留」，实际有 7 条绝对路径躺在 config.yaml 里。
    ⇒ 自检本身也会骗人。没有阴性对照的「0 残留」不可信。
    """
    probe = 'x = "D:/云端全存档/私有路径/y"'
    hit_kw = any(k in probe for k in BANNED)
    hit_pat = PAT.search(probe) is not None
    ok = hit_kw and hit_pat
    print("阴性对照 %s  关键词命中=%s 绝对路径命中=%s"
          % ("[OK]" if ok else "[!!] 自检本身失灵", hit_kw, hit_pat))
    return 0 if ok else 1


def main():
    bad = _selftest()
    for f in sorted(glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        if _skip(rel):
            continue
        for i, l in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
            s = l.strip()
            if s.startswith("#") and ("用法" in s or "python " in s or "D:" in s):
                # 文档里的示例路径，允许但要提示
                if re.search(r"[A-Za-z]:\\\\", s):
                    print("DOC  %s:%d  %s" % (os.path.relpath(f, ROOT), i, s[:90]))
                continue
            for m in PAT.finditer(l):
                hit = m.group(0)
                if any(k.lower() in l.lower() for k in SKIP_LINES):
                    continue
                print("PATH %s:%d  %s" % (os.path.relpath(f, ROOT), i, s[:100]))
                bad += 1
                break
    # 项目私有关键词
    for f in sorted(glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True) +
                    glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True) +
                    glob.glob(os.path.join(ROOT, "**", "*.yaml"), recursive=True) +
                    glob.glob(os.path.join(ROOT, "**", "*.yml"), recursive=True) +
                    glob.glob(os.path.join(ROOT, "**", "*.json"), recursive=True) +
                    glob.glob(os.path.join(ROOT, "**", "*.html"), recursive=True)):
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        if _skip(rel):
            continue
        try:
            txt = open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for k in BANNED:
            if k in txt:
                for i, l in enumerate(txt.splitlines(), 1):
                    if k in l:
                        print("PRIV %s:%d  %s" % (rel, i, l.strip()[:90]))
                        bad += 1
                        break
    # 通用绝对路径扫描（非 .py 也要扫：yaml / md / json / html 一样会泄露本机路径）
    for f in sorted(glob.glob(os.path.join(ROOT, "**", "*.yaml"), recursive=True) +
                    glob.glob(os.path.join(ROOT, "**", "*.yml"), recursive=True) +
                    glob.glob(os.path.join(ROOT, "**", "*.json"), recursive=True) +
                    glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True) +
                    glob.glob(os.path.join(ROOT, "**", "*.html"), recursive=True)):
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        if _skip(rel):
            continue
        try:
            txt = open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for i, l in enumerate(txt.splitlines(), 1):
            if any(k.lower() in l.lower() for k in SKIP_LINES):
                continue
            m = PAT.search(l)
            if m:
                print("PATH %s:%d  %s" % (rel, i, l.strip()[:100]))
                bad += 1
    print("\n== 残留问题 %d 处 ==" % bad)
    return bad


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
