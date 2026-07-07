# GHB-PPT-SKILL

> 用自带 **GHB 模板**生成完整演示文稿的**自包含** pi skill。封面 template-fill 保留模板首页格式、正文走 SVG 流水线生成富视觉内容、末页续接模板致谢页，最后通过 OOXML 母版注入合并，让全 deck 每一页都挂在模板母版下（背景装饰图透出）。安装本 skill + `python-pptx` + `requests` + `Pillow` 即可出 PPT，无需另装任何依赖 skill；配图增强（联网搜图/AI 生图/图标）已内置，可选联网/key。

---

## 这是什么

解决一个常见困境：用户给一个 `.pptx` 模板 + 内容素材，要求"保留模板母版和首页格式"，但模板往往**只有封面/章节/致谢页、没有可填正文的版式**。直接 `template-fill` 没版式可填；直接走 SVG 流水线又丢了模板母版。本 skill 用"**两线并行再合并 + 末尾续接致谢页**"绕过这个困境：

```
模板.pptx ─┬─→ template-fill 克隆封面 + 填文本 ──→ cover.pptx (真模板母版)
           │      └→ fix_cover_font 楷体→微软雅黑
           └─→ (母版/版式/主题/背景图 由合并脚本注入)
                                        ↓
Markdown 源 ──→ SVG 流水线 ──→ content.pptx (删白底后透明)
             (spec_lock 锁品牌色/字体)        │
                                              ↓
                              merge_template_master.py
                              注入模板母版+章节版式+背景图，
                              正文页版式指向模板章节版式，
                              封面置顶，致谢页续接末尾
                                              ↓
                        final.pptx (1 封面 + N 正文 + 1 致谢，全挂模板母版)
```

关键技巧：**删掉正文 SVG 的白色背景矩形**让模板母版背景透出；合并脚本把正文页版式引用改指向模板章节版式；封面与致谢页各自挂自己的模板版式。

## 核心特性

- **保留模板母版**：全 deck 每一页（封面/正文/致谢）都挂在模板 `slideMaster` 下，背景装饰图透出。
- **封面保真**：template-fill 克隆模板首页填文本，保留真模板封面格式。
- **正文富视觉**：SVG 流水线手写正文（卡片/表格/流程图/对比表），spec_lock 锁定模板品牌色与字体，视觉与模板统一。
- **末页致谢续接**：自动克隆模板最后一页作致谢页，挂模板母版。
- **自包含**：ppt-master 用到的脚本（含联网搜图/AI 生图）已 vendor 进 `scripts/ppt_master/`，模板放 `templates/`、图标放 `templates/icons/`，外部依赖 `python-pptx` + `requests` + `Pillow`（配图增强可选联网/key）。
- **封面字体修复**：模板封面原用楷体，自动改成微软雅黑与正文一致。

## 快速开始

```bash
pip install python-pptx requests Pillow   # python-pptx 校验用；requests+Pillow 配图管线用
```

```bash
SKILL_DIR=<本 skill 根目录>
VENV_PY=python3
TEMPLATE="$SKILL_DIR/templates/GHB_PPT_模板.pptx"
PM="$SKILL_DIR/scripts/ppt_master"
PROJECT=projects/<name>

# Phase 1 — 封面（template-fill + 字体修复）
$VENV_PY "$PM/template_fill_pptx.py" analyze "$TEMPLATE" -o $PROJECT/analysis/slide_library.json
#   手写 cover_fill_plan.json（封面 slot: s01_sh8 标题 / s01_sh6 副标题 / s01_sh4 日期）
$VENV_PY "$PM/template_fill_pptx.py" apply "$TEMPLATE" $PROJECT/analysis/cover_fill_plan.json -o $PROJECT/exports/cover.pptx
$VENV_PY "$SKILL_DIR/scripts/fix_cover_font.py" $PROJECT/exports/cover.pptx

# Phase 2 — 正文 SVG（手写 design_spec/spec_lock + 逐页 SVG → svg_output/，spec_lock 锁 #AB1F29 / Arial Black / Microsoft YaHei）
$VENV_PY "$PM/project_manager.py" init <name> --format ppt169
$VENV_PY "$PM/svg_quality_checker.py" "$PROJECT"        # 0 error 才继续

# Phase 3 — 删白底 + 导出 content
#   删除每页 <g id="bg"> 白矩形（见 SKILL.md 正则）
$VENV_PY "$PM/total_md_split.py" "$PROJECT"
$VENV_PY "$PM/finalize_svg.py" "$PROJECT"
$VENV_PY "$PM/svg_to_pptx.py" "$PROJECT"

# Phase 4 — 母版统一合并（含致谢页续接）
$VENV_PY "$SKILL_DIR/scripts/merge_template_master.py" \
  --content $PROJECT/exports/content.pptx --template "$TEMPLATE" \
  --cover $PROJECT/exports/cover.pptx --content-layout 2 \
  --output $PROJECT/exports/final.pptx

# Phase 5 — 校验
$VENV_PY -c "from pptx import Presentation; print(len(list(Presentation('$PROJECT/exports/final.pptx').slides)))"
```

