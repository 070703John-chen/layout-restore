# -*- coding: utf-8 -*-
"""引擎修复回归自测：把 7 处已验证修复钉成断言。

为什么必须有这个测试
    这些修复全是**静默**的 —— 改错了不会报错、不会崩，只会让还原变差：
      · 通道写反 → 底板出现蓝色字形残影（看着像「画面脏了」）
      · hex 按 BGR 解析 → 寻优判据退化，字重/描边永远选最细
      · 美术块不抠字 → 同一句话两层重影
      · clipPath 副本没一起改 → 同一句话两层错位重影
      · 抗锯齿晕圈被当描边 → 描边寻优挑最大宽度 → 字糊成一块读不出来
    以前全靠「跑出来看着还行」才发现问题 ⇒ 必须有断言把它们钉死，
    否则下一次重构就会把它们悄悄改回去。

用法
    python tests/test_rebuild_fixes.py

退出码
    0 = 全部修复符合预期
    1 = 有修复被改回去了（必须重做）
"""
import os
import re
import sys
import shutil
import tempfile

import numpy as np
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from layout_restore.rebuild import Rebuild          # noqa: E402


# ------------------------------------------------------------------ 工具
def _save(im, path):
    Image.fromarray(im).save(path)
    return path


def _new_rb(spec, tmp):
    out = os.path.join(tmp, spec["key"])
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    return Rebuild(spec, out)


def _blank(tmp, name):
    """一张真实存在的小图（Rebuild 构造时会打开 spec["src"]）。"""
    p = os.path.join(tmp, name)
    _save(np.full((8, 8, 3), 250, np.uint8), p)
    return p


def _near_white(arr):
    """近白像素数（R,G,B 都高）。"""
    a = arr.astype(int)
    return int(((a[:, :, 0] > 200) & (a[:, :, 1] > 200) & (a[:, :, 2] > 200)).sum())


# ------------------------------------------------------------------ 1 归美术层
def test_art_cover(tmp):
    """覆盖 ≥50% 的文字归美术素材层；不足 50% 的仍做活字并把那一小块抠掉。"""
    W, H = 200, 120
    im = np.full((H, W, 3), 250, np.uint8)
    im[0:40, :] = (30, 30, 40)             # 深色横幅 = 美术块 blk0 覆盖的区域
    im[8:28, 10:90] = (255, 255, 255)      # t0 的字（整块在美术块内）
    im[14:30, 102:118] = (255, 255, 255)   # t2 的字（只有左半在美术块内）
    src = _save(im, os.path.join(tmp, "art.png"))

    spec = {
        "key": "t_art", "name": "art layer", "src": src, "crop": [0, 0, 0, 0],
        "art": [["blk0", [0, 0, 120, 40]]],
        "text": [
            {"id": "t0", "text": "标题", "box": [10, 6, 90, 30],
             "base": 28, "size": 22, "weight": 700, "fill": "#FFFFFF",
             "mask_color": "#FFFFFF", "pad": 0},
            {"id": "t1", "text": "正文", "box": [10, 60, 90, 80],
             "base": 78, "size": 18, "weight": 400, "fill": "#333333",
             "mask_color": "#333333", "pad": 0},
            {"id": "t2", "text": "小字", "box": [100, 12, 160, 32],
             "base": 30, "size": 16, "weight": 400, "fill": "#FFFFFF",
             "mask_color": "#FFFFFF", "pad": 0},
        ],
    }
    rb = _new_rb(spec, tmp)
    cover = rb._art_cover()
    assert cover[0] == 1.0, "t0 整块在美术块内，覆盖率应 = 1.0，实得 %s" % cover[0]
    assert cover[1] == 0.0, "t1 不在美术块内，覆盖率应 = 0，实得 %s" % cover[1]
    assert 0.2 < cover[2] < 0.5, \
        "t2 只被压了一角，覆盖率应 <0.5（否则被误判成整块丢弃），实得 %s" % cover[2]

    rb.make_plate()
    rb.cut_art()
    txt = spec["text"]
    assert txt[0].get("art_covered"), "t0 覆盖率 100% → 必须归美术层（不画活字）"
    assert not txt[1].get("art_covered"), "t1 覆盖率 0 → 不该归美术层"
    assert not txt[2].get("art_covered"), "t2 覆盖率 <50% → 不该归美术层"

    a0 = os.path.join(rb.out, "assets", "t0_art.png")
    assert os.path.exists(a0), "归美术层的文字必须生成原图裁切素材"
    crop = np.asarray(Image.open(os.path.join(rb.out, "assets", "blk0.png")).convert("RGB"))
    # t0 归美术层 → 块里**保留**原图文字
    w_t0 = _near_white(crop[8:28, 10:90])
    assert w_t0 > 100, "归美术层的文字在美术块里必须保留原图像素，实得 %d px" % w_t0
    # t2 仍做活字 → 块里那一小块文字必须被**抠掉**
    w_t2 = _near_white(crop[14:30, 102:118])
    assert w_t2 < 20, \
        "仍在做活字的文字必须从美术块里抠掉（否则半截重影），实得 %d px 近白" % w_t2

    html = rb.build_html()
    assert "assets/t0_art.png" in html, "归美术层的文字要用 <img> 贴原图裁切"
    assert not re.search(r"<text[^>]*>标题</text>", html), \
        "归美术层的文字不能同时画活字（会重影）"
    assert re.search(r"<text[^>]*>正文</text>", html), "未覆盖的文字必须仍是活字"
    assert re.search(r"<text[^>]*>小字</text>", html), "部分覆盖的文字必须仍是活字"
    return "归美术层 1 个（t0 cov=1.0），抠字 1 处（t2 cov=%.2f）" % cover[2]


