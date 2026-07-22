#!/usr/bin/env python3
"""Derive one versioned template profile from template-fill analysis."""

from __future__ import annotations

import json
import hashlib
import re
import zipfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _box_from_xfrm(
    shape: ET.Element,
    *,
    slide_width_emu: int,
    slide_height_emu: int,
    width: int,
    height: int,
) -> list[int] | None:
    xfrm = shape.find("p:spPr/a:xfrm", NS)
    off = xfrm.find("a:off", NS) if xfrm is not None else None
    ext = xfrm.find("a:ext", NS) if xfrm is not None else None
    if off is None or ext is None or slide_width_emu <= 0 or slide_height_emu <= 0:
        return None
    try:
        return [
            round(int(off.get("x", "0")) / slide_width_emu * width),
            round(int(off.get("y", "0")) / slide_height_emu * height),
            round(int(ext.get("cx", "0")) / slide_width_emu * width),
            round(int(ext.get("cy", "0")) / slide_height_emu * height),
        ]
    except ValueError:
        return None


def _layout_geometry(
    archive: zipfile.ZipFile,
    layout_index: int,
    *,
    width: int,
    height: int,
) -> tuple[dict[str, list[int]], int, int]:
    presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
    slide_size = presentation.find("p:sldSz", NS)
    slide_width_emu = int(slide_size.get("cx", "0")) if slide_size is not None else 0
    slide_height_emu = int(slide_size.get("cy", "0")) if slide_size is not None else 0
    name = f"ppt/slideLayouts/slideLayout{layout_index}.xml"
    if name not in archive.namelist():
        return {}, slide_width_emu, slide_height_emu
    root = ET.fromstring(archive.read(name))
    boxes: dict[str, list[int]] = {}
    for shape in root.findall(".//p:sp", NS):
        placeholder = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if placeholder is None:
            continue
        kind = placeholder.get("type", "body")
        role = "title" if kind in {"title", "ctrTitle"} else "body" if kind in {"body", "obj"} else kind
        box = _box_from_xfrm(
            shape,
            slide_width_emu=slide_width_emu,
            slide_height_emu=slide_height_emu,
            width=width,
            height=height,
        )
        if box is not None and box[2] > 0 and box[3] > 0 and role not in boxes:
            boxes[role] = box
    return boxes, slide_width_emu, slide_height_emu


def _is_brand_color(value: str) -> bool:
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    highest, lowest = max(red, green, blue), min(red, green, blue)
    return highest - lowest >= 36 and 28 <= highest <= 240


def _brand_colors(archive: zipfile.ZipFile, themes: list[str]) -> tuple[str, str, str]:
    explicit: Counter[str] = Counter()
    for name in archive.namelist():
        if not re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
            continue
        xml = archive.read(name).decode("utf-8", errors="ignore")
        explicit.update(value.upper() for value in re.findall(r'srgbClr val="([0-9A-Fa-f]{6})"', xml))
    chromatic = [(value, count) for value, count in explicit.most_common() if _is_brand_color(value)]
    primary = chromatic[0][0] if chromatic else "5B9BD5"

    secondary = "44546A"
    source = "slide-explicit-color-frequency+theme-dk2"
    for theme in themes:
        if theme not in archive.namelist():
            continue
        root = ET.fromstring(archive.read(theme))
        node = root.find(".//a:clrScheme/a:dk2/*", NS)
        if node is not None:
            candidate = (node.get("val") or node.get("lastClr") or "").upper()
            if re.fullmatch(r"[0-9A-F]{6}", candidate):
                secondary = candidate
                break
    if secondary == primary and len(chromatic) > 1:
        secondary = chromatic[1][0]
    return f"#{primary}", f"#{secondary}", source


