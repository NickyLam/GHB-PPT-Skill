import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.evidence_manifest import (
    DEFAULT_DEPENDENCY_DAG,
    EvidenceItem,
    canonical_digest,
    create_manifest,
    evaluate_freshness,
    write_manifest_atomic,
)


def evidence_items(root: Path) -> list[EvidenceItem]:
    files = {}
    for identity in DEFAULT_DEPENDENCY_DAG:
        path = root / f"{identity}.bin"
        path.write_bytes(f"bytes:{identity}".encode())
        files[identity] = path
    return [
        EvidenceItem(
            identity=identity,
            kind=identity,
            semantic={"schema": f"ghb.{identity}.v1", "threshold": 0.5},
            content=files[identity],
        )
        for identity in DEFAULT_DEPENDENCY_DAG
    ]


class CanonicalDigestTest(unittest.TestCase):
    def test_json_key_order_is_equivalent(self):
        left = {"schema": "v1", "policy": {"max": 0.8, "min": 0.4}}
        right = {"policy": {"min": 0.4, "max": 0.8}, "schema": "v1"}
        self.assertEqual(canonical_digest(left), canonical_digest(right))

    def test_volatile_metadata_and_absolute_paths_do_not_change_digest(self):
        left = {
            "schema": "v1",
            "generated_at": "2026-07-14T08:00:00Z",
            "run_dir": "/tmp/run-a",
            "output_path": "output/a/report.json",
            "renderer": {"binary": "/Applications/LibreOffice.app/soffice", "dpi": 144},
        }
        right = {
            "schema": "v1",
            "generated_at": "2027-01-01T00:00:00Z",
            "run_dir": "/var/tmp/run-b",
            "output_path": "elsewhere/report.json",
            "renderer": {"binary": "/opt/libreoffice/soffice", "dpi": 144},
        }
        self.assertEqual(canonical_digest(left), canonical_digest(right))

    def test_schema_and_threshold_changes_are_semantic(self):
        base = {"schema": "ghb.visual-profile.v1", "threshold": {"max": 0.8}}
        self.assertNotEqual(canonical_digest(base), canonical_digest({**base, "schema": "ghb.visual-profile.v2"}))
        self.assertNotEqual(
            canonical_digest(base),
            canonical_digest({**base, "threshold": {"max": 0.75}}),
        )


class EvidenceFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.items = evidence_items(self.root)
        self.manifest = create_manifest(
            project_id="demo-project",
            run_id="run-001",
            items=self.items,
        )

    def tearDown(self):
        self.temp.cleanup()

    def evaluate(self, items=None, **overrides):
        return evaluate_freshness(
            self.manifest,
            project_id=overrides.get("project_id", "demo-project"),
            run_id=overrides.get("run_id", "run-001"),
            current_items=self.items if items is None else items,
        )

    def test_complete_unchanged_dag_is_fresh(self):
        result = self.evaluate()
        self.assertTrue(result.fresh)
        self.assertEqual(set(result.states.values()), {"fresh"})
        self.assertEqual(result.issues, ())

    def test_manifest_record_order_is_canonical(self):
        reverse_manifest = create_manifest(
            project_id="demo-project",
            run_id="run-001",
            items=reversed(self.items),
        )
        self.assertEqual(reverse_manifest, self.manifest)

    def test_profile_change_invalidates_exact_downstream_nodes(self):
        changed = [
            replace(item, semantic={**item.semantic, "threshold": 0.7})
            if item.identity == "visual-profile"
            else item
            for item in self.items
        ]
        result = self.evaluate(changed)
        stale = {identity for identity, state in result.states.items() if state == "stale"}
        self.assertEqual(
            stale,
            {
                "visual-profile",
                "authored-svg-bundle",
                "finalized-svg-bundle",
                "deterministic-report",
                "pptx",
                "render-evidence",
                "adapter-review",
                "final-report",
            },
        )
        self.assertNotIn("layout-plan", stale)
        self.assertNotIn("render-environment", stale)
        self.assertNotIn("adapter-policy", stale)

    def test_render_environment_change_does_not_stale_deterministic_report(self):
        changed = [
            replace(item, semantic={**item.semantic, "renderer": "other"})
            if item.identity == "render-environment"
            else item
            for item in self.items
        ]
        stale = {
            identity
            for identity, state in self.evaluate(changed).states.items()
            if state == "stale"
        }
        self.assertEqual(stale, {"render-environment", "render-evidence", "adapter-review", "final-report"})

    def test_same_bytes_at_another_output_path_remain_fresh(self):
        pptx = next(item for item in self.items if item.identity == "pptx")
        assert isinstance(pptx.content, Path)
        relocated = self.root / "another-run" / "deck.pptx"
        relocated.parent.mkdir()
        relocated.write_bytes(pptx.content.read_bytes())
        current = [
            replace(item, content=relocated) if item.identity == "pptx" else item
            for item in self.items
        ]
        self.assertTrue(self.evaluate(current).fresh)

    def test_copy_to_another_project_or_run_is_not_fresh(self):
        project_result = self.evaluate(project_id="other-project")
        run_result = self.evaluate(run_id="run-002")
        self.assertFalse(project_result.fresh)
        self.assertFalse(run_result.fresh)
        self.assertIn("evidence-project-mismatch", project_result.issue_codes)
        self.assertIn("evidence-run-mismatch", run_result.issue_codes)

    def test_missing_dependency_and_byte_mismatch_are_visible(self):
        without_layout = [item for item in self.items if item.identity != "layout-plan"]
        missing = self.evaluate(without_layout)
        self.assertIn("evidence-missing-current-item", missing.issue_codes)
        self.assertEqual(missing.states["layout-plan"], "stale")
        self.assertEqual(missing.states["final-report"], "stale")

        svg = next(item for item in self.items if item.identity == "authored-svg-bundle")
        assert isinstance(svg.content, Path)
        svg.content.write_bytes(b"changed-svg-bytes")
        mismatched = self.evaluate()
        self.assertIn("evidence-byte-digest-mismatch", mismatched.issue_codes)
        self.assertEqual(mismatched.states["authored-svg-bundle"], "stale")
        self.assertEqual(mismatched.states["final-report"], "stale")

    def test_authored_and_finalized_svg_evidence_have_distinct_dependencies(self):
        self.assertNotIn("svg-bundle", DEFAULT_DEPENDENCY_DAG)
        self.assertEqual(
            DEFAULT_DEPENDENCY_DAG["authored-svg-bundle"],
            ("visual-profile", "art-direction", "layout-plan", "rule-contract"),
        )
        self.assertEqual(
            DEFAULT_DEPENDENCY_DAG["finalized-svg-bundle"],
            ("authored-svg-bundle",),
        )
        self.assertEqual(
            DEFAULT_DEPENDENCY_DAG["pptx"],
            ("finalized-svg-bundle",),
        )

    def test_unknown_version_cycle_duplicate_and_dependency_mismatch_have_stable_codes(self):
        unknown = {**self.manifest, "schema": "ghb.evidence-manifest.v3"}
        self.assertIn(
            "evidence-unknown-manifest-version",
            evaluate_freshness(
                unknown,
                project_id="demo-project",
                run_id="run-001",
                current_items=self.items,
            ).issue_codes,
        )

        duplicate = json.loads(json.dumps(self.manifest))
        duplicate["evidence"].append(dict(duplicate["evidence"][0]))
        self.assertIn(
            "evidence-duplicate-identity",
            evaluate_freshness(
                duplicate,
                project_id="demo-project",
                run_id="run-001",
                current_items=self.items,
            ).issue_codes,
        )

        cycle = json.loads(json.dumps(self.manifest))
        by_id = {item["identity"]: item for item in cycle["evidence"]}
        by_id["visual-profile"]["depends_on"] = ["final-report"]
        self.assertIn(
            "evidence-dependency-cycle",
            evaluate_freshness(
                cycle,
                project_id="demo-project",
                run_id="run-001",
                current_items=self.items,
            ).issue_codes,
        )

        dependency_mismatch = json.loads(json.dumps(self.manifest))
        by_id = {item["identity"]: item for item in dependency_mismatch["evidence"]}
        by_id["pptx"]["depends_on"] = []
        mismatch_result = evaluate_freshness(
            dependency_mismatch,
            project_id="demo-project",
            run_id="run-001",
            current_items=self.items,
        )
        self.assertIn(
            "evidence-dependency-mismatch",
            mismatch_result.issue_codes,
        )

        missing_dependency = json.loads(json.dumps(self.manifest))
        by_id = {item["identity"]: item for item in missing_dependency["evidence"]}
        by_id["pptx"]["depends_on"] = ["missing-svg"]
        missing_result = evaluate_freshness(
            missing_dependency,
            project_id="demo-project",
            run_id="run-001",
            current_items=self.items,
        )
        self.assertIn(
            "evidence-missing-dependency",
            missing_result.issue_codes,
        )

    def test_atomic_writer_round_trips_manifest(self):
        output = self.root / "run" / "evidence-manifest.json"
        write_manifest_atomic(output, self.manifest)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), self.manifest)
        self.assertFalse(any(output.parent.glob(f".{output.name}.*.tmp")))


if __name__ == "__main__":
    unittest.main()
