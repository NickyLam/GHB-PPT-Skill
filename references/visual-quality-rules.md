# SVG、图片与图标视觉质量规则

在生成正文 SVG 和运行 `finalize_svg.py` 前读取本文件。目标是让质量问题在导出 PPTX 前失败，而不是依赖肉眼碰运气。

## 1. 图片

- 始终给位图 `<image>` 写 `preserveAspectRatio="xMidYMid meet"`（完整展示）或 `xMidYMid slice`（裁切铺满）；禁止 `none`，禁止省略。
- 源图宽高均不得低于显示框宽高；建议至少 1.5 倍像素密度。小图标不要放大充当主视觉。
- 图片框必须完整位于 `viewBox` 内。需要出血时显式写 `data-allow-overlap="true"` 并在 `design_spec.md` 说明。
- `finalize_svg.py` 后，普通位图必须变成 `data:` URI；EMF/WMF 可保留外部引用供原生转换。
- 同一页最多使用 1 张 hero 或 2 张 supporting images。图片只在能解释内容、提供证据或建立语境时使用。

## 2. 图标

- 始终使用带库前缀的名字，如 `tabler-outline/target`；禁止无前缀 `target`。
- 图标框必须为正方形。常规要点图标用 24–64 px；超过 128 px 时改用插图或结构图。
- 同一页使用同一通用图标库和相同线宽。品牌 Logo 才使用 `simple-icons`。
- 每个 `<use data-icon>` 必须在 `templates/icons/<library>/` 找到对应 SVG；`finalize_svg.py` 后不得残留未解析 `<use data-icon>`。
- 图标只承担导航、分类或强调，不用图标代替核心信息结构。

## 3. 碰撞契约

对自由摆放、可能互相遮挡的文本块、图片和图标声明 QA 几何：

```xml
<g id="summary" data-qa-role="text" data-qa-box="120 230 360 96">...</g>
<image id="hero" data-qa-role="image" x="560" y="220" width="540" height="320" .../>
<use id="signal" data-qa-role="icon" data-icon="tabler-outline/target"
     x="120" y="360" width="40" height="40"/>
```

- `data-qa-box` 使用画布绝对坐标 `x y width height`，不要使用变换后的局部坐标。
- 对靠近卡片边界、不同 Office 字体度量可能导致文本框扩张的单行文本，可显式写
  `data-text-fit="fixed"`。该属性必须与正数 `data-qa-box` 同时使用；转换器会输出
  DrawingML `noAutofit`，因此作者必须为最宽目标字体保留安全宽度，避免从“越界”
  变成“裁字”。未声明时仍保留默认自动适配行为。
- 用 `data-qa-peer-group="cards"` 显式标记需要比较间距的同级组件。间距
  指标只比较同组对象；未声明时会排除相互包含/重叠的父子盒，避免卡片
  内部文本把真实卡片间距误算为 0。
- 默认同属 `data-qa-group="content"` 的框不得重叠超过较小框面积的 12%。
- 有意叠放（如图片上的标题遮罩）必须在参与叠放的元素上写 `data-allow-overlap="true"`。
- 装饰性背景不要标 `data-qa-role`；它不参与碰撞检查。
- 基础结构形状（rect/circle/ellipse/line/polygon/polyline）必须完整位于画布内；有意出血时给形状写 `data-allow-overflow="true"`。
- `header` 组内的红色竖杠必须与主标题字面垂直居中，中心偏差不得超过 4 px；
  页眉迁入右上模板标题框后，不得继续沿用包含旧页眉高度的竖条坐标。
- 流程、飞轮和状态图的连接线起终点必须位于节点轮廓之外；显式箭头尖端
  与目标边框保留 3–6 px 安全间隙，不能进入节点填充区域。
- 相邻流程节点至少预留 24 px 可见连接空间。若连接段不足，先缩窄节点、
  增大间距或换行布局；禁止把连接线压缩成反向线段或近似竖直的箭头短桩。

### 3.1 页眉保留区合同

- 主标题建议使用 `id="main-title" data-qa-role="title" data-qa-box="..."`；
- 模板章节文本必须使用 `id="template-section-label"`，可同时声明
  `data-qa-role="section-label" data-qa-box="..."`；
- 校验器按 GHB 原生章节框的完整 footprint 检查，不以短占位文本宽度代替；
- 主标题进入章节框保留区时产生 `header-safe-zone-collision` error。

### 3.2 流程节点与连接线合同

```xml
<rect id="step-1" data-flow-node="step-1"
      data-qa-box="100 220 180 100" x="100" y="220" width="180" height="100"/>
<line id="edge-1" data-flow-from="step-1" data-flow-to="step-2"
      x1="286" y1="270" x2="314" y2="270"/>
```

