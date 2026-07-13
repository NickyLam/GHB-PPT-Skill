import unittest

from scripts.ppt_master.svg_layouts import LayoutSpec, render_layout


class SvgLayoutsTest(unittest.TestCase):
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
