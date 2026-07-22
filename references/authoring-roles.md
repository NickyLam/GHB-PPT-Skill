# Authoring role boundaries

These are sequential evidence roles, not a requirement to spawn subagents. A
single capable model may perform all five, but it must preserve the hand-off
artifacts and review each phase from a fresh role perspective.

| Role | Inputs | Required output | Must not do |
|---|---|---|---|
| Content architect | confirmed brief, source material | `content_model.json`, evidence boundaries, conclusion titles | choose geometry before claims are stable |
| Layout planner | content model, art direction | `layout_plan.json`, page rhythm, layout-fit evidence | generate SVG or fabricate source evidence |
| SVG author | finalized plan, visual profile, template profile | sequentially authored `svg_output/*.svg` | batch-generate the full deck or change confirmed claims |
| Engineering executor | authored SVG, cover plan, template | finalized SVG, PPTX, reports, render evidence | silently repair semantic content or waive warnings |
| Visual reviewer | contact sheet, page PNGs, layout plan, SVG/structure summaries | bounded findings with slide, issue type, evidence box and action | accept a deck because structural checks alone pass |

The SVG author works page by page in the main context. Engineering scripts may
perform deterministic output and post-processing, but they do not replace the
SVG author's composition decisions.
