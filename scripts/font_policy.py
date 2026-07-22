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


_FONT_ALIASES = {
    PRIMARY_CJK_FONT: ("source han sans sc", "sourcehansanssc", "思源黑体"),
    LEGACY_CJK_FONT: ("microsoft yahei", "微软雅黑"),
}


def resolve_font_file(font_name: str, fc_list_output: str) -> str | None:
    """Return the on-disk file for ``font_name`` from raw ``fc-list`` output.

    ``fc-list`` prints lines shaped like ``/path/to/font.otf: Family:style=...``.
    Matching is done against the family aliases so ``Source Han Sans SC`` is
    found regardless of localisation. Returns ``None`` when unresolved.
    """
    aliases = _FONT_ALIASES.get(font_name, (font_name.lower(),))
    for line in fc_list_output.splitlines():
        path, sep, rest = line.partition(":")
        if not sep or not path.strip():
            continue
        haystack = rest.lower()
        if any(alias in haystack for alias in aliases):
            return path.strip()
    return None
