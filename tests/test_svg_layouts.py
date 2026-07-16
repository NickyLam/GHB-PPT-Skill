import unittest
import re
import hashlib
import math
from xml.etree import ElementTree as ET

from scripts.ppt_master.svg_layouts import LAYOUT_CONTRACTS, LayoutSpec, render_layout


class SvgLayoutsTest(unittest.TestCase):
    archetypes = (
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
    )

    @staticmethod
    def _geometry(svg):
        return re.findall(
            r"<(?:rect|polygon|line|text)\b[^>]*(?:x=|points=|x1=)[^>]*>", svg
        )

    def test_legacy_timeline_and_matrix_geometry_is_unchanged_without_intent(self):
        timeline = render_layout(LayoutSpec("timeline", ["A", "B", "C", "D"]))
        matrix = render_layout(LayoutSpec("matrix", ["A", "B", "C", "D"]))
        self.assertIn('x1="120" y1="420.0" x2="1160"', timeline)
        self.assertIn('x="98.0" y="398.0" width="44" height="44"', timeline)
        self.assertIn('x="120.0" y="220.0" width="520.0" height="200.0"', matrix)

    def test_all_legacy_calls_remain_byte_stable_without_visual_intent(self):
        expected = {
            "pyramid": "7886c3380e967a11f1e30044c6bd515d0425a029602368ce101f180c71a00079",
            "waterfall": "e81b05a7143bc91b78b45bb7ec280171616e369e3c9fb34a7cbd790ecc07ec17",
            "staircase": "54a7f625715159227433d6690728836fe35060ad0cf60d772a552a3167f26ea0",
            "layered_arch": "bd41f87b5dc61cb9c6869307bf39aeed73c2ce13bc023736347d84b19db53507",
            "matrix": "00c84f97634d555be46d48c179ab91110c263f37b2e7a7038de62711903b0efb",
            "timeline": "86ae416f8bb5463239f2185d76ebc6802695a0e99d2e4fb873eca4eb3b8e70a6",
            "funnel": "305c4123e24c3846cf4d41b63374f9158a0214324e21029c36dc30f5de0bc332",
            "flywheel": "d2099e596b4fb8573ed04959dac02f5bd64e130aac6d1763aa0b31030a997ff5",
            "swimlane": "3883beb12df97b7f768e26af20c0ad196fe473b39527667a2d26915cbe570827",
            "iceberg": "cdbe0f7aece8064892bcf7e7076d6dd2c18280ba3dd7920f3f68f2bca8086162",
        }
        for archetype, digest in expected.items():
            with self.subTest(archetype=archetype):
                svg = render_layout(LayoutSpec(archetype, ["A", "B", "C"], title=archetype))
                self.assertEqual(hashlib.sha256(svg.encode()).hexdigest(), digest)

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

    def test_matrix_comparison_keeps_equal_cards_with_visible_gaps(self):
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
        cards = [
            tuple(float(value) for value in match)
            for match in re.findall(
                r'<rect x="([^"]+)" y="([^"]+)" width="([^"]+)" height="([^"]+)"',
                pilot,
            )
        ]
        self.assertEqual(len(cards), 4)
        self.assertEqual({(width, height) for _, _, width, height in cards}, {(516.0, 196.0)})
        self.assertEqual(cards[1][0] - (cards[0][0] + cards[0][2]), 8.0)
        self.assertEqual(cards[2][1] - (cards[0][1] + cards[0][3]), 8.0)
        self.assertIn('font-size="21"', pilot)

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

    def test_all_archetypes_consume_density_and_single_focal_intent(self):
        for archetype in self.archetypes:
            contract = LAYOUT_CONTRACTS[archetype]
            items = [f"Item {index}" for index in range(contract.min_items)]
            if len(items) < 2:
                items.append("Item 1")
            with self.subTest(archetype=archetype):
                breathing = render_layout(
                    LayoutSpec(
                        archetype,
                        items,
                        density="breathing",
                        emphasis="single-focal",
                        focal_index=1,
                    )
                )
                dense = render_layout(
                    LayoutSpec(
                        archetype,
                        items,
                        density="dense",
                        emphasis="single-focal",
                        focal_index=1,
                    )
                )
                self.assertIn('data-density="breathing"', breathing)
                self.assertIn('data-focal="true"', breathing)
                self.assertNotEqual(self._geometry(breathing), self._geometry(dense))

    def test_all_archetypes_enforce_declared_min_max_and_text_budgets(self):
        for archetype in self.archetypes:
            contract = LAYOUT_CONTRACTS[archetype]
            minimum = [f"M{index}" for index in range(contract.min_items)]
            maximum = [f"X{index}" for index in range(contract.max_items)]
            with self.subTest(archetype=archetype, boundary="minimum"):
                self.assertIn(
                    f'data-layout="{archetype}"',
                    render_layout(LayoutSpec(archetype, minimum, density="balanced")),
                )
            with self.subTest(archetype=archetype, boundary="maximum"):
                rendered = render_layout(LayoutSpec(archetype, maximum, density="balanced"))
                for item in maximum:
                    self.assertIn(item, rendered)
            with self.subTest(archetype=archetype, boundary="below-minimum"):
                with self.assertRaisesRegex(ValueError, "layout-budget-items-below-minimum"):
                    render_layout(
                        LayoutSpec(
                            archetype,
                            minimum[:-1],
                            density="balanced",
                        )
                    )
            with self.subTest(archetype=archetype, boundary="above-maximum"):
                with self.assertRaisesRegex(ValueError, "layout-budget-items-exceeded"):
                    render_layout(
                        LayoutSpec(
                            archetype,
                            maximum + ["overflow"],
                            density="balanced",
                        )
                    )
            with self.subTest(archetype=archetype, boundary="declared-node-budget"):
                with self.assertRaisesRegex(ValueError, "layout-budget-items-exceeded"):
                    render_layout(
                        LayoutSpec(
                            archetype,
                            minimum,
                            density="balanced",
                            max_items=len(minimum) - 1,
                        )
                    )
            with self.subTest(archetype=archetype, boundary="declared-text-budget"):
                with self.assertRaisesRegex(ValueError, "layout-budget-text-exceeded"):
                    render_layout(
                        LayoutSpec(
                            archetype,
                            minimum,
                            density="balanced",
                            max_text_chars=sum(map(len, minimum)) - 1,
                        )
                    )

    def test_catalogued_variants_change_geometry_and_aliases_do_not_add_archetypes(self):
        pyramid_default = render_layout(
            LayoutSpec("pyramid", ["A", "B", "C"], density="balanced", variant="pyramid/default")
        )
        pyramid_foundation = render_layout(
            LayoutSpec("pyramid", ["A", "B", "C"], density="balanced", variant="pyramid/foundation")
        )
        timeline_editorial = render_layout(
            LayoutSpec("timeline", ["A", "B", "C"], density="balanced", variant="timeline/editorial")
        )
        timeline_phased = render_layout(
            LayoutSpec("timeline", ["A", "B", "C"], density="balanced", variant="timeline/phased")
        )
        self.assertNotEqual(self._geometry(pyramid_default), self._geometry(pyramid_foundation))
        self.assertNotEqual(self._geometry(timeline_editorial), self._geometry(timeline_phased))

        comparison = render_layout(
            LayoutSpec("comparison", ["A", "B", "C", "D"], density="balanced")
        )
        metric = render_layout(
            LayoutSpec(
                "matrix",
                ["41%", "62%", "78%", "95%"],
                density="balanced",
                variant="matrix/metric-callout",
                emphasis="single-focal",
                focal_index=3,
            )
        )
        self.assertIn('data-layout="matrix"', comparison)
        self.assertIn('data-variant="matrix/comparison"', comparison)
        self.assertNotIn('data-layout="comparison"', comparison)
        self.assertIn('data-variant="matrix/metric-callout"', metric)
        self.assertIn('font-size="26"', metric)

    def test_matrix_renders_only_visible_items_as_equal_cards_with_fixed_gaps(self):
        for count in (2, 3, 4):
            items = [f"Option {index}" for index in range(count)]
            svg = render_layout(
                LayoutSpec(
                    "matrix",
                    items,
                    density="balanced",
                    variant="matrix/comparison",
                    emphasis="distributed",
                )
            )
            root = ET.fromstring(f"<svg>{svg}</svg>")
            cards = [node for node in root.iter() if node.tag == "rect"]
            with self.subTest(count=count):
                self.assertEqual(len(cards), count)
                self.assertEqual(len({node.get("width") for node in cards}), 1)
                self.assertEqual(len({node.get("height") for node in cards}), 1)
                boxes = sorted(
                    (
                        float(node.get("x")),
                        float(node.get("y")),
                        float(node.get("width")),
                        float(node.get("height")),
                    )
                    for node in cards
                )
                for left_index, left in enumerate(boxes):
                    for right in boxes[left_index + 1 :]:
                        separated = (
                            left[0] + left[2] < right[0]
                            or right[0] + right[2] < left[0]
                            or left[1] + left[3] < right[1]
                            or right[1] + right[3] < left[1]
                        )
                        self.assertTrue(separated)

    def test_comparison_cards_separate_option_heading_from_explanation(self):
        svg = render_layout(
            LayoutSpec(
                "matrix",
                ["拥挤：信息完整但难扫描", "均衡：层级稳定且可编辑"],
                density="balanced",
                variant="matrix/comparison",
                emphasis="distributed",
            )
        )

        self.assertRegex(svg, r'font-size="20" font-weight="bold"[^>]*>拥挤</text>')
        self.assertRegex(svg, r'font-size="20" font-weight="bold"[^>]*>均衡</text>')
        self.assertIn(">信息完整但难扫描</text>", svg)
        self.assertIn(">层级稳定且可编辑</text>", svg)

    def test_intent_rejects_text_that_fits_character_budget_but_not_card_height(self):
        with self.assertRaisesRegex(ValueError, "layout-budget-text-exceeded"):
            render_layout(
                LayoutSpec(
                    "flywheel",
                    ["甲" * 40] * 6,
                    density="breathing",
                    emphasis="distributed",
                )
            )

    def test_schema_driven_output_uses_only_office_safe_elements(self):
        forbidden = ("<filter", "<mask", "<foreignObject", "<style", "<marker", "class=")
        for archetype in self.archetypes:
            contract = LAYOUT_CONTRACTS[archetype]
            items = [f"I{index}" for index in range(contract.min_items)]
            svg = render_layout(LayoutSpec(archetype, items, density="dense"))
            with self.subTest(archetype=archetype):
                self.assertFalse(any(token in svg for token in forbidden))
                tags = set(re.findall(r"<([A-Za-z][\w-]*)", svg))
                self.assertLessEqual(tags, {"g", "rect", "polygon", "line", "text"})

    def test_maximum_item_geometry_stays_inside_declared_bounds(self):
        for archetype in self.archetypes:
            contract = LAYOUT_CONTRACTS[archetype]
            items = [f"I{index}" for index in range(contract.max_items)]
            for density in ("breathing", "balanced", "dense"):
                spec = LayoutSpec(archetype, items, density=density)
                root = ET.fromstring(f"<svg>{render_layout(spec)}</svg>")
                points = []
                for node in root.iter():
                    if node.tag == "rect":
                        x, y = float(node.get("x")), float(node.get("y"))
                        points.extend(((x, y), (x + float(node.get("width")), y + float(node.get("height")))))
                    elif node.tag == "line":
                        points.extend(((float(node.get("x1")), float(node.get("y1"))), (float(node.get("x2")), float(node.get("y2")))))
                    elif node.tag == "polygon":
                        points.extend(tuple(map(float, pair.split(","))) for pair in node.get("points").split())
                with self.subTest(archetype=archetype, density=density):
                    self.assertTrue(points)
                    self.assertTrue(all(spec.x <= x <= spec.x + spec.width for x, _ in points))
                    self.assertTrue(all(spec.y <= y <= spec.y + spec.height for _, y in points))

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

    def test_waterfall_arrowheads_are_aligned_and_symmetric(self):
        svg = render_layout(
            LayoutSpec(
                "waterfall",
                ["需求澄清", "架构评审", "集成验证", "发布检查"],
                density="balanced",
                emphasis="distributed",
            )
        )
        connector = re.search(
            r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"[^>]*/>\s*'
            r'<polygon points="([^"]+)"',
            svg,
        )
        self.assertIsNotNone(connector)
        _, _, x2, y2, raw_points = connector.groups()
        points = [tuple(map(float, pair.split(","))) for pair in raw_points.split()]
        self.assertEqual(points[0], (float(x2), float(y2)))
        left_leg = math.dist(points[0], points[1])
        right_leg = math.dist(points[0], points[2])
        self.assertAlmostEqual(left_leg, right_leg, delta=0.1)

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
        for archetype in self.archetypes:
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
