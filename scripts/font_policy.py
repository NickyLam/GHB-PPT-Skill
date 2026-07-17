"""Shared Chinese font policy for GHB PPT generation and rendering."""

from __future__ import annotations


PRIMARY_CJK_FONT = "Source Han Sans SC"
LEGACY_CJK_FONT = "Microsoft YaHei"
SUPPORTED_CJK_FONTS = (PRIMARY_CJK_FONT, LEGACY_CJK_FONT)


def detect_cjk_fonts(font_output: str) -> dict[str, bool]:
    """Return availability for supported CJK fonts from ``fc-list`` output."""
    normalized = font_output.lower()
    return {
        PRIMARY_CJK_FONT: (
            "source han sans sc" in normalized
            or "sourcehansanssc" in normalized
            or "思源黑体" in normalized
        ),
        LEGACY_CJK_FONT: "microsoft yahei" in normalized or "微软雅黑" in normalized,
    }


def preferred_cjk_font(fonts: dict[str, bool]) -> str | None:
    """Select the first installed font in project preference order."""
    return next((font for font in SUPPORTED_CJK_FONTS if fonts.get(font)), None)
