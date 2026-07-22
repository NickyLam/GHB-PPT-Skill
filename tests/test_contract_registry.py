from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "references" / "contracts.md"


class SkillDocumentationContractTest(unittest.TestCase):
    def test_contract_registry_links_all_project_artifacts_from_skill(self):
        registry = CONTRACTS.read_text(encoding="utf-8")
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for artifact in (
            "confirmation.json",
            "content_model.json",
            "art_direction.json",
            "visual_profile.json",
            "layout_plan.json",
            "spec_lock.md",
            "design_spec.md",
            "cover_fill_plan.json",
        ):
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, registry)
                self.assertIn(artifact, skill)

    def test_registered_semantic_markers_and_failure_codes_exist_in_code_or_tests(self):
        registry = CONTRACTS.read_text(encoding="utf-8")
        source = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for directory in (ROOT / "scripts", ROOT / "tests")
            for path in directory.rglob("*.py")
        )
        markers = sorted(set(re.findall(r"`(data-[a-z0-9-]+)(?:=[^`]*)?`", registry)))
        codes = sorted(
            set(
                re.findall(
                    r"`((?:plan|component|header|text|connector|invalid-font|invalid-embedded|font-embed)[a-z0-9-]+)`",
                    registry,
                )
            )
        )
        self.assertGreaterEqual(len(markers), 15)
        self.assertGreaterEqual(len(codes), 10)
        for token in [*markers, *codes]:
            with self.subTest(token=token):
                self.assertIn(token, source)

    def test_docs_index_marks_historical_reports_as_non_authoritative(self):
        index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        self.assertIn("Historical files are evidence snapshots", index)
        self.assertIn("references/contracts.md", index)


if __name__ == "__main__":
    unittest.main()
