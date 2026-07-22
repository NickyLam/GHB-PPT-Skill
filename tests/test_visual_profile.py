import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_project_contract import (
    default_art_direction,
    default_visual_profile,
    validate_art_direction,
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
            self.assertIn("missing-art-direction", codes)
            self.assertIn("missing-layout-plan", codes)

    def test_art_direction_requires_deck_level_visual_thesis_and_rhythm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "art_direction.json"
            payload = default_art_direction()
            path.write_text(json.dumps(payload), encoding="utf-8")
            codes = {item["code"] for item in validate_art_direction(path)}
            self.assertIn("incomplete-art-direction", codes)

            payload.update({
                "visual_thesis": "用证据与决策页建立从工具体验到团队工作流的叙事",
                "anchor_slide_ids": ["body-01", "body-09", "body-18"],
            })
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(validate_art_direction(path), [])

    def test_art_direction_anchor_ids_must_exist_in_layout_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            art = default_art_direction()
            art.update({
                "visual_thesis": "用一张锚点页建立整套演示的视觉重心",
                "anchor_slide_ids": ["body-99"],
            })
            (project / "art_direction.json").write_text(json.dumps(art), encoding="utf-8")
            (project / "visual_profile.json").write_text(
                json.dumps(default_visual_profile()), encoding="utf-8"
            )
            (project / "layout_plan.json").write_text(json.dumps([{
                "slide_id": "body-01",
                "layout_archetype": "layered_arch",
                "items": ["platform-core"],
                "page_schema": page_schema(),
            }]), encoding="utf-8")

            codes = {
                item["code"]
                for item in validate_project_contract(
                    project,
                    skip_required_files=True,
                    require_visual_contract=True,
                )
            }

            self.assertIn("art-direction-anchor-missing-slide", codes)

    def test_art_direction_design_mode_must_match_confirmed_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            art = default_art_direction()
            art.update({
                "design_mode": "instructional",
                "visual_thesis": "以逐步讲解建立可复用的 Skill 选择方法",
                "anchor_slide_ids": ["body-01"],
            })
            (project / "art_direction.json").write_text(json.dumps(art), encoding="utf-8")
            (project / "visual_profile.json").write_text(
                json.dumps(default_visual_profile()), encoding="utf-8"
            )
            (project / "confirmation.json").write_text(
                json.dumps({"decisions": {"mode": "briefing"}}),
                encoding="utf-8",
            )
            (project / "layout_plan.json").write_text(json.dumps([{
                "slide_id": "body-01",
                "layout_archetype": "layered_arch",
                "items": ["platform-core"],
                "page_schema": page_schema(),
            }]), encoding="utf-8")

            codes = {
                item["code"]
                for item in validate_project_contract(
                    project,
                    skip_required_files=True,
                    require_visual_contract=True,
                )
            }

            self.assertIn("art-direction-mode-drift", codes)

    def test_extended_page_purpose_taxonomy_accepts_real_presentation_roles(self):
        row = {
            "slide_id": "body-01",
            "layout_archetype": "editorial",
            "items": ["message"],
        }
        for purpose in (
            "hero",
            "section-anchor",
            "evidence",
            "case-study",
            "instruction",
            "decision",
            "risk",
            "screenshot",
            "data-story",
            "recommendation",
            "closing",
        ):
            with self.subTest(purpose=purpose):
                schema = page_schema(
                    page_purpose=purpose,
                    layout_variant="editorial/default",
                    emphasis="distributed",
                    focal_target=None,
                )
                self.assertEqual(
                    validate_page_schema(
                        schema,
                        row=row,
                        path=Path("layout_plan.json"),
                        profile=default_visual_profile(),
                    ),
                    [],
                )

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
