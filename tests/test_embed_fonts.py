from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as ET
import zipfile

from scripts.embed_fonts import (
    FONT_CONTENT_TYPE,
    FontEmbedError,
    collect_used_characters,
    embed_fonts,
)
from scripts.validate_ghb_pptx import validate_pptx


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '</Types>'
)
PRESENTATION = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<p:notesSz cx="6858000" cy="9144000"/>'
    '</p:presentation>'
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="test" Target="slides/slide1.xml"/>'
    '</Relationships>'
)
SLIDE = (
    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    '<a:t>中文 &amp; ABC</a:t>'
    '</p:sld>'
)


def _deck(path: Path, *, presentation: str = PRESENTATION) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("ppt/presentation.xml", presentation)
        archive.writestr("ppt/_rels/presentation.xml.rels", RELS)
        archive.writestr("ppt/slides/slide1.xml", SLIDE)


class EmbedFontsTest(unittest.TestCase):
    def test_collects_cjk_and_decodes_xml_entities(self):
        with tempfile.TemporaryDirectory() as tmp:
            deck = Path(tmp) / "input.pptx"
            _deck(deck)
            chars = collect_used_characters(deck)
            self.assertTrue(set("中文&ABC").issubset(chars))

    def test_embeds_font_part_relationship_and_presentation_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deck = root / "input.pptx"
            font = root / "Source & Test.ttf"
            output = root / "output.pptx"
            _deck(deck)
            font.write_bytes(b"not-a-real-font")
            with (
                mock.patch("scripts.embed_fonts.read_fs_type", return_value=0),
                mock.patch("scripts.embed_fonts.subset_font", return_value=b"subset-font"),
            ):
                report = embed_fonts(deck, font_paths=[font], output_path=output)

            self.assertEqual(report["fonts_embedded"], 1)
            self.assertTrue(report["fsType_ok"])
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("ppt/fonts/font1.fntdata"), b"subset-font")
                content_types = archive.read("[Content_Types].xml").decode("utf-8")
                presentation = archive.read("ppt/presentation.xml").decode("utf-8")
                rels = archive.read("ppt/_rels/presentation.xml.rels").decode("utf-8")
            self.assertIn(FONT_CONTENT_TYPE, content_types)
            self.assertIn('embedTrueTypeFonts="1"', presentation)
            self.assertIn('saveSubsetFonts="1"', presentation)
            self.assertIn("Source &amp; Test", presentation)
            self.assertIn("fonts/font1.fntdata", rels)
            ET.fromstring(presentation)
            ET.fromstring(rels)

    def test_restricted_license_fails_before_subsetting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deck = root / "input.pptx"
            font = root / "restricted.ttf"
            _deck(deck)
            font.write_bytes(b"font")
            with (
                mock.patch("scripts.embed_fonts.read_fs_type", return_value=0x0002),
                mock.patch("scripts.embed_fonts.subset_font") as subset,
                self.assertRaisesRegex(FontEmbedError, "forbids embedding"),
            ):
                embed_fonts(deck, font_paths=[font], output_path=root / "output.pptx")
            subset.assert_not_called()

    def test_no_subsetting_license_embeds_full_font_and_disables_subset_saving(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deck = root / "input.pptx"
            font = root / "no-subset.ttf"
            output = root / "output.pptx"
            _deck(deck)
            font.write_bytes(b"full-font")
            with (
                mock.patch("scripts.embed_fonts.read_fs_type", return_value=0x0100),
                mock.patch("scripts.embed_fonts.subset_font") as subset,
            ):
                report = embed_fonts(deck, font_paths=[font], output_path=output)
            subset.assert_not_called()
            self.assertEqual(report["full_font_names"], ["no-subset"])
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("ppt/fonts/font1.fntdata"), b"full-font")
                presentation = archive.read("ppt/presentation.xml").decode("utf-8")
            self.assertIn('saveSubsetFonts="0"', presentation)

    def test_bitmap_only_license_fails_before_embedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deck = root / "input.pptx"
            font = root / "bitmap-only.ttf"
            _deck(deck)
            font.write_bytes(b"font")
            with (
                mock.patch("scripts.embed_fonts.read_fs_type", return_value=0x0200),
                mock.patch("scripts.embed_fonts.subset_font") as subset,
                self.assertRaisesRegex(FontEmbedError, "forbids embedding"),
            ):
                embed_fonts(deck, font_paths=[font], output_path=root / "output.pptx")
            subset.assert_not_called()

    def test_existing_embedded_font_list_fails_instead_of_writing_orphan_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deck = root / "input.pptx"
            font = root / "font.ttf"
            presentation = PRESENTATION.replace(
                "</p:presentation>",
                "<p:embeddedFontLst/></p:presentation>",
            )
            _deck(deck, presentation=presentation)
            font.write_bytes(b"font")
            with (
                mock.patch("scripts.embed_fonts.read_fs_type", return_value=0),
                mock.patch("scripts.embed_fonts.subset_font", return_value=b"subset"),
                self.assertRaisesRegex(FontEmbedError, "already contains embedded fonts"),
            ):
                embed_fonts(deck, font_paths=[font], output_path=root / "output.pptx")

    def test_validator_reports_actual_embedded_font_contract_and_license_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deck = root / "input.pptx"
            font = root / "font.ttf"
            output = root / "output.pptx"
            report_path = root / "font-embed-report.json"
            _deck(deck)
            font.write_bytes(b"font")
            with (
                mock.patch("scripts.embed_fonts.read_fs_type", return_value=0),
                mock.patch("scripts.embed_fonts.subset_font", return_value=b"subset"),
            ):
                report_payload = embed_fonts(deck, font_paths=[font], output_path=output)
            import json

            report_path.write_text(json.dumps(report_payload), encoding="utf-8")
            validation = validate_pptx(output, font_embed_report_path=report_path)
            evidence = validation.quality["font_embedding"]
            self.assertEqual(evidence["fonts_embedded"], 1)
            self.assertTrue(evidence["embedding_enabled"])
            self.assertTrue(evidence["fsType_ok"])


if __name__ == "__main__":
    unittest.main()
