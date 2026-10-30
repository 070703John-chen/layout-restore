# -*- coding: utf-8 -*-
r"""版式工程 · 批量重建驱动（R2~R6 用）

一条命令跑完：挖字 -> 裁素材 -> 生成 HTML -> 渲染 -> 差异统计 -> 墨迹校准 -> 参数寻优
             -> 双版本（活字版/像素层版）1x/2x -> 对比图 + 热力图 -> 源件包 + 规格说明

用法
    python rebuild.py --spec specs/R2.json [--no-sweep] [--no-deliver]

spec.json
{
  "key":  "R2",
  "name": "R2_LED灯带RA98",
  "src":  "refs/demo.jpg",
  "crop": [17, 8, 19, 24],                  # 上,下,左,右
  "text": [
    {"id":"led", "text":"LED", "box":[18,68,146,134],
     "base":134, "size":89, "weight":900, "fill":"#AD0E19",
     "stroke":"#...", "stroke_w":2.0, "font":"Century Gothic",
     "tol":78,          # 挖字判据容差（与 fill 色的最大通道差）
     "px":true}         # true = 像素层版里换成原图裁切块
  ],
  "art": [["badge", [280,5,450,32]]],
  "rects": [                                  # 矢量色块（背景结构）。可选，缺省不影响
    {"id":"bar","box":[24,30,742,115],"fill":"#1E1B2F","rx":0,"opacity":1.0},
    {"id":"chip","box":[100,200,300,240],"fill":"#0075C2","rx":6}
  ],
  "lines": [                                  # 矢量线条（表格线/尺寸标注线，前景结构）。可选
    {"id":"v","x1":100,"y1":280,"x2":100,"y2":345,"stroke":"#666666","w":1},
    {"id":"h","x1":120,"y1":460,"x2":640,"y2":460,"stroke":"#666666","w":1,"dash":"4 3"}
  ],
  "sweep": [
    {"marker":"LED", "attr":"font-size", "values":[60,70,80], "region":[10,60,215,140]},
    {"marker":"LED", "attr":"y",          "values":[125,134,143], "region":[10,60,215,140]}
  ]
}
"""
import os
import re
import sys
import json
import shutil

# 探针/寻优日志里有大量中文与 ® 这类符号，
# Windows 控制台默认 GBK → print 时 UnicodeEncodeError 直接把整轮跑挂掉。
# 这里强制 stdout 用 UTF-8（不改文件内容，只改控制台编码）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse

import numpy as np
import cv2
from PIL import Image
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
# 字体目录：优先「包内 assets」，其次环境变量 LAYOUT_RESTORE_FONTS 指定的目录。
# （原来这里写死了一个本机绝对路径，公开仓库里必须去掉。）
FONT_HERE = os.path.join(HERE, "assets")
FONT_SRC = os.environ.get("LAYOUT_RESTORE_FONTS", "") or FONT_HERE
ROOT = os.environ.get("LAYOUT_RESTORE_ROOT", "")

# 字体注册表：文件名 -> (CSS family, weight range, style)
# 商业字体本机无授权源，只能用可替代的公开字体：
#   Bodoni MT Bold/Book  —— 系统自带 Didone，对应 R4 的高对比衬线
#   Playfair Display      —— 开源 Didone，对应 R5 的杂志风标题
#   Noto Serif SC         —— 开源中文宋体，对应 R6 的「奢享纯净」
FONTS = [
    ("NotoSansSC-VF.ttf", "Noto Sans SC", "100 900", "normal", "truetype"),
    ("GOTHIC.TTF", "Century Gothic", "400 900", "normal", "truetype"),
    ("PlayfairDisplay.ttf", "Playfair Display", "100 900", "normal", "truetype"),
    ("PlayfairDisplay-Italic.ttf", "Playfair Display", "100 900", "italic", "truetype"),
    ("NotoSerifSC.ttf", "Noto Serif SC", "100 900", "normal", "truetype"),
]
FONT_FAMILY_ALIAS = {
    "Bodoni Bd BT": "Bodoni Bd BT",
    "Bodoni Bk BT": "Bodoni Bk BT",
    "Microsoft YaHei": "Microsoft YaHei",
    "Microsoft YaHei Light": "Microsoft YaHei Light",
    "STSong, SimSun, serif": "STSong",
    "SimSun, STSong, serif": "SimSun",
}


def font_face_css(used=None):
    """生成 @font-face 规则。used = 本图实际用到的 family 集合（None = 全给）。"""
    out = []
    for fn, fam, wght, style, fmt in FONTS:
        if used is not None and fam not in used:
            continue
        out.append('@font-face{font-family:"%s";src:url("assets/%s") format("%s");'
                   'font-weight:%s;font-style:%s;font-display:block}'
                   % (fam, fn, fmt, wght, style))
    return "\n".join(out)


# ================================================================== 小工具
def hex2rgb(h):
    """'#RRGGBB' -> RGB 数组 [R, G, B]。

    踩坑记录：这块先后错过两次。
      1) 01_decompose.py 传下来的版本返回 [G, R, B] —— 顺序错。
      2) 修正时又写成 [B, G, R] —— 还是错。
    真相是：**本模块里的图像数组一律是 RGB**（PIL 读进来的），不是 BGR；
    而 cv2 那条线（probe_layers.py / cc_color.py）才是 BGR。
    灰白色 (#FFFFFF/#111111) 三通道相同，错了也看不出来，
    一遇到红色系（#AD0E19）就整片挖不出来 —— R2 首次跑 3.86% 就是这个原因。
    """
    return np.array([int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)], np.int16)


def rgb2hex(rgb):
    return "#%02X%02X%02X" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def load_crop(src, crop):
    raw = np.asarray(Image.open(src).convert("RGB")).astype(np.uint8)
    t, b, l, r = crop
    H0, W0 = raw.shape[:2]
    A = raw[t:H0 - b if b else H0, l:W0 - r if r else W0]
    return A, W0, H0


def _esc_marker(marker):
    """sweep marker（原文）-> HTML 里出现的形式（& 转义一次）。

    marker 统一存**原文**；build_html 写进 HTML 时把 & 转成 &，
    所以匹配前只需转义一次。以前 autospec 存的是已转义版、
    rebuild._extract_text_el 又转一次 → &amp; 永远匹配不上。
    """
    return (marker or "").replace("&", "&amp;")


