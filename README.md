# GHB-PPT-SKILL

使用内置 GHB 模板生成企业级 PPTX：封面保留模板首页，正文由 SVG
转换为可编辑 DrawingML，所有页面继承模板母版和背景装饰，末页默认
续接模板致谢页。

默认流程纯离线运行，不依赖图片 API 或 AI 生图密钥。联网搜图、AI
生图、图标和版权署名能力仍作为可选增强保留。

## 能力边界

- 保留模板封面、母版、主题、背景媒体和致谢页。
- 正文标题、标签、卡片、流程、表格和架构图以可编辑对象为主。
- SVG 是可编辑正文的中间格式；内置图标和结构图均为可选工具，页面
  版式由内容语义决定，不为满足多样性配额强制使用。
- 不使用整页截图或整页图片代替正文。
- 通过统一 CLI 执行封面、SVG 门、导出、OOXML 合并、验证、渲染和
  报告。
- 用 `.ghb/state.json` 和 `.ghb/runs/` 支持失败诊断与断点恢复。
- 用确定性 A/B/C/D fixtures、单元测试和逐页渲染证明质量。

## 安装

需要 Python 3.9+。

```bash
python3 -m pip install -r requirements.txt
python3 scripts/ghb_ppt.py doctor
```

`--embed-fonts` is optional and requires the `fonttools` dependency included in
`requirements.txt`. It refuses fonts whose `OS/2.fsType` forbids embedding and
records actual embedded parts, typeface names, and license evidence in the
quality report.

开发与测试：

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
```

渲染为可选增强，需要 LibreOffice/soffice 和 Poppler `pdftoppm`。没有
渲染器时，构建和 OOXML 验证仍可运行，但不能宣称最终视觉效果通过。

## 快速开始

创建项目并分析模板：

```bash
python3 scripts/ghb_ppt.py init --project projects/demo
python3 scripts/ghb_ppt.py analyze-template \
  --project projects/demo \
  --template templates/GHB_PPT_模板.pptx
