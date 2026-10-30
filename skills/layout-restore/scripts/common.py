# -*- coding: utf-8 -*-
"""layout-restore 批量流水线 · 共享层

分层铁律（别破坏）：
    代码写「怎么判」  →  探针 / 矢量检测 / 寻优 / 取色判据
    配置写「判什么·在哪」 →  config.yaml（路径 / 阈值 / 选片策略 / 达标口径）
    状态板写「到哪了」 →  runs/<run_id>/

所有脚本共用本模块：配置读取、路径解析、环境注入、指标收集。
"""
import os
import sys
import json
import glob
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
CFG_PATH = os.path.join(SKILL, "config.yaml")
CFG_LOCAL = os.path.join(SKILL, "config.local.yaml")

# 批次 profile：同一套 skill 要同时服务多个批次（不同原图库 / 不同工程根）时，
# 用 `config.local.<profile>.yaml` 隔离，避免反复改同一个配置文件把上一批搞乱。
# 用法：环境变量 LAYOUT_RESTORE_PROFILE=multicat
PROFILE_ENV = "LAYOUT_RESTORE_PROFILE"


def profile_name():
    return (os.environ.get(PROFILE_ENV) or "").strip()


def local_cfg_path(profile=None):
    """本机覆盖配置路径。指定 profile → config.local.<profile>.yaml。"""
    p = (profile or profile_name()).strip()
    if p:
        return os.path.join(SKILL, "config.local.%s.yaml" % p)
    return CFG_LOCAL


# ------------------------------------------------------------------ 配置
DEFAULTS = {
    "engine": {"restore": "", "python": ""},
    "paths": {
        "raw": "", "project": "", "specs": "specs", "out": "out",
        "work": "_work", "deliver": "", "features": "", "clusters": "",
        "verify": "",
    },
    "batch": {
        "jobs": 2, "target": 50, "ink_mode": "majority", "min_conf": 0.45,
        "cjk_font": "Noto Sans SC", "px_threshold": 18.0,
        "pick": {"main_all": True, "secondary": 29, "cluster_quota": True},
    },
    "report": {"pass_threshold": 8.0, "real_text_min": 3},
    "site": {"dir": "批量复刻50张_对比站", "thumb": 420, "enabled": True},
}


