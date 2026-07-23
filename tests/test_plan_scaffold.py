from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.plan_scaffold import ScaffoldError, extract_claims, scaffold_project
from scripts.validate_project_contract import (
    find_scaffold_markers,
    score_layout_fit,
    validate_plan,
    validate_project_contract,
)


SOURCE = """# 项目背景
- 团队规模扩张导致协作成本上升
- 需要统一的知识管理平台

# 解决方案
1. 引入结构化文档流程
2. 建立自动化质量门

# 预期收益
- 返工率下降 30%
"""

CONFIRMATION = {
    "schema": "ghb.confirmation.v1",
    "status": "confirmed",
    "confirmation_source": "chat",
    "confirmed_at": "2026-07-22T00:00:00Z",
    "decision_digest": "test",
    "decisions": {
        "audience": "技术团队",
        "page_range": "8-12",
        "mode": "briefing",
        "outline": [
            {"title": "项目背景", "rhythm": "anchor"},
            {"title": "解决方案", "rhythm": "dense"},
            {"title": "预期收益", "rhythm": "breathing"},
        ],
        "content_tradeoffs": {"expand": [], "omit": [], "combine": []},
        "visual_assets": {"image_source": None, "icon_set": None},
    },
}


def _seed_project(root: Path) -> Path:
    project = root / "proj"
    (project / "sources").mkdir(parents=True)
    (project / "sources" / "source.md").write_text(SOURCE, encoding="utf-8")
    (project / "confirmation.json").write_text(
        json.dumps(CONFIRMATION, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return project


class ExtractClaimsTest(unittest.TestCase):
    def test_extracts_headings_and_bullets_with_traceable_ids(self):
        claims = extract_claims(SOURCE)
        self.assertGreaterEqual(len(claims), 4)
        ids = [c["id"] for c in claims]
        self.assertEqual(len(ids), len(set(ids)))
        for claim in claims:
            self.assertTrue(claim["draft"])
            self.assertTrue(claim["source_reference"].startswith("sources/source.md"))

    def test_empty_source_still_yields_a_todo_claim(self):
        claims = extract_claims("")
        self.assertEqual(len(claims), 1)
        self.assertTrue(claims[0]["draft"])


class ScaffoldProjectTest(unittest.TestCase):
    def test_layout_fit_score_rejects_timeline_without_time_order(self):
        row = {
            "slide_id": "body-01",
            "page_schema": {"layout_variant": "timeline/editorial"},
        }
        result = score_layout_fit(row)
        self.assertEqual(result["score"], 35)
        self.assertIn("ordered", result["suggestion"])

    def test_check_plan_emits_layout_fit_advisory_with_replacement_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = _seed_project(Path(tmp))
            scaffold_project(project)
            layout_path = project / "layout_plan.json"
            layout = json.loads(layout_path.read_text(encoding="utf-8"))
            layout[0]["page_schema"]["layout_variant"] = "flywheel/default"
            layout_path.write_text(json.dumps(layout), encoding="utf-8")
            issues = validate_plan(project)
            finding = next(item for item in issues if item["code"] == "layout-fit-score-low")
            self.assertEqual(finding["severity"], "advisory")
            self.assertIn("linear process", finding["message"])

    def test_scaffold_writes_four_marked_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = _seed_project(Path(tmp))
            written = scaffold_project(project)
            names = {p.name for p in written}
            self.assertEqual(
                names,
                {
                    "content_model.json",
                    "layout_plan.json",
                    "art_direction.json",
                    "visual_profile.json",
                },
            )
            markers = find_scaffold_markers(project)
            self.assertEqual(
                set(markers),
                {
                    "content_model.json",
                    "layout_plan.json",
                    "art_direction.json",
                    "visual_profile.json",
                },
            )

    def test_layout_rows_reference_existing_claims_and_anchor_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = _seed_project(Path(tmp))
            scaffold_project(project)
            layout = json.loads((project / "layout_plan.json").read_text(encoding="utf-8"))
            content = json.loads((project / "content_model.json").read_text(encoding="utf-8"))
            art = json.loads((project / "art_direction.json").read_text(encoding="utf-8"))
            claim_ids = {c["id"] for c in content["claims"]}
            slide_ids = {row["slide_id"] for row in layout}
            for row in layout:
                for cid in row["claim_ids"]:
                    self.assertIn(cid, claim_ids)
            for anchor in art["anchor_slide_ids"]:
                self.assertIn(anchor, slide_ids)

    def test_check_plan_passes_with_only_advisory_scaffold_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = _seed_project(Path(tmp))
            scaffold_project(project)
            issues = validate_plan(project)
            blocking = [i for i in issues if i.get("severity") != "advisory"]
            self.assertEqual(blocking, [], msg=f"unexpected blocking plan issues: {blocking}")
            self.assertTrue(any(i["code"] == "plan-draft-not-finalized" for i in issues))

    def test_scaffold_markers_block_release_contract_until_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = _seed_project(Path(tmp))
            scaffold_project(project)
            issues = validate_project_contract(project, workflow_mode="strict")
            self.assertTrue(any(i["code"] == "plan-draft-not-finalized" for i in issues))

            # Clearing every scaffold marker removes the release blocker.
            for name in ("content_model.json", "layout_plan.json", "art_direction.json", "visual_profile.json"):
                path = project / name
                payload = json.loads(path.read_text(encoding="utf-8"))
                _strip_markers(payload)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.assertEqual(find_scaffold_markers(project), [])
            cleared = validate_project_contract(project, workflow_mode="strict")
            self.assertFalse(
                any(i["code"] == "plan-draft-not-finalized" for i in cleared),
                msg=f"marker still detected after clearing: {cleared}",
            )

    def test_refined_content_is_protected_from_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = _seed_project(Path(tmp))
            scaffold_project(project)
            content = project / "content_model.json"
            payload = json.loads(content.read_text(encoding="utf-8"))
            _strip_markers(payload)
            content.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            with self.assertRaises(ScaffoldError):
                scaffold_project(project)
            # --force overrides the guard.
            scaffold_project(project, force=True)

    def test_scaffold_requires_confirmed_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            (project / "sources").mkdir(parents=True)
            (project / "confirmation.json").write_text(
                json.dumps({"schema": "ghb.confirmation.v1", "decisions": {"outline": []}}),
                encoding="utf-8",
            )
            with self.assertRaises(ScaffoldError):
                scaffold_project(project)


def _strip_markers(payload: object) -> None:
    if isinstance(payload, dict):
        payload.pop("needs_review", None)
        payload.pop("draft", None)
        if payload.get("origin") == "scaffold":
            payload.pop("origin", None)
        for value in payload.values():
            _strip_markers(value)
    elif isinstance(payload, list):
        for item in payload:
            _strip_markers(item)


if __name__ == "__main__":
    unittest.main()
