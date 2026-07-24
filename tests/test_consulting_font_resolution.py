from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from scripts.font_policy import resolve_consulting_research_font, rewrite_pptx_typeface


def test_consulting_font_prefers_real_kaiti_then_verified_serif_fallback() -> None:
    both = (
        "/fonts/KaiTi.ttf: KaiTi:style=Regular\n"
        "/fonts/Songti.ttc: Songti SC:style=Regular\n"
    )
    fallback_only = "/fonts/Songti.ttc: Songti SC:style=Regular\n"

    assert resolve_consulting_research_font(both) == "KaiTi"
    assert resolve_consulting_research_font(fallback_only) == "Songti SC"
    assert resolve_consulting_research_font("") is None


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
