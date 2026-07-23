# GHB-PPT-SKILL 现状不足分析与优化建议

日期：2026-07-22
分析对象：当前仓库 `SKILL.md`、统一 CLI `scripts/ghb_ppt.py`、参考文档 `references/*`、脚本层 `scripts/*.py` 与 `scripts/ppt_master/*`、测试 `tests/*`，以及历史分析文档（`docs/*`）。
方法：只读审计代码与文档，交叉核对历史结论是否仍然成立，聚焦"当前仍未闭环"的问题，而非重复已修复项。

---

## 0. 先给结论

> **第二次实施更新（2026-07-22）**：本文后续“8 类合同默认必填、普通
> release 必须逐项 waiver、固定 body surface”描述保留为历史问题背景，
> 已不再代表当前默认行为。当前以 `references/workflow-modes.md` 为准。

### 简化方案实施状态

| 项目 | 状态 | 实现证据 |
|---|---|---|
| Quick / Standard / Strict | 已完成 | `--workflow-mode` 已贯穿 init、plan、合同检查、SVG 门和 build |
| Standard 两文件合同 | 已完成 | 作者只维护 `brief.json + deck_plan.json`，`workflow_profiles.py` 投影兼容合同 |
| Strict 完整治理 | 已完成 | 完整视觉合同、warning waiver、`--review --require-review` 仅 Strict release 强制 |
| 构图自由度 | 已完成 | Standard 不再强制固定 `body_surface`；完整语义/字号合同降为建议 |
| 设计与工程重新分工 | 已完成 | `SKILL.md` 明确 ppt-master 主导逐页设计，GHB 负责品牌、OOXML 与交付验证 |
| 真实素材回归 | 已完成 | `PPT_TEST_SURVEY.md` 生成 20 页 Standard PPTX；LibreOffice 20/20、字体嵌入、人工逐页检查通过 |

当前默认流程是 `确认 → brief/deck plan → ppt-master 逐页设计 → GHB 构建
与 QA`。复杂证据文件仍可由底层生成，但不再是 Standard 作者逐份维护的
输入合同。

### 实施状态（2026-07-22续接）

| 任务 | 状态 | 当前证据 |
|---|---|---|
| P0-1 `plan` + `check-plan` | 已完成 | CLI、草稿标记、合同漂移与定向测试已落地 |
| P0-2 组件 schema + 卡内均衡 | 已完成 | `ghb.layout-schema.v1`、可执行建议、`component-void`/槽位检查与坏例测试 |
| P0-3 字体嵌入 | 已完成 | `--embed-fonts`、fsType守卫、报告字段、真实 Source Han Sans SC 子集嵌入冒烟测试 |
| P1-4 `template_profile.json` | 已完成 | analyze-template输出profile；封面、页眉/正文质量门、合并默认值读取；任意模板从OOXML推导版式几何/品牌色，内置GHB使用已评审sidecar |
| P1-5 视觉复核与跨页指标 | 已完成 | 评审请求携带PNG+layout/SVG/结构上下文；响应强制位置框；盒/内容占用率分离；目标渲染器绑定 |
| P1-6 文档收敛 | 已完成 | `references/contracts.md`、文档状态索引与一致性测试 |
| P1-7 视觉坏例回归 | 已完成 | 三组真实坏例固定SVG与具体失败码断言；workflow_dispatch可选LibreOffice+CJK像素指标基线 |
| P2-8 版式语义评分与角色边界 | 已完成 | timeline/matrix/flywheel适配评分与五角色证据边界 |

以上“完成”以代码与自动化回归为准；最终全量测试、Ruff及diff独立复核结果
记录在本次续接任务的交付说明中。

当前 Skill 的**工程底座已经相当成熟**：统一可恢复 CLI、检查点、证据 DAG、release/draft 双策略、warning 逐项豁免、目标渲染器绑定、OOXML 合并硬门、结构/回读验证都已落地并有较高测试覆盖（脚本约 8.8k 行，测试约 6.1k 行）。

但成品质量的**真正瓶颈没有变**，并且新增了几个由"合同越加越多"带来的**新型摩擦**：

