from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.merge_template_master import NS
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


if __name__ == "__main__":
    unittest.main()
