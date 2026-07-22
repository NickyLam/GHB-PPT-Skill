import tempfile
import unittest
from pathlib import Path

from scripts.remove_svg_background import (
    BackgroundRemovalError,
    remove_background,
    remove_project_backgrounds,
)


SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
<g id="bg"><rect width="1280" height="720" fill="#FFFFFF"/></g>
<g id="bg-surface"><rect x="56" y="96" width="1168" height="608" fill="#FFFFFF"/></g>
<text x="100" y="100">Content</text>
</svg>'''


class RemoveSvgBackgroundTest(unittest.TestCase):
    def test_project_removal_can_target_finalized_directory_without_mutating_authored(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            authored = project / "svg_output"
            finalized = project / "svg_final"
            authored.mkdir()
            finalized.mkdir()
            (authored / "01.svg").write_text(SVG, encoding="utf-8")
            (finalized / "01.svg").write_text(SVG, encoding="utf-8")

            results = remove_project_backgrounds(
                project,
                svg_dir_name="svg_final",
            )

            self.assertEqual([result.status for result in results], ["removed"])
            self.assertEqual((authored / "01.svg").read_text(encoding="utf-8"), SVG)
            self.assertNotIn(
                '<g id="bg">',
                (finalized / "01.svg").read_text(encoding="utf-8"),
            )

    def test_removes_only_full_canvas_preview_background_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slide.svg"
            backup_dir = Path(tmp) / "backup"
            path.write_text(SVG, encoding="utf-8")
            result = remove_background(path, backup_dir=backup_dir)
            self.assertEqual(result.status, "removed")
            updated = path.read_text(encoding="utf-8")
            self.assertNotIn('<g id="bg">', updated)
            self.assertIn('<g id="bg-surface">', updated)
            self.assertEqual((backup_dir / path.name).read_text(encoding="utf-8"), SVG)
            self.assertEqual(remove_background(path).status, "already-absent")

    def test_dry_run_does_not_modify_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slide.svg"
            path.write_text(SVG, encoding="utf-8")
            self.assertEqual(remove_background(path, dry_run=True).status, "would-remove")
            self.assertEqual(path.read_text(encoding="utf-8"), SVG)

    def test_rejects_non_white_or_partial_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slide.svg"
            path.write_text(SVG.replace("#FFFFFF", "#AB1F29", 1), encoding="utf-8")
            with self.assertRaisesRegex(BackgroundRemovalError, "not white"):
                remove_background(path)
            path.write_text(SVG.replace('width="1280" height="720" fill', 'width="1200" height="720" fill', 1), encoding="utf-8")
            with self.assertRaisesRegex(BackgroundRemovalError, "full viewBox"):
                remove_background(path)


if __name__ == "__main__":
    unittest.main()
