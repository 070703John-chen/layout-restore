# -*- coding: utf-8 -*-
"""引擎修复回归自测：把 5 处已验证修复钉成断言。

为什么必须有这个测试
    这 5 处修复全是**静默**的 —— 改错了不会报错、不会崩，只会让还原变差：
      · 通道写反 → 底板出现蓝色字形残影（看着像「画面脏了」）
      · hex 按 BGR 解析 → 寻优判据退化，字重/描边永远选最细
      · 美术块不抠字 → 同一句话两层重影
      · clipPath 副本没一起改 → 同一句话两层错位重影
    以前全靠「跑出来看着还行」才发现问题 ⇒ 必须有断言把它们钉死，
    否则下一次重构就会把它们悄悄改回去。

用法
    python tests/test_rebuild_fixes.py

退出码
    0 = 5 处修复全部符合预期
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


# ------------------------------------------------------------------ main
CASES = [
    ("1 归美术层（覆盖 >=50% 判定）", test_art_cover),
    ("2 make_plate 多项式回填 RGB/BGR", test_plate_channel),
    ("3 _ink_stats 的 hex 按 RGB 解析", test_ink_stats_rgb),
    ("4 多色字 clipPath 副本一起改", test_set_attr_group),
    ("5 make_plate 存 self.P / elem_masks", test_make_plate_state),
    ("6 三个二分开关可用", test_env_switches),
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
