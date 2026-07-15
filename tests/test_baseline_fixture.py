from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET


MODULE_PATH = Path(__file__).parent / "fixtures" / "build_baseline.py"
SPEC = importlib.util.spec_from_file_location("ghb_build_baseline_fixture", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BaselineFixtureTest(unittest.TestCase):
    def test_fixture_writer_remains_byte_deterministic_without_visual_intent(self):
        slide = {
            "key_message": "Legacy fixture geometry must stay stable",
            "layout_type": "timeline",
            "items": ["输入", "处理", "验证", "交付"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.svg"
            second = Path(tmp) / "second.svg"
            MODULE.write_svg(first, 1, 1, slide)
            MODULE.write_svg(second, 1, 1, slide)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_schema_driven_fixture_fragment_is_deterministic_and_keeps_font_floor(self):
        spec = MODULE.LayoutSpec(
            "pyramid",
            ["基础", "能力", "结果"],
            density="breathing",
            variant="pyramid/foundation",
            emphasis="single-focal",
            focal_index=0,
            max_items=3,
            max_text_chars=20,
        )
        first = MODULE.render_layout(spec)
        second = MODULE.render_layout(spec)
        self.assertEqual(first, second)
        self.assertIn('data-focal="true"', first)
        font_sizes = [int(value) for value in re.findall(r'font-size="(\d+)"', first)]
        self.assertTrue(font_sizes)
        self.assertGreaterEqual(min(font_sizes), 13)

    def test_each_item_is_written_as_visible_svg_text(self):
        slide = {
            "key_message": "每个结构块都必须携带可见内容",
            "layout_type": "matrix",
            "items": [
                "短标签",
                "高价值 / 高复杂度：Strategic Bet",
                "自动化构建与集成验证",
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "fixture.svg"
            MODULE.write_svg(output, 1, 1, slide)
            root = ET.parse(output).getroot()
            content = next(node for node in root if node.get("data-layout") == "matrix")
            visible_text = " ".join("".join(node.itertext()) for node in content if node.tag.endswith("text"))
            normalized = visible_text.replace(" ", "")
            for item in slide["items"]:
                self.assertIn(item.replace(" ", ""), normalized)
            self.assertEqual(sum(1 for node in content if node.tag.endswith("rect")), 4)

    def test_different_archetypes_produce_different_geometry(self):
        items = ["输入", "处理", "验证", "交付"]
        timeline = MODULE.render_layout(MODULE.LayoutSpec("timeline", items))
        matrix = MODULE.render_layout(MODULE.LayoutSpec("matrix", items))
        self.assertIn("<line", timeline)
        self.assertEqual(timeline.count("<rect"), 4)
        self.assertEqual(matrix.count("<rect"), 4)
        self.assertNotEqual(timeline, matrix)


if __name__ == "__main__":
    unittest.main()
