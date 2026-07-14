import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_project_contract import (
    default_visual_profile,
    validate_project_contract,
    validate_page_schema,
    validate_visual_profile,
)


def page_schema(**overrides):
    payload = {
        "schema": "ghb.page-schema.v1",
        "slide_id": "body-01",
        "page_purpose": "architecture",
        "layout_variant": "layered_arch/default",
        "density": "balanced",
        "rhythm_role": "anchor",
        "emphasis": "single-focal",
        "focal_target": "platform-core",
        "budgets": {"max_text_chars": 180, "max_nodes": 7},
    }
    payload.update(overrides)
    return payload


class VisualProfileContractTest(unittest.TestCase):
    def test_default_profile_is_valid_and_additive_fields_are_tolerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "visual_profile.json"
            payload = default_visual_profile()
            payload["future_annotation"] = {"owner": "agent"}
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(validate_visual_profile(path), [])

    def test_unknown_profile_major_and_malformed_bands_have_stable_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "visual_profile.json"
            payload = default_visual_profile()
            payload["schema"] = "ghb.visual-profile.v2"
            payload["occupancy"]["body"] = {"min": 0.9, "max": 0.4}
            path.write_text(json.dumps(payload), encoding="utf-8")
            issues = validate_visual_profile(path)
            self.assertEqual(
                {item["code"] for item in issues},
                {"invalid-visual-profile-schema", "invalid-visual-profile-occupancy"},
            )
            self.assertTrue(all(item["path"] == str(path) for item in issues))

    def test_explicit_contract_gate_rejects_missing_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            issues = validate_project_contract(
                project,
                skip_required_files=True,
                require_visual_contract=True,
            )
            codes = {item["code"] for item in issues}
            self.assertIn("missing-visual-profile", codes)
            self.assertIn("missing-layout-plan", codes)

    def test_page_schema_rejects_unknown_major_but_tolerates_additive_fields(self):
        row = {
            "slide_id": "body-01",
            "layout_archetype": "layered_arch",
            "items": ["platform-core"],
        }
        additive = page_schema(experimental_note={"owner": "agent"})
        self.assertEqual(
            validate_page_schema(
                additive, row=row, path=Path("layout_plan.json"), profile=default_visual_profile()
            ),
            [],
        )
        unknown_major = {**additive, "schema": "ghb.page-schema.v2"}
        self.assertIn(
            "invalid-page-schema-schema",
            {
                item["code"]
                for item in validate_page_schema(
                    unknown_major,
                    row=row,
                    path=Path("layout_plan.json"),
                    profile=default_visual_profile(),
                )
            },
        )

    def test_page_schema_rejects_missing_focal_and_slide_or_variant_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "visual_profile.json").write_text(
                json.dumps(default_visual_profile()), encoding="utf-8"
            )
            schema = page_schema(
                slide_id="body-other",
                layout_variant="timeline/default",
                focal_target=None,
            )
            (project / "layout_plan.json").write_text(
                json.dumps([
                    {
                        "slide_id": "body-01",
                        "layout_archetype": "layered_arch",
                        "density": "breathing",
                        "page_schema": schema,
                    }
                ]),
                encoding="utf-8",
            )
            issues = validate_project_contract(
                project,
                skip_required_files=True,
                require_visual_contract=True,
            )
            codes = {item["code"] for item in issues}
            self.assertIn("page-schema-slide-id-drift", codes)
            self.assertIn("page-schema-layout-variant-drift", codes)
            self.assertIn("page-schema-missing-focal-target", codes)
            self.assertIn("page-schema-density-drift", codes)

    def test_page_schema_rejects_invalid_budget_and_bounds_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "visual_profile.json").write_text(
                json.dumps(default_visual_profile()), encoding="utf-8"
            )
            (project / "layout_plan.json").write_text(
                json.dumps([
                    {
                        "slide_id": "body-01",
                        "layout_archetype": "matrix",
                        "page_schema": page_schema(
                            page_purpose="comparison",
                            layout_variant="comparison/default",
                            emphasis="distributed",
                            focal_target=None,
                            budgets={"max_text_chars": 0, "max_nodes": 100},
                            bounds_override={"x": 1200, "y": 100, "width": 200, "height": 300},
                        ),
                    }
                ]),
                encoding="utf-8",
            )
            codes = {
                item["code"]
                for item in validate_project_contract(
                    project, skip_required_files=True, require_visual_contract=True
                )
            }
            self.assertIn("invalid-page-schema-budgets", codes)
            self.assertIn("invalid-page-schema-bounds-override", codes)

    def test_legacy_contract_is_not_required_by_default_before_u11(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "layout_plan.json").write_text("[]", encoding="utf-8")
            codes = {
                item["code"]
                for item in validate_project_contract(project, skip_required_files=True)
            }
            self.assertNotIn("missing-visual-profile", codes)
            self.assertNotIn("missing-page-schema", codes)


if __name__ == "__main__":
    unittest.main()
