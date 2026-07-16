# SVG Layout Catalog

Use this catalog after content confirmation and before writing body-slide SVG. Pick a `layout_archetype` for every body slide, write it into `layout_plan.json`, and put the same value on the main SVG content group as `data-layout="<layout_archetype>"`.

## Layout Plan Contract

Create `layout_plan.json` in the project root:

```json
[
  {
    "slide": 3,
    "message": "能力建设要先有平台底座，再叠加流程和治理",
    "layout_archetype": "pyramid",
    "density": "balanced",
    "rhythm_role": "anchor",
    "items": ["基础设施", "平台能力", "流程机制", "治理闭环"],
    "reason": "内容表达层级递进，金字塔能突出基础与顶层目标的关系",
    "alternatives": ["layered_arch", "staircase"]
  }
]
```

Required fields:

| Field | Meaning |
|---|---|
| `slide` | Body-slide number, excluding cover and ending slide |
| `message` | One-sentence slide takeaway |
| `layout_archetype` | Chosen structure, e.g. `pyramid` |
| `density` | Geometry band: `breathing`, `balanced`, or `dense` |
| `rhythm_role` | Deck-level role such as `anchor`; this does not replace density |
| `items` | Ordered labels that drive the SVG component |
| `reason` | Why this structure fits the content |
| `alternatives` | 1-2 acceptable fallback layouts |

## Diversity Rules

- Do not use the same `layout_archetype` on three consecutive body slides.
- For decks with 8+ body slides, use at least four distinct structural archetypes when the source content supports it.
- Keep repeated layouts only when the repetition itself is meaningful, such as a deliberate section-by-section comparison.
- Prefer structure changes over decorative changes. Changing colors/icons while keeping the same card grid does not count as real layout variety.

## Page-purpose patterns

Not every page purpose needs a dedicated generator. Choose a semantic pattern
first, then use a built-in archetype or hand-author an Office-safe SVG with the
same `data-layout` and planning contract.

| Page purpose | Recommended structure | Authoring rule |
|---|---|---|
| Core conclusion | `anchor_claim` or `pyramid` | One dominant claim plus no more than three supporting facts |
| Left text / right visual | `split_visual` | Keep the visual editable when possible; never use an entire slide screenshot |
| Conclusion above / evidence below | `evidence_stack` or `layered_arch` | Separate the claim band from evidence objects and source note |
| Three/four cards | `card_grid` | Use only for genuine peers; do not repeat it across the deck |
| Problem / cause / action | `problem_cause_action` | Preserve causal direction and highlight the action, not three equal boxes |
| Before / after | `comparison` | Align comparable dimensions row by row and state the changed outcome |
| Option comparison | `comparison` or editable table | Use shared criteria, explicit trade-offs, and a recommendation |
| Two-axis prioritization | `matrix` | Name both axes and place no more than four primary categories |
| Timeline / roadmap | `timeline` or `staircase` | Use timeline for dates; staircase for capability progression |
| Process / handoff | `waterfall` | Show direction, decision points, and final output |
| Swimlane | `swimlane` | Use only when roles really own different steps |
| Layered architecture | `layered_arch` | Read bottom-to-top dependencies; keep layer labels editable |
| System relationships | `hub_spoke` | Use a central system plus labeled relationships; avoid decorative spokes |
| Data chart | `editable_chart` | Prefer native chart/table or editable SVG marks; include units and source |
| Big-number metrics | `metric_callout` | One dominant number per metric with baseline/target context |
| Risk and response | `risk_response` | Pair every risk with owner, mitigation, and status |
| Summary | `flywheel`, `pyramid`, or `summary_grid` | Recombine the deck's actual conclusions; do not add new claims |

Built-in renderers currently cover `pyramid`, `waterfall`, `staircase`,
`layered_arch`, `matrix`, `timeline`, `funnel`, `flywheel`, `swimlane`, and
`iceberg`. For other named patterns, hand-author the SVG and use the semantic
pattern name in `data-layout`; add a reusable renderer only after the pattern
recurs across multiple decks.

