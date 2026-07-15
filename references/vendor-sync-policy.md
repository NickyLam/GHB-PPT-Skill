# Vendored ppt-master Sync Policy

`scripts/ppt_master/` and `templates/icons/` are vendored to keep the default
GHB build offline and self-contained. They are not an automatically tracking
dependency.

## Boundary

Keep GHB-specific orchestration, background removal, master merging,
validation, rendering, and reporting in top-level `scripts/`. Treat the
converter, template-fill, source converters, image backends/sources, and SVG
finalization packages under `scripts/ppt_master/` as vendored upstream code.

The GHB-owned additions currently colocated under the vendor tree are:

- `svg_layouts.py`
- `check_layout_diversity.py`
- `visual_asset_checker.py`

`svg_layouts.py` also owns the GHB-specific `LayoutSpec` visual-intent fields,
per-family `LAYOUT_CONTRACTS`, and Office-safe density/variant/emphasis
geometry. These are local renderer contracts, not imported upstream API.

They remain there because they integrate directly with the vendored SVG
pipeline. Mark and test any further colocated additions explicitly.

## Sync procedure

1. Record the upstream repository, revision/tag, license, and import date in the
   sync change description.
2. Compare only the selected upstream paths; do not bulk-copy unrelated tools.
3. Reapply the small local path adaptations for bundled icons and any GHB-owned
   hooks.
4. Avoid formatting-only rewrites.
5. Run the full offline test suite and the A/B/C/D fixture matrix.
6. Inspect OOXML reports and representative contact sheets before accepting the
   sync.
7. Document conflicts, intentionally skipped upstream changes, and remaining
   local patches.

## Local vendor modifications

Every direct modification to vendored code must have a focused regression test
and a comment explaining the GHB packaging reason. Prefer a top-level adapter
when the change can be isolated outside the vendor tree.

For layout-contract changes, focused coverage must prove all ten built-in
families, legacy byte stability when intent is omitted, item/text budget
failures, focal visibility, and the restricted SVG element set. Keep
`comparison` normalized to `matrix`; do not add it to the archetype inventory.
