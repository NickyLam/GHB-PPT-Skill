import tempfile
import unittest
from pathlib import Path

from scripts.ppt_master.check_layout_diversity import (
    analyze_layout_sequence,
    extract_layout_markers,
    main,
)


class LayoutDiversityCheckerTest(unittest.TestCase):
    def test_extracts_data_layout_markers_from_svg(self):
        svg = '<svg><g id="content" data-layout="pyramid"></g></svg>'
        self.assertEqual(extract_layout_markers(svg), ["pyramid"])

    def test_flags_three_consecutive_same_layouts(self):
        issues = analyze_layout_sequence(["cards", "pyramid", "pyramid", "pyramid"])
        self.assertEqual(len(issues), 1)
        self.assertIn("content-appropriate", issues[0])
        self.assertIn("pyramid", issues[0])

    def test_flags_low_distinct_count_for_long_deck(self):
        issues = analyze_layout_sequence(
            ["cards", "cards", "pyramid", "pyramid", "matrix", "matrix", "cards", "pyramid"]
        )
        self.assertTrue(any("semantically justified" in issue for issue in issues))

    def test_accepts_varied_long_deck(self):
        issues = analyze_layout_sequence(
            ["cards", "pyramid", "waterfall", "matrix", "timeline", "staircase", "cards", "layered_arch"]
        )
        self.assertEqual(issues, [])

    def test_cli_reports_repetition_as_advice_without_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "svg_output").mkdir()
            for number in range(1, 9):
                (project / "svg_output" / f"{number:02d}_editorial.svg").write_text(
                    '<svg><g data-layout="editorial"><text>内容优先</text></g></svg>',
                    encoding="utf-8",
                )

            self.assertEqual(main([str(project)]), 0)

    def test_cli_still_fails_when_layout_metadata_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "svg_output").mkdir()
            (project / "svg_output" / "01_missing.svg").write_text(
                "<svg><g><text>缺少版式元数据</text></g></svg>",
                encoding="utf-8",
            )

            self.assertEqual(main([str(project)]), 1)


if __name__ == "__main__":
    unittest.main()