# ------------------------------------------------------------------ 2 RGB/BGR
def test_plate_channel(tmp):
    """make_plate 的多项式回填必须先 RGB→BGR，否则红底上的字区变蓝。"""
    W, H = 160, 100
    yy = np.linspace(0, 1, H)[:, None]
    base = np.zeros((H, W, 3), np.float64)
    base[:, :, 0] = 210 + 20 * yy      # R
    base[:, :, 1] = 50 + 20 * yy       # G
    base[:, :, 2] = 40 + 15 * yy       # B
    im = base.astype(np.uint8)
    im[40:60, 40:120] = (25, 25, 30)   # 粗笔画「文字」
    src = _save(im, os.path.join(tmp, "chan.png"))

    spec = {
        "key": "t_chan", "name": "channel order", "src": src, "crop": [0, 0, 0, 0],
        "art": [],
        "text": [{"id": "t0", "text": "字", "box": [40, 40, 120, 60],
                  "base": 58, "size": 20, "weight": 700, "fill": "#191920",
                  "mask_color": "#191920", "pad": 0, "grow": 1, "tol": 78}],
    }
    rb = _new_rb(spec, tmp)
    rb.make_plate()
    plate = np.asarray(Image.open(os.path.join(rb.out, "assets", "plate.png")).convert("RGB"))
    reg = plate[40:60, 40:120].astype(int)
    mr, mg, mb = reg[:, :, 0].mean(), reg[:, :, 1].mean(), reg[:, :, 2].mean()
    assert mr > mb, \
        "字区 R 均值(%.1f) 必须大于 B 均值(%.1f) —— 通道被写反了（R↔B 互换）" % (mr, mb)
    assert mr > 190, "字区 R 均值(%.1f) 应接近原渐变(≈220)，说明多项式回填没生效" % mr
    return "字区 RGB 均值 = (%.0f, %.0f, %.0f)（原渐变 ≈ (220, 60, 47)）" % (mr, mg, mb)


# ------------------------------------------------------------------ 3 hex 按 RGB
def test_ink_stats_rgb(tmp):
    """_ink_stats 的 hex ref 必须按 RGB 解析（BGR 会让 o_area 恒为 0）。"""
    spec = {"key": "t_ink", "name": "ink", "src": _blank(tmp, "blank.png"),
            "crop": [0, 0, 0, 0], "art": [], "text": []}
    rb = _new_rb(spec, tmp)

    pix = np.array([[196, 9, 12], [196, 9, 12], [196, 9, 12]], np.int32)
    area, _ = rb._ink_stats(pix, np.array([250, 250, 250]), ref="#C4090C")
    assert area == 3, \
        "饱和红 #C4090C 必须被认成同色像素（面积 3），实得 %d —— hex 被按 BGR 解析了" % area

    # 二分开关：LEGACY_INK=1 → 退回 BGR → 掩膜应为空
    rb._legacy_ink = True
    area_l, _ = rb._ink_stats(pix, np.array([250, 250, 250]), ref="#C4090C")
    assert area_l == 0, "LEGACY_INK=1 应复现老行为（面积 0），实得 %d" % area_l
    rb._legacy_ink = False
    return "RGB 解析 → 面积 3；LEGACY_INK=1 → 面积 0（BGR 老行为）"


