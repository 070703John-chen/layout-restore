# 第三方资源与授权（THIRD PARTY NOTICES）

本目录下的字体文件全部以 **SIL Open Font License, Version 1.1** 授权分发。
OFL 1.1 允许自由使用、修改、嵌入、再分发（含随本项目一起分发），
**条件是必须随附许可证全文** —— 见本目录下的 `OFL-*.txt`。

| 字体文件 | 字体家族 | 授权 | 版权 | 许可证全文 |
|---|---|---|---|---|
| `NotoSansSC-VF.ttf` | Noto Sans SC（可变字重） | SIL OFL 1.1 | © 2014-2021 Adobe，Reserved Font Name 'Source' | `OFL-NotoSansSC.txt` |
| `NotoSerifSC.ttf` | Noto Serif SC ExtraLight | SIL OFL 1.1 | © 2017-2024 Adobe | `OFL-NotoSerifSC.txt` |
| `PlayfairDisplay.ttf` | Playfair Display | SIL OFL 1.1 | © 2017 The Playfair Display Project Authors，Reserved Font Name "Playfair Display" | `OFL-PlayfairDisplay.txt` |
| `PlayfairDisplay-Italic.ttf` | Playfair Display Italic | SIL OFL 1.1 | 同上 | `OFL-PlayfairDisplay.txt` |

上游来源：Google Fonts（<https://github.com/google/fonts>）。

---

## 商业字体：**本仓库不分发任何商业字体**

引擎原本会用到 Century Gothic（几何无衬线）与 Bodoni MT（高对比衬线）。
这些是 **Monotype 等厂商的商用字体**，其授权写明「受许可协议约束、不得再分发」，
**进公开仓库等于侵权分发** ⇒ 一律不随仓库发布。

机制（`layout_restore/rebuild.py`）：

- 引擎的字体注册表里，商业字体登记在 `OPTIONAL_FONTS`，
  **只有当使用者自己把字体文件放到 `layout_restore/assets/`
  或 `LAYOUT_RESTORE_FONTS` 指向的目录时才会被使用**；
- 文件不存在时，引擎**自动降级**到仓库自带的开源字体
  （大字标题 → Playfair Display；中文标题 → Noto Serif SC / Noto Sans SC）；
- `@font-face` 规则也只对**真实存在**的字体文件生成，
  避免浏览器 404 后静默回退到不可控的系统字体。

⇒ 想复现得更准，可以自行安装对应商业字体再跑，仓库本身保持零商业字体。

---

## OFL 1.1 摘要（完整正文见 `OFL-*.txt`）

- 可自由使用、修改、再分发，**包括随软件一起捆绑分发**
- 字体本身**不可单独售卖**
- 衍生字体**不得使用 Reserved Font Name**
- 必须以 OFL 授权分发，不得改用其它许可
- 用这些字体制作的**文档/作品不受 OFL 约束**

完整的许可正文见同目录 `OFL-NotoSansSC.txt` / `OFL-NotoSerifSC.txt` /
`OFL-PlayfairDisplay.txt`（三份 OFL 1.1 正文相同，差别只在开头的版权声明行，
这是 Google Fonts 的上游惯例）。
