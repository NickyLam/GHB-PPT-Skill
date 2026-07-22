from __future__ import annotations

import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ppt_master"))

from template_fill_pptx.checker import _fit_status  # noqa: E402


class TemplateFillCheckerTest(unittest.TestCase):
    def test_short_placeholder_can_use_reliable_geometry_capacity(self):
        status, message = _fit_status(
            role="label_candidate",
            old_width=3,
            new_width=21.5,
            old_paragraphs=1,
            new_paragraphs=1,
            geometry={"width": 915, "height": 61},
            text_metrics={"font_size_px": 42.67},
        )

        self.assertEqual(status, "OK")
        self.assertIn("capacity", message)

    def test_short_placeholder_still_warns_when_geometry_is_too_small(self):
        status, _message = _fit_status(
            role="label_candidate",
            old_width=3,
            new_width=21.5,
            old_paragraphs=1,
            new_paragraphs=1,
            geometry={"width": 80, "height": 20},
            text_metrics={"font_size_px": 16},
        )

        self.assertEqual(status, "WARN")

    def test_short_placeholder_does_not_trust_fallback_font_size(self):
        status, _message = _fit_status(
            role="label_candidate",
            old_width=3,
            new_width=21.5,
            old_paragraphs=1,
            new_paragraphs=1,
            geometry={"width": 915, "height": 61},
            text_metrics={},
        )

        self.assertEqual(status, "WARN")


if __name__ == "__main__":
    unittest.main()
