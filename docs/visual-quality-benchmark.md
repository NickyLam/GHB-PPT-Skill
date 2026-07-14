# Visual Quality Benchmark

This benchmark freezes the visual-quality comparison inputs before schema-driven
renderer geometry changes. It is deterministic, offline, and deliberately does
not require a model adapter, network access, credentials, or committed binary
render artifacts.

## Frozen corpus

- `tests/fixtures/scenarios.json` contains 30 independent body-slide inputs.
- `tests/fixtures/visual_quality_cases.json` assigns every semantic source once.
- The six page purposes are `architecture`, `process`, `comparison`, `timeline`,
  `metrics`, and `summary`.
- Each purpose has two calibration cases, one pilot holdout, and two final
  holdouts. Partition assignment is bound by a canonical SHA-256 digest.
- Calibration consumers cannot request either holdout partition. U11 receives
  only pilot holdouts; final evaluation receives only final holdouts.

The source identity is `(scenario_id, body_slide_index)`. Reusing an identity in
another case or partition is a contract error because it would leak the same
semantic page into tuning and evaluation.

## Rebuild pre-change SVG evidence

Run before changing `scripts/ppt_master/svg_layouts.py`:

```bash
python3 tests/fixtures/build_visual_benchmark.py \
  --output artifacts/visual-benchmark/pre-change
```

The builder refuses to overwrite an existing destination. It regenerates each
authored SVG with the current offline renderer and compares its SHA-256 digest
with the frozen value in `visual_quality_cases.json`. PNG/PDF evidence is not
fabricated when an Office renderer and target fonts are unavailable; cases
record `unavailable-without-render` and the later render stage must add renderer,
DPI, font availability, substitutions, and warnings.

Use `--validate-only`, `--consumer tuning`, `--consumer u11-pilot`, or
`--consumer final-evaluation` for contract and partition checks that create no
artifacts.

## Blind preference protocol

`tests/fixtures/visual_preferences.json` freezes the review rules:

- randomized left/right presentation with before/after identity hidden;
- at least three independent eligible reviewers per page;
- at least two eligible non-tie judgments for a page decision;
- ties and abstentions retained for audit but excluded from the denominator;
- aggregation per page before aggregation across pages;
- any structural regression vetoes the page;
- duplicate reviewer/page judgments are invalid.

Pilot expansion requires at least 70% eligible preference on pilot holdouts,
zero represented-purpose regression, zero structural vetoes, zero blocking
false positives, and at most 10% advisory false-positive rule/case pairs. The
advisory denominator and its digest are frozen before U11. Final success is
calculated separately from still-sealed final holdouts.
