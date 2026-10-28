# -*- coding: utf-8 -*-
r"""生成**示例图**（全部程序绘制，无任何第三方素材/版权风险）。

为什么要自己画
    开源仓库里不能放任何来源不明的参考图（电商平台的图都有著作权）。
    自己生成的图既是**原创**素材，又能精确构造出引擎要处理的各种结构：
    深色标题条、参数表、跨底色文字、圆形标注、双栏对比……

生成 3 张，分别对应 3 个版式族：
    demo_param_card  参数规格卡：深色标题条 + 产品位 + 属性格 + 参数表
                     + **一行横跨浅底/深底两个区域的文字**（跨底色场景）
    demo_brace_title 大括号标题：｛大标题｝ + 副标题 + 圆形标注 + 底部信息条
    demo_compare     对比双栏：左右两栏 + 图标 + 结论文案

用法
    python examples/make_samples.py --out examples/samples
"""
import os
import sys
import math
import argparse

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONT = os.path.join(ROOT, "layout_restore", "assets", "NotoSansSC-VF.ttf")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def F(size):
    try:
        return ImageFont.truetype(FONT, size)
    except Exception:
        return ImageFont.load_default()


def vgrad(w, h, c0, c1, horizontal=False):
    """线性渐变。"""
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    n = w if horizontal else h
    for i in range(n):
        t = i / max(1, n - 1)
        col = tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3))
        if horizontal:
            d.line([(i, 0), (i, h)], fill=col)
        else:
            d.line([(0, i), (w, i)], fill=col)
    return im


def text_at(d, xy, s, font, fill, anchor=None):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)


