"""Shared Chinese font policy for GHB PPT generation and rendering."""

from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path


PRIMARY_CJK_FONT = "Source Han Sans SC"
LEGACY_CJK_FONT = "Microsoft YaHei"
SUPPORTED_CJK_FONTS = (PRIMARY_CJK_FONT, LEGACY_CJK_FONT)
CONSULTING_RESEARCH_FONT_CANDIDATES = (
    "KaiTi",
    "STKaiti",
    "HuaWenKaiTi",
    "Songti SC",
    "SimSun",
)
_BODY_SLIDE_PART = re.compile(r"ppt/slides/slide\d+\.xml")


def _normalized_font_name(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value).casefold()


_CONSULTING_RESEARCH_FONT_ALIASES = {
    "KaiTi": ("KaiTi", "楷体"),
    "STKaiti": ("STKaiti", "华文楷体", "華文楷體"),
    "HuaWenKaiTi": ("HuaWenKaiTi", "华文楷体", "華文楷體"),
    "Songti SC": ("Songti SC", "宋体-简", "宋體-簡"),
    "SimSun": ("SimSun", "宋体"),
}


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


def resolve_consulting_research_font(fc_list_output: str) -> str | None:
    """Choose a real typeface for the consulting research profile.

    SVG/CSS can express a fallback stack, but DrawingML stores one typeface per
    run.  Select the first profile-approved family that fontconfig reports as
    actually installed, so a missing KaiTi never silently becomes a sans-serif
    substitution in the rendered deck.  ``Songti SC`` / ``SimSun`` are the
    verified serif fallback only when a true KaiTi family is unavailable.
    """
    installed: set[str] = set()
    for line in fc_list_output.splitlines():
        family_segment = line.partition(":")[2] if ":" in line else line
        for family in re.split(r"[:,]", family_segment):
            normalized = _normalized_font_name(family)
            if normalized and not normalized.startswith("style="):
                installed.add(normalized)
    for candidate in CONSULTING_RESEARCH_FONT_CANDIDATES:
        aliases = _CONSULTING_RESEARCH_FONT_ALIASES[candidate]
        if any(_normalized_font_name(alias) in installed for alias in aliases):
            return candidate
    return None


def rewrite_pptx_typeface(pptx_path: Path, *, source: str, target: str) -> int:
    """Replace one explicit body-slide typeface in place and return its count.

    This is a GHB adapter, not a change to the vendored SVG converter.  It only
    touches generated ``ppt/slides/slide*.xml`` parts, leaving masters,
    templates, cover, and ending slides untouched.
    """
    if not pptx_path.is_file():
        raise FileNotFoundError(f"PPTX not found: {pptx_path}")
    if source == target:
        return 0
    source_attr = f'typeface="{source}"'.encode("utf-8")
    target_attr = f'typeface="{target}"'.encode("utf-8")
    with zipfile.ZipFile(pptx_path) as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info.filename) for info in infos}
    changed = 0
    for name, payload in parts.items():
        if not _BODY_SLIDE_PART.fullmatch(name):
            continue
        count = payload.count(source_attr)
        if count:
            parts[name] = payload.replace(source_attr, target_attr)
            changed += count
    if not changed:
        return 0
    with tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=".pptx",
        prefix=f".{pptx_path.stem}.font-",
        dir=pptx_path.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as output:
            for info in infos:
                output.writestr(info, parts[info.filename])
        temp_path.replace(pptx_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return changed


def count_pptx_typeface(pptx_path: Path, *, typeface: str) -> int:
    """Count explicit typeface references in generated body-slide XML parts."""
    if not pptx_path.is_file():
        raise FileNotFoundError(f"PPTX not found: {pptx_path}")
    typeface_attr = f'typeface="{typeface}"'.encode("utf-8")
    with zipfile.ZipFile(pptx_path) as archive:
        return sum(
            archive.read(info.filename).count(typeface_attr)
            for info in archive.infolist()
            if _BODY_SLIDE_PART.fullmatch(info.filename)
        )


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
