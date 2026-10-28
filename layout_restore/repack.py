# -*- coding: utf-8 -*-
r"""只重建源件包（不重新寻优）：用标定后的 spec 重新生成 HTML / 素材 / 规格说明。

用途
    引擎改了（字体注册表、@font-face 生成规则等）之后，
    不需要把寻优重跑一遍 —— 寻优结果是确定性的，直接用 *_calibrated.json 重打包即可。

用法
    python repack.py            # 打包 R1~R6
    python repack.py R3 R5      # 只打包指定几张
"""
import os
import sys
import json
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rebuild as RB                                            # noqa: E402

ROOT = RB.ROOT
SPECS = os.path.join(HERE, "specs")

ORDER = [
    ("R1", "R1_Midea小煮锅", None),                              # 早期格式，单独处理
    ("R2", "R2_LED灯带RA98", None),
    ("R3", "R3_煎炒蒸煮涮", None),
    ("R4", "R4_BeyondRarity_黑金高端", None),
    ("R5", "R5_LAVictoria_杂志风网站", None),
    ("R6", "R6_PURESPRING_黑金高端", None),
]

# R1 是第一轮用 r1_extract.py 做的，spec 格式没有 src/crop，这里补上
R1_SRC = os.path.join(ROOT, r"02_参考与拆解\版式工程\refs\R1_Midea小煮锅_促销主图.png")
R1_CROP = [78, 0, 0, 0]


def load_spec(key):
    cal = os.path.join(SPECS, "%s_calibrated.json" % key)
    base = os.path.join(SPECS, "%s.json" % key)
    if os.path.exists(cal):
        return json.load(open(cal, encoding="utf-8-sig"))
    if os.path.exists(base):
        return json.load(open(base, encoding="utf-8-sig"))
    if key == "R1":
        p = os.path.join(HERE, "r1_rebuild", "_spec.json")
        if os.path.exists(p):
            s = json.load(open(p, encoding="utf-8-sig"))
            s["key"] = "R1_Midea小煮锅"
            s["name"] = "R1_Midea小煮锅_促销主图"
            s["src"] = R1_SRC
            s["crop"] = R1_CROP
            return s
    return None


def main(keys):
    for key, folder, _ in ORDER:
        if keys and key not in keys:
            continue
        spec = load_spec(key)
        if spec is None:
            print("skip", key, "(no spec)")
            continue
        outdir = os.path.join(HERE, "%s_rebuild" % key.lower())
        if not os.path.exists(os.path.join(outdir, "assets")):
            print("skip", key, "(no rebuild dir)")
            continue
        rb = RB.Rebuild(spec, outdir)
        rb.make_plate()
        rb.cut_art()
        used = rb._used_families()
        keep = set()
        for f, fam, wght, style, fmt in RB.FONTS:
            if fam in used:
                keep.add(f)
                s = os.path.join(RB.FONT_HERE, f)
                if os.path.exists(s) and os.path.getsize(s) > 1024:
                    shutil.copy(s, os.path.join(outdir, "assets", f))
        # 清掉中间目录里没被用到的字体（否则会被一起拷进源件包，白占几十 MB）
        adir = os.path.join(outdir, "assets")
        for f in os.listdir(adir):
            if f.lower().endswith((".ttf", ".otf")) and f not in keep:
                try:
                    os.remove(os.path.join(adir, f))
                except Exception:
                    pass
        html = rb.build_html(px=False)
        open(os.path.join(outdir, "index.html"), "w", encoding="utf-8").write(html)
        if any(t.get("px") for t in spec["text"]):
            px = rb.make_px()
            open(os.path.join(outdir, "index_px.html"), "w", encoding="utf-8").write(px)
        json.dump(spec, open(os.path.join(outdir, "_spec.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        # 交付目录
        DEST = os.path.join(ROOT, r"05_成品与源文件\主图", spec["key"] + "_像素级还原")
        ADEST = os.path.join(ROOT, r"05_成品与源文件\源文件_PSD_AI", spec["key"] + "_像素级还原")
        os.makedirs(ADEST, exist_ok=True)
        # 先清掉交付包里用不到的字体（上一版留下的）
        for f in os.listdir(os.path.join(ADEST, "assets")):
            if f.lower().endswith((".ttf", ".otf")) and f not in keep:
                try:
                    os.remove(os.path.join(ADEST, "assets", f))
                except Exception:
                    pass
        for f in os.listdir(os.path.join(outdir, "assets")):
            shutil.copy(os.path.join(outdir, "assets", f), os.path.join(ADEST, "assets", f))
        for f in ("index.html", "index_px.html", "_spec.json"):
            p = os.path.join(outdir, f)
            if os.path.exists(p):
                shutil.copy(p, os.path.join(ADEST, f))
        RB.write_spec_doc(spec, rb, os.path.join(ADEST, "还原规格说明.md"))
        print("repacked", key, "->", ADEST)


if __name__ == "__main__":
    main(set(sys.argv[1:]))
