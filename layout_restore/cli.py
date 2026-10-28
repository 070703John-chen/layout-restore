# -*- coding: utf-8 -*-
r"""layout-restore —— 唯一命令行入口。

分层（别破坏）
    代码写「怎么判」：探针 / 矢量检测 / 寻优 / 取色判据   → 改算法 = 改代码
    配置写「判什么·在哪」：阈值 / 路径 / 字体              → 改数据 = 改 config.yaml
    状态板写「到哪了」：runs/<run_id>/状态板.md

子命令
    build     一条命令跑完整链（探针 → spec → 矢量层 → 渲染寻优 → 像素层降级 → 验收）
    probe     只跑探针（看文字层/色块/美术层拆得对不对）
    autospec  探针 → spec 草稿
    vectorize 加矢量结构层（色块 rects / 线条 lines）
    verify    从**交付的源件包**重渲并和原图对账
    overview  拼「原图｜活字版｜像素层版｜热力图」总览图
    report    生成指标表 Markdown
    status    打印状态板

例子
    layout-restore build --src refs/demo.jpg --key demo
    layout-restore build --src refs/demo.jpg --key demo --jobs 4
    layout-restore verify --pack out/demo
    layout-restore overview --out overview.png --packs out
"""
import os
import sys
import glob
import json
import time
import argparse
import subprocess

