import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.ppt_master.visual_asset_checker import check_svg, main


ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "templates" / "icons"


def png_data_uri(width=200, height=100):
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


class VisualAssetCheckerTest(unittest.TestCase):
    def write_svg(self, directory: Path, body: str, name="01_test.svg") -> Path:
        path = directory / name
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">{body}</svg>',
            encoding="utf-8",
        )
        return path

    def test_rejects_mojibake_stretched_icon_and_missing_aspect_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_svg(
                Path(tmp),
                '<g data-layout="timeline">'
                '<text x="20" y="40">bad \ufffd text</text>'
                '<use data-icon="tabler-outline/home" x="20" y="80" width="48" height="36"/>'
                f'<image x="100" y="100" width="200" height="100" href="{png_data_uri()}"/>'
                '</g>',
            )
            result = check_svg(path, stage="authored", icons_dir=ICONS)
            self.assertFalse(result.passed)
            joined = "\n".join(result.errors)
            self.assertIn("mojibake", joined)
            self.assertIn("must be square", joined)
            self.assertIn("preserveAspectRatio", joined)

    def test_rejects_declared_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_svg(
                Path(tmp),
                '<g data-layout="matrix">'
                '<g id="copy" data-qa-role="text" data-qa-box="100 100 300 120"><text x="100" y="130">Copy</text></g>'
                '<image id="hero" data-qa-role="image" x="250" y="120" width="300" height="180" '
                f'preserveAspectRatio="xMidYMid slice" href="{png_data_uri(600, 360)}"/>'
                '</g>',
            )
            result = check_svg(path, stage="authored", icons_dir=ICONS)
            self.assertTrue(any("collision:" in error for error in result.errors))

    def test_rejects_structural_shape_outside_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_svg(
                Path(tmp),
                '<g data-layout="swimlane"><rect id="clipped-cell" x="1180" y="100" width="180" height="80"/></g>',
            )
            result = check_svg(path, stage="authored", icons_dir=ICONS)
            self.assertTrue(any("visible shape is outside viewBox" in error for error in result.errors))

    def test_accepts_intentional_overlap_and_good_finalized_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_svg(
                Path(tmp),
                '<g data-layout="matrix">'
                '<g id="caption" data-qa-role="text" data-qa-box="100 100 240 80" data-allow-overlap="true">'
                '<text x="120" y="140">Caption overlay</text></g>'
                f'<image id="hero" data-qa-role="image" x="100" y="100" width="400" height="200" href="{png_data_uri(800, 400)}"/>'
                '</g>',
            )
            result = check_svg(path, stage="finalized", icons_dir=ICONS)
            self.assertTrue(result.passed, result.errors)

    def test_project_density_and_layout_plan_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            output = project / "svg_output"
            output.mkdir()
            self.write_svg(
                output,
                '<g data-layout="timeline"><text x="10" y="30">' + ("内容" * 100) + "</text></g>",
            )
            (project / "layout_plan.json").write_text(
                json.dumps([{"slide": 1, "layout_archetype": "timeline", "density": "breathing"}]),
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(project), "--stage", "authored"]), 1)

    def test_finalized_project_scans_svg_final_not_svg_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            authored = project / "svg_output"
            finalized = project / "svg_final"
            authored.mkdir()
            finalized.mkdir()
            self.write_svg(
                authored,
                '<g data-layout="timeline"><text x="10" y="30">Authored placeholder content</text>'
                '<use data-icon="tabler-outline/home" x="20" y="50" width="40" height="40"/></g>',
            )
            self.write_svg(
                finalized,
                '<g data-layout="timeline"><text x="10" y="30">Finalized clean content</text></g>',
            )
            (project / "layout_plan.json").write_text(
                json.dumps([{"slide": 1, "layout_archetype": "timeline", "density": "anchor"}]),
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(project), "--stage", "finalized"]), 0)


if __name__ == "__main__":
    unittest.main()
