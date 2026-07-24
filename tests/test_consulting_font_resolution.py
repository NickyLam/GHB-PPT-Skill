from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from scripts.font_policy import resolve_consulting_research_font, rewrite_pptx_typeface
from scripts.ghb_ppt import _effective_embed_font_paths, parser


def test_consulting_font_prefers_real_kaiti_then_verified_serif_fallback() -> None:
    both = (
        "/fonts/KaiTi.ttf: KaiTi:style=Regular\n"
        "/fonts/Songti.ttc: Songti SC:style=Regular\n"
    )
    fallback_only = "/fonts/Songti.ttc: Songti SC:style=Regular\n"

    assert resolve_consulting_research_font(both) == "KaiTi"
    assert resolve_consulting_research_font(fallback_only) == "Songti SC"
    assert resolve_consulting_research_font("") is None


def test_explicit_kaiti_file_overrides_fontconfig_serif_fallback() -> None:
    fallback_only = "/fonts/Songti.ttc: Songti SC:style=Regular\n"
    fake_font = mock.MagicMock()
    fake_font["name"].getDebugName.return_value = "KaiTi"
    with tempfile.TemporaryDirectory() as tmp:
        font_path = Path(tmp) / "Kaiti.ttf"
        font_path.write_bytes(b"test font payload")
        with mock.patch("fontTools.ttLib.TTFont", return_value=fake_font):
            assert (
                resolve_consulting_research_font(
                    fallback_only,
                    consulting_font=font_path,
                )
                == "KaiTi"
            )


def test_cli_accepts_consulting_font_for_all_build_boundaries() -> None:
    font = Path("/operator-assets/Kaiti.ttf")
    arguments = {
        "build-content": ["--project", "/tmp/project", "--consulting-font", str(font)],
        "merge": ["--project", "/tmp/project", "--consulting-font", str(font)],
        "build": ["--project", "/tmp/project", "--consulting-font", str(font)],
    }
    for command, argv in arguments.items():
        parsed = parser().parse_args([command, *argv])
        assert parsed.consulting_font == font


def test_exact_consulting_font_is_embedded_once_when_also_passed_explicitly() -> None:
    font = Path("/operator-assets/Kaiti.ttf")
    assert _effective_embed_font_paths([], consulting_font=font) == [font]
    assert _effective_embed_font_paths([font], consulting_font=font) == [font]


def test_rewrite_pptx_typeface_changes_body_slides_without_touching_master() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        deck = Path(tmp) / "content.pptx"
        slide = '<a:rPr xmlns:a="a"><a:latin typeface="KaiTi"/><a:ea typeface="KaiTi"/></a:rPr>'
        master = '<a:latin xmlns:a="a" typeface="KaiTi"/>'
        with zipfile.ZipFile(deck, "w") as archive:
            archive.writestr("ppt/slides/slide1.xml", slide)
            archive.writestr("ppt/slideMasters/slideMaster1.xml", master)

        changed = rewrite_pptx_typeface(deck, source="KaiTi", target="Songti SC")

        assert changed == 2
        with zipfile.ZipFile(deck) as archive:
            assert 'typeface="Songti SC"' in archive.read("ppt/slides/slide1.xml").decode("utf-8")
            assert 'typeface="KaiTi"' in archive.read("ppt/slideMasters/slideMaster1.xml").decode("utf-8")
