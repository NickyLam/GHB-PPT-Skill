from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from scripts.ppt_master.svg_finalize.align_embed_images import (
    align_and_embed_images_in_svg,
)
from scripts.ppt_master.svg_finalize.svg_rect_to_path import process_svg


class SvgFinalizeMetadataTest(unittest.TestCase):
    def test_meet_alignment_updates_image_qa_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (200, 100), "white").save(root / "source.png")
            svg_path = root / "slide.svg"
            svg_path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                '<image id="hero" data-qa-role="image" data-qa-box="0 0 100 100" '
                'href="source.png" x="0" y="0" width="100" height="100" '
                'preserveAspectRatio="xMidYMid meet"/></svg>',
                encoding="utf-8",
            )

            processed, errors = align_and_embed_images_in_svg(svg_path)

            self.assertEqual((processed, errors), (1, 0))
            image = next(
                elem
                for elem in ET.parse(svg_path).getroot().iter()
                if elem.tag.rsplit("}", 1)[-1] == "image"
            )
            self.assertEqual(
                (image.get("x"), image.get("y"), image.get("width"), image.get("height")),
                ("0", "25", "100", "50"),
            )
            self.assertEqual(image.get("data-qa-box"), "0 25 100 50")

    def test_rounded_rect_conversion_adds_measurable_qa_box(self):
        processed, count = process_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
            '<rect id="card" x="10" y="20" width="100" height="50" rx="8"/>'
            '</svg>'
        )

        self.assertEqual(count, 1)
        path = next(
            elem
            for elem in ET.fromstring(processed).iter()
            if elem.tag.rsplit("}", 1)[-1] == "path"
        )
        self.assertEqual(path.get("data-qa-box"), "10 20 100 50")


if __name__ == "__main__":
    unittest.main()
