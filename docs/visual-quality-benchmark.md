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
lists every required audit field; rubric dimensions use finite 1–5 values or
the explicit `not-scored` marker when reviewers cannot assign meaningful
numbers. `not-scored` never changes the A/B aggregation or gate threshold.
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

## Build the final-holdout evaluation bundle

Run this only when final evaluation is authorized. It opens the twelve sealed
`final-holdout` cases (two per page purpose), copies their frozen before SVGs,
and uses the current schema-aware `render_layout` path to generate after SVGs
for every actual family represented by those cases. The operation is local,
does not invoke a model adapter or subprocess, does not read credentials, and
refuses to overwrite an existing destination:

```bash
python3 tests/fixtures/build_visual_benchmark.py --final-evaluation \
  --output artifacts/visual-benchmark/final-holdout
```

The output separates reviewer-visible evidence from evaluator-only evidence:

- Give reviewers only `blind-review-template.json` and `blind/`.
- Keep `evaluator-record.json`, `before/`, `after/`,
  `final-benchmark-manifest.json`, and `deterministic-fixtures.json` private.
- The public template contains masked A/B paths and no baseline/optimized role
  mapping or randomization seed. A fresh private HMAC seed randomizes each
  bundle; `evaluator-record.json` retains the seed and role mapping so the
  exact bundle remains auditable without making roles derivable from case IDs.
  The private record starts with no judgments and `decision: pending`.
- The manifest records source and artifact digests, page schema, before/after
  proxy metrics, renderer provenance, and limitations. These metrics are
  evidence, not a human aesthetic score.

The deterministic fixture report characterizes an approved composition and
stable negative cases for geometry-based fake diversity, underscaled content,
explicit long-title bounds overflow, primary-color overuse, and repeated focal
zones. It also constructs a real temporary PPTX and runs `validate_pptx` to
prove `empty-text-box`, and exercises the renderer's font-evidence projection
to prove `target-font-missing`. Numeric expectations are frozen in each fixture
and compared with explicit tolerances; a rebuild does not validate itself by
comparing two fresh runs. PNG equality is not a gate.

### Human review handoff and evaluation

Each page needs at least three independent eligible reviewers who did not
author or tune the evaluated variant, and at least two non-tie/non-abstention
judgments. Reviewers score the frozen rubric, retain ties and abstentions, and
set `structural_veto` when semantics, editability, clipping, or required content
regress. Merge the records into the private `judgments` array without changing
the pair assignments, masked IDs, or role mapping. Reviewer identifiers must be
stable opaque hashes; do not put names or email addresses in the artifact.
Every reviewer hash must have exactly one private roster attestation with
`independent`, `did_not_author`, and `did_not_tune` all true.

Evaluate only after the human record is complete: exclude tie and abstention
votes from each page denominator, determine the page winner first, then
aggregate decided pages and purpose results. Passing requires optimized pages
to win at least 70% of decided page comparisons, every purpose to be
non-regressing, and no structural veto. Preserve the original bundle and
completed evaluator record together so randomization, disagreements, ties,
abstentions, denominator, and provenance remain auditable.

The SVG-only bundle cannot establish editability, Office clipping, target-font
fidelity, or rendered readability. Those dimensions are marked unreviewable,
and the private structural evidence record starts unavailable. A final gate
cannot pass until fresh PPTX, render, target-font, and contact-sheet evidence
are added with their artifact SHA-256 values. In an environment without an
Office renderer or GUI-equivalent render path, the absent contact sheet remains
an explicit blocker rather than an inferred pass.
Each available structural-evidence row must name a distinct artifact path
relative to the evaluator record and its real SHA-256. The final gate resolves
the path inside that directory, rejects symlinks/traversal, and recomputes the
digest; a 64-character placeholder is not evidence.
It also requires a 12-slide PPTX whose visible text matches the frozen cases,
12 distinct non-blank rendered page PNGs, a parseable 12-page PDF, target-font
availability from that same render report, and a contact sheet reproduced from
those exact pages. A self-written report, repeated blank image, hidden tiny
text, or unrelated but well-formed deck cannot satisfy the gate.

After adding real reviewer judgments, roster attestations, and structural
evidence, run the evaluator. It reuses the same blind-record validation and
page-first aggregation core as the pilot gate:

```bash
python3 scripts/ghb_visual_quality.py final-gate \
  --preferences tests/fixtures/visual_preferences.json \
  --corpus tests/fixtures/visual_quality_cases.json \
  --scenarios tests/fixtures/scenarios.json \
  --fixture-contract tests/fixtures/final_deterministic_contract.json \
  --review artifacts/visual-benchmark/final-holdout/evaluator-record.json \
  --deterministic artifacts/visual-benchmark/final-holdout/deterministic-fixtures.json \
  --output artifacts/visual-benchmark/final-holdout/final-gate.json
```

Missing judgments or structural evidence returns `decision: pending`; invalid
or duplicate eligibility attestations are rejected. A complete record passes
only at 70% optimized page preference, no purpose regression, zero structural
vetoes, and no deterministic issue-code or frozen-metric regression. Until
those real inputs exist, U6's human-preference claim remains blocked.
