# -*- coding: utf-8 -*-
"""发布前自检：绝对路径 / 私有词 / 联系方式 / **商业字体** / 字体授权。

★ 为什么这个脚本自己不能带私有词（2026-11-09 改）
  原来 BANNED 里硬编码了具体的人名、QQ 号、第三方商品名。
  脚本会跳过自己 ⇒ 扫描报「0 残留」，**但这些字符串本身就在公开仓库里可见**，
  等于自检把要找的东西自己写出来了。
  ⇒ 改成：私有词从**不入库的本地文件**读（默认空），
    仓库里只保留**结构性**规则（绝对路径 / 手机号 / 商业字体 / 字体授权），
    这些规则不依赖任何具体私有值，陌生人 clone 下来也能用。

★ 阴性对照（自检本身也会骗人）
  2026-10-30 实测：原来 BANNED 只匹配反斜杠形式，而 yaml 里全是正斜杠
  ⇒ 一条都没匹配上 ⇒ 报「0 残留」，实际有 7 条绝对路径躺在 config.yaml 里。
  ⇒ 没有阴性对照的「0 残留」不可信。
"""
import os
import re
import sys
import glob
import struct

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAT = re.compile(r"[A-Za-z]:[\\/]{1,2}(?![\\/])[^\s\"'<>|]*")
SKIP_LINES = ("http://", "https://", "xmlns", "file:///", "svg", "viewBox")

# 私有词表：**不入库**，由使用者自建（tests/.private_words.local.txt，一行一个词）
PRIVATE_WORDS_FILE = os.path.join(ROOT, "tests", ".private_words.local.txt")

# 结构性规则：与具体私有值无关，陌生人也能用
STRUCT_PATTERNS = [
    ("MOBILE", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),      # 大陆手机号
    ("IDCARD", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),     # 身份证号
    ("PRIVATE_IP", re.compile(r"\b(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)\b")),
]

# 运行产物目录（.gitignore 已排除，不入库 → 不算发布残留）
IGNORED_DIRS = ("out", "specs", ".work", "runs", ".git", "__pycache__",
                "node_modules", ".venv", "venv", "build", "dist", ".demo_work")

TEXT_EXT = (".py", ".md", ".yaml", ".yml", ".json", ".html", ".txt", ".toml", ".cfg")


def _skip(rel):
    """入库相关才查；运行产物目录跳过"""
    return any(seg in IGNORED_DIRS for seg in rel.split("/"))


def load_private_words():
    if not os.path.isfile(PRIVATE_WORDS_FILE):
        return []
    out = []
    try:
        for line in open(PRIVATE_WORDS_FILE, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    except Exception:
        pass
    return out


def _selftest():
    """阴性对照：确认本脚本**能**抓到已知违规"""
    probe = 'x = "D:/云端全存档/私有路径/y"'
    hit_kw = PAT.search(probe) is not None
    probe2 = 'phone = "13800138000"'
    hit_struct = STRUCT_PATTERNS[0][1].search(probe2) is not None
    ok = hit_kw and hit_struct
    print("阴性对照 %s  绝对路径命中=%s 手机号命中=%s"
          % ("[OK]" if ok else "[!!] 自检本身失灵", hit_kw, hit_struct))
    return 0 if ok else 1


# ---------------------------------------------------------------- 字体检查
def _name_table(path):
    """解析 TrueType name table，返回 {nameID: text}"""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) < 12:
            return {}
        num = struct.unpack(">H", data[4:6])[0]
        off = None
        for i in range(num):
            rec = 12 + i * 16
            if data[rec:rec + 4] == b"name":
                off = struct.unpack(">I", data[rec + 8:rec + 12])[0]
                break
        if off is None:
            return {}
        count, strOff = struct.unpack(">HH", data[off + 2:off + 6])
        out = {}
        for i in range(count):
            rec = off + 6 + i * 12
            pid, eid, lid, nid, ln, o = struct.unpack(">HHHHHH", data[rec:rec + 12])
            raw = data[off + strOff + o: off + strOff + o + ln]
            try:
                s = raw.decode("utf-16-be") if pid == 3 else raw.decode("latin-1")
            except Exception:
                continue
            if nid not in out:
                out[nid] = s.replace("\r", " ").replace("\n", " ")
        return out
    except Exception:
        return {}


