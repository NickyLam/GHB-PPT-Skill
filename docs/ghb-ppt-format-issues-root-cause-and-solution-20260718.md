# GHB PPT 格式异常根因分析与解决方案

日期：2026-07-18

分析对象：使用当前 `ghb-ppt-skill`、由 GLM-5.2 参与生成的《企业内部 AI-Agent 与 Skill 实践》截图 3 张
结论置信度：流水线根因高；单页对象级归因中高（未提供该演示文稿的 PPTX、SVG 和质量报告）

## 1. 结论先行

这些问题的主因不是“GLM-5.2 不够强”，而是当前流水线把模型生成、结构正确和视觉正确混成了同一件事。

当前系统能够较好地证明 PPTX 可打开、对象可编辑、母版关系存在、SVG 没有明显非法结构，但不能证明最终页面在 WPS 中没有标题冲突、文字溢出、卡片内部失衡或连接线穿过内容。更关键的是：

1. 默认构建不会把最终渲染页强制交给视觉评审；模型通常只完成 SVG/内容编排，没有看到 WPS 最终画面。
2. 当前渲染器只支持 LibreOffice/soffice，截图却来自 WPS，目标渲染环境不一致。
3. 大量视觉问题只记为 warning/advisory，而程序退出码只由 error 决定；仓库现有真实样例在 46 条 advisory 下仍然是 `passed: true`。
4. 一些检测依赖作者主动写 `data-qa-box`。模型漏写元数据时，系统往往只给“覆盖不足”警告，而不是拒绝交付。
5. 现有指标偏重整页占用率和对象边界，不理解“卡片内的内容是否均衡”“箭头是否穿过文字”“标题是否侵入模板页眉保留区”等组件语义。
6. `--require-review` 当前把 `needs-revision` 和 `limited` 也当成“评审完成”，并不等于视觉验收通过。

因此，换成更强模型只能降低出错概率，不能消除这类问题。要解决，必须把目标渲染、语义几何检测和阻断式复核变成发布门禁。

## 2. 本次证据范围与限制

已检查：

- 三张 WPS 截图；
- 当前仓库 `HEAD=ff9136c`；
- 当前未提交工作树；
- `SKILL.md`、视觉质量规则、合并器、SVG→DrawingML 转换器、最终 PPTX 校验器、渲染器与相关测试；
- 仓库现有 `spacex_investment_research_20260717` 构建报告；
- 当前未提交修补的定向回归测试。

未提供且未在仓库中找到本次《企业内部 AI-Agent 与 Skill 实践》的：

- 最终 `.pptx`；
- `svg_output/`、`svg_final/`；
- `layout_plan.json`；
- `svg-authored.json`、`svg-finalized.json`、`quality-report.json`；
- WPS 导出的逐页 PNG/PDF。

所以，本报告可以确认“哪些质量门存在系统性缺口”，也能从截图判断最可能的故障链；但若要把每一个像素偏移精确归因到“SVG 作者、DrawingML 转换还是 WPS 字体度量”，仍需补充上述工件包。

## 3. 三张截图逐项诊断

| 截图 | 可见异常 | 直接原因 | 为什么现有门禁会漏过 |
|---|---|---|---|
| 第 6 页 / Skill 定义 | 银行 Logo、长主标题、右上章节框共用狭窄页眉；标题过长，整体层级拥挤；右侧模板竖条贴近/越过边缘 | 页面同时存在“SVG 自绘页眉”和“模板原生章节框”，没有统一的页眉保留区及长标题宽度预算 | 当前已提交版本只重挂母版，不把 SVG 章节文本语义化迁入模板原生框；页眉通常被占用率计算排除，未声明 QA 框时也不会做跨系统碰撞判断 |
| 第 16 页 / 实测案例 | 两个大卡片内部出现巨大的无效空白；底部截图与按钮像散落的独立对象；左右内容量和垂直节奏不对称 | 使用了自由绝对定位，没有“卡片内部槽位”约束；把卡片外框面积误当成内容已充分占用 | 整页占用率会把大白卡片本身计为有效几何，因此即使卡片内部很空也可能通过；现有规则没有检测卡片子元素的顶部/正文/媒体/结论槽位，也没有检测左右列的结构对称性 |
| 第 19 页 / 推荐工作流 | 多个箭头被压成短三角/短桩；第 4 步长文字越过卡片并压到箭头和邻卡；流程可读性被破坏 | 7 个节点横向硬塞，节点间距不足；单行文本框使用 `spAutoFit`，缺少组件宽度约束和强制换行；连接线与节点/文字没有统一几何契约 | 现有碰撞检查主要比较声明过的文本/图片 QA 矩形，不检查任意 line/polygon 与节点或文字的相交；转换器会为单行文本生成紧框并允许自动扩展，WPS 字体度量变化后更容易溢出 |

