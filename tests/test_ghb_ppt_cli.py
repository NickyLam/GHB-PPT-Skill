import contextlib
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts.ghb_ppt import (
    PipelineError,
    RunContext,
    locate_new_timestamped_output,
    main,
    timestamped_candidates,
    validation_error_codes,
)
from scripts.validate_project_contract import confirmation_digest, validate_project_contract


class GhbPptCliTest(unittest.TestCase):
    def test_real_project_requires_six_decision_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            issues = validate_project_contract(project)
            codes = {issue["code"] for issue in issues}
            self.assertIn("missing-confirmation", codes)

    def test_confirmation_rejects_incomplete_six_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "confirmation.json").write_text(
                '{"schema":"ghb.confirmation.v1","status":"confirmed",'
                '"confirmation_source":"user","decisions":{"audience":"技术负责人"}}',
                encoding="utf-8",
            )
            issues = validate_project_contract(project, confirmation_only=True)
            codes = {issue["code"] for issue in issues}
            self.assertIn("incomplete-confirmation", codes)

    def test_fixed_fixture_confirmation_passes_without_user_interaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "confirmation.json").write_text(
                """{
  "schema": "ghb.confirmation.v1",
  "status": "confirmed",
  "confirmation_source": "fixture",
  "confirmed_at": "2026-07-13T00:00:00Z",
  "decisions": {
    "audience": "测试受众",
    "page_range": "6 body slides",
    "mode": "instructional",
    "outline": [{"title": "测试页", "rhythm": "anchor"}],
    "content_tradeoffs": {"expand": [], "omit": [], "combine": []},
    "visual_assets": {"image_source": "none", "icon_set": "none"}
  }
}
""",
                encoding="utf-8",
            )
            payload = json.loads((project / "confirmation.json").read_text(encoding="utf-8"))
            payload["decision_digest"] = confirmation_digest(payload["decisions"])
            (project / "confirmation.json").write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.dict("os.environ", {"GHB_PPT_TEST_FIXTURE": "1"}):
                self.assertEqual(
                    validate_project_contract(project, confirmation_only=True), []
                )

    def test_fixture_source_cannot_bypass_real_project_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "confirmation.json").write_text(
                """{
  "schema":"ghb.confirmation.v1","status":"confirmed",
  "confirmation_source":"fixture","confirmed_at":"2026-07-13T00:00:00Z",
  "decisions":{
    "audience":"管理层","page_range":"1 body slide","mode":"briefing",
    "outline":[{"title":"结论","rhythm":"anchor"}],
    "content_tradeoffs":{"expand":[],"omit":[],"combine":[]},
    "visual_assets":{"image_source":"none","icon_set":"none"}
  }
}
""",
                encoding="utf-8",
            )
            issues = validate_project_contract(project, confirmation_only=True)
            self.assertIn(
                "fixture-confirmation-outside-test-context",
                {item["code"] for item in issues},
            )

    def test_layout_semantics_reject_timeline_without_order_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "layout_plan.json").write_text(
                '[{"slide":1,"layout_archetype":"timeline","items":["能力", "平台"]}]',
                encoding="utf-8",
            )
            issues = validate_project_contract(
                project, confirmation_only=False, skip_required_files=True
            )
            self.assertIn(
                "timeline-missing-order",
                {issue["code"] for issue in issues},
            )
            self.assertIn("incomplete-layout-row", {issue["code"] for issue in issues})

    def test_build_fails_contract_before_writing_cover(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "build", "--project", str(project),
                        "--title", "T", "--subtitle", "S", "--date", "D",
                        "--no-render",
                    ]
                )
            self.assertEqual(code, 1)
            self.assertFalse((project / "exports" / "cover.pptx").exists())
            self.assertIn("project-contract", stderr.getvalue())

    def test_merge_cannot_bypass_project_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                code = main(["merge", "--project", str(project)])
            self.assertEqual(code, 1)
            self.assertFalse((project / "exports" / "final.pptx").exists())
            self.assertIn("project-contract", stderr.getvalue())

    def test_confirmation_outline_must_match_layout_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "confirmation.json").write_text(
                """{
  "schema":"ghb.confirmation.v1","status":"confirmed",
  "confirmation_source":"user","confirmed_at":"2026-07-13T00:00:00Z",
  "decisions":{
    "audience":"管理层","page_range":"1 body slide","mode":"briefing",
    "outline":[{"title":"已确认标题","rhythm":"anchor"}],
    "content_tradeoffs":{"expand":[],"omit":[],"combine":[]},
    "visual_assets":{"image_source":"none","icon_set":"none"}
  }
}
""",
                encoding="utf-8",
            )
            (project / "layout_plan.json").write_text(
                '[{"slide":1,"message":"被改写的标题","layout_archetype":"pyramid","items":["A"]}]',
                encoding="utf-8",
            )
            issues = validate_project_contract(
                project, skip_required_files=True
            )
            self.assertIn("confirmation-plan-drift", {item["code"] for item in issues})

    def test_init_creates_stable_project_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--project", str(project)]), 0)
            for name in ("sources", "analysis", "images", "svg_output", "svg_final", "notes", "exports"):
                self.assertTrue((project / name).is_dir())
            confirmation = json.loads((project / "confirmation.json").read_text(encoding="utf-8"))
            self.assertEqual(confirmation["status"], "pending")
            profile = json.loads((project / "visual_profile.json").read_text(encoding="utf-8"))
            self.assertEqual(profile["schema"], "ghb.visual-profile.v1")
            self.assertEqual(profile["composition"]["default_density"], "balanced")

    def test_init_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--project", str(project), "--dry-run"]), 0)
            self.assertFalse(project.exists())

    def test_check_project_can_explicitly_require_visual_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            stderr = io.StringIO()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main([
                    "check-project", "--project", str(project), "--require-visual-contract"
                ])
            self.assertEqual(code, 1)
            self.assertIn("missing-visual-profile", stdout.getvalue())

    def test_locates_exact_new_timestamped_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            requested = Path(tmp) / "cover.pptx"
            old = Path(tmp) / "cover_20260101_010101.pptx"
            old.touch()
            before = timestamped_candidates(requested)
            created = Path(tmp) / "cover_20260710_120000.pptx"
            created.touch()
            self.assertEqual(locate_new_timestamped_output(requested, before), created.resolve())

    def test_analyze_template_accepts_project_default_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "analyze-template",
                        "--project", str(project),
                        "--dry-run",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("analysis/slide_library.json", stdout.getvalue())

    def test_rejects_ambiguous_or_missing_timestamped_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            requested = Path(tmp) / "cover.pptx"
            with self.assertRaisesRegex(PipelineError, "found 0"):
                locate_new_timestamped_output(requested, set())
            (Path(tmp) / "cover_20260710_120000.pptx").touch()
            (Path(tmp) / "cover_20260710_120001.pptx").touch()
            with self.assertRaisesRegex(PipelineError, "found 2"):
                locate_new_timestamped_output(requested, set())

    def test_missing_project_returns_nonzero_without_traceback(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["check-svg", "--project", "/definitely/missing/ghb-project"])
        self.assertEqual(code, 1)
        self.assertIn("project directory not found", stderr.getvalue())

    def test_doctor_reports_machine_readable_result(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["doctor", "--json"])
        self.assertEqual(code, 0)
        self.assertIn('"dependencies"', stdout.getvalue())
        self.assertIn('"fonts"', stdout.getvalue())
        self.assertIn('"permissions"', stdout.getvalue())

    def test_validation_error_codes_reads_only_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            report.write_text(
                '{"issues":[{"severity":"error","code":"cover-font"},'
                '{"severity":"warning","code":"small-font"}]}',
                encoding="utf-8",
            )
            self.assertEqual(validation_error_codes(report), {"cover-font"})

    def test_build_repair_attempts_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "build", "--project", str(project), "--dry-run",
                        "--title", "T", "--subtitle", "S", "--date", "D",
                        "--repair-attempts", "4",
                    ]
                )
            self.assertEqual(code, 1)
            self.assertIn("between 0 and 3", stderr.getvalue())

    def test_keep_intermediate_is_accepted_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = RunContext(
                Path(tmp),
                "build",
                dry_run=True,
                keep_intermediate=True,
            )
            self.assertTrue(run.record.keep_intermediate)
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "check-svg",
                        "--project", str(Path(tmp)),
                        "--dry-run",
                        "--keep-intermediate",
                    ]
                )
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