# ------------------------------------------------------------------ 4 clipPath 组
def test_set_attr_group(tmp):
    """同框多色字：base + 各 clip-path 副本必须一起改，否则两层错位重影。"""
    spec = {"key": "t_span", "name": "spans", "src": _blank(tmp, "blank.png"),
            "crop": [0, 0, 0, 0], "art": [], "text": []}
    rb = _new_rb(spec, tmp)

    inner = "整句彩色高亮"
    html = (
        '<text x="10" y="40" font-size="30" font-weight="700" fill="#392307">%s</text>\n'
        '<text x="10" y="40" font-size="30" font-weight="700" fill="#176B16" '
        'clip-path="url(#cp0_0)">%s</text>\n'
        '<text x="10" y="40" font-size="30" font-weight="700" fill="#392307" '
        'clip-path="url(#cp0_1)">%s</text>' % (inner, inner, inner)
    )
    out = rb._set_attr(html, inner, "font-size", 42)
    sizes = re.findall(r'font-size="(\d+)"', out)
    assert sizes == ["42", "42", "42"], \
        "同一 clipPath 分组的 3 个副本必须一起改字号，实得 %s" % sizes

    # 不带 clip-path 的普通文字：只改那一个
    plain = '<text x="1" y="2" font-size="30" fill="#000000">普通</text>'
    o2 = rb._set_attr(plain, "普通", "font-size", 44)
    assert 'font-size="44"' in o2 and o2.count('font-size="30"') == 0, "普通文字改字号失败"
    return "3 个副本字号全部同步为 42"


# ------------------------------------------------------------------ 5 存盘状态
def test_make_plate_state(tmp):
    """make_plate 末尾必须存 self.P / self.text_mask / self.elem_masks。"""
    im = np.full((60, 60, 3), 250, np.uint8)
    im[20:30, 20:40] = (30, 30, 40)
    src = _save(im, os.path.join(tmp, "state.png"))
    spec = {
        "key": "t_state", "name": "state", "src": src, "crop": [0, 0, 0, 0],
        "art": [],
        "text": [{"id": "t0", "text": "字", "box": [20, 20, 40, 30],
                  "base": 29, "size": 10, "weight": 700, "fill": "#1E1E28",
                  "mask_color": "#1E1E28", "pad": 0}],
    }
    rb = _new_rb(spec, tmp)
    rb.make_plate()
    assert getattr(rb, "P", None) is not None, "make_plate 未存 self.P（底板）"
    assert getattr(rb, "text_mask", None) is not None, "make_plate 未存 self.text_mask"
    elems = getattr(rb, "elem_masks", None)
    assert isinstance(elems, list) and len(elems) == 1, \
        "make_plate 未存 self.elem_masks（逐元素掩膜）"
    assert rb.P.shape == (60, 60, 3), "self.P 应是 RGB 底板数组"
    return "self.P / text_mask / elem_masks 均已存下"


# ------------------------------------------------------------------ 6 二分开关
def test_env_switches(tmp):
    """3 个二分开关必须真能读到（定位问题来源用）。"""
    names = ["LAYOUT_RESTORE_NO_ARTMASK", "LAYOUT_RESTORE_LEGACY_INK",
             "LAYOUT_RESTORE_DIAG_METRIC"]
    spec = {"key": "t_env", "name": "env", "src": _blank(tmp, "blank.png"),
            "crop": [0, 0, 0, 0], "art": [], "text": []}
    rb = _new_rb(spec, tmp)
    for n in names:
        attr = "_" + n.replace("LAYOUT_RESTORE_", "").lower()
        assert hasattr(rb, attr), "缺少开关 %s（属性 %s）" % (n, attr)
    assert rb._no_artmask is False and rb._legacy_ink is False and rb._diag_metric is False
    os.environ["LAYOUT_RESTORE_NO_ARTMASK"] = "1"
    os.environ["LAYOUT_RESTORE_LEGACY_INK"] = "1"
    os.environ["LAYOUT_RESTORE_DIAG_METRIC"] = "1"
    try:
        rb2 = _new_rb(spec, tmp)
        assert rb2._no_artmask and rb2._legacy_ink and rb2._diag_metric, \
            "环境变量开关没有生效"
    finally:
        for n in names:
            os.environ.pop(n, None)
    return "3 个开关读写均生效"


