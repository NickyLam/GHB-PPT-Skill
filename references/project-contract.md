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