```

在 `projects/demo/` 准备：

- `analysis/cover_fill_plan.json`
- `sources/source.md`
- `confirmation.json`（六项确认的机器可读凭证）
- `design_spec.md` 与 `spec_lock.md`
- `content_model.json`（可追溯的论点与不可删减项）
- `art_direction.json`（视觉命题、叙事弧、页面家族、锚点页与图像策略）
- `visual_profile.json`（项目级视觉阈值与预算）
- `layout_plan.json`
- `svg_output/*.svg`
- `notes/total.md`（需要备注时）

完整 authoring 约束见 [SKILL.md](SKILL.md) 和
[references/authoring-workflow.md](references/authoring-workflow.md)。

执行完整构建：

```bash
python3 scripts/ghb_ppt.py build \
  --project projects/demo \
  --template templates/GHB_PPT_模板.pptx \
  --cover-plan projects/demo/analysis/cover_fill_plan.json \
  --output projects/demo/exports/final.pptx \
  --quality-policy release \
  --target-renderer libreoffice \
  --keep-intermediate \
  --repair-attempts 1
```

结果包括最终 PPTX、authored/finalized SVG 报告、最终 JSON/Markdown
报告，以及渲染器可用时的 PDF、逐页 PNG 和 contact sheet。

正式交付默认使用 `--quality-policy release`，未处理 warning 会返回非零。
有意接受的警告用 `ghb.warning-waivers.v1` 文件记录，并通过
`--warning-waivers path/to/warning-waivers.json` 传入。草稿阶段可显式选择
`--quality-policy draft`。用 `--target-renderer auto|libreoffice|powerpoint|wps`
声明目标环境；指定 WPS/PowerPoint 时，LibreOffice 渲染不能冒充目标证据。

## 统一命令

```text
doctor             环境、依赖、模板、字体、渲染器和安装 Skill 漂移检查
init               创建规范项目目录
analyze-template   分析模板槽位、母版和版式
build-cover        生成模板封面并修复字体
check-project      强制校验确认、art direction、视觉合同、内容模型和版式语义
check-svg          运行 authored SVG 综合质量门
build-content      finalize 到独立目录、正式移除白底、导出正文 PPTX
merge              合并封面、正文、模板母版和可选致谢页
validate           验证 ZIP/OOXML/母版/内容/可编辑性/版面
render             生成 PDF、逐页 PNG 和 contact sheet
report             生成 JSON 与 Markdown 质量报告
review             显式运行可选视觉评审并重组最终报告
build              执行完整流水线
```

查看帮助：

```bash
python3 scripts/ghb_ppt.py --help
python3 scripts/ghb_ppt.py build --help
```

常用开关：

- `--dry-run`：只输出执行计划。
- `--keep-intermediate`：保留中间产物。
- `--no-ending`：不续接致谢页。
- `--ending-slide N`：指定模板致谢页。
- `--no-render`：明确跳过渲染。
- `--review`：在 build 中显式运行已配置的可选视觉评审。
- `--require-review`：要求可选评审结果为 `passed`；其他结果阻断交付。
- `--quality-policy draft|release`：选择草稿或阻断式发布判定。
- `--warning-waivers PATH`：显式接受已审批的逐项 warning。
- `--target-renderer auto|libreoffice|powerpoint|wps`：声明目标渲染环境。
- `--repair-attempts 0..3`：限制确定性修复重试次数。

## 流水线

```text
template ── template-fill ── cover-font repair ── cover.pptx
    │
source → content model → art direction → layout plan → authored SVG gate
                     → finalize copy → svg_final background removal
                     → finalized gate → editable content.pptx
    │
    └─ template master/layout/theme/media injection
                     → final.pptx → validate → render → report
```

OOXML 合并使用动态 ID、part 和媒体名分配，避免覆盖已有关系或资源；
输出采用原子替换。详细契约见
[references/ooxml-merge.md](references/ooxml-merge.md)。

## 输出结构

```text
project/
├── analysis/
├── sources/
├── art_direction.json     # deck-level aesthetic contract
├── visual_profile.json    # strict role typography and geometry policy
├── svg_output/            # immutable authored SVG
├── svg_final/             # finalized SVG
├── notes/
├── exports/
│   ├── cover.pptx
│   ├── content.pptx
│   └── final.pptx
├── reports/
│   ├── svg-authored.json
│   ├── svg-finalized.json
│   ├── ppt-readback.md
│   ├── visual-review.json        # 仅显式 review 时
│   ├── quality-report.json
│   └── quality-report.md
├── render/                # PDF, slide-*.png, contact-sheet.png
└── .ghb/
    ├── evidence-manifest.json
    ├── state.json
    └── runs/<timestamp>/run.json
```

## 质量与恢复

每个 `layout_plan.json` 正文记录使用嵌套 `page_schema` 声明用途、密度、
节奏角色、变体和强调。Density is not emphasis：不得从密度或旧
`anchor` 节奏机械推断重点；`single-focal` 必须由 `key_message` 支持并
绑定真实 `focal_target`。

默认视觉合同不是 opt-in：每个可见文本必须有角色元数据，标题/正文默认
不得低于 28/18 pt（SVG 建议至少 38/24 px）；process、comparison、evidence、
metrics、decision、risk 等页面必须提供对应语义标记。最终 PPTX 会再次输出
`min_font_by_role`，防止转换后字号退化。

最终报告检查关系目标、Content Types、ID、母版链、页数与页面角色、
`ppt_to_md` 回读、计划文字、备注、字体、品牌色、对象统计、越界、
重叠、空文本、白底和全幅图片。渲染证据仍需逐页人工复核。

`.ghb/evidence-manifest.json` 使用 v2 DAG，分别绑定 visual profile、art
direction、authored SVG、finalized SVG、PPTX、渲染和最终报告；任一上游
语义或字节变化只按依赖边传播 stale，不能复用旧证据。

遇到中断时，先读 `.ghb/state.json` 和最新 run log，确认输入未变化，
从最后一个有效检查点重跑。详见
[references/quality-and-recovery.md](references/quality-and-recovery.md)。

## 确定性基线

仓库包含四类离线场景和九组组合：技术分享、管理规划、长文本压力、
以及 1/3/10 页正文、不同致谢选项和图标媒体的 OOXML 回归矩阵。

构建完整优化后基线（目录必须不存在）：

```bash
python3 tests/fixtures/build_baseline.py \
  --output artifacts/baseline/after \
  --pipeline unified
```

CI 的最小无 GUI smoke：

```bash
python3 tests/fixtures/build_baseline.py \
  --output /tmp/ghb-smoke \
  --pipeline unified \
  --case D_01_body_default_ending \
  --no-render
```

`.github/workflows/offline-regression.yml` 运行全套离线测试，生成并再次
验证最小 editable PPTX，再上传 PPTX 与 JSON/Markdown 证据。

## 示例项目

- `examples/layout_demos/`：四种结构型版式的最小 SVG 示例。
- `examples/claude_code_arch_demo/`：包含 source、design/spec lock、完整
  layout plan、备注和六页 SVG 的技术分享示例。

从仓库根目录运行各示例目录中的生成脚本，再执行 `check-svg` 或示例
README 中的两个离线质量门。示例用于 authoring 与版式验证，不替代
A/B/C/D 最终 PPTX 基线。

## 已知限制

- 当前环境同时缺少 `Source Han Sans SC`（首选）和 `Microsoft YaHei`
  （兼容回退）时，LibreOffice 可能丢失中文或显示方框。报告会保留警告；
  必须在目标 Office/PowerPoint 环境复核中文。
- 自动检查不能可靠判断所有审美问题，报告会列出人工复核项而不是生成
  虚假美学分数。
- 封面备注默认不复制，以避免 notes master 冲突；正文备注受支持并被
  验证。

## Vendored 边界

通用 template-fill、SVG finalize/转换、source converters、图片后端和
图标资源位于 `scripts/ppt_master/` 与 `templates/icons/`。GHB 专用
编排、白底移除、OOXML 合并、验证和渲染位于顶层 `scripts/`。

同步上游前阅读
[references/vendor-sync-policy.md](references/vendor-sync-policy.md)，只引入
必要路径、记录上游 revision，并运行完整回归与渲染复核。
