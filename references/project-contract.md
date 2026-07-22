# Project Contract

Read this reference after the six decisions are confirmed and before writing
`spec_lock.md`, acquiring assets, or authoring SVGs.

## Confirmation receipt

Write `<project>/confirmation.json`. A real project must use
`confirmation_source: "user"`; deterministic repository fixtures use
`"fixture"`. Fixture confirmation is accepted only under repository
`examples/` / `tests/fixtures/`, or when the fixture runner injects the
test-only `GHB_PPT_TEST_FIXTURE=1` environment marker. Normal production CLI
usage has no bypass option. Do not use `fixture` to bypass a real user's
confirmation.

```json
{
  "schema": "ghb.confirmation.v1",
  "status": "confirmed",
  "confirmation_source": "user",
  "confirmed_at": "2026-07-13T10:00:00+08:00",
  "decision_digest": "<sha256 of canonical decisions object>",
  "decisions": {
    "audience": "技术负责人",
    "page_range": "8–10 body slides",
    "mode": "briefing",
    "outline": [
      {"title": "结论式页面标题", "rhythm": "anchor"}
    ],
    "content_tradeoffs": {
      "expand": ["关键证据"],
      "omit": ["重复背景"],
      "combine": ["现状与问题"]
    },
    "visual_assets": {
      "image_source": "none",
      "icon_set": "tabler-outline"
    }
  }
}
```

The validator rejects pending status, missing timestamps, missing decisions,
invalid modes, outline rows without a title/rhythm, incomplete trade-off
fields, missing image/icon choices, and a missing/stale `decision_digest`.
Compute the digest with `confirmation_digest()` from
`scripts/validate_project_contract.py` after the user confirms. Any later
decision edit requires renewed confirmation and a new timestamp/digest.

## Content model

Write `<project>/content_model.json` before `layout_plan.json`:

```json
{
  "schema": "ghb.content-model.v1",
  "claims": [
    {
      "id": "claim-01",
      "statement": "平台能力必须先于规模化流程建设",
      "must_include": true,
      "source_reference": "sources/source.md#平台底座"
    }
  ]
}
```

Every layout-plan row uses `claim_ids` to map the page back to claims. Every
`must_include` claim needs a source reference and must appear in the plan.

## Visual profile v1

`visual_profile.json` owns measurable project-wide visual policy.
`ghb_ppt.py init` creates the valid strict GHB scaffold below; it does not
invent a page purpose, focal target, or layout coordinates.

```json
{
  "schema": "ghb.visual-profile.v1",
  "brand": {"primary": "#AB1F29", "text": "#2B2B2B", "surface": "#FFFFFF"},
  "typography": {
    "enforcement": "strict",
    "min_title_pt": 28,
    "min_body_pt": 18,
    "min_caption_pt": 12,
    "min_source_pt": 10,
    "min_footer_pt": 9,
    "min_title_body_ratio": 1.5
  },
  "spacing": {"base_unit": 8, "min_component_gap": 16},
  "occupancy": {"body": {"min": 0.42, "max": 0.78}},
  "composition": {"default_density": "balanced", "default_emphasis": "ranked"},
  "focal": {"allowed_zones": ["left", "center", "right", "full"]},
  "deck_rhythm": {"default_role": "continuity", "max_same_role_streak": 3},
  "budgets": {"max_text_chars": 240, "max_nodes": 8}
}
```

The validator rejects an unknown schema major, inverted occupancy bands,
non-positive or unordered typography roles, non-strict enforcement, invalid
spacing/defaults, an empty focal-zone policy, and non-positive budgets. SVG
font sizes are CSS pixels and convert to points at `0.75`; the default floors
therefore require at least 38 px title and 24 px body text. Unknown additive
fields are retained and tolerated. Page budgets may tighten but never exceed
the project maxima.

## Art direction v1

`art_direction.json` owns deck-level aesthetic coherence. `init` writes an
intentionally incomplete scaffold; after the six decisions are confirmed, the
author must replace `visual_thesis: null` and choose real anchor slide IDs
before any SVG is authored.

```json
{
  "schema": "ghb.art-direction.v1",
  "design_mode": "instructional",
  "visual_thesis": "用证据与决策页建立从工具体验到团队工作流的叙事",
  "narrative_arc": ["orient", "explain", "prove", "decide"],
  "page_families": ["editorial", "evidence", "comparison", "process", "decision"],
  "surface_strategy": {
    "variants": ["light", "contrast", "evidence"],
    "max_same_variant_streak": 2
  },
  "focal_strategy": {"max_distributed_streak": 4},
  "anchor_slide_ids": ["body-01", "body-09", "body-18"],
  "imagery": {"strategy": "evidence-first", "max_images_per_page": 2}
}
```

The validator requires a supported design mode, a non-empty thesis, at least
three narrative stages and page families, at least two surface variants,
positive streak limits, at least one real anchor ID, and an image policy of
`none`, `evidence-first`, `editorial`, or `data-led`. The evidence manifest
binds this file upstream of both authored and finalized SVG bundles.
`design_mode` must exactly equal the confirmed `decisions.mode`, and every
`anchor_slide_ids` entry must equal a `slide_id` that exists in the current
`layout_plan.json`; either mismatch is confirmation/plan drift and blocks the
visual contract gate.