1. **上手成本过高**：真实项目在 `build` 前需人工/模型手写 8 类合同文件（`confirmation.json`、`content_model.json`、`art_direction.json`、`visual_profile.json`、`layout_plan.json`、`spec_lock.md`、`design_spec.md`、`cover_fill_plan.json`）＋逐页手绘 SVG，且**没有任何脚手架/生成器**降低这一负担。
2. **视觉正确仍无法自动证明**：占用率仍测"盒子"不测"盒内信息"，无自动化 WPS/PowerPoint 渲染，审美仍靠人工。
3. **中文保真依赖目标环境**：全流程**没有字体嵌入**能力，跨机交付时中文保真度始终无法在本地证明。
4. **模板强绑定**：页眉安全区、封面槽位 ID、母版/主题名、版式索引等仍部分硬编码在 GHB 模板上，换模板成本高。
5. **文档与合同蔓延**：references 约 2.8k 行 + 多份历史 docs，存在漂移与认知负担。

下面逐项展开，并给出可落地、优先级明确的优化方案。

---

## 1. 当前优势（简述，避免重复优化已完成项）

- 统一 CLI + `.ghb/state.json` 检查点 + `.ghb/runs/` 运行日志，支持断点恢复。
- 证据 v2 DAG（`evidence_manifest.py`）按依赖边传播 stale，防止复用旧证据。
- release 策略下未豁免 warning 阻断；`ghb.warning-waivers.v1` 逐项豁免。
- `--target-renderer` 绑定最终 PPTX digest；LibreOffice 证据不能冒充 WPS。
- 六项确认闸门 + `confirmation.json` + `decision_digest`，防止确认漂移。
- OOXML 合并采用动态 ID/part/media 分配、原子替换，并有 D 矩阵回归。
- 结构 / 回读 / 角色字号 `min_font_by_role` 均有最终 PPTX 级校验。

这些属于"稳定下限"能力，已无需重复优化。以下问题属于"提升上限"与"降低摩擦"。

---

## 2. 不足分析（按影响排序）

### P0-A 上手与创作负担过重，且无脚手架

**证据**
- `references/authoring-workflow.md` 要求在 `build` 前创建 8 类合同文件 + 逐页 SVG。
- CLI 子命令（`ghb_ppt.py` L1440+）为 `doctor/init/analyze-template/build-cover/check-svg/check-project/build-content/merge/validate/render/review/report/build`——**没有** `plan`/`scaffold`/`draft` 类命令。
- 历史审计（`current-pipeline-audit.md` §"Phase 2"、`SKILL工作流…20260713.md` §9.1）已明确："正常工作流没有通用内容→SVG 生成器"，至今仍未提供。

**问题**
1. 每个项目从零手写多份强耦合 JSON，合同之间（`content_model` ↔ `layout_plan` ↔ `art_direction` ↔ `visual_profile`）容易互相漂移，`check-project` 只能事后拒绝，无法事前引导。
2. 逐页 SVG 手绘坐标是最大的返工来源（历史三张坏图均源于自由坐标）。
3. `init` 只产出空脚手架默认值，`art_direction.json` 还被明确禁止停留在 init 默认值——即产物起点与验收要求之间存在一段"必须靠模型硬跳"的空白。

**影响**：token 成本高、弱模型难以稳定产出、返工频繁、真实项目冷启动慢。

---

### P0-B 视觉/审美正确仍无法自动证明

**证据**
- `ghb-ppt-format-issues-…20260718.md` §4.4："occupancy 计算的是可见几何并集"，大白卡片本身即被计入，卡内空洞可漏过。0718 已加入比较卡片槽位与流程节点/边检测，但**仅覆盖内置结构版式**；手工编排的 `editorial`/自定义构图仍无 intra-component 均衡检测。
- `render_ghb_pptx.py` 无 `wps`/`powerpoint` 后端（已核实），WPS 证据只能靠外部 `ghb.render-report.v1` 人工导入。
- README §"已知限制"、`optimization-report.md` §"Known limitations" 均承认审美/层级/留白仍是逐页人工复核项。

**问题**：结构 0 error ≠ 视觉通过。跨页节奏、留白均衡、"图形是否真的解释内容"这类软质量既无确定性指标，也无稳定的自动渲染反馈闭环。

---

### P0-C 中文保真依赖目标环境，无字体嵌入

