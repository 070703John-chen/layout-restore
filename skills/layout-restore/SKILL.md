---
name: layout-restore
description: |
  Restore e-commerce reference images (Taobao/Tmall main & secondary images, posters,
  detail pages) into an EDITABLE source package — HTML + CSS + SVG, layered into
  photo plate / vector structure / live text — then verify it pixel-by-pixel.
  Use this skill when the user wants to 复刻 a layout, 还原 a 参考图, turn a flat
  image into an editable source, batch-restore a set of reference images,
  measure a 达标率, or diagnose why a reconstruction's diff rate is too high.
  Trigger phrases include "复刻这批图", "批量还原", "还原成可编辑源件包",
  "复刻一下原图", "layout restore", "pixel-accurate reconstruction".
  Do NOT use it for: cropping/resizing a single photo (use an image library),
  generating new artwork from scratch, designing vector illustrations, or
  scraping/crawling reference images from e-commerce platforms.
descriptions:
  zh-Hans: |
    把电商参考图（淘宝/天猫主图与附图、海报、详情页）还原成**可编辑源件包**
    （HTML+CSS+SVG，拆成照片层/矢量结构层/活字文字层），并做像素级验收。
    适用于：复刻版式、还原参考图、把平面图变成可编辑源件、批量复刻一批参考图、
    统计达标率、诊断重建差异率为什么降不下来；
    以及跑批之后的**归集与收尾**：并成「一个网站 + 一个存放目录」、
    做品类/产品/图位分类、做单品类专科交付页、清理旧站点前逐文件自证覆盖。
    不适用于：单纯裁剪/改尺寸、原创画图、矢量插画设计、抓取电商平台素材。
displayNames:
  zh-Hans: "版式还原 · 批量复刻"
---

# layout-restore

批量把参考图还原成**可编辑源件包**，并给出可复现的达标率。

## Inputs to collect

- **本机路径**：首次使用必须写 `config.local.yaml`（**不入库**）。
  仓库里的 `config.yaml` 一律是**空占位** —— 真实路径、账号、token 都进本机覆盖文件。
  模板见 `config.local.example.yaml`。
- **参考图在哪**：`config.local.yaml` 的 `paths.raw`（默认是淘宝原图库，
  里面有 `main` / `secondary` 两个子目录）。用户给了别的目录就改这个配置。
- **要几张**：默认 50（`batch.target`）。
- **要什么产物**：可编辑源件包（默认）+ 成品 PNG + 差异热力图 + 对比网站。
  缺省时按默认做，不必追问 —— 这些是这套流程的标准输出。

## Procedure

1. **先自检** —— `python scripts/doctor.py`
   原因：这套流水线依赖本机已装好的 Python 工具链（引擎 / playwright chromium / OCR /
   原图库 / 族聚类产物）。缺任何一项，后面跑到一半才炸，浪费几十分钟。
   缺 chromium 就先 `python -m playwright install chromium`。

2. **选片** —— `python scripts/pick.py --target 50`
   原因：随机抽 50 张会抽到一堆长得差不多的，达标率被相似图稀释，
   测出来的数字代表不了跨版式的真实水平。
   脚本按**版式簇配额**分配，簇内用**最远点采样**挑互相差异最大的。

3. **批量复刻** —— `python scripts/run_batch.py --jobs 2`
   原因：每张要跑完整链（探针 → spec → 矢量层 → 渲染寻优 → 像素层 → 交付），
   单张 2~4 分钟，50 张约 110 分钟。**放后台跑，不要占前台。**
   `jobs` 别开大：本机 2 核 8G，`2` 最稳。

4. **全量验收** —— `python scripts/verify_all.py`
   原因：验收要验的是「客户拿到包之后打开的效果」，不是中间目录；
   中间目录和交付包不一致时，中间目录的指标是**假的**。

5. **出指标** —— `python scripts/report.py`
   原因：达标率必须报**三条口径**（交付 / 活字版 / 有效复刻），
   单报一个会骗人（纯产品照差异率≈0 是因为没活干）。

6. **出对比网站** —— `python scripts/make_site.py`
   原因：用户要**逐张看清差别**。网站是「原图 | 还原图 横向并排」的卡片网格，
   点开是可放大到 4× 的灯箱。静态长图看不了细节。

7. **交付**：把对比站路径 + 三条口径数字 + 差异最大的几张 KEY 一起给用户。

8. **产物异常时，去读源码验证**（别只按流程走）
   原因：2026-10-30 的 eval 实测 —— 不带 skill 的 agent 反而钻进了源码，
   挖出 5 个真缺陷（描边宽度候选集上限 6、验收清单硬编码样本、
   子进程 DEVNULL 吞错误、批次列表正则只认 R1~R6、10 个源图丢失），
   带 skill 的 agent 反而没发现 —— 因为 skill 教的是「怎么跑」，
   不教「跑出来的结果可疑时该怀疑什么」。
   → 遇到「差异率高 / 数字反常 / 某张特别差」，**先读引擎源码 + 读 spec**，
   不要直接下结论说「素材限制」。