# ================================================================== 引擎
class Rebuild:
    def __init__(self, spec, outdir):
        self.spec = spec
        self.key = spec["key"]
        self.out = outdir
        os.makedirs(os.path.join(outdir, "assets"), exist_ok=True)
        self.A, self.W0, self.H0 = load_crop(spec["src"], spec.get("crop", [0, 0, 0, 0]))
        self.H, self.W = self.A.shape[:2]
        self.O = self.A.astype(int)

    # ---------------------------------------------------------- 照片层
    def make_plate(self):
        """原图挖掉要重建的文字。

        掩膜判据 = 文字自身 fill 色（不用众数色，否则会把胶囊底/横幅底一起挖成白块）。

        背景回填走**两条路，用留出法自动选优**：
          inpaint —— 适合纯色面板上的小字（周围均匀，直接补色）
          多项式 —— 适合大号字压在渐变/纹理背景上（inpaint 会把背景拖糊）

        选优判据（留出法 / leave-out）：
          在元素附近随机挑一批**已知是背景**的像素，假装它们也被挖掉了，
          看两种算法谁能更准地把它们还原出来，谁赢就派给真正的文字区。
        （不能用「重建 vs 原图」当判据 —— 原图那格是字，不是背景，
          越像字越"准"，那是自欺欺人。R2 首次试这招时多项式就把红条填成了米色。）
        """
        A, H, W = self.A, self.H, self.W
        elem_masks = []
        for t in self.spec["text"]:
            x0, y0, x1, y1 = t["box"]
            pad = int(t.get("pad", 3))
            yy0, yy1 = max(0, y0 - pad), min(H, y1 + pad)
            xx0, xx1 = max(0, x0 - pad), min(W, x1 + pad)
            reg = A[yy0:yy1, xx0:xx1].astype(np.int16)
            f = hex2rgb(t.get("mask_color", t["fill"]))
            d = np.abs(reg - f).max(axis=2)
            if t.get("mask_mode") == "nonbg":
                # 框内**离背景最远**的那批像素 = 字 + 描边 + 阴影，全挖。
                # 背景参考：框外一圈的中位色（ring）。
                pad2 = max(4, int(0.4 * max(x1 - x0, y1 - y0)))
                ring = A[max(0, yy0 - pad2):min(H, yy1 + pad2),
                        max(0, xx0 - pad2):min(W, xx1 + pad2)].reshape(-1, 3)
                bgref = np.median(ring, axis=0).astype(np.int16) if len(ring) else None
                if bgref is not None:
                    dd = np.abs(reg - bgref).max(axis=2)
                    thr = max(38, int(0.42 * int(dd.max())))
                    mm = (dd > thr).astype(np.uint8) * 255
                else:
                    mm = (d < int(t.get("tol", 78))).astype(np.uint8) * 255
            else:
                mm = (d < int(t.get("tol", 78))).astype(np.uint8) * 255
            # 描边也要挖：文字要重画，旧描边留在底图上会和新描边叠粗
            if t.get("stroke"):
                sc = hex2rgb(t["stroke"])
                d3 = np.abs(reg - sc).max(axis=2)
                mm = np.maximum(mm, (d3 < int(t.get("tol", 78))).astype(np.uint8) * 255)
            sub = np.zeros((H, W), np.uint8)
            sub[yy0:yy1, xx0:xx1] = mm
            # 抗锯齿边缘：文字核心被挖掉了，但 1~2px 的过渡带还留着，
            # 在照片上会显示成「鬼影」（R5 的 LA VICTORIA 就是这么变成重影的）。
            # grow 越大，吃掉的边缘越多 —— 大号显示字体需要 2~3。
            grow = int(t.get("grow", 1))
            if grow > 1:
                sub = cv2.dilate(sub, np.ones((3, 3), np.uint8), iterations=grow)
            elem_masks.append(sub)
        mask = np.zeros((H, W), np.uint8)
        for sub in elem_masks:
            mask = np.maximum(mask, sub)
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

        bgr = cv2.cvtColor(A, cv2.COLOR_RGB2BGR)
        rad = int(self.spec.get("inpaint_radius", 5))
        plate_bgr = cv2.inpaint(bgr, mask, rad, cv2.INPAINT_TELEA)

        # ---- 逐元素选优 + 回填 ----
        for t, sub in zip(self.spec["text"], elem_masks):
            em = cv2.dilate(sub, np.ones((3, 3), np.uint8), iterations=1) > 0
            cv = self._leave_out(A, em, mask, t["box"])
            if cv is None:
                continue
            e_i, e_p = cv
            if e_p < e_i - 0.5:
                fill = self._poly_fill_elem(A, em, mask, t["box"])
                if fill is not None:
                    plate_bgr[em] = fill[em]
                    print("    %-12s 留出法 inpaint=%6.2f poly=%6.2f -> 多项式"
                          % (t["id"], e_i, e_p))
                    continue
            print("    %-12s 留出法 inpaint=%6.2f poly=%6.2f -> inpaint"
                  % (t["id"], e_i, e_p))

        plate = cv2.cvtColor(plate_bgr, cv2.COLOR_BGR2RGB)
        Image.fromarray(plate).save(os.path.join(self.out, "assets", "plate.png"))
        return int((mask > 0).sum())

    def _win(self, box, m=44):
        H, W = self.A.shape[:2]
        x0, y0, x1, y1 = box
        return (max(0, x0 - m), max(0, y0 - m),
                min(W, x1 + m), min(H, y1 + m))

    def _leave_out(self, A, elem_mask, all_mask, box):
        """留出法：随机挖一批已知背景像素，比较两种算法的还原能力。"""
        wx0, wy0, wx1, wy1 = self._win(box)
        win = A[wy0:wy1, wx0:wx1]
        e = elem_mask[wy0:wy1, wx0:wx1] > 0
        bg_ok = (all_mask[wy0:wy1, wx0:wx1] == 0) & (~e)
        ys, xs = np.nonzero(bg_ok)
        if len(ys) < 80:
            return None
        rng = np.random.default_rng(20261024)
        idx = rng.choice(len(ys), size=min(260, len(ys)), replace=False)
        tm = np.zeros(win.shape[:2], np.uint8)
        tm[ys[idx], xs[idx]] = 255
        # 考题要跟真实难度一致：
        # 真实要补的是**粗笔画**的洞（大字笔画十几像素宽），
        # 用单像素考 inpaint 等于送分 —— inpaint 补单点几乎不会错，
        # 但补一条 15px 宽的笔画会拖出一大片糊。
        # 所以按元素高度估笔画粗细，把考题膨胀到同厚度。
        bh = max(1, box[3] - box[1])
        k = max(2, min(14, int(bh / 20)))
        tm = cv2.dilate(tm, np.ones((3, 3), np.uint8), iterations=k)
        tm[e] = 0                     # 别把真实文字区算进考题
        if tm.sum() < 50:
            return None
        winb = cv2.cvtColor(win, cv2.COLOR_RGB2BGR)
        rec_i = cv2.cvtColor(cv2.inpaint(winb, tm, 5, cv2.INPAINT_TELEA),
                             cv2.COLOR_BGR2RGB)
        rec_p = self._poly_local(win, bg_ok & (tm == 0))
        if rec_p is None:
            return None
        t = tm > 0
        e_i = float(np.abs(rec_i[t].astype(np.int16) -
                           win[t].astype(np.int16)).max(axis=1).mean())
        e_p = float(np.abs(rec_p[t].astype(np.int16) -
                           win[t].astype(np.int16)).max(axis=1).mean())
        return e_i, e_p

    def _poly_fill_elem(self, A, elem_mask, all_mask, box):
        """在元素邻域窗口内用「非文字像素」拟合二次曲面，回填到全尺寸数组。"""
        wx0, wy0, wx1, wy1 = self._win(box)
        win = A[wy0:wy1, wx0:wx1]
        fit_ok = (all_mask[wy0:wy1, wx0:wx1] == 0) & \
                 (elem_mask[wy0:wy1, wx0:wx1] == 0)
        rec = self._poly_local(win, fit_ok)
        if rec is None:
            return None
        full = np.zeros_like(A)
        full[wy0:wy1, wx0:wx1] = rec
        return full

    def _poly_local(self, win, fit_ok, extra_mask=None):
        """在窗口内用 fit_ok 像素拟合二次曲面，返回整窗的重建结果。"""
        H, W = win.shape[:2]
        ys, xs = np.mgrid[0:H, 0:W]
        feats = [np.ones(H * W), xs.ravel().astype(np.float64),
                 ys.ravel().astype(np.float64),
                 (xs * xs).ravel().astype(np.float64),
                 (ys * ys).ravel().astype(np.float64),
                 (xs * ys).ravel().astype(np.float64)]
        F = np.stack(feats, axis=1)
        sel = fit_ok.ravel().copy()
        if extra_mask is not None:
            sel = sel & (extra_mask == 0).ravel()
        if sel.sum() < 120:
            return None
        M = None
        for _ in range(3):
            A_mat = F[sel]
            models = []
            for ch in range(3):
                b = win[:, :, ch].ravel()[sel]
                coef, *_ = np.linalg.lstsq(A_mat, b, rcond=None)
                models.append(F @ coef)
            M = np.stack(models, axis=1)
            res = np.abs(M - win.reshape(-1, 3)).max(axis=1)
            thr = max(10.0, float(np.median(res[sel])) * 2.5 + 10)
            new = sel & (res < thr)
            if new.sum() == sel.sum() or new.sum() < 120:
                break
            sel = new
        out = win.copy()
        for ch in range(3):
            out[:, :, ch] = np.clip(M[:, ch].reshape(H, W), 0, 255).astype(np.uint8)
        return out

    # ---------------------------------------------------------- 美术素材
    def cut_art(self):
        for name, box in self.spec.get("art", []):
            x0, y0, x1, y1 = [int(v) for v in box]
            Image.fromarray(self.A[y0:y1, x0:x1]).save(
                os.path.join(self.out, "assets", name + ".png"))

    # ---------------------------------------------------------- HTML
    def _used_families(self):
        """本图实际用到的字体 family（用于只生成/只拷贝需要的 @font-face）。"""
        used = {"Noto Sans SC"}      # 默认回退字体，常驻
        for t in self.spec.get("text", []):
            f = t.get("font")
            if not f:
                continue
            for part in f.split(","):
                part = part.strip().strip('"')
                if part and part not in ("serif", "sans-serif", "monospace"):
                    used.add(part)
        return used

    def build_html(self, px=False):
        arts, texts, pximgs, defs = [], [], [], []
        rects, lines = [], []
        for r in self.spec.get("rects", []):
            rx0, ry0, rx1, ry1 = [int(v) for v in r["box"]]
            a = 'x="%d" y="%d" width="%d" height="%d" fill="%s"' % (
                rx0, ry0, rx1 - rx0, ry1 - ry0, r.get("fill", "#000000"))
            if r.get("rx"):
                a += ' rx="%d"' % int(r["rx"])
            if r.get("opacity") is not None:
                a += ' opacity="%s"' % r["opacity"]
            if r.get("stroke"):
                a += ' stroke="%s" stroke-width="%s"' % (
                    r["stroke"], r.get("stroke_w", 1))
            rects.append('    <rect %s/>' % a)
        for l in self.spec.get("lines", []):
            a = 'x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s"' % (
                l["x1"], l["y1"], l["x2"], l["y2"],
                l.get("stroke", "#000000"), l.get("w", 1))
            if l.get("dash"):
                a += ' stroke-dasharray="%s"' % l["dash"]
            if l.get("opacity") is not None:
                a += ' opacity="%s"' % l["opacity"]
            lines.append('    <line %s/>' % a)
        for name, box in self.spec.get("art", []):
            x0, y0 = int(box[0]), int(box[1])
            arts.append('<img class="layer" src="assets/%s.png" style="left:%dpx;top:%dpx">'
                        % (name, x0, y0))
        for i, t in enumerate(self.spec["text"]):
            if px and t.get("px"):
                bx0, by0, bx1, by1 = t["px_box"]
                pximgs.append('<img class="layer" src="assets/%s.png" style="left:%dpx;top:%dpx">'
                              % (t["px_asset"], bx0, by0))
                continue
            x0 = int(t.get("x", t["box"][0]))
            y0, y1 = t["box"][1], t["box"][3]
            w = int(t.get("text_length", t["box"][2] - t["box"][0]))
            fill = t["fill"]
            if t.get("grad"):
                gid = "gr%d" % i
                g = t["grad"]
                y1g = int(g.get("y2", y1))
                y2g = int(g.get("y1", t["box"][1]))
                if g.get("dir", "v") == "h":
                    defs.append('<linearGradient id="%s" gradientUnits="userSpaceOnUse" '
                                'x1="%d" y1="0" x2="%d" y2="0">'
                                '<stop offset="0%%" stop-color="%s"/>'
                                '<stop offset="100%%" stop-color="%s"/></linearGradient>'
                                % (gid, t["box"][0], t["box"][2], g["from"], g["to"]))
                else:
                    defs.append('<linearGradient id="%s" gradientUnits="userSpaceOnUse" '
                                'x1="0" y1="%d" x2="0" y2="%d">'
                                '<stop offset="0%%" stop-color="%s"/>'
                                '<stop offset="100%%" stop-color="%s"/></linearGradient>'
                                % (gid, y2g, y1g, g["from"], g["to"]))
                fill = "url(#%s)" % gid
            a = 'x="%d" y="%s" font-size="%s" font-weight="%d" fill="%s"' % (
                x0, t["base"], t["size"], t.get("weight", 700), fill)
            if t.get("stroke"):
                a += ' stroke="%s" stroke-width="%s" paint-order="stroke"' % (
                    t["stroke"], t.get("stroke_w", 2))
            if w > 4:
                a += ' textLength="%d" lengthAdjust="spacingAndGlyphs"' % w
            if t.get("font"):
                a += ' font-family="%s,Noto Sans SC,sans-serif"' % t["font"]
            if t.get("italic"):
                a += ' font-style="italic"'
            texts.append('    <text %s>%s</text>' % (a, (t["text"] or "").replace("&", "&amp;")))
        W, H = self.W, self.H
        defs_html = ("  <defs>%s</defs>\n" % "".join(defs)) if defs else ""
        return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>%(name)s · 还原源件</title>