from . import config as _cfg

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------ 工具
def run_module(mod, argv, env=None):
    """跑一个包内模块（python -m layout_restore.X）。

    ⚠ 子进程输出**直接落日志文件**，不要走 PIPE：
      Windows 管道缓冲约 64KB，日志一大就写满 → 子进程阻塞等读、
      父进程等子进程 → **死锁**（2026-10-29 实测踩过）。
    """
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    if env:
        e.update(env)
    r = subprocess.run([sys.executable, "-m", "layout_restore." + mod] + list(argv),
                       env=e, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _load_report(out_dir):
    p = os.path.join(out_dir, "_report.json")
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def _metrics(rep):
    """兼容两种报告结构（live/px 与 活字版/像素层版）。"""
    live = rep.get("live") or rep.get("活字版") or {}
    px = rep.get("px") or rep.get("像素层版") or {}
    return (live.get("diff_gt20_pct"), px.get("diff_gt20_pct"),
            live.get("psnr"), px.get("psnr"))


# ------------------------------------------------------------------ 子命令
def cmd_build(cfg, a):
    """完整链：probe → autospec → vectorize → rebuild → 像素层降级 → 交付。"""
    src = os.path.abspath(a.src)
    key = a.key
    out_root = a.out or os.path.join(os.getcwd(), "out")
    out_dir = os.path.join(out_root, key)
    specs = a.specs or os.path.join(os.getcwd(), "specs")
    work = a.work or os.path.join(os.getcwd(), ".work", "probe")
    os.makedirs(out_root, exist_ok=True)
    os.makedirs(specs, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.join(out_root, key), exist_ok=True)

    probe_json = os.path.join(work, "_probe_%s.json" % key)
    spec_json = os.path.join(specs, "%s.json" % key)

    b = cfg.get("build", {})
    steps = [
        ("probe", ["probe_layers", "--src", src, "--key", key,
                   "--crop", a.crop, "--outdir", work,
                   "--ink-mode", a.ink_mode or b.get("ink_mode", "majority")]),
        ("autospec", ["autospec", "--probe", probe_json, "--key", key,
                      "--name", a.name or key, "--src", src,
                      "--crop", a.crop, "--out", spec_json,
                      "--min-conf", str(a.min_conf or b.get("min_conf", 0.45)),
                      "--cal-weight", "--cal-fill",
                      "--cjk-font", b.get("cjk_font", "Noto Sans SC"),
                      "--latin-font", b.get("latin_font", "Noto Sans SC")]),
        ("vectorize", ["vectorize", "--src", src, "--probe", probe_json,
                       "--out", spec_json, "--merge"]),
        ("rebuild", ["rebuild", "--spec", spec_json, "--out", out_dir]),
    ]
    for name, argv in steps:
        t0 = time.time()
        rc, out = run_module(argv[0], argv[1:])
        if rc != 0:
            print("[%s] 失败 rc=%d" % (name, rc))
            print(out[-3000:])
            return rc
        print("[%s] ok  %.0fs" % (name, time.time() - t0))

    # 像素层降级：字体替代还原不出来的大字 → 像素层
    rc, out = run_module("pixel_fallback",
                         ["--spec", spec_json, "--out", out_dir,
                          "--threshold", str(b.get("px_threshold", 18.0))])
    if rc == 0 and "像素层" in out:
        print("[pixel-fallback] 有降级，重跑 rebuild 出像素层版")
        rc2, out2 = run_module("rebuild",
                               ["--spec", spec_json, "--out", out_dir, "--no-sweep"])
        if rc2 != 0:
            print(out2[-2000:])
            return rc2

    rep = _load_report(out_dir)
    live, px, psnr, ppsnr = _metrics(rep)
    print("\n=== 验收 %s ===" % key)
    print("  活字版   diff>20 = %s%%   psnr = %s" % (live, psnr))
    print("  像素层版 diff>20 = %s%%   psnr = %s" % (px, ppsnr))
    print("  产物 -> %s" % out_dir)
    return 0


def cmd_probe(cfg, a):
    work = a.outdir or os.path.join(os.getcwd(), ".work", "probe")
    os.makedirs(work, exist_ok=True)
    b = cfg.get("build", {})
    rc, out = run_module("probe_layers",
                         ["--src", os.path.abspath(a.src), "--key", a.key,
                          "--crop", a.crop, "--outdir", work,
                          "--ink-mode", a.ink_mode or b.get("ink_mode", "majority")])
    print(out)
    return rc


def cmd_autospec(cfg, a):
    rc, out = run_module("autospec",
                         ["--probe", a.probe, "--key", a.key,
                          "--name", a.name or a.key, "--src", os.path.abspath(a.src),
                          "--crop", a.crop, "--out", a.out,
                          "--min-conf", str(cfg.get("build", {}).get("min_conf", 0.45)),
                          "--cal-weight", "--cal-fill"])
    print(out)
    return rc


def cmd_vectorize(cfg, a):
    rc, out = run_module("vectorize",
                         ["--src", os.path.abspath(a.src), "--probe", a.probe,
                          "--out", a.out, "--merge"])
    print(out)
    return rc


def cmd_verify(cfg, a):
    rc, out = run_module("verify", ["--pack", os.path.abspath(a.pack),
                                    "--tol", str(cfg.get("verify", {}).get("tol", 0.15))])
    print(out)
    return rc


def cmd_overview(cfg, a):
    rc, out = run_module("overview",
                         ["--out", os.path.abspath(a.out), "--packs", a.packs,
                          "--cell-h", str(a.cell_h)])
    print(out)
    return rc


def cmd_report(cfg, a):
    rc, out = run_module("report", ["--out", os.path.abspath(a.out), "--packs", a.packs])
    print(out)
    return rc


def cmd_status(cfg, a):
    """状态板：一眼知道「到哪了」。"""
    out_root = a.out or os.path.join(os.getcwd(), "out")
    rows = []
    for d in sorted(glob.glob(os.path.join(out_root, "*"))):
        if not os.path.isdir(d):
            continue
        rep = _load_report(d)
        if not rep:
            continue
        live, px, psnr, ppsnr = _metrics(rep)
        rows.append((os.path.basename(d), live, px, psnr, ppsnr))
    print("=" * 64)
    print("layout-restore · 状态板")
    print("=" * 64)
    print("产物目录: %s   共 %d 个" % (out_root, len(rows)))
    if not rows:
        print("尚未产出重建结果。跑：layout-restore build --src <图> --key <名>")
        return 0
    print("\n%-18s %10s %10s %9s %9s" % ("KEY", "活字差异%", "像素层%", "PSNR", "像素PSNR"))
    for r in rows:
        print("%-18s %10s %10s %9s %9s" % (
            r[0][:18],
            ("%.2f" % r[1]) if r[1] is not None else "—",
            ("%.2f" % r[2]) if r[2] is not None else "—",
            ("%.2f" % r[3]) if r[3] is not None else "—",
            ("%.2f" % r[4]) if r[4] is not None else "—"))
    ok = [r for r in rows if r[1] is not None and r[1] <= 8]
    print("\n活字版 ≤8%% 的：%d / %d" % (len(ok), len(rows)))
    return 0


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="layout-restore",
        description="参考图 → 可编辑源件包（像素级可验收）")
    # 公共参数：每个子命令都能带 --config（放在子命令后面也能用）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=None, help="配置文件（默认 ./config.yaml）")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("build", help="跑完整链（探针→spec→矢量层→渲染寻优→像素层→验收）", parents=[common])
    p.add_argument("--src", required=True, help="参考图")
    p.add_argument("--key", required=True, help="产物名（也是族配方名）")
    p.add_argument("--name", default=None)
    p.add_argument("--crop", default="0,0,0,0", help="裁切 t,b,l,r")
    p.add_argument("--out", default=None, help="产物根目录（默认 ./out）")
    p.add_argument("--specs", default=None, help="spec 目录（默认 ./specs）")
    p.add_argument("--work", default=None)
    p.add_argument("--ink-mode", default=None, choices=["ring", "majority"])
    p.add_argument("--min-conf", type=float, default=None)
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("probe", help="只跑探针", parents=[common])
    p.add_argument("--src", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--crop", default="0,0,0,0")
    p.add_argument("--outdir", default=None)
    p.add_argument("--ink-mode", default=None, choices=["ring", "majority"])
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("autospec", help="探针 → spec 草稿", parents=[common])
    p.add_argument("--probe", required=True)
    p.add_argument("--src", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--crop", default="0,0,0,0")
    p.set_defaults(fn=cmd_autospec)

    p = sub.add_parser("vectorize", help="加矢量结构层", parents=[common])
    p.add_argument("--src", required=True)
    p.add_argument("--probe", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_vectorize)

    p = sub.add_parser("verify", help="从交付源件包重渲并对账", parents=[common])
    p.add_argument("--pack", required=True)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("overview", help="拼总览对比图", parents=[common])
    p.add_argument("--out", required=True)
    p.add_argument("--packs", default="out", help="含多个 _report.json 的目录")
    p.add_argument("--cell-h", type=int, default=560)
    p.set_defaults(fn=cmd_overview)

    p = sub.add_parser("report", help="生成指标表 Markdown", parents=[common])
    p.add_argument("--out", required=True)
    p.add_argument("--packs", default="out")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("status", help="打印状态板", parents=[common])
    p.add_argument("--out", default=None, help="产物根目录（默认 ./out）")
    p.set_defaults(fn=cmd_status)

    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    cfg, cfg_path = _cfg.load(getattr(a, "config", None))
    if cfg_path:
        print("[config] %s" % cfg_path)
    return a.fn(cfg, a) or 0


if __name__ == "__main__":
    raise SystemExit(main())
