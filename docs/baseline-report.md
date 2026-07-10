# Deterministic Pre-change Baseline Report

Generated: 2026-07-10  
Location: `artifacts/baseline/before/`  
Generator: `tests/fixtures/build_baseline.py`  
Content source: `tests/fixtures/scenarios.json`

## Reproduction

Run from a checkout where `artifacts/baseline/before/` does not yet exist:

```bash
python3 tests/fixtures/build_baseline.py
```

The generator deliberately refuses to overwrite an existing baseline. It uses
only local source JSON, the bundled template, bundled icons, and repository
scripts. It does not use image search, AI image generation, paid APIs, random
model output, or network access.

## Coverage and results

| Case | Final pages | Dangling rels | Duplicate slide IDs | Layout rels on injected master |
|---|---:|---:|---:|---:|
| A technical sharing | 9 | 0 | 0 | 2 |
| B management plan | 8 | 0 | 0 | 2 |
| C layout stress | 6 | 0 | 0 | 2 |
| D 1 body + default ending | 3 | 0 | 0 | 2 |
| D 3 body + default ending | 5 | 0 | 0 | 2 |
| D 3 body + explicit ending | 5 | 0 | 0 | 2 |
| D 3 body + no ending | 4 | 0 | 0 | 2 |
| D 3 body + bundled icon | 5 | 0 | 0 | 2 |
| D 10 body + default ending | 12 | 0 | 0 | 2 |

All nine final PPTX files passed ZIP integrity checks and opened with
`python-pptx 1.0.2`. The fixture matrix contains 57 rendered pages in total.

Every case preserves:

- original local source Markdown;
- `layout_plan.json` with the expanded planning fields;
- raw SVGs in `svg_output_original/`;
- background-removed SVGs in `svg_output/`;
- finalized SVGs in `svg_final/`;
- cover, content, and final PPTX files;
- command, stdout, stderr, and exit-code evidence in `commands.json`;
- an OOXML summary in `ooxml-summary.json`;
- LibreOffice-rendered PDF, per-page PNGs, and a contact sheet.

## Reproduced structural defect

The baseline proves a specific pre-change defect. A final deck with a distinct
ending layout uses three injected layouts in practice (cover, body, ending),
but `slideMaster2.xml.rels` registers only two layout relationships. The ending
layout part exists and points back to the master, so generic dangling-target
checks remain green; the graph is nevertheless incomplete from the master's
layout-list side.

The no-ending case correctly needs only two injected layouts. The post-change
validator and tests must distinguish these cases instead of merely asserting
that all relationship targets exist.

## Render evidence and limitation

LibreOfficeDev 26.8 can render the files when launched with an isolated writable
user profile. All nine cases produced PDFs, 57 page PNGs, and contact sheets.

The contact sheets show a severe environment-specific font problem:

- `Microsoft YaHei` is not installed on this machine;
- Chinese cover text renders as missing-glyph squares in some decks;
- many Chinese DrawingML text runs are blank or only retain adjacent English;
- English and numeric text is visible, and the GHB background/master decoration
  is present on cover, body, and ending pages.

Therefore the baseline proves that LibreOffice rendering is operational, but
it does **not** prove final Chinese visual fidelity. This is recorded as a real
render warning, not treated as a visual pass. `doctor` must report the missing
font and the final report must keep PowerPoint/LibreOffice font substitution on
the manual-review list until a compatible CJK font is available to the renderer.

Representative contact sheets:

- `artifacts/baseline/before/A_technical_sharing/render/contact-sheet.png`
- `artifacts/baseline/before/B_management_plan/render/contact-sheet.png`
- `artifacts/baseline/before/C_layout_stress/render/contact-sheet.png`

## Baseline size

The complete local baseline is approximately 30 MB. It is intentionally ignored
by Git to avoid committing generated PPTX/PDF/PNG binaries; the deterministic
generator, scenario data, audit, and this report are committed so the evidence
can be recreated without external services.