def _deep(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _deep(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read_yaml(p):
    import yaml
    with open(p, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("配置不是字典：%r" % type(data))
    return data


def load_cfg(path=None, profile=None):
    """读配置。

    加载顺序：DEFAULTS → config.yaml → **config.local.yaml**（后者覆盖前者）。

    ⚠ 解析失败**直接报错退出**，不静默退回默认值 ——
      坏配置静默降级比崩掉更糟：脚本会拿着默认路径跑，
      看起来「在正常跑」但全跑错地方（2026-10-29 踩过：config.yaml 开头
      误写成 Python docstring，YAML 解析失败，doctor 还报「可以跑」）。
    """
    p = path or CFG_PATH
    if not os.path.exists(p):
        sys.stderr.write("[cfg] 找不到配置文件 %s\n" % p)
        raise SystemExit(2)
    try:
        cfg = _read_yaml(p)
    except Exception as e:
        sys.stderr.write("[cfg] 配置解析失败：%r\n  文件：%s\n" % (e, p))
        sys.stderr.write("[cfg] 修好再跑 —— 静默用默认路径比崩更糟\n")
        raise SystemExit(2)
    # 本机覆盖（不入库）
    lp = local_cfg_path(profile)
    if os.path.exists(lp):
        try:
            cfg = _deep(cfg, _read_yaml(lp))
        except Exception as e:
            sys.stderr.write("[cfg] %s 解析失败：%r\n" % (lp, e))
            raise SystemExit(2)
    elif profile:
        sys.stderr.write("[cfg] profile=%s 但找不到 %s\n" % (profile, lp))
        raise SystemExit(2)
    return _deep(DEFAULTS, cfg)


def g(cfg, dotted, default=None):
    cur = cfg
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur if cur is not None else default


def path_of(cfg, key):
    """paths 段 → 绝对路径。相对路径以 paths.project 为基准。

    ⚠ 未配置（空串）时返回 **空串**，不是 "." ——
      返回 "." 会让脚本「拿着当前目录当路径」继续跑，
      结果是跑到一半才发现文件不存在（2026-10-30 修）。
    """
    v = g(cfg, "paths." + key, key)
    if not v:
        return ""
    if os.path.isabs(v):
        return os.path.normpath(v)
    base = g(cfg, "paths.project", os.getcwd())
    if not base:
        return os.path.normpath(v)
    return os.path.normpath(os.path.join(base, v))


def py_exe(cfg):
    return g(cfg, "engine.python", sys.executable)


# ------------------------------------------------------------------ 环境
def child_env(cfg):
    """子进程环境：统一 UTF-8 控制台 + 把路径塞进环境变量。

    ⚠ PYTHONIOENCODING 必须注入：Windows 控制台默认 GBK，
      引擎日志里有中文和 ® 这类符号，GBK 下会 UnicodeEncodeError **整轮崩掉**。
    """
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    e["LAYOUT_RESTORE_ENGINE"] = g(cfg, "engine.restore", "")
    e["LAYOUT_RESTORE_PY"] = py_exe(cfg)
    return e


def run(cmd, cwd=None, env=None, log=None, timeout=None):
    """跑子进程。

    ⚠ 输出**直接写日志文件**，不要走 PIPE。
      Windows 管道缓冲约 64KB，日志一大就写满 → 子进程阻塞等读 →
      父进程等子进程 → **死锁**（2026-10-29 实测踩过，批量跑到一半不动）。
    """
    import subprocess
    if log:
        with open(log, "w", encoding="utf-8") as fh:
            return subprocess.call([str(c) for c in cmd], cwd=cwd, env=env,
                                   stdout=fh, stderr=subprocess.STDOUT,
                                   timeout=timeout)
    return subprocess.call([str(c) for c in cmd], cwd=cwd, env=env,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=timeout)


# ------------------------------------------------------------------ 指标
def metrics_path(cfg, key):
    return os.path.join(path_of(cfg, "out"), key, "_report.json")


def spec_path(cfg, key):
    return os.path.join(path_of(cfg, "out"), key, "_spec.json")


def collect(cfg, keys=None):
    """收集每个 KEY 的指标 + 文字元素数 + verify 结果。"""
    out_root = path_of(cfg, "out")
    rows = []
    if keys is None:
        keys = [os.path.basename(d) for d in sorted(glob.glob(os.path.join(out_root, "*")))
                if os.path.isdir(d)]
    for k in keys:
        r = {"key": k, "live": None, "px": None, "psnr": None, "px_psnr": None,
             "n_text": 0, "n_rect": 0, "n_line": 0, "verify_ok": None,
             "name": k, "dom": "", "cluster": ""}
        rp = metrics_path(cfg, k)
        if os.path.exists(rp):
            try:
                rep = json.load(open(rp, encoding="utf-8"))
                live = rep.get("live") or rep.get("活字版") or {}
                px = rep.get("px") or rep.get("像素层版") or {}
                r["live"] = live.get("diff_gt20_pct")
                r["px"] = px.get("diff_gt20_pct")
                r["psnr"] = live.get("psnr")
                r["px_psnr"] = px.get("psnr")
            except Exception:
                pass
        sp = spec_path(cfg, k)
        if os.path.exists(sp):
            try:
                s = json.load(open(sp, encoding="utf-8"))
                r["n_text"] = len(s.get("text", []))
                r["n_rect"] = len(s.get("rects", []))
                r["n_line"] = len(s.get("lines", []))
            except Exception:
                pass
        vp = os.path.join(out_root, k, "_verify.json")
        if os.path.exists(vp):
            try:
                v = json.load(open(vp, encoding="utf-8"))
                lg = (v.get("live") or {}).get("diff_gt20_pct")
                r["verify_ok"] = (lg is not None and r["live"] is not None
                                  and abs(lg - r["live"]) <= 0.15)
            except Exception:
                pass
        rows.append(r)
    return rows


def jobs_path(cfg, name="batch_jobs.json"):
    return os.path.join(path_of(cfg, "work"), name)


def load_jobs(cfg, name="batch_jobs.json"):
    p = jobs_path(cfg, name)
    if not os.path.exists(p):
        return []
    return json.load(open(p, encoding="utf-8"))


def save_jobs(cfg, jobs, name="batch_jobs.json"):
    p = jobs_path(cfg, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(jobs, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p


def stamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")
