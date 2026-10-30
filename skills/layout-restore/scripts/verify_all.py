# -*- coding: utf-8 -*-
"""全量 verify：从**交付的源件包**重新渲染，和原图对账。

为什么必须做
    验收要验的是「客户拿到包之后打开的效果」，不是中间目录。
    中间目录和交付包不一致时，中间目录的指标是**假的**。
    （2026-10-24 第一次跑就抓到两个回写 bug：同名文字用 hits[0] 匹配、
      文本含 & 时 HTML 里是 &amp; → 寻优值没回写。）

用法
    python verify_all.py
    python verify_all.py --jobs 2
"""
import os
import sys
import time
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

VERIFY_PY = r"D:\电商素材\设计中枢\16_开源项目\layout-restore\layout_restore\verify.py"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--only", default=None)
    a = ap.parse_args()

    cfg = C.load_cfg()
    jobs = C.load_jobs(cfg)
    if a.only:
        keys = {k.strip() for k in a.only.split(",") if k.strip()}
        jobs = [j for j in jobs if j["key"] in keys]
    if not jobs:
        print("没有任务 —— 先跑 pick.py")
        return 2

    n_jobs = a.jobs or C.g(cfg, "batch.jobs", 2)
    py = C.py_exe(cfg)
    out_root = C.path_of(cfg, "out")
    work = C.path_of(cfg, "work")
    logdir = os.path.join(work, "logs")
    os.makedirs(logdir, exist_ok=True)
    env = C.child_env(cfg)

    if not os.path.exists(VERIFY_PY):
        print("找不到通用版 verify：%s" % VERIFY_PY)
        print("（公开仓库 layout-restore 里那份是通用版；引擎里那份是写死项目的旧版）")
        return 2

    pend = [j for j in jobs
            if os.path.exists(os.path.join(out_root, j["key"], "index.html"))]
    running = []
    t0 = time.time()
    n = 0
    while pend or running:
        while pend and len(running) < n_jobs:
            j = pend.pop(0)
            pack = os.path.join(out_root, j["key"])
            log = os.path.join(logdir, "v_%s.log" % j["key"])
            fh = open(log, "w", encoding="utf-8")
            p = subprocess.Popen([py, VERIFY_PY, "--pack", pack],
                                 env=env, stdout=fh, stderr=subprocess.STDOUT)
            running.append((j, p, fh, log))
            time.sleep(1)
        time.sleep(2)
        still = []
        for j, p, fh, log in running:
            rc = p.poll()
            if rc is None:
                still.append((j, p, fh, log))
                continue
            fh.close()
            n += 1
            print("[%d/%d] %-5s rc=%d" % (n, len(jobs), j["key"], rc), flush=True)
        running = still
    print("verify 结束，用时 %.1f 分钟" % ((time.time() - t0) / 60))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
