from __future__ import annotations

import unittest

from scripts.ppt_master.svg_finalize.embed_icons import parse_use_element


class ParseUseElementTest(unittest.TestCase):
    def test_data_qa_box_does_not_shadow_x_attribute(self):
        attrs = parse_use_element(
            '<use data-qa-box="808 268 48 48" x="808" y="268" '
            'width="48" height="48" data-icon="tabler-outline/users"/>'
        )
        self.assertEqual(attrs["x"], 808.0)
        self.assertEqual(attrs["y"], 268.0)
        self.assertEqual(attrs["width"], 48.0)
        self.assertEqual(attrs["height"], 48.0)


if __name__ == "__main__":
    unittest.main()