<style>
%(fonts)s
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:#fff}
#poster{position:relative;width:%(W)dpx;height:%(H)dpx;overflow:hidden;background:#fff;
  font-family:"Noto Sans SC",sans-serif;-webkit-font-smoothing:antialiased}
.layer{position:absolute;display:block}
svg{position:absolute;left:0;top:0}
/* 关掉 SVG 文字的亚像素(LCD)渲染 —— 否则细笔画会出现红蓝彩边。
   原图是位图（无彩边），不关掉的话差异统计会被彩边污染，
   而且肉眼一看就像「空心字」。实测：R-B 通道差 191 -> 0。 */
svg text{-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}
</style></head><body><div id="poster">
  <!-- L1 照片层：原图（已挖掉待重建文字） -->
  <img class="layer" src="assets/plate.png" style="left:0;top:0">
%(px)s
  <!-- L2a 矢量色块层：纯色矩形/圆角矩形（背景结构） -->
  <svg width="%(W)d" height="%(H)d" viewBox="0 0 %(W)d %(H)d" xmlns="http://www.w3.org/2000/svg">
%(rects)s
  </svg>
  <!-- L2 美术素材层：原样裁切 + 原位贴回 -->
%(arts)s
  <!-- L2c 矢量线条层：表格线 / 尺寸标注线（前景结构） -->
  <svg width="%(W)d" height="%(H)d" viewBox="0 0 %(W)d %(H)d" xmlns="http://www.w3.org/2000/svg">
