# SVG Layout Diversity Design

## Goal

Improve GHB-PPT-SKILL's body-slide SVG output so generated decks can reliably use richer business layouts such as pyramid, waterfall, staircase, layered architecture, matrix, timeline, funnel, flywheel, swimlane, and iceberg instead of repeatedly falling back to cards and simple columns.

## Current Problem

The current skill locks template colors, fonts, chrome, and PPT merge behavior, but it does not make layout choice explicit. As a result, the SVG authoring step depends on the model choosing a page structure from memory. That tends to converge on safe but repetitive layouts: cards, grids, tables, and left-right split pages.

## Design

Add a small, deterministic SVG layout layer between content planning and hand-authored SVG:

1. A `layout_plan.json` contract documents each slide's `layout_archetype`, rationale, density, item count, and alternatives.
2. A reusable Python module generates Office/WPS-safe SVG fragments for high-frequency business layouts.
3. A reference catalog explains when to choose each archetype and what constraints apply.
4. A lightweight diversity checker reads `data-layout` markers from generated SVGs and flags over-repetition.
5. The SKILL workflow requires layout planning before SVG creation and records `data-layout` on each content group for later quality review.

## Initial Layout Set

The first implementation now includes ten layouts because the original reported gap specifically called out narrowing, loop, role-process, and visible-vs-hidden structures in addition to the initial hierarchy and sequence layouts:

- `pyramid` for hierarchy, maturity models, strategy decomposition, and capability stacks.
- `waterfall` for staged delivery, progressive handoff, and cumulative movement.
- `staircase` for maturity progression, capability upgrades, and phased improvement.
- `layered_arch` for system layers, platform stacks, and governance models.
- `matrix` for two-axis comparison, priority mapping, and portfolio decisions.
- `timeline` for roadmap, milestones, and sequential plans.
- `funnel` for narrowing stages, conversion, and screening flows.
- `flywheel` for reinforcing feedback loops and growth engines.
- `swimlane` for role × process handoff across teams or functions.
- `iceberg` for visible symptoms versus hidden causes or constraints.

## Technical Constraints

Generated fragments must stay inside the current SVG-to-PPT pipeline constraints:

- Use explicit SVG primitives: `rect`, `polygon`, `line`, `text`, `tspan`, and `g`.
- Avoid `marker`, `filter`, `mask`, `foreignObject`, external CSS, class selectors, and browser-only features.
- Use HEX colors and `fill-opacity` instead of `rgba()` or group opacity.
- Use the GHB template palette by default: `#AB1F29`, `#44546A`, `#F6F6F7`, `#E0E0E0`, `#2B2B2B`, and `#6E6E73`.
- Keep output embeddable as a content fragment under the existing page chrome.

## Non-Goals

- Do not integrate Mermaid, ECharts, D3, or Vega directly in this pass.
- Do not change the template PPTX, master merge script, cover generation, image search, or AI image generation.
- Do not rewrite the full SVG quality checker in this pass.
- Do not touch unrelated dirty files already present in the workspace.

## Validation

Validation has three layers:

1. Unit tests prove each layout generator emits expected structural SVG and `data-layout`.
2. Unit tests prove unsupported archetypes fail with a clear error.
3. Diversity-checker tests prove three repeated layouts and low long-deck variety are flagged.
4. A smoke check imports the module and renders representative fragments for all supported layouts.

## Future Extension

After the current ten layouts are stable, the same interface can still add `hub_spoke` and `comparison` without changing the SKILL workflow.