def _reviewed_sidecar(template: Path) -> dict[str, Any] | None:
    sidecar = template.with_suffix(".profile.json")
    if not sidecar.is_file():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != "ghb.template-profile.v1":
        return None
    expected_digest = payload.get("source_sha256")
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        return None
    actual_digest = hashlib.sha256(template.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        return None
    return payload


def build_template_profile(library: dict[str, Any], template: Path) -> dict[str, Any]:
    canvas = library.get("canvas_px") if isinstance(library.get("canvas_px"), dict) else {}
    width = int(canvas.get("width") or 1280)
    height = int(canvas.get("height") or 720)
    slides = library.get("slides") if isinstance(library.get("slides"), list) else []
    cover = next(
        (slide for slide in slides if slide.get("page_type") == "cover_candidate"),
        slides[0] if slides else {},
    )
    slots = [
        item
        for item in cover.get("slots", [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]

    def area_weight(item: dict[str, Any]) -> float:
        geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
        metrics = item.get("text_metrics") if isinstance(item.get("text_metrics"), dict) else {}
        return float(geometry.get("width") or 0) * float(metrics.get("font_size_px") or 1)

    title = max(slots, key=area_weight, default={})
    remaining = [item for item in slots if item is not title]
    date = max(
        remaining,
        key=lambda item: float((item.get("geometry") or {}).get("y") or 0),
        default={},
    )
    subtitle = max(
        [item for item in remaining if item is not date],
        key=area_weight,
        default={},
    )
    content_slide = next(
        (slide for slide in slides if slide.get("page_type") == "content_candidate"),
        None,
    )
    ending_slide = next(
        (slide for slide in reversed(slides) if slide.get("page_type") == "ending_candidate"),
        None,
    )
    with zipfile.ZipFile(template) as archive:
        names = archive.namelist()
        content_slide_index = int((content_slide or {}).get("slide_index") or 2)
        rels_name = f"ppt/slides/_rels/slide{content_slide_index}.xml.rels"
        content_layout_index = 2
        if rels_name in names:
            rels_xml = archive.read(rels_name).decode("utf-8", errors="ignore")
            match = re.search(r'Target="[^\"]*slideLayout(\d+)\.xml"', rels_xml)
            if match:
                content_layout_index = int(match.group(1))
        masters = sorted(name for name in names if name.startswith("ppt/slideMasters/slideMaster") and name.endswith(".xml"))
        themes = sorted(name for name in names if name.startswith("ppt/theme/theme") and name.endswith(".xml"))
        layout_boxes, _slide_width_emu, _slide_height_emu = _layout_geometry(
            archive,
            content_layout_index,
            width=width,
            height=height,
        )
        primary, secondary, brand_source = _brand_colors(archive, themes)

    title_zone = layout_boxes.get("title") or [round(width * 0.07), round(height * 0.08), round(width * 0.63), round(height * 0.13)]
    body_surface = layout_boxes.get("body") or [round(width * 0.044), round(height * 0.133), round(width * 0.9125), round(height * 0.844)]
    section_width = max(round(title_zone[2] * 0.25), round(width * 0.18))
    section_zone = [title_zone[0] + title_zone[2] - section_width, title_zone[1], section_width, title_zone[3]]
    logo_width = min(round(width * 0.195), max(round(title_zone[2] * 0.22), 1))
    inferred = {
        "schema": "ghb.template-profile.v1",
        "source_pptx": str(template),
        "profile_source": "ooxml-inferred",
        "canvas": {"width": width, "height": height},
        "cover_slots": {
            "title": title.get("slot_id"),
            "subtitle": subtitle.get("slot_id"),
            "date": date.get("slot_id"),
        },
        "header_safe_zones": {
            "logo": [title_zone[0], title_zone[1], logo_width, title_zone[3]],
            "title": title_zone,
            "section": section_zone,
        },
        "body_surface": body_surface,
        "brand": {"primary": primary, "secondary": secondary},
        "master_naming": {"masters": masters, "themes": themes},
        "content_layout_index": content_layout_index,
        "ending_slide_index": int((ending_slide or {}).get("slide_index") or len(slides) or 1),
        "inference": {
            "cover_slots": "geometry-and-font-analysis",
            "safe_zones": "content-layout-placeholder-geometry",
            "brand": brand_source,
        },
    }
    reviewed = _reviewed_sidecar(template)
    if reviewed is None:
        return inferred
    result = deepcopy(reviewed)
    result["source_pptx"] = str(template)
    result["profile_source"] = "reviewed-sidecar"
    result.setdefault("inference", {})["base"] = "reviewed-sidecar-over-ooxml-inference"
    return result


def write_template_profile(library_path: Path, template: Path, output: Path) -> dict[str, Any]:
    library = json.loads(library_path.read_text(encoding="utf-8"))
    profile = build_template_profile(library, template)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return profile