**证据**
- 全仓库脚本**没有任何字体嵌入逻辑**（已核实：`grep embed…font` 无命中）。
- README §"已知限制"、`completion-audit.md` §"Known limitation"：缺 `Source Han Sans SC`/`Microsoft YaHei` 时中文可能丢字/方框，本地无法证明中文保真。
- `SKILL.md` L48：跨机器交付前必须在目标环境再跑 `doctor`——即把风险转嫁给交付环境。

**问题**：企业交付常在 WPS/无思源黑体的机器打开，当前无法在产物内**自带字体**保证一致呈现，保真度始终"未验证"。

---

### P1-D 模板强绑定，换模板成本高

**证据**
- `current-pipeline-audit.md` §4 硬编码清单：封面槽位 `s01_sh8/s01_sh6/s01_sh4`、`slideMaster2/theme2`、固定 master ID `2147483649`、内容面板 `(56,96,1168,608)`、品牌色写死。
- `ghb-ppt-format-issues-…20260718.md` §10 结尾自承："页眉保留区目前是 GHB 内置模板绑定值；若未来允许任意模板，应把该值放进模板分析产物"——尚未落地。

**问题**：`analyze-template` 已能提取部分结构，但页眉安全区、槽位、品牌常量等仍未统一由模板分析产物驱动，导致质量门与模板耦合，换模板需改代码分支。

---

### P1-E 文档与合同蔓延、存在漂移

**证据**
- `references/*` 约 2.8k 行；`docs/*` 有 6+ 份历史分析报告，日期跨度大。
- `current-pipeline-audit.md` §5/§6 明确列出"仅存在于文档的规则"与"实现了但文档未准确描述"的双向漂移。

**问题**：合同（8 类文件 + 众多 `data-*` 语义标记）与说明分散在 SKILL + references + docs 三处，认知负担大，且随迭代持续漂移，新贡献者/模型难以建立单一事实来源。

---

### P1-F 测试/CI 存在视觉与字体盲区

**证据**
- `.github/workflows/offline-regression.yml` 为纯离线、`--no-render` smoke；测试断言结构与失败码，不断言渲染像素。
- 依赖字体的中文渲染、WPS 目标渲染均不在 CI 内。

**问题**：CI 能防结构回归，防不住视觉回归；坏版式的回归样例（0718 §7 建议的三组坏例）是否已全部落地为断言具体失败码的测试，需专项核对补齐。

---

### P2-G 模型能力集中于前置，缺分级降级路径

**证据**
- `SKILL工作流…20260713.md` §1：约 55%–65% 质量责任落在构建前的模型判断（源理解、叙事、版式语义映射、SVG 信息设计）。
- 语义适配虽已加入 timeline/matrix/swimlane/flywheel/comparison 的最小契约，但 `editorial`、自由构图与"选对而非选多"的判断仍无机器评分。

**问题**：整体成品上限强依赖单个强模型的临场发挥，缺少"弱模型也能走的收敛路径"和"选对版式"的可验证评分。

---

## 3. 优化建议（按优先级，落地到命令/文件）

### P0-1 引入规划脚手架，降低冷启动与漂移

新增 `ghb_ppt.py plan` 命令：输入 `sources/source.md` + `confirmation.json`，**确定性生成**以下草稿（供模型细化，而非替代判断）：

- `content_model.json` 草稿：抽取候选论点/证据/来源占位，标注 `claim_id`。
- `layout_plan.json` 草稿：按大纲生成逐页 `page_schema` 骨架，预填 `slide_id/purpose/rhythm` 占位。
- `art_direction.json` / `visual_profile.json`：从确认的 mode 生成非 init-默认的合理起点。

配套：新增 `check-plan` 前置校验（在写 SVG 前就报合同互相漂移），把 `check-project` 的部分错误提前为"引导式建议"。

收益：把"必须硬跳"的空白变成"填空 + 修订"，弱模型也能沿清晰中间态工作，显著减少 token 与返工。

### P0-2 把自由 SVG 收敛为"受约束组件 + 必要定制"

- 让内置结构 renderer（`scripts/ppt_master/svg_layouts.py`）接收**受约束页面 schema**（限定标题长度、节点数、每节点字数、强调项、来源区），生成前先验证 schema，再输出 Office-safe 几何。
- 仅锚点页 / 用户点名的弱页保留完全手绘；其余页优先走组件路径。
- 对手绘 `editorial` 构图补充 **intra-component 槽位均衡检测**（顶/正文/媒体/结论槽位、左右列对称），关闭 0718 遗留的"卡内空洞"漏洞。

