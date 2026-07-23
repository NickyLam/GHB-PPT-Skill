---
name: ghb-ppt-skill
description: 使用内置 GHB 模板创建、构建、修复或验证企业演示文稿（.pptx）。默认由 ppt-master 负责逐页内容设计和 SVG 创作，GHB 负责品牌模板、可编辑 DrawingML、OOXML 合并、兼容性与交付验证。支持 Quick、Standard、Strict 三种工作流。
---

# GHB PPT

交付“GHB 模板封面 + 逐页设计的可编辑正文 + 模板致谢页”。默认使用
`Standard`；不要把普通项目自动升级为完整审计流程。

## 职责边界

### ppt-master：设计主流程

- 理解来源、规划叙事和拆页；
- 为每页选择内容驱动的构图；
- 当前主代理逐页、顺序创作 SVG，并通过实时预览迭代；
- 关键结论页、章节锚点页和用户点名的问题页必须专门设计；
- 禁止用通用卡片函数或生成脚本批量决定整套正文构图。

### GHB：模板与交付底座

- 填充封面，保留品牌、母版、主题、页眉和致谢页；
- 将 Office-safe SVG 转成可编辑 DrawingML；
- 合并 OOXML，处理字体和目标渲染器兼容；
- 执行结构、溢出、渲染、回读和交付检查。

## 选择工作流

| 模式 | 使用场景 | 作者维护的合同 | 硬门 |
|---|---|---|---|
| `quick` | 草稿、内部预览 | 来源 + SVG | 可构建、可打开、无明显越界、可渲染 |
| `standard` | 默认正式演示 | `brief.json` + `deck_plan.json` | 确认、来源、可编辑、结构/溢出、渲染、人工逐页检查 |
| `strict` | 外部发布、审计敏感 | 完整 legacy 合同与证据 | Standard 全部 + 完整视觉合同、warning 处置、强制视觉评审 |

详细定义见 [references/workflow-modes.md](references/workflow-modes.md)。

### 默认选择规则

- 没有特别说明：`standard`。
- 用户明确说草稿、快速预览：`quick`。
- 用户明确要求审计、严格发布、完整证据：`strict`。
- 模板已有成熟正文版式且只换文字：直接用 template-fill，不启动 SVG 流程。
- 不需要 GHB 模板保真：改用自由演示文稿工作流。

## 不可变交付约束

- 用 `template_fill_pptx.py` 填充模板首页，用 `fix_cover_font.py` 规范封面字体。
- 正文使用 Office-safe SVG，并转换为原生 DrawingML 文本和图形；禁止整页截图冒充正文。
- 正式构建只从 `svg_final/` 删除预览白底；不得原地改写 `svg_output/`。
- 用 `merge_template_master.py` 注入模板母版、版式、主题和媒体。
- 默认续接模板最后一页；只有用户要求时才使用 `--no-ending`。
- 默认离线，不自动调用图片 API、AI 生图或付费服务。
- 未知错误立即失败并保留现场；不得伪造视觉评分或确认凭证。

## Standard 主流程

```text
来源 → 一次确认 → brief.json + deck_plan.json
    → ppt-master 逐页设计与 SVG 预览
    → GHB 模板/OOXML 构建
    → 自动检查 → 渲染 → 人工逐页检查 → 交付
```

### 1. 一次确认

在创作正文前，用一组简短建议一次确认：

1. 受众与用途；
2. 页数或演讲时长；
3. `instructional` / `briefing` / `narrative`；
4. 逐页大纲和保留/压缩策略；
5. 视觉风格；
6. 图片和图标来源。

用户确认后写 `brief.json`，不要让用户分别确认内容模型、艺术方向、视觉画像
和布局合同。`deck_plan.json` 只记录故事、风格和逐页设计意图。字段以
[references/workflow-modes.md](references/workflow-modes.md) 为准。

### 可选内容档案（默认不启用）

`deck_plan.json.style.content_profile` 仅在用户明确需要某种内容组织方法时设置。
首个档案 `consulting-evidence-cn-v1` 用“结论先行、比较证据、业务含义”组织内容；
选择后，在写 SVG 前读取
[references/content-styles/consulting-evidence-cn-v1.md](references/content-styles/consulting-evidence-cn-v1.md)。

- 它不替代 `visual_style`，不改变 GHB 模板、颜色、字体或封面；
- 未设置时保持当前内容生成与投影行为；
- 事实型页面的 `consulting_content` 必须能回溯到 `source_refs`，推断和建议必须显式标注。

### 可选咨询研究型视觉档案（默认不启用）

当用户明确要求“麦肯锡式 / 咨询研究报告式”的**视觉呈现**时，在
`deck_plan.json.style.visual_profile` 写入 `consulting-research-cn-v1`，并在写 SVG 前读取
[references/visual-styles/consulting-research-cn-v1.md](references/visual-styles/consulting-research-cn-v1.md)。

- 该档案是附件可观察到的研究版式规律的转译，不复制 McKinsey 标志、名称、字体文件或版式资产；
- 它与 `content_profile` 独立：可与 `consulting-evidence-cn-v1` 组合使用，也可单独选择；
- 选中后，保留 GHB 正文页的左上 Logo、右上原生章节标题框和模板空白正文底版；咨询研究式标题、证据图和来源只在页眉下方安全区生成，并用 `template-section-label` 写回右上原生框；
- 未设置时，**不得**改变 GHB 默认颜色、页眉、字体或既有生成结果；未知档案在投影前失败。

