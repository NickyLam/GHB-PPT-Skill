---
name: GHB-PPT-SKILL
description: 用自带 GHB 模板生成完整演示文稿——封面 template-fill 保留模板首页格式、正文 SVG 流水线生成富视觉内容、末页续接模板致谢页，全 deck 统一继承模板母版（含背景装饰图）。自包含：脚本与模板均已内置，仅需 python-pptx，安装本 skill 即可出 PPT。触发：用 GHB 模板做PPT、生成演示文稿、GHB PPT、保留模板母版和首页格式、模板母版统一、续接致谢页。
---

# GHB-PPT-SKILL

> 用自带的 `GHB_PPT_模板.pptx` 生成 PPT：**封面**用 template-fill 克隆模板首页并填文本，**正文**走 SVG 流水线生成富视觉内容，**末页**续接模板致谢页；最后通过 OOXML 母版注入合并，让全 deck 每一页都挂在模板母版下（背景装饰图透出）。**自包含**——ppt-master 的用到的脚本已 vendor 进 `scripts/ppt_master/`，模板放 `templates/`，用户只装本 skill + python-pptx 即可。

## 何时使用

| 信号 | 例子 |
|------|------|
| 要用 GHB 模板做 PPT | "用这个模板做 PPT"、"按 GHB 模板填充" |
| 要保留模板母版/首页 | "保留模板母版和首页格式"、"母版不要变" |
| 模板缺正文版式 | 模板只有封面/章节/致谢页，没有可填正文的内容版式 |
| 正文要视觉丰富 | 不满足纯文本填槽，要卡片/表格/结构化布局 |
| 要续接致谢页 | 末页用模板原致谢页 |

**不要用于**：完全自由设计不需要模板（直接自由设计 SVG 即可）；或模板本身有成熟正文版式且只需文本替换（直接 template-fill 即可，不必走 SVG 流水线）。

## 前置依赖

- **本 skill 自包含**：`scripts/ppt_master/`（vendor 自 ppt-master 的 7 个脚本 + 3 个内部包）、`scripts/merge_template_master.py`（母版统一合并，纯标准库）、`scripts/fix_cover_font.py`（封面字体修复，纯标准库）、`templates/GHB_PPT_模板.pptx`（自带模板）。
- **python-pptx**（`pip install python-pptx`）——仅 Phase 5 校验用。
- **不再依赖外部 ppt-master skill**。

## 环境变量

```bash
SKILL_DIR=<本 skill 根目录>                 # 即 GHB-PPT-SKILL/
VENV_PY=python3                              # 需 python-pptx（仅校验用）
TEMPLATE="$SKILL_DIR/templates/GHB_PPT_模板.pptx"   # 自带模板
PM="$SKILL_DIR/scripts/ppt_master"           # vendored ppt-master 脚本
MERGE="$SKILL_DIR/scripts/merge_template_master.py"
FIXFONT="$SKILL_DIR/scripts/fix_cover_font.py"
```

## 模板已知事实（Phase 0 已预分析）

`GHB_PPT_模板.pptx` 结构固定，无需每次重新分析：

| 项 | 值 | 用途 |
|----|----|----|
| 总页数 | 4 | slide1 封面 / slide2-3 章节 / slide4 致谢 |
| 封面页 | slide1 → slideLayout1 | template-fill 克隆目标 |
| 正文背景版式 | slideLayout2（章节页用，引 image1 满铺 + image2 角装饰） | `--content-layout 2` |
| 致谢页 | slide4 → slideLayout3（引 image3/4/5） | 默认续接（模板最后一页） |
| 品牌色 | `#AB1F29` | `spec_lock.colors.primary` |
| 第二强调色 | `#44546A`（模板 theme dk2） | `spec_lock.colors.secondary_accent`（对比双色） |
| 标题字体 | Arial Black | `spec_lock.typography.title_family` |
| 正文字体 | Microsoft YaHei（CJK）/ Arial | `spec_lock.typography.font_family` |
| 封面原字体 | **楷体**（需 Phase 1 改微软雅黑与正文一致） | `fix_cover_font.py` 处理 |

> 如换用其他模板，按 [`references/template-analysis.md`](references/template-analysis.md) 重新分析，更新上表与 `--content-layout`。

## 核心思路

模板只有封面/章节/致谢页 → 正文无法直接填槽。分两条线再合并，末尾续接致谢页：

