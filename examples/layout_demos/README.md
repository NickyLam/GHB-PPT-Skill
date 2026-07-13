# Layout Demos

This example project generates four demo body-slide SVG pages for the newly added
layout archetypes:

- `funnel`
- `flywheel`
- `swimlane`
- `iceberg`

Regenerate the demo assets from the repo root:

```bash
python3 examples/layout_demos/generate_demo_svgs.py
python3 scripts/ghb_ppt.py check-project --project examples/layout_demos
python3 scripts/ppt_master/svg_quality_checker.py examples/layout_demos
python3 scripts/ppt_master/check_layout_diversity.py examples/layout_demos
```

Outputs:

- `examples/layout_demos/layout_plan.json`
- `examples/layout_demos/svg_output/*.svg`
