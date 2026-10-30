# -*- coding: utf-8 -*-
r"""从探针结果自动生成 spec.json **草稿**（人工审一遍就能跑）。

为什么要有这个
    批量化的真正瓶颈不是"渲染慢"，而是**每张图都要人肉量坐标、色值、字号**。
    这一步占了整轮工作量的八成。
    探针已经把坐标/内容/候选色/候选字号都算出来了，
    这里把探针结果直接翻译成 spec 草稿，人只做「审」不做「量」。

用法
    python autospec.py --probe refs\\_probe_R2.json --key R2 \
        --src refs\\R2_LED灯带RA98_促销主图.png --crop 17,8,19,24 \
        --out specs\\R2.json
"""
import os
import sys
import json
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def guess_weight(txt, h):
    """粗判字重：中文默认 700，纯拉丁大写偏 900。"""
    if not txt:
        return 700
    cjk = sum(1 for c in txt if ord(c) > 0x2E80)
    if cjk >= len(txt) * 0.5:
        return 900 if h > 30 else 700
    return 700 if h < 20 else 900


def guess_font(txt, h, cjk_font=None, latin_font=None):
    """粗判字体。

    注意：这个启发式是**海报**场景来的（大字中文 -> 宋体）。
    电商图直接套会错得离谱：淘宝促销大字是**黑体**，
    套成宋体后重建出来是「细瘦宋体」，差异率能飙到 20%。
    字体是**族级配方属性**，必须能由调用方指定。
    """
    cjk = sum(1 for c in txt if ord(c) > 0x2E80)
    if cjk >= len(txt) * 0.5:
        if cjk_font:
            return cjk_font
        return "Noto Serif SC" if h > 30 else "Noto Sans SC"
    if latin_font:
        return latin_font
    return "Century Gothic" if h > 30 else "Noto Sans SC"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--src", required=True)
    ap.add_argument("--crop", default="0,0,0,0")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-conf", type=float, default=0.6)
    ap.add_argument("--cal-weight", action="store_true",
                    help="把字重加入自动寻优（电商图正文常是常规字重，猜不准）")
    ap.add_argument("--cal-fill", action="store_true",
                    help="把字色加入自动寻优（探针取色可能落在抗锯齿中间色）")
    ap.add_argument("--cjk-font", default=None,
                    help="force CJK font (family-level recipe attribute); e-commerce promo type = Noto Sans SC")
    ap.add_argument("--latin-font", default=None, help="force latin font")
    ap.add_argument("--mask-mode", default=None, choices=[None, "nonbg"],
                    help="nonbg = 框内非背景像素全挖（含描边）；电商图大字必需")
    a = ap.parse_args()

    rep = json.load(open(a.probe, encoding="utf-8"))
    crop = [int(v) for v in a.crop.split(",")]

    texts, art, warns = [], [], []
    used = {}
    for row in rep["rows"]:
        if row["src"] != "ocr" or row["conf"] < a.min_conf:
            continue
        txt = (row.get("text") or "").strip()
        if not txt:
            continue
        # 同一文案出现多次 -> 逐个编号，sweep 用 occ 区分
        n = used.get(txt, 0)
        used[txt] = n + 1
        box = row["box"]
        h = box[3] - box[1]
        size = int(round(row.get("size_guess") or h))
        fill = row.get("fill") or "#FFFFFF"
        bg = row.get("bg") or "#000000"
        el = {
            "id": "t%02d" % len(texts),
            "text": txt,
            "box": box,
            "base": box[3],
            "size": size,
            "weight": guess_weight(txt, h),
            "fill": fill,
            "font": guess_font(txt, h, a.cjk_font, a.latin_font),
            "tol": 45,
            "alts": row.get("alts") or [],
            "bg": row.get("bg") or "#FFFFFF",
            "mask_mode": a.mask_mode,
        }
        if row.get("cross_bg"):
            # 文字横跨两种底色（压在色块/蒙版边界上）——
            # 字色由探针用「局部底色」采样，别再用单一全局底色判。
            el["cross_bg"] = True
            el["split_x"] = row.get("split_x")
            warns.append("#%s %r 跨底色（边界列 x=%s）→ 字色走局部底色采样，"
                         "字重/字色寻优改用像素差（全局底色的墨量判据在此不可靠）"
                         % (el["id"], txt[:12], row.get("split_x")))
        if row.get("stroke"):
            el["stroke"] = row["stroke"]
            el["stroke_w"] = row.get("stroke_w") or 2
        # 色值可疑：字色和底色太接近（可能取反了），或者字色接近纯黑但底色亮
        try:
            f = int(fill[1:3], 16), int(fill[3:5], 16), int(fill[5:7], 16)
            b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
            dfb = max(abs(x - y) for x, y in zip(f, b))
            if dfb < 60:
                warns.append("#%s %r 字色(%s)与底色(%s)太接近，可能取反了" %
                             (el["id"], txt[:12], fill, bg))
        except Exception:
            pass
        texts.append(el)

    # 美术素材候选：高饱和色块，且不与任何文字框重叠
    for i, b in enumerate(rep.get("blocks", [])):
        bx = [b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]]
        hit = False
        for t in texts:
            tx0, ty0, tx1, ty1 = t["box"]
            if bx[0] < tx1 and bx[2] > tx0 and bx[1] < ty1 and bx[3] > ty0:
                hit = True
                break
        if hit:
            continue
        if b["area"] < 2500:
            continue
        art.append(["blk%02d" % i, bx])

    # 自动生成 sweep：字号 / 基线 / x 各 3 档
    sweep = []
    for t in texts:
        x0, y0, x1, y1 = t["box"]
        w, h = x1 - x0, y1 - y0
        reg = [max(0, x0 - 6), max(0, y0 - 6), min(rep["canvas"][0], x1 + 6),
               min(rep["canvas"][1], y1 + 6)]
        s = t["size"]
        marker = t["text"]
        sweep.append({"marker": marker, "attr": "font-size",
                      "values": sorted(set([max(6, s - 3), s, s + 3])), "region": reg})
        sweep.append({"marker": marker, "attr": "y",
                      "values": sorted(set([y1 - 3, y1, y1 + 3])), "region": reg})
        sweep.append({"marker": marker, "attr": "x",
                      "values": sorted(set([x0 - 2, x0, x0 + 2])), "region": reg})
        # 描边宽度自动校准：描边厚度靠探针估不准（估的是总笔画宽），
        # 交给寻优按像素差挑。描边是大特征（几像素宽的连续轮廓），
        # 像素差在这里比在细字上可靠。
        if t.get("stroke"):
            cwid = t.get("stroke_w") or 2
            # ⚠ 候选集必须覆盖真值的 2 倍以上：
            #   原图描边**单侧**就有 4~5px，SVG stroke-width 是对称的 → 要到 8~10。
            #   原来上限只有 6 → 大描边永远校不准（天花板卡死）。
            sweep.append({"marker": marker, "attr": "stroke-width",
                          "values": sorted(set([1, 2, 3, 4, 5, 6, 8, 10, 12, cwid])),
                          "region": reg, "score": "strokearea"})
        # 字重自动校准：电商图正文大多是常规字重，猜的 700/900 常偏粗。
        # 交给寻优按像素差异挑最接近的，而不是人肉改。
        if a.cal_weight:
            cw = t.get("weight") or 700
            # 评分用「墨量」不用像素差：字形差 1px 时笔画不重合，
            # 像素差分不出颜色和字重（实测灰@300 赢过 黑@400）。
            # 墨量 = 笔画覆盖面积，直接对应字重，且不怕 1px 错位。
            # 有描边的字：填充色面积和描边色面积要分开数，
            # 否则「细填充+粗描边」和「粗填充+细描边」的墨量相等 → 判不出来。
            # ⚠ 跨底色的字不能用量判据：墨量 = 「离**全局**底色远的像素数」，
            #   而另一种底色整片都远 → 墨量被底色灌水，字重判不出来。
            #   跨底色改用像素差（底色在各候选里都一样，差异只来自笔画）。
            if t.get("cross_bg"):
                sweep.append({"marker": marker, "attr": "font-weight",
                              "values": sorted(set([300, 400, 500, 700, 900, cw])),
                              "region": reg})
            else:
                wscore = "fillarea" if t.get("stroke") else "inkarea"
                sweep.append({"marker": marker, "attr": "font-weight",
                              "values": sorted(set([300, 400, 500, 700, 900, cw])),
                              "region": reg, "score": wscore})
        # 字色自动校准：小字抗锯齿后探针可能取到中间灰，
        # 把探针给的备选色一起交给寻优挑。
        if a.cal_fill:
            cands = [t["fill"]] + [c for c in (t.get("alts") or []) if c != t["fill"]]
            if len(set(cands)) > 1:
                # 评分用「墨色」：候选笔画核心的中位色 vs 原图笔画核心的中位色
                # ⚠ 跨底色的字改用像素差：「墨色」判据同样依赖全局底色。
                if t.get("cross_bg"):
                    sweep.append({"marker": marker, "attr": "fill",
                                  "values": list(dict.fromkeys(cands)), "region": reg})
                else:
                    sweep.append({"marker": marker, "attr": "fill",
                                  "values": list(dict.fromkeys(cands)), "region": reg,
                                  "score": "inkcolor"})

    spec = {
        "key": a.key,
        "name": a.name or a.key,
        "src": a.src,
        "crop": crop,
        "text": texts,
        "art": art,
        "sweep": sweep,
        "_review": warns,
    }
    # ⚠ dirname 可能是空串（--out spec.json 相对路径）→ makedirs('') 直接崩
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(spec, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("草稿已写：%s" % a.out)
    print("  文字元素 %d 个 / 美术素材候选 %d 个 / sweep %d 条" %
          (len(texts), len(art), len(sweep)))
    print("  表面积 %dx%d，裁切 %s" % (rep["canvas"][0], rep["canvas"][1], crop))
    if warns:
        print("\n  [!] 需要人工确认：")
        for w in warns:
            print("    " + w)
    print("\n  人工确认清单：")
    print("    1) 文字框有没有把素材误判成文字（反之亦然）")
    print("    2) 字色是否取反（看上面 [!] 列表）")
    print("    3) 美术素材框是否需要手动收紧")
    print("    4) 哪些元素该做像素层（px=true）—— 通常是最大的主视觉")
    print("    5) 美术素材层要人工补：探针的色块检测和文字框重叠时会漏（通常只有几项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