- `data-flow-node` 在一页内唯一，且必须有正数 `data-qa-box`；
- 每条语义连接线必须同时声明 `data-flow-from` / `data-flow-to`；
- 节点端点相交报 `connector-node-intersection`；
- 连接线端点之间的实际可见长度低于 24 px 报 `connector-visible-length-low`；
- 连接段穿过 `data-qa-role="text|title|label"` 的 QA 框时报
  `connector-text-intersection`。

### 3.3 卡片组件与槽位合同

```xml
<g data-component="evidence-card" data-component-id="left"
   data-component-balance="insets"
   data-component-pair="comparison-1" data-qa-box="100 180 420 360">
  <g data-component-parent="left" data-component-slot="verdict"
     data-qa-box="140 470 340 48">...</g>
</g>
```

- 组件必须同时声明 `data-component`、唯一 `data-component-id` 和 QA 框；
- 子槽位必须同时声明 `data-component-parent`、`data-component-slot` 和 QA 框；
- 槽位越出父卡片时报 `component-slot-overflow`；
- 相同 `data-component-pair` 必须恰有两张同类卡片；槽位缺失、顶部或高度
  偏差超过 24 px 时，报 `component-balance-outlier`。
- 重复卡片可声明 `data-component-balance="insets"`。检查器会以全部子槽位的
  联合边界计算左、右、上、下内边距：同一卡片的左右与上下差值不得超过 4 px，
  同类卡片的四向内边距也必须在 4 px 内一致，否则报
  `component-inset-outlier`。应给图标、编号、标题和说明分别声明固定槽位，不要用
  字符串长短或字体墨迹边界冒充布局边界。

### 3.4 页面目的语义合同

`page_schema.page_purpose` 必须在主 `data-layout` 内有可见语义证据，不能
用版式名称替代结构事实：

- `process`：至少两个 `data-flow-node` 和一条完整 `data-flow-from` /
  `data-flow-to` 边，或至少两个 `data-step` / `data-lane`；
- `instruction` / `timeline`：至少两个 `data-step`，instruction 也可使用
  完整 flow；
- `architecture`：至少两个 `data-layer`；
- `comparison`：至少两个带唯一 `data-component-id` 的组件；
- `evidence` / `case-study` / `screenshot`：至少一个 `data-evidence`；
- `metrics` / `data-story`：至少一个 `data-metric`；
- `decision` / `recommendation`：至少一个 `data-decision` 或
  `data-recommendation`；
- `risk`：同时存在 `data-risk` 与 `data-mitigation`；
- `hero` / `section-anchor` / `closing`：至少一个 `data-focal="true"`。

缺失语义标记是 authored/finalized 两阶段的 error。内置 intent-aware
renderer 会为 staircase、timeline、funnel、swimlane、layered architecture、
matrix comparison/metric 等输出对应标记；手工 SVG 必须自行声明。

### 3.5 角色化排版合同

严格 `visual_profile.typography.enforcement` 默认开启。可见文本必须通过
`data-qa-role`（可由父组继承）或稳定 ID 声明角色：

| 角色 | ID 示例 | 最小 pt | SVG 最小 px |
|---|---|---:|---:|
| title | `main-title` | 28 | 38（28.5 pt） |
| body / text / label | `body-summary` | 18 | 24 |
| caption | `caption-shot` | 12 | 16 |
| source | `source-note` | 10 | 14（10.5 pt） |
| footer | `footer-page` | 9 | 12 |

换算固定为 `1 px = 0.75 pt`。主 `data-layout` 中未声明角色的文本报
`typography-unclassified-text`；低于角色下限报
`typography-<role>-below-min`。最终 PPTX 还会按
`main-title`、`body-*`、`caption-*`、`source-*`、`footer-*` 形状名再次
读回并输出 `min_font_by_role`，防止 SVG→DrawingML 转换后字号退化。

## 4. 乱码与文本负载

- 禁止 Unicode replacement character `�`、控制字符和常见 UTF-8/Latin-1 乱码片段。
- v1 `page_schema.density` 决定主 `data-layout` 内容组上限（页眉页脚不计）：
  - `breathing`：最多 160 个非空白字符、12 个 `<text>`。
  - `balanced`：最多 300 个非空白字符、18 个 `<text>`。
  - `dense`：最多 520 个非空白字符、28 个 `<text>`。
- 仅当页面没有 `page_schema` 时，旧顶层 `density: anchor` 兼容 balanced 的文本负载；`anchor` 不是 v1 几何密度。
- 超过上限时先拆页，再删减；不要靠缩小字体塞入。
- 计划页没有可见内容是错误；少于 18 个可见字符会提示页面可能过空。

## 5. 强制命令

生成后、后处理前：

