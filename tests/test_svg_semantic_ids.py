from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.merge_template_master import NS
from scripts.ppt_master.svg_layouts import LayoutSpec, render_layout
from scripts.ppt_master.svg_to_pptx import convert_svg_to_slide_shapes


class SvgSemanticIdsTest(unittest.TestCase):
    def test_text_id_becomes_drawingml_shape_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / "slide.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
                '<text id="template-section-label" x="100" y="100" font-size="16">Part 2</text>'
                "</svg>",
                encoding="utf-8",
            )
            slide_xml, _, _, _ = convert_svg_to_slide_shapes(svg)
            slide = ET.fromstring(slide_xml)
            names = [node.get("name") for node in slide.findall(".//p:cNvPr", NS)]
            self.assertIn("template-section-label", names)

    def test_intent_renderer_typography_ids_survive_drawingml_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / "slide.svg"
            fragment = render_layout(
                LayoutSpec(
                    "timeline",
                    ["发现问题", "完成修复"],
                    title="执行路径",
                    density="balanced",
                    emphasis="distributed",
                )
            )
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
                f"{fragment}</svg>",
                encoding="utf-8",
            )

            slide_xml, _, _, _ = convert_svg_to_slide_shapes(svg)
            slide = ET.fromstring(slide_xml)
            names = [node.get("name") for node in slide.findall(".//p:cNvPr", NS)]

            self.assertIn("body-timeline-title", names)
            self.assertIn("body-timeline-item-1-line-1", names)
            self.assertIn("body-timeline-item-2-line-1", names)

    def test_declared_qa_box_width_is_the_minimum_drawingml_text_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / "slide.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
                '<text id="body-wide-label" data-qa-box="64 64 320 48" '
                'x="224" y="112" text-anchor="middle" font-size="32" '
                'font-weight="bold">SKILL.md</text>'
                "</svg>",
                encoding="utf-8",
            )

            slide_xml, _, _, _ = convert_svg_to_slide_shapes(svg)
            slide = ET.fromstring(slide_xml)
            shape = next(
                node
                for node in slide.findall(".//p:sp", NS)
                if node.find("./p:nvSpPr/p:cNvPr", NS).get("name") == "body-wide-label"
            )
            extent = shape.find("./p:spPr/a:xfrm/a:ext", NS)

            self.assertGreaterEqual(int(extent.get("cx")), 320 * 9525)

    def test_fixed_text_fit_disables_renderer_box_expansion_only_for_opted_in_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / "slide.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
                '<text id="fixed-label" data-text-fit="fixed" '
                'data-qa-box="64 64 240 48" x="64" y="104" '
                'font-size="32">WorkBuddy</text>'
                '<text id="auto-label" data-qa-box="64 144 240 48" '
                'x="64" y="184" font-size="32">Codex</text>'
                "</svg>",
                encoding="utf-8",
            )

            slide_xml, _, _, _ = convert_svg_to_slide_shapes(svg)
            slide = ET.fromstring(slide_xml)
            shapes = {
                node.find("./p:nvSpPr/p:cNvPr", NS).get("name"): node
                for node in slide.findall(".//p:sp", NS)
            }

            fixed_body = shapes["fixed-label"].find("./p:txBody/a:bodyPr", NS)
            auto_body = shapes["auto-label"].find("./p:txBody/a:bodyPr", NS)
            self.assertIsNotNone(fixed_body.find("./a:noAutofit", NS))
            self.assertIsNone(fixed_body.find("./a:spAutoFit", NS))
            self.assertIsNotNone(auto_body.find("./a:spAutoFit", NS))
            self.assertIsNone(auto_body.find("./a:noAutofit", NS))

    def test_fixed_text_fit_uses_the_declared_qa_box_as_the_drawingml_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / "slide.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
                '<text id="fixed-frame" data-text-fit="fixed" '
                'data-qa-box="80 140 240 48" x="80" y="180" '
                'font-size="32">WorkBuddy</text>'
                "</svg>",
                encoding="utf-8",
            )

            slide_xml, _, _, _ = convert_svg_to_slide_shapes(svg)
            slide = ET.fromstring(slide_xml)
            shape = next(
                node
                for node in slide.findall(".//p:sp", NS)
                if node.find("./p:nvSpPr/p:cNvPr", NS).get("name") == "fixed-frame"
            )
            offset = shape.find("./p:spPr/a:xfrm/a:off", NS)
            extent = shape.find("./p:spPr/a:xfrm/a:ext", NS)
            body = shape.find("./p:txBody/a:bodyPr", NS)

            self.assertEqual(int(offset.get("x")), 80 * 9525)
            self.assertEqual(int(offset.get("y")), 140 * 9525)
            self.assertEqual(int(extent.get("cx")), 240 * 9525)
            self.assertEqual(int(extent.get("cy")), 48 * 9525)
            self.assertEqual(body.get("anchor"), "ctr")


if __name__ == "__main__":
    unittest.main()
