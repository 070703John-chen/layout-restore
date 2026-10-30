# -*- coding: utf-8 -*-
"""一键全流程：选片 → 批量复刻 → 全量验收 → 指标汇总 → 对比网站。

用法
    python pipeline.py                 # 全流程
    python pipeline.py --target 30     # 只跑 30 张
    python pipeline.py --skip-site      # 不生成网站
    python pipeline.py --doctor-only   # 只做环境自检

★ 全流程很慢（每张 2~4 分钟）。50 张约 2 小时。
  可以分步跑，中间断了也能续：每个步骤都独立，靠 <work>/batch_jobs.json 串起来。
"""
import os
import sys
import time
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

HERE = os.path.dirname(os.path.abspath(__file__))


def step(name, args, py=None):
    print("\n" + "=" * 62)
    print("== %s" % name)
    print("=" * 62, flush=True)
    t0 = time.time()
    # ⚠ 用**配置里的** python，不是 sys.executable：
    #   本机 Python314 没装 chromium，sys.executable 指向它 → 出图全废。
    rc = subprocess.call([py or sys.executable,
                          os.path.join(HERE, args[0])] + args[1:])
    print("-- %s 结束 rc=%d  用时 %.1f 分钟" % (name, rc, (time.time() - t0) / 60))
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=None)
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--skip-site", action="store_true")
    ap.add_argument("--doctor-only", action="store_true")
    a = ap.parse_args()

    cfg = C.load_cfg()
    py = C.py_exe(cfg)

    rc = step("环境自检", ["doctor.py"], py)
    if rc != 0:
        print("\n环境不齐，先补齐再跑（doctor 已列出缺什么）")
        return rc
    if a.doctor_only:
        return 0

    t0 = time.time()
    pa = []
    if a.target:
        pa += ["--target", str(a.target)]
    rc = step("① 选片", ["pick.py"] + pa, py)
    if rc:
        return rc

    pa = []
    if a.jobs:
        pa += ["--jobs", str(a.jobs)]
    rc = step("② 批量复刻", ["run_batch.py"] + pa, py)
    if rc:
        print("有失败项，先看 <work>/logs/ 下的日志")

    # ⚠ 每一步的 rc 都要收集：原来「全部步骤结束」无论成败都 return 0，
    #   调用方/CI 看不出这轮到底跑通了没（2026-10-30 修）。
    bad = 1 if rc else 0
    rc = step("③ 全量验收 verify",
              ["verify_all.py"] + (["--jobs", str(a.jobs)] if a.jobs else []), py)
    if rc:
        bad = 1
        print("验收有不一致 —— 交付包重渲结果和 _report.json 对不上")

    rc = step("④ 指标汇总", ["report.py"], py)
    if rc:
        bad = 1
    if C.g(cfg, "site.enabled", True) and not a.skip_site:
        rc = step("⑤ 对比网站", ["make_site.py"], py)
        if rc:
            bad = 1

    print("\n全部步骤结束，总用时 %.1f 分钟" % ((time.time() - t0) / 60))
    print("状态板：%s" % os.path.join(C.path_of(cfg, "work"), "batch_report.md"))
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
