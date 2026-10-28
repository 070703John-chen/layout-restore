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
BANNED = ("D:\\云端全存档", "D:\\电商素材", "C:\\Users", "AL-LED",
          "小熊电煮锅", "小熊", "陈明令", "2913454968")
# 自检脚本自己含这些字样，跳过
SELF_SKIP = {"tests/check_no_private_paths.py"}


def main():
    bad = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        if rel in SELF_SKIP or "__pycache__" in f:
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
                    glob.glob(os.path.join(ROOT, "**", "*.yaml"), recursive=True)):
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        if rel in SELF_SKIP or "__pycache__" in f:
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
    print("\n== 残留问题 %d 处 ==" % bad)


if __name__ == "__main__":
    main()
