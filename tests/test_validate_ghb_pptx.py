from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from scripts.merge_template_master import merge_pptx, parse_rels, relation_type, resolve_target
from scripts.validate_ghb_pptx import main, validate_pptx


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "GHB_PPT_模板.pptx"


def make_cover(path: Path) -> None:
    presentation = Presentation(TEMPLATE)
    slide = presentation.slides[0]
    replacements = ["企业级基线", "离线验证", "2026年7月"]
    index = 0
    for shape in slide.shapes:
        if not getattr(shape, "has_text_frame", False) or not shape.text.strip():
            continue
        shape.text = replacements[min(index, len(replacements) - 1)]
        index += 1
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                run.font.name = "Microsoft YaHei"
    presentation.save(path)


def make_content(path: Path, count: int, *, full_slide_image: bool = False) -> None:
    presentation = Presentation()
    presentation.slide_width = 12192000
    presentation.slide_height = 6858000
    blank = presentation.slide_layouts[6]
    for index in range(count):
        slide = presentation.slides.add_slide(blank)
        if full_slide_image and index == 0:
            image_path = path.with_suffix(".png")
            Image.new("RGB", (1280, 720), "white").save(image_path)
            slide.shapes.add_picture(
                str(image_path), 0, 0,
                width=presentation.slide_width,
                height=presentation.slide_height,
            )
        else:
            box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
            box.text = f"Body {index + 1} 可编辑正文"
    presentation.save(path)


def rewrite_package(path: Path, transform) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
    transform(entries)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


class ValidateGhbPptxTest(unittest.TestCase):
    def build(self, directory: Path, *, count: int = 3, no_ending: bool = False, full_slide_image: bool = False):
        content = directory / "content.pptx"
        cover = directory / "cover.pptx"
        output = directory / "final.pptx"
        make_content(content, count, full_slide_image=full_slide_image)
        make_cover(cover)
        result = merge_pptx(
            content_path=content,
            template_path=TEMPLATE,
            cover_path=cover,
            output_path=output,
            no_ending=no_ending,
        )
        return output, result

    def test_valid_final_deck_passes_with_per_slide_editability_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, _result = self.build(Path(tmp))
            report = validate_pptx(output, expected_body_count=3, expect_ending=True)
            self.assertTrue(report.passed, report.errors)
            self.assertEqual(report.page_count, 5)
            self.assertEqual([slide.role for slide in report.slides], ["cover", "body", "body", "body", "ending"])
            self.assertTrue(all(slide.text_objects >= 1 for slide in report.slides[1:-1]))
            self.assertEqual(len(report.package["masters_used"]), 1)

    def test_wrong_page_count_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, _result = self.build(Path(tmp), count=1)
            report = validate_pptx(output, expected_body_count=3, expect_ending=True)
            self.assertFalse(report.passed)
            self.assertTrue(any(issue.code == "page-count" for issue in report.errors))

    def test_unregistered_used_ending_layout_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, result = self.build(Path(tmp))

            def corrupt(entries: dict[str, bytes]) -> None:
                rels_name = result.master_part.replace("ppt/slideMasters/", "ppt/slideMasters/_rels/") + ".rels"
                root = ET.fromstring(entries[rels_name])
                for rel in list(root):
                    if relation_type(rel) != "slideLayout":
                        continue
                    target = resolve_target(result.master_part, rel.get("Target", ""))
                    if target == result.ending_layout_part:
                        root.remove(rel)
                entries[rels_name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

            rewrite_package(output, corrupt)
            report = validate_pptx(output, expected_body_count=3, expect_ending=True)
            self.assertFalse(report.passed)
            self.assertTrue(any(issue.code == "unregistered-used-layout" for issue in report.errors))

    def test_full_slide_body_image_without_editable_text_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, _result = self.build(Path(tmp), count=1, full_slide_image=True)
            report = validate_pptx(output, expected_body_count=1, expect_ending=True)
            self.assertFalse(report.passed)
            self.assertTrue(any(issue.code == "full-slide-image-body" for issue in report.errors))

    def test_missing_planned_body_item_is_rejected_even_when_title_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            output, _result = self.build(directory, count=1)
            plan = directory / "layout_plan.json"
            plan.write_text(
                json.dumps(
                    [
                        {
                            "slide": 1,
                            "key_message": "Body 1 可编辑正文",
                            "items": ["必须出现的卡片标签"],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = validate_pptx(
                output,
                expected_body_count=1,
                expect_ending=True,
                layout_plan_path=plan,
            )
            self.assertFalse(report.passed)
            self.assertTrue(any(issue.code == "missing-planned-item" for issue in report.errors))

    def test_cli_writes_json_and_markdown_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            output, _result = self.build(directory, count=1, no_ending=True)
            json_path = directory / "report.json"
            markdown_path = directory / "report.md"
            code = main(
                [
                    str(output),
                    "--body-count", "1",
                    "--no-ending",
                    "--json-output", str(json_path),
                    "--markdown-output", str(markdown_path),
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(json_path.read_text(encoding="utf-8"))["passed"])
            self.assertIn("Per-slide object summary", markdown_path.read_text(encoding="utf-8"))

    def test_readback_markdown_is_required_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            output, _result = self.build(directory, count=1)
            missing = directory / "missing-readback.md"
            report = validate_pptx(
                output,
                expected_body_count=1,
                expect_ending=True,
                readback_markdown_path=missing,
            )
            self.assertFalse(report.passed)
            self.assertTrue(any(issue.code == "missing-ppt-readback" for issue in report.errors))

    def test_readback_markdown_page_count_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            output, _result = self.build(directory, count=1)
            readback = directory / "readback.md"
            readback.write_text("# final\n\n## Slide 1\n\ncover only\n", encoding="utf-8")
            report = validate_pptx(
                output,
                expected_body_count=1,
                expect_ending=True,
                readback_markdown_path=readback,
            )
            self.assertFalse(report.passed)
            self.assertTrue(any(issue.code == "ppt-readback-page-count" for issue in report.errors))


if __name__ == "__main__":
    unittest.main()
