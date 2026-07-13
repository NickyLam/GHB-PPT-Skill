# SVG Layout Diversity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, Office-safe SVG business layout layer to GHB-PPT-SKILL so generated PPTs can use richer structures such as pyramid, waterfall, staircase, layered architecture, matrix, timeline, funnel, flywheel, swimlane, and iceberg.

**Architecture:** Add a focused Python module under `scripts/ppt_master/` that renders reusable SVG fragments from a small `LayoutSpec` object. Add a second lightweight checker that reads `data-layout` markers and reports repeated/low-variety decks. Add a reference catalog that teaches future agents when to choose each layout. Update `SKILL.md` so Phase 2 requires a layout plan before SVG authoring and requires `data-layout` markers for quality review.

**Tech Stack:** Python standard library, `unittest`, Markdown references, existing SVG-to-PPT pipeline.

---

## File Structure

- Create `scripts/ppt_master/svg_layouts.py`: deterministic layout-fragment generator with one public `render_layout(spec)` entrypoint and ten archetype renderers.
- Create `scripts/ppt_master/check_layout_diversity.py`: standalone `data-layout` sequence checker for generated SVG decks.
- Create `tests/test_svg_layouts.py`: unit tests for emitted SVG structure, safety constraints, and unsupported layout errors.
- Create `tests/test_layout_diversity_checker.py`: unit tests for marker extraction, repeated layout detection, and long-deck variety detection.
- Create `references/svg-layout-catalog.md`: layout selection catalog for future SVG authoring.
- Modify `SKILL.md`: add layout planning contract and reference catalog usage to Phase 2.

## Task 1: Add failing tests for SVG layout generation

**Files:**
- Create: `tests/test_svg_layouts.py`

- [ ] **Step 1: Write tests that expect `scripts.ppt_master.svg_layouts` to exist**

```python
import unittest

from scripts.ppt_master.svg_layouts import LayoutSpec, render_layout


class SvgLayoutsTest(unittest.TestCase):
    def test_pyramid_outputs_office_safe_group_with_layout_marker(self):
        svg = render_layout(LayoutSpec("pyramid", ["基础层", "能力层", "战略层"], title="能力金字塔"))
        self.assertIn('data-layout="pyramid"', svg)
        self.assertGreaterEqual(svg.count("<polygon"), 3)
        self.assertIn("能力金字塔", svg)
        self.assertNotIn("<marker", svg)
        self.assertNotIn("rgba(", svg)

    def test_waterfall_outputs_steps_and_explicit_arrowheads(self):
        svg = render_layout(LayoutSpec("waterfall", ["输入", "处理", "交付"], title="瀑布递进"))
        self.assertIn('data-layout="waterfall"', svg)
        self.assertEqual(svg.count('class='), 0)
        self.assertGreaterEqual(svg.count("<rect"), 3)
        self.assertGreaterEqual(svg.count("<polygon"), 2)

    def test_all_initial_archetypes_render(self):
        for archetype in ("pyramid", "waterfall", "staircase", "layered_arch", "matrix", "timeline"):
            with self.subTest(archetype=archetype):
                svg = render_layout(LayoutSpec(archetype, ["A", "B", "C"], title=archetype))
                self.assertIn(f'data-layout="{archetype}"', svg)
                self.assertIn("<g ", svg)
                self.assertIn("</g>", svg)

    def test_unsupported_archetype_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "Unsupported layout archetype"):
            render_layout(LayoutSpec("unknown", ["A"]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tests/test_svg_layouts.py -v`

Expected: FAIL because `scripts.ppt_master.svg_layouts` does not exist.

## Task 2: Implement minimal SVG layout generator

**Files:**
- Create: `scripts/ppt_master/svg_layouts.py`

- [ ] **Step 1: Add `LayoutSpec` and `render_layout`**

Implement a dataclass with `archetype`, `items`, `title`, `x`, `y`, `width`, and `height`. `render_layout` dispatches to the supported private renderer functions and raises `ValueError("Unsupported layout archetype: ...")` for unknown values.

- [ ] **Step 2: Implement ten Office-safe renderers**

Use only safe primitives. Each renderer returns a top-level group with `id="layout-<archetype>"` and `data-layout="<archetype>"`.

- [ ] **Step 3: Run tests and verify GREEN**

Run: `python3 -m unittest tests/test_svg_layouts.py -v`

Expected: PASS.

## Task 3: Add the layout selection catalog

**Files:**
- Create: `scripts/ppt_master/check_layout_diversity.py`
- Create: `tests/test_layout_diversity_checker.py`

- [ ] **Step 1: Write failing tests for layout diversity checks**

Test `extract_layout_markers()` and `analyze_layout_sequence()` before writing the checker implementation.

- [ ] **Step 2: Implement the checker**

Implement a CLI that accepts a project directory, reads `svg_output/*.svg`, extracts the first `data-layout` marker from each SVG, and exits non-zero when diversity issues are found.

- [ ] **Step 3: Run tests and verify GREEN**

Run: `python3 -m unittest tests/test_layout_diversity_checker.py -v`

Expected: PASS.

## Task 4: Add the layout selection catalog

**Files:**
- Create: `references/svg-layout-catalog.md`

- [ ] **Step 1: Document the supported archetypes**

For each archetype, include:

- Suitable content signals.
- Content that should not use it.
- Recommended item count.
- Default composition.
- SVG safety notes.

- [ ] **Step 2: Include layout diversity rules**

Document that a deck should avoid three consecutive slides with the same `layout_archetype`, and decks of 8+ body slides should use at least four distinct structure archetypes when content supports it.

## Task 5: Update SKILL.md workflow

**Files:**
- Modify: `SKILL.md`

- [ ] **Step 1: Add layout planning to Phase 2**

After content confirmation and before SVG writing, require `layout_plan.json` with `slide`, `message`, `layout_archetype`, `density`, `items`, `reason`, and `alternatives`.

- [ ] **Step 2: Add renderer usage instructions**

Tell agents to use `scripts/ppt_master/svg_layouts.py` for the supported archetypes and hand-author only when the catalog does not fit.

- [ ] **Step 3: Add `data-layout` rule**

Require the main content group on every body SVG to include `data-layout="<archetype>"`.

## Task 6: Verify skill changes

**Files:**
- Inspect all changed files.

- [ ] **Step 1: Run unit tests**

Run: `python3 -m unittest tests/test_svg_layouts.py tests/test_layout_diversity_checker.py -v`

Expected: PASS.

- [ ] **Step 2: Run a syntax check**

Run: `python3 -m py_compile scripts/ppt_master/svg_layouts.py scripts/ppt_master/check_layout_diversity.py`

Expected: exit 0.

- [ ] **Step 3: Inspect git diff**

Run: `git diff -- SKILL.md references/svg-layout-catalog.md scripts/ppt_master/svg_layouts.py scripts/ppt_master/check_layout_diversity.py tests/test_svg_layouts.py tests/test_layout_diversity_checker.py docs/superpowers/specs/2026-07-08-svg-layout-diversity-design.md docs/superpowers/plans/2026-07-08-svg-layout-diversity.md`

Expected: diff only includes intended files.
