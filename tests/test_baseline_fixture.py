from __future__ import annotations

import importlib.util
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
