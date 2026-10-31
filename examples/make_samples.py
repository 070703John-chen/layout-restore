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


# ------------------------------------------------------------------ 样本 4
def sample_promo_banner(w=900, h=900):
    """促销主图：大字 + 价格块 + 爆炸贴 + 倒计时条。"""
    im = vgrad(w, h, (226, 62, 78), (176, 32, 52))
    d = ImageDraw.Draw(im)

    text_at(d, (w // 2, 96), "限时特惠", F(34), (255, 226, 160), anchor="ma")
    text_at(d, (w // 2, 190), "全场五折起", F(76), (255, 255, 255), anchor="ma")
    text_at(d, (w // 2, 292), "爆款直降 200 元", F(34), (255, 238, 214), anchor="ma")

    # 价格块
    d.rounded_rectangle([150, 380, 750, 590], radius=20, fill=(255, 255, 255))
    text_at(d, (250, 430), "￥", F(44), (214, 44, 56))
    text_at(d, (290, 408), "299", F(110), (214, 44, 56))
    text_at(d, (520, 452), "起", F(34), (120, 118, 126))
    d.line([(600, 500), (700, 500)], fill=(190, 120, 126), width=3)
    text_at(d, (650, 478), "¥499", F(30), (150, 140, 146), anchor="ma")

    # 爆炸贴
    d.ellipse([640, 120, 830, 310], fill=(255, 208, 72), outline=(228, 158, 40), width=5)
    text_at(d, (735, 176), "爆", F(52), (168, 84, 22), anchor="ma")
    text_at(d, (735, 232), "款", F(52), (168, 84, 22), anchor="ma")

    # 倒计时条
    d.rounded_rectangle([90, 660, 810, 760], radius=14, fill=(48, 22, 34))
    text_at(d, (120, 692), "距结束", F(26), (255, 208, 208))
    for i, (v, lbl) in enumerate([("02", "时"), ("18", "分"), ("45", "秒")]):
        x = 380 + i * 130
        text_at(d, (x, 686), v, F(40), (255, 255, 255), anchor="ma")
        text_at(d, (x + 46, 700), lbl, F(22), (255, 190, 190))
    text_at(d, (w // 2, 820), "活动时间：即日起至库存售罄", F(22),
            (255, 214, 214), anchor="ma")
    return im


# ------------------------------------------------------------------ 样本 5
def sample_spec_table(w=900, h=1200):
    """参数规格长图：表头 + 多行表格 + 脚注。"""
    im = Image.new("RGB", (w, h), (250, 250, 248))
    d = ImageDraw.Draw(im)

    d.rectangle([0, 0, w, 150], fill=(38, 46, 58))
    text_at(d, (w // 2, 44), "LUMEN 吸顶灯 · 技术参数", F(38), (255, 255, 255), anchor="ma")
    text_at(d, (w // 2, 102), "Model AL-3000 · 规格书", F(24), (172, 180, 192), anchor="ma")

    head = ["项目", "参数", "备注"]
    xw = [220, 380, 200]
    y0 = 200
    x = 50
    for i, htxt in enumerate(head):
        d.rectangle([x, y0, x + xw[i], y0 + 56], fill=(228, 232, 238))
        text_at(d, (x + 16, y0 + 14), htxt, F(26), (52, 60, 72))
        x += xw[i]
    rows = [("额定功率", "24W ± 10%", "恒定电流驱动"),
            ("输入电压", "AC 220V / 50Hz", "国标三芯"),
            ("色温", "3000K / 4000K / 6000K", "三色可选"),
            ("显色指数", "Ra ≥ 95", "全光谱"),
            ("光通量", "2400 lm", "整灯输出"),
            ("光效", "110 lm/W", "整灯效率"),
            ("防护等级", "IP20", "室内使用"),
            ("灯体材质", "压铸铝 + 亚克力", "喷砂处理"),
            ("净重", "1.85 kg", "含光源"),
            ("质保", "3 年", "光源 5 年")]
    y = y0 + 56
    for r in rows:
        x = 50
        for i, cell in enumerate(r):
            d.rectangle([x, y, x + xw[i], y + 58], outline=(206, 210, 218), width=1)
            text_at(d, (x + 16, y + 16), cell, F(25),
                    (58, 62, 70) if i == 0 else (96, 100, 108))
            x += xw[i]
        y += 58
    d.rectangle([50, y0, 850, y], outline=(178, 184, 194), width=2)

    text_at(d, (50, y + 40), "注：以上数据为实验室实测值，实际以产品为准。",
            F(22), (128, 132, 140))
    text_at(d, (50, y + 84), "执行标准 GB/T 9473-2015 · 质保需凭购买凭证",
            F(22), (128, 132, 140))
    return im


# ------------------------------------------------------------------ 样本 6
def sample_white_product(w=900, h=900):
    """白底产品图：产品 + 卖点标注线 + 底部参数条。"""
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)

    # 产品（简笔吸顶灯）
    d.ellipse([250, 170, 650, 380], fill=(238, 240, 244), outline=(214, 218, 226), width=4)
    d.ellipse([310, 220, 590, 330], fill=(250, 246, 226))
    d.rectangle([420, 380, 480, 470], fill=(206, 210, 218))

    # 卖点标注线 + 标签
    def callout(x1, y1, x2, y2, label):
        d.line([(x1, y1), (x2, y2)], fill=(196, 118, 110), width=2)
        d.ellipse([x1 - 5, y1 - 5, x1 + 5, y1 + 5], fill=(196, 118, 110))
        text_at(d, (x2, y2), label, F(24), (140, 92, 88),
                anchor="la" if x2 > x1 else "ra")

    callout(300, 240, 90, 170, "导光面板")
    callout(450, 420, 620, 470, "铝合金散热体")
    callout(600, 300, 780, 210, "Ra≥95 全光谱")

    text_at(d, (w // 2, 560), "AL-3000 吸顶灯", F(40), (44, 48, 56), anchor="ma")
    text_at(d, (w // 2, 622), "24W · 3000K · 2400lm", F(28), (128, 132, 140), anchor="ma")

    d.rectangle([0, 720, w, h], fill=(246, 247, 249))
    items = [("功率", "24W"), ("色温", "3000K"), ("显色", "Ra95"), ("质保", "3年")]
    for i, (k, v) in enumerate(items):
        x = 110 + i * 190
        text_at(d, (x, 752), k, F(22), (140, 144, 152))
        text_at(d, (x, 786), v, F(32), (44, 48, 56))
    return im


# ------------------------------------------------------------------ 样本 7
def sample_detail_long(w=900, h=1400):
    """详情长图：多段图文 + 图标网格 + 底部对比条。"""
    im = Image.new("RGB", (w, h), (252, 250, 247))
    d = ImageDraw.Draw(im)

    d.rectangle([0, 0, w, 120], fill=(24, 26, 32))
    text_at(d, (w // 2, 40), "为什么选它", F(40), (255, 255, 255), anchor="ma")

    text_at(d, (w // 2, 180), "三个理由", F(32), (32, 36, 44), anchor="ma")

    reasons = [("01", "省电", "比传统白炽灯省 80% 电费", (58, 122, 96)),
               ("02", "护眼", "Ra≥95 全光谱，无可视频闪", (52, 92, 148)),
               ("03", "耐用", "50000 小时质保无忧", (168, 108, 48))]
    for i, (no, title, desc, col) in enumerate(reasons):
        y = 250 + i * 210
        d.rounded_rectangle([80, y, 820, y + 170], radius=18, fill=(255, 255, 255),
                            outline=(228, 224, 216), width=2)
        d.ellipse([116, y + 36, 196, y + 116], fill=col)
        text_at(d, (156, y + 56), no, F(34), (255, 255, 255), anchor="ma")
        text_at(d, (232, y + 38), title, F(34), (32, 36, 44))
        text_at(d, (232, y + 92), desc, F(25), (128, 126, 122))

    # 图标网格
    text_at(d, (w // 2, 900), "核心参数", F(32), (32, 36, 44), anchor="ma")
    grid = [("24W", "功率"), ("3000K", "色温"), ("2400lm", "光通量"),
            ("Ra95", "显色"), ("IP20", "防护"), ("3年", "质保")]
    for i, (v, k) in enumerate(grid):
        cx = 130 + (i % 3) * 320
        cy = 960 + (i // 3) * 150
        d.rounded_rectangle([cx - 110, cy - 52, cx + 110, cy + 52], radius=14,
                            fill=(255, 255, 255), outline=(226, 222, 214), width=2)
        text_at(d, (cx, cy - 34), v, F(34), (36, 40, 48), anchor="ma")
        text_at(d, (cx, cy + 14), k, F(22), (140, 138, 132), anchor="ma")

    d.rounded_rectangle([80, 1270, 820, 1360], radius=14, fill=(24, 26, 32))
    text_at(d, (w // 2, 1296), "同规格对比：我们比普通款亮 18%",
            F(30), (255, 255, 255), anchor="ma")
    return im


# ------------------------------------------------------------------ 样本 8
def sample_wide_banner(w=1200, h=500):
    """横向横幅：logo + 大标题 + 按钮 + 背景几何。"""
    im = vgrad(w, h, (28, 34, 48), (52, 40, 70), horizontal=True)
    d = ImageDraw.Draw(im)

    # 背景几何
    d.ellipse([820, -120, 1180, 240], fill=(70, 58, 98))
    d.ellipse([900, 220, 1240, 560], fill=(44, 50, 74))
    d.polygon([(0, 500), (300, 120), (520, 500)], fill=(36, 42, 60))

    d.ellipse([80, 70, 140, 130], fill=(255, 206, 92))
    text_at(d, (160, 82), "AURORA", F(34), (255, 255, 255))
    text_at(d, (80, 200), "让每一束光", F(62), (255, 255, 255))
    text_at(d, (80, 284), "都恰到好处", F(62), (255, 206, 92))

    d.rounded_rectangle([80, 386, 300, 446], radius=10, fill=(255, 206, 92))
    text_at(d, (190, 400), "立即选购", F(28), (40, 34, 24), anchor="ma")
    text_at(d, (330, 400), "全屋灯光方案", F(26), (214, 210, 226), anchor="lm")
    return im


SAMPLES = [
    ("demo_param_card", sample_param_card),
    ("demo_brace_title", sample_brace_title),
    ("demo_compare", sample_compare),
    ("demo_promo_banner", sample_promo_banner),
    ("demo_spec_table", sample_spec_table),
    ("demo_white_product", sample_white_product),
    ("demo_detail_long", sample_detail_long),
    ("demo_wide_banner", sample_wide_banner),
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
