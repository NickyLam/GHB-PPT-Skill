from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.check_render_baseline import compare_render, measure_render


class RenderBaselineTest(unittest.TestCase):
    def test_measures_and_compares_tolerant_pixel_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slide.png"
            image = Image.new("RGB", (20, 10), "white")
            for x in range(5):
                for y in range(10):
                    image.putpixel((x, y), (0xAB, 0x1F, 0x29))
            image.save(path)
            metrics = measure_render(path)
        self.assertEqual(metrics["width"], 20)
        self.assertEqual(metrics["brand_red_ratio"], 0.25)
        baseline = {
            "width": 20,
            "height": 10,
            "ranges": {
                "brand_red_ratio": {"min": 0.24, "max": 0.26},
                "non_background_ratio": {"min": 0.24, "max": 0.26},
            },
        }
        self.assertEqual(compare_render(metrics, baseline), [])

    def test_reports_out_of_range_metric(self):
        errors = compare_render(
            {"width": 20, "height": 10, "brand_red_ratio": 0.1},
            {
                "width": 20,
                "height": 10,
                "ranges": {"brand_red_ratio": {"min": 0.2, "max": 0.3}},
            },
        )
        self.assertTrue(any("brand_red_ratio" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
