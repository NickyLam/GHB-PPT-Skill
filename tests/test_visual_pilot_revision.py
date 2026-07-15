from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
CORPUS_PATH = FIXTURES / "visual_pilot_revision_cases.json"
FREEZE_PATH = FIXTURES / "freeze_visual_pilot_revision.py"
FROZEN_DIR = FIXTURES / "visual_pilot_revision_prechange_svg"


def load_freezer():
    spec = importlib.util.spec_from_file_location("freeze_visual_pilot_revision", FREEZE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VisualPilotRevisionTest(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))

    def test_revision_holdout_is_new_and_covers_both_pilot_families(self):
        cases = self.corpus["cases"]
        self.assertEqual(self.corpus["round_id"], "u11-revision-2")
        self.assertEqual({case["page_purpose"] for case in cases}, {"comparison", "timeline", "metrics"})
        self.assertEqual({case["slide"]["layout_type"] for case in cases}, {"matrix", "timeline"})
        scenarios = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
        original_signatures = {
            (slide["key_message"], tuple(slide["items"]))
            for scenario in scenarios.values()
            for slide in scenario["slides"]
        }
        revision_signatures = {
            (case["slide"]["key_message"], tuple(case["slide"]["items"])) for case in cases
        }
        self.assertTrue(revision_signatures.isdisjoint(original_signatures))

    def test_freezer_uses_exact_pre_u11_renderer_and_matches_versioned_svg(self):
        module = load_freezer()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "revision-before"
            manifest = module.build(output, self.corpus)
            self.assertEqual(manifest["pre_change_renderer"]["commit"], "aabfc6a")
            self.assertEqual(len(manifest["generated"]), 3)
            for case in self.corpus["cases"]:
                name = f"{case['case_id']}.svg"
                self.assertEqual((output / name).read_bytes(), (FROZEN_DIR / name).read_bytes())
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                module.build(output, self.corpus)

    def test_digest_drift_is_rejected(self):
        module = load_freezer()
        changed = json.loads(json.dumps(self.corpus))
        changed["cases"][0]["pre_change_evidence"]["authored_svg_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "pre-change SVG digest mismatch"):
                module.build(Path(tmp) / "changed", changed)


if __name__ == "__main__":
    unittest.main()
