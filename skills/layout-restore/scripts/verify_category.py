# -*- coding: utf-8 -*-
"""★ 品类校验闸门 —— 把「图和品类对不上」挡在跑批之前。

【为什么必须有这道闸门】2026-11-03 实测：
    Bing 搜图按「词匹配 + 相关推荐」返回，**不保证图和品类语义对应**。
    125 张里目视查出 **11 张错类**：手机组混进项链吊坠、香水组混进唇釉/洗发水、
    零食组混进仓库物流广告。
    ⇒ 光看「差异率达标率」是自欺欺人 —— **指标漂亮但数据是脏的**。

【判据】（easyocr 中文 OCR，本机已有模型，不用联网下载）
    must 命中  → PASS   （图上文字含该品类特征词）
    否则 reject 命中 → FAIL（图上文字含**别的**品类特征词）
    否则 → REVIEW（无相关文字，得靠人眼）
    ★ must 优先于 reject：香水图上写"香氛精华"不该被 reject 里的"精华"误杀。

用法
    python verify_category.py --refs <dir> --out <report.json>
    python verify_category.py --manifest <jobs.json>
"""
import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- 词表
RULES = {
    "phone": {
        "must": ["手机", "智能手机", "老人机", "老年机", "老年手机", "折叠屏", "折叠",
                 "翻盖", "全网通", "双卡", "充电", "像素", "拍照", "处理器",
                 "运行内存", "屏幕尺寸", "电池容量", "入网许可", "运营商",
                 "大字", "大按键", "备用机", "直板", "5G", "4G", "手机壳"],
        "reject": ["项链", "吊坠", "耳环", "耳钉", "戒指", "手链", "手镯", "珠宝",
                   "黄金", "足金", "铂金", "钻石", "翡翠", "珍珠", "锆石", "宝石",
                   "首饰", "佛珠", "手串", "平安扣", "玉佩", "玉石", "吊坠项链"],
    },
    "perfume": {
        "must": ["香水", "淡香", "浓香", "香氛", "香精", "留香", "前调", "中调",
                 "后调", "淡香水", "浓香水", "香水瓶", "EDP", "EDT", "香调"],
        "reject": ["洗发", "沐浴", "面霜", "唇釉", "口红", "眼影", "粉底", "面膜",
                   "护肤", "洗面奶", "身体乳", "防晒", "彩妆", "乳液", "护发素",
                   "发膜", "沐浴露", "洗发水", "素颜霜", "遮瑕", "粉饼", "睫毛膏",
                   "面部精华", "护肤精华", "身体护理"],
    },
    "food": {
        "must": ["零食", "坚果", "薯片", "辣条", "肉干", "果干", "膨化", "大礼包",
                 "整箱", "组合装", "蜜饯", "糕点", "巧克力", "话梅", "果脯",
                 "麦片", "蛋糕", "面包", "罐头", "果冻", "海苔", "糖"],
        "reject": ["仓储", "物流", "货架", "供应商", "批发部", "厂房", "仓库",
                   "托盘", "招商加盟"],
    },
    "led": {
        "must": ["LED", "吸顶灯", "灯带", "灯泡", "射灯", "照明", "色温", "光源",
                 "护眼", "灯珠", "平板灯", "灯体", "灯罩", "瓦数", "客厅灯",
                 "卧室灯", "氛围灯"],
        "reject": [],
    },
    "pot": {
        "must": ["电煮锅", "电热锅", "多功能锅", "煮锅", "煮面", "煮蛋", "内胆",
                 "不粘", "蒸锅", "煮锅", "火锅", "容量", "保温", "加热", "锅体",
                 "早餐机", "电热", "锅具"],
        "reject": [],
    },
}

CAT_CN = {"food": "零食", "led": "LED灯", "perfume": "品牌香水",
          "phone": "手机", "pot": "电煮锅"}


def ocr_texts(path, reader, canvas_size=1280, max_side=1200):
    """easyocr 内部用 cv2.imread 读路径 ⇒ **中文路径直接失败**
    （实测 WARN: can't open/read file → 全部判 REVIEW）。
    ⇒ 自己读字节 → cv2.imdecode → 把 numpy 数组喂给 easyocr。

    ★ 性能：easyocr 默认 canvas_size=2560，CPU 上一张图要 15~20 秒。
      降到 1280 + 预处理降采样到长边 1200，速度约 3~4 倍，电商图的大字仍能识别。
      ★ 再加 --fast（canvas_size=768 + 长边 900）：单张 ~8 秒，
        批量筛查够用；代价是**细字可能识别不出 ⇒ REVIEW 变多**，
        但 reject 词命中（错类的强信号）不受影响 ⇒ 用 --fast 做全量筛查、
        对可疑项再用默认精度复核。
    """
    try:
        import cv2
        import numpy as np
        buf = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            return ""
        h, w = img.shape[:2]
        m = max(h, w)
        if m > max_side:
            s = max_side / m
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        res = reader.readtext(img, detail=0, paragraph=False,
                              canvas_size=canvas_size, mag_ratio=1.0,
                              workers=0)   # ★ workers=0 → 单线程，不跟别的进程抢 CPU
                              #   （实测本机 explorer/WPS 云服务会吃掉 60%+ CPU）
    except Exception:
        return ""
    return " ".join(str(x) for x in res) if res else ""


def classify(cat, text):
    """返回 (verdict, hit) —— verdict ∈ PASS / FAIL / REVIEW"""
    r = RULES.get(cat, {"must": [], "reject": []})
    t = (text or "").replace(" ", "")
    must_hit = [w for w in r["must"] if w.lower() in t.lower()]
    rej_hit = [w for w in r["reject"] if w.lower() in t.lower()]
    if must_hit:
        return "PASS", must_hit[:4]
    if rej_hit:
        return "FAIL", rej_hit[:4]
    return "REVIEW", []