## 4. 根因追问（五层）

### 4.1 为什么页面会出现肉眼明显的错误？

因为生成器采用绝对坐标放置文本、卡片、图片和箭头，而这些对象之间没有完整的语义约束。只要坐标在画布内、XML 合法，文件就能被构建出来。

### 4.2 为什么校验没有拦住？

当前硬门主要拦截非法 SVG、明显越界、显式 QA 框碰撞、占位符、整页图片等问题。它不知道“这个文本属于哪张卡片”“这条箭头应该连接哪两个节点”“页眉右侧必须为模板章节框留多宽”。

此外，多项视觉指标只产生 warning。`scripts/validate_ghb_pptx.py` 的最终 `passed` 只检查 error，warning 不改变退出码。现有 SpaceX 样例报告就是直接证据：

- `passed: true`；
- `blocking_count: 0`；
- `advisory_count: 46`；
- `visual-review.json` 的 outcome 为 `skipped`。

这说明“生成报告成功”并不等于“视觉问题已解决”。

### 4.3 为什么 GLM-5.2 没有自行发现？

模型名称只说明谁参与了内容/代码生成，不说明它看过最终 WPS 渲染。

当前 `build` 默认不调用模型评审；只有显式 `review` 或 `build --review` 才可能调用适配器。即使配置了 `--require-review`，当前代码仍接受 `needs-revision` 和 `limited` 作为“已完成”。这使评审更像附加报告，而不是发布裁决。

同一个模型在没有目标渲染截图、对象边界证据和明确失败码时，只能按源码坐标推测效果。SVG 浏览器预览、LibreOffice 输出和 WPS 最终显示并不等价，尤其是中文字体度量、自动扩展文本框和组合对象边界。

### 4.4 为什么已有视觉指标也没有发现卡片空洞？

当前 occupancy 计算的是可见几何并集。第 16 页两个大白色卡片本身占据了大量页面面积，即使卡片内部信息集中在顶部和底部，中间几乎为空，整页占用率仍可能正常。

这属于“测量对象错位”：系统测了盒子有多大，没有测盒子里的信息是否被合理组织。

### 4.5 为什么 WPS 中更容易暴露？

当前 `scripts/render_ghb_pptx.py` 只接受 `auto|soffice|libreoffice`，没有 WPS 后端。流水线即使完成逐页渲染，也是在 LibreOffice 中完成，不是用户最终打开文件的 WPS。

因此目前验证的是“LibreOffice 可渲染”，不是“WPS 版式已通过”。这对使用 `spAutoFit` 的中文单行文本框、组合对象和模板边缘出血尤其敏感。

## 5. 当前版本状态：已有修补，但还没有闭环

当前仓库存在一批未提交改动，主要针对本次截图中暴露的部分问题：

- 用 `template-section-label` 把 SVG 章节文本迁入模板原生右上标题框；
- 将模板原生框重新放回幻灯片边界内；
- 检查页眉红色竖条和主标题的垂直中心；
- 修正 waterfall 的过小间距、反向/短桩箭头；
- 修正 flywheel 连接线端点进入节点的问题；
- 保留 SVG 文本 `id` 到 DrawingML shape name；
- 避免把组合内局部坐标误判为幻灯片越界。

对这些改动运行的定向测试结果为：

```text
62 passed in 3.68s
```

但它们仍不足以关闭本次问题：

1. 页眉修补没有验证“长主标题是否侵入右上章节框保留区”；
2. waterfall/flywheel 修补不是通用流程连接器检测，不能覆盖第 19 页这种自定义 7 卡流程；
3. 没有卡片内部槽位和双栏对称性检测，第 16 页仍可能通过；
4. 单行文本仍使用 `wrap="none" + spAutoFit`，目标渲染器可能扩大文本框；
5. 没有 WPS 渲染后端；
6. warning 和 `needs-revision` 仍不阻断发布。

结论：当前未提交修补值得保留，但只能算 P0 的一部分，不能据此宣称问题已解决。

## 6. 解决方案

### P0：先堵住“明显坏页仍显示通过”

#### 6.1 改成阻断式发布判定

修改 `scripts/validate_ghb_pptx.py` 与 `scripts/ghb_ppt.py`：

- 真实用户项目的 release pass 必须满足：`error == 0` 且不存在未处置的发布级 warning；
- `--require-review` 只接受 `outcome=passed`；
- `needs-revision` 必须返回非零退出码；
- `limited` 只能生成“受限预览”，不得生成“可交付”状态；
- warning 如需放行，必须写入逐页 waiver，包含 issue code、slide id、理由和批准来源，不能静默忽略。

建议新增：

```text
--quality-policy draft|release
--warning-waivers <path>
```

