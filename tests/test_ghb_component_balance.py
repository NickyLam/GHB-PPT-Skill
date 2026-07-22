from __future__ import annotations

import unittest

from scripts.ghb_component_balance import analyze_component_balance
from scripts.ghb_visual_quality import evaluate_page_quality


def _svg(body: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        f"{body}</svg>"
    )


# A 500x400 card with a single thin slot near the top: ~9% occupancy and a
# ~340px empty band below it -> hollow card.
VOID_CARD = _svg(
    '<rect data-component="matrix-card" data-component-id="c1" '
    'data-qa-box="100 100 500 400"/>'
    '<rect data-component-parent="c1" data-component-slot="heading" '
    'data-qa-box="120 120 460 40"/>'
)

# Same card footprint but slots fill most of it: no void.
FILLED_CARD = _svg(
    '<rect data-component="matrix-card" data-component-id="c1" '
    'data-qa-box="100 100 500 400"/>'
    '<rect data-component-parent="c1" data-component-slot="heading" '
    'data-qa-box="120 120 460 120"/>'
    '<rect data-component-parent="c1" data-component-slot="body" '
    'data-qa-box="120 250 460 230"/>'
)

# Card with no declared slots is left to upstream contract checks.
NO_SLOTS = _svg(
    '<rect data-component="matrix-card" data-component-id="c1" '
    'data-qa-box="100 100 500 400"/>'
)


class ComponentVoidTest(unittest.TestCase):
    def test_hollow_card_reports_component_void_error(self):
        findings = analyze_component_balance(VOID_CARD, slide_id="s1")
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["code"], "component-void")
        self.assertEqual(finding["severity"], "error")
        self.assertEqual(finding["evidence"]["component"], "c1")
        self.assertLess(finding["evidence"]["slot_occupancy"], 0.45)
        self.assertGreater(finding["evidence"]["largest_empty_band_px"], 200.0)

    def test_filled_card_has_no_void(self):
        self.assertEqual(analyze_component_balance(FILLED_CARD, slide_id="s1"), [])

    def test_card_without_slots_is_not_flagged(self):
        self.assertEqual(analyze_component_balance(NO_SLOTS, slide_id="s1"), [])

    def test_thresholds_are_tunable(self):
        # Loosening the band requirement past the actual band clears the finding.
        self.assertEqual(
            analyze_component_balance(VOID_CARD, slide_id="s1", void_band_px=1000.0),
            [],
        )

    def test_invalid_svg_is_silent(self):
        self.assertEqual(analyze_component_balance("<svg", slide_id="s1"), [])


class ComponentVoidIntegrationTest(unittest.TestCase):
    def test_void_surfaces_through_page_quality_findings(self):
        result = evaluate_page_quality(
            VOID_CARD,
            slide_id="s1",
            profile={"typography": {"enforcement": "strict"}},
            page_schema={"density": "balanced"},
        )
        codes = {f["code"] for f in result["findings"]}
        self.assertIn("component-void", codes)
        void = next(f for f in result["findings"] if f["code"] == "component-void")
        self.assertEqual(void["severity"], "error")


if __name__ == "__main__":
    unittest.main()