9. **自检也会骗人 —— 交付前做「内容级」检查**
   原因：2026-10-30 实测三条「表面验收 100% 通过、实际全错」的坑：
   - 对比站 50 张差异热力图**内容全是 M01 的**（文件在、链接对、数量 50/50）；
   - `report.py` 在构造报告时崩溃，stdout 数字打完了但 **.md 根本没落盘**，
     磁盘上躺着旧文件；
   - `verify.py` 对**交付包**没有基准可比，交付包被改坏也照样判「全部一致 [OK]」。
   → 交付前必查三条：
   1. **同批次产物哈希唯一**（重复 = 张冠李戴）；
   2. **报告文件 mtime 真的更新了**（别只看 stdout）；
   3. **故意破坏一个交付件，看验收会不会 FAIL**（不会 = 闸门是摆设）。

9. **归集到一个网站 + 一个存放目录** —— `references/交付站归集与清理.md`
   原因：跑批产物天然散在各处，用户拿到手是一堆文件夹，看不出「到底做了什么」。
   → 目标形态：`交付站\{index.html, data\index.json, assets\<产品组>\, src\<产品组>\<KEY>\}`
   → 分类三级：**品类 → 产品 → 图位**（第一维度必须是产品归属）
   → 源件包字体**共享一份 + 硬链接**落回各包 `assets/`（零额外磁盘、相对路径零改写）
   → 专科页面（单品类）用 `../assets/` 相对路径引用 ⇒ 零重复拷贝，仍是一个存放目录

