# -*- coding: utf-8 -*-
"""layout-restore —— 参考图 → 可编辑源件包（像素级可验收）

一句话
    把一张**参考图**拆成「照片层 / 矢量结构层 / 活字文字层」，
    渲染成**可编辑的 HTML+CSS+SVG 源件包**，并用像素指标验收。

三层模型（核心思想，见 docs/01_三层模型.md）
    L1 照片层 plate.png    原图，挖掉待重建文字后修补
    L2 矢量结构层 rects/lines  色块、线条 —— 改色改宽都是改一个数
    L3 文字层 SVG <text>   活字，能改文案/改价

命令行
    layout-restore build --src ref.jpg --key demo
    layout-restore verify --pack out/demo
    layout-restore overview --out overview.png --packs out
"""
__version__ = "0.1.0"
__all__ = ["__version__"]
