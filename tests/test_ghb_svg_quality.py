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

    def add_visual_contract(self, project: Path) -> None:
        (project / "visual_profile.json").write_text(
            json.dumps({
                "schema": "ghb.visual-profile.v1",
                "brand": {"primary": "#AB1F29"},
                "typography": {"min_title_pt": 28, "min_body_pt": 18, "min_title_body_ratio": 1.5},
                "spacing": {"base_unit": 8, "min_component_gap": 16},
                "occupancy": {"body": {"min": 0.42, "max": 0.78}},
                "deck_rhythm": {"max_same_role_streak": 3},
            }),
            encoding="utf-8",
        )
        plan = json.loads((project / "layout_plan.json").read_text(encoding="utf-8"))
        plan[0]["slide_id"] = "body-01"
        plan[0]["page_schema"] = {
            "schema": "ghb.page-schema.v1",
            "slide_id": "body-01",
            "density": "balanced",
            "rhythm_role": "continuity",
            "emphasis": "distributed",
            "layout_variant": "timeline/default",
        }
        (project / "layout_plan.json").write_text(json.dumps(plan), encoding="utf-8")

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

    def test_reports_stage_scoped_page_metrics_coverage_and_advisory_deck_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(Path(tmp))
            self.add_visual_contract(project)
            payload = check_project(project, stage="authored")
            self.assertEqual(payload["stage"], "authored")
            self.assertEqual(payload["visual_quality"]["schema"], "ghb.visual-quality-report.v1")
            page = payload["files"][0]
            self.assertEqual(page["slide_id"], "body-01")
            self.assertIn("occupancy", page["visual_metrics"])
            self.assertIn(page["visual_coverage"]["status"], {"supported", "partial", "not-measurable"})
            self.assertIn("composition-fingerprint", page["visual_metrics"])
            self.assertIn("deck_metrics", payload["visual_quality"])
            self.assertNotIn("composite", json.dumps(payload).lower())
            self.assertTrue(payload["passed"], payload)

    def test_repeated_real_geometry_warns_even_when_layout_markers_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(Path(tmp))
            self.add_visual_contract(project)
            plan = json.loads((project / "layout_plan.json").read_text(encoding="utf-8"))
            base_svg = (project / "svg_output" / "01_timeline.svg").read_text(encoding="utf-8").replace(
                '<text x="100" y="160"',
                '<rect x="100" y="200" width="400" height="240" data-focal="true" fill="#AB1F29"/>'
                '<rect x="600" y="200" width="400" height="240" fill="#FFFFFF"/>'
                '<text x="100" y="160"',
            )
            (project / "svg_output" / "01_timeline.svg").write_text(base_svg, encoding="utf-8")
            for number, marker in ((2, "matrix"), (3, "funnel")):
                svg = base_svg.replace('data-layout="timeline"', f'data-layout="{marker}"')
                (project / "svg_output" / f"0{number}_{marker}.svg").write_text(svg, encoding="utf-8")
                row = json.loads(json.dumps(plan[0]))
                row["slide"] = number
                row["slide_id"] = f"body-0{number}"
                row["layout_archetype"] = marker
                row["page_schema"]["slide_id"] = row["slide_id"]
                row["page_schema"]["layout_variant"] = f"{marker}/default"
                row["page_schema"]["focal_zone"] = "left"
                plan.append(row)
            plan[0]["page_schema"]["focal_zone"] = "left"
            (project / "layout_plan.json").write_text(json.dumps(plan), encoding="utf-8")
            payload = check_project(project, stage="authored")
            codes = {finding["code"] for finding in payload["visual_quality"]["deck_findings"]}
            self.assertIn("visual-composition-repeated", codes)
            self.assertIn("visual-focal-zone-streak", codes)
            self.assertEqual(payload["error_count"], 0)
            self.assertGreaterEqual(payload["warning_count"], 2)

    def test_empty_project_returns_a_stable_failure_in_text_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "svg_output").mkdir()
            self.assertEqual(main([str(project), "--stage", "authored"]), 1)


if __name__ == "__main__":
    unittest.main()
