# -*- coding: utf-8 -*-
"""配置层：**代码写「怎么判」，配置写「判什么·在哪」**。

只有一份配置（config.yaml），所有子命令共用。
没有配置文件时用这里的默认值 —— 配置是**加法不是替换**。
"""
import os

DEFAULTS = {
    "build": {
        # 探针取字色的方式：majority = 框内最大簇当底色（电商图必需）
        "ink_mode": "majority",
        # OCR 置信度下限
        "min_conf": 0.45,
        # 族级配方：强制字体（电商图中文默认黑体，不是宋体）
        "cjk_font": "Noto Sans SC",
        "latin_font": "Noto Sans SC",
        # 区域差异率 > 此值(%) → 该文字降级成像素层
        "px_threshold": 18.0,
        # 并行进程数
        "jobs": 4,
    },
    "verify": {
        # 与 rebuild 记录的差异率允许的偏差（百分点）
        "tol": 0.15,
    },
    "paths": {
        "refs": "refs",
        "specs": "specs",
        "out": "out",
        "work": ".work",
    },
}


def _read_yaml(path):
    try:
        import yaml
    except ImportError:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return None


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None):
    """读配置。优先 <cwd>/config.yaml，其次 <包的上级目录>/config.yaml。"""
    cands = []
    if path:
        cands.append(path)
    cands.append(os.path.join(os.getcwd(), "config.yaml"))
    cands.append(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "config.yaml"))
    for c in cands:
        if c and os.path.exists(c):
            data = _read_yaml(c)
            if data is not None:
                return _deep_merge(DEFAULTS, data), c
    return dict(DEFAULTS), None


def get(cfg, dotted, default=None):
    cur = cfg or {}
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur if cur is not None else default


def path_of(cfg, key, root=None):
    rel = get(cfg, "paths." + key, key)
    base = root or os.getcwd()
    return os.path.normpath(os.path.join(base, rel))
