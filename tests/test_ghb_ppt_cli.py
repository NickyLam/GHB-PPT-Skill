import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts.ghb_ppt import (
    PipelineError,
    locate_new_timestamped_output,
    main,
    timestamped_candidates,
)


class GhbPptCliTest(unittest.TestCase):
    def test_init_creates_stable_project_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--project", str(project)]), 0)
            for name in ("sources", "analysis", "images", "svg_output", "svg_final", "notes", "exports"):
                self.assertTrue((project / name).is_dir())

    def test_init_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--project", str(project), "--dry-run"]), 0)
            self.assertFalse(project.exists())

    def test_locates_exact_new_timestamped_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            requested = Path(tmp) / "cover.pptx"
            old = Path(tmp) / "cover_20260101_010101.pptx"
            old.touch()
            before = timestamped_candidates(requested)
            created = Path(tmp) / "cover_20260710_120000.pptx"
            created.touch()
            self.assertEqual(locate_new_timestamped_output(requested, before), created.resolve())

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


if __name__ == "__main__":
    unittest.main()
