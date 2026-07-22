# GHB Contract Registry

This file is the single index for authoring artifacts and SVG semantic markers.
Detailed algorithms remain in their focused references; other documents should
link here instead of redefining field names.

## Project artifacts

| Artifact | Schema / required root fields | Owner |
|---|---|---|
| `confirmation.json` | `ghb.confirmation.v1`; `status`, `confirmation_source`, `decision_digest`, `decisions` | user confirmation gate |
| `content_model.json` | `ghb.content-model.v1`; `claims[].id`, `statement`, `source_reference` | content architecture |
| `art_direction.json` | `ghb.art-direction.v1`; `design_mode`, `visual_thesis`, `narrative_arc`, `page_families`, `anchor_slide_ids` | art direction |
| `visual_profile.json` | `ghb.visual-profile.v1`; `canvas`, `brand`, `typography`, `spacing`, `composition`, `budgets`, `deck_rhythm` | visual system |
| `layout_plan.json` | rows with `slide_id`, `claim_ids`, `page_schema`, `source`, `notes` | page planning |
| `spec_lock.md` | canvas, mode, colors, typography, composition and asset policy | human execution lock |
| `design_spec.md` | audience, narrative, page strategy and evidence boundary | human design brief |
| `analysis/cover_fill_plan.json` | `template_fill_pptx_plan.v1`; source slide and slot replacements | cover template-fill |

Scaffold output may carry `draft`, `needs_review`, or `origin: scaffold` only
during planning. A release build rejects those markers with
`plan-draft-not-finalized`.

## SVG semantic markers

| Purpose | Required markers |
|---|---|
| page layout | `data-layout`, `data-density`, `data-variant`, `data-emphasis` |
| typography QA | `data-qa-role`, `data-qa-box`, stable `main-title` / `body-*` / `caption-*` / `source-*` / `footer-*` IDs |
| native section frame | `id="template-section-label"` |
| flow | `data-flow-node`, `data-flow-from`, `data-flow-to`, `data-step`, `data-lane` |
| comparison | `data-component`, `data-component-id`, `data-component-pair`, `data-component-parent`, `data-component-slot` |
| evidence and intent | `data-evidence`, `data-metric`, `data-decision`, `data-risk`, `data-mitigation`, `data-focal` |
| fixed text fidelity | `data-text-fit="fixed"` together with a positive `data-qa-box` |

## Stable contract failure codes

- planning: `plan-contract-drift`, `plan-draft-not-finalized`
- component geometry: `component-void`, `component-slot-overflow`, `component-balance-outlier`
- header and text: `header-safe-zone-collision`, `text-component-overflow`
- flow: `connector-node-intersection`, `connector-text-intersection`
- font delivery: `invalid-embedded-font-contract`, `invalid-font-embed-report`, `font-embed-report-mismatch`

The documentation consistency test verifies that every marker and stable code
registered above is referenced by implementation or focused regression tests.