收益：把最大返工源（自由坐标）变成参数化，稳定可读性，同时保留创作空间。

### P0-3 增加字体嵌入交付选项

新增 `build --embed-fonts`（或 `merge` 阶段选项），将 `Source Han Sans SC`（授权允许时）子集化嵌入 PPTX（OOXML `fntdata` + `presentation.xml` `embedTrueTypeFonts`）。

- 许可证不允许嵌入时明确失败并提示，不静默跳过。
- `doctor` 与报告记录 `fonts_embedded: true/false`，作为交付可信度证据。

收益：把"中文保真"从"依赖目标环境"变成"产物自带"，直接消除 P0-C 的核心风险。

### P1-4 模板常量全部下沉到模板分析产物

- 扩展 `analyze-template` 输出一份 `template_profile.json`：页眉安全区（Logo/主标题/章节框 x 区间）、封面槽位 ID、母版/主题命名策略、品牌色、内容面板矩形。
- 质量门（页眉碰撞、槽位、字号）与合并器**读该产物**，不再读硬编码常量。
- GHB 内置模板作为该产物的一个预生成实例。

收益：换模板从"改代码分支"变为"重跑 analyze-template"，解耦质量门与模板。

### P1-5 建立视觉反馈的结构化复核闭环

- 将结构报告 + SVG 元数据 + layout plan + 逐页 PNG 汇总为**逐页 QA 输入**，`review` 要求输出"证据位置 + 问题类型 + 建议动作"，禁止模糊美学分。
- 补齐跨页节奏 / 留白均衡的确定性指标（如相邻页密度方差、内容占用率 vs 盒占用率分离统计）。
- 若无法自动 WPS 渲染，则把"外部 WPS PNG 已入 manifest 且与 digest 绑定"设为 release 硬前置（0718 已部分实现，需确认默认强制）。

### P1-6 收敛文档，建立单一事实来源

- 把散落的 `data-*` 语义标记、8 类合同字段整理为一份 `references/contracts.md`（或 schema 目录），作为唯一权威定义；SKILL 与其他 references 只做引用。
- 归档过期 docs（标注 superseded），保留一份"当前有效约束"索引，减少漂移。
- 补 `test_skill_docs.py` 类的链接/字段一致性断言，CI 检测文档-实现漂移。

### P1-7 补齐视觉回归与坏例测试

- 落实 0718 §7 三组坏例（`header-long-title-…`、`comparison-card-internal-void`、`seven-step-flow-…`）为断言**具体失败码**的测试，修复前必挂、修复后必过。
- CI 增加一个"字体可用"的可选 job（自托管或缓存字体），对最小 deck 做渲染像素基线对比。

### P2-8 分级模型策略与版式语义评分

- 在 `check-project` / `plan` 中加入"选对版式"的可验证评分：如 `timeline` 必须含时间序、`matrix` 必须两轴、`flywheel` 必须闭环（部分已有，扩展到评分而非仅二值门）。
- 文档化多角色分工（内容架构 / 版式规划 / SVG 创作 / 工程执行 / 视觉评审），即使同一模型顺序承担也保留阶段边界与独立证据要求。

---

## 3bis. 各项优化的详细实施方案

下面把第 3 节的每条建议展开为可直接开工的方案：涉及文件、数据结构、CLI 签名、核心算法、失败码与测试。所有新增均遵循现有约束——顶层 `scripts/` 加 GHB 适配，动 `scripts/ppt_master/` 前读 `vendor-sync-policy.md` 并加回归测试；未知错误 fail-fast 保留现场，不静默跳过。

### 方案 P0-1：规划脚手架 `plan` + 前置校验 `check-plan`

**目标**：把"从零硬写 8 类合同"变成"生成草稿 → 模型修订 → 前置校验"。

**新增文件**
- `scripts/plan_scaffold.py`：确定性草稿生成器（纯规则，不调用模型）。
- `tests/test_plan_scaffold.py`：草稿字段完整性与 `check-project` 兼容性断言。

**CLI 签名**（在 `ghb_ppt.py` `add_parser` 区新增，位置紧随 `init`）
```
ghb_ppt.py plan --project <dir> [--from-source sources/source.md]
                [--confirmation confirmation.json] [--force] [--dry-run]
ghb_ppt.py check-plan --project <dir>   # 复用 add_project()
```

