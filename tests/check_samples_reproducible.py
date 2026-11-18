#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""示例图可复现性检查（跨平台 · 像素级）

为什么不用 `git diff --exit-code examples/samples`
    字节级断言在跨平台时会**假失败**。同样的像素，字节可以完全不同：

      1. PNG 压缩流不同 —— zlib / libpng 版本不同，同样的像素编码出的字节不同
      2. 栅格化不同 —— FreeType 版本与 hinting 设置不同，抗锯齿的亚像素有微差

    这两条都不是 bug，是"换了一台机器"。示例图是给人看的，
    不是给人比对 hash 的，所以断言应该落在**像素**上。

    同平台（Windows ↔ Windows）下本仓库的示例图是**逐字节一致**的
    （本机实测 8/8 maxdiff=0），报告里会显式标出这一条。

判定标准（三条都过）
    1. 尺寸全等 —— 版式变了尺寸一定会变（硬门槛）
    2. 像素一致率 >= 98%
    3. 平均绝对差 <= 1.2

阈值是怎么定的
    ubuntu-latest 实测（FreeType 版本与 Windows 不同）：
        一致率  98.735% ~ 99.934%
        平均差  0.061 ~ 0.897
        最大差  210 ~ 233
    差异形态：**集中在字形边缘**，且单像素可能从墨色直接翻到纸色 ——
    这是 FreeType hinting 的亚像素抖动（同一根竖笔画落在像素边界另一侧），
    不是渲染错误。同平台（Windows ↔ Windows）实测 8/8 逐字节一致。
    真回归（版式错、字号错、字体实例错）会让尺寸变、或平均差跳到 5 以上，
    上面两条阈值足以拦住。

用法
    python tests/check_samples_reproducible.py
退出码
    0 = 通过    1 = 不通过
"""

import hashlib
import os
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAMPLES = os.path.join(ROOT, "examples", "samples")
MAKER = os.path.join(ROOT, "examples", "make_samples.py")

# 判定阈值（依据见文件头「阈值是怎么定的」）
MIN_IDENTICAL_RATIO = 0.98    # 实测最差 98.735%，留 0.27% 余量
MAX_MEAN_ABS_DIFF = 1.2       # 实测最差 0.897，留余量


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    from PIL import Image
    import numpy as np

    if not os.path.isdir(SAMPLES):
        print("FAIL: 找不到 examples/samples/")
        return 1
    if not os.path.isfile(MAKER):
        print("FAIL: 找不到 examples/make_samples.py")
        return 1

    repo_pngs = sorted(f for f in os.listdir(SAMPLES) if f.lower().endswith(".png"))
    if not repo_pngs:
        print("FAIL: examples/samples/ 里没有 png")
        return 1

    tmp = tempfile.mkdtemp(prefix="cvs_samples_")
    print("重新生成示例图 → %s" % tmp)
    r = subprocess.run(
        [sys.executable, MAKER, "--out", tmp],
        cwd=ROOT, capture_output=True,
        # 不用 text=True：Windows 本机默认 GBK，子进程输出是 UTF-8，
        # 解码会在读取线程里抛 UnicodeDecodeError。显式指定更稳。
        encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        print("FAIL: make_samples.py 退出码 %d" % r.returncode)
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        return 1

    made = sorted(f for f in os.listdir(tmp) if f.lower().endswith(".png"))
    missing = [f for f in repo_pngs if f not in made]
    extra = [f for f in made if f not in repo_pngs]
    if missing:
        print("FAIL: 脚本没有生成这些示例图（仓库里有、脚本没产出）：%s" % ", ".join(missing))
        return 1
    if extra:
        print("FAIL: 脚本多生成了仓库里没有的示例图：%s" % ", ".join(extra))
        return 1

    print()
    print("%-24s %-11s %-11s %9s %9s %9s %s" % (
        "示例图", "我的尺寸", "基准尺寸", "一致率%", "平均差", "最大差", "判定"))
    print("-" * 96)

    all_byte_identical = True
    all_pixel_identical = True
    failures = []

    for name in repo_pngs:
        a_path = os.path.join(tmp, name)
        b_path = os.path.join(SAMPLES, name)

        a = Image.open(a_path).convert("RGB")
        b = Image.open(b_path).convert("RGB")

        if a.size != b.size:
            print("%-24s %-11s %-11s %9s %9s %9s %s" % (
                name, "%dx%d" % a.size, "%dx%d" % b.size, "-", "-", "-", "FAIL 尺寸"))
            failures.append("%s 尺寸不同 %s vs %s" % (name, a.size, b.size))
            continue

        arr_a = np.asarray(a, dtype=np.int16)
        arr_b = np.asarray(b, dtype=np.int16)
        diff = np.abs(arr_a - arr_b)
        identical_ratio = float((diff == 0).all(axis=2).mean())
        mean_abs = float(diff.mean())
        max_abs = int(diff.max())

        byte_same = sha(a_path) == sha(b_path)
        if not byte_same:
            all_byte_identical = False
        if identical_ratio < 1.0:
            all_pixel_identical = False

        ok = identical_ratio >= MIN_IDENTICAL_RATIO and mean_abs <= MAX_MEAN_ABS_DIFF
        if not ok:
            failures.append(
                "%s 像素不一致（一致率 %.3f%% / 平均差 %.3f）" % (name, identical_ratio * 100, mean_abs))

        print("%-24s %-11s %-11s %8.3f%% %9.4f %9d %s" % (
            name, "%dx%d" % a.size, "%dx%d" % b.size,
            identical_ratio * 100, mean_abs, max_abs,
            "OK" if ok else "FAIL"))

    print()
    if all_byte_identical:
        print("字节级：全部逐字节一致（同平台可复现）")
    elif all_pixel_identical:
        print("字节级：存在差异 —— 但像素完全一致，是 PNG 压缩流不同"
              "（zlib/libpng 版本差异，不是渲染问题）")
    else:
        print("字节级：存在差异 —— 且像素也有微差，形态为字形边缘的亚像素抖动"
              "（FreeType hinting 跨平台不同；不是版式错误）")
    print("像素级：判定阈值 = 一致率 >= %.1f%% 且 平均差 <= %.2f" % (
        MIN_IDENTICAL_RATIO * 100, MAX_MEAN_ABS_DIFF))
    print()

    if failures:
        print("FAIL：%d 项不符" % len(failures))
        for f in failures:
            print("  - " + f)
        return 1

    print("PASS：%d 张示例图与仓库基准一致" % len(repo_pngs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