def main():
    ap = argparse.ArgumentParser(description="品类校验闸门")
    ap.add_argument("--manifest", default="", help="jobs json（按 key 推断品类）")
    ap.add_argument("--refs", default="", help="目录模式：<dir>/<cat>/<pN>/…")
    ap.add_argument("--out", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jsonl", default="",
                    help="★ 逐张落盘的增量结果（每判完一张 append 一行）。"
                         "OCR 在 CPU 上每张 30~45s，全量 125 张会超过后台任务 1 小时上限"
                         "⇒ 必须增量落盘，否则被杀就白跑。")
    ap.add_argument("--resume", action="store_true",
                    help="从 --jsonl 里读已完成的 key 跳过（配合 --jsonl 使用）")
    ap.add_argument("--only-cats", default="",
                    help="只跑这些品类（逗号分隔），用于分批")
    ap.add_argument("--only-keys", default="",
                    help="★ 只跑这些 key（逗号分隔）。"
                         "用途：fast 筛查后拿一批 REVIEW 用默认精度复核。")
    ap.add_argument("--fast", action="store_true",
                    help="★ 快速筛查模式（canvas_size=768 + 长边 900，单张 ~8 秒）。"
                         "代价：细字可能识别不出 ⇒ REVIEW 变多；"
                         "但 reject 词命中（错类的强信号）不受影响 ⇒ "
                         "全量筛查用 --fast，可疑项再用默认精度复核。")
    a = ap.parse_args()
    CANVAS = 768 if a.fast else 1280
    MAXSIDE = 900 if a.fast else 1200

    items = []           # (cat, path, key)
    if a.manifest:
        for j in json.load(open(a.manifest, encoding="utf-8")):
            src = j.get("src", "")
            cat = j.get("cluster", "")
            if cat not in RULES:
                continue
            if not os.path.isfile(src):
                continue
            items.append((cat, src, j["key"]))
    elif a.refs:
        for cat in os.listdir(a.refs):
            if cat not in RULES:
                continue
            cdir = os.path.join(a.refs, cat)
            for dp, dn, fn in os.walk(cdir):
                for f in fn:
                    if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                        items.append((cat, os.path.join(dp, f),
                                      os.path.relpath(os.path.join(dp, f), a.refs)))
    else:
        ap.error("要 --manifest 或 --refs")

    if a.only_cats:
        keep = {c.strip() for c in a.only_cats.split(",") if c.strip()}
        items = [it for it in items if it[0] in keep]

    if a.only_keys:
        keepk = {k.strip() for k in a.only_keys.split(",") if k.strip()}
        items = [it for it in items if it[2] in keepk]

    # ★ 续跑：先读增量结果，已判过的 key 直接跳过
    done_rows, done_keys = [], set()
    if a.resume and a.jsonl and os.path.isfile(a.jsonl):
        with open(a.jsonl, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                done_rows.append(r)
                done_keys.add(r["key"])
        items = [it for it in items if it[2] not in done_keys]
        print("续跑：已判 %d 张，剩 %d 张" % (len(done_rows), len(items)))

    if a.limit:
        items = items[:a.limit]

    if not items:
        rows = done_rows
    else:
        import easyocr
        t0 = time.time()
        reader = easyocr.Reader(["ch_sim", "en"], gpu=False, download_enabled=False,
                                verbose=False)
        print("OCR 引擎就绪（%.1fs），待校验 %d 张" % (time.time() - t0, len(items)))

        rows = list(done_rows)
        jf = open(a.jsonl, "a", encoding="utf-8") if a.jsonl else None
        for i, (cat, path, key) in enumerate(items, 1):
            txt = ocr_texts(path, reader, CANVAS, MAXSIDE)
            verdict, hit = classify(cat, txt)
            row = {"key": key, "cat": cat, "verdict": verdict, "hit": hit,
                   "path": path, "text": txt[:200]}
            rows.append(row)
            if jf:                       # ★ 每张立刻落盘
                jf.write(json.dumps(row, ensure_ascii=False) + "\n")
                jf.flush()
            if verdict == "FAIL" or a.fast or i % 10 == 0 or i == len(items):
                print("  [%3d/%3d] %-6s %-30s %s %s"
                      % (i, len(items), verdict, key[:30],
                         ",".join(hit), ("· " + txt[:60]) if verdict == "FAIL" else ""),
                      flush=True)
        if jf:
            jf.close()

    n_pass = sum(1 for r in rows if r["verdict"] == "PASS")
    n_fail = sum(1 for r in rows if r["verdict"] == "FAIL")
    n_rev = sum(1 for r in rows if r["verdict"] == "REVIEW")
    print("\n=== 品类校验结果 ===")
    print("PASS %d / FAIL %d / REVIEW %d（共 %d）" % (n_pass, n_fail, n_rev, len(rows)))
    for cat in RULES:
        c = [r for r in rows if r["cat"] == cat]
        f = [r for r in c if r["verdict"] == "FAIL"]
        if c:
            print("  %-6s %d 张：PASS %d / FAIL %d / REVIEW %d"
                  % (CAT_CN.get(cat, cat), len(c),
                     sum(1 for r in c if r["verdict"] == "PASS"), len(f),
                     sum(1 for r in c if r["verdict"] == "REVIEW")))
            for r in f:
                print("      FAIL %-28s 命中 %s  ← %s" % (r["key"][:28],
                                                        ",".join(r["hit"]), r["text"][:50]))

    if a.out:
        json.dump(rows, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("报告 → %s" % a.out)
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