**生成逻辑**（`plan_scaffold.py`）
1. 读 `confirmation.json.decisions.outline`，逐行生成 `layout_plan.json` 草稿：`slide_id` 用序号；`purpose`/`rhythm` 从 outline 带入；`page_schema` 预填 `page_purpose`、`density`、`emphasis=distributed`（安全默认，绝不臆测 single-focal）、空 `focal_target`；`claim_ids` 留空数组待填。
2. 从 `source.md` 按标题/要点抽取候选论点，生成 `content_model.json` 草稿：每条 `claim` 带自动 `id`（`claim-NN`）、`statement`（截断的原句）、`must_include=false`、`source_reference` 指向对应锚点；**标注 `"draft": true`**，强制模型复核后移除。
3. 从确认的 `mode` 生成 `art_direction.json` / `visual_profile.json` 的**非 init-默认**合理起点（如 briefing→较高密度、narrative→较多 breathing 页），并写 `"origin": "scaffold"` 标记。
4. 所有草稿写 `"needs_review": true`；`build` 若检出未清除的 `needs_review/draft` 标记，release 模式阻断。

**`check-plan` 校验**（新增于 `validate_project_contract.py`，比 `check-project` 早、以"引导式"报错）
- `content_model.claims[].id` ↔ `layout_plan[].claim_ids` 双向引用完整（无悬空/无孤儿）。
- `art_direction.anchor_slides` 命名的 `slide_id` 真实存在于 `layout_plan`。
- `visual_profile` 角色字号下限与 `layout_plan` 声明的密度不矛盾。
- 仍存在 `draft/needs_review/origin=scaffold` 时：`check-plan` 报 **advisory**（提示需细化），`build --quality-policy release` 报 **error**。

**新增失败码**：`plan-contract-drift`、`plan-draft-not-finalized`。

**测试**：给定 fixture 的 `source.md`+`confirmation.json`，断言生成的四份草稿能通过 `check-plan` 的结构校验且带 `needs_review`；清除标记后能通过 `check-project`。

---

### 方案 P0-2：SVG 组件 schema 化 + intra-component 均衡检测

**目标**：把最大返工源（自由坐标）参数化，并补上"卡内空洞/左右失衡"检测。

**A. 组件 schema 入口**（改 `scripts/ppt_master/svg_layouts.py`，属 vendored，需读同步策略 + 回归）
- 为内置结构 renderer 增加受约束入参 schema `ghb.layout-schema.v1`：
```json
{
  "archetype": "comparison",
  "title": {"text": "...", "max_chars": 24},
  "nodes": [{"id":"a","heading":"...","body":"...","max_body_chars":80}],
  "emphasis": {"mode":"distributed"},
  "source": "sources/...#..."
}
```
- 生成前先 `validate_layout_schema()`：标题/节点字数越界、节点数超上限（如 flow>6）直接**返回可执行建议**（缩写、换行、拆页、改 4+3 布局），而非生成后再报溢出。
- 输出仍为 Office-safe DrawingML 兼容几何，并保留既有 `data-*` 语义标记。

**B. intra-component 均衡检测**（新增 `scripts/ghb_component_balance.py`，被 `ghb_visual_quality.py` 调用）
- 对声明了 `data-qa-box` 父组件（卡片/节点）的元素，计算**槽位占用率**：把卡片划分为 top/body/media/verdict 槽位，统计每槽内可见子元素几何面积。
- 失败判据：
  - `component-void`：卡片内容占用率 < 阈值（如 45%）且存在 > 200px 垂直空白带。
  - `component-balance-outlier`：成对比较卡片相同槽位 top/bottom 偏差超阈值（如 > 24px）。
  - `component-slot-overflow`：子元素越出所属卡片边界。
- release 模式为 error，draft 为 warning；覆盖手绘 `editorial` 与内置结构版式。

**测试**：`test_visual_asset_checker.py` 补空洞卡片、左右失衡卡片 fixture，断言各自失败码；schema 越界断言返回建议而非崩溃。

---

### 方案 P0-3：字体子集嵌入 `--embed-fonts`

**目标**：把中文保真从"依赖目标环境"变成"产物自带"。

