# Authoring Workflow

Use this reference after the skill triggers and before creating body SVGs.

## Content confirmation gate

For a real user deck, read the source and ask once for six decisions. For every
decision, provide concrete options, mark one recommendation, and state how to
change it.

1. Audience: propose 2–4 source-specific audiences and explain the change in
   tone or information density.
2. Page range: preserve source pagination, re-plan, compress, or expand; give a
   recommended range.
3. Mode: `instructional`, `briefing`, or `narrative`.
4. Outline: list every proposed body slide with title and rhythm
   (`anchor`/`dense`/`breathing`).
5. Content trade-offs: identify what to expand, omit, and combine.
6. Visual assets: choose none, extracted, user-provided, web search, or AI
   generation; separately choose an icon set if useful.

Do not write `spec_lock.md`, acquire assets, or author SVGs until the user
confirms. After confirmation, continue through build and QA without additional
engineering approval. In repository tests and CI, use the fixed fixture config
instead of waiting for a user.

Immediately persist the confirmed decisions in `confirmation.json` using
[project-contract.md](project-contract.md). Use `confirmation_source: user` for
real work and `fixture` only for deterministic repository fixtures. The build
gate rejects missing or incomplete confirmation; never fabricate the receipt.

## Required project files

Create these before `build`:

- `analysis/cover_fill_plan.json`: template-fill plan for cover slots.
- `sources/source.md`: normalized source content.
- `design_spec.md`: confirmed audience, mode, scope, visual strategy, and asset
  choice.
- `confirmation.json`: machine-readable evidence that all six decisions were
  explicitly confirmed.
- `spec_lock.md`: GHB canvas, colors, typography, and image policy.
- `content_model.json`: traceable claims, evidence, importance, and required
  content before page planning.
- `layout_plan.json`: one record per body slide.
- `svg_output/NN_name.svg`: authored body pages.
- `notes/total.md`: one speaker-note section per SVG when notes are required.

The layout plan must include `slide_id`, `purpose`, `key_message`, `audience`,
`content_density`, `rhythm`, `layout_type`, `visual_encoding`,
`editable_elements`, `image_requirement`, `source_reference`, and
`speaker_note`. Also include `items`, `reason`, and alternatives for the layout
diversity checker.

Map every page to `content_model.json` using `claim_ids`. Add the semantic
evidence fields required by [project-contract.md](project-contract.md) for
timeline, matrix, swimlane, flywheel, and comparison layouts.

## GHB lock

Use a 1280×720 SVG viewBox and a 16:9 PowerPoint canvas.

- Primary: `#AB1F29`
- Secondary accent: `#44546A`
- Text: `#2B2B2B`; secondary: `#6E6E73`
- Border: `#E0E0E0`; surface: `#F6F6F7`
- Title: Arial Black with Microsoft YaHei for CJK
- Body: Microsoft YaHei with an Office-safe Latin fallback
- Body/content/title minimums: follow the density plan; never solve overflow by
  globally shrinking text.

Use the standard body surface at `x=56, y=96, width=1168, height=608`. Keep the
top template decoration visible. Include exactly one preview-only
`<g id="bg">` white background so the formal removal step can delete it.

## Authoring rules

- Express a conclusion in each title, not a generic section label.
- Preserve titles, labels, cards, tables, processes, and architecture as SVG
  text/shapes that convert to editable DrawingML.
- Do not use a full-slide image or screenshot as body content.
- Put `data-layout="<archetype>"` on the main content group.
- Use at least four genuine structures for decks with eight or more body pages
  when content supports them; never count recolored card grids as diversity.
- Handle long text in this order: rewrite, change layout, split the slide,
  tighten spacing, then make a small bounded font adjustment.
- Use explicit Office-safe SVG geometry. See
  [visual-quality-rules.md](visual-quality-rules.md) for the complete banned
  feature and QA contract.
- Choose page structures from [svg-layout-catalog.md](svg-layout-catalog.md).
- For images, icons, attribution, and optional online paths, read
  [svg-image-embedding.md](svg-image-embedding.md),
  [image-searcher.md](image-searcher.md), or
  [image-generator.md](image-generator.md) only when that path is selected.

## Cover plan

For the bundled template use:

- `s01_sh8`: title
- `s01_sh6`: subtitle
- `s01_sh4`: date

Keep cover text concise. `build-cover` applies template-fill and then repairs
KaiTi to Microsoft YaHei atomically.