%(lines)s
  </svg>
  <!-- L3 文字层：SVG 活字，可编辑 -->
  <svg width="%(W)d" height="%(H)d" viewBox="0 0 %(W)d %(H)d" xmlns="http://www.w3.org/2000/svg">
%(defs)s%(texts)s
  </svg>
</div></body></html>
""" % {"name": self.spec["name"], "W": W, "H": H,
       "fonts": font_face_css(self._used_families()),
       "defs": defs_html,
       "px": "\n".join("  " + p for p in pximgs),
       "arts": "\n".join("  " + a for a in arts),
       "rects": "\n".join(rects),
       "lines": "\n".join(lines),
       "texts": "\n".join(texts)}

    # ---------------------------------------------------------- 渲染
    def _browser(self):
        if getattr(self, "_pw", None) is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._br = self._pw.chromium.launch()
            self._pages = {}
        return self._br

    def _page(self, scale):
        self._browser()
        key = scale
        if key not in self._pages:
            self._pages[key] = self._br.new_page(
                viewport={"width": self.W, "height": self.H},
                device_scale_factor=scale)
        return self._pages[key]

    def close(self):
        if getattr(self, "_pw", None) is not None:
            try:
                self._br.close()
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def render(self, htmlp, scale=1, outp=None):
        outp = outp or os.path.join(self.out, "_render.png")
        page = self._page(scale)
        page.goto("file:///" + htmlp.replace("\\", "/"))
        try:
            page.evaluate("async () => { await document.fonts.ready; }")
        except Exception:
            pass
        page.wait_for_timeout(120)
        page.locator("#poster").screenshot(path=outp)
        im = Image.open(outp).convert("RGB")
        if scale != 1:
            im = im.resize((self.W, self.H), Image.LANCZOS)
        return np.asarray(im).astype(int)

    # ---------------------------------------------------------- 差异
    def diff(self, B):
        d = np.abs(self.O - B).max(axis=2)
        return {"diff_gt20_pct": round(100.0 * float((d > 20).sum()) / d.size, 2),
                "mean_abs": round(float(np.abs(self.O - B).mean()), 2),
                "psnr": round(float(10 * np.log10(255 ** 2 /
                                                max(1e-9, ((self.O - B) ** 2).mean()))), 2)}

    # ---------------------------------------------------------- 墨迹校准
    def _bbox(self, img, box, pred, minpx=3):
        x0, y0, x1, y1 = box
        H, W = img.shape[:2]
        x0 = max(0, x0); y0 = max(0, y0); x1 = min(W, x1); y1 = min(H, y1)
        reg = img[y0:y1, x0:x1]
        m = pred(reg)
        if m.sum() < minpx:
            return None
        ys, xs = np.nonzero(m)
        return (int(xs.min() + x0), int(ys.min() + y0),
                int(xs.max() + x0), int(ys.max() + y0), int(m.sum()))

    def calibrate(self, B, title="文字墨迹包围盒校准"):
        print("\n=== %s ===" % title)
        print("%-14s %-26s %-26s %5s%5s%5s%5s %5s%5s" %
              ("元素", "原图 ink bbox", "重建 ink bbox", "dx0", "dy0", "dx1", "dy1", "w差", "h差"))
        rows = []
        for t in self.spec["text"]:
            if t.get("px"):
                continue
            f = hex2rgb(t["fill"])
            pred = lambda c: (np.abs(c - f).max(axis=2) < int(t.get("cal_tol", 70)))
            a = self._bbox(self.O, t["box"], pred)
            b = self._bbox(B, t["box"], pred)
            if not a or not b:
                print("%-14s orig=%s rebuild=%s  <取不到>" % (t["id"], a, b))
                continue
            d = (b[0] - a[0], b[1] - a[1], b[2] - a[2], b[3] - a[3])
            aw, ah = a[2] - a[0], a[3] - a[1]
            bw, bh = b[2] - b[0], b[3] - b[1]
            print("%-14s (%3d,%3d,%3d,%3d)      (%3d,%3d,%3d,%3d)      %5d%5d%5d%5d %5d%5d" %
                  (t["id"], a[0], a[1], a[2], a[3], b[0], b[1], b[2], b[3],
                   d[0], d[1], d[2], d[3], bw - aw, bh - ah))
            rows.append({"id": t["id"], "d": list(d), "dw": bw - aw, "dh": bh - ah})
        return rows

    # ---------------------------------------------------------- 参数寻优
    def _cur_attr(self, html, marker, attr, occ=0):
        """从当前 HTML 里读出某个元素的某个属性现值。"""
        marker = _esc_marker(marker)
        hits = list(re.finditer(r'<text[^>]*>' + re.escape(marker) + r'</text>', html))
        if len(hits) <= occ:
            return None
        el = hits[occ].group(0)
        m = re.search(r'(?<![\w-])' + re.escape(attr) + r'="([^"]*)"', el)
        return m.group(1) if m else None

    def sweep(self):
        """逐属性寻优：改一个属性 -> 重渲 -> 看该区域差异>20 的像素数 -> 取最小。

        **当前值必须进候选集**，否则会出现「越寻越差」：
        候选里没有现值时，最优解必然比现值差，引擎却照样把它写进 HTML。

        **批量渲染**：同一属性的 N 个候选拼成一张长页面，一次 page load + 一次截图，
        再逐格裁剪打分。
        以前是 N 次「打开页面 → 等字体 → 截图」，N 次里 90% 的时间花在重复加载上。
        批量后单属性的开销 ≈ 1 次加载 + 1 次大截图，R6 那种 27 属性 × 4 候选的
        寻优从 ~110 次渲染降到 ~27 次。
        """
        htmlp = os.path.join(self.out, "index.html")
        h = open(htmlp, encoding="utf-8").read()
        for s in self.spec.get("sweep", []):
            vals = list(s["values"])
            occ = int(s.get("occ", 0))
            cur = self._cur_attr(h, s["marker"], s["attr"], occ)
            if cur is not None and cur not in vals:
                vals.append(cur)
            cands = [self._set_attr(h, s["marker"], s["attr"], v, occ) for v in vals]
            smode = s.get("score")
            if smode in ("inkarea", "inkcolor", "fillarea", "strokearea"):
                scores = self._score_candidates_ink(cands, s["region"], smode,
                                                    s.get("marker"))
            else:
                scores = self._score_candidates(cands, s["region"], s["marker"], occ)
                if scores is None:
                    scores = self._score_candidates_fallback(cands, s["region"])
            best = None
            for v, sc, html in zip(vals, scores, cands):
                print("    %-16s %-12s=%-8s : %6d px%s" %
                      (s["marker"][:16], s["attr"], v, sc,
                       "   <= 现值" if str(v) == str(cur) else ""), flush=True)
                if best is None or sc < best[1]:
                    best = (v, sc, html)
            open(htmlp, "w", encoding="utf-8").write(best[2])
            h = best[2]
            print("  => %s : %s=%s (%d px)\n" % (s["marker"], s["attr"], best[0], best[1]))
        self._sync_spec_from_html(h)
        return h

    def _score_candidates(self, cands, region, marker, occ):
        """**局部 patch 渲染**打分。

        关键点：候选的得分只看 region 那一小块，所以根本不用渲染整张海报。
        把**当前整页内容**（照片层 + 美术素材层 + 全部文字层）平移裁到 region，
        拼成一个小窗口（典型 150×50），N 个候选横排一页 —— 一次截图全打完。

        渲染量从「整张海报 × N」降到「region 大小 × N」，
        1080×1920 的海报换成 150×50 的小块 ≈ 1300 倍像素差。
        这才是批量寻优该有的做法。

        注意：patch 必须包含**全部文字层**（不只是被调的那个），
        否则区域里其它文字的缺失会让得分和整张渲染对不上（实测差 0.2 个百分点）。
        """
        cells = self._render_cells(cands, region)
        x0, y0, x1, y1 = region
        RW, RH = max(1, x1 - x0), max(1, y1 - y0)
        im = None
        scores = []
        for k in range(len(cands)):
            cell = cells[k]
            if cell is None:
                scores.append(10 ** 9)
                continue
            d = np.abs(self.O[y0:y1, x0:x1] - cell).max(axis=2)
            scores.append(int((d > 20).sum()))
        return scores

    def _render_cells(self, cands, region):
        """把 N 个候选渲染成 N 个 region 大小的 cell（一次 page load + 一次截图）。

        纵向堆叠：**不要用 flex 横排** —— 单元格总宽超过视口时 flex 会自动压缩，
        渲染出来的比例和整张渲染对不上（实测 R6 差 0.2 个百分点）。
        """
        x0, y0, x1, y1 = region
        RW, RH = max(1, x1 - x0), max(1, y1 - y0)
        bodies = []
        for html_v in cands:
            body = self._split_html(html_v)[1]
            bodies.append(self._translate_body(body, x0, y0))
        css = self._split_html(cands[0])[0]
        page = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<style>%s</style></head><body style="margin:0;padding:0;background:#fff">'
                '%s</body></html>' %
                (css, "".join(
                    '<div style="position:relative;width:%dpx;height:%dpx;overflow:hidden">%s</div>'
                    % (RW, RH, c) for c in bodies)))
        gp = os.path.join(self.out, "_patch_sweep.html")
        open(gp, "w", encoding="utf-8").write(page)
        outp = os.path.join(self.out, "_patch_sweep.png")
        page_obj = self._page(1)
        page_obj.goto("file:///" + gp.replace("\\", "/"))
        try:
            page_obj.evaluate("async () => { await document.fonts.ready; }")
        except Exception:
            pass
        page_obj.wait_for_timeout(100)
        page_obj.screenshot(path=outp, full_page=True)
        im = np.asarray(Image.open(outp).convert("RGB")).astype(int)
        out = []
        for k in range(len(cands)):
            cell = im[k * RH:(k + 1) * RH, 0:RW]
            if cell.shape[0] < RH or cell.shape[1] < RW:
                out.append(None)
            else:
                out.append(cell.astype(np.uint8))
        return out

    def _translate_body(self, body, x0, y0):
        """把整页内容平移 (-x0,-y0)，让 region 落在窗口原点。"""
        art_pos = {nm: (int(bx[0]), int(bx[1])) for nm, bx in self.spec.get("art", [])}

        def fix(m):
            src = m.group("src")
            name = src.split("/")[-1].replace(".png", "")
            if name == "plate":
                return ('<img class="layer" src="assets/plate.png" '
                        'style="left:%dpx;top:%dpx">' % (-x0, -y0))
            if name in art_pos:
                ax, ay = art_pos[name]
                return ('<img class="layer" src="assets/%s.png" '
                        'style="left:%dpx;top:%dpx">' % (name, ax - x0, ay - y0))
            return m.group(0)
        # 注意：照片层写的是 left:0;top:0（没有 px），美术层是 left:0px;top:0px
        # 正则要两种都能匹配上，否则照片层不会被平移，patch 显示的是图的错位区域
        b = re.sub(r'<img class="layer" src="assets/(?P<src>[^"]+)" '
                   r'style="left:(?P<lx>[^;"]+);top:(?P<ty>[^;"]+)">', fix, body)
        svg_old = ('<svg width="%d" height="%d" viewBox="0 0 %d %d" '
                   'xmlns="http://www.w3.org/2000/svg">' %
                   (self.W, self.H, self.W, self.H))
        svg_new = ('<svg width="%d" height="%d" viewBox="0 0 %d %d" '
                   'style="position:absolute;left:%dpx;top:%dpx" '
                   'xmlns="http://www.w3.org/2000/svg">' %
                   (self.W, self.H, self.W, self.H, -x0, -y0))
        b = b.replace(svg_old, svg_new)
        return b


    # ---------------------------------------------------------- 墨量/墨色评分
    def _paper(self, region):
        """区域里的「纸底色」= 区域内出现最多的量化色的中位色。"""
        x0, y0, x1, y1 = region
        reg = self.O[y0:y1, x0:x1].reshape(-1, 3)
        if len(reg) == 0:
            return np.array([255, 255, 255], np.int32)
        q = reg // 16
        key = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
        vals, counts = np.unique(key, return_counts=True)
        k = vals[int(np.argmax(counts))]
        med = np.median(reg[key == k], axis=0).astype(np.int32)
        return med

    def _ink_stats(self, pix, bg, ref=None, tol=90):
        """返回 (墨量, 墨色)。

        ref=None  → 墨 = 离纸底足够远的那批像素（整体墨量）
        ref=色值  → 墨 = **与该颜色接近**的像素（分开数填充色 / 描边色）
        """
        if len(pix) == 0:
            return 0, None
        if ref is not None:
            r = np.array([int(ref[5:7], 16), int(ref[3:5], 16),
                          int(ref[1:3], 16)], np.int32)
            dm = np.abs(pix.astype(np.int32) - r).max(axis=1)
            mask = dm < tol
            area = int(mask.sum())
            if area < 2:
                return area, None
            med = np.median(pix[mask], axis=0).astype(int)
            return area, med
        d = np.abs(pix.astype(np.int32) - bg).max(axis=1)
        dmax = int(d.max())
        if dmax < 45:
            return 0, None
        thr = max(55, int(0.55 * dmax))
        mask = d > thr
        area = int(mask.sum())
        if area < 2:
            return area, None
        core = pix[mask]
        # 墨色再取一次核心：离纸底最远的那一小撮
        dd = d[mask]
        cm = dd > max(thr, int(0.85 * dmax))
        if cm.sum() >= 2:
            core = core[cm]
        med = np.median(core, axis=0).astype(int)
        return area, med

    def _elem_by_marker(self, marker):
        for t in self.spec.get("text", []):
            if t.get("text") == marker:
                return t
        return None

    def _score_candidates_ink(self, cands, region, mode, marker=None):
        """按墨量 / 墨色 / 分色面积评分（不看像素差）。"""
        x0, y0, x1, y1 = region
        bg = self._paper(region)
        orig_pix = self.O[y0:y1, x0:x1].reshape(-1, 3)
        ref = None
        elem = self._elem_by_marker(marker) if marker else None
        if mode == "fillarea" and elem:
            ref = elem.get("fill")
        elif mode == "strokearea" and elem:
            ref = elem.get("stroke")
        o_area, o_color = self._ink_stats(orig_pix, bg, ref=ref)
        cells = self._render_cells(cands, region)
        scores = []
        for cell in cells:
            if cell is None:
                scores.append(10 ** 9)
                continue
            c_area, c_color = self._ink_stats(cell.reshape(-1, 3), bg, ref=ref)
            if mode in ("inkarea", "fillarea", "strokearea"):
                scores.append(abs(c_area - o_area))
            else:                                   # inkcolor
                if c_color is None or o_color is None:
                    scores.append(10 ** 9)
                else:
                    scores.append(int(np.abs(c_color - o_color).max()))
        return scores

    def _score_candidates_fallback(self, cands, region):
        """局部 patch 失败时的退路：老老实实整张渲染（慢但准）。"""
        x0, y0, x1, y1 = region
        htmlp = os.path.join(self.out, "index.html")
        scores = []
        for html_v in cands:
            open(htmlp, "w", encoding="utf-8").write(html_v)
            B = self.render(htmlp, 1, os.path.join(self.out, "_sweep.png"))
            d = np.abs(self.O[y0:y1, x0:x1] - B[y0:y1, x0:x1]).max(axis=2)
            scores.append(int((d > 20).sum()))
        return scores

    def _extract_text_el(self, html, marker, occ=0):
        """从 HTML 里取出第 occ 个 <text ...>marker</text> 元素。"""
        esc = _esc_marker(marker)
        hits = list(re.finditer(r'<text[^>]*>' + re.escape(esc) + r'</text>', html))
        if len(hits) <= occ:
            return None
        return hits[occ].group(0)

    def _split_html(self, html):
        """拆出 <style> 内容与 <body> 内容。"""
        m = re.search(r'<style>(.*?)</style>', html, re.S)
        css = m.group(1) if m else ""
        b = html.split("<body>")
        body = b[1].split("</body>")[0] if len(b) > 1 else html
        return css, body

    def _css_of(self, html):
        m = re.search(r'<style>(.*?)</style>', html, re.S)
        return m.group(1) if m else ""

    def _sync_spec_from_html(self, html):
        """把寻优后的最终属性回写进 spec。

        这样 spec 本身就是「标定结果」：重跑一遍能得到同样的成品，
        像素层版也能从 spec 重建出与活字版一致的其它文字。

        注意：**同名文字要按出现顺序逐个对应**。
        踩过的坑：早先写 `hits[0]`，结果 R2 的两个「全光谱」、
        R4 的两组 Beyond/Rarity 全被写成第一处的值，
        重新打包后 R4 活字版从 4.16% 退化到 5.18%。
        HTML 里的 <text> 顺序 = spec 里的顺序，所以按序消费即可。
        """
        used = {}
        for t in self.spec["text"]:
            txt = t["text"]
            # HTML 里 & 会被转义成 &amp;，匹配时要用转义后的形式
            esc = (txt or "").replace("&", "&amp;")
            hits = list(re.finditer(r'<text[^>]*>' + re.escape(esc) + r'</text>', html))
            k = used.get(txt, 0)
            if k >= len(hits):
                continue
            used[txt] = k + 1
            el = hits[k].group(0)

            def g(attr, cast=str):
                m = re.search(r'(?<![\w-])' + re.escape(attr) + r'="([^"]*)"', el)
                return cast(m.group(1)) if m else None
            v = g("x", int)
            if v is not None:
                t["x"] = v
            v = g("y")
            if v is not None:
                t["base"] = v
            v = g("font-size")
            if v is not None:
                t["size"] = v
            v = g("font-weight", int)
            if v is not None:
                t["weight"] = v
            v = g("stroke-width")
            if v is not None:
                t["stroke_w"] = v
            v = g("textLength", int)
            if v is not None:
                t["text_length"] = v
            # fill 回写：字色进寻优后必须落盘，否则重打包退回原始字色
            v = g("fill")
            if v is not None and not v.startswith("url("):
                t["fill"] = v

    def _set_attr(self, html, marker, attr, value, occ=0):
        marker = _esc_marker(marker)
        hits = list(re.finditer(r'<text[^>]*>' + re.escape(marker) + r'</text>', html))
        if len(hits) <= occ:
            return html
        m = hits[occ]
        el = m.group(0)
        # 加上负向断言，避免 "x=" 误命中 "textLength=" 之类
        new_el = re.sub(r'(?<![\w-])' + re.escape(attr) + r'="[^"]*"',
                        '%s="%s"' % (attr, value), el, count=1)
        return html[:m.start()] + new_el + html[m.end():]

    # ---------------------------------------------------------- 像素层版
    def make_px(self):
        """在**寻优后**的 index.html 上做替换，而不是从 spec 重新生成。

        坑：从 spec 重新生成会把寻优结果（字号/基线/x）全部打回原值，
        像素层版反而比活字版还差（R2 首次交付 3.68% vs 3.58% 就是这个原因）。
        """
        htmlp = os.path.join(self.out, "index.html")
        base = open(htmlp, encoding="utf-8").read()
        imgs = []
        for t in self.spec["text"]:
            if not t.get("px"):
                continue
            x0, y0, x1, y1 = t["box"]
            pad = int(t.get("px_pad", 4))
            bx0, by0 = max(0, x0 - pad), max(0, y0 - pad)
            bx1, by1 = min(self.W, x1 + pad), min(self.H, y1 + pad)
            Image.fromarray(self.A[by0:by1, bx0:bx1]).save(
                os.path.join(self.out, "assets", t["px_asset"] + ".png"))
            imgs.append((t["text"],
                         '<img class="layer" src="assets/%s.png" style="left:%dpx;top:%dpx">'
                         % (t["px_asset"], bx0, by0)))
        out = base
        for txt, img in imgs:
            out = re.sub(r'\s*<text[^>]*>' + re.escape(txt) + r'</text>', '', out)
        anchor = '<img class="layer" src="assets/plate.png" style="left:0;top:0">'
        out = out.replace(anchor, anchor + "\n" + "\n".join("  " + i for _, i in imgs))
        return out


# ================================================================== 交付
def deliver(rb, res):
    """产出交付件。

    目录（**每个 run 自带**，可整体拷走）：
        <out>/<KEY>/deliver/<KEY>_像素级还原/   成品图 + 对比图 + 热力图
        <out>/<KEY>/deliver/<KEY>_源件包/        index.html + assets + 规格说明
    """
    spec = rb.spec
    droot = os.path.join(rb.out, "deliver")
    DEST = os.path.join(droot, spec["key"] + "_像素级还原")
    ADEST = os.path.join(droot, spec["key"] + "_源件包")
    os.makedirs(DEST, exist_ok=True)
    os.makedirs(os.path.join(ADEST, "assets"), exist_ok=True)

    base = spec["name"]
    versions = [("活字版", os.path.join(rb.out, "index.html"))]
    pxp = os.path.join(rb.out, "index_px.html")
    if os.path.exists(pxp):
        versions.append(("像素层版", pxp))

    out = {}
    for tag, htmlp in versions:
        for sc in (1, 2):
            outp = os.path.join(DEST, "%s_还原_%s_%dx.png" % (base, tag, sc))
            B = rb.render(htmlp, sc, outp)
            if sc == 1:
                d = np.abs(rb.O - B).max(axis=2)
                out[tag] = rb.diff(B)
                hm = np.zeros((rb.H, rb.W, 3), np.uint8)
                hm[:, :, 2] = np.clip(d * 4, 0, 255)
                hm[:, :, 1] = np.clip(d * 4, 0, 255) // 3
                Image.fromarray(hm).save(os.path.join(DEST, "%s_差异热力图_%s.png" % (base, tag)))
                side = Image.new("RGB", (rb.W * 2 + 12, rb.H), (255, 255, 255))
                side.paste(Image.fromarray(rb.A), (0, 0))
                side.paste(Image.fromarray(B.astype(np.uint8)), (rb.W + 12, 0))
                side.save(os.path.join(DEST, "%s_对比_原图左_还原右_%s.png" % (base, tag)))
        print("  %s -> %s" % (tag, out[tag]))

    json.dump(out, open(os.path.join(DEST, "_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # 源件包
    for f in os.listdir(os.path.join(rb.out, "assets")):
        shutil.copy(os.path.join(rb.out, "assets", f), os.path.join(ADEST, "assets", f))
    for f in ("index.html", "index_px.html", "_spec.json"):
        p = os.path.join(rb.out, f)
        if os.path.exists(p):
            shutil.copy(p, os.path.join(ADEST, f))
    write_spec_doc(spec, rb, os.path.join(ADEST, "还原规格说明.md"))
    print("交付 ->", DEST)
    print("源件 ->", ADEST)
    return out


def write_spec_doc(spec, rb, path):
    L = []
    L.append("# %s · 还原规格说明" % spec["name"])
    L.append("")
    L.append("> 唯一编辑入口：`index.html`（改价/改文案/换图都在这里改）")
    L.append("> `index_px.html` = 像素层版（主视觉改用原图裁切块，逐像素一致，代价是不可编辑）")
    L.append("")
    L.append("## 画布")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append("| 原图 | %d×%d |" % (rb.W0, rb.H0))
    L.append("| 裁切（上,下,左,右） | %s |" % (spec.get("crop", [0, 0, 0, 0]),))
    L.append("| 工作画布 | %d×%d |" % (rb.W, rb.H))
    L.append("")
    L.append("## 图层结构")
    L.append("")
    L.append("| 层 | 内容 | 可编辑 |")
    L.append("|---|---|---|")
    L.append("| L1 照片层 `assets/plate.png` | 原图，挖掉待重建文字后 inpaint 修补 | 否 |")
    L.append("| L2 美术素材层 `assets/*.png` | 原样裁切 + 原位贴回（像素级 0 差异） | 换图可改 |")
    L.append("| L3 文字层 SVG `<text>` | 活字，改文案/字号/描边/颜色 | 是 |")
    L.append("")
    L.append("## 文字元素（%d 个）" % len(spec["text"]))
    L.append("")
    L.append("| id | 文案 | 墨迹框 x0,y0,x1,y1 | 基线 y | 字号 | 字重 | 字色 | 描边 | 描边宽 | 字体 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for t in spec["text"]:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            t.get("id", ""), t.get("text", ""),
            ",".join(str(v) for v in t["box"]), t.get("base", ""), t.get("size", ""),
            t.get("weight", ""), t.get("fill", ""), t.get("stroke", "-"),
            t.get("stroke_w", "-"), t.get("font", "Noto Sans SC")))
    L.append("")
    L.append("## 美术素材（%d 个，原样裁切 + 原位贴回）" % len(spec.get("art", [])))
    L.append("")
    L.append("| 名称 | 裁切框 x0,y0,x1,y1 |")
    L.append("|---|---|")
    for name, box in spec.get("art", []):
        L.append("| %s | %s |" % (name, ",".join(str(v) for v in box)))
    L.append("")
    if spec.get("sweep"):
        L.append("## 参数寻优记录")
        L.append("")
        L.append("| 元素 | 属性 | 候选值 |")
        L.append("|---|---|---|")
        for s in spec["sweep"]:
            L.append("| %s | %s | %s |" % (s["marker"], s["attr"],
                                           " / ".join(str(v) for v in s["values"])))
        L.append("")
    open(path, "w", encoding="utf-8").write("\n".join(L))


# ================================================================== 主流程
def run(spec_path, outdir, do_sweep=True, do_deliver=True):
    # utf-8-sig：容忍 PowerShell Set-Content -Encoding UTF8 写出的 BOM
    spec = json.load(open(spec_path, encoding="utf-8-sig"))
    rb = Rebuild(spec, outdir)
    print("== %s  canvas %dx%d (orig %dx%d) ==" %
          (spec["name"], rb.W, rb.H, rb.W0, rb.H0))
    n = rb.make_plate()
    print("  plate.png: 挖掉 %d px 文字" % n)
    rb.cut_art()
    used = rb._used_families()
    for f, fam, wght, style, fmt in FONTS:
        if fam not in used:
            continue          # 只拷 spec 里真正用到的字体（Noto Serif SC 有 25MB）
        for s in (os.path.join(FONT_HERE, f), os.path.join(FONT_SRC, f)):
            if not os.path.exists(s):
                continue
            try:
                if os.path.getsize(s) < 1024:
                    continue          # 下载中/损坏的字体直接跳过
                shutil.copy(s, os.path.join(outdir, "assets", f))
            except Exception as e:
                print("  ! 字体拷贝失败 %s: %s" % (f, e))
            break
    html = rb.build_html(px=False)
    open(os.path.join(outdir, "index.html"), "w", encoding="utf-8").write(html)
    json.dump(spec, open(os.path.join(outdir, "_spec.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    B = rb.render(os.path.join(outdir, "index.html"), 1, os.path.join(outdir, "_render_1x.png"))
    print("  初始:", rb.diff(B))
    rb.calibrate(B)

    if do_sweep and spec.get("sweep"):
        print("\n== 参数寻优 ==")
        rb.sweep()
        B = rb.render(os.path.join(outdir, "index.html"), 1, os.path.join(outdir, "_render_1x.png"))
        print("  寻优后:", rb.diff(B))
        rb.calibrate(B, "寻优后 墨迹包围盒校准")
        # 寻优结果回写进 spec（spec 即标定结果，可复现）
        json.dump(spec, open(os.path.join(outdir, "_spec.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        cal = os.path.join(os.path.dirname(os.path.abspath(outdir)), "specs",
                           "%s_calibrated.json" % spec["key"].split("_")[0])
        try:
            os.makedirs(os.path.dirname(cal), exist_ok=True)
            json.dump(spec, open(cal, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            pass

    res = {"live": rb.diff(B)}
    # 像素层版**总是**产出：即使没有文字需要降级，也要有一份
    # 「字形用原图裁切」的版本，交付方才能统一处理两个版本。
    px_html = rb.make_px()
    pxp = os.path.join(outdir, "index_px.html")
    open(pxp, "w", encoding="utf-8").write(px_html)
    BP = rb.render(pxp, 1, os.path.join(outdir, "_render_px.png"))
    res["px"] = rb.diff(BP)
    print("  像素层版:", res["px"])

    json.dump(res, open(os.path.join(outdir, "_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    if do_deliver:
        deliver(rb, res)
    rb.close()
    return rb, res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-sweep", action="store_true")
    ap.add_argument("--no-deliver", action="store_true")
    a = ap.parse_args()
    sp = json.load(open(a.spec, encoding="utf-8"))
    out = a.out or os.path.join(HERE, sp["key"].lower() + "_rebuild")
    run(a.spec, out, do_sweep=not a.no_sweep, do_deliver=not a.no_deliver)