### 2. 建立项目与投影兼容合同

```bash
python3 scripts/ghb_ppt.py init \
  --project projects/<name> \
  --workflow-mode standard

python3 scripts/ghb_ppt.py plan \
  --project projects/<name> \
  --workflow-mode standard
```

`plan` 从 `brief.json + deck_plan.json` 确定性投影旧转换器需要的兼容文件。
这些文件是内部实现，不再要求用户逐份编写。旧项目没有简化合同文件时仍按
原合同兼容构建，不会被自动覆盖。

### 3. 逐页设计正文

创作前读取 ppt-master 的 Executor、共享 SVG 标准以及选定的模式/风格参考。
每页顺序完成：读当前计划 → 选择构图 → 编写 SVG → 预览 → 修订。

- 画布保持 `viewBox="0 0 1280 720"`。
- 必须保留一个可安全删除的 `<g id="bg">` 预览背景。
- `id="template-section-label"` 只用于迁入模板原生章节框的页眉标签。
- 使用模板分析产物定义的安全区；默认建议内容安全区为
  `x=64..1216, y=170..680`，不是固定正文矩形。
- 允许全宽大图、非对称分栏、大数字、时间轴、中心图、满版流程和留白页。
- 连续三页不得机械重复同一构图；每 3–5 页应有一次节奏变化。
- 禁止为了凑版式数量强套内置结构图；内容语义优先于形式配额。
- 卡片超过四个时优先重构信息，不要靠缩小文字塞入。
- 流程必须用位置和连接关系表达，不能只是并排文本框。

Standard 中，详细 `data-*` 语义标记和角色字号合同作为 QA 建议；Strict
才将完整语义与 `page_schema` 作为硬门。来源、可编辑性、溢出和渲染始终
是硬门。模型视觉评审在 Standard 中是可选增强，人工逐页检查仍为必需。

### 4. 构建

```bash
python3 scripts/ghb_ppt.py build \
  --project projects/<name> \
  --workflow-mode standard \
  --template templates/GHB_PPT_模板.pptx \
  --cover-plan projects/<name>/analysis/cover_fill_plan.json \
  --output projects/<name>/exports/final.pptx \
  --quality-policy release \
  --target-renderer libreoffice \
  --embed-fonts \
  --repair-attempts 1
```

`--no-render` 只能用于草稿排错，不能据此声称视觉检查完成。

### 5. 视觉验收

至少执行一个“发现问题 → 修复 → 重新渲染”的循环：

1. 检查 `reports/svg-authored.json` 和最终质量报告；
2. 查看 `render/contact-sheet.png`；
3. 逐页查看 PNG，重点检查越界、裁切、间距、对齐、标题换行、页脚碰撞、
   卡片内边距、流程连接和跨页节奏；
4. 与上一版或指定基准 contact sheet 并排比较；
5. 修复后重新构建并复查受影响页面。

结构 `0 errors` 不等于审美通过。最终交付必须明确人工检查范围和渲染器。

## Quick

```bash
python3 scripts/ghb_ppt.py build \
  --project projects/<name> \
  --workflow-mode quick \
  --quality-policy draft
```

Quick 不需要用户确认和完整规划合同，但仍必须提供 `sources/source.md` 和
逐页创作的 SVG。Quick 不是发布模式。

## Strict

Strict 继续使用：

- `confirmation.json`
- `content_model.json`
- `art_direction.json`
- `visual_profile.json`
- `layout_plan.json` + 每页 `page_schema`
- `spec_lock.md`
- `design_spec.md`
- `analysis/cover_fill_plan.json`
- 完整语义标记、evidence manifest、warning waiver 和新鲜度绑定

严格发布必须显式运行且通过视觉评审：

```bash
python3 scripts/ghb_ppt.py build \
  --project projects/<name> \
  --workflow-mode strict \
  --quality-policy release \
  --review --require-review
```

`visual-review: skipped / unavailable / limited / needs-revision / error` 均不能
作为 Strict release 交付。完整旧合同规则见
[references/authoring-workflow.md](references/authoring-workflow.md) 和
[references/contracts.md](references/contracts.md)。

Strict 的交付证据包括 `reports/visual-review.json`、
`.ghb/evidence-manifest.json`，确需接受的模板异常必须通过
`--warning-waivers` 显式处置。中文正文首选 `Source Han Sans SC`，跨机器
交付应使用 `--embed-fonts` 或在目标环境重新验证。

## 常用命令

| 命令 | 作用 |
|---|---|
| `doctor` | 检查依赖、字体、模板、渲染器和本机 Skill 漂移 |
| `init` | 按模式创建项目 |
| `plan` | Standard 投影兼容合同；Strict 生成规划草稿 |
| `analyze-template` | 生成模板分析与 `template_profile.json` |
| `check-project` | 按工作流模式检查作者合同 |
| `check-svg` | 按模式运行 SVG 门禁 |
| `build` | 构建、合并、验证、渲染和报告 |
| `render` | 生成 PDF、逐页 PNG 和 contact sheet |
| `review` | 显式视觉评审；Strict release 必需 |

## 维护边界

优先在顶层 `scripts/` 添加 GHB 适配。修改 `scripts/ppt_master/` 前必须读
[references/vendor-sync-policy.md](references/vendor-sync-policy.md)，保持改动窄小并添加回归测试。