# ------------------------------------------------------------------ 样本 1
def sample_param_card(w=900, h=1100):
    """参数规格卡（含跨底色文字）。"""
    im = vgrad(w, h, (226, 214, 198), (198, 182, 162))
    d = ImageDraw.Draw(im)

    # --- 深色标题条 ---
    bar_h = 108
    d.rectangle([0, 0, w, bar_h], fill=(26, 22, 44))
    text_at(d, (40, 26), "AURORA 落地灯 · 参数规格", F(34), (255, 255, 255))
    text_at(d, (w - 40, 44), "型号 AL-2000", F(24), (196, 190, 215), anchor="ra")

    # --- 产品位（浅灰圆角卡 + 简笔灯） ---
    d.rounded_rectangle([40, 152, 400, 560], radius=18, fill=(238, 234, 228))
    d.ellipse([130, 190, 310, 370], fill=(214, 206, 196))
    d.rectangle([213, 360, 227, 470], fill=(198, 190, 180))
    d.ellipse([180, 458, 260, 486], fill=(176, 168, 158))
    # 卡片内的尺寸标注（浅底上的深色字）
    d.line([(90, 520), (350, 520)], fill=(150, 140, 128), width=2)
    for x in (90, 350):
        d.ellipse([x - 4, 516, x + 4, 524], fill=(150, 140, 128))
    text_at(d, (220, 488), "1200mm", F(22), (130, 120, 108), anchor="ma")

    # --- 右侧属性格 2x2 ---
    cells = [("功率", "24W"), ("色温", "3000K"), ("显色", "Ra≥95"), ("寿命", "50000h")]
    for i, (k, v) in enumerate(cells):
        cx = 450 + (i % 2) * 210
        cy = 152 + (i // 2) * 110
        d.rounded_rectangle([cx, cy, cx + 190, cy + 92], radius=10,
                            fill=(255, 255, 255), outline=(206, 196, 182), width=2)
        text_at(d, (cx + 14, cy + 12), k, F(20), (140, 130, 118))
        text_at(d, (cx + 14, cy + 44), v, F(28), (34, 30, 44))

    # --- 深色面板（右）---
    px0, py0 = 560, 620
    d.rectangle([px0, py0, w, 970], fill=(64, 52, 38))

    # --- ★ 跨底色：一行白字横跨浅底与深底的边界（x=560）---
    text_at(d, (40, py0 + 18),
            "整灯亮度 800lm · 光效 110lm/W · 质保 3 年", F(28), (255, 255, 255))

    # --- 深底上的尺寸标注 ---
    d.line([(600, py0 + 150), (840, py0 + 150)], fill=(255, 255, 255), width=2)
    for x in (600, 840):
        d.ellipse([x - 4, py0 + 146, x + 4, py0 + 154], fill=(255, 255, 255))
    text_at(d, (720, py0 + 118), "480mm", F(24), (255, 255, 255), anchor="ma")

    # --- 参数表（左）---
    rows = [("额定电压", "AC 220V / 50Hz"), ("输入功率", "24W ± 10%"),
            ("光源", "集成 LED 模组"), ("防护等级", "IP20"),
            ("灯体材质", "压铸铝 + 亚克力"), ("净重", "1.85 kg")]
    y = 706
    for k, v in rows:
        d.line([(40, y - 14), (520, y - 14)], fill=(208, 196, 180), width=1)
        text_at(d, (46, y), k, F(23), (86, 78, 68))
        text_at(d, (250, y), v, F(23), (34, 30, 44))
        y += 46

    text_at(d, (40, 1030), "注：以上数据为实验室实测值，实际以产品为准。",
            F(20), (110, 100, 88))
    return im


# ------------------------------------------------------------------ 样本 2
def sample_brace_title(w=900, h=900):
    """大括号标题 + 圆形标注 + 底部信息条。"""
    im = vgrad(w, h, (244, 228, 208), (214, 190, 162))
    d = ImageDraw.Draw(im)

    text_at(d, (w // 2, 90), "NOVA 保温杯", F(30), (150, 110, 78), anchor="ma")
    text_at(d, (w // 2, 190), "{  轻量 · 保温 · 一杯两用  }", F(58),
            (38, 30, 24), anchor="ma")
    text_at(d, (w // 2, 276), "316 不锈钢内胆 · 24h 长效保温", F(26),
            (96, 78, 60), anchor="ma")

    # 杯身（示意）
    d.rounded_rectangle([330, 360, 570, 700], radius=40, fill=(238, 240, 242),
                        outline=(196, 200, 204), width=4)
    d.rounded_rectangle([350, 330, 550, 380], radius=16, fill=(120, 128, 136))
    d.rectangle([400, 470, 500, 590], fill=(198, 206, 212))

    # 圆形标注
    for cx, cy, txt in ((250, 430, "轻"), (650, 520, "暖"), (280, 640, "净")):
        d.ellipse([cx - 62, cy - 62, cx + 62, cy + 62], fill=(255, 255, 255),
                  outline=(198, 132, 74), width=5)
        text_at(d, (cx, cy), txt, F(44), (178, 110, 54), anchor="mm")

    # 底部信息条
    d.rectangle([0, 760, w, h], fill=(38, 30, 24))
    items = [("容量", "500ml"), ("重量", "268g"), ("保冷", "12h"), ("质保", "2年")]
    for i, (k, v) in enumerate(items):
        x = 90 + i * 190
        text_at(d, (x, 792), k, F(22), (176, 162, 148))
        text_at(d, (x, 824), v, F(30), (255, 255, 255))
    return im


# ------------------------------------------------------------------ 样本 3
def sample_compare(w=900, h=900):
    """左右双栏对比 + 结论文案。"""
    im = Image.new("RGB", (w, h), (244, 245, 247))
    d = ImageDraw.Draw(im)

    d.rectangle([0, 0, w, 96], fill=(30, 38, 52))
    text_at(d, (w // 2, 30), "普通涂层  vs  陶瓷涂层", F(34), (255, 255, 255), anchor="ma")

    # 左栏
    d.rounded_rectangle([60, 150, 410, 660], radius=16, fill=(255, 255, 255),
                        outline=(214, 218, 224), width=2)
    text_at(d, (235, 190), "普通涂层", F(30), (96, 102, 112), anchor="ma")
    d.ellipse([145, 250, 325, 430], fill=(210, 214, 220))
    for i, s in enumerate(["易脱落", "易划伤", "涂层不均"]):
        y = 480 + i * 56
        d.ellipse([170, y, 196, y + 26], fill=(198, 118, 110))
        text_at(d, (214, y - 2), s, F(26), (120, 96, 92))

    # 右栏
    d.rounded_rectangle([490, 150, 840, 660], radius=16, fill=(255, 255, 255),
                        outline=(180, 200, 214), width=3)
    text_at(d, (665, 190), "陶瓷涂层", F(30), (40, 72, 104), anchor="ma")
    d.ellipse([575, 250, 755, 430], fill=(196, 214, 228))
    for i, s in enumerate(["更耐磨", "更耐腐蚀", "受热更均匀"]):
        y = 480 + i * 56
        d.ellipse([600, y, 626, y + 26], fill=(104, 168, 122))
        text_at(d, (644, y - 2), s, F(26), (66, 104, 84))

    # 结论文案条
    d.rounded_rectangle([60, 700, 840, 800], radius=12, fill=(30, 38, 52))
    text_at(d, (w // 2, 730), "结论：陶瓷涂层在耐磨与耐腐蚀上明显更优",
            F(30), (255, 255, 255), anchor="ma")
    text_at(d, (w // 2, 840), "同批次测试 · 实验室数据 · 仅供参考",
            F(20), (128, 134, 144), anchor="ma")
    return im


SAMPLES = [
    ("demo_param_card", sample_param_card),
    ("demo_brace_title", sample_brace_title),
    ("demo_compare", sample_compare),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "samples"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for name, fn in SAMPLES:
        im = fn()
        p = os.path.join(a.out, name + ".png")
        im.save(p)
        print("wrote %s  %dx%d" % (p, im.width, im.height))
    print("\n%s 张示例图（全部程序绘制，原创素材）" % len(SAMPLES))


if __name__ == "__main__":
    main()