## Schema-driven renderer contract

Pass visual intent through `LayoutSpec`. Calls that omit all intent fields keep
their legacy SVG bytes. Intent-aware calls accept:

- `density`: `breathing`, `balanced`, or `dense`; each changes spacing, scale,
  or placement geometry.
- `variant`: one of the family-owned variants below.
- `emphasis`: `single-focal`, `ranked`, or `distributed`.
- `focal_index` or `focal_target`: required for `single-focal`; the matching
  visible shape is tagged `data-focal="true"`.
- `max_items` and `max_text_chars`: optional page-schema limits. They may make
  a family limit stricter but cannot expand it.

The renderer rejects content below the semantic minimum, above the family or
declared node maximum, above the per-item limit, or above the declared/family
text maximum. Even within those hard ceilings, it also rejects labels whose
wrapped lines cannot fit the actual component height at the 13 px font floor.
It does not globally shrink type to hide an over-budget page.

Density is not emphasis. The author must derive emphasis from `key_message`:
`single-focal` is valid only when the conclusion names or clearly privileges
the matching visible `focal_target`. Never select the second item, the largest
card, or an `anchor` page by convention. For peer comparisons and complete
cycles, prefer `distributed`; when color or fill is used, its semantic meaning
must be evident from the title or an explicit label.

| Archetype | Items | Max chars/item | Max text | Variants |
|---|---:|---:|---:|---|
| `pyramid` | 2-5 | 64 | 240 | `pyramid/default`, `pyramid/foundation` |
| `waterfall` | 2-6 | 56 | 260 | `waterfall/default`, `waterfall/descending` |
| `staircase` | 2-5 | 56 | 220 | `staircase/default`, `staircase/editorial` |
| `layered_arch` | 2-6 | 72 | 320 | `layered_arch/default`, `layered_arch/platform` |
| `matrix` | 2-4 | 80 | 240 | `matrix/default`, `matrix/comparison`, `matrix/spotlight`, `matrix/metric-callout` |
| `timeline` | 2-6 | 80 | 360 | `timeline/default`, `timeline/editorial`, `timeline/phased` |
| `funnel` | 2-5 | 56 | 240 | `funnel/default`, `funnel/qualified` |
| `flywheel` | 3-6 | 48 | 240 | `flywheel/default`, `flywheel/hub-led` |
| `swimlane` | 2-4 | 48 | 180 | `swimlane/default`, `swimlane/compact` |
| `iceberg` | 2-4 | 64 | 220 | `iceberg/default`, `iceberg/deep-dive` |

`comparison` is a semantic alias that normalizes to the existing `matrix`
archetype with `matrix/comparison`; it never emits a new `data-layout` value.
`matrix/metric-callout` is the catalogued metric-capable variant. Matrix cards
remain equal width and height with fixed gaps; focal prominence uses fill,
border, and font hierarchy only, never unequal card area.

Run the checker after SVGs exist:

```bash
python3 "$PM/check_layout_diversity.py" "$PROJECT"
```

## Supported Layouts

### `pyramid`

Use for:

- hierarchy, maturity levels, capability stacks
- strategy → capability → execution decomposition
- base layer supporting upper layers

Avoid for:

- strict time order
- peer-level comparison
- more than five equally important items

Recommended item count: 3-5.

Default composition: centered stacked trapezoids, widest layer at the bottom, strongest emphasis at the top or base depending on the page message.

SVG safety: use explicit `<polygon>` layers. Do not use clipping, masks, filters, or gradient-dependent text contrast.

### `waterfall`

Use for:

- staged handoff
- phase-by-phase delivery
- cumulative movement from input to output

Avoid for:

- cyclical feedback loops
- parallel workstreams
- static hierarchy

Recommended item count: 3-6.

Default composition: descending or ascending blocks connected by explicit line segments and polygon arrowheads.

