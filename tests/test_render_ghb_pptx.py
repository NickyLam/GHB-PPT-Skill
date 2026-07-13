from __future__ import annotations

import tempfile
import unittest
import shutil
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from scripts.render_ghb_pptx import RenderError, make_contact_sheet, render_pptx


class RenderGhbPptxTest(unittest.TestCase):
    def test_contact_sheet_preserves_all_pages_and_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            pages = []
            for index, color in enumerate(("red", "green", "blue", "white"), 1):
                path = directory / f"page-{index}.png"
                Image.new("RGB", (640, 360), color).save(path)
                pages.append(path)
            output = make_contact_sheet(pages, directory / "contact.png", columns=3, thumb_width=320)
            self.assertTrue(output.is_file())
            with Image.open(output) as image:
                self.assertGreater(image.width, 3 * 320)
                self.assertGreater(image.height, 2 * 180)

    def test_contact_sheet_rejects_empty_page_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RenderError, "without page images"):
                make_contact_sheet([], Path(tmp) / "contact.png")

    @unittest.skipUnless(shutil.which("soffice") and shutil.which("pdftoppm"), "render tools unavailable")
    def test_soffice_integration_writes_pdf_png_contact_sheet_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            pptx = directory / "one-slide.pptx"
            presentation = Presentation()
            slide = presentation.slides.add_slide(presentation.slide_layouts[6])
            slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = "Render smoke test"
            presentation.save(pptx)
            report = render_pptx(pptx, directory / "render", dpi=96)
            self.assertTrue(report.passed, report.errors)
            self.assertEqual(report.page_count, 1)
            self.assertTrue(Path(report.pdf).is_file())
            self.assertTrue(Path(report.pages[0]).is_file())
            self.assertTrue(Path(report.contact_sheet).is_file())
            self.assertTrue((directory / "render" / "render-report.json").is_file())


if __name__ == "__main__":
    unittest.main()