`draft` 保持当前宽松行为，`release` 使用上述严格规则。真实交付默认 `release`。

#### 6.2 强制目标渲染复核

- 在 `scripts/render_ghb_pptx.py` 增加 `--renderer wps|powerpoint`，或为 WPS 提供单独适配器；
- 若自动化 WPS 导出暂时不稳定，至少强制人工提供 WPS 导出的 PDF/逐页 PNG，并写入 evidence manifest；
- 构建报告必须记录 `target_renderer` 与 `actual_renderer`；release 模式二者不一致时直接阻断；
- 对最终 WPS PNG 运行视觉评审，而不是只评 SVG 或 LibreOffice PNG。

#### 6.3 把三类明显问题升级为 error

新增稳定失败码：

- `header-safe-zone-collision`：主标题、Logo、章节框进入彼此保留区；
- `text-component-overflow`：文本实际/估算边界超出所属卡片或流程节点；
- `connector-node-intersection`：连接线或箭头进入源/目标节点；
- `connector-text-intersection`：连接线或箭头穿过文字边界；
- `connector-visible-length-low`：可见连接段短于 24 SVG px；
- `component-slot-overflow`：子元素越过卡片槽位；
- `component-balance-outlier`：成对比较卡片的关键槽位缺失或垂直位置偏差超过阈值；
- `visual-coverage-insufficient`：应检测对象没有足够几何元数据。release 模式下从 warning 升为 error。

### P1：从“自由坐标”升级为“组件契约”

#### 6.4 页眉只允许一个权威来源

建立固定安全区，例如：

```text
Logo 区：x=56..250
主标题区：x=88..900
章节框区：x=930..1280
```

具体数值应由模板分析报告生成，不能写死在模型提示词里。

规则：

- SVG 只写一个 `template-section-label`，合并器负责迁入原生模板框；
- 主标题必须声明 `data-qa-role="title"` 和最大宽度；
- 标题超长时按“语义缩写 → 两行标题 → 拆页/改标题”处理，禁止单行横穿页眉；
- Logo、主标题、章节框三者做真实边界碰撞检测；
- 模板允许的装饰性出血必须是显式、固定、可豁免的模板异常，而不是泛化放行。

#### 6.5 比较卡片使用槽位布局

为第 16 页这种场景增加复用组件，例如 `comparison/evidence-card`：

```text
card
├── heading
├── subtitle
├── evidence-list
├── media
└── verdict
```

每个槽位都有边界、最小间距和可选性。校验器检查：

- 子元素必须属于某个卡片；
- `media` 与 `verdict` 不得成为无锚点的自由对象；
- 左右卡片相同槽位的 top/bottom 偏差不得超过设定阈值；
- 若一侧内容更少，卡片应采用统一顶对齐与底部结论区，不允许用巨幅空白填充；
- 卡片外框不再计入信息占用率，内容占用率单独计算。

#### 6.6 流程布局必须由节点和边生成

不要让模型直接猜箭头坐标。输入应是：

```json
{
  "nodes": [{"id": "step-1", "label": "真实任务"}],
  "edges": [{"from": "step-1", "to": "step-2"}]
}
```

布局器负责：

- 根据最长标签计算节点宽度；
- 超过单行预算时确定性换行；
- 7 个节点放不下时自动改为 4+3 两行流程或时间线；
- 连接线从节点外缘开始，在目标外缘前 3–6 px 结束；
- 箭头至少保留 24 px 可见连接段；
- 对所有 line/polygon 与节点/文本框做相交测试。

#### 6.7 消除单行 `spAutoFit` 的不确定扩张

修改 SVG→DrawingML 文本转换：

- 组件内文字必须携带显式文本框宽高，不能只按字符估算紧框；
- 长文本输出为带固定宽度的 paragraph 模式，并允许内部换行；
- 在 release 模式禁止组件标签使用 `wrap="none" + spAutoFit`；
- 保存转换前后的文本框边界，并在目标渲染后做 OCR/像素边界或 PowerPoint/WPS readback 对比。

### P2：建立真正的渲染反馈闭环

完整流程应变为：

```text
内容模型
  → 语义布局/组件树
  → Office-safe SVG
  → authored SVG 硬门
  → DrawingML
  → PPTX 结构硬门
  → LibreOffice 预渲染
  → WPS/PowerPoint 目标渲染
  → 确定性图像检测 + 独立视觉评审
  → 修复受影响页
  → 全链路重跑
  → release pass
```

模型负责提出布局和修复建议；确定性代码负责几何；目标渲染负责证明最终呈现。三者缺一不可。

## 7. 必须新增的回归样例

把本次三张图抽象为最小、可重复的坏例，不要只保留截图：