# ------------------------------------------------------------------ 7 假描边
def test_false_stroke(tmp):
    """抗锯齿晕圈不能被当成描边；同色描边必须丢（否则字被撑成糊块）。

    实测事故（2026-11-09）：细体白字在米色底上，晕圈被探针判成「第二色 = 描边」，
    描边宽度寻优又挑了最大值 12px → 22~36px 的字被描边糊成一块，**整行读不出来**。
    """
    from layout_restore import probe_layers as PL

    bg = "#DCD3C7"
    assert PL._is_blend_color("#F8F6F3", "#FCFAF9", bg), \
        "白字的抗锯齿晕圈必须判成混色（不是描边）"
    assert PL._is_blend_color("#736A5D", "#72685C", bg), \
        "近色晕圈必须判成混色"
    assert not PL._is_blend_color("#3A2F28", "#FCFAF9", bg), \
        "真描边色（另一个色相）不能被判成混色"

    # (b) 渲染层兜底：fill == stroke 时不发 stroke
    im = np.full((80, 120, 3), 250, np.uint8)
    src = _save(im, os.path.join(tmp, "stroke.png"))
    spec = {
        "key": "t_stroke", "name": "stroke", "src": src, "crop": [0, 0, 0, 0],
        "art": [],
        "text": [{"id": "t0", "text": "同色描边", "box": [10, 10, 90, 30],
                  "base": 28, "size": 22, "weight": 300, "fill": "#7B7165",
                  "stroke": "#7B7165", "stroke_w": 12, "mask_color": "#7B7165",
                  "pad": 0}],
    }
    rb = _new_rb(spec, tmp)
    rb.make_plate()
    html = rb.build_html()
    assert "stroke=" not in html, \
        "fill==stroke 的描边必须不发（会把字撑胖、字形糊成一块）"

    # (c) 描边打分要排除填充色本身，否则「描边越宽 → 得分越高」永远挑最大宽度
    pix = np.array([[119, 106, 94]] * 3 + [[115, 104, 90]] * 3, np.int32)
    area_all, _ = rb._ink_stats(pix, np.array([220, 211, 199]), ref="#7B7165")
    area_ex, _ = rb._ink_stats(pix, np.array([220, 211, 199]), ref="#7B7165",
                               exclude="#7B7165")
    assert area_all == 6, "不加 exclude 时近色像素都算描边色，实得 %d" % area_all
    assert area_ex == 0, "排除填充色后不该剩下描边色像素，实得 %d" % area_ex
    return "混色判据 / 同色描边不发 / 描边打分排除填充色 三条都符合预期"


# ------------------------------------------------------------------ 8 寻优后描边复核
def test_normalize_strokes(tmp):
    """寻优把字色改回白色后，那条「白字上的白描边」必须被摘掉。

    实测事故（demo_param_card 横幅）：文字框右侧压着一个深色方块 →
    探针把方块色当成字色、把**真正的白字**降级成「第二色 = 描边」→
    寻优把字色改回白色 → 12px 白描边把整行糊成白块。
    ⇒ 描边复核必须发生在**寻优之后**，用最终字色重判。
    """
    im = np.full((80, 120, 3), 250, np.uint8)
    src = _save(im, os.path.join(tmp, "norm.png"))
    spec = {
        "key": "t_norm", "name": "norm", "src": src, "crop": [0, 0, 0, 0],
        "art": [],
        "text": [{"id": "t0", "text": "白字", "box": [10, 10, 90, 30],
                  "base": 28, "size": 22, "weight": 300, "fill": "#FCFAF9",
                  "stroke": "#F8F6F3", "stroke_w": 12, "bg": "#D1C3B0",
                  "mask_color": "#FCFAF9", "pad": 0}],
    }
    rb = _new_rb(spec, tmp)
    rb.make_plate()
    html = rb.build_html()
    assert 'stroke-width="12"' in html, "前置条件：html 里应先带着这条假描边"
    open(os.path.join(rb.out, "index.html"), "w", encoding="utf-8").write(html)

    n = rb.normalize_strokes()
    assert n == 1, "应摘掉 1 处假描边，实得 %d" % n
    html2 = open(os.path.join(rb.out, "index.html"), encoding="utf-8").read()
    assert "stroke-width" not in html2, "假描边必须从 index.html 里摘掉"
    assert "stroke=" not in html2, "stroke 属性本身也必须摘掉"
    assert rb.spec["text"][0].get("stroke") is None, "spec 里的 stroke 也要清掉"
    return "白字白描边被摘掉（1 处）"


