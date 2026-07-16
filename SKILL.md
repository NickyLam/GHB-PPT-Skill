---
name: ghb-ppt-skill
description: 使用内置 GHB 模板创建、构建、修复或验证企业演示文稿（.pptx）：template-fill 保留封面，正文 SVG 转可编辑 DrawingML，OOXML 注入模板母版/背景，默认续接致谢页，并生成结构报告与逐页渲染。用于“用 GHB 模板做 PPT”“保留模板母版/首页格式”“生成 GHB 演示文稿”“给模板 PPT 配图”“验证或修复 GHB PPTX”等请求；支持纯离线默认路径及可选联网搜图/AI 生图。
---

# GHB PPT

用统一流水线交付“模板封面 + 可编辑正文 + 模板致谢页”的企业级
PPTX。保留模板母版、主题和背景装饰，不要用整页截图或整页图片冒充
可编辑正文。

## 不可变约束

- 用 `template_fill_pptx.py` 克隆并填充模板首页。
- 用 `fix_cover_font.py` 规范封面字体。
- 用 Office-safe SVG 生成正文，并转换为原生 DrawingML 文本和图形。
- 删除正文 SVG 的预览白底，让模板母版背景透出。
- 用 `merge_template_master.py` 注入模板母版、版式、主题和媒体。
- 默认续接模板最后一页；仅按用户要求使用 `--no-ending` 或
  `--ending-slide N`。
- 保持离线默认路径；不要默认调用图片 API、AI 生图或付费服务。
- 对未知错误立即失败并保留现场；不要吞异常或伪造视觉评分。

## 先判断路径

- 若模板已有成熟正文版式且只需替换文字，直接使用 template-fill；
  不要启动完整 SVG/OOXML 流水线。
- 若不需要 GHB 模板或模板保真，改用自由演示文稿工作流。
- 若需要 GHB 封面/母版/致谢页且正文需结构化视觉表达，使用本流程。
- 若更换模板，先读 [references/template-analysis.md](references/template-analysis.md)
  并运行 `analyze-template`。

## 准备环境

从 Skill 根目录运行：

```bash
python3 -m pip install -r requirements.txt
python3 scripts/ghb_ppt.py doctor
```

`doctor` 检查 Python、依赖、模板、目录权限、字体和渲染器。缺少
LibreOffice 时仍可构建和结构验证，但必须记录“未进行最终渲染”。缺少
Microsoft YaHei 时，不得声称中文视觉效果已经通过。

## 建立项目

```bash
python3 scripts/ghb_ppt.py init --project projects/<name>
python3 scripts/ghb_ppt.py analyze-template \
  --project projects/<name> \
  --template templates/GHB_PPT_模板.pptx
```

按 [references/authoring-workflow.md](references/authoring-workflow.md) 准备
封面计划、源内容、设计规范、`spec_lock.md`、`layout_plan.json`、正文
SVG 和备注。

### 内容确认闸门

真实用户项目在写 `spec_lock.md`、生成 SVG 或取图前，必须一次性确认：

1. 目标受众；
2. 页数范围；
3. `instructional` / `briefing` / `narrative` 模式；
4. 逐页大纲与节奏；
5. 展开、删减和合并策略；
6. 配图来源与图标选择。

每项给出具体选项、推荐及修改方法。等待明确确认。仓库测试和 CI 使用
固定 fixture 配置，不等待用户输入。

确认后立即按 [references/project-contract.md](references/project-contract.md)
写入 `confirmation.json`。真实项目必须记录 `confirmation_source: user`；
测试只能使用 `fixture`。不得在未获得用户明确确认时伪造确认凭证。
`check-project`、`check-svg`、`build-content` 和 `build` 都会强制校验该凭证，
没有生产绕过参数。

## 规划并编写正文

先把来源中的核心论点、证据、不可删减项和来源引用写入
`content_model.json`，再为每页写结论式标题，并在 `layout_plan.json` 中声明用途、关键信息、
密度、节奏、结构、可编辑对象、素材需求、来源和备注。先读：

- [references/svg-layout-catalog.md](references/svg-layout-catalog.md)：页面结构
  与多样性；
- [references/visual-quality-rules.md](references/visual-quality-rules.md)：SVG、
  图片、图标、碰撞、乱码和内容负载硬规则；
- [references/svg-image-embedding.md](references/svg-image-embedding.md)：仅在使用
  图片或图标时读取。

`visual_profile.json` 定义全局字号、间距、占用率、构图和预算；每个正文
记录必须在嵌套 `page_schema` 中声明页面用途、密度、节奏角色、版式变体和
强调意图。Density is not emphasis：不能因为页面较稀疏或旧节奏为
`anchor` 就机械强调第 2 项。只有 `key_message` 明确支持某个可见项目时才
使用 `single-focal`，且 `focal_target` 必须与该项目精确对应；否则使用
`distributed` 或 `ranked`。

