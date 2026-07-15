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

The builder refuses to overwrite an existing destination. It copies the
versioned pre-change authored SVG fixtures and compares every SHA-256 digest
with the frozen value in `visual_quality_cases.json`; it never asks the later,
modified renderer to recreate what “before” looked like. PNG/PDF evidence is not
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

## Build and evaluate the two-family pilot

U11 changes only the existing `timeline` and `matrix` families. The builder
copies all six immutable pilot-holdout before SVGs, generates after SVGs only
for the three timeline/matrix cases, measures actual SVG geometry, and writes
separate public blind-review and evaluator artifacts:

```bash
python3 tests/fixtures/build_visual_pilot.py \
  --output artifacts/visual-benchmark/u11-pilot
```

The public `blind-review-template.json` intentionally omits the masked-side
role mapping and points only to `blind/<case>/A.svg` and `B.svg`. Give reviewers
only the template and `blind/` directory; keep `before/`, `after/`, and
`pilot-gate-review.json` private from them. After independent review, merge the
audited judgments into the evaluator record. The embedded `judgment_template`
lists every required audit field; rubric dimensions use finite 1–5 values.
Complete the
frozen advisory rule/case adjudication in
`deterministic-audit-template.json`, then run:

```bash
python3 scripts/ghb_visual_quality.py pilot-gate \
  --preferences tests/fixtures/visual_preferences.json \
  --review artifacts/visual-benchmark/u11-pilot/pilot-gate-review.json \
  --deterministic artifacts/visual-benchmark/u11-pilot/deterministic-audit-template.json \
  --output artifacts/visual-benchmark/u11-pilot/pilot-gate.json
```

Empty or insufficient human evidence returns `decision: pending`,
`proceed: false`, and a non-zero exit. It never fabricates a pass. A failed
threshold similarly blocks expansion; changing the frozen threshold or
denominator is not a recovery action.

### Revision after an exposed pilot round

Once reviewers have seen a pilot pair, those pages cannot support a later
unseen-value claim. Preserve the raw feedback, revise geometry using calibration
inputs, and freeze a new semantic holdout before reviewing the revision.

The first U11 feedback round preferred equal-size matrix options while also
requiring visible gaps. The matrix revision therefore keeps all four cards
equal in width and height, applies density-specific gaps, and expresses focal
intent through fill, border, and typography rather than unequal card area. The
timeline focal geometry remains unchanged. The exposed round-one pages are
diagnostic evidence only and must not be reused to pass the revision gate.

Build the frozen revision holdout with:

```bash
python3 tests/fixtures/build_visual_pilot.py --revision \
  --output artifacts/visual-benchmark/u11-pilot-revision-2
```

The revision builder reads only `visual_pilot_revision_cases.json` and the
versioned SVGs produced from the exact pre-U11 renderer source at commit
`aabfc6a`; it does not read final-holdout cases.