def test_translate_art(tmp):
    """局部 patch 渲染里，**所有** layer 图都必须跟着平移。

    实测事故（2026-11-09，demo_param_card / 额定电压）：
        美术裁片 t00_art 落在 (38,30)，而寻优 region 是 (40,702)-(146,739)
        → patch 里它跑到 cell 的右下角（region 完全无关的位置）
        → cell 的 dmax 从 91（字的对比度）被抬到 181（深色头图 #1A162C）
        → 阈值 thr = max(55, 0.55×181) = 99 > 91
        → **字自己被排除在墨量统计之外**，统计到的只剩那块深色方块
        → 方块被越粗的字盖得越多 ⇒ 墨量随字重**递减**
        → 字重打分等于在给「标题色块」打分 ⇒ 低对比度标签被选成 700/900。
    ⇒ per-text 美术素材（t00_art 等，不在 spec["art"] 里）原来**原样返回**，
      位置完全没平移 —— 必须按它自己的 left/top 一起平移。
    """
    im = np.full((80, 120, 3), 250, np.uint8)
    src = _save(im, os.path.join(tmp, "trans.png"))
    spec = {
        "key": "t_trans", "name": "trans", "src": src, "crop": [0, 0, 0, 0],
        "art": [],
        "text": [{"id": "t0", "text": "文字", "box": [10, 10, 90, 30],
                  "base": 28, "size": 22, "weight": 300, "fill": "#333333",
                  "bg": "#FAFAFA", "mask_color": "#333333", "pad": 0}],
    }
    rb = _new_rb(spec, tmp)
    rb.make_plate()
    html = rb.build_html()
    # 塞一个 per-text 美术裁片（故意**不**登记进 spec["art"]）
    html = html.replace(
        '<img class="layer" src="assets/plate.png"',
        '<img class="layer" src="assets/t00_art.png" style="left:38px;top:30px">'
        '<img class="layer" src="assets/plate.png"', 1)
    assert 'src="assets/t00_art.png"' in html, "前置条件：html 里应有这张美术裁片"

    body = rb._split_html(html)[1]
    out = rb._translate_body(body, 40, 702)
    assert 'src="assets/t00_art.png" style="left:-2px;top:-672px"' in out, \
        "per-text 美术裁片必须按 (-x0,-y0) 平移（38-40=-2, 30-702=-672）"
    assert 'src="assets/plate.png" style="left:-40px;top:-702px"' in out, \
        "照片层也必须平移"
    return "per-text 美术裁片随 region 一起平移"


def test_ink_threshold_relative(tmp):
    """墨量阈值必须是**相对量** —— 同样的字形，只换更浅的字色，墨量不能变。

    实测事故（2026-11-09，demo_param_card / 额定电压）：
        原图字色 #564E44（离底色 121）vs 候选字色 #746A5E（离底色 91）
        旧的 `thr = max(55, 0.55*dmax)` 里那个**绝对下限 55** 让两边的
        「覆盖率口径」不同（54.5% vs 60.5%）
        ⇒ 候选墨量被**系统性低估** ⇒ 字重寻优只能靠加粗去凑数
        ⇒ 原图是细体(Thin)却被判成 200/700。
    ⇒ 阈值改成 `max(12, 0.55*dmax)` 后，同样的覆盖率在两种字色下必须数出同样的墨量。
    """
    bg = np.array([207, 193, 174], np.int32)
    alpha = np.array([0.0, 0.3, 0.58, 0.8, 1.0, 0.4, 0.9], np.float32)
    spec = {
        "key": "t_thr", "name": "thr", "src": _blank(tmp, "thr.png"),
        "crop": [0, 0, 0, 0], "art": [], "text": [],
    }
    rb = _new_rb(spec, tmp)
    areas = []
    for fill in ([86, 78, 68], [116, 106, 94]):      # 深字色 / 浅字色
        f = np.array(fill, np.float32)
        pix = bg.astype(np.float32) + alpha[:, None] * (f - bg.astype(np.float32))
        area, _ = rb._ink_stats(pix.astype(np.uint8), bg)
        areas.append(int(area))
    assert areas[0] == areas[1], \
        "同样的覆盖率在不同字色下墨量必须一致，实得 %s（旧的绝对下限 55 会让它们不等）" % areas
    assert areas[0] == 4, "覆盖率 >55%% 的像素应有 4 个，实得 %d" % areas[0]
    return "墨量阈值相对化，深/浅字色数出同样墨量（%d）" % areas[0]


