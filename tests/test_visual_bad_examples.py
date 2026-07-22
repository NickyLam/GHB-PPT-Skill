from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.ghb_svg_quality import check_project
from scripts.ghb_visual_quality import evaluate_page_quality
from scripts.ppt_master.visual_asset_checker import check_svg
from scripts.validate_project_contract import default_visual_profile


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "visual_bad_examples"
ICONS = ROOT / "templates" / "icons"


class VisualBadExampleRegressionTest(unittest.TestCase):
    def test_header_long_title_reports_specific_safe_zone_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "svg_output").mkdir()
            shutil.copy(
                FIXTURES / "header-long-title-with-native-section-frame.svg",
                project / "svg_output" / "01_header.svg",
            )
            (project / "layout_plan.json").write_text(
                json.dumps([{
                    "slide": 1,
                    "slide_id": "body-01",
                    "layout_archetype": "editorial",
                    "page_schema": {
                        "slide_id": "body-01",
                        "page_purpose": "hero",
                        "density": "balanced",
                        "rhythm_role": "anchor",
                        "layout_variant": "editorial/hero",
                        "emphasis": "single-focal",
                        "focal_target": "过长主标题",
                    },
                }]),
                encoding="utf-8",
            )
            (project / "visual_profile.json").write_text(
                json.dumps(default_visual_profile()), encoding="utf-8"
            )
            payload = check_project(project, stage="authored")
            errors = payload["files"][0]["visual_errors"]
            self.assertTrue(any("header-safe-zone-collision" in item for item in errors))

    def test_comparison_void_reports_specific_component_code(self):
        svg = (FIXTURES / "comparison-card-internal-void.svg").read_text(encoding="utf-8")
        result = evaluate_page_quality(
            svg,
            slide_id="body-01",
            profile=default_visual_profile(),
            page_schema={"density": "balanced"},
        )
        self.assertIn("component-void", {item["code"] for item in result["findings"]})

    def test_seven_step_flow_reports_text_and_connector_codes(self):
        result = check_svg(
            FIXTURES / "seven-step-flow-with-long-cjk-labels.svg",
            stage="authored",
            icons_dir=ICONS,
        )
        joined = "\n".join(result.errors)
        self.assertIn("text-component-overflow", joined)
        self.assertIn("connector-node-intersection", joined)


if __name__ == "__main__":
    unittest.main()