COMMERCIAL_HINTS = ("Monotype", "Monotype Typography", "Typeface ©", "All Rights Reserved",
                     "Adobe Type", "licensed under the terms of a license agreement")


def _ofl_covers(base, ofls):
    """字体文件名 -> 是否有对应的 OFL-*.txt 覆盖
    NotoSansSC-VF.ttf  -> OFL-NotoSansSC.txt
    PlayfairDisplay-Italic.ttf -> OFL-PlayfairDisplay.txt
    """
    stem = base
    for suf in ("-VF-Italic", "-Italic", "-VF", "Italic"):
        if stem.endswith(suf):
            stem = stem[: -len(suf)]
    key = stem.lower()
    return any(key in o.lower() for o in ofls)


def check_fonts():
    """商业字体不得入库 + 每个字体必须有 OFL 许可全文"""
    bad = 0
    adir = os.path.join(ROOT, "layout_restore", "assets")
    if not os.path.isdir(adir):
        return 0
    fonts = sorted(glob.glob(os.path.join(adir, "*.ttf")) + glob.glob(os.path.join(adir, "*.otf")))
    ofls = {os.path.basename(p).upper() for p in glob.glob(os.path.join(adir, "OFL-*.txt"))}
    for p in fonts:
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        nt = _name_table(p)
        cr = nt.get(0, "")
        lic = nt.get(13, "")
        is_ofl = "Open Font License" in lic
        if not is_ofl:
            commercial = any(h in cr for h in COMMERCIAL_HINTS) or \
                        "NOTIFICATION OF LICENSE" in lic.upper()
            print("FONT %s  商业字体/无开源授权，禁止入库（copyright=%s）"
                  % (rel, cr[:70]))
            bad += 1
            continue
        base = os.path.splitext(os.path.basename(p))[0]
        if not _ofl_covers(base, ofls):
            print("FONT %s  缺少随附的 OFL 许可全文（OFL 要求）" % rel)
            bad += 1
    print("字体检查: %d 个字体，问题 %d 处" % (len(fonts), bad))
    return bad


def main():
    bad = _selftest()
    words = load_private_words()
    print("私有词表: %s（%d 个词，来自 %s）"
          % ("已加载" if words else "空（未建本地词表）", len(words),
             os.path.relpath(PRIVATE_WORDS_FILE, ROOT)))

    # 1) 绝对路径 + 结构性模式（所有文本类文件）
    for f in sorted(glob.glob(os.path.join(ROOT, "**", "*.*"), recursive=True)):
        if not f.lower().endswith(TEXT_EXT):
            continue
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        if _skip(rel):
            continue
        if rel == os.path.relpath(os.path.abspath(__file__), ROOT).replace("\\", "/"):
            continue  # 本脚本自身：阴性对照的探针字符串会命中规则，必须跳过
        try:
            lines = open(f, encoding="utf-8", errors="replace").read().splitlines()
        except Exception:
            continue
        for i, l in enumerate(lines, 1):
            s = l.strip()
            if any(k.lower() in l.lower() for k in SKIP_LINES):
                continue
            if s.startswith("#") and ("用法" in s or "python " in s or "D:" in s):
                if re.search(r"[A-Za-z]:\\\\", s):
                    print("DOC  %s:%d  %s" % (rel, i, s[:90]))
                continue
            m = PAT.search(l)
            if m:
                print("PATH %s:%d  %s" % (rel, i, s[:100]))
                bad += 1
            for name, rx in STRUCT_PATTERNS:
                if rx.search(l):
                    print("%s %s:%d  %s" % (name, rel, i, s[:100]))
                    bad += 1

    # 2) 私有词（来自不入库的本地词表）
    if words:
        for f in sorted(glob.glob(os.path.join(ROOT, "**", "*.*"), recursive=True)):
            if not f.lower().endswith(TEXT_EXT):
                continue
            rel = os.path.relpath(f, ROOT).replace("\\", "/")
            if _skip(rel) or rel.endswith(".private_words.local.txt"):
                continue
            try:
                txt = open(f, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            for k in words:
                if k in txt:
                    print("PRIV %s  含私有词（值由本地词表提供）" % rel)
                    bad += 1
                    break

    # 3) 字体授权
    bad += check_fonts()

    print("\n== 残留问题 %d 处 ==" % bad)
    return bad


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
