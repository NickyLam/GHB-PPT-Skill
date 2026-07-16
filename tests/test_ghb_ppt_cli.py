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
    record_unavailable_render,
    record_review_state,
    timestamped_candidates,
    validation_error_codes,
    build_evidence_items,
    evidence_freshness,
    load_review_config,
    _load_review_authorization,
    run_optional_review,
)
from scripts.validate_project_contract import confirmation_digest, validate_project_contract


class GhbPptCliTest(unittest.TestCase):
    def test_operator_review_config_must_be_explicit_and_outside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            adapter = root / "adapter"
            adapter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            adapter.chmod(0o755)
            payload = {
                "schema": "ghb.visual-review-operator-config.v1",
                "executable": str(adapter),
                "capability": "local",
                "model_id": "fixture-model",
                "tool_contract": "fixture-tool-v1",
                "trusted_direct": True,
                "credential_env_names": ["GHB_REVIEW_TOKEN"],
            }
            outside = root / "review-config.json"
            outside.write_text(json.dumps(payload), encoding="utf-8")
            config, policy = load_review_config(outside, project)
            self.assertEqual(config.credential_env_names, ("GHB_REVIEW_TOKEN",))
            self.assertNotIn(str(outside), json.dumps(policy))
            inside = project / "review-config.json"
            inside.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(PipelineError):
                load_review_config(inside, project)
            config_link = project / "review-config-link.json"
            config_link.symlink_to(outside)
            with self.assertRaises(PipelineError):
                load_review_config(config_link, project)

            for mutation in (
                {**payload, "trusted_direct": "false"},
                {**payload, "launcher_supplies_os_sandbox": "false"},
                {**payload, "deadline_seconds": "credential-value-123"},
            ):
                outside.write_text(json.dumps(mutation), encoding="utf-8")
                with self.assertRaises(PipelineError) as raised:
                    load_review_config(outside, project)
                self.assertNotIn("credential-value-123", str(raised.exception))

            authorization = root / "review-authorization.json"
            authorization.write_text(json.dumps({
                "schema": "ghb.visual-review-disclosure.v1",
                "provider": {"token": "credential-value-123"},
                "destination": "fixture-destination",
                "retention": "none",
                "slide_ids": ["slide-01"],
            }), encoding="utf-8")
            with self.assertRaises(PipelineError) as raised:
                _load_review_authorization(authorization, project)
            self.assertNotIn("credential-value-123", str(raised.exception))
            authorization_link = project / "review-authorization-link.json"
            authorization_link.symlink_to(authorization)
            with self.assertRaises(PipelineError):
                _load_review_authorization(authorization_link, project)

    def test_optional_review_requires_fresh_complete_render_before_adapter_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "reports").mkdir()
            (project / "render").mkdir()
            pptx = project / "final.pptx"
            pptx.write_bytes(b"pptx")
            deterministic = project / "reports" / "quality-pre-render.json"
            deterministic.write_text('{"quality":{"deterministic_outcome":{"status":"passed"}}}', encoding="utf-8")
            run = RunContext(project, "review")
            with mock.patch("scripts.ghb_ppt.review_visual_quality") as adapter:
                result, _policy = run_optional_review(
                    run,
                    pptx=pptx,
                    render_dir=project / "render",
                    deterministic_report=deterministic,
                    config_path=None,
                    authorization_path=None,
                )
            adapter.assert_not_called()
            self.assertEqual(result["outcome"], "unavailable")

    def test_build_review_runs_after_render_before_final_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            events = []
            review_report = {"schema": "ghb.visual-review-report.v1", "outcome": "passed"}
            with (
                mock.patch("scripts.ghb_ppt.check_project_contract"),
                mock.patch("scripts.ghb_ppt.build_cover"),
                mock.patch("scripts.ghb_ppt.build_content"),
                mock.patch("scripts.ghb_ppt.merge_deck"),
                mock.patch("scripts.ghb_ppt.render_deck", side_effect=lambda *a, **k: events.append("render") or project / "render"),
                mock.patch("scripts.ghb_ppt.run_optional_review", side_effect=lambda *a, **k: (events.append("review") or review_report, {"status": "configured"})),
                mock.patch("scripts.ghb_ppt.validate_deck", side_effect=lambda *a, **k: events.append("pre-report" if len([x for x in events if "report" in x]) == 0 and "render" not in events else "final-report") or (project / "a", project / "b")),
                mock.patch.object(RunContext, "checkpoint"),
            ):
                code = main([
                    "build", "--project", str(project), "--review", "--dry-run",
                    "--title", "T", "--subtitle", "S", "--date", "D",
                ])
            self.assertEqual(code, 0)
            self.assertLess(events.index("render"), events.index("review"))
            self.assertLess(events.index("review"), events.index("final-report"))

    def test_required_review_failure_is_reported_after_deterministic_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            events = []
            with (
                mock.patch("scripts.ghb_ppt.check_project_contract"),
                mock.patch("scripts.ghb_ppt.build_cover"),
                mock.patch("scripts.ghb_ppt.build_content"),
                mock.patch("scripts.ghb_ppt.merge_deck"),
                mock.patch("scripts.ghb_ppt.render_deck", return_value=project / "render"),
                mock.patch("scripts.ghb_ppt.run_optional_review", return_value=({"schema":"ghb.visual-review-report.v1","outcome":"error"}, {"status":"configured"})),
                mock.patch("scripts.ghb_ppt.validate_deck", side_effect=lambda *a, **k: events.append("validated") or (project / "a", project / "b")),
                mock.patch.object(RunContext, "checkpoint") as checkpoint,
            ):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    code = main([
                        "build", "--project", str(project), "--review", "--require-review", "--dry-run",
                        "--title", "T", "--subtitle", "S", "--date", "D",
                    ])
            self.assertEqual(code, 1)
            self.assertGreaterEqual(len(events), 2)
            self.assertIn("required optional review", stderr.getvalue())
            checkpoint.assert_not_called()

    def test_report_command_never_accepts_or_launches_review(self):
        parser_error = io.StringIO()
        with contextlib.redirect_stderr(parser_error), self.assertRaises(SystemExit):
            main(["report", "--project", "/tmp/project", "--review-config", "/tmp/config"])
        with mock.patch("scripts.ghb_ppt.review_visual_quality") as adapter:
            code = main(["report", "--project", "/definitely/missing/project"])
        self.assertEqual(code, 1)
        adapter.assert_not_called()

    def test_validate_marks_persisted_review_stale_without_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "reports").mkdir()
            (project / "reports" / "visual-review.json").write_text(
                '{"schema":"ghb.visual-review-report.v1","outcome":"passed"}',
                encoding="utf-8",
            )
            pptx = project / "final.pptx"
            pptx.write_bytes(b"pptx")
            captured = {}

            def validate(_run, **kwargs):
                captured.update(kwargs)
                return kwargs["json_output"], kwargs["markdown_output"]

            with mock.patch("scripts.ghb_ppt.validate_deck", side_effect=validate):
                self.assertEqual(
                    main([
                        "validate", "--project", str(project), "--pptx", str(pptx)
                    ]),
                    0,
                )
            self.assertEqual(captured["freshness"].states["adapter-review"], "stale")

    def test_validate_accepts_manifest_fresh_persisted_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for directory in ("svg_output", "svg_final", "reports", "render", ".ghb"):
                (project / directory).mkdir()
            (project / "visual_profile.json").write_text('{}', encoding="utf-8")
            (project / "layout_plan.json").write_text('[]', encoding="utf-8")
            pptx = project / "final.pptx"
            pptx.write_bytes(b"pptx")
            (project / "reports" / "quality-pre-render.json").write_text(
                '{"passed":true}', encoding="utf-8"
            )
            (project / "reports" / "quality-report.json").write_text(
                '{"passed":true}', encoding="utf-8"
            )
            (project / "reports" / "quality-report.md").write_text(
                "fresh\n", encoding="utf-8"
            )
            (project / "reports" / "visual-review.json").write_text(
                '{"schema":"ghb.visual-review-report.v1","outcome":"passed"}',
                encoding="utf-8",
            )
            (project / ".ghb" / "adapter-policy.json").write_text(
                '{"required":true}', encoding="utf-8"
            )
            (project / "render" / "render-report.json").write_text(
                '{"status":"passed","outputs":[]}', encoding="utf-8"
            )
            from scripts.evidence_manifest import create_manifest, write_manifest_atomic

            manifest = create_manifest(
                project_id=project.name,
                run_id="review-run",
                items=build_evidence_items(
                    project,
                    run_id="review-run",
                    include_final=True,
                    pptx_path=pptx,
                ),
            )
            write_manifest_atomic(project / ".ghb" / "evidence-manifest.json", manifest)
            captured = {}

            def validate(_run, **kwargs):
                captured.update(kwargs)
                return kwargs["json_output"], kwargs["markdown_output"]

            with mock.patch("scripts.ghb_ppt.validate_deck", side_effect=validate):
                self.assertEqual(
                    main([
                        "validate", "--project", str(project), "--pptx", str(pptx)
                    ]),
                    0,
                )
            self.assertEqual(
                captured["freshness"].states["adapter-review"],
                "fresh",
                captured["freshness"],
            )
            self.assertTrue(captured["review_required"])

    def test_report_rejects_render_directory_outside_manifest_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            custom_render = Path(tmp) / "custom-render"
            custom_render.mkdir()
            with mock.patch("scripts.ghb_ppt.validate_deck") as validate:
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    code = main([
                        "report", "--project", str(project),
                        "--render-dir", str(custom_render),
                    ])
            self.assertEqual(code, 1)
            validate.assert_not_called()
            self.assertIn("manifest-bound", stderr.getvalue())

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

    def test_optional_review_state_is_deterministic_without_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = RunContext(Path(tmp), "build")
            self.assertEqual(record_review_state(run, render_available=True), "skipped")
            self.assertEqual(run.record.stages[-1]["implementation"], "absent")
            self.assertEqual(record_review_state(run, render_available=False), "unavailable")

    def test_build_dry_run_preserves_stage_order_without_optional_review_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), mock.patch(
                "scripts.ghb_ppt.review_visual_quality"
            ) as adapter:
                code = main([
                    "build", "--project", str(project), "--dry-run", "--no-render",
                    "--title", "T", "--subtitle", "S", "--date", "D",
                ])
            self.assertEqual(code, 0)
            adapter.assert_not_called()
            output = stdout.getvalue()
            stages = ["project-contract", "analyze-template", "svg-authored", "finalize-svg", "svg-finalized", "merge", "validate"]
            positions = [output.index(f"[DRY-RUN] {stage}:") for stage in stages]
            self.assertEqual(positions, sorted(positions))
            self.assertNotIn("optional-review.py", output)

    def test_checkpoint_records_dependency_digests(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "visual_profile.json").write_text('{"schema":"ghb.visual-profile.v1"}', encoding="utf-8")
            (project / "layout_plan.json").write_text('[]', encoding="utf-8")
            run = RunContext(project, "check-svg")
            run.checkpoint("check-svg", [])
            state = json.loads((project / ".ghb" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["evidence_manifest"]["schema"], "ghb.evidence-manifest.v1")
            identities = {item["identity"] for item in state["evidence_manifest"]["evidence"]}
            self.assertTrue({"visual-profile", "layout-plan", "rule-contract"}.issubset(identities))

    def test_evidence_freshness_propagates_only_to_manifest_dependents(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for directory in ("svg_output", "svg_final", "reports", "exports", "render"):
                (project / directory).mkdir()
            profile_path = project / "visual_profile.json"
            layout_path = project / "layout_plan.json"
            svg_path = project / "svg_output" / "01.svg"
            pptx_path = project / "exports" / "final.pptx"
            render_path = project / "render" / "render-report.json"
            render_page = project / "render" / "slide-01.png"
            profile_path.write_text('{"schema":"ghb.visual-profile.v1","v":1}', encoding="utf-8")
            layout_path.write_text('[]', encoding="utf-8")
            svg_path.write_text('<svg/>', encoding="utf-8")
            pptx_path.write_bytes(b"pptx")
            (project / "reports" / "quality-report.json").write_text('{"passed":true}', encoding="utf-8")
            render_page.write_bytes(b"png")
            render_path.write_text(
                json.dumps({"status": "passed", "dpi": 144, "outputs": [str(render_page)]}),
                encoding="utf-8",
            )
            items = build_evidence_items(project, run_id="run", include_final=True)
            from scripts.evidence_manifest import create_manifest
            manifest = create_manifest(project_id=project.name, run_id="run", items=items)

            cases = [
                (
                    profile_path,
                    '{"schema":"ghb.visual-profile.v1","v":2}',
                    {"visual-profile", "svg-bundle", "pptx", "deterministic-report", "render-evidence", "adapter-review", "final-report"},
                ),
                (
                    layout_path,
                    '[{"slide":1}]',
                    {"layout-plan", "svg-bundle", "pptx", "deterministic-report", "render-evidence", "adapter-review", "final-report"},
                ),
                (
                    svg_path,
                    '<svg><rect/></svg>',
                    {"svg-bundle", "pptx", "deterministic-report", "render-evidence", "adapter-review", "final-report"},
                ),
                (
                    pptx_path,
                    b"changed-pptx",
                    {"pptx", "deterministic-report", "render-evidence", "adapter-review", "final-report"},
                ),
                (
                    render_path,
                    '{"status":"passed","dpi":192}',
                    {"render-environment", "render-evidence", "adapter-review", "final-report"},
                ),
                (
                    render_page,
                    b"changed-png",
                    {"render-evidence", "adapter-review", "final-report"},
                ),
            ]
            for path, replacement, expected in cases:
                original = path.read_bytes()
                try:
                    if isinstance(replacement, bytes):
                        path.write_bytes(replacement)
                    else:
                        path.write_text(replacement, encoding="utf-8")
                    result = evidence_freshness(project, manifest, run_id="run", include_final=True)
                    stale = {identity for identity, state in result.states.items() if state == "stale"}
                    self.assertEqual(stale, expected, path.name)
                finally:
                    path.write_bytes(original)

            with mock.patch("scripts.ghb_ppt.shutil.which", side_effect=lambda name: f"/tools/{name}"):
                environment_manifest = create_manifest(
                    project_id=project.name,
                    run_id="run",
                    items=build_evidence_items(project, run_id="run", include_final=True),
                )
            with mock.patch("scripts.ghb_ppt.shutil.which", return_value=None):
                environment_result = evidence_freshness(
                    project, environment_manifest, run_id="run", include_final=True
                )
            self.assertEqual(
                {identity for identity, state in environment_result.states.items() if state == "stale"},
                {"render-environment", "render-evidence", "adapter-review", "final-report"},
            )

    def test_report_marks_stale_without_render_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for directory in ("svg_output", "svg_final", "reports", "exports", "render", ".ghb"):
                (project / directory).mkdir()
            profile = project / "visual_profile.json"
            profile.write_text('{"schema":"ghb.visual-profile.v1","v":1}', encoding="utf-8")
            (project / "layout_plan.json").write_text('[]', encoding="utf-8")
            (project / "exports" / "final.pptx").write_bytes(b"pptx")
            (project / "reports" / "quality-report.json").write_text('{"passed":true}', encoding="utf-8")
            (project / "render" / "render-report.json").write_text('{"status":"passed","dpi":144}', encoding="utf-8")
            from scripts.evidence_manifest import create_manifest, write_manifest_atomic
            manifest = create_manifest(
                project_id=project.name,
                run_id="original-run",
                items=build_evidence_items(project, run_id="original-run", include_final=True),
            )
            write_manifest_atomic(project / ".ghb" / "evidence-manifest.json", manifest)
            profile.write_text('{"schema":"ghb.visual-profile.v1","v":2}', encoding="utf-8")
            with mock.patch("scripts.ghb_ppt.validate_deck") as validate, mock.patch("scripts.ghb_ppt.render_deck") as render:
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    code = main(["report", "--project", str(project)])
            self.assertEqual(code, 1)
            validate.assert_not_called()
            render.assert_not_called()
            self.assertIn("stale evidence", stderr.getvalue())

    def test_custom_pptx_is_the_manifest_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for directory in ("svg_output", "svg_final", "reports", "exports", "render"):
                (project / directory).mkdir()
            custom_pptx = project / "deliverables" / "board-deck.pptx"
            custom_pptx.parent.mkdir()
            custom_pptx.write_bytes(b"custom-pptx")
            (project / "visual_profile.json").write_text('{}', encoding="utf-8")
            (project / "layout_plan.json").write_text('[]', encoding="utf-8")
            (project / "reports" / "quality-pre-render.json").write_text(
                '{"passed":true}', encoding="utf-8"
            )
            (project / "reports" / "quality-report.json").write_text(
                '{"passed":true}', encoding="utf-8"
            )
            (project / "render" / "render-report.json").write_text(
                '{"status":"passed","dpi":144}', encoding="utf-8"
            )
            from scripts.evidence_manifest import create_manifest

            manifest = create_manifest(
                project_id=project.name,
                run_id="run",
                items=build_evidence_items(
                    project,
                    run_id="run",
                    include_final=True,
                    pptx_path=custom_pptx,
                ),
            )
            custom_pptx.write_bytes(b"changed-custom-pptx")
            result = evidence_freshness(
                project,
                manifest,
                run_id="run",
                include_final=True,
                pptx_path=custom_pptx,
            )
            stale = {identity for identity, state in result.states.items() if state == "stale"}
            self.assertTrue(
                {"pptx", "deterministic-report", "render-evidence", "adapter-review", "final-report"}
                .issubset(stale)
            )

    def test_report_refreshes_manifest_and_can_run_twice_without_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for directory in ("svg_output", "svg_final", "reports", "exports", "render", ".ghb"):
                (project / directory).mkdir()
            (project / "visual_profile.json").write_text('{}', encoding="utf-8")
            (project / "layout_plan.json").write_text('[]', encoding="utf-8")
            (project / "exports" / "final.pptx").write_bytes(b"pptx")
            (project / "reports" / "quality-pre-render.json").write_text(
                '{"passed":true}', encoding="utf-8"
            )
            (project / "reports" / "quality-report.json").write_text(
                '{"quality":{"freshness":{"status":"fresh"}}}', encoding="utf-8"
            )
            (project / "reports" / "quality-report.md").write_text("fresh\n", encoding="utf-8")
            (project / "render" / "render-report.json").write_text(
                '{"status":"passed","dpi":144}', encoding="utf-8"
            )
            seed = RunContext(project, "build")
            seed.checkpoint(
                "build",
                [
                    project / "exports" / "final.pptx",
                    project / "reports" / "quality-report.json",
                    project / "reports" / "quality-report.md",
                ],
            )

            def regenerate(_run, **kwargs):
                kwargs["json_output"].write_text(
                    '{"quality":{"freshness":{"status":"fresh"}}}', encoding="utf-8"
                )
                kwargs["markdown_output"].write_text("fresh\n", encoding="utf-8")
                return kwargs["json_output"], kwargs["markdown_output"]

            with (
                mock.patch("scripts.ghb_ppt.validate_deck", side_effect=regenerate) as validate,
                mock.patch("scripts.ghb_ppt.render_deck") as render,
            ):
                self.assertEqual(main(["report", "--project", str(project)]), 0)
                self.assertEqual(main(["report", "--project", str(project)]), 0)
            self.assertEqual(validate.call_count, 2)
            render.assert_not_called()
            state = json.loads((project / ".ghb" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["last_successful_stage"], "report")

    def test_report_requires_manifest_instead_of_claiming_default_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for directory in ("reports", "exports"):
                (project / directory).mkdir()
            (project / "exports" / "final.pptx").write_bytes(b"pptx")
            with mock.patch("scripts.ghb_ppt.validate_deck") as validate:
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    code = main(["report", "--project", str(project)])
            self.assertEqual(code, 1)
            validate.assert_not_called()
            self.assertIn("evidence manifest not found", stderr.getvalue())

    def test_report_can_rebuild_a_changed_final_report_from_fresh_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for directory in ("svg_output", "svg_final", "reports", "exports", "render", ".ghb"):
                (project / directory).mkdir()
            (project / "visual_profile.json").write_text('{}', encoding="utf-8")
            (project / "layout_plan.json").write_text('[]', encoding="utf-8")
            pptx = project / "exports" / "final.pptx"
            pptx.write_bytes(b"pptx")
            pre = project / "reports" / "quality-pre-render.json"
            pre.write_text('{"passed":true}', encoding="utf-8")
            final_json = project / "reports" / "quality-report.json"
            final_md = project / "reports" / "quality-report.md"
            final_json.write_text('{"version":1}', encoding="utf-8")
            final_md.write_text("version 1\n", encoding="utf-8")
            (project / "render" / "render-report.json").write_text(
                '{"status":"unavailable","outputs":[]}', encoding="utf-8"
            )
            seed = RunContext(project, "build")
            seed.checkpoint("build", [pptx, final_json, final_md], pptx_path=pptx)
            final_json.write_text("not valid json", encoding="utf-8")

            def regenerate(_run, **kwargs):
                kwargs["json_output"].write_text('{"version":2}', encoding="utf-8")
                kwargs["markdown_output"].write_text("version 2\n", encoding="utf-8")
                return kwargs["json_output"], kwargs["markdown_output"]

            with mock.patch("scripts.ghb_ppt.validate_deck", side_effect=regenerate):
                self.assertEqual(main(["report", "--project", str(project)]), 0)
            self.assertEqual(json.loads(final_json.read_text(encoding="utf-8"))["version"], 2)

    def test_custom_report_outputs_are_bound_into_checkpoint_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for directory in ("svg_output", "svg_final", "reports", "exports", "render"):
                (project / directory).mkdir()
            (project / "visual_profile.json").write_text('{}', encoding="utf-8")
            (project / "layout_plan.json").write_text('[]', encoding="utf-8")
            pptx = project / "exports" / "final.pptx"
            pptx.write_bytes(b"pptx")
            (project / "reports" / "quality-pre-render.json").write_text(
                '{"passed":true}', encoding="utf-8"
            )
            custom_json = project / "deliverables" / "review.json"
            custom_md = project / "deliverables" / "review.md"
            custom_json.parent.mkdir()
            custom_json.write_text('{"passed":true}', encoding="utf-8")
            custom_md.write_text("fresh\n", encoding="utf-8")
            (project / "render" / "render-report.json").write_text(
                '{"status":"unavailable","outputs":[]}', encoding="utf-8"
            )
            run = RunContext(project, "report")
            run.checkpoint(
                "report",
                [pptx, custom_json, custom_md],
                pptx_path=pptx,
                final_report_path=custom_json,
                final_markdown_path=custom_md,
            )
            manifest = json.loads(
                (project / ".ghb" / "evidence-manifest.json").read_text(encoding="utf-8")
            )
            custom_md.write_text("changed\n", encoding="utf-8")
            result = evidence_freshness(
                project,
                manifest,
                run_id=manifest["run_id"],
                include_final=True,
                pptx_path=pptx,
                final_report_path=custom_json,
                final_markdown_path=custom_md,
            )
            self.assertEqual(result.states["final-report"], "stale")

    def test_unavailable_render_replaces_old_success_report(self):
        from scripts.render_ghb_pptx import RenderError

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            pptx = project / "new.pptx"
            pptx.write_bytes(b"pptx")
            render_dir = project / "render"
            render_dir.mkdir()
            (render_dir / "render-report.json").write_text(
                '{"status":"passed","outputs":["old.png"]}', encoding="utf-8"
            )
            run = RunContext(project, "build")
            with mock.patch(
                "scripts.render_ghb_pptx.detect_renderer",
                side_effect=RenderError("no renderer"),
            ):
                record_unavailable_render(
                    run, pptx=pptx, output_dir=render_dir, dpi=144
                )
            payload = json.loads(
                (render_dir / "render-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["status"], "unavailable")
            self.assertEqual(payload["pptx"], str(pptx.resolve()))
            self.assertEqual(payload["outputs"], [])


if __name__ == "__main__":
    unittest.main()