完整字段约束、chrome 标准、决策要点见 [`SKILL.md`](SKILL.md)。

## 工作流（5 阶段）

| 阶段 | 做什么 | 产物 |
|------|--------|------|
| Phase 1 | template-fill 克隆封面填文本 + 楷体→微软雅黑 | `cover.pptx` |
| Phase 2 | 手写 design_spec/spec_lock + 逐页 SVG（锁品牌色/字体，统一 chrome） | `svg_output/*.svg` |
| Phase 3 | 删 `<g id="bg">` 白底 + 后处理三步导出 | `content.pptx`（正文页透明）|
| Phase 4 | 母版统一合并：注入母版/版式/主题/背景图，正文挂模板版式，封面置顶，致谢续接 | `final.pptx` |
| Phase 5 | python-pptx + ppt_to_md + 挂载链核验 | — |

## 目录结构

```
GHB-PPT-SKILL/
├── SKILL.md                         # skill 定义（5 阶段工作流 + chrome 标准 + 决策要点）
├── README.md                        # 本文件
├── .gitignore
├── templates/
│   ├── GHB_PPT_模板.pptx            # 自带模板
│   └── icons/                       # 5 套图标（tabler-outline/chunk-filled/...）
├── scripts/
│   ├── merge_template_master.py     # 母版统一合并（含致谢页续接），纯标准库
│   ├── fix_cover_font.py            # 封面字体楷体→微软雅黑，纯标准库
│   └── ppt_master/                  # ⬇ vendor 自 ppt-master 的脚本（详见下节）
│       ├── project_manager.py / template_fill_pptx.py / svg_quality_checker.py
│       ├── total_md_split.py / finalize_svg.py / svg_to_pptx.py
│       ├── image_search.py / image_gen.py   # 联网搜图 / AI 生图（配图）
│       ├── image_backends/ / image_sources/ # 生图后端(15) / 搜图 provider(4)
│       ├── config.py / error_helper.py / pptx_animations.py / project_utils.py
│       ├── source_to_md/            # ppt_to_md.py 等（源→Markdown）
│       ├── svg_to_pptx/             # DrawingML 转换包（SVG→PPTX 核心）
│       ├── svg_finalize/            # SVG 后处理包（图标/图像/文本扁平化/圆角转路径）
│       └── template_fill_pptx/      # template-fill 包（PPTX 文本/表格/图表填充）
└── references/
    ├── template-analysis.md         # 换模板时的结构分析方法
    └── image-{searcher,generator,base}.md / svg-image-embedding.md  # 配图工作流
```

---

## 借鉴 ppt-master（详细说明）

