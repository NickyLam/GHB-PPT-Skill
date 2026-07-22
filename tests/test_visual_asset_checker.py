import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.ppt_master.visual_asset_checker import _apply_content_plan, check_svg, main


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

    def test_rejects_flow_connector_that_is_too_short_or_enters_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_svg(
                Path(tmp),
                '<g data-layout="waterfall">'
                '<g id="step-1" data-flow-node="step-1" data-qa-box="100 200 180 100">'
                '<rect x="100" y="200" width="180" height="100"/></g>'
                '<g id="step-2" data-flow-node="step-2" data-qa-box="290 200 180 100">'
                '<rect x="290" y="200" width="180" height="100"/></g>'
                '<line id="edge-1" data-flow-from="step-1" data-flow-to="step-2" '
                'x1="270" y1="250" x2="280" y2="250"/>'
                '</g>',
            )
            result = check_svg(path, stage="authored", icons_dir=ICONS)
            joined = "\n".join(result.errors)
            self.assertIn("connector-node-intersection", joined)
            self.assertIn("connector-visible-length-low", joined)

    def test_rejects_flow_connector_crossing_declared_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_svg(
                Path(tmp),
                '<g data-layout="waterfall">'
                '<g id="step-1" data-flow-node="step-1" data-qa-box="100 200 160 100">'
                '<rect x="100" y="200" width="160" height="100"/></g>'
                '<g id="step-2" data-flow-node="step-2" data-qa-box="420 200 160 100">'
                '<rect x="420" y="200" width="160" height="100"/></g>'
                '<text id="spill" data-qa-role="text" data-qa-box="270 225 120 50" '
                'x="270" y="250">AGENTS.md/Rules 约束</text>'
                '<line id="edge-1" data-flow-from="step-1" data-flow-to="step-2" '
                'x1="266" y1="250" x2="414" y2="250"/>'
                '</g>',
            )
            result = check_svg(path, stage="authored", icons_dir=ICONS)
            self.assertTrue(
                any("connector-text-intersection" in error for error in result.errors),
                result.errors,
            )

    def test_rejects_component_slot_overflow_and_pair_imbalance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_svg(
                Path(tmp),
                '<g data-layout="matrix">'
                '<g id="left" data-component="evidence-card" data-component-id="left" '
                'data-component-pair="comparison-1" data-qa-box="100 180 420 360">'
                '<rect x="100" y="180" width="420" height="360"/>'
                '<g id="left-verdict" data-component-parent="left" data-component-slot="verdict" '
                'data-qa-box="140 470 340 48"><text x="160" y="500">待补充</text></g>'
                '</g>'
                '<g id="right" data-component="evidence-card" data-component-id="right" '
                'data-component-pair="comparison-1" data-qa-box="620 180 420 360">'
                '<rect x="620" y="180" width="420" height="360"/>'
                '<g id="right-verdict" data-component-parent="right" data-component-slot="verdict" '
                'data-qa-box="660 300 340 48"><text x="680" y="330">须查布局</text></g>'
                '<g id="right-media" data-component-parent="right" data-component-slot="media" '
                'data-qa-box="980 500 120 80"><rect x="980" y="500" width="120" height="80"/></g>'
                '</g>'
                '</g>',
            )
            result = check_svg(path, stage="authored", icons_dir=ICONS)
            joined = "\n".join(result.errors)
            self.assertIn("component-slot-overflow", joined)
            self.assertIn("component-balance-outlier", joined)

    def test_rejects_fixed_text_fit_without_an_explicit_positive_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_svg(
                Path(tmp),
                '<g data-layout="editorial">'
                '<text id="unsafe-fixed" data-text-fit="fixed" '
                'x="100" y="160" font-size="32">WorkBuddy</text>'
                '</g>',
            )
            result = check_svg(path, stage="authored", icons_dir=ICONS)
            self.assertTrue(
                any("text-fit-contract" in error for error in result.errors),
                result.errors,
            )

    def test_near_capacity_text_estimate_does_not_create_false_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_svg(
                Path(tmp),
                '<g data-layout="editorial">'
                '<text id="near-capacity" data-qa-box="100 120 248 40" '
                'x="100" y="154" font-size="24">十个中文字符刚好容纳</text>'
                '<text id="title-line" data-qa-box="100 70 760 40" '
                'x="100" y="106" font-size="40">第二行标题</text>'
                '</g>',
            )
            result = check_svg(path, stage="authored", icons_dir=ICONS)
        self.assertFalse(
            any("text-component-overflow" in error for error in result.errors),
            result.errors,
        )

    def test_component_inset_contract_rejects_uneven_and_accepts_balanced_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            uneven = self.write_svg(
                root,
                '<g data-layout="flywheel">'
                '<g id="uneven" data-component="skill-loop-card" '
                'data-component-id="uneven" data-component-balance="insets" '
                'data-qa-box="100 100 320 112">'
                '<rect x="100" y="100" width="320" height="112"/>'
                '<g data-component-parent="uneven" data-component-slot="icon" '
                'data-qa-box="124 132 48 48"/>'
                '<g data-component-parent="uneven" data-component-slot="copy" '
                'data-qa-box="188 124 208 82"/>'
                '</g></g>',
                name="01_uneven.svg",
            )
            balanced = self.write_svg(
                root,
                '<g data-layout="flywheel">'
                '<g id="balanced" data-component="skill-loop-card" '
                'data-component-id="balanced" data-component-balance="insets" '
                'data-qa-box="100 100 320 112">'
                '<rect x="100" y="100" width="320" height="112"/>'
                '<g data-component-parent="balanced" data-component-slot="icon" '
                'data-qa-box="124 132 48 48"/>'
                '<g data-component-parent="balanced" data-component-slot="copy" '
                'data-qa-box="188 112 208 88"/>'
                '</g></g>',
                name="02_balanced.svg",
            )
            inconsistent = self.write_svg(
                root,
                '<g data-layout="flywheel">'
                '<g data-component="skill-loop-card" data-component-id="card-a" '
                'data-component-balance="insets" data-qa-box="100 100 320 112">'
                '<rect x="100" y="100" width="320" height="112"/>'
                '<g data-component-parent="card-a" data-component-slot="icon" '
                'data-qa-box="124 132 48 48"/>'
                '<g data-component-parent="card-a" data-component-slot="copy" '
                'data-qa-box="188 112 208 88"/>'
                '</g>'
                '<g data-component="skill-loop-card" data-component-id="card-b" '
                'data-component-balance="insets" data-qa-box="500 100 320 112">'
                '<rect x="500" y="100" width="320" height="112"/>'
                '<g data-component-parent="card-b" data-component-slot="icon" '
                'data-qa-box="532 132 48 48"/>'
                '<g data-component-parent="card-b" data-component-slot="copy" '
                'data-qa-box="588 120 200 72"/>'
                '</g></g>',
                name="03_inconsistent.svg",
            )

            uneven_result = check_svg(uneven, stage="authored", icons_dir=ICONS)
            balanced_result = check_svg(balanced, stage="authored", icons_dir=ICONS)
            inconsistent_result = check_svg(inconsistent, stage="authored", icons_dir=ICONS)
            self.assertTrue(
                any("component-inset-outlier" in error for error in uneven_result.errors),
                uneven_result.errors,
            )
            self.assertFalse(
                any("component-inset-outlier" in error for error in balanced_result.errors),
                balanced_result.errors,
            )
            self.assertTrue(
                any("component-inset-outlier" in error for error in inconsistent_result.errors),
                inconsistent_result.errors,
            )

    def test_content_inset_contract_centers_variable_width_copy_per_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_svg(
                root,
                '<g data-layout="flywheel">'
                '<g data-component="skill-loop-card" data-component-id="wide" '
                'data-component-balance="content-insets" data-qa-box="100 100 320 112">'
                '<rect x="100" y="100" width="320" height="112"/>'
                '<g data-component-parent="wide" data-component-slot="icon" '
                'data-qa-box="133 132 48 48"/>'
                '<g data-component-parent="wide" data-component-slot="copy" '
                'data-qa-box="197 112 190 88"/>'
                '</g>'
                '<g data-component="skill-loop-card" data-component-id="narrow" '
                'data-component-balance="content-insets" data-qa-box="500 100 320 112">'
                '<rect x="500" y="100" width="320" height="112"/>'
                '<g data-component-parent="narrow" data-component-slot="icon" '
                'data-qa-box="547.5 132 48 48"/>'
                '<g data-component-parent="narrow" data-component-slot="copy" '
                'data-qa-box="611.5 112 161 88"/>'
                '</g></g>',
                name="01_centered-content.svg",
            )
            off_center = self.write_svg(
                root,
                '<g data-layout="flywheel">'
                '<g data-component="skill-loop-card" data-component-id="off-center" '
                'data-component-balance="content-insets" data-qa-box="100 100 320 112">'
                '<rect x="100" y="100" width="320" height="112"/>'
                '<g data-component-parent="off-center" data-component-slot="icon" '
                'data-qa-box="124 132 48 48"/>'
                '<g data-component-parent="off-center" data-component-slot="copy" '
                'data-qa-box="188 112 161 88"/>'
                '</g></g>',
                name="02_off-center-content.svg",
            )

            result = check_svg(path, stage="authored", icons_dir=ICONS)
            off_center_result = check_svg(off_center, stage="authored", icons_dir=ICONS)

            self.assertTrue(result.passed, result.errors)
            self.assertTrue(
                any(
                    "component-inset-outlier" in error
                    for error in off_center_result.errors
                ),
                off_center_result.errors,
            )

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

    def test_nested_page_schema_density_wins_and_legacy_anchor_remains_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_svg(
                root,
                '<g data-layout="timeline"><text x="10" y="30">' + ("内容" * 100) + "</text></g>",
            )
            result = check_svg(path, stage="authored", icons_dir=ICONS)
            nested = root / "nested.json"
            nested.write_text(
                json.dumps([{
                    "slide": 1,
                    "layout_archetype": "timeline",
                    "density": "anchor",
                    "page_schema": {"density": "breathing"},
                }]),
                encoding="utf-8",
            )
            self.assertEqual(_apply_content_plan([result], nested), [])
            self.assertTrue(any("breathing page" in error for error in result.errors))

            legacy_result = check_svg(path, stage="authored", icons_dir=ICONS)
            legacy = root / "legacy.json"
            legacy.write_text(
                json.dumps([{"slide": 1, "layout_archetype": "timeline", "density": "anchor"}]),
                encoding="utf-8",
            )
            self.assertEqual(_apply_content_plan([legacy_result], legacy), [])
            self.assertFalse(any("unknown density" in error for error in legacy_result.errors))

    def test_planned_page_without_visible_content_is_a_hard_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_svg(
                root,
                '<g data-layout="timeline"><text x="10" y="30" display="none">Hidden</text></g>',
            )
            plan = root / "layout_plan.json"
            plan.write_text(
                json.dumps([{"slide": 1, "layout_archetype": "timeline", "density": "anchor"}]),
                encoding="utf-8",
            )
            result = check_svg(path, stage="authored", icons_dir=ICONS)
            _apply_content_plan([result], plan)
            self.assertIn("planned page has no visible content", result.errors)

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
