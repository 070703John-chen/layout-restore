# 贡献指南

## 这个项目想解决什么

把一张**参考图**变成**可编辑的源件包**，并且**像素级可验收**。

不是「做一个通用的视觉引擎」，而是**把版式还原这件事工程化**：
判据写清楚、坑写下来、指标可复现。

## 提交前必做

```bash
# ① 不能留任何本机绝对路径 / 私有品牌
python tests/check_no_private_paths.py     # 期望输出：残留问题 0 处

# ② 示例图必须还能程序生成
python examples/make_samples.py --out examples/samples

# ③ 端到端还能跑通，且指标不退化
python -m layout_restore.cli build --src examples/samples/demo_param_card.png --key demo_param_card
python -m layout_restore.cli verify --pack out/demo_param_card
```

## 分层铁律（改代码前先看）

> **代码写「怎么判」· 配置写「判什么·在哪」· 状态板写「到哪了」。**

- 阈值、路径、字体 → `config.yaml`，**不要**写死在 `.py` 里
- 探针 / 寻优 / 取色判据 → 改 `.py`
- 「怎么判」变了 → 必须**全量重跑**示例图，比对 `_report.json` 指标

## 新判据怎么加（重要）

**新判据先当「仲裁者」，不要当主力。**

踩过的坑：把「连通块厚度」当主判据去取字色，结果照片底上的字全部取浅
（高光纹理混进来了）。正确用法是只在**老路明显失效**时才让它接管。

验收方式：

1. 逐条比对新旧取色结果（`_work/probe/_probe_*.json`）
2. **端到端重跑**比 `_report.json` 指标 —— 新旧 spec 的颜色**不能直接比**
   （旧的是寻优后回写的，新探针给的是寻优前原值）

## 素材版权

- **不要**提交任何第三方素材（电商平台的图、别人的设计稿）
- 示例图必须由 `examples/make_samples.py` 程序生成
- 字体只放 SIL OFL / 明确可商用的，且在 `LICENSE` 里说明

## 代码风格

- Python 3.9+，`# -*- coding: utf-8 -*-`
- 中文注释，**每个非显然的判据都要写清「为什么」和「踩过什么坑」**
- 不要用 `print` 做主要输出，CLI 用 `argparse`
- 子进程输出**直接写日志文件**，不要走 `PIPE`
  （Windows 管道缓冲约 64KB，日志一大就写满 → 子进程阻塞 → 死锁）