1. `header-long-title-with-native-section-frame`
   - 长中文标题 + Logo + 原生章节框；
   - 修复前必须触发 `header-safe-zone-collision`；
   - 修复后在 LibreOffice 和 WPS 中均无碰撞。

2. `comparison-card-internal-void`
   - 两张等高卡片，一侧媒体/结论漂移到底部；
   - 修复前必须触发 `component-balance-outlier`；
   - 外框面积不得掩盖内部内容占用不足。

3. `seven-step-flow-with-long-cjk-labels`
   - 7 节点、含 `AGENTS.md/Rules 约束` 等长标签；
   - 修复前必须触发文本溢出和连接器相交；
   - 修复后自动采用换行或 4+3 布局，箭头可见长度不低于 24 px。

每个样例至少保存：SVG、PPTX、LibreOffice PNG、WPS PNG、预期 issue codes 和质量报告。测试必须断言具体失败码，不能只断言命令返回失败。

## 8. 验收标准

只有以下条件同时满足，才能宣告本问题完成：

- 三个回归样例修复前均可靠失败，修复后均通过；
- authored/finalized SVG：0 error；
- PPTX 结构与 readback：0 error；
- release 模式：0 个未豁免的发布级 warning；
- `--require-review` 遇到 `needs-revision`、`limited`、`skipped` 均返回非零；
- LibreOffice 和 WPS 逐页渲染页数一致；
- WPS 页中无页眉冲突、卡片内部漂移、文本溢出、短桩箭头或连接线穿字；
- WPS 最终 PNG 已进入 evidence manifest，且与最终 PPTX digest 绑定；
- 全量测试通过，最终 diff 独立复核无无关改动。

## 9. 推荐实施顺序

1. 先改发布判定和 `--require-review` 语义，立即阻止坏页被标记为成功。
2. 加入三组失败 fixture，锁定本次真实问题。
3. 完成页眉安全区、通用文本/连接器相交检测。
4. 引入比较卡片槽位组件和流程图节点/边布局器。
5. 改造单行文本框策略，减少 WPS 自动扩张差异。
6. 增加 WPS 目标渲染证据，再跑完整构建与回归。

不建议先做的事：继续堆提示词、仅换更强模型、只增加一轮“请检查美观”的自评、或只针对三张截图手调坐标。这些做法能修一份 PPT，不能修复 Skill 的质量合同。

## 10. 2026-07-18 实施结果与边界

本轮已经把关键建议落实为代码门禁，而不是只更新提示词：

- 顶层 `build`、`validate`、`report`、`review` 默认使用 release 策略；低层验证库仍默认 draft，避免破坏已有库调用；
- release 下所有未豁免 warning 均阻断，豁免文件使用 `ghb.warning-waivers.v1` 且逐项记录 code、slide、理由和批准人；
- release 必须提供与最终 PPTX 路径、SHA-256 和页数绑定的逐页 PNG 渲染报告；目标 renderer 与实际 renderer 不一致或证据陈旧时阻断；
- `--require-review` 现在只接受 fresh `outcome=passed`；`needs-revision`、`limited`、`skipped`、`unavailable`、`error` 均不能满足要求；
- `template-section-label` 会迁入 GHB 原生章节框，不再由 SVG 和模板各画一套页眉；主标题会检查模板绑定的章节框保留区；
- waterfall、flywheel 输出节点/边语义，连接线进入节点、穿过声明文本或可见长度小于 24 px 时失败；
- 比较卡片支持父组件、槽位和成对关系，槽位越界、缺失或垂直失衡时失败；
- SVG 文本 `id` 会保留为 DrawingML shape name，使合并器能可靠识别语义对象；组合对象使用局部坐标时不再产生整页越界误报。

当前没有引入不可靠的 WPS GUI 自动化。WPS/PowerPoint 证据通过外部
`ghb.render-report.v1` 接入，必须包含最终 PPTX 路径、SHA-256、renderer 和全部逐页 PNG；
LibreOffice 证据不能冒充 WPS。也就是说，本轮保证“没有目标证据就不能 release”，
但不会替用户操作 WPS 导出。后续若增加稳定的 WPS CLI/受控桌面适配器，可复用同一证据合同。

页眉保留区目前是 GHB 内置模板绑定值；若未来允许任意模板，应把该值放进模板分析产物，
由质量门读取，而不是继续扩展硬编码模板分支。

## 11. 最终判断

这次输出暴露的是“质量门禁定义错误”，不是单纯的模型偶发失误。

当前 Skill 已经有不错的结构化基础，也有一批正在进行的页眉和箭头修补；但只要目标 WPS 渲染不是强制证据、warning 不阻断、组件语义不存在、`needs-revision` 仍算完成，同类问题仍会重复出现。

真正的解决标准不是“让 GLM-5.2 再认真一点”，而是让任何模型生成的坏版式都无法获得 release pass。