```
模板.pptx ─┬─→ template-fill 克隆封面 + 填文本 ──→ cover.pptx (真模板母版)
           │      └→ fix_cover_font 楷体→微软雅黑
           └─→ (母版/版式/主题/背景图 由合并脚本注入)
                                        ↓
Markdown 源 ──→ SVG 流水线 ──→ content.pptx (白底，删 bg 后透明)
             (spec_lock 锁品牌色/字体)        │
                                              ↓ 移除正文白底
                              merge_template_master.py
                              注入模板母版+章节版式+背景图，
                              正文页版式指向模板章节版式，
                              封面置顶，致谢页续接末尾
                                              ↓
                        final.pptx (1 封面 + N 正文 + 1 致谢，全挂模板母版)
```

关键点：**删掉正文 SVG 的白色背景矩形**让模板母版背景透出；合并脚本把正文页版式引用改指向模板章节版式；封面与致谢页各自挂自己的模板版式。

---

## 工作流（5 阶段）

### Phase 1 — 封面生成（template-fill + 字体修复）

```bash
# 1. 分析模板，得文本槽
$VENV_PY "$PM/template_fill_pptx.py" analyze "$TEMPLATE" -o analysis/slide_library.json

# 2. 手写 cover_fill_plan.json（封面 3 个 slot：s01_sh8 标题 / s01_sh6 副标题 / s01_sh4 日期）
#    schema见 $PM/template_fill_pptx.py（template_fill_pptx_plan.v1）

# 3. 应用 → cover.pptx（apply 会自动加时间戳，重命名为 cover.pptx）
$VENV_PY "$PM/template_fill_pptx.py" apply "$TEMPLATE" analysis/cover_fill_plan.json -o exports/cover.pptx
mv exports/cover_*.pptx exports/cover.pptx

# 4. 字体修复：模板封面用楷体，改成微软雅黑（与正文 SVG 一致）
$VENV_PY "$FIXFONT" exports/cover.pptx
```

> 封面 slot：`s01_sh8`=主标题（Arial Black，sz 4400）、`s01_sh6`=副标题、`s01_sh4`=日期。文本别太长（副标题槽 ~915px，超长 check-plan 会 warn）。

### Phase 2 — 正文 SVG 生成

为正文页走 SVG 流水线，**spec_lock 锁定模板品牌色与字体**。每页统一 chrome + 半透明白色内容面板（让模板背景作淡色底 + 页缘框透出）。

```bash
# 1. 建项目
$VENV_PY "$PM/project_manager.py" init <name> --format ppt169
cp source.md "$PROJECT/sources/"

# 2. Strategist：写 design_spec.md + spec_lock.md（锁定品牌）
# 3. Executor：逐页手写 SVG → svg_output/NN_name.svg
# 4. 质量检查（0 error 才继续）
$VENV_PY "$PM/svg_quality_checker.py" "$PROJECT"
# 5. 演讲者备注 → notes/total.md（# NN_name 标题，--- 分隔）
```

#### spec_lock 锁定值（GHB 品牌）

```yaml
canvas: viewBox 0 0 1280 720 / PPT 16:9
mode: instructional          # 或按内容选 briefing/narrative
visual_style: swiss-minimal
colors:
  primary: #AB1F29           # 品牌红 — Superpowers 侧 / 通用强调
  secondary_accent: #44546A  # 模板 theme dk2 — 对比第二色
  success: #2E7D32           # 优点
  warning: #B26A00           # 缺点
  text: #2B2B2B / text_secondary: #6E6E73 / muted: #999999
  border: #E0E0E0 / surface_alt: #F6F6F7 / bg: #FFFFFF
typography:
  font_family: "'Microsoft YaHei', Arial, sans-serif"
  title_family: "'Arial Black', 'Microsoft YaHei', Arial, sans-serif"
  code_family: "Consolas, 'Courier New', monospace"
  body: 18 / title: 30 / subtitle: 22 / annotation: 13
```

#### 每页统一 chrome（调整后标准坐标，已下移 40 让顶部背景装饰透出）

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <defs><!-- 页面级 filter/gradient 按需 --></defs>
  <!-- 白底：Phase 3 会删，先保留便于单页预览 -->
  <g id="bg"><rect width="1280" height="720" fill="#FFFFFF"/></g>
  <!-- 半透明白色内容面板：让模板背景作淡色底 + 页缘框 -->
  <g id="bg-surface">
    <rect x="56" y="96" width="1168" height="608" rx="12" fill="#FFFFFF" fill-opacity="0.92" stroke="#E0E0E0" stroke-width="1"/>
  </g>
  <g id="header">
    <rect x="88" y="132" width="6" height="40" fill="#AB1F29"/>            <!-- 红色强调条 -->
    <text x="108" y="162" font-size="30" font-weight="bold" fill="#2B2B2B" font-family="'Arial Black', 'Microsoft YaHei', Arial, sans-serif">页面标题</text>
    <line x1="88" y1="190" x2="1192" y2="190" stroke="#E0E0E0" stroke-width="1"/>  <!-- 发丝线 -->
    <text x="1192" y="162" text-anchor="end" font-size="14" fill="#AB1F29" font-family="'Microsoft YaHei', Arial, sans-serif">Part X · Label</text>
  </g>
  <g id="footer">
    <text x="1192" y="696" text-anchor="end" font-size="13" fill="#999999" font-family="'Microsoft YaHei', Arial, sans-serif">NN / 总页数</text>
  </g>
  <!-- 内容 <g id="..."> 3–8 个，置于 y=210..670 区域 -->