10. **清理旧站点前，逐文件自证覆盖** —— `scripts/audit_coverage.py`
    原因：「看起来是冗余」不是删除理由。删之前必须证明归集站里确实有它，
    有缺口就 SKIP。
    ```powershell
    python scripts/audit_coverage.py --source <工程根>\out --target <工程根>\交付站\src `
      --intermediate _render_1x.png,_render_px.png --json-out coverage.json
    ```
    闸门 BLOCKED 就不许删；覆盖度 < 100% 的旧站**只能归档**。
    ⚠ 删完工作目录后**必须给出站/归集脚本加「源缺失闸门」**，
    否则下次重跑会把成品静默覆盖成空站（铁律 30）。

### 或者一键跑完

`python scripts/pipeline.py` 串起上面全部。适合「从头到尾重做一遍」。

### 多品类批次（每品类 N 组）

```powershell
$env:LAYOUT_RESTORE_PROFILE='multicat'
python scripts/pick_multicat.py      # 每品类独立聚类 → 每品类 N 组
python scripts/run_batch.py --jobs-file batch_jobs.json
```

- **profile 机制**：每个批次一份 `config.local.<profile>.yaml`（**不入库**），
  用环境变量 `LAYOUT_RESTORE_PROFILE` 切换。多个批次共用同一个 skill，
  不用反复改同一份配置把上一批搞乱。
- **「组」是什么**：抓图走通道 B（必应索引 → alicdn 直链），拿到的是**散图、
  没有商品结构** —— 不知道哪张附图属于哪张主图。所以「组」= **同品类下视觉特征
  相近的一簇图**（版式族），组内 1 张最典型的作主图，其余作附图。
  **这不是「同一商品的主图+附图」。** 要真实商品结构，得开带登录态的浏览器走通道 A。

### 单张复刻（只要一张）

```powershell
python scripts/run_batch.py --only M04
```

### 「这张为什么差」——自动定性

```powershell
python scripts/diag_why.py M04 S27 --crops out/_hotspots
python scripts/diag_why.py --batch <work>/batch_jobs.json    # 整批
```

按「分区复算 → 文字区差异 → 是不是字体不可得」三步给出结论：

| 结论 | 判据 | 能修吗 |
|---|---|---|
| 达标 | 整体 ≤ 阈值 | — |
| 工程缺陷：分层/背景重建错 | **非文字区差异 ≥ 3%** | 能 |
| 工程缺陷：字色/字重取错 | 文字区差异大 **且** 多个字整体偏深/偏浅 | 能 |
| 工程缺陷：字号/字距错位 | 文字区差异 20~35%，非文字区干净 | 能 |
| **素材限制：大字艺术字体不可得** | 有 ≥85px 的字 | 不能（除非走像素层） |
| **素材限制：字形不可得** | 无大字但字形明显不同（产品丝印/装饰字体） | 不能 |

⚠ **别单看「文字区差异率」**：实测一批里达标图的文字区差异也有 33~46%
（字面积占比小，整体被稀释）。**判定要看整体 + 各区面积占比。**

## Output contract

- `<paths.project>/out/<KEY>/index.html` —— **活字版，唯一编辑入口**
- `<paths.project>/out/<KEY>/index_px.html` —— 像素层版（字形原图裁切）
- `<paths.project>/out/<KEY>/_spec.json` —— 配方（坐标/色值/字号/字重/寻优记录）
- `<paths.project>/out/<KEY>/deliver/` —— 1x/2x 成品 + 对比图 + 差异热力图 + 源件包
- `<paths.project>/_work/batch_report.md` —— 三条口径达标率 + 分簇分析 + 逐张明细
- `<paths.project>/批量复刻50张_对比站/index.html` —— 对比网站（双击即开，离线可用）

汇报时**至少给这四个数**：交付达标率、活字版达标率、有效复刻达标率、verify 包自洽率。

## Failure handling

- **某张失败** —— 日志在 `<paths.project>/_work/logs/b_<KEY>.log`。
  先看是不是编码问题（`UnicodeEncodeError` → 确认 `PYTHONIOENCODING=utf-8` 有没有注入），
  再看是不是路径问题（中文路径 → `cv2.imread` 会失败，引擎已用 `np.fromfile` 绕过）。
- **路径没配** —— `doctor.py` 会报「未配置」。填 `config.local.yaml`，
  **不要**改 `config.yaml`（那个文件必须保持无绝对路径，发布前有自检）。
- **批量跑到一半卡住不动** —— 大概率是**死锁**：子进程输出走了 `PIPE` 而父进程最后才读，
  Windows 管道缓冲约 64KB 写满就阻塞。本 skill 的脚本已改成**子进程直接写日志文件**。
- **重跑脚本把成品覆盖成空站** —— 清理掉源目录之后，出站/归集脚本的数据源就没了。
  ⇒ 必须加源缺失闸门（`if not os.path.isdir(SRC): return 2`），
  并在 README 里写清「先跑引擎 → 再归集 → 再出站」的顺序。见铁律 30。
- **交付页少了一半内容 / 只有第一个分组** —— 多半是 JS 里引用了 Python 侧才有的常量，
  `ReferenceError` 让 `render()` 在第一项之后静默中断。
  验收脚本要数**各分组的条目数**，只数总数看不出这个问题。
- **差异率高** —— 按这个顺序查，跳过任何一步都是浪费时间：
  1. 非文字区差异率是不是 0.00%？不为 0 → 分层错了，先修分层，别碰寻优。
  2. 是不是字体问题？把主视觉换成原图裁切块，残差掉下来 → 是**字体替代的天花板**。
  3. 差异热力图上某一块特别红 → 那一块的结构没拆对。
  4. 某行字变黑粗体 + 白色鬼影 → **跨底色**取色错误，见 `references/铁律.md` 第 5 条。

## References

- `references/跑批实录与排障手册.md` —— **实际踩过的坑**（现象 / 为什么会遇到 /
  怎么解决的 / 以后遇到怎么办）。**跑批前先看症状速查表**；
  出问题时按症状查编号，别从头读。
- `references/铁律.md` —— **踩坑换来的硬规则**（25 条）。改引擎或调参前先读。
- `references/三层模型与版式族.md` —— 三层模型 + spec 结构 + 族怎么定怎么复用。
- `references/环境与依赖.md` —— 依赖清单、脚本分工、产物落点、时间成本。

## Examples

**Input**：复刻这 50 张原图，我要能看到每张的差别。
**Output**：`run_batch.py` 跑完 → `report.py` 给
「交付达标率 49/50=98%、活字版 36/50=72%、有效复刻 24/38=63%、verify 50/50=100%」
→ `make_site.py` 给出对比站路径，卡片是「原图｜活字版」横向并排，
点开可放大到 4× 逐像素看。

**Input**：为什么这张重建出来差 20%？
**Output**：查 `out/<KEY>/_render_1x.png` 的热力图 → 残差集中在文字上 →
该字是商业艺术字（无授权替代字体）→ 属素材限制，
方案是把它归入美术素材层从原图裁切（代价：那处字不可编辑）。

## Windows (win32) platform notes

本 skill 只在 Windows PowerShell 下跑。所有命令用 `python`（不是 `python3`），
路径含中文时 PowerShell 5.1 默认 GBK 编码会弄坏内容 —— 读文件用 Read 工具、
写文件用 Write 工具，脚本内部一律显式 `encoding="utf-8"`。

子进程必须注入 `PYTHONIOENCODING=utf-8`（`common.py` 的 `child_env()` 已做）：
引擎日志里有中文和 `®` 这类符号，GBK 控制台会 `UnicodeEncodeError` **整轮崩掉**。

删临时文件走可恢复的 `rm -- <target>`（mavis-trash），不要用 `Remove-Item`。
