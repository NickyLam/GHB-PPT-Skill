# GHB OOXML Merge Contract

Use `scripts/merge_template_master.py` through the unified CLI unless debugging
the merge itself.

## Required graph

- Cover slide → cloned cover layout → injected template master
- Every body slide → selected content layout → injected template master
- Optional ending slide → cloned ending layout → injected template master
- Injected layouts → injected template master
- Injected master → injected theme and all referenced background media

The ending layout must appear in both the master relationship set and
`p:sldLayoutIdLst`. A package can have no dangling targets and still be invalid
when this reverse registration is missing.

## Allocation rules

- Allocate slide IDs, relationship IDs, master IDs, layout IDs, part names,
  theme names, media names, and tag names from the current package.
- Never assume a fixed body-page count or fixed `rId`/part suffix.
- Resolve basename collisions by allocating a new part and updating the copied
  relationship target.
- Update `[Content_Types].xml` with required defaults and overrides.
- Serialize the OPC Content Types namespace as the default namespace;
  LibreOffice rejects the semantically equivalent `ns0:` wire form.
- Verify all relationship targets before atomically replacing the output.

## Ending options

- Default: clone the template's last slide.
- `--no-ending`: omit it.
- `--ending-slide N`: clone a specific template slide.

## Do not do

- Do not edit the ZIP in place.
- Do not mutate XML with regex.
- Do not overwrite existing media or theme parts by basename.
- Do not discard unknown errors or accept a file only because python-pptx opens
  it.

Use `scripts/validate_ghb_pptx.py` after every merge. See
[template-analysis.md](template-analysis.md) before using a different template.