</svg>
```

> **设计要点**：内容面板 `y=96`（下移 40px，留顶部 ~96px 让模板 image1 顶部装饰透出）；`fill-opacity="0.92"` 让模板背景作整页淡色底。`<g id="bg-surface">` 含 `bg` 词干会被导出器当 chrome（不参与动画），且 Phase 3 删除正则只匹配 `<g id="bg">` 精确名，不会误删。

**SVG 技术约束**（违反即导出失败）：viewBox=0 0 1280 720；HEX 色 + fill-opacity（禁 rgba / `<g opacity>`）；一行逻辑文本=一个 `<text>`+内联 `<tspan>`（内联 tspan 不得带 x/y/dy）；字体栈以预装家族结尾；禁 mask/style/class/foreignObject/`<symbol>`+`<use>`/textPath/animate。完整清单见 `scripts/ppt_master` 上游 shared-standards。本 skill 流程不用图标/图片/图表（纯排版+形状+色彩），故无需 `templates/icons`。

### Phase 3 — 移除正文白底 + 导出 content.pptx

```bash
# 删除每页 <g id="bg"> 白矩形（正则一次性）
$VENV_PY -c "
import re,glob,os
pat=re.compile(r'<g id=\"bg\">\s*<rect[^>]*/>\s*</g>\s*\n?', re.S)
for f in glob.glob('$PROJECT/svg_output/*.svg'):
    s=open(f,encoding='utf-8').read(); s2=pat.sub('',s,1)
    if s2!=s: open(f,'w',encoding='utf-8').write(s2)
"

# 后处理三步（顺序不可换，逐个执行）
$VENV_PY "$PM/total_md_split.py" "$PROJECT"
$VENV_PY "$PM/finalize_svg.py" "$PROJECT"
$VENV_PY "$PM/svg_to_pptx.py" "$PROJECT"
# → exports/<name>_<ts>.pptx (content.pptx，正文页无强制白底)
```

验证正文页透明：解包 content.pptx，查 `ppt/slides/slide1.xml` 应**无** `<p:bg>` 且无全幅 rect。

### Phase 4 — 母版统一合并（含致谢页）

```bash
$VENV_PY "$MERGE" \
  --content       "$PROJECT/exports/content.pptx" \
  --template      "$TEMPLATE" \
  --cover         "$PROJECT/exports/cover.pptx" \
  --content-layout 2 \
  --output        "$PROJECT/exports/final.pptx"
# 默认续接模板最后一页(slide4)作致谢页；--no-ending 跳过；--ending-slide N 指定
```

脚本做的事：

1. 注入模板 `slideMaster1`→`slideMaster2`（修剪 `sldLayoutIdLst`）+ 封面版式 + 内容版式 + 致谢版式 + `theme1`→`theme2` + 所有背景图（image1/2/3/4/5/6）
2. 33 张正文页版式 rels 改指向注入的内容版式
3. 封面 slide 置顶（挂封面版式）
4. **致谢页续接末尾**（克隆模板最后一页 + 其版式 + 装饰图，挂模板母版）
5. 改写 `presentation.xml` / `presentation.xml.rels` / `[Content_Types].xml`

### Phase 5 — 校验

```bash
# 1. python-pptx 打开 + 页数 = 1 封面 + N 正文 + 1 致谢
$VENV_PY -c "from pptx import Presentation; p=Presentation('final.pptx'); print(len(list(p.slides)))"

# 2. ppt_to_md 回读，确认文本/结构完整
$VENV_PY "$PM/source_to_md/ppt_to_md.py" final.pptx

