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

`visual_profile.json` owns project-wide visual direction. `ghb_ppt.py init`
creates the valid neutral GHB scaffold below; it does not invent a page purpose,
focal target, or layout coordinates.

```json
{
  "schema": "ghb.visual-profile.v1",
  "brand": {"primary": "#AB1F29", "text": "#2B2B2B", "surface": "#FFFFFF"},
  "typography": {"min_title_pt": 28, "min_body_pt": 18, "min_title_body_ratio": 1.5},
  "spacing": {"base_unit": 8, "min_component_gap": 16},
  "occupancy": {"body": {"min": 0.42, "max": 0.78}},
  "composition": {"default_density": "balanced", "default_emphasis": "ranked"},
  "focal": {"allowed_zones": ["left", "center", "right", "full"]},
  "deck_rhythm": {"default_role": "continuity", "max_same_role_streak": 3},
  "budgets": {"max_text_chars": 240, "max_nodes": 8}
}
```

The validator rejects an unknown schema major, inverted occupancy bands,
non-positive typography/spacing values, invalid defaults, empty focal-zone
policy, and non-positive budgets. Unknown additive fields are retained and
tolerated. Page budgets may tighten but never exceed the project maxima.

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
| `page_purpose` | exactly one primary value: `architecture`, `process`, `comparison`, `timeline`, `metrics`, or `summary`; optional additive secondary tags do not change the primary purpose |
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

Before the U11 rollout gate, use the explicit contract check on migrated/pilot
projects:

```bash
python3 scripts/ghb_ppt.py check-project --project projects/<name> --require-visual-contract
```

Normal legacy checks remain available during this rollout window. New projects
already receive `visual_profile.json`, but page schemas are written only during
layout planning after user confirmation.

## Layout semantic fields

Add these fields when the matching layout is selected:

| Layout | Required semantic evidence |
|---|---|
| `timeline` | non-empty `order_signal` |
| `matrix` | `axes.x` and `axes.y` |
| `swimlane` | `owners` with at least two entries |
| `flywheel` | non-empty `loop_closure` |
| `comparison` | non-empty `comparison_criteria` |

Run the contract gate directly when diagnosing:

```bash
python3 scripts/ghb_ppt.py check-project --project projects/<name>
```

`check-svg`, `build-content`, and `build` call the same gate automatically.
There is no production bypass flag.