## Nested page schema v1

Every newly authored layout row declares its intent in `page_schema`; concrete
component boxes remain renderer-derived. A valid architecture anchor page is:

```json
{
  "slide_id": "body-01",
  "layout_archetype": "layered_arch",
  "page_schema": {
    "schema": "ghb.page-schema.v1",
    "slide_id": "body-01",
    "page_purpose": "architecture",
    "layout_variant": "layered_arch/default",
    "density": "balanced",
    "rhythm_role": "anchor",
    "emphasis": "single-focal",
    "focal_target": "platform-core",
    "budgets": {"max_text_chars": 180, "max_nodes": 7}
  }
}
```

V1 vocabulary and precedence:

| Concern | Allowed values / boundary |
|---|---|
| `page_purpose` | exactly one primary value: `architecture`, `process`, `comparison`, `timeline`, `metrics`, `summary`, `hero`, `section-anchor`, `evidence`, `case-study`, `instruction`, `decision`, `risk`, `screenshot`, `data-story`, `recommendation`, or `closing` |
| `density` | `breathing`, `balanced`, or `dense`; page value overrides the profile default but cannot exceed profile budgets or typography floors |
| `rhythm_role` | `anchor`, `continuity`, or `transition`; this is independent of density |
| `emphasis` | `single-focal`, `ranked`, or `distributed`; `single-focal` requires a non-empty `focal_target` |
| `layout_variant` | `<existing-archetype>/<catalogued-variant>`; `comparison` is accepted as the semantic alias of the existing `matrix` family |
| `budgets` | positive integer `max_text_chars` and `max_nodes`, each no greater than the profile maximum |
| `bounds_override` | optional `{x,y,width,height}` inside the 1280×720 canvas; omit it unless an authored override is genuinely required |

The nested `slide_id` must exactly match the containing layout row. The variant
family must match `layout_archetype`; the only v1 alias is `comparison` for
`matrix`. Unknown additive fields are tolerated, but missing required intent is
never inferred.

Density is not emphasis. `page_schema.emphasis` is a semantic decision grounded
in the row's `key_message`, not a consequence of density or `rhythm_role`.
`single-focal` requires a visible `focal_target` that the conclusion actually
privileges. If no such relationship exists, use `distributed` or `ranked` and
do not invent a highlighted ordinal item.

The legacy confirmation/layout rhythm vocabulary remains unchanged:
`anchor`, `dense`, and `breathing`. It is evidence of the confirmed outline,
not the new page density or rhythm role. During explicit migration, a legacy
`anchor` may seed `page_schema.density: balanced`; `dense` and `breathing` map
to the same-named densities. The author must still choose `rhythm_role`,
purpose, emphasis, focal target, and variant. Validators never silently create
a missing `page_schema`.

The visual contract is mandatory in the production CLI. Diagnose it directly:

```bash
python3 scripts/ghb_ppt.py check-project --project projects/<name>
```

`check-project`, `check-svg`, `build-content`, `merge`, and `build` all require
`visual_profile.json`, a completed `art_direction.json`, and one valid
`page_schema` per planned body slide. There is no production opt-out. Direct
library calls may still omit the explicit gate only for legacy unit fixtures;
that compatibility surface is not an authoring path.

## Layout semantic fields

Add these fields when the matching layout is selected:

| Layout | Required semantic evidence |
|---|---|
| `timeline` | non-empty `order_signal` |
| `matrix` | `axes.x` and `axes.y` |
| `swimlane` | `owners` with at least two entries |
| `flywheel` | non-empty `loop_closure` |
| `comparison` | non-empty `comparison_criteria` |

The authored SVG must also prove the page purpose with visible semantic
markers; `data-layout` is descriptive and is not sufficient evidence:

| Page purpose | Required SVG semantics |
|---|---|
| `process` | two or more `data-flow-node` plus an edge, or two `data-step` / `data-lane` markers |
| `instruction` / `timeline` | two or more `data-step` markers; instruction may alternatively use a complete flow |
| `architecture` | two or more `data-layer` markers |
| `comparison` | two or more unique `data-component-id` components |
| `evidence` / `case-study` / `screenshot` | at least one `data-evidence` object |
| `metrics` / `data-story` | at least one `data-metric` object |
| `decision` / `recommendation` | at least one `data-decision` or `data-recommendation` object |
| `risk` | both `data-risk` and `data-mitigation` objects |
| `hero` / `section-anchor` / `closing` | at least one visible `data-focal="true"` object |

## Authored and finalized identity

`svg_output/` is the immutable authored bundle. `build-content` runs the
authored gate, writes finalized copies into `svg_final/`, removes the preview
`<g id="bg">` only from those copies, runs the finalized gate, and converts
only `svg_final/` into PPTX. Any authored edit creates a new upstream digest;
post-processing must never rewrite authored evidence in place.

Run the contract gate directly when diagnosing:

```bash
python3 scripts/ghb_ppt.py check-project --project projects/<name>
```

`check-svg`, `build-content`, `merge`, and `build` call the same gate automatically.
There is no production bypass flag.
