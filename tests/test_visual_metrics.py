from __future__ import annotations

import json
import tempfile
import unittest
import importlib.util
import subprocess
import sys
from pathlib import Path

from scripts.ghb_visual_quality import (
    analyze_deck_quality,
    evaluate_page_quality,
    evaluate_pilot_gate,
    measure_svg,
)
from scripts.ppt_master.svg_layouts import LayoutSpec, render_layout


ROOT = Path(__file__).resolve().parents[1]
PREFERENCES = json.loads(
    (ROOT / "tests/fixtures/visual_preferences.json").read_text(encoding="utf-8")
)


class VisualMetricsTest(unittest.TestCase):
    def test_metrics_are_measured_from_svg_geometry_not_layout_marker(self):
        fragment = render_layout(
            LayoutSpec(
                "matrix",
                ["A", "B", "C", "D"],
                density="dense",
                variant="matrix/comparison",
                emphasis="single-focal",
                focal_index=1,
            )
        )
        metrics = measure_svg(f'<svg viewBox="0 0 1280 720">{fragment}</svg>')
        self.assertGreater(metrics["occupancy"]["value"], 0.20)
        self.assertEqual(metrics["focal-dominance"]["value"], 1.0)
        self.assertEqual(metrics["occupancy"]["coverage"], "partial")
        disguised = fragment.replace('data-layout="matrix"', 'data-layout="timeline"')
        self.assertEqual(measure_svg(f'<svg viewBox="0 0 1280 720">{disguised}</svg>'), metrics)

    def test_metrics_report_unsupported_geometry_and_malformed_svg(self):
        metrics = measure_svg('<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="20"/></svg>')
        self.assertEqual(metrics["occupancy"]["coverage"], "supported")
        self.assertAlmostEqual(metrics["occupancy"]["value"], 0.16, places=6)
        partial = measure_svg(
            '<svg viewBox="0 0 100 100"><g transform="translate(10 10)"><rect width="20" height="20"/></g>'
            '<path d="M0 0L10 10"/><text x="20" y="20">unknown extent</text></svg>'
        )
        self.assertEqual(partial["coverage"]["status"], "not-measurable")
        self.assertIn("transformed-group", partial["limitations"])
        self.assertIn("path", partial["limitations"])
        self.assertIn("text-extent", partial["limitations"])
        with self.assertRaisesRegex(ValueError, "invalid-svg-geometry"):
            measure_svg("<svg><rect")

    def test_geometry_policy_flags_fake_marker_and_underscaled_composition(self):
        cards = "".join(
            f'<rect x="{10 + index * 22}" y="40" width="18" height="12" fill="#FFFFFF"/>'
            for index in range(4)
        )
        svg = f'<svg viewBox="0 0 200 100"><g data-layout="timeline">{cards}</g></svg>'
        result = evaluate_page_quality(
            svg,
            slide_id="body-01",
            profile={"occupancy": {"body": {"min": 0.42, "max": 0.78}}},
            page_schema={"density": "balanced", "emphasis": "distributed"},
        )
        self.assertEqual(result["measurements"]["composition-fingerprint"]["source"], "geometry")
        self.assertIn("visual-occupancy-below-min", {item["code"] for item in result["findings"]})
        self.assertTrue(all(item["severity"] == "warning" for item in result["findings"]))
        self.assertNotIn("timeline", result["measurements"]["composition-fingerprint"]["value"])

    def test_supported_geometry_and_qa_boxes_have_stable_metrics(self):
        svg = '''<svg viewBox="0 0 200 100">
        <g id="layout-cards" data-layout="matrix">
          <g id="title" data-qa-role="title" data-qa-box="10 8 180 16"><text font-size="24">Title</text></g>
          <rect id="a" x="10" y="35" width="80" height="50" fill="#AB1F29" data-focal="true"/>
          <rect id="b" x="110" y="35" width="80" height="50" fill="#FFFFFF"/>
          <text x="20" y="60" font-size="12">unknown width</text>
        </g></svg>'''
        metrics = measure_svg(svg, primary_color="#AB1F29", base_unit=8)
        self.assertAlmostEqual(metrics["occupancy"]["value"], 0.544, places=3)
        self.assertAlmostEqual(metrics["emphasis-color-area"]["value"], 0.20, places=3)
        self.assertEqual(metrics["coverage"]["status"], "partial")
        self.assertEqual(metrics["composition-fingerprint"]["source"], "geometry")
        self.assertNotIn("score", json.dumps(metrics).lower())

    def test_background_header_footer_and_bleed_do_not_inflate_body_occupancy(self):
        svg = '''<svg viewBox="0 0 200 100">
        <g id="bg"><rect width="200" height="100"/></g>
        <g id="header"><rect width="200" height="10"/></g>
        <rect id="bleed" x="-20" y="20" width="240" height="60" data-allow-overflow="true"/>
        <g id="layout-body"><rect x="50" y="30" width="100" height="40"/></g>
        <g id="footer"><rect y="90" width="200" height="10"/></g>
        </svg>'''
        metrics = measure_svg(svg)
        self.assertAlmostEqual(metrics["occupancy"]["value"], 0.20, places=6)

    def test_deck_findings_use_raw_fingerprints_and_allow_policy_suppression(self):
        svg = '<svg viewBox="0 0 200 100"><g id="layout-cards"><rect x="10" y="20" width="80" height="60" data-focal="true"/><rect x="110" y="20" width="80" height="60"/></g></svg>'
        pages = []
        for index in range(3):
            page = evaluate_page_quality(
                svg,
                slide_id=f"body-{index + 1:02d}",
                profile={},
                page_schema={
                    "density": "balanced",
                    "rhythm_role": "continuity",
                    "layout_variant": f"variant-{index}",
                    "policy_exceptions": ["visual-composition-repeated"] if index == 1 else [],
                },
            )
            pages.append(page)
        raw_before = [page["measurements"] for page in pages]
        deck = analyze_deck_quality(pages, profile={"deck_rhythm": {"max_same_role_streak": 3}})
        codes = {item["code"] for item in deck["findings"]}
        self.assertIn("visual-focal-zone-streak", codes)
        self.assertNotIn("visual-composition-repeated", codes)
        self.assertEqual(raw_before, [page["measurements"] for page in pages])
        self.assertEqual(deck["measurements"]["composition_fingerprints"][0], deck["measurements"]["composition_fingerprints"][1])

    def test_advisory_exceptions_cannot_suppress_explicit_bounds_errors(self):
        svg = '<svg viewBox="0 0 200 100"><g id="layout-card"><rect x="10" y="10" width="160" height="70"/></g></svg>'
        result = evaluate_page_quality(
            svg,
            slide_id="body-01",
            profile={},
            page_schema={
                "density": "balanced",
                "emphasis": "distributed",
                "bounds_override": {"x": 20, "y": 20, "width": 100, "height": 50},
                "policy_exceptions": ["visual-explicit-bounds-violation"],
            },
        )
        errors = [item for item in result["findings"] if item["severity"] == "error"]
        self.assertEqual([item["code"] for item in errors], ["visual-explicit-bounds-violation"])
        self.assertNotIn("visual-explicit-bounds-violation", result["suppressed_issue_codes"])

    def test_explicit_bounds_use_raw_geometry_before_body_clipping(self):
        svg = '''<svg viewBox="0 0 200 100">
        <g id="bg-surface"><rect x="50" y="10" width="140" height="80"/></g>
        <g id="layout-card"><rect x="40" y="20" width="40" height="40"/></g>
        </svg>'''
        result = evaluate_page_quality(
            svg,
            slide_id="body-01",
            profile={},
            page_schema={
                "density": "balanced",
                "emphasis": "distributed",
                "bounds_override": {"x": 50, "y": 10, "width": 140, "height": 80},
            },
        )
        self.assertIn("visual-explicit-bounds-violation", {item["code"] for item in result["findings"]})

    def test_equal_card_primary_fill_is_a_valid_focal_signal(self):
        fragment = render_layout(
            LayoutSpec(
                "matrix",
                ["A", "B", "C", "D"],
                density="balanced",
                variant="matrix/comparison",
                emphasis="single-focal",
                focal_index=0,
            )
        )
        result = evaluate_page_quality(
            f'<svg viewBox="0 0 1280 720">{fragment}</svg>',
            slide_id="body-01",
            profile={},
            page_schema={"density": "balanced", "emphasis": "single-focal"},
        )
        self.assertTrue(result["measurements"]["focal-emphasis"]["primary_fill"])
        self.assertNotIn("visual-focal-dominance-low", {item["code"] for item in result["findings"]})

    def test_empty_deck_is_measurable_as_an_empty_advisory_result(self):
        deck = analyze_deck_quality([], profile={})
        self.assertEqual(deck["findings"], [])
        self.assertEqual(deck["measurements"]["composition_fingerprints"], [])

    def test_non_finite_geometry_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid-svg-geometry"):
            measure_svg('<svg viewBox="0 0 nan 100"><rect width="20" height="20"/></svg>')

    def test_background_aliases_are_excluded_without_a_layout_scope(self):
        metrics = measure_svg(
            '<svg viewBox="0 0 200 100"><g id="bg"><rect width="200" height="100"/></g>'
            '<g id="bg-surface"><rect width="200" height="100"/></g>'
            '<rect x="50" y="30" width="100" height="40"/></svg>'
        )
        self.assertAlmostEqual(metrics["occupancy"]["value"], 0.20, places=6)

    def test_visual_quality_cli_bootstraps_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/ghb_visual_quality.py"), "--help"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gate_is_pending_without_real_blind_judgments(self):
        result = evaluate_pilot_gate(
            PREFERENCES,
            {
                "schema": "ghb.visual-pilot-review.v1",
                "eligible_case_ids": ["comparison-03", "timeline-03", "metrics-03"],
                "pair_assignments": [],
                "judgments": [],
            },
            {"schema": "ghb.visual-pilot-deterministic.v1", "blocking_false_positives": [], "advisory_rule_case_results": []},
        )
        self.assertEqual(result["decision"], "pending")
        self.assertFalse(result["proceed"])
        self.assertIn("insufficient-blind-review-evidence", result["reasons"])

    def test_gate_passes_only_with_frozen_protocol_and_complete_false_positive_audit(self):
        review = self._review_record("pilot")
        deterministic = self._deterministic_record()
        result = evaluate_pilot_gate(PREFERENCES, review, deterministic)
        self.assertEqual(result["decision"], "passed")
        self.assertTrue(result["proceed"])
        self.assertEqual(result["preference_rate"], 1.0)

        review["judgments"][0]["structural_veto"] = True
        failed = evaluate_pilot_gate(PREFERENCES, review, deterministic)
        self.assertEqual(failed["decision"], "failed")
        self.assertIn("structural-regression-veto", failed["reasons"])

    def test_gate_rejects_duplicate_reviewer_and_incomplete_audit(self):
        review = self._review_record("pilot")
        review["judgments"].append(dict(review["judgments"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate-reviewer-page-judgment"):
            evaluate_pilot_gate(PREFERENCES, review, self._deterministic_record())
        with self.assertRaisesRegex(ValueError, "incomplete-advisory-audit"):
            evaluate_pilot_gate(PREFERENCES, self._review_record("pilot"), self._deterministic_record() | {"advisory_rule_case_results": []})

    def test_pilot_builder_preserves_before_and_emits_only_two_family_after(self):
        path = ROOT / "tests/fixtures/build_visual_pilot.py"
        spec = importlib.util.spec_from_file_location("build_visual_pilot", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "pilot"
            manifest = module.build(output)
            self.assertEqual(manifest["decision"], "pending")
            self.assertEqual(manifest["eligible_case_count"], 3)
            self.assertEqual(len(list((output / "before").glob("*.svg"))), 6)
            self.assertEqual(len(list((output / "after").glob("*.svg"))), 3)
            self.assertEqual(len(list((output / "blind").glob("*/*.svg"))), 6)
            self.assertEqual({row["family"] for row in manifest["eligible_cases"]}, {"timeline", "matrix"})
            self.assertEqual(
                {row["page_schema"]["density"] for row in manifest["eligible_cases"]},
                {"balanced", "dense"},
            )
            public = json.loads((output / "blind-review-template.json").read_text(encoding="utf-8"))
            self.assertNotIn("roles", json.dumps(public))
            self.assertEqual(set(public["judgment_template"]["rubric"]), {"hierarchy", "balance", "readability", "semantic-fit"})
            for pair in public["pairs"]:
                self.assertRegex(pair["left_artifact"], r"^blind/[^/]+/A\.svg$")
                self.assertRegex(pair["right_artifact"], r"^blind/[^/]+/B\.svg$")
                self.assertTrue((output / pair["left_artifact"]).is_file())
                self.assertTrue((output / pair["right_artifact"]).is_file())
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                module.build(output)

    def test_gate_rejects_incomplete_case_set_and_invalid_audit_fields(self):
        review = self._review_record("pilot")
        review["eligible_case_ids"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete-pilot-case-assignments"):
            evaluate_pilot_gate(PREFERENCES, review, self._deterministic_record())

        review = self._review_record("pilot")
        review["judgments"][0]["rubric"] = {"hierarchy": 1}
        with self.assertRaisesRegex(ValueError, "invalid-review-rubric"):
            evaluate_pilot_gate(PREFERENCES, review, self._deterministic_record())

    def test_gate_accepts_explicit_unscored_rubric_without_inventing_numbers(self):
        review = self._review_record("pilot")
        for judgment in review["judgments"]:
            judgment["rubric"] = {
                dimension: "not-scored"
                for dimension in ("hierarchy", "balance", "readability", "semantic-fit")
            }
        result = evaluate_pilot_gate(PREFERENCES, review, self._deterministic_record())
        self.assertEqual(result["decision"], "passed")
        review = self._review_record("pilot")
        review["judgments"][0]["rubric"]["hierarchy"] = 6
        with self.assertRaisesRegex(ValueError, "invalid-review-rubric"):
            evaluate_pilot_gate(PREFERENCES, review, self._deterministic_record())

    def _review_record(self, winner: str) -> dict:
        pairs = []
        judgments = []
        for case_id, purpose in (("comparison-03", "comparison"), ("timeline-03", "timeline"), ("metrics-03", "metrics")):
            left = f"{case_id}::A"
            right = f"{case_id}::B"
            pairs.append({"page_case_id": case_id, "page_purpose": purpose, "masked_left_id": left, "masked_right_id": right, "roles": {left: "baseline", right: "pilot"}})
            for reviewer in range(3):
                judgments.append({"reviewer_id_hash": f"reviewer-{reviewer}", "page_case_id": case_id, "masked_left_id": left, "masked_right_id": right, "presented_order": [left, right], "judgment": right if winner == "pilot" else left, "rubric": {"hierarchy": 1, "balance": 1, "readability": 1, "semantic-fit": 1}, "structural_veto": False, "recorded_at": "2026-07-14T00:00:00Z"})
        return {
            "schema": "ghb.visual-pilot-review.v1",
            "eligible_case_ids": [pair["page_case_id"] for pair in pairs],
            "pair_assignments": pairs,
            "judgments": judgments,
        }

    def _deterministic_record(self) -> dict:
        pairs = PREFERENCES["deterministic_pilot_false_positive_gate"]["advisory_rule_case_pairs"]
        return {"schema": "ghb.visual-pilot-deterministic.v1", "blocking_false_positives": [], "advisory_rule_case_results": [{"rule_case_pair": pair, "disposition": "not-triggered"} for pair in pairs]}


if __name__ == "__main__":
    unittest.main()
