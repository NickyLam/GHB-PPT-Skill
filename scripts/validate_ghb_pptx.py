#!/usr/bin/env python3
"""Validate a final GHB PPTX and emit console, JSON, and Markdown reports."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.merge_template_master import (  # noqa: E402
    NS,
    parse_rels,
    presentation_slide_parts,
    qn,
    relation_type,
    resolve_target,
    slide_layout_part,
)


CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
MOJIBAKE = ("\ufffd", "Ã", "Â", "â€", "ðŸ", "ï»¿")
PLACEHOLDER_PATTERNS = (
    re.compile(r"\{\{[^}]+\}\}"),
    re.compile(r"\b(?:XXX+|TBD|TODO)\b", re.IGNORECASE),
    re.compile(r"202X"),
)


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    slide: int | None = None


@dataclass
class SlideSummary:
    slide: int
    role: str
    layout_part: str
    master_part: str
    text_objects: int = 0
    text_chars: int = 0
    shape_objects: int = 0
    group_objects: int = 0
    picture_objects: int = 0
    table_objects: int = 0
    chart_objects: int = 0
    min_font_pt: float | None = None
    title: str = ""
    full_slide_pictures: int = 0
    out_of_bounds_objects: int = 0
    full_white_rectangles: int = 0
    notes_chars: int = 0
    empty_text_boxes: int = 0
    text_boxes_too_small: int = 0
    possible_text_overlaps: int = 0
    page_number_found: bool = False


@dataclass
class ValidationReport:
    pptx: str
    passed: bool
    file_size: int
    page_count: int
    body_count: int
    has_ending: bool
    slide_size: dict[str, Any]
    issues: list[Issue] = field(default_factory=list)
    slides: list[SlideSummary] = field(default_factory=list)
    package: dict[str, Any] = field(default_factory=dict)
    known_limitations: list[str] = field(default_factory=list)
    manual_review: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "warning"]


def _issue(issues: list[Issue], severity: str, code: str, message: str, slide: int | None = None) -> None:
    issues.append(Issue(severity, code, message, slide))


def _package(path: Path, issues: list[Issue]) -> tuple[dict[str, bytes], list[str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            names = [info.filename for info in infos]
            duplicates = sorted({name for name in names if names.count(name) > 1})
            for name in duplicates:
                _issue(issues, "error", "duplicate-part", f"duplicate ZIP part: {name}")
            bad = archive.testzip()
            if bad:
                _issue(issues, "error", "corrupt-zip-member", f"corrupt ZIP member: {bad}")
            return ({info.filename: archive.read(info.filename) for info in infos}, names)
    except zipfile.BadZipFile as exc:
        _issue(issues, "error", "invalid-zip", f"invalid PPTX ZIP: {exc}")
        return {}, []


def _owner_for_rels(name: str) -> str | None:
    if "/_rels/" in name:
        prefix, filename = name.split("/_rels/", 1)
        return f"{prefix}/{filename[:-5]}"
    if name.startswith("_rels/"):
        return name[len("_rels/") : -5]
    return None


def _check_relationships(parts: dict[str, bytes], issues: list[Issue]) -> dict[str, Any]:
    rel_count = 0
    external_count = 0
    for name, payload in parts.items():
        if not name.endswith(".rels"):
            continue
        owner = _owner_for_rels(name)
        if owner is None:
            continue
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            _issue(issues, "error", "invalid-rels", f"{name}: {exc}")
            continue
        ids = [rel.get("Id", "") for rel in root]
        for rid in sorted({rid for rid in ids if ids.count(rid) > 1}):
            _issue(issues, "error", "duplicate-rid", f"{name}: duplicate relationship ID {rid}")
        for rel in root:
            rel_count += 1
            if rel.get("TargetMode") == "External":
                external_count += 1
                continue
            target = resolve_target(owner, rel.get("Target", ""))
            if target not in parts:
                _issue(
                    issues,
                    "error",
                    "dangling-relationship",
                    f"{name}: {rel.get('Id')} targets missing part {target}",
                )
    return {"relationship_count": rel_count, "external_relationship_count": external_count}


def _check_content_types(parts: dict[str, bytes], issues: list[Issue]) -> dict[str, Any]:
    name = "[Content_Types].xml"
    if name not in parts:
        _issue(issues, "error", "missing-content-types", f"missing {name}")
        return {}
    raw = parts[name]
    if b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' not in raw:
        _issue(
            issues,
            "error",
            "noncanonical-content-types-namespace",
            "[Content_Types].xml must use the OPC namespace as the default; "
            "LibreOffice rejects the equivalent ns0-prefixed wire form",
        )
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        _issue(issues, "error", "invalid-content-types", str(exc))
        return {}
    defaults = [node.get("Extension", "").lower() for node in root if node.tag.endswith("Default")]
    overrides = [node.get("PartName", "") for node in root if node.tag.endswith("Override")]
    for ext in sorted({ext for ext in defaults if defaults.count(ext) > 1}):
        _issue(issues, "error", "duplicate-content-default", f"duplicate content-type Default for .{ext}")
    for part in sorted({part for part in overrides if overrides.count(part) > 1}):
        _issue(issues, "error", "duplicate-content-override", f"duplicate content-type Override for {part}")
    override_set = {part.lstrip("/") for part in overrides}
    for part in parts:
        if re.fullmatch(r"ppt/(?:slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster|theme/theme)\d+\.xml", part):
            if part not in override_set:
                _issue(issues, "error", "missing-content-override", f"missing content-type Override for {part}")
        if part.startswith("ppt/media/") and "." in part:
            ext = part.rsplit(".", 1)[-1].lower()
            if ext not in defaults:
                _issue(issues, "error", "missing-media-default", f"missing content-type Default for .{ext}")
    return {"default_count": len(defaults), "override_count": len(overrides)}


def _iter_shapes(shapes: Iterable[Any]) -> Iterable[Any]:
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes(shape.shapes)


def _shape_text(shape: Any) -> str:
    if not getattr(shape, "has_text_frame", False):
        return ""
    try:
        return "\n".join(paragraph.text for paragraph in shape.text_frame.paragraphs).strip()
    except Exception:
        return ""


def _font_sizes(shape: Any) -> list[float]:
    if not getattr(shape, "has_text_frame", False):
        return []
    values: list[float] = []
    try:
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                if run.font.size is not None:
                    values.append(round(run.font.size.pt, 2))
    except Exception:
        return values
    return values


def _is_white_fill(shape: Any) -> bool:
    try:
        color = shape.fill.fore_color.rgb
        return color is not None and str(color).upper() == "FFFFFF"
    except Exception:
        return False


def _notes_text(slide: Any) -> str:
    try:
        notes_slide = slide.notes_slide
    except Exception:
        return ""
    return "\n".join(filter(None, (_shape_text(shape) for shape in _iter_shapes(notes_slide.shapes))))


def _summarize_slide(
    slide: Any,
    *,
    index: int,
    role: str,
    layout_part: str,
    master_part: str,
    slide_width: int,
    slide_height: int,
    issues: list[Issue],
) -> SlideSummary:
    summary = SlideSummary(index, role, layout_part, master_part)
    positioned_text: list[tuple[int, int, str]] = []
    text_boxes: list[tuple[int, int, int, int, str]] = []
    font_sizes: list[float] = []
    slide_area = max(slide_width * slide_height, 1)
    for shape in _iter_shapes(slide.shapes):
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            summary.group_objects += 1
        else:
            summary.shape_objects += 1
        text = _shape_text(shape)
        has_text_frame = bool(getattr(shape, "has_text_frame", False))
        if (
            has_text_frame
            and shape.shape_type == MSO_SHAPE_TYPE.TEXT_BOX
            and not text
            and not bool(getattr(shape, "is_placeholder", False))
        ):
            summary.empty_text_boxes += 1
        if text:
            summary.text_objects += 1
            summary.text_chars += len(re.sub(r"\s+", "", text))
            positioned_text.append((int(getattr(shape, "top", 0) or 0), int(getattr(shape, "left", 0) or 0), text))
            font_sizes.extend(_font_sizes(shape))
            for marker in MOJIBAKE:
                if marker in text:
                    _issue(issues, "error", "mojibake", f"corrupt text marker {marker!r}: {text[:80]}", index)
            for pattern in PLACEHOLDER_PATTERNS:
                match = pattern.search(text)
                if match:
                    _issue(issues, "error", "placeholder", f"unreplaced placeholder {match.group(0)!r}", index)
        if getattr(shape, "has_table", False):
            summary.table_objects += 1
        if getattr(shape, "has_chart", False):
            summary.chart_objects += 1
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            summary.picture_objects += 1
        left = int(getattr(shape, "left", 0) or 0)
        top = int(getattr(shape, "top", 0) or 0)
        width = int(getattr(shape, "width", 0) or 0)
        height = int(getattr(shape, "height", 0) or 0)
        if text:
            text_boxes.append((left, top, width, height, text))
            explicit_sizes = _font_sizes(shape)
            if explicit_sizes and height / 12700 < min(explicit_sizes) * 1.05:
                summary.text_boxes_too_small += 1
        if left < -1 or top < -1 or left + width > slide_width + 1 or top + height > slide_height + 1:
            summary.out_of_bounds_objects += 1
        area_ratio = max(width, 0) * max(height, 0) / slide_area
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE and area_ratio >= 0.85:
            summary.full_slide_pictures += 1
        if area_ratio >= 0.90 and _is_white_fill(shape):
            summary.full_white_rectangles += 1
    if positioned_text:
        summary.title = sorted(positioned_text)[0][2].splitlines()[0].strip()
    summary.page_number_found = any(
        re.search(r"\b\d{1,2}\s*/\s*\d{1,2}\b", text)
        for _left, _top, _width, _height, text in text_boxes
    )
    for left_index, left_box in enumerate(text_boxes):
        lx, ly, lw, lh, _lt = left_box
        left_area = max(lw, 0) * max(lh, 0)
        if not left_area:
            continue
        for right_box in text_boxes[left_index + 1 :]:
            rx, ry, rw, rh, _rt = right_box
            right_area = max(rw, 0) * max(rh, 0)
            if not right_area:
                continue
            intersection_w = max(0, min(lx + lw, rx + rw) - max(lx, rx))
            intersection_h = max(0, min(ly + lh, ry + rh) - max(ly, ry))
            if intersection_w * intersection_h / min(left_area, right_area) >= 0.60:
                summary.possible_text_overlaps += 1
    if font_sizes:
        summary.min_font_pt = min(font_sizes)
    summary.notes_chars = len(re.sub(r"\s+", "", _notes_text(slide)))

    if summary.shape_objects + summary.group_objects == 0:
        _issue(issues, "error", "blank-slide", "slide has no slide-level objects", index)
    if summary.out_of_bounds_objects and role == "body":
        _issue(issues, "error", "object-out-of-bounds", f"{summary.out_of_bounds_objects} object(s) exceed slide bounds", index)
    elif summary.out_of_bounds_objects:
        _issue(
            issues,
            "warning",
            "template-bleed",
            f"{summary.out_of_bounds_objects} template object(s) extend beyond slide bounds; verify intentional bleed visually",
            index,
        )
    if role == "body" and summary.full_slide_pictures and summary.text_objects == 0:
        _issue(issues, "error", "full-slide-image-body", "body slide is effectively a full-slide image with no editable text", index)
    if role == "body" and summary.full_white_rectangles:
        _issue(issues, "error", "full-white-rectangle", "body slide contains a near-full-slide white rectangle", index)
    if summary.min_font_pt is not None and summary.min_font_pt < 9:
        _issue(issues, "warning", "small-font", f"minimum explicit font size is {summary.min_font_pt:g} pt", index)
    if role == "body" and summary.empty_text_boxes:
        _issue(issues, "warning", "empty-text-box", f"{summary.empty_text_boxes} empty text box(es)", index)
    if role == "body" and summary.text_boxes_too_small:
        _issue(issues, "warning", "text-box-too-small", f"{summary.text_boxes_too_small} text box(es) are shorter than their explicit font size", index)
    if role == "body" and summary.possible_text_overlaps:
        _issue(issues, "warning", "possible-text-overlap", f"{summary.possible_text_overlaps} pair(s) of text boxes overlap by at least 60%", index)
    if role == "body" and not summary.page_number_found:
        _issue(issues, "warning", "missing-page-number", "no NN / total page-number text was detected", index)
    if role == "body" and summary.text_chars > 600:
        _issue(issues, "warning", "high-text-density", f"body slide has {summary.text_chars} non-whitespace text characters", index)
    if role == "body" and summary.shape_objects + summary.group_objects > 120:
        _issue(issues, "warning", "high-object-density", f"body slide has {summary.shape_objects + summary.group_objects} objects/groups", index)
    if summary.title and len(summary.title) > 80:
        _issue(issues, "warning", "long-title", f"title has {len(summary.title)} characters", index)
    return summary


def _layout_master(parts: dict[str, bytes], layout: str) -> str:
    rels = parse_rels(parts, layout)
    masters = [rel for rel in rels if relation_type(rel) == "slideMaster"]
    if len(masters) != 1:
        raise ValueError(f"{layout}: expected one slideMaster relationship, found {len(masters)}")
    return resolve_target(layout, masters[0].get("Target", ""))


def _check_mount_chain(
    parts: dict[str, bytes],
    ordered_slides: list[str],
    roles: list[str],
    issues: list[Issue],
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    chains: list[tuple[str, str]] = []
    used_layouts_by_master: dict[str, set[str]] = {}
    for index, (slide, role) in enumerate(zip(ordered_slides, roles), 1):
        try:
            layout = slide_layout_part(parts, slide)
            master = _layout_master(parts, layout)
        except (KeyError, ValueError, RuntimeError, ET.ParseError) as exc:
            _issue(issues, "error", "mount-chain", str(exc), index)
            chains.append(("", ""))
            continue
        chains.append((layout, master))
        used_layouts_by_master.setdefault(master, set()).add(layout)
    for master, used_layouts in used_layouts_by_master.items():
        try:
            rels = parse_rels(parts, master)
            registered_by_rel = {
                resolve_target(master, rel.get("Target", "")): rel.get("Id")
                for rel in rels if relation_type(rel) == "slideLayout"
            }
            theme_targets = [
                resolve_target(master, rel.get("Target", ""))
                for rel in rels if relation_type(rel) == "theme"
            ]
            master_xml = ET.fromstring(parts[master])
            registered_ids = {
                node.get(qn("r", "id")) for node in master_xml.findall(".//p:sldLayoutId", NS)
            }
        except (KeyError, ET.ParseError, RuntimeError) as exc:
            _issue(issues, "error", "master-structure", f"{master}: {exc}")
            continue
        missing = sorted(used_layouts - set(registered_by_rel))
        if missing:
            _issue(issues, "error", "unregistered-used-layout", f"{master} does not register used layout(s): {missing}")
        if registered_ids != set(registered_by_rel.values()):
            _issue(issues, "error", "master-layout-list-mismatch", f"{master} layout ID list does not match its relationships")
        if len(theme_targets) != 1 or theme_targets[0] not in parts:
            _issue(issues, "error", "master-theme", f"{master} must reference one existing theme")
    masters = {master for _layout, master in chains if master}
    if len(masters) != 1:
        _issue(issues, "error", "multiple-role-masters", f"cover/body/ending use {len(masters)} masters: {sorted(masters)}")
    return chains, {"masters_used": sorted(masters), "layouts_used": sorted({layout for layout, _master in chains if layout})}


def _load_layout_plan(path: Path | None, issues: list[Issue]) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _issue(issues, "error", "invalid-layout-plan", str(exc))
        return []
    if not isinstance(payload, list):
        _issue(issues, "error", "invalid-layout-plan", "layout plan top level must be a list")
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def validate_pptx(
    path: Path,
    *,
    expected_body_count: int | None = None,
    expect_ending: bool | None = None,
    source_svg_dir: Path | None = None,
    layout_plan_path: Path | None = None,
    cover_text: list[str] | None = None,
    render_dir: Path | None = None,
    expect_body_notes: bool = False,
    svg_report_paths: list[Path] | None = None,
    readback_markdown_path: Path | None = None,
) -> ValidationReport:
    issues: list[Issue] = []
    if not path.is_file():
        return ValidationReport(
            str(path), False, 0, 0, 0, bool(expect_ending), {},
            issues=[Issue("error", "missing-file", f"PPTX not found: {path}")],
        )
    size = path.stat().st_size
    if size < 10_000:
        _issue(issues, "error", "file-too-small", f"PPTX size is suspiciously small: {size} bytes")
    parts, names = _package(path, issues)
    required = ("[Content_Types].xml", "ppt/presentation.xml", "ppt/_rels/presentation.xml.rels")
    for required_part in required:
        if required_part not in parts:
            _issue(issues, "error", "missing-required-part", f"missing required part: {required_part}")
    package_info = {"part_count": len(names), **_check_relationships(parts, issues), **_check_content_types(parts, issues)}

    ordered_slides: list[str] = []
    if all(name in parts for name in required[1:]):
        try:
            ordered_slides = presentation_slide_parts(parts)
            pres = ET.fromstring(parts["ppt/presentation.xml"])
            slide_ids = [node.get("id") for node in pres.findall(".//p:sldId", NS)]
            master_ids = [node.get("id") for node in pres.findall(".//p:sldMasterId", NS)]
            if len(slide_ids) != len(set(slide_ids)):
                _issue(issues, "error", "duplicate-slide-id", "presentation has duplicate slide IDs")
            if len(master_ids) != len(set(master_ids)):
                _issue(issues, "error", "duplicate-master-id", "presentation has duplicate master IDs")
        except (ET.ParseError, RuntimeError, KeyError) as exc:
            _issue(issues, "error", "presentation-graph", str(exc))

    svg_count = None
    if source_svg_dir is not None:
        svg_count = len(list(source_svg_dir.glob("*.svg"))) if source_svg_dir.is_dir() else 0
        if svg_count == 0:
            _issue(issues, "error", "missing-source-svg", f"no source SVG files found: {source_svg_dir}")
    if expected_body_count is None:
        expected_body_count = svg_count
    if expect_ending is None:
        expect_ending = True
    inferred_body_count = max(len(ordered_slides) - 1 - int(expect_ending), 0)
    if expected_body_count is not None and inferred_body_count != expected_body_count:
        _issue(
            issues,
            "error",
            "page-count",
            f"expected 1 cover + {expected_body_count} body + {int(expect_ending)} ending, got {len(ordered_slides)} pages",
        )
    if svg_count is not None and inferred_body_count != svg_count:
        _issue(issues, "error", "svg-page-count", f"body count {inferred_body_count} does not match source SVG count {svg_count}")
    roles = ["cover"] + ["body"] * inferred_body_count + (["ending"] if expect_ending else [])
    if len(roles) != len(ordered_slides):
        roles = ["cover"] + ["body"] * max(len(ordered_slides) - 1, 0)

    chains: list[tuple[str, str]] = [("", "")] * len(ordered_slides)
    if ordered_slides:
        chains, mount_info = _check_mount_chain(parts, ordered_slides, roles, issues)
        package_info.update(mount_info)

    slides: list[SlideSummary] = []
    slide_full_texts: list[str] = []
    slide_size: dict[str, Any] = {}
    try:
        presentation = Presentation(path)
        width = int(presentation.slide_width)
        height = int(presentation.slide_height)
        ratio = width / height if height else 0
        slide_size = {"width_emu": width, "height_emu": height, "ratio": round(ratio, 6), "is_16_9": abs(ratio - 16 / 9) < 0.01}
        if not slide_size["is_16_9"]:
            _issue(issues, "error", "slide-size", f"slide ratio is {ratio:.4f}, expected 16:9")
        if len(presentation.slides) != len(ordered_slides):
            _issue(issues, "error", "python-pptx-page-count", f"python-pptx sees {len(presentation.slides)} slides, package graph sees {len(ordered_slides)}")
        for index, slide in enumerate(presentation.slides, 1):
            role = roles[index - 1] if index <= len(roles) else "body"
            layout, master = chains[index - 1] if index <= len(chains) else ("", "")
            slides.append(
                _summarize_slide(
                    slide,
                    index=index,
                    role=role,
                    layout_part=layout,
                    master_part=master,
                    slide_width=width,
                    slide_height=height,
                    issues=issues,
                )
            )
            slide_full_texts.append(
                "\n".join(filter(None, (_shape_text(shape) for shape in _iter_shapes(slide.shapes))))
            )
    except Exception as exc:
        _issue(issues, "error", "python-pptx-open", f"python-pptx could not open deck: {exc}")

    all_text = "\n".join(summary.title for summary in slides) + "\n"
    for slide in getattr(locals().get("presentation"), "slides", []):
        all_text += "\n".join(_shape_text(shape) for shape in _iter_shapes(slide.shapes)) + "\n"
    if not all_text.strip():
        _issue(issues, "error", "empty-text-roundtrip", "no text could be read back from the final deck")
    for required_text in cover_text or []:
        if required_text and required_text not in all_text:
            _issue(issues, "error", "missing-cover-text", f"cover text not found: {required_text!r}", 1)

    plan = _load_layout_plan(layout_plan_path, issues)
    if plan and len(plan) != inferred_body_count:
        _issue(issues, "error", "layout-plan-count", f"layout plan has {len(plan)} entries for {inferred_body_count} body slides")
    for offset, entry in enumerate(plan, 2):
        if offset - 1 >= len(slides):
            break
        message = str(entry.get("key_message") or entry.get("message") or "").strip()
        slide_text = slide_full_texts[offset - 1] if offset - 1 < len(slide_full_texts) else ""
        normalized_slide_text = re.sub(r"\s+", "", slide_text)
        if message and re.sub(r"\s+", "", message) not in normalized_slide_text:
            _issue(issues, "error", "missing-planned-text", f"planned key message was not preserved: {message!r}", offset)
        for item in entry.get("items", []):
            if not isinstance(item, (str, int, float)):
                continue
            item_text = str(item).strip()
            if item_text and re.sub(r"\s+", "", item_text) not in normalized_slide_text:
                _issue(
                    issues,
                    "error",
                    "missing-planned-item",
                    f"planned body item was not preserved: {item_text!r}",
                    offset,
                )

    if expect_body_notes:
        for summary in slides:
            if summary.role == "body" and summary.notes_chars == 0:
                _issue(issues, "error", "missing-speaker-notes", "expected body speaker notes are missing", summary.slide)

    slide_xml = b"\n".join(payload for name, payload in parts.items() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name))
    decoded_slide_xml = slide_xml.decode("utf-8", errors="replace")
    if re.search(r'typeface="(?:楷体|KaiTi)"', decoded_slide_xml, re.IGNORECASE):
        _issue(issues, "error", "cover-font", "KaiTi/楷体 remains in slide text runs")
    if "AB1F29" not in decoded_slide_xml.upper():
        _issue(issues, "warning", "brand-color", "GHB primary color #AB1F29 was not found in slide XML")
    for index, slide_part in enumerate(ordered_slides, 1):
        xml = parts.get(slide_part, b"").decode("utf-8", errors="replace")
        run_properties = re.findall(
            r"<a:rPr\b[^>]*(?:/>|>.*?</a:rPr>)",
            xml,
            re.DOTALL,
        )
        if any(
            "<a:noFill" in block or re.search(r'<a:alpha\s+val="0"', block)
            for block in run_properties
        ):
            _issue(issues, "warning", "possibly-invisible-text", "text run may have no fill or zero alpha", index)

    for left, right in zip(slides, slides[1:]):
        if left.title and left.title == right.title:
            _issue(issues, "warning", "adjacent-duplicate-title", f"adjacent slides repeat title {left.title!r}", right.slide)

    known_limitations: list[str] = []
    manual_review = [
        "Review typography, visual hierarchy, intentional overlaps, and aesthetic balance page by page.",
        "Confirm PowerPoint rendering on the target enterprise desktop environment.",
    ]
    if render_dir is None:
        known_limitations.append("No render directory was supplied; final visual appearance was not verified by this validation run.")
    else:
        pngs = sorted(render_dir.glob("slide-*.png")) if render_dir.is_dir() else []
        if len(pngs) != len(slides):
            _issue(issues, "warning", "render-count", f"render directory contains {len(pngs)} page PNGs for {len(slides)} slides")
        package_info["rendered_pages"] = len(pngs)
        render_report_path = render_dir / "render-report.json"
        if render_report_path.is_file():
            try:
                render_payload = json.loads(render_report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                _issue(issues, "warning", "invalid-render-report", str(exc))
            else:
                package_info["render"] = {
                    "renderer": render_payload.get("renderer"),
                    "page_count": render_payload.get("page_count"),
                    "passed": render_payload.get("passed"),
                }
                for warning in render_payload.get("warnings", []):
                    known_limitations.append(str(warning))
                    _issue(issues, "warning", "render-warning", str(warning))

    svg_quality: list[dict[str, Any]] = []
    for svg_report_path in svg_report_paths or []:
        try:
            svg_payload = json.loads(svg_report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _issue(issues, "error", "invalid-svg-report", f"{svg_report_path}: {exc}")
            continue
        summary = {
            "stage": svg_payload.get("stage"),
            "passed": svg_payload.get("passed"),
            "file_count": len(svg_payload.get("files", [])),
            "error_count": svg_payload.get("error_count", 0),
            "warning_count": svg_payload.get("warning_count", 0),
            "path": str(svg_report_path),
        }
        svg_quality.append(summary)
        if not svg_payload.get("passed"):
            _issue(issues, "error", "svg-quality-gate", f"SVG {summary['stage']} report failed with {summary['error_count']} errors")
    if svg_quality:
        package_info["svg_quality"] = svg_quality

    if readback_markdown_path is not None:
        if not readback_markdown_path.is_file():
            _issue(
                issues,
                "error",
                "missing-ppt-readback",
                f"ppt_to_md readback was not produced: {readback_markdown_path}",
            )
        else:
            try:
                readback = readback_markdown_path.read_text(encoding="utf-8")
            except OSError as exc:
                _issue(issues, "error", "invalid-ppt-readback", str(exc))
            else:
                readback_chars = len(re.sub(r"\s+", "", readback))
                readback_slides = len(re.findall(r"^## Slide \d+\s*$", readback, re.MULTILINE))
                package_info["ppt_readback"] = {
                    "path": str(readback_markdown_path),
                    "chars": readback_chars,
                    "slide_sections": readback_slides,
                }
                if readback_chars < 20:
                    _issue(issues, "error", "empty-ppt-readback", "ppt_to_md readback is empty")
                if readback_slides != len(slides):
                    _issue(
                        issues,
                        "error",
                        "ppt-readback-page-count",
                        f"ppt_to_md readback contains {readback_slides} slide sections for {len(slides)} pages",
                    )

    report = ValidationReport(
        pptx=str(path.resolve()),
        passed=not any(issue.severity == "error" for issue in issues),
        file_size=size,
        page_count=len(ordered_slides),
        body_count=inferred_body_count,
        has_ending=bool(expect_ending),
        slide_size=slide_size,
        issues=issues,
        slides=slides,
        package=package_info,
        known_limitations=known_limitations,
        manual_review=manual_review,
    )
    return report


def report_dict(report: ValidationReport) -> dict[str, Any]:
    return {
        **asdict(report),
        "error_count": len(report.errors),
        "warning_count": len(report.warnings),
    }


def markdown_report(report: ValidationReport) -> str:
    lines = [
        "# GHB PPTX Quality Report",
        "",
        f"- Result: **{'PASS' if report.passed else 'FAIL'}**",
        f"- File: `{report.pptx}`",
        f"- Pages: {report.page_count} (cover 1 / body {report.body_count} / ending {int(report.has_ending)})",
        f"- Errors: {len(report.errors)}",
        f"- Warnings: {len(report.warnings)}",
        "",
        "## Issues",
        "",
    ]
    if not report.issues:
        lines.append("No structural issues detected.")
    else:
        for issue in report.issues:
            where = f" slide {issue.slide}" if issue.slide else ""
            lines.append(f"- `{issue.severity.upper()}` `{issue.code}`{where}: {issue.message}")
    lines.extend([
        "",
        "## Per-slide object summary",
        "",
        "| Slide | Role | Text | Shapes | Groups | Pictures | Tables | Charts | Min font | OOB | Full image | Empty text | Overlaps | Page no. |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    svg_quality = report.package.get("svg_quality", [])
    if svg_quality:
        insertion = ["", "## SVG quality gates", ""]
        for item in svg_quality:
            insertion.append(
                f"- `{item['stage']}`: {'PASS' if item['passed'] else 'FAIL'}; "
                f"files={item['file_count']}, errors={item['error_count']}, warnings={item['warning_count']}"
            )
        # Keep the object table immediately after its heading; prepend this section.
        table_heading = lines.index("## Per-slide object summary")
        lines[table_heading:table_heading] = insertion
    for slide in report.slides:
        min_font = "" if slide.min_font_pt is None else f"{slide.min_font_pt:g}"
        lines.append(
            f"| {slide.slide} | {slide.role} | {slide.text_objects} | {slide.shape_objects} | "
            f"{slide.group_objects} | {slide.picture_objects} | {slide.table_objects} | "
            f"{slide.chart_objects} | {min_font} | {slide.out_of_bounds_objects} | "
            f"{slide.full_slide_pictures} | {slide.empty_text_boxes} | "
            f"{slide.possible_text_overlaps} | {'yes' if slide.page_number_found else 'no'} |"
        )
    lines.extend(["", "## Known limitations", ""])
    lines.extend(f"- {item}" for item in report.known_limitations)
    lines.extend(["", "## Manual review", ""])
    lines.extend(f"- {item}" for item in report.manual_review)
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--body-count", type=int)
    ending = parser.add_mutually_exclusive_group()
    ending.add_argument("--expect-ending", action="store_true")
    ending.add_argument("--no-ending", action="store_true")
    parser.add_argument("--source-svg-dir", type=Path)
    parser.add_argument("--layout-plan", type=Path)
    parser.add_argument("--cover-text", action="append", default=[])
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--expect-body-notes", action="store_true")
    parser.add_argument("--svg-report", type=Path, action="append", default=[])
    parser.add_argument("--readback-markdown", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    expect_ending = False if args.no_ending else True if args.expect_ending else None
    report = validate_pptx(
        args.pptx,
        expected_body_count=args.body_count,
        expect_ending=expect_ending,
        source_svg_dir=args.source_svg_dir,
        layout_plan_path=args.layout_plan,
        cover_text=args.cover_text,
        render_dir=args.render_dir,
        expect_body_notes=args.expect_body_notes,
        svg_report_paths=args.svg_report,
        readback_markdown_path=args.readback_markdown,
    )
    payload = report_dict(report)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"[{'PASS' if report.passed else 'FAIL'}] {args.pptx}")
        print(f"  pages={report.page_count} body={report.body_count} ending={int(report.has_ending)}")
        print(f"  errors={len(report.errors)} warnings={len(report.warnings)}")
        for issue in report.issues:
            where = f" slide={issue.slide}" if issue.slide else ""
            print(f"  {issue.severity.upper()} {issue.code}{where}: {issue.message}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
