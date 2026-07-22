from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import shutil
from pathlib import Path

from scripts.ghb_ppt import _profiled_merge_values, _write_cover_plan
from scripts.template_profile import build_template_profile


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "GHB_PPT_模板.pptx"


class TemplateProfileTest(unittest.TestCase):
    def test_bundled_template_profile_discovers_cover_slots_and_slide_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            library_path = Path(tmp) / "library.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "ppt_master" / "template_fill_pptx.py"),
                    "analyze",
                    str(TEMPLATE),
                    "-o",
                    str(library_path),
                ],
                check=True,
                cwd=ROOT,
                capture_output=True,
            )
            library = json.loads(library_path.read_text(encoding="utf-8"))
        profile = build_template_profile(library, TEMPLATE)
        self.assertEqual(profile["schema"], "ghb.template-profile.v1")
        self.assertEqual(
            profile["cover_slots"],
            {"title": "s01_sh8", "subtitle": "s01_sh6", "date": "s01_sh4"},
        )
        self.assertEqual(len(profile["header_safe_zones"]["section"]), 4)
        self.assertEqual(profile["profile_source"], "reviewed-sidecar")
        self.assertGreaterEqual(profile["ending_slide_index"], profile["content_layout_index"])

    def test_template_without_reviewed_sidecar_infers_geometry_and_brand_from_ooxml(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "alternate-template.pptx"
            shutil.copyfile(TEMPLATE, copied)
            library_path = Path(tmp) / "library.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "ppt_master" / "template_fill_pptx.py"),
                    "analyze",
                    str(copied),
                    "-o",
                    str(library_path),
                ],
                check=True,
                cwd=ROOT,
                capture_output=True,
            )
            library = json.loads(library_path.read_text(encoding="utf-8"))
            profile = build_template_profile(library, copied)

        self.assertEqual(profile["profile_source"], "ooxml-inferred")
        self.assertEqual(profile["brand"], {"primary": "#AB1F29", "secondary": "#44546A"})
        self.assertEqual(profile["inference"]["safe_zones"], "content-layout-placeholder-geometry")
        self.assertNotEqual(profile["body_surface"], [56, 96, 1168, 608])
        self.assertGreater(profile["header_safe_zones"]["section"][2], 0)

    def test_stale_reviewed_sidecar_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "alternate-template.pptx"
            shutil.copyfile(TEMPLATE, copied)
            copied.with_suffix(".profile.json").write_text(
                json.dumps({
                    "schema": "ghb.template-profile.v1",
                    "source_sha256": "0" * 64,
                    "body_surface": [1, 2, 3, 4],
                }),
                encoding="utf-8",
            )
            library_path = Path(tmp) / "library.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "ppt_master" / "template_fill_pptx.py"),
                    "analyze",
                    str(copied),
                    "-o",
                    str(library_path),
                ],
                check=True,
                cwd=ROOT,
                capture_output=True,
            )
            profile = build_template_profile(
                json.loads(library_path.read_text(encoding="utf-8")), copied
            )
        self.assertEqual(profile["profile_source"], "ooxml-inferred")
        self.assertNotEqual(profile["body_surface"], [1, 2, 3, 4])

    def test_cover_plan_uses_profile_slots_instead_of_hardcoded_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            _write_cover_plan(
                path,
                "标题",
                "副标题",
                "日期",
                cover_slots={"title": "title-x", "subtitle": "sub-x", "date": "date-x"},
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                [item["slot_id"] for item in payload["slides"][0]["replacements"]],
                ["title-x", "sub-x", "date-x"],
            )

    def test_merge_defaults_come_from_profile_but_explicit_values_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "analysis").mkdir()
            (project / "analysis" / "template_profile.json").write_text(
                json.dumps({
                    "schema": "ghb.template-profile.v1",
                    "content_layout_index": 7,
                    "ending_slide_index": 9,
                }),
                encoding="utf-8",
            )
            self.assertEqual(
                _profiled_merge_values(project, content_layout=None, ending_slide=None),
                (7, 9),
            )
            self.assertEqual(
                _profiled_merge_values(project, content_layout=3, ending_slide=4),
                (3, 4),
            )


if __name__ == "__main__":
    unittest.main()
