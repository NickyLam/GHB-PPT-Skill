import unittest

from scripts.ppt_master.check_layout_diversity import (
    analyze_layout_sequence,
    extract_layout_markers,
)


class LayoutDiversityCheckerTest(unittest.TestCase):
    def test_extracts_data_layout_markers_from_svg(self):
        svg = '<svg><g id="content" data-layout="pyramid"></g></svg>'
        self.assertEqual(extract_layout_markers(svg), ["pyramid"])

    def test_flags_three_consecutive_same_layouts(self):
        issues = analyze_layout_sequence(["cards", "pyramid", "pyramid", "pyramid"])
        self.assertEqual(len(issues), 1)
        self.assertIn("three consecutive slides", issues[0])
        self.assertIn("pyramid", issues[0])

    def test_flags_low_distinct_count_for_long_deck(self):
        issues = analyze_layout_sequence(
            ["cards", "cards", "pyramid", "pyramid", "matrix", "matrix", "cards", "pyramid"]
        )
        self.assertTrue(any("at least 4 distinct" in issue for issue in issues))

    def test_accepts_varied_long_deck(self):
        issues = analyze_layout_sequence(
            ["cards", "pyramid", "waterfall", "matrix", "timeline", "staircase", "cards", "layered_arch"]
        )
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