**新增文件**
- `scripts/embed_fonts.py`：字体子集化 + OOXML 注入。
- `tests/test_embed_fonts.py`。

**CLI**：`merge` 与 `build` 各加 `--embed-fonts`（默认关闭，避免体积/许可证意外）。

**实现步骤**（`embed_fonts.py`）
1. 收集最终 PPTX 全部文本用到的字符集（复用 `ppt_to_md` 回读结果）。
2. 用 `fontTools.subset` 对 `Source Han Sans SC`（及必要 Latin fallback）子集化为 `.fntdata`（PowerPoint 使用的 obfuscated embedded font 格式，含 GUID key XOR 前 32 字节）。
3. 写入 `ppt/fonts/fontN.fntdata`，在 `[Content_Types].xml` 加 `fntdata` 默认扩展，在 `presentation.xml` 加 `<p:embeddedFontLst>` 与对应 rels。
4. 在 `presentation.xml` 设置 `<p:presentation embedTrueTypeFonts="1" saveSubsetFonts="1">`。
5. **许可证守卫**：读字体 `OS/2 fsType`；若禁止嵌入则 fail-fast 并提示，不静默跳过。

**报告与证据**：`quality-report.json` 增 `fonts_embedded`、`embedded_font_names`、`fsType_ok`；`doctor` 报告本机字体是否允许嵌入。

**测试**：断言输出 PPTX 含 `fntdata` part、`embedTrueTypeFonts=1`、Content Types 有 `fntdata`；用受限 fsType 的假字体断言 fail-fast。

---

### 方案 P1-4：模板常量下沉到 `template_profile.json`

**目标**：换模板从"改代码分支"变为"重跑 analyze-template"。

**改动**
- `analyze-template` 增产 `<project>/analysis/template_profile.json`（schema `ghb.template-profile.v1`）：
```json
{
  "cover_slots": {"title":"s01_sh8","subtitle":"s01_sh6","date":"s01_sh4"},
  "header_safe_zones": {"logo":[56,250],"title":[88,900],"section":[930,1280]},
  "body_surface": [56,96,1168,608],
  "brand": {"primary":"#AB1F29","secondary":"#44546A"},
  "master_naming": {"master":"slideMaster2","theme":"theme2"},
  "content_layout_index": 2,
  "ending_slide_index": 4
}
```
- 质量门（页眉碰撞、槽位、字号、封面填充）与 `merge_template_master.py` **改读该产物**；GHB 内置模板作为预生成实例存 `templates/GHB_PPT_模板.profile.json`。
- 硬编码常量保留为"无 profile 时的兼容回退"，但 release 模式要求 profile 存在。

**测试**：对内置模板生成 profile 并断言关键槽位/安全区数值；构造第二个假模板断言质量门读取的是 profile 而非硬编码。

---

### 方案 P1-5：结构化视觉复核闭环 + 跨页指标

**目标**：让"视觉正确"可定位、可回归。

**A. 逐页 QA 输入规范**（改 `review_visual_quality.py`）
- 组装 `review-input.json`：每页含 PNG 路径、layout_plan 记录、SVG 元数据摘要、结构报告问题项。
- 评审输出**强制结构化**：`{slide, issue_type, evidence_bbox, suggested_action}`，禁止仅返回美学分；缺 `evidence_bbox` 视为无效评审（`outcome=error`）。

**B. 跨页确定性指标**（新增 `scripts/ghb_deck_rhythm.py`）
- 相邻页密度方差、内容占用率 vs 盒占用率**分离统计**（直接堵住 P0-B 的"盒子占满即通过"）、锚点页分布是否符合 `art_direction`。
- 输出 advisory 指标进报告，超阈值在 release 提示人工复核。

**C. WPS 证据硬前置**：release 模式下若 `--target-renderer wps|powerpoint`，必须存在与最终 PPTX digest 绑定的外部 `ghb.render-report.v1`，否则阻断（确认默认已强制，未强制则补齐）。

**测试**：断言无 `evidence_bbox` 的评审被判 error；构造密度突变 deck 断言 rhythm 指标告警。

---

### 方案 P1-6：文档收敛与漂移检测

**目标**：建立单一事实来源，抑制文档-实现漂移。

