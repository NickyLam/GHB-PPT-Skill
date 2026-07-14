import unittest
import re

from scripts.ppt_master.svg_layouts import LayoutSpec, render_layout


class SvgLayoutsTest(unittest.TestCase):
    def test_legacy_timeline_and_matrix_geometry_is_unchanged_without_intent(self):
        timeline = render_layout(LayoutSpec("timeline", ["A", "B", "C", "D"]))
        matrix = render_layout(LayoutSpec("matrix", ["A", "B", "C", "D"]))
        self.assertIn('x1="120" y1="420.0" x2="1160"', timeline)
        self.assertIn('x="98.0" y="398.0" width="44" height="44"', timeline)
        self.assertIn('x="120.0" y="220.0" width="520.0" height="200.0"', matrix)

    def test_schema_driven_timeline_changes_real_geometry(self):
        legacy = render_layout(LayoutSpec("timeline", ["A", "B", "C", "D"]))
        pilot = render_layout(
            LayoutSpec(
                "timeline",
                ["A", "B", "C", "D"],
                density="breathing",
                variant="timeline/editorial",
                emphasis="single-focal",
                focal_index=1,
            )
        )
        self.assertNotEqual(legacy, pilot)
        self.assertIn('data-variant="timeline/editorial"', pilot)
        self.assertIn('data-focal="true"', pilot)
        legacy_rect = re.search(r'<rect x="[^"]+" y="[^"]+" width="([^"]+)" height="([^"]+)"', legacy)
        pilot_rect = re.search(r'<rect x="[^"]+" y="[^"]+" width="([^"]+)" height="([^"]+)"', pilot)
        self.assertNotEqual(legacy_rect.groups(), pilot_rect.groups())

    def test_matrix_comparison_alias_changes_proportion_and_focal_area(self):
        legacy = render_layout(LayoutSpec("matrix", ["A", "B", "C", "D"]))
        pilot = render_layout(
            LayoutSpec(
                "matrix",
                ["A", "B", "C", "D"],
                density="dense",
                variant="matrix/comparison",
                emphasis="single-focal",
                focal_index=1,
            )
        )
        self.assertNotEqual(legacy, pilot)
        self.assertIn('data-variant="matrix/comparison"', pilot)
        self.assertIn('data-focal="true"', pilot)
        self.assertIn('width="619.2"', pilot)

    def test_explicit_pilot_intent_rejects_unknown_values_and_over_budget_content(self):
        with self.assertRaisesRegex(ValueError, "layout-budget-items-exceeded"):
            render_layout(LayoutSpec("timeline", list("ABCDEFG"), density="dense"))
        with self.assertRaisesRegex(ValueError, "layout-budget-text-exceeded"):
            render_layout(LayoutSpec("matrix", ["x" * 81], density="balanced"))
        with self.assertRaisesRegex(ValueError, "invalid-layout-density"):
            render_layout(LayoutSpec("timeline", ["A"], density="anchor"))
        with self.assertRaisesRegex(ValueError, "invalid-layout-variant"):
            render_layout(LayoutSpec("matrix", ["A"], variant="timeline/editorial"))
        with self.assertRaisesRegex(ValueError, "invalid-layout-focal-target"):
            render_layout(LayoutSpec("timeline", ["A", "B"], emphasis="single-focal", focal_target="C"))

    def test_focal_target_selects_the_matching_visible_item(self):
        pilot = render_layout(
            LayoutSpec(
                "timeline",
                ["A", "B", "C"],
                emphasis="single-focal",
                focal_target="B",
            )
        )
        focal = re.search(r'<rect x="([^\"]+)" y="[^\"]+" width="([^\"]+)"[^>]+data-focal="true"', pilot)
        self.assertIsNotNone(focal)
        self.assertEqual(focal.groups(), ("607.4", "65.3"))

    def test_pyramid_outputs_office_safe_group_with_layout_marker(self):
        svg = render_layout(
            LayoutSpec("pyramid", ["基础层", "能力层", "战略层"], title="能力金字塔")
        )
        self.assertIn('data-layout="pyramid"', svg)
        self.assertGreaterEqual(svg.count("<polygon"), 3)
        self.assertIn("能力金字塔", svg)
        self.assertNotIn("<marker", svg)
        self.assertNotIn("rgba(", svg)

    def test_waterfall_outputs_steps_and_explicit_arrowheads(self):
        svg = render_layout(LayoutSpec("waterfall", ["输入", "处理", "交付"], title="瀑布递进"))
        self.assertIn('data-layout="waterfall"', svg)
        self.assertEqual(svg.count("class="), 0)
        self.assertGreaterEqual(svg.count("<rect"), 3)
        self.assertGreaterEqual(svg.count("<polygon"), 2)

    def test_funnel_outputs_narrowing_layers(self):
        svg = render_layout(LayoutSpec("funnel", ["触达", "激活", "转化", "复购"], title="转化漏斗"))
        self.assertIn('data-layout="funnel"', svg)
        self.assertGreaterEqual(svg.count("<polygon"), 4)
        self.assertIn("转化漏斗", svg)
        self.assertNotIn("<marker", svg)

    def test_flywheel_outputs_cycle_connectors(self):
        svg = render_layout(LayoutSpec("flywheel", ["获客", "激活", "交付", "裂变"], title="增长飞轮"))
        self.assertIn('data-layout="flywheel"', svg)
        self.assertGreaterEqual(svg.count("<line"), 4)
        self.assertGreaterEqual(svg.count("<polygon"), 4)
        self.assertGreaterEqual(svg.count("<rect"), 5)

    def test_swimlane_outputs_lane_headers_and_stage_grid(self):
        svg = render_layout(
            LayoutSpec("swimlane", ["业务发起", "平台受理", "研发实施"], title="跨角色协同")
        )
        self.assertIn('data-layout="swimlane"', svg)
        self.assertGreaterEqual(svg.count("<rect"), 6)
        self.assertGreaterEqual(svg.count("阶段"), 3)
        self.assertIn("业务发起", svg)

    def test_iceberg_outputs_surface_and_hidden_layers(self):
        svg = render_layout(
            LayoutSpec("iceberg", ["表层症状", "结构问题", "深层根因", "系统约束"], title="问题冰山")
        )
        self.assertIn('data-layout="iceberg"', svg)
        self.assertGreaterEqual(svg.count("<polygon"), 1)
        self.assertGreaterEqual(svg.count("<line"), 1)
        self.assertGreaterEqual(svg.count("<rect"), 4)
        self.assertIn("水面以上", svg)
        self.assertIn("水面以下", svg)
        self.assertIn("表层症状", svg)

    def test_all_supported_archetypes_render(self):
        for archetype in (
            "pyramid",
            "waterfall",
            "staircase",
            "layered_arch",
            "matrix",
            "timeline",
            "funnel",
            "flywheel",
            "swimlane",
            "iceberg",
        ):
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
