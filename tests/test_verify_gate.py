# -*- coding: utf-8 -*-
"""验收闸门自测：证明 `verify` **抓得住**被破坏的交付件。

为什么必须有这个测试
    2026-10-30 实测：交付包里没有 `_report.json` → verify 取不到基准 →
    **不比对** → 交付包被改坏（字号+17px、注入色块、删文件）也照样打印
    「全部一致 [OK]」、exit 0。表面验收 100% 通过，实际什么都没验。
    ⇒ 「验收通过」这件事本身必须被验证过。

用法
    python tests/test_verify_gate.py [pack_dir]
    pack_dir 默认 out/demo_param_card/deliver/demo_param_card_源件包

退出码
    0 = 闸门有效（正常包判过，坏包判不过）
    1 = 闸门失效（必须修引擎）
"""
import os
import re
import sys
import shutil
import subprocess
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PACK = os.path.join(ROOT, "out", "demo_param_card", "deliver",
                            "demo_param_card_源件包")


def verify(pack):
    p = subprocess.run([sys.executable, "-m", "layout_restore.verify", "--pack", pack],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out


def copy_pack(pack, tag):
    d = os.path.join(tempfile.gettempdir(), "lr_gate_%s" % tag)
    if os.path.isdir(d):
        shutil.rmtree(d)
    shutil.copytree(pack, d)
    return d


def main():
    pack = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PACK
    if not os.path.isdir(pack):
        print("找不到交付包：%s" % pack)
        print("先跑：python -m layout_restore.cli build "
              "--src examples/samples/demo_param_card.png --key demo_param_card")
        return 2

    ip = os.path.join(pack, "index.html")
    h = open(ip, encoding="utf-8", errors="replace").read()
    fails = []

    # ---- 0. 产物是**旧的**（修引擎之前 build 的）→ 跳过，不算闸门失效 ----
    #     旧产物没有 _report.json、没有 px 素材 —— 那是历史遗留，不是引擎坏了。
    if not os.path.exists(os.path.join(pack, "_report.json")):
        print("!! 交付包是**旧产物**（缺 _report.json）—— 先重新 build：")
        print("   python -m layout_restore.cli build "
              "--src examples/samples/demo_param_card.png --key demo_param_card")
        return 2

    # ---- 1. 正常包必须判过 ----
    rc, out = verify(pack)
    print("[0] 正常包 verify rc=%d （期望 0）" % rc)
    if rc != 0:
        fails.append("正常包被判 FAIL")
        print(out[-1500:])

    # ---- 2. 注入色块 ----
    d = copy_pack(pack, "block")
    p = os.path.join(d, "index.html")
    hh = h.replace("</body>",
                   '<div style="position:absolute;left:10px;top:10px;width:180px;'
                   'height:180px;background:#ff0000;z-index:9999"></div></body>')
    if hh == h:
        hh = h + ('<div style="position:absolute;left:10px;top:10px;width:180px;'
                  'height:180px;background:#ff0000"></div>')
    open(p, "w", encoding="utf-8").write(hh)
    rc, out = verify(d)
    print("[1] 注入色块 verify rc=%d （期望 != 0）" % rc)
    if rc == 0:
        fails.append("注入色块没被抓到")

    # ---- 2. 改一个填充色 ----
    d = copy_pack(pack, "fill")
    p = os.path.join(d, "index.html")
    hh = re.sub(r'fill="#[0-9A-Fa-f]{3,8}"', 'fill="#ff00ff"', h, count=1)
    open(p, "w", encoding="utf-8").write(hh)
    rc, out = verify(d)
    print("[2] 改填充色 verify rc=%d （期望 != 0）" % rc)
    if rc == 0:
        fails.append("改填充色没被抓到")

    # ---- 3. 删 index_px.html ----
    d = copy_pack(pack, "nopx")
    fp = os.path.join(d, "index_px.html")
    if os.path.exists(fp):
        os.remove(fp)
    rc, out = verify(d)
    print("[3] 删 index_px.html verify rc=%d （期望 != 0）" % rc)
    if rc == 0:
        fails.append("缺 index_px.html 没被抓到")

    # ---- 4. 删 _report.json（无基准 = 没验）----
    d = copy_pack(pack, "noreport")
    fp = os.path.join(d, "_report.json")
    if os.path.exists(fp):
        os.remove(fp)
    rc, out = verify(d)
    print("[4] 删 _report.json verify rc=%d （期望 != 0）" % rc)
    if rc == 0:
        fails.append("无基准没被抓到")

    # ---- 5. 像素层必须真的有素材（原来恒空转）----
    adir = os.path.join(pack, "assets")
    px = [f for f in os.listdir(adir) if f.startswith("px_")] if os.path.isdir(adir) else []
    print("[5] 交付包 px_*.png = %d 张" % len(px))
    if not px:
        print("    （该样例无降级文字时为 0，属正常；有降级时必须 > 0）")

    print()
    if fails:
        print("闸门失效：%s" % "；".join(fails))
        return 1
    print("验收闸门有效 [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