**改动**
- 新增 `references/contracts.md`：集中定义 8 类合同字段 + 全部 `data-*` 语义标记，作为唯一权威；SKILL 与其他 references 只引用不重复。
- `docs/` 过期报告加 `> Status: superseded by <new>` 头，保留一份"当前有效约束"索引。
- 扩展 `tests/test_skill_docs.py`：断言 `contracts.md` 列出的失败码/字段与 `validate_*` 实际使用的常量集合一致（从代码提取 code 常量做集合比对），漂移即 CI 失败。

**测试**：故意在代码增删一个失败码，断言文档一致性测试变红。

---

### 方案 P1-7：视觉回归坏例测试

**目标**：把历史真实坏图固化为"修复前必挂、修复后必过"的断言。

**新增 fixtures**（`tests/fixtures/`）与断言（`test_visual_benchmark.py`）
1. `header-long-title-with-native-section-frame` → 断言 `header-safe-zone-collision`。
2. `comparison-card-internal-void` → 断言 `component-void` / `component-balance-outlier`（依赖 P0-2）。
3. `seven-step-flow-with-long-cjk-labels` → 断言 `text-component-overflow` + `connector-node-intersection`。
- 每例保存 SVG + 预期 issue codes；测试断言**具体失败码**，不只断言非零退出。
- CI 增可选 job：缓存/自托管 CJK 字体，对最小 deck 做渲染像素基线（`render` + 逐页 PNG hash 容差比对）。

---

### 方案 P2-8：版式语义评分 + 模型分工文档

**目标**：把"选对版式"从直觉变为部分可验证，并稳定多角色协作。

**改动**
- 在 `check-project`/`plan` 增 `layout-fit-score`：对每种 archetype 给可验证契约评分而非二值门——`timeline` 需时间序标记数≥2、`matrix` 需两轴且四象限含义、`flywheel` 需成环边、`comparison` 需共享比较维度；低分记 advisory 并给替换建议。
- 新增 `references/authoring-roles.md`：文档化 内容架构/版式规划/SVG 创作/工程执行/视觉评审 五角色的输入证据与产物边界；即使单模型顺序承担也保留阶段边界与独立证据要求。

**测试**：构造"无时间序却用 timeline"的 plan，断言 `layout-fit-score` 低分 + 给出建议。

---

## 4. 建议落地路线图

| 阶段 | 内容 | 关键交付 | 依赖 |
|---|---|---|---|
| 1（P0） | `plan` 脚手架 + `check-plan` 前置校验 | 新命令 + 草稿生成器 + 测试 | 无 |
| 1（P0） | 组件 schema 化 + intra-component 均衡检测 | `svg_layouts.py` schema 入口 + 新失败码 | 无 |
| 1（P0） | 字体嵌入选项 | `--embed-fonts` + 许可证守卫 + 报告字段 | 字体授权 |
| 2（P1） | `template_profile.json` 下沉 | `analyze-template` 扩展 + 质量门改读产物 | 阶段1 |
| 2（P1） | 结构化视觉复核 + 跨页指标 | `review` 输入规范 + 新指标 | 渲染证据 |
| 2（P1） | 文档收敛 + 漂移测试 | `contracts.md` + 一致性断言 | 无 |
| 2（P1） | 视觉回归坏例测试 | 三组 fixture + 失败码断言 | 阶段1 |
| 3（P2） | 版式语义评分 + 模型分工文档 | 评分规则 + 分工说明 | 阶段1-2 |

---

## 5. 明确不建议的做法

- 只换更强模型或继续堆提示词——不改变质量门定义，无法根治坏版式。
- 用整页图片/截图冒充可编辑正文——违反核心约束。
- 为满足多样性配额强套内置结构图——内容语义优先。
- 把模板常量继续硬编码扩展成更多模板分支——应下沉到模板分析产物。
- 静默跳过字体嵌入/渲染缺失并宣称视觉通过——必须如实记录限制。

---

## 6. 一句话总结

当前 Skill 已经很好地解决了"稳定生成结构正确、可编辑、可验证、可恢复的 PPTX"。下一阶段的优化重点应从"再加一道结构门"转向三件事：**降低冷启动创作负担（脚手架 + 组件化）、让中文保真可自带（字体嵌入）、让视觉正确可证明（intra-component 指标 + 结构化复核闭环）**。这三点直接对应当前仍未闭环的上限与摩擦问题。