每个正文 SVG 必须：

- 使用 `viewBox="0 0 1280 720"`；
- 包含一个可安全删除的 `<g id="bg">` 预览白底；
- 在主内容组写 `data-layout="<layout_archetype>"`；
- 保留标题、正文、卡片、表格、流程和架构为文本/形状；
- 使用 `#AB1F29` 主色、`#44546A` 辅色和 GHB 字体规范；
- 给自由摆放内容提供质量检查所需的边界/角色元数据。

不要用同一种卡片网格伪装版式多样性。长文本依次采用重写、换布局、
拆页、调间距和小幅字号调整；禁止全局缩成不可读小字。

## 构建

推荐直接运行完整流水线：

```bash
python3 scripts/ghb_ppt.py build \
  --project projects/<name> \
  --template templates/GHB_PPT_模板.pptx \
  --cover-plan projects/<name>/analysis/cover_fill_plan.json \
  --output projects/<name>/exports/final.pptx \
  --keep-intermediate \
  --repair-attempts 1
```

`build` 依次执行封面、authored SVG 门、正式白底移除、SVG finalized 门、
可编辑正文导出、碰撞安全 OOXML 合并、预渲染验证、可用时的
LibreOffice 渲染和最终报告。修复重试仅限 `0..3` 次确定性操作。

需要排查或单步执行时使用：

| 命令 | 作用 |
|---|---|
| `doctor` | 检查依赖、字体、模板、渲染器和权限 |
| `init` | 创建规范项目目录 |
| `analyze-template` | 分析模板槽位和版式 |
| `build-cover` | template-fill 封面并修复字体 |
| `check-svg` | 运行 authored SVG 综合门 |
| `check-project` | 强制校验六项确认、内容模型、版式语义和必需文件 |
| `build-content` | 移除白底、finalize 并导出正文 PPTX |
| `merge` | 合并封面、正文、母版和可选致谢页 |
| `validate` | 输出最终结构/内容/可编辑性检查 |
| `render` | 输出 PDF、逐页 PNG 和 contact sheet |
| `review` | 基于新鲜确定性与渲染证据运行一次显式可选视觉评审 |
| `report` | 生成 JSON/Markdown 质量报告 |
| `build` | 执行完整流程并写检查点 |

用 `--dry-run` 查看计划；用 `--no-render` 明确跳过渲染；不要以
`--no-render` 的结果声称视觉验证通过。

默认构建不调用模型。仅当操作者明确提供可信配置时使用 `review` 或
`build --review`；远程适配器还需要单独的披露授权。`--require-review`
只提升可选评审的交付要求，不改变确定性检查结果。

## 验收与修复

打开以下证据：

- `reports/svg-authored.json`
- `reports/svg-finalized.json`
- `reports/ppt-readback.md`
- `reports/quality-report.json`
- `reports/quality-report.md`
- `reports/visual-review.json`（仅显式运行可选评审时）
- `render/contact-sheet.png` 和逐页 PNG（渲染器可用时）
- `.ghb/evidence-manifest.json`、`.ghb/runs/<run>/run.json` 与
  `.ghb/state.json`

按 [references/quality-and-recovery.md](references/quality-and-recovery.md)
逐页检查。至少确认：页数/角色正确、母版链完整、无悬空关系、无白底、
无整页图片、计划文字和备注存在、正文对象不越界、没有明显遮挡/乱码/
占位符、页面结构与 `layout_plan.json` 一致。

若合并异常，读 [references/ooxml-merge.md](references/ooxml-merge.md)。
修复后必须重新构建、验证、渲染并复核受影响页面。保留失败 run，不要
覆盖原始证据。

## 可选配图

默认使用无图或内置图标。只有用户确认后再选择：

- 源材料提取或用户自备：读
  [references/svg-image-embedding.md](references/svg-image-embedding.md)；
- 联网搜图：读 [references/image-searcher.md](references/image-searcher.md)，
  按 license tier 记录来源并在需要时内联署名；
- AI 生图：读 [references/image-generator.md](references/image-generator.md)，
  使用用户授权的后端和密钥。

不要删除联网搜图、AI 生图、图标和版权能力；也不要让它们成为离线
构建的必需条件。

## 完成交付

交付最终 PPTX、源/最终 SVG、中间 PPTX、运行日志、状态文件、JSON 与
Markdown 报告、逐页渲染和 contact sheet。明确列出渲染器、字体替换、
备注支持和人工复核限制。

只有在所有可用硬门通过、每页已检查且已知限制被准确记录后，才宣告
完成。中断后从 `.ghb/state.json` 的最后有效检查点恢复。

## 维护边界

优先在顶层 `scripts/` 添加 GHB 适配。修改 `scripts/ppt_master/` 前先读
[references/vendor-sync-policy.md](references/vendor-sync-policy.md)，保持改动
窄小、注释明确并添加回归测试。
