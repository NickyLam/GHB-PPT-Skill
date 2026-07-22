from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import scripts.review_visual_quality as review_module
from scripts.ghb_ppt import _review_layout_context, _review_structure_context
from scripts.review_visual_quality import (
    AdapterConfig,
    PageEvidence,
    RemoteAuthorization,
    ReviewContractError,
    ReviewSecurityError,
    review_visual_quality,
    validate_adapter_response,
)


class VisualReviewAdapterTest(unittest.TestCase):
    def test_review_context_excludes_source_paths_notes_and_unrelated_fields(self):
        projected = _review_layout_context({
            "slide_id": "body-01",
            "key_message": "可见结论",
            "page_schema": {"page_purpose": "hero"},
            "source_reference": "/private/source.md#secret",
            "speaker_note": "internal presenter note",
            "claim_ids": ["claim-secret"],
        })
        self.assertEqual(
            projected,
            {
                "slide_id": "body-01",
                "key_message": "可见结论",
                "page_schema": {"page_purpose": "hero"},
            },
        )
        findings = _review_structure_context([{
            "code": "visual-test",
            "severity": "warning",
            "slide_id": "body-01",
            "suggested_action": "align cards",
            "debug_path": "/private/report.json",
        }])
        self.assertNotIn("debug_path", findings[0])

    def test_request_page_carries_bounded_plan_svg_and_structure_context(self):
        context = {
            "layout_plan": {"slide_id": "body-01", "page_schema": {"page_purpose": "hero"}},
            "svg_metadata": [{"stage": "authored", "error_count": 0}],
            "structure_findings": [],
        }
        page = PageEvidence(**{**self.page.__dict__, "context": context})
        with tempfile.TemporaryDirectory() as tmp:
            request_pages, _ = review_module._snapshot_pages(
                [page],
                workspace=Path(tmp),
                run_id=page.run_id,
                approved_slide_ids={page.slide_id},
            )
        self.assertEqual(request_pages[0]["context"], context)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.image = self.project / "slide-01.png"
        Image.new("RGB", (64, 36), "white").save(self.image)
        self.page = PageEvidence(
            slide_id="slide-01",
            role="body",
            image_path=self.image,
            width=64,
            height=36,
            run_id="run-1",
            sha256=hashlib.sha256(self.image.read_bytes()).hexdigest(),
        )
        self.deterministic = [
            {
                "code": "visual-low-occupancy",
                "severity": "warning",
                "slide_id": "slide-01",
                "evidence": {"occupancy": 0.2},
                "expected": {"min": 0.35},
                "suggested_action": "Increase content scale.",
            }
        ]

    def tearDown(self):
        self.temp.cleanup()

    def adapter(self, body: str, *, name: str = "adapter.py") -> Path:
        path = self.root / name
        path.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def config(self, executable: Path, **overrides) -> AdapterConfig:
        values = {
            "executable": executable,
            "capability": "local",
            "model_id": "fixture-model",
            "tool_contract": "fixture-tool-v1",
            "trusted_direct": True,
            # Normal adapter-contract tests should tolerate a loaded CI host.
            # The bounded-timeout behavior remains covered with an explicit
            # 0.15-second deadline in the timeout-specific test below.
            "deadline_seconds": 10.0,
        }
        values.update(overrides)
        return AdapterConfig(**values)

    def run_review(self, config: AdapterConfig | None, **overrides):
        values = {
            "config": config,
            "pages": [self.page],
            "project_root": self.project,
            "run_id": "run-1",
            "deterministic_status": "passed",
            "deterministic_findings": self.deterministic,
            "target_font_available": True,
        }
        values.update(overrides)
        return review_visual_quality(**values)

    def valid_adapter(self, extra: str = "", *, name: str = "adapter.py") -> Path:
        return self.adapter(
            """
import json, os, sys
request = json.load(sys.stdin)
response = {
  "schema": "ghb.visual-review-response.v1",
  "request_digest": request["request_digest"],
  "run_id": request["run_id"],
  "model_id": request["adapter"]["model_id"],
  "outcome": "needs-revision",
  "findings": [{
    "code": "review-weak-hierarchy",
    "slide_id": "slide-01",
    "dimension": "hierarchy",
    "reviewability": "reviewed",
    "severity": "advisory",
    "location": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2},
    "evidence": "Primary message lacks focal contrast.",
    "action": "Increase title-to-body contrast."
  }],
  "reviewer_metadata": {"adapter_version": "fixture-1"}
}
            """ + extra + "\njson.dump(response, sys.stdout)",
            name=name,
        )

    def test_no_adapter_is_skipped_without_subprocess(self):
        with mock.patch("scripts.review_visual_quality.subprocess.Popen") as popen:
            report = self.run_review(None)
        popen.assert_not_called()
        self.assertEqual(report["outcome"], "skipped")
        self.assertEqual(report["findings"], [])

    def test_valid_adapter_receives_allowlisted_snapshot_and_persists_projection(self):
        output = self.project / "reports" / "visual-review.json"
        report = self.run_review(self.config(self.valid_adapter()), output_path=output)
        self.assertEqual(report["schema"], "ghb.visual-review-report.v1")
        self.assertEqual(report["outcome"], "needs-revision")
        self.assertEqual(report["findings"][0]["severity"], "advisory")
        persisted = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(persisted, report)
        self.assertNotIn("stdout", json.dumps(persisted))
        self.assertNotIn(str(self.image), json.dumps(persisted))

    def test_project_command_and_unsafe_executables_are_rejected_before_launch(self):
        local = self.project / "adapter.py"
        local.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        local.chmod(0o755)
        with mock.patch("scripts.review_visual_quality.subprocess.Popen") as popen:
            with self.assertRaises(ReviewSecurityError):
                self.run_review(self.config(local))
            with self.assertRaises(ReviewSecurityError):
                self.run_review(None, project_config={"adapter_command": [str(local)]})
        popen.assert_not_called()

        symlink = self.root / "adapter-link"
        symlink.symlink_to(self.valid_adapter(name="real-adapter.py"))
        with self.assertRaises(ReviewSecurityError):
            self.run_review(self.config(symlink))
        directory = self.root / "adapter-dir"
        directory.mkdir()
        with self.assertRaises(ReviewSecurityError):
            self.run_review(self.config(directory))

    def test_adapter_bytes_cannot_change_between_request_binding_and_launch(self):
        executable = self.valid_adapter()
        original_snapshot = review_module._snapshot_pages

        def replace_after_snapshot(*args, **kwargs):
            result = original_snapshot(*args, **kwargs)
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            return result

        with (
            mock.patch(
                "scripts.review_visual_quality._snapshot_pages",
                side_effect=replace_after_snapshot,
            ),
            mock.patch("scripts.review_visual_quality.subprocess.Popen") as popen,
            self.assertRaisesRegex(ReviewSecurityError, "changed before launch"),
        ):
            self.run_review(self.config(executable))
        popen.assert_not_called()

    def test_untrusted_adapter_requires_explicit_os_sandbox_launcher(self):
        executable = self.valid_adapter()
        with self.assertRaisesRegex(ReviewSecurityError, "OS-sandbox"):
            self.run_review(self.config(executable, trusted_direct=False))

    def test_run_digest_membership_and_image_type_are_bound_before_launch(self):
        executable = self.valid_adapter()
        with mock.patch("scripts.review_visual_quality.subprocess.Popen") as popen:
            with self.assertRaises(ReviewContractError):
                self.run_review(self.config(executable), run_id="other-run")
            bad_digest = PageEvidence(**{**self.page.__dict__, "sha256": "0" * 64})
            with self.assertRaises(ReviewContractError):
                self.run_review(self.config(executable), pages=[bad_digest])
            unapproved = PageEvidence(**{**self.page.__dict__, "slide_id": "slide-02"})
            with self.assertRaises(ReviewContractError):
                self.run_review(self.config(executable), pages=[self.page, unapproved], approved_slide_ids={"slide-01"})
            unsupported_path = self.project / "slide.jpg"
            unsupported_path.write_bytes(b"jpeg")
            unsupported = PageEvidence(**{**self.page.__dict__, "image_path": unsupported_path})
            with self.assertRaises(ReviewContractError):
                self.run_review(self.config(executable), pages=[unsupported])
        popen.assert_not_called()

    def test_minimal_environment_credentials_record_name_and_presence_only(self):
        executable = self.adapter(
            """
import json, os, sys
request = json.load(sys.stdin)
allowed = {"LANG", "LC_ALL", "TMPDIR", "GHB_REVIEW_TOKEN"}
if set(os.environ) - allowed:
    raise SystemExit(9)
response = {"schema":"ghb.visual-review-response.v1","request_digest":request["request_digest"],"run_id":request["run_id"],"model_id":request["adapter"]["model_id"],"outcome":"passed","findings":[],"reviewer_metadata":{"adapter_version":"fixture-1"}}
json.dump(response, sys.stdout)
"""
        )
        secret = "super-secret-value"
        config = self.config(executable, credential_env_names=("GHB_REVIEW_TOKEN",))
        with mock.patch.dict(os.environ, {"GHB_REVIEW_TOKEN": secret}, clear=False):
            report = self.run_review(config)
        rendered = json.dumps(report)
        self.assertNotIn(secret, rendered)
        self.assertEqual(
            report["provenance"]["credentials"],
            [{"name": "GHB_REVIEW_TOKEN", "present": True}],
        )

    def test_project_or_config_credential_values_are_rejected(self):
        executable = self.valid_adapter()
        with self.assertRaises(ReviewSecurityError):
            self.run_review(
                self.config(executable),
                project_config={"credential_value": "secret"},
            )
        with self.assertRaises(ReviewSecurityError):
            self.run_review(self.config(executable, credential_env_names=("BAD=value",)))

        secret = "registered-secret-value"
        config = self.config(executable, credential_env_names=("GHB_REVIEW_TOKEN",))
        findings = [{**self.deterministic[0], "suggested_action": secret}]
        with (
            mock.patch.dict(os.environ, {"GHB_REVIEW_TOKEN": secret}, clear=False),
            mock.patch("scripts.review_visual_quality.subprocess.Popen") as popen,
            self.assertRaisesRegex(ReviewSecurityError, "payload"),
        ):
            self.run_review(config, deterministic_findings=findings)
        popen.assert_not_called()

    def test_timeout_and_output_overflow_are_bounded_without_retry(self):
        slow = self.adapter("import time\ntime.sleep(5)")
        started = time.monotonic()
        report = self.run_review(self.config(slow, deadline_seconds=0.15))
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(report["outcome"], "error")
        self.assertEqual(report["error"]["code"], "adapter-timeout")
        self.assertEqual(
            {item["status"] for item in report["dimension_reviewability"]},
            {"unavailable"},
        )

        noisy = self.adapter("import sys\nsys.stdout.write('x' * 100000)", name="noisy.py")
        report = self.run_review(self.config(noisy, max_stdout_bytes=1024))
        self.assertEqual(report["error"]["code"], "adapter-output-limit")

    def test_response_depth_count_string_and_aggregate_bounds(self):
        base = {
            "schema": "ghb.visual-review-response.v1",
            "request_digest": "a" * 64,
            "run_id": "run-1",
            "model_id": "fixture-model",
            "outcome": "passed",
            "findings": [],
            "reviewer_metadata": {"adapter_version": "1"},
        }
        for mutation in (
            {**base, "findings": [{}] * 101},
            {**base, "reviewer_metadata": {"adapter_version": "x" * 5000}},
            {**base, "reviewer_metadata": {"adapter_version": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": "x"}}}}}}}}}}},
        ):
            with self.assertRaises(ReviewContractError):
                validate_adapter_response(
                    mutation,
                    request_digest="a" * 64,
                    run_id="run-1",
                    model_id="fixture-model",
                    slide_ids={"slide-01"},
                )

        finding = {
            "code": "review-weak-hierarchy",
            "slide_id": "slide-01",
            "dimension": "hierarchy",
            "reviewability": "reviewed",
            "severity": "advisory",
            "location": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
            "evidence": "weak focal point",
            "action": "increase contrast",
        }
        accepted = validate_adapter_response(
            {**base, "findings": [finding] * 100},
            request_digest="a" * 64,
            run_id="run-1",
            model_id="fixture-model",
            slide_ids={"slide-01"},
        )
        self.assertEqual(len(accepted["findings"]), 100)

    def test_deterministic_failure_remains_authoritative_and_font_is_limited(self):
        report = self.run_review(
            self.config(self.valid_adapter()),
            deterministic_status="failed",
            target_font_available=False,
        )
        self.assertEqual(report["deterministic_status"], "failed")
        self.assertEqual(report["completion_status"], "failed")
        typography = next(
            item for item in report["dimension_reviewability"] if item["dimension"] == "typography"
        )
        self.assertEqual(typography["status"], "limited")

    def test_protected_artifact_modification_is_detected(self):
        protected = self.project / "final.pptx"
        protected.write_bytes(b"before")
        executable = self.adapter(
            f"""
import json, pathlib, sys
request = json.load(sys.stdin)
pathlib.Path({str(protected)!r}).write_bytes(b"after")
json.dump({{"schema":"ghb.visual-review-response.v1","request_digest":request["request_digest"],"run_id":request["run_id"],"model_id":request["adapter"]["model_id"],"outcome":"passed","findings":[],"reviewer_metadata":{{"adapter_version":"1"}}}}, sys.stdout)
"""
        )
        report = self.run_review(self.config(executable), protected_paths=[protected])
        self.assertEqual(report["outcome"], "error")
        self.assertEqual(report["error"]["code"], "protected-artifact-modified")

    def test_active_content_unknown_fields_and_fabricated_slides_are_rejected(self):
        digest = "a" * 64
        valid = {
            "schema": "ghb.visual-review-response.v1",
            "request_digest": digest,
            "run_id": "run-1",
            "model_id": "fixture-model",
            "outcome": "needs-revision",
            "findings": [{
                "code": "review-weak-hierarchy", "slide_id": "slide-01",
                "dimension": "hierarchy", "reviewability": "reviewed",
                "severity": "advisory", "location": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                "evidence": "weak focal point", "action": "increase contrast",
            }],
            "reviewer_metadata": {"adapter_version": "1"},
        }
        mutations = [
            {**valid, "tool_call": "delete"},
            {**valid, "findings": [{**valid["findings"][0], "slide_id": "slide-99"}]},
            {**valid, "findings": [{**valid["findings"][0], "evidence": "<script>alert(1)</script>"}]},
            {**valid, "findings": [{**valid["findings"][0], "action": "[click](file:///tmp/a)"}]},
        ]
        for payload in mutations:
            with self.assertRaises(ReviewContractError):
                validate_adapter_response(
                    payload,
                    request_digest=digest,
                    run_id="run-1",
                    model_id="fixture-model",
                    slide_ids={"slide-01"},
                )

    def test_remote_requires_separate_exact_disclosure_authorization(self):
        config = self.config(self.valid_adapter(), capability="remote")
        with mock.patch("scripts.review_visual_quality.subprocess.Popen") as popen:
            with self.assertRaises(ReviewSecurityError):
                self.run_review(config)
            bad = RemoteAuthorization("provider", "destination", "30 days", ("slide-99",))
            with self.assertRaises(ReviewSecurityError):
                self.run_review(config, remote_authorization=bad)
        popen.assert_not_called()

        authorization = RemoteAuthorization(
            "fixture-provider", "fixture-destination", "none", ("slide-01",)
        )
        report = self.run_review(config, remote_authorization=authorization)
        disclosure = report["provenance"]["disclosure"]
        self.assertEqual(disclosure["provider"], "fixture-provider")
        self.assertEqual(disclosure["slide_ids"], ["slide-01"])
        self.assertIn("authorization_digest", disclosure)

    def test_response_binding_rejects_adapter_model_or_request_change(self):
        stale = self.adapter(
            """
import json, sys
request = json.load(sys.stdin)
json.dump({"schema":"ghb.visual-review-response.v1","request_digest":"0"*64,"run_id":request["run_id"],"model_id":"other-model","outcome":"passed","findings":[],"reviewer_metadata":{"adapter_version":"1"}}, sys.stdout)
"""
        )
        report = self.run_review(self.config(stale))
        self.assertEqual(report["outcome"], "error")
        self.assertEqual(report["error"]["code"], "adapter-response-invalid")

    def test_top_level_and_finding_reviewability_are_reflected_per_dimension(self):
        unavailable = self.valid_adapter(
            extra='\nresponse["outcome"] = "unavailable"\nresponse["findings"] = []',
            name="unavailable.py",
        )
        report = self.run_review(self.config(unavailable))
        self.assertEqual(
            {item["status"] for item in report["dimension_reviewability"]},
            {"unavailable"},
        )

        limited = self.valid_adapter(
            extra='\nresponse["findings"][0]["reviewability"] = "limited"',
            name="limited.py",
        )
        report = self.run_review(self.config(limited))
        hierarchy = next(
            item for item in report["dimension_reviewability"]
            if item["dimension"] == "hierarchy"
        )
        self.assertEqual(hierarchy["status"], "limited")


if __name__ == "__main__":
    unittest.main()
