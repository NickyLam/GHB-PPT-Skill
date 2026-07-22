import unittest
import re
import hashlib
import math
from xml.etree import ElementTree as ET

from scripts.ppt_master.svg_layouts import (
    FONT,
    LAYOUT_CONTRACTS,
    LayoutSpec,
    render_layout,
    render_layout_schema,
    validate_layout_schema,
)
from scripts.ghb_svg_quality import typography_contract_errors
from scripts.validate_project_contract import default_visual_profile
from scripts.ppt_master.svg_to_pptx.drawingml_elements import _build_run_xml
from scripts.ppt_master.svg_to_pptx.drawingml_utils import parse_font_family


class SvgLayoutsTest(unittest.TestCase):
    def test_constrained_json_schema_validates_before_rendering(self):
        payload = {
            "schema": "ghb.layout-schema.v1",
            "archetype": "comparison",
            "title": {"text": "方案比较", "max_chars": 24},
            "nodes": [
                {"id": "a", "heading": "方案A", "body": "稳健", "max_body_chars": 20},
                {"id": "b", "heading": "方案B", "body": "敏捷", "max_body_chars": 20},
            ],
            "density": "balanced",
            "emphasis": {"mode": "distributed"},
            "source": "sources/source.md#comparison",
        }
        self.assertEqual(validate_layout_schema(payload), [])
        svg = render_layout_schema(payload)
        self.assertIn('data-layout="matrix"', svg)
        self.assertIn("方案A", svg)

    def test_constrained_json_schema_returns_actionable_copy_and_split_advice(self):
        payload = {
            "schema": "ghb.layout-schema.v1",
            "archetype": "timeline",
            "title": {"text": "这是一个明显超过标题字符预算的结论式长标题", "max_chars": 8},
            "nodes": [
                {
                    "id": f"n{i}",
                    "heading": f"阶段{i}",
                    "body": "过长说明" * 30,
                    "max_body_chars": 20,
                }
                for i in range(7)
            ],
        }
        issues = validate_layout_schema(payload)
        codes = {item["code"] for item in issues}
        self.assertIn("layout-schema-title-too-long", codes)
        self.assertIn("layout-budget-items-exceeded", codes)
        self.assertIn("layout-schema-node-body-too-long", codes)
        self.assertTrue(all(item["suggestion"] for item in issues))
        with self.assertRaisesRegex(ValueError, "suggestion"):
            render_layout_schema(payload)

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

    def test_source_han_sans_sc_is_primary_and_survives_drawingml_conversion(self):
        self.assertTrue(FONT.startswith("'Source Han Sans SC'"))
        rendered = render_layout(LayoutSpec("timeline", ["阶段一", "阶段二"]))
        self.assertIn("Source Han Sans SC", rendered)
        fonts = parse_font_family("'Source Han Sans SC', 'Microsoft YaHei', Arial, sans-serif")
        self.assertEqual(fonts["ea"], "Source Han Sans SC")
        run_xml = _build_run_xml(
            {
                "text": "中文与 English",
                "font_family": "'Source Han Sans SC', 'Microsoft YaHei', Arial, sans-serif",
            },
            fonts,
        )
        self.assertIn('<a:latin typeface="Source Han Sans SC"/>', run_xml)
        self.assertIn('<a:ea typeface="Source Han Sans SC"/>', run_xml)

    def test_all_legacy_calls_remain_byte_stable_without_visual_intent(self):
        expected = {
            "pyramid": "656d76c5d109d545ea7403662ef68a3fb08be8578c5b0ae6b5f489de115ebd4d",
            "waterfall": "0568b334eb894c885debac6b92078044c4dd45ca2291cb425b6e3d647b7aac77",
            "staircase": "3ecfcd2ab65e8dabeab9e6e75b09c43a93f19b3a4993391e684dff7fd8a74645",
            "layered_arch": "2f24e3587bf1c16f2ce0732eef63abdca951fa8ca9023aac5216628d15f43444",
            "matrix": "5d70a807cb1d05c691fbe0d6e3ab8a7aab663a86412a2557fd0fa5279c0cb410",
            "timeline": "5d2a27e1751f6747859ddb5bf7a120e96e2ce13411eab95963e9928e307f010e",
            "funnel": "3824b0b9c5a6186878c31e6ba3141a4b4277690bf2d26b0baa1f9744ef34a1b8",
            "flywheel": "d3a29f6bea660aa9ef31aaad30b7f85e252778e38b9ad1a03b3469721d047b31",
            "swimlane": "27b9712977c2f7ed81bca7b0aa61b9cc8ef95e75f9ff4628ac65794d2e40c2a9",
            "iceberg": "057a871727ba73b4a40561c6abf2b4c106136350dcd7529a39874311ac8f51ea",
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
        self.assertIn('font-size="24"', pilot)

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

        self.assertRegex(svg, r'font-size="24" font-weight="bold"[^>]*>拥挤</text>')
        self.assertRegex(svg, r'font-size="24" font-weight="bold"[^>]*>均衡</text>')
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

    def test_all_intent_aware_layouts_satisfy_default_strict_typography(self):
        profile = default_visual_profile()
        for archetype, contract in LAYOUT_CONTRACTS.items():
            items = [f"项目{index + 1}" for index in range(contract.min_items)]
            fragment = render_layout(
                LayoutSpec(archetype, items, density="balanced", emphasis="distributed")
            )
            errors = typography_contract_errors(
                f'<svg viewBox="0 0 1280 720">{fragment}</svg>',
                profile,
            )
            with self.subTest(archetype=archetype):
                self.assertEqual(errors, [])

    def test_all_intent_aware_text_nodes_have_stable_typography_role_ids(self):
        for archetype, contract in LAYOUT_CONTRACTS.items():
            items = [f"项目{index + 1}" for index in range(contract.min_items)]
            fragment = render_layout(
                LayoutSpec(
                    archetype,
                    items,
                    title=f"{archetype} 结构",
                    density="balanced",
                    emphasis="distributed",
                )
            )
            root = ET.fromstring(f"<svg>{fragment}</svg>")
            text_ids = [node.get("id") for node in root.iter() if node.tag == "text"]
            with self.subTest(archetype=archetype):
                self.assertTrue(text_ids)
                self.assertTrue(all(text_ids))
                self.assertTrue(
                    all(
                        text_id.startswith(("body-", "caption-", "source-", "footer-"))
                        for text_id in text_ids
                    )
                )

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
        svg = render_layout(LayoutSpec(
            "waterfall", ["输入", "处理", "交付"], title="瀑布递进",
            density="balanced", emphasis="distributed",
        ))
        self.assertIn('data-layout="waterfall"', svg)
        self.assertEqual(svg.count("class="), 0)
        self.assertGreaterEqual(svg.count("<rect"), 3)
        self.assertGreaterEqual(svg.count("<polygon"), 2)
        self.assertIn('data-flow-node="waterfall-step-1"', svg)
        self.assertIn('data-flow-from="waterfall-step-1"', svg)

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
            r'<line[^>]* x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"[^>]*/>\s*'
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

    def test_dense_waterfall_keeps_compact_nodes_and_visible_forward_connectors(self):
        svg = render_layout(
            LayoutSpec(
                "waterfall",
                ["可回收设计", "复飞验证", "发射频次提升", "单位成本下降", "产能扩张"],
                x=120,
                y=268,
                width=820,
                height=322,
                density="dense",
                emphasis="ranked",
            )
        )
        root = ET.fromstring(f"<svg>{svg}</svg>")
        boxes = [node for node in root.iter() if node.tag == "rect"]
        connectors = [node for node in root.iter() if node.tag == "line"]

        self.assertEqual(len(boxes), 5)
        self.assertEqual(len(connectors), 4)
        self.assertLessEqual(max(float(box.get("height")) for box in boxes), 90.0)
        for left, right, connector in zip(boxes, boxes[1:], connectors):
            gap = float(right.get("x")) - (
                float(left.get("x")) + float(left.get("width"))
            )
            self.assertGreaterEqual(gap, 30.0)
            x1 = float(connector.get("x1"))
            x2 = float(connector.get("x2"))
            self.assertGreater(x2, x1)
            self.assertGreaterEqual(math.dist(
                (x1, float(connector.get("y1"))),
                (x2, float(connector.get("y2"))),
            ), 24.0)

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

    def test_flywheel_connectors_stop_outside_rounded_nodes(self):
        svg = render_layout(
            LayoutSpec(
                "flywheel",
                ["卫星部署", "网络覆盖", "用户订阅", "现金回流", "再投资扩网"],
                x=120,
                y=268,
                width=820,
                height=322,
                density="dense",
                emphasis="distributed",
            )
        )
        root = ET.fromstring(f"<svg>{svg}</svg>")
        boxes = [node for node in root.iter() if node.tag == "rect"][1:]
        connectors = [node for node in root.iter() if node.tag == "line"]
        self.assertEqual(len(boxes), len(connectors))
        self.assertTrue(all(node.get("data-flow-node") for node in boxes))
        self.assertTrue(all(node.get("data-flow-from") for node in connectors))

        def inside(box, point, margin=0.0):
            x = float(box.get("x")) + margin
            y = float(box.get("y")) + margin
            width = float(box.get("width")) - margin * 2
            height = float(box.get("height")) - margin * 2
            return x <= point[0] <= x + width and y <= point[1] <= y + height

        for index, connector in enumerate(connectors):
            start = (float(connector.get("x1")), float(connector.get("y1")))
            end = (float(connector.get("x2")), float(connector.get("y2")))
            self.assertFalse(inside(boxes[index], start))
            self.assertFalse(inside(boxes[(index + 1) % len(boxes)], end))

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