本 skill 的 **SVG→PPTX 核心能力源自 [ppt-master](https://github.com/) skill**（一个 AI 驱动的 SVG 演示文稿生成 skill：源文档 → SVG 页面 → PPTX，多角色协作流水线）。本 skill **并非从零实现** SVG 转 PPTX，而是把 ppt-master 中本流程实际用到的脚本**原样 vendor（内嵌）**进 `scripts/ppt_master/`，并在其上叠加面向 GHB 模板的专用工作流。

### 借鉴了什么

vendor 进来的 ppt-master 脚本（共 81 个 `.py`，含配图管线）：

| 脚本/包 | 作用 | 本 skill 用途 |
|---------|------|---------------|
| `project_manager.py` | 项目初始化/校验 | Phase 2 建项目 |
| `template_fill_pptx.py` + `template_fill_pptx/` 包 | 克隆 PPTX 模板页 + 文本/表格/图表填充 | Phase 1 封面生成 |
| `svg_quality_checker.py` | SVG 质量检查（banned 特性/viewBox/spec_lock 漂移） | Phase 2 质量门 |
| `total_md_split.py` | 演讲者备注拆分 | Phase 3 |
| `finalize_svg.py` + `svg_finalize/` 包 | SVG 后处理（图标嵌入/图像裁剪嵌入/文本扁平化/圆角转路径） | Phase 3 |
| `image_search.py` + `image_sources/` 包 | 联网搜图（Openverse/Wikimedia/Pexels/Pixabay，license 过滤+版权 manifest） | Phase 2.6（⑥D） |
| `image_gen.py` + `image_backends/` 包 | AI 生图（14 后端：openai/gemini/siliconflow…） | Phase 2.6（⑥E） |
| `svg_to_pptx.py` + `svg_to_pptx/` 包 | **SVG→PPTX 原生转换核心**（DrawingML 生成） | Phase 3 导出 |
| `source_to_md/ppt_to_md.py` | PPTX→Markdown 回读 | Phase 5 校验 |
| `config.py` / `error_helper.py` / `pptx_animations.py` / `project_utils.py` | 共享模块 | 上述脚本依赖 |

> vendor 时排除了 `__pycache__`；已引入 ppt-master 的**图标库（`templates/icons/` 5 套）+ 联网搜图（`image_search.py`）+ AI 生图（`image_gen.py`）**，供 ⑥ 配图来源选择；仍未引入图表模板/live preview/confirm UI 等（本流程以排版+形状+色彩+可选配图为主）。

### 为什么 vendor（而不是运行时引用）

- **自包含**：用户装本 skill + `python-pptx` + `requests` + `Pillow` 即可出 PPT，无需另装 ppt-master skill；配图增强（联网搜图/AI 生图/图标）已内置，可选联网/key。满足“安装即用”的要求。
- **版本稳定**：本 skill 的合并脚本依赖 ppt-master 脚本的特定行为（如 `svg_to_pptx` 对 `transform="translate"` 的处理、`finalize_svg` 的圆角转路径）。vendor 后不受 ppt-master 后续变更影响。
- **取舍**：代价是与 ppt-master 代码重复、后续 ppt-master 更新不会自动同步——但这是"独立可用"的必要代价。

### 本 skill 在 ppt-master 基础上做了什么

本 skill **不是** ppt-master 的替代，而是面向 **GHB 模板**的**专用封装**。在 vendor 的 ppt-master 脚本之上，本 skill 自己写了两个脚本 + 一套工作流：

| 本 skill 自有 | 做什么 | 为何 ppt-master 没有 |
|---------------|--------|---------------------|
| `scripts/merge_template_master.py` | 母版统一合并：把模板母版/版式/主题/背景图注入 SVG 生成的 content.pptx，正文页版式重指向模板章节版式，封面置顶，**致谢页续接末尾** | ppt-master 主流水线不处理"SVG 内容叠到用户模板母版上"的场景；这是本 skill 解决"模板只有封面/章节/致谢页"困境的核心 |
| `scripts/fix_cover_font.py` | 封面字体楷体→微软雅黑 | GHB 模板封面原用楷体，与正文不一致；template-fill 只换文本不换字体，需额外修复 |
| SKILL.md 5 阶段工作流 | 封面 template-fill + 正文 SVG + 删白底 + 合并 + 校验 | 把 ppt-master 的 template-fill 工作流与主流水线按 GHB 模板特点串成一条专用线 |
| 调整后 chrome 标准 | 内容面板 `y=96`（下移 40 让模板顶部装饰透出）+ 半透明 `fill-opacity 0.92` | 针对 GHB 模板背景装饰的位置调校 |

简言之：**ppt-master 提供通用的"SVG→PPTX 引擎"和"template-fill"工具；本 skill 提供把它们与 GHB 模板母版缝合起来的"母版统一合并"能力 + 专用工作流。**

### 致谢

- 感谢 **ppt-master skill** 提供的 SVG→PPTX 转换引擎、template-fill 工具与 SVG 技术规范。本 skill 内嵌了其部分脚本（`scripts/ppt_master/`），版权归原作者所有。
- 本 skill 自有脚本（`merge_template_master.py`、`fix_cover_font.py`、SKILL.md 工作流）可自由使用。

---

## 模板事实（GHB_PPT_模板.pptx）

| 项 | 值 |
|----|----|
| 总页数 | 4（slide1 封面 / slide2-3 章节 / slide4 致谢）|
| 封面页 | slide1 → slideLayout1 |
| 正文背景版式 | slideLayout2（image1 满铺 + image2 角装饰）→ `--content-layout 2` |
| 致谢页 | slide4 → slideLayout3（image3/4/5）→ 默认续接 |
| 品牌色 | `#AB1F29` |
| 第二强调色 | `#44546A`（模板 theme dk2）|
| 字体 | 标题 Arial Black / 正文 Microsoft YaHei（封面原楷体，需修复）|

换用其他模板时，按 [`references/template-analysis.md`](references/template-analysis.md) 重新分析并更新上表与 `--content-layout`。

## 常见问题

| 问题 | 处理 |
|------|------|
| 合并后 python-pptx 报 "no content-type" | `[Content_Types].xml` 漏 png Default 或某 Override；检查 merge 脚本正则 |
| 正文页背景仍白色 | Phase 3 没删干净 `<g id="bg">`，或 content slide 仍有 `<p:bg>` |
| 封面显示楷体 | 忘跑 `fix_cover_font.py` |
| 致谢页没出现 | 用了 `--no-ending`；默认即续接，或 `--ending-slide N` 指定 |
| 想用其他模板 | 按 references/template-analysis.md 分析，更新 SKILL.md 模板事实表与 `--content-layout` |

## 许可

- 本 skill 自有代码（`scripts/merge_template_master.py`、`scripts/fix_cover_font.py`、SKILL.md、README）按其原始许可使用。
- `scripts/ppt_master/` 内嵌自 ppt-master 的脚本，版权归原作者所有，遵循 ppt-master 的许可条款。
- `templates/GHB_PPT_模板.pptx` 为用户提供的设计模板。