# 3. 挂载链核验（封面→封面版式→模板母版；正文→内容版式→模板母版；致谢→致谢版式→模板母版）
```

校验清单：

- [ ] python-pptx 打开无异常，页数 = 1 封面 + N 正文 + 1 致谢
- [ ] ppt_to_md 回读，封面 + 正文 + 致谢文本齐全
- [ ] 封面 slide 挂 `slideLayout{cover}` → `slideMaster2`
- [ ] 正文 slide 挂 `slideLayout{content}` → `slideMaster2`
- [ ] 致谢 slide 挂 `slideLayout{ending}` → `slideMaster2`
- [ ] `slideMaster2` 引用模板背景图 + theme2
- [ ] `[Content_Types].xml` 有 png Default + 各新部件 Override
- [ ] 封面字体为微软雅黑（无楷体/Arial）
- [ ] 正文白框下移 40（面板 y=96），顶部模板装饰透出

---

## 决策要点

### 选 `--content-layout`（正文背景版式）

- GHB 模板固定用 `slideLayout2`（章节页，image1 满铺背景）。
- 换模板时选章节/内容页用的版式（其背景装饰图最适合作正文背景），避免选封面版式。

### SVG spec 锁定模板品牌

- `spec_lock.colors.primary` = `#AB1F29`；`secondary_accent` = `#44546A`（对比双色）。
- 字体栈与模板一致（Arial Black / Microsoft YaHei），结尾 PPT-safe。
- 正文 SVG 内容（标题/卡片/强调色）与模板母版背景视觉统一。

### 封面字体必须修复

- 模板封面文本原用**楷体**，与正文（微软雅黑）不一致。`template-fill apply` 后必须跑 `fix_cover_font.py` 改成微软雅黑，否则首页楷体突兀。

### 白框下移 40（面板 y=96）

- 内容面板默认 `y=56` 会盖住模板背景顶部装饰。下移 40 到 `y=96`，留顶部装饰透出，底部仍留 16px 边距。已固化为 chrome 标准。

## 常见问题

| 问题 | 处理 |
|------|------|
| 合并后 python-pptx 报 "no content-type for partname" | `[Content_Types].xml` 漏了 png Default 或某 Override；检查 merge 脚本正则是否匹配（无前缀 `<Types>` 用 `(?:\w+:)?` 可选前缀） |
| 正文页背景仍是白色 | Phase 3 没删干净 SVG 白底，或 content slide 仍有 `<p:bg>`；重新删 `<g id="bg">` 并确认导出后 slide XML 无全幅 rect |
| 模板装饰图与正文卡片重叠难读 | 内容已在半透明白色面板（fill-opacity 0.92）上，可读性有保障；个别页可再加一层半透明白底面板 |
| 封面备注丢失 | 合并脚本默认丢弃 cover 的 notesSlide（避免 notesMaster 冲突）；如需可在 Phase 5 后用 python-pptx 单独给封面加备注 |
| 封面显示楷体 | 忘跑 `fix_cover_font.py`；补跑即可 |
| 正文页挂载仍指向 SVG 母版 | merge 脚本的 rels 正则 `Target="\.\./slideLayouts/slideLayout\d+\.xml"` 未命中；检查 content slide rels 格式 |
| 致谢页没出现 | 用了 `--no-ending`；默认即续接，或 `--ending-slide N` 指定模板页号 |

## 产物结构

```
project/
├── sources/            # Markdown 源
├── analysis/           # slide_library.json + cover_fill_plan.json
├── svg_output/         # 正文 SVG（白底已删，chrome 含 translate/或 y=96 坐标）
├── notes/              # 演讲者备注
├── design_spec.md / spec_lock.md
├── exports/
│   ├── cover.pptx          # template-fill 封面半成品（字体已修复）
│   ├── content_<ts>.pptx   # SVG 正文半成品（无白底）
│   └── final.pptx          # ✅ 最终交付（封面 + 正文 + 致谢，全页模板母版）
└── merge_template_master.py 调用记录
```

## skill 自身结构

```
GHB-PPT-SKILL/
├── SKILL.md                         # 本文件
├── templates/GHB_PPT_模板.pptx       # 自带模板
├── scripts/
│   ├── merge_template_master.py     # 母版统一合并（含致谢页续接），纯标准库
│   ├── fix_cover_font.py            # 封面字体楷体→微软雅黑，纯标准库
│   └── ppt_master/                  # vendor 自 ppt-master 的脚本（自包含）
│       ├── project_manager.py / template_fill_pptx.py / svg_quality_checker.py
│       ├── total_md_split.py / finalize_svg.py / svg_to_pptx.py
│       ├── config.py / error_helper.py / pptx_animations.py / project_utils.py
│       ├── source_to_md/ (ppt_to_md.py ...)
│       ├── svg_to_pptx/  (DrawingML 转换包)
│       ├── svg_finalize/ (SVG 后处理包)
│       └── template_fill_pptx/ (template-fill 包)
├── references/template-analysis.md  # 换模板时的结构分析方法
└── (可选) 示例源 md
```

## 参考

- [references/template-analysis.md](references/template-analysis.md) — 换模板时的结构分析方法
- `scripts/merge_template_master.py --help` — 合并脚本参数（含 `--ending-slide` / `--no-ending`）
- `scripts/fix_cover_font.py` — 封面字体修复
- vendor 自 ppt-master 的脚本位于 `scripts/ppt_master/`，用法与上游一致
