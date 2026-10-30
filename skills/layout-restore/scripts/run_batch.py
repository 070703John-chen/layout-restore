# -*- coding: utf-8 -*-
"""批量复刻：每张跑完整链（探针 → spec → 矢量层 → 渲染寻优 → 像素层 → 交付）。

★ 子进程输出**直接写日志文件**，不走 PIPE。
    Windows 管道缓冲约 64KB，日志一大就写满 → 子进程阻塞等读 →
    父进程等子进程 → **死锁**（2026-10-29 实测：批量跑到一半不动）。

★ 支持断点续跑：已产出 _report.json 的直接跳过。

用法
    python run_batch.py                # 跑全部
    python run_batch.py --only M01,M02
    python run_batch.py --jobs 2
"""
import os
import sys
import json
import time
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="只跑这些 KEY（逗号分隔）")
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="已产出的也重跑")
    a = ap.parse_args()

    cfg = C.load_cfg()
    jobs = C.load_jobs(cfg)
    if a.only:
        keys = {k.strip() for k in a.only.split(",") if k.strip()}
        jobs = [j for j in jobs if j["key"] in keys]
    if not jobs:
        print("没有任务 —— 先跑 pick.py 选片")
        return 2

    n_jobs = a.jobs or C.g(cfg, "batch.jobs", 2)
    py = C.py_exe(cfg)
    eng = C.g(cfg, "engine.restore", "")
    proj = C.path_of(cfg, "project")
    work = C.path_of(cfg, "work")
    logdir = os.path.join(work, "logs")
    os.makedirs(logdir, exist_ok=True)
    env = C.child_env(cfg)

    tb_run = os.path.join(proj, "tb_run.py")
    if not os.path.exists(tb_run):
        print("找不到 %s" % tb_run)
        return 2

    pend = []
    for j in jobs:
        if not a.force and os.path.exists(C.metrics_path(cfg, j["key"])):
            continue
        pend.append(j)
    if len(pend) < len(jobs):
        print("跳过已完成 %d 张（--force 可重跑）" % (len(jobs) - len(pend)))

    running = []
    t0 = time.time()
    done = fail = 0
    while pend or running:
        while pend and len(running) < n_jobs:
            j = pend.pop(0)
            log = os.path.join(logdir, "b_%s.log" % j["key"])
            cmd = [py, tb_run, "--key", j["key"], "--src", j["src"],
                   "--name", j["title"],
                   "--cjk-font", C.g(cfg, "batch.cjk_font", "Noto Sans SC"),
                   "--ink-mode", C.g(cfg, "batch.ink_mode", "majority"),
                   "--min-conf", str(C.g(cfg, "batch.min_conf", 0.45)),
                   "--px-threshold", str(C.g(cfg, "batch.px_threshold", 18.0))]
            fh = open(log, "w", encoding="utf-8")
            p = subprocess.Popen(cmd, cwd=proj, env=env, stdout=fh,
                                 stderr=subprocess.STDOUT)
            running.append((j, p, fh, log, time.time()))
            print("[起] %-5s %-26s 剩 %d" % (j["key"], j["name"], len(pend)),
                  flush=True)
            time.sleep(1)
        time.sleep(3)
        still = []
        for j, p, fh, log, ts in running:
            rc = p.poll()
            if rc is None:
                still.append((j, p, fh, log, ts))
                continue
            fh.close()
            dt = time.time() - ts
            done += 1
            if rc == 0:
                print("[成] %-5s %-26s %5.0fs" % (j["key"], j["name"], dt), flush=True)
            else:
                fail += 1
                print("[败] %-5s %-26s rc=%d  日志 %s"
                      % (j["key"], j["name"], rc, log), flush=True)
        running = still
        n = done + fail
        el = time.time() - t0
        if n:
            print("   ...%d/%d  用时 %.0f 分钟  预计还要 %.0f 分钟"
                  % (n, len(pend) + n, el / 60,
                     (el / n) * max(0, len(pend)) / 60), flush=True)
    print("\n完成 %d / 失败 %d / 用时 %.1f 分钟"
          % (done, fail, (time.time() - t0) / 60))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
