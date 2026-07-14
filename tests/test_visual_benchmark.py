from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "tests" / "fixtures" / "visual_quality_cases.json"
PREFERENCES_PATH = ROOT / "tests" / "fixtures" / "visual_preferences.json"
BUILDER_PATH = ROOT / "tests" / "fixtures" / "build_visual_benchmark.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("ghb_visual_benchmark", BUILDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VisualBenchmarkContractTest(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        self.preferences = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))

    def test_corpus_is_stratified_and_partitioned(self):
        cases = self.corpus["cases"]
        self.assertGreaterEqual(len(cases), 30)
        self.assertEqual(len({case["case_id"] for case in cases}), len(cases))
        expected_purposes = {
            "architecture", "process", "comparison", "timeline", "metrics", "summary"
        }
        self.assertEqual({case["page_purpose"] for case in cases}, expected_purposes)
        source_ids = {
            (case["source"]["scenario_id"], case["source"]["body_slide_index"])
            for case in cases
        }
        self.assertEqual(len(source_ids), len(cases), "semantic sources must not leak across partitions")

        by_purpose = defaultdict(Counter)
        for case in cases:
            by_purpose[case["page_purpose"]][case["partition"]] += 1
            self.assertIn(case["density"], {"breathing", "anchor", "dense"})
            self.assertIn(case["content_length_band"], {"short", "medium", "long"})
            self.assertIn(case["item_count_band"], {"few", "standard", "many"})
            self.assertEqual(case["source"]["scenario_file"], "tests/fixtures/scenarios.json")
            self.assertIn("renderer", case["pre_change_evidence"]["provenance"])
            self.assertIn("dpi", case["pre_change_evidence"]["provenance"])
            self.assertIn("fonts", case["pre_change_evidence"]["provenance"])
            self.assertEqual(len(case["pre_change_evidence"]["authored_svg_sha256"]), 64)
            self.assertIsNone(case["pre_change_evidence"]["rendered_png"])
            self.assertEqual(
                case["pre_change_evidence"]["render_status"],
                "unavailable-without-render",
            )
        for purpose in expected_purposes:
            self.assertGreaterEqual(by_purpose[purpose]["calibration"], 2)
            self.assertGreaterEqual(by_purpose[purpose]["pilot-holdout"], 1)
            self.assertGreaterEqual(by_purpose[purpose]["final-holdout"], 2)
        self.assertEqual({case["density"] for case in cases}, {"breathing", "anchor", "dense"})
        self.assertEqual({case["content_length_band"] for case in cases}, {"short", "medium", "long"})
        self.assertEqual({case["item_count_band"] for case in cases}, {"few", "standard", "many"})

    def test_partition_digest_and_consumer_views_are_frozen(self):
        module = load_builder()
        module.validate_contracts(self.corpus, self.preferences)
        self.assertEqual(
            module.partition_digest(self.corpus["cases"]),
            self.corpus["partition_assignment_sha256"],
        )
        tuning = module.cases_for_consumer(self.corpus, "tuning")
        pilot = module.cases_for_consumer(self.corpus, "u11-pilot")
        final = module.cases_for_consumer(self.corpus, "final-evaluation")
        self.assertEqual({case["partition"] for case in tuning}, {"calibration"})
        self.assertEqual({case["partition"] for case in pilot}, {"pilot-holdout"})
        self.assertEqual({case["partition"] for case in final}, {"final-holdout"})
        with self.assertRaisesRegex(ValueError, "unknown benchmark consumer"):
            module.cases_for_consumer(self.corpus, "renderer")

    def test_builder_refuses_to_overwrite_and_needs_no_secret(self):
        module = load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "frozen"
            result = module.build(output, self.corpus, self.preferences)
            self.assertEqual(result["case_count"], len(self.corpus["cases"]))
            manifest = json.loads((output / "benchmark-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["network"], "disabled-not-required")
            self.assertEqual(manifest["model_adapter"], "not-used")
            self.assertEqual(manifest["credentials"], "not-used")
            self.assertEqual(len(manifest["generated_authored_svg"]), len(self.corpus["cases"]))
            self.assertEqual(len(list((output / "authored-svg").glob("*.svg"))), len(self.corpus["cases"]))
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                module.build(output, self.corpus, self.preferences)

    def test_source_identity_reuse_is_rejected(self):
        module = load_builder()
        changed = json.loads(json.dumps(self.corpus))
        changed["cases"][1]["source"] = dict(changed["cases"][0]["source"])
        with self.assertRaisesRegex(ValueError, "source identity"):
            module.validate_contracts(changed, self.preferences)

    def test_blind_review_protocol_and_frozen_false_positive_denominator(self):
        protocol = self.preferences["blind_review_protocol"]
        self.assertTrue(protocol["pair_order_randomized"])
        self.assertTrue(protocol["identity_anonymized"])
        self.assertGreaterEqual(protocol["minimum_independent_eligible_reviewers_per_page"], 3)
        self.assertEqual(protocol["tie_handling"], "exclude-from-preference-denominator")
        self.assertEqual(protocol["abstention_handling"], "exclude-from-preference-denominator")
        self.assertEqual(protocol["aggregation_order"], ["per-page", "across-pages"])
        self.assertEqual(protocol["structural_regression"], "page-level-veto")
        self.assertTrue(protocol["reject_duplicate_reviewer_page_judgments"])
        self.assertGreaterEqual(protocol["minimum_eligible_non_tie_judgments_per_page"], 2)

        gate = self.preferences["deterministic_pilot_false_positive_gate"]
        self.assertEqual(gate["blocking_false_positive_maximum"], 0)
        self.assertEqual(gate["advisory_false_positive_rate_maximum"], 0.10)
        self.assertEqual(gate["advisory_denominator_count"], len(gate["advisory_rule_case_pairs"]))
        self.assertEqual(len(gate["advisory_rule_case_pairs"]), len(set(gate["advisory_rule_case_pairs"])))
        module = load_builder()
        self.assertEqual(
            module.advisory_denominator_digest(gate["advisory_rule_case_pairs"]),
            gate["advisory_denominator_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