```bash
python3 scripts/ppt_master/visual_asset_checker.py "$PROJECT" --stage authored
```

运行 `finalize_svg.py` 后、导出 PPTX 前（自动扫描 `svg_final/`）：

```bash
python3 scripts/ppt_master/visual_asset_checker.py "$PROJECT" --stage finalized
```

两次都必须 0 error。机器集成可加 `--json`。

## 6. Deterministic visual-quality findings

The authored and finalized SVG reports measure visible SVG geometry before
applying GHB policy. `data-layout` is descriptive metadata and is never used as
proof of composition. Reports do not calculate an aggregate aesthetic score.

## Measurement and coverage

The generic geometry envelope records the slide and body canvases, supported
shape or `data-qa-box` bounds, semantic role, focal marker, fill, typography
size where known, peer-group identity, and measurement limitations. The GHB
policy layer derives:

- body occupancy (union area, so overlapping shapes are not double counted);
- focal-area ratio, primary-fill focal signal, and observed left/center/right focal zone;
- title/body size ratio when both sizes are observable;
- spacing variation, minimum peer gap, and spacing-grid deviation;
- primary-brand-color area;
- normalized geometry-and-role composition fingerprint.

Background/master decoration, header, footer, chrome, and elements marked as
deliberate bleed are excluded from body occupancy. Hidden elements are not
visible content. A transformed subtree, unsupported path, or text without a QA
extent is not guessed: it lowers coverage to `partial`, or to `not-measurable`
when no supported bounds remain. Raw measurements are immutable after
extraction. Occupancy uses geometry clipped to the body canvas, while explicit
bounds enforcement retains the pre-clip geometry so body overflow cannot be
hidden by measurement clipping.

## Policy findings

Each finding has a stable code, severity, affected slide identity, measured
evidence, expected range, and suggested action.

| Code | Initial severity | Trigger |
|---|---|---|
| `visual-occupancy-below-min` / `visual-occupancy-above-max` | warning | Measured occupancy falls outside `visual_profile.occupancy.body`. |
| `visual-title-body-scale-low` | warning | Measurable title/body ratio is below the profile minimum. |
| `visual-component-gap-small` | warning | Nearest peer gap is below `spacing.min_component_gap`. |
| `visual-spacing-inconsistent` | warning | Peer-gap coefficient of variation exceeds the provisional `0.45` band. |
| `visual-alignment-deviation` | warning | Mean edge deviation exceeds `0.35` of the profile base unit. |
| `visual-primary-color-overuse` | warning | Primary-color area exceeds the provisional `0.35` body-area band. |
| `visual-focal-dominance-low` | warning | A single-focal page has an observed focal ratio no greater than `1.1` and no primary-fill focal signal. |
| `visual-coverage-partial` / `visual-not-measurable` | warning | Geometry coverage is incomplete or absent. |
| `visual-composition-repeated` | warning | Adjacent body pages have the same geometry/role fingerprint. |
| `visual-focal-zone-streak` | warning | Three adjacent body pages retain the same observed focal zone. |
| `visual-rhythm-role-streak` | warning | Declared rhythm role exceeds the profile streak limit. |
| `visual-density-rhythm-drift` | warning | Four adjacent pages retain one v1 density. |
| `visual-variant-repetition` | warning | Three adjacent pages repeat one declared semantic variant. |
| `visual-explicit-bounds-violation` | error | Fully measured content exceeds an explicit bounds override by more than `0.5` SVG unit. |
| `visual-invalid-geometry` | error | Geometry extraction rejects malformed or non-finite SVG coordinates. |

The provisional balance, hierarchy, color, and deck-rhythm bands are advisory.
Existing malformed-contract, collision, overflow, empty planned content, and
other geometry errors remain blocking. `passed` continues to mean that the
combined report contains no errors; warnings do not change the exit code.

## Schema and compatibility

New projects consume `page_schema.density` with the v1 values `breathing`,
`balanced`, and `dense`. A row without `page_schema` may use legacy top-level
`anchor` limits for compatibility; this maps to balanced load only and does not
make `anchor` a geometry density. `anchor` remains a rhythm role in v1.

Authored and finalized evidence is generated independently and carries its
stage in the report. Later final-PPTX/readback observations must be a separate
envelope rather than overwriting either SVG stage. `svg_output/` is never
post-processed in place: finalization and preview-background removal operate
only on `svg_final/` before the finalized report is produced.

## Exceptions

An additive `page_schema.policy_exceptions` list may suppress named advisory
findings for an intentional composition. Deck findings are suppressed when an
affected page declares that code. Exceptions never alter occupancy,
fingerprints, focal zones, coverage, or any other raw measurement, and they do
not suppress existing structural errors.