SVG safety: use explicit `<line>` plus `<polygon>` arrowheads. Do not use `marker-end`.

### `staircase`

Use for:

- maturity progression
- capability upgrades
- increasing investment, confidence, or automation

Avoid for:

- non-directional groupings
- cases where the last item is not clearly more advanced than the first

Recommended item count: 3-5.

Default composition: rising blocks with numbered steps and a highlighted target step.

SVG safety: use rectangles with direct coordinates. Keep text horizontal for PPT readability.

### `layered_arch`

Use for:

- system architecture layers
- platform stack
- governance, service, and application layering

Avoid for:

- flows where direction and transitions matter more than stable layers
- unrelated bullet groups

Recommended item count: 3-6.

Default composition: horizontal layers, bottom-to-top dependency reading, optional right-side annotations if the slide needs more explanation.

SVG safety: use `<rect>` layers only. Keep all layer labels as SVG `<text>`.

### `matrix`

Use for:

- priority mapping
- value vs complexity
- risk vs benefit
- portfolio categorization

Avoid for:

- more than four primary categories
- content without two meaningful axes

Supported item count: 2-4 quadrants/cards; use four when both axes are fully populated.

Default composition: 2×2 grid with one highlighted quadrant. Add axis labels manually when needed.

SVG safety: use rectangles and lines. Do not rely on embedded chart libraries for this simple pattern.

### `timeline`

Use for:

- roadmap
- milestones
- release stages
- historical sequence

Avoid for:

- hierarchy
- unordered concepts
- dense details per milestone

Supported item count: 2-6.

Default composition: horizontal line, numbered nodes, alternating labels to preserve breathing room.

SVG safety: use `<line>`, rounded `<rect>` nodes, and text. Avoid complex path animations or CSS classes.

### `funnel`

Use for:

- narrowing stages
- conversion paths
- intake → screening → closure

Avoid for:

- loops or recurring systems
- parallel ownership handoff
- cases where every stage matters equally

Supported item count: 2-5.

Default composition: top-wide to bottom-narrow stacked trapezoids with the final stage visually emphasized.

SVG safety: use explicit `<polygon>` segments. Keep labels centered and horizontal.

### `flywheel`

Use for:

- feedback loops
- growth engines
- repeated reinforce-and-scale mechanisms

Avoid for:

- one-way delivery sequences
- strict role ownership charts
- content without a real loop

Recommended item count: 3-6.

Default composition: clockwise node ring with explicit line connectors, polygon arrowheads, and a central reinforcing hub.

SVG safety: use `<rect>`, `<line>`, and `<polygon>` only. Avoid path-based circular arrows.

### `swimlane`

Use for:

- role × process breakdown
- cross-team handoff
- governance, platform, and business collaboration

Avoid for:

- pure hierarchy
- single-owner sequences
- slides with no real lane distinction

Recommended item count: 2-4 lanes.

Default composition: left-side lane headers plus repeated process cells across 3 stages.

SVG safety: use a plain rect grid and horizontal text. Do not use HTML tables or foreign objects.

### `iceberg`

Use for:

- visible symptoms vs hidden causes
- management perception vs system constraints
- short-term signal vs deep structure

Avoid for:

- balanced peer comparison
- time sequencing
- content with no hidden layer

Supported item count: 2-4 (one surface item plus up to three hidden layers).

Default composition: a labeled waterline, 1-2 items above the line, and the remaining items inside the lower iceberg mass.

SVG safety: use one explicit `<polygon>` silhouette plus a `<line>` waterline and SVG text.

## Fallback Layouts

The current generator supports ten archetypes. If content clearly needs another structure, hand-author the SVG and still set `data-layout`:

- `hub_spoke` for core capability plus surrounding modules.
- `comparison` is not a fallback archetype; use the built-in `matrix/comparison`
  variant (or the `comparison` input alias) for before/after or option A/B.

Add a deterministic renderer only after the pattern appears in multiple decks.
