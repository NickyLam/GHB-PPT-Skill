from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.ghb_svg_quality import check_project, main


SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
<g id="bg"><rect width="1280" height="720" fill="#FFFFFF"/></g>
<g id="bg-surface"><rect x="56" y="96" width="1168" height="608" fill="#FFFFFF"/></g>
<g id="content" data-layout="timeline"><text x="100" y="160" font-size="30" font-family="Microsoft YaHei, Arial, sans-serif">稳定交付需要验证闭环</text></g>
</svg>'''


class GhbSvgQualityTest(unittest.TestCase):
    def make_project(self, directory: Path, *, broken: bool = False) -> Path:
        (directory / "svg_output").mkdir()
        (directory / "svg_final").mkdir()
        content = SVG.replace("稳定交付需要验证闭环", "bad �") if broken else SVG
        (directory / "svg_output" / "01_timeline.svg").write_text(content, encoding="utf-8")
        finalized = content.replace('<g id="bg"><rect width="1280" height="720" fill="#FFFFFF"/></g>\n', "")
        (directory / "svg_final" / "01_timeline.svg").write_text(finalized, encoding="utf-8")
        (directory / "layout_plan.json").write_text(
            json.dumps([{"slide": 1, "layout_archetype": "timeline", "density": "anchor"}]),
            encoding="utf-8",
        )
        return directory

    def test_combines_svg_visual_layout_and_plan_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(Path(tmp))
            payload = check_project(project, stage="authored")
            self.assertTrue(payload["passed"], payload)
            self.assertEqual(payload["layouts"], ["timeline"])
            self.assertEqual(payload["error_count"], 0)

    def test_ghb_surface_coordinate_drift_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(Path(tmp))
            path = project / "svg_output" / "01_timeline.svg"
            path.write_text(path.read_text(encoding="utf-8").replace('y="96"', 'y="56"'), encoding="utf-8")
            payload = check_project(project, stage="authored")
            self.assertFalse(payload["passed"])
            self.assertTrue(
                any("x=56 y=96" in message for message in payload["files"][0]["visual_errors"])
            )

    def test_broken_text_fails_and_cli_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(Path(tmp), broken=True)
            output = project / "report.json"
            self.assertEqual(main([str(project), "--stage", "finalized", "--output", str(output)]), 1)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["passed"])
            self.assertGreater(payload["error_count"], 0)


if __name__ == "__main__":
    unittest.main()