def test_px_assets_no_stale(tmp):
    """像素层素材**不能留陈旧文件**在交付包里。

    实测事故（2026-11-09，CI「像素层真的生效了」这一步红了）：
        标记的降级处数 = 22，但交付包 assets 里躺着 **23** 张 px_*.png
        ⇒ assets/ 目录从不清空 ⇒ 上一轮降级过、这一轮不用降级的元素，
          它的 px_xx.png 变成**没人引用的陈旧文件**，跟着交付包一起给了客户。
    ⇒ 生成像素层素材前，先把上一轮的 px_*.png 清掉。
    """
    im = np.full((60, 90, 3), 245, np.uint8)
    src = _save(im, os.path.join(tmp, "pxstale.png"))
    spec = {
        "key": "t_px", "name": "px", "src": src, "crop": [0, 0, 0, 0],
        "art": [],
        "text": [{"id": "t0", "text": "像素", "box": [10, 10, 60, 30],
                  "base": 28, "size": 22, "weight": 300, "fill": "#333333",
                  "bg": "#FAFAFA", "mask_color": "#333333", "pad": 0,
                  "px": True, "px_asset": "px_t0", "px_pad": 2}],
    }
    rb = _new_rb(spec, tmp)
    rb.make_plate()
    html = rb.build_html()
    open(os.path.join(rb.out, "index.html"), "w", encoding="utf-8").write(html)

    stale = os.path.join(rb.out, "assets", "px_t99.png")
    _save(np.full((10, 10, 3), 1, np.uint8), stale)
    assert os.path.isfile(stale), "前置条件：先放一张陈旧的 px 素材"

    rb.make_px()
    assert not os.path.isfile(stale), "陈旧的 px 素材必须被清掉（不能混进交付包）"
    cur = os.path.join(rb.out, "assets", "px_t0.png")
    assert os.path.isfile(cur), "本轮的 px 素材必须生成"
    return "陈旧 px 素材被清理（1 张残留已清）"


# ------------------------------------------------------------------ main
CASES = [
    ("1 归美术层（覆盖 >=50% 判定）", test_art_cover),
    ("2 make_plate 多项式回填 RGB/BGR", test_plate_channel),
    ("3 _ink_stats 的 hex 按 RGB 解析", test_ink_stats_rgb),
    ("4 多色字 clipPath 副本一起改", test_set_attr_group),
    ("5 make_plate 存 self.P / elem_masks", test_make_plate_state),
    ("6 三个二分开关可用", test_env_switches),
    ("7 假描边（晕圈/同色/打分）", test_false_stroke),
    ("8 寻优后描边复核", test_normalize_strokes),
    ("9 局部渲染平移所有图层", test_translate_art),
    ("10 墨量阈值相对化", test_ink_threshold_relative),
    ("11 像素层素材不留陈旧文件", test_px_assets_no_stale),
]


def main():
    tmp = tempfile.mkdtemp(prefix="lr_fixes_")
    fails = []
    try:
        for name, fn in CASES:
            try:
                info = fn(tmp)
                print("[OK]   %-34s %s" % (name, info))
            except AssertionError as e:
                print("[FAIL] %-34s %s" % (name, e))
                fails.append(name)
            except Exception as e:
                print("[ERR]  %-34s %r" % (name, e))
                fails.append(name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fails:
        print("引擎修复回归自测失败：%s" % "；".join(fails))
        return 1
    print("引擎修复回归自测全部通过 [OK]（%d 项）" % len(CASES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
