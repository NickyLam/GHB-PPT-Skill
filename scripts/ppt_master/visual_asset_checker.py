#!/usr/bin/env python3
"""Validate SVG visual assets, collision contracts, and page content load.

This checker complements ``svg_quality_checker.py``.  It focuses on failures
that are easy to miss in XML-only validation: corrupt text, stretched icons,
bad or blurry images, out-of-canvas assets, declared-box collisions, and a
layout plan whose density does not match the rendered page.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET


SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
VECTOR_EXTENSIONS = {".svg", ".emf", ".wmf"}
CORRUPT_TEXT_MARKERS = ("\ufffd", "Ã", "Â", "â€", "ðŸ", "ï»¿")
DENSITY_LIMITS = {
    "breathing": (160, 12),
    "balanced": (300, 18),
    "dense": (520, 28),
}
LEGACY_DENSITY_LIMITS = {"anchor": DENSITY_LIMITS["balanced"]}
EXCLUDED_VISUAL_ROLES = {"background", "master", "header", "footer", "bleed", "chrome"}


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def intersection(self, other: "Box") -> float:
        width = min(self.x + self.width, other.x + other.width) - max(self.x, other.x)
        height = min(self.y + self.height, other.y + other.height) - max(self.y, other.y)
        return max(0.0, width) * max(0.0, height)


@dataclass(frozen=True)
class QAItem:
    label: str
    role: str
    box: Box
    collision_group: str
    allow_overlap: bool


@dataclass
class Result:
    path: Path
    errors: list[str]
    warnings: list[str]
    text_chars: int = 0
    text_elements: int = 0
    layout: Optional[str] = None

    @property
    def passed(self) -> bool:
        return not self.errors


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:px)?\s*", value)
    if not match:
        return None
    number = float(match.group(1))
    return number if math.isfinite(number) else None


def _viewbox(root: ET.Element) -> Optional[Box]:
    values = re.split(r"[\s,]+", root.get("viewBox", "").strip())
    if len(values) != 4:
        return None
    numbers = [_number(value) for value in values]
    return Box(*numbers) if all(value is not None for value in numbers) else None


def _box_from_element(elem: ET.Element) -> Optional[Box]:
    declared = elem.get("data-qa-box")
    if declared:
        values = re.split(r"[\s,]+", declared.strip())
        if len(values) != 4:
            return None
        numbers = [_number(value) for value in values]
        return Box(*numbers) if all(value is not None for value in numbers) else None
    values = [_number(elem.get(name)) for name in ("x", "y", "width", "height")]
    return Box(*values) if all(value is not None for value in values) else None


def _hidden(elem: ET.Element, inherited: bool = False) -> bool:
    style = {
        key.strip().lower(): value.strip().lower()
        for key, _, value in (item.partition(":") for item in elem.get("style", "").split(";"))
        if key.strip()
    }
    return inherited or (
        elem.get("display", "").lower() == "none"
        or elem.get("visibility", "").lower() == "hidden"
        or _number(elem.get("opacity")) == 0
        or style.get("display") == "none"
        or style.get("visibility") == "hidden"
        or style.get("opacity") == "0"
    )


def _semantic_role(elem: ET.Element) -> str:
    explicit = elem.get("data-qa-role", "").strip().lower()
    if explicit:
        return explicit
    identifier = (elem.get("id") or "").strip().lower().replace("_", "-")
    if identifier in {"bg", "bg-surface"}:
        return "background"
    for role in (*sorted(EXCLUDED_VISUAL_ROLES), "title", "body", "metric", "card"):
        if identifier == role or identifier.startswith(f"{role}-"):
            return role
    return "content"


def _clip_box(box: Box, canvas: Box) -> Optional[Box]:
    left = max(box.x, canvas.x)
    top = max(box.y, canvas.y)
    right = min(box.x + box.width, canvas.x + canvas.width)
    bottom = min(box.y + box.height, canvas.y + canvas.height)
    if right <= left or bottom <= top:
        return None
    return Box(left, top, right - left, bottom - top)


def _union_area(boxes: list[Box]) -> float:
    """Return exact union area for axis-aligned boxes."""
    xs = sorted({value for box in boxes for value in (box.x, box.x + box.width)})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (box.y, box.y + box.height)
            for box in boxes
            if box.x < right and box.x + box.width > left and box.height > 0
        )
        covered = 0.0
        if intervals:
            start, end = intervals[0]
            for interval_start, interval_end in intervals[1:]:
                if interval_start > end:
                    covered += end - start
                    start, end = interval_start, interval_end
                else:
                    end = max(end, interval_end)
            covered += end - start
        area += (right - left) * covered
    return area


def _measurement_box(elem: ET.Element) -> Optional[Box]:
    declared = _box_from_element(elem) if elem.get("data-qa-box") else None
    return declared or _shape_box(elem)


def measure_visible_geometry(svg_text: str) -> dict[str, Any]:
    """Extract immutable, policy-neutral visible geometry observations.

    Unsupported transforms and unknown text extents reduce coverage instead of
    being approximated. Semantic layout markers are deliberately ignored.
    """
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise ValueError(f"invalid-svg-geometry: malformed XML: {exc}") from exc
    if _local_name(root.tag) != "svg":
        raise ValueError("invalid-svg-geometry: root element must be svg")
    canvas = _viewbox(root)
    if canvas is None or canvas.width <= 0 or canvas.height <= 0:
        raise ValueError("invalid-svg-geometry: SVG requires a positive viewBox")

    body_canvas = canvas
    surface = next((node for node in root.iter() if node.get("id") == "bg-surface"), None)
    if surface is not None:
        surface_box = next(
            (_shape_box(node) for node in surface.iter() if _local_name(node.tag) == "rect"),
            None,
        )
        if surface_box and surface_box.width > 0 and surface_box.height > 0:
            body_canvas = surface_box

    scope = next(
        (
            node
            for node in root.iter()
            if _local_name(node.tag) == "g"
            and ((node.get("id") or "").startswith("layout-") or node.get("data-layout"))
        ),
        root,
    )
    observations: list[dict[str, Any]] = []
    raw_observations: list[dict[str, Any]] = []
    limitations: set[str] = set()
    text_sizes: list[dict[str, Any]] = []
    candidate_count = 0

    def collect_declared_text(elem: ET.Element, role: str, hidden: bool = False) -> None:
        hidden = _hidden(elem, hidden)
        if hidden:
            return
        child_role = _semantic_role(elem)
        if child_role == "content":
            child_role = role
        if _local_name(elem.tag) in {"text", "tspan"} and "".join(elem.itertext()).strip():
            size = _number(elem.get("font-size"))
            if size is not None and size > 0:
                text_sizes.append({"role": child_role, "font_size": size})
        for child in elem:
            collect_declared_text(child, child_role, hidden)

    def collect_explicit_titles(
        elem: ET.Element,
        inherited_role: str = "content",
        hidden: bool = False,
    ) -> None:
        """Include page titles that live outside the body layout scope."""
        hidden = _hidden(elem, hidden)
        if hidden:
            return
        role = _semantic_role(elem)
        if role == "content":
            role = inherited_role
        if (
            role == "title"
            and _local_name(elem.tag) in {"text", "tspan"}
            and "".join(elem.itertext()).strip()
        ):
            size = _number(elem.get("font-size"))
            if size is not None and size > 0:
                text_sizes.append({"role": "title", "font_size": size})
        for child in elem:
            collect_explicit_titles(child, role, hidden)

    def walk(
        elem: ET.Element,
        *,
        hidden: bool = False,
        excluded: bool = False,
        transformed: bool = False,
        inherited_role: str = "content",
    ) -> None:
        nonlocal candidate_count
        tag = _local_name(elem.tag)
        hidden = _hidden(elem, hidden)
        role = _semantic_role(elem)
        if role == "content" and inherited_role != "content":
            role = inherited_role
        excluded = excluded or role in EXCLUDED_VISUAL_ROLES or elem.get("data-allow-overflow", "").lower() in {"1", "true", "yes"}
        transformed = transformed or bool(elem.get("transform"))
        if hidden or excluded:
            return
        if transformed and not elem.get("data-qa-box"):
            if tag == "g" or any(True for _ in elem):
                limitations.add("transformed-group")
                candidate_count += 1
                return
            limitations.add(f"transformed-{tag}")
            candidate_count += 1
            return
        if tag in {"defs", "clipPath", "mask", "filter", "style"}:
            return

        qa_box = elem.get("data-qa-box")
        if tag in {"text", "tspan"}:
            text = "".join(elem.itertext()).strip()
            if text:
                size = _number(elem.get("font-size"))
                if size is not None and size > 0:
                    text_sizes.append({"role": role, "font_size": size})
                if not qa_box:
                    limitations.add("text-extent")
                    candidate_count += 1
                    return
        supported = qa_box is not None or tag in {
            "rect", "circle", "ellipse", "line", "polygon", "polyline", "image", "use"
        }
        if supported:
            candidate_count += 1
            box = _measurement_box(elem)
            if box is None or box.width < 0 or box.height < 0:
                raise ValueError(f"invalid-svg-geometry: invalid {tag} extent")
            clipped = _clip_box(box, body_canvas)
            shared = {
                "role": role,
                "focal": elem.get("data-focal", "").lower() == "true",
                "fill": (elem.get("fill") or "").strip().upper(),
                "tag": tag,
                "container": bool(
                    elem.get("data-component")
                    or elem.get("data-qa-peer-group")
                    or (elem.get("id") or "") in {"bg-surface", "content-field"}
                ),
                # GHB-owned additive metadata: authors can explicitly identify
                # the sibling components whose whitespace should be measured.
                # This avoids treating a card's internal text box as its peer.
                "peer_group": (elem.get("data-qa-peer-group") or "").strip() or None,
            }
            raw_observations.append(
                shared | {"box": [box.x, box.y, box.width, box.height]}
            )
            if clipped is not None:
                observations.append(
                    shared | {"box": [clipped.x, clipped.y, clipped.width, clipped.height]}
                )
            if qa_box:
                if tag not in {"text", "tspan"}:
                    collect_declared_text(elem, role, hidden)
                return
        elif tag not in {"svg", "g", "text", "tspan"}:
            candidate_count += 1
            limitations.add(tag)
            return
        for child in elem:
            walk(
                child,
                hidden=hidden,
                excluded=excluded,
                transformed=transformed,
                inherited_role=role,
            )

    walk(scope)
    collect_explicit_titles(root)
    measured = len(raw_observations)
    if measured == 0:
        status = "not-measurable"
    elif limitations:
        status = "partial"
    else:
        status = "supported"
    boxes = [Box(*item["box"]) for item in observations]
    content_boxes = [
        Box(*item["box"])
        for item in observations
        if not item.get("container")
    ]
    positive_boxes = [box for box in boxes if box.area > 0]
    gaps: list[float] = []
    grouped = {
        str(item["peer_group"])
        for item in observations
        if item.get("peer_group") and Box(*item["box"]).area > 0
    }
    if grouped:
        peer_sets = [
            [
                Box(*item["box"])
                for item in observations
                if item.get("peer_group") == group and Box(*item["box"]).area > 0
            ]
            for group in sorted(grouped)
        ]
    else:
        peer_sets = [positive_boxes]

    for peers in peer_sets:
        for index, left in enumerate(peers):
            distances = []
            for right_index, right in enumerate(peers):
                if index == right_index:
                    continue
                # Without an explicit peer group, intersecting boxes are most
                # often parent/child geometry (card plus internal text). They
                # are not sibling whitespace and must not collapse the metric
                # to zero. Collision validation remains responsible for real
                # unintended overlap.
                if not grouped and left.intersection(right) > 0:
                    continue
                dx = max(left.x - (right.x + right.width), right.x - (left.x + left.width), 0.0)
                dy = max(left.y - (right.y + right.height), right.y - (left.y + left.height), 0.0)
                distances.append(math.hypot(dx, dy))
            if distances:
                gaps.append(min(distances))
    return {
        "schema": "svg.geometry-observations.v1",
        "canvas": [canvas.x, canvas.y, canvas.width, canvas.height],
        "body_canvas": [body_canvas.x, body_canvas.y, body_canvas.width, body_canvas.height],
        "observations": observations,
        "raw_observations": raw_observations,
        "text_sizes": text_sizes,
        "gaps": gaps,
        "coverage": {
            "status": status,
            "measured_elements": measured,
            "candidate_elements": candidate_count,
            "ratio": round(measured / candidate_count, 6) if candidate_count else 0.0,
            "limitations": sorted(limitations),
        },
        "occupied_area": _union_area(boxes),
        "content_occupied_area": _union_area(content_boxes),
    }


def _outside(inner: Box, canvas: Box, tolerance: float = 0.5) -> bool:
    return (
        inner.x < canvas.x - tolerance
        or inner.y < canvas.y - tolerance
        or inner.x + inner.width > canvas.x + canvas.width + tolerance
        or inner.y + inner.height > canvas.y + canvas.height + tolerance
    )


def _href(elem: ET.Element) -> str:
    return elem.get("href") or elem.get(XLINK_HREF) or ""


def _decode_raster(href: str, svg_path: Path):
    """Return ``(width, height)`` or raise when a raster cannot be decoded."""
    from PIL import Image

    if href.startswith("data:"):
        header, encoded = href.split(",", 1)
        if ";base64" not in header:
            raise ValueError("image data URI is not base64 encoded")
        payload = base64.b64decode(encoded, validate=True)
        source = io.BytesIO(payload)
    else:
        source = (svg_path.parent / href).resolve()
        if not source.exists():
            raise FileNotFoundError(href)
    with Image.open(source) as image:
        image.verify()
    with Image.open(source) as image:
        return image.size


def _qa_item(elem: ET.Element, index: int) -> Optional[QAItem]:
    role = elem.get("data-qa-role", "").strip()
    if not role:
        return None
    box = _box_from_element(elem)
    if box is None:
        return None
    label = elem.get("id") or elem.get("data-icon") or f"{_local_name(elem.tag)}#{index}"
    return QAItem(
        label=label,
        role=role,
        box=box,
        collision_group=elem.get("data-qa-group", "content"),
        allow_overlap=elem.get("data-allow-overlap", "").lower() in {"1", "true", "yes"},
    )


def _check_text(root: ET.Element, result: Result) -> None:
    content_root = next((elem for elem in root.iter() if elem.get("data-layout")), root)

    def walk(elem: ET.Element, hidden: bool = False, in_content: bool = False) -> None:
        hidden = _hidden(elem, hidden)
        in_content = in_content or elem is content_root
        if _local_name(elem.tag) == "text" and not hidden:
            text_fit = (elem.get("data-text-fit") or "").strip().lower()
            if text_fit and text_fit != "fixed":
                result.errors.append(
                    f"text-fit-contract: {elem.get('id') or 'text'} uses unsupported "
                    f"data-text-fit={text_fit!r}"
                )
            elif text_fit == "fixed":
                box = _box_from_element(elem)
                if box is None or box.width <= 0 or box.height <= 0:
                    result.errors.append(
                        f"text-fit-contract: {elem.get('id') or 'text'} requires a "
                        "positive data-qa-box when data-text-fit='fixed'"
                    )
            text = "".join(elem.itertext()).strip()
            if not text:
                result.warnings.append("empty <text> element")
            else:
                markers = [marker for marker in CORRUPT_TEXT_MARKERS if marker in text]
                controls = [char for char in text if ord(char) < 32 and char not in "\t\n\r"]
                if markers or controls:
                    result.errors.append(f"corrupt/mojibake text detected: {text[:48]!r}")
                if in_content:
                    result.text_elements += 1
                    result.text_chars += len(re.sub(r"\s+", "", text))
        for child in elem:
            walk(child, hidden, in_content)

    walk(root)


def _check_images(root: ET.Element, path: Path, canvas: Box, stage: str, result: Result) -> None:
    for index, elem in enumerate(root.iter(), start=1):
        if _local_name(elem.tag) != "image":
            continue
        label = elem.get("id") or f"image#{index}"
        box = _box_from_element(elem)
        if box is None or box.width <= 0 or box.height <= 0:
            result.errors.append(f"{label}: image needs positive x/y/width/height")
            continue
        if _outside(box, canvas):
            result.errors.append(f"{label}: image box is outside viewBox")
        href = _href(elem)
        if not href:
            result.errors.append(f"{label}: image has no href")
            continue
        suffix = Path(href.split("?", 1)[0]).suffix.lower()
        is_vector = suffix in VECTOR_EXTENSIONS and not href.startswith("data:")
        if stage == "authored" and not is_vector:
            par = (elem.get("preserveAspectRatio") or "").strip()
            if not par or par == "none":
                result.errors.append(
                    f"{label}: raster image must declare preserveAspectRatio='xMidYMid meet|slice'"
                )
        if stage == "finalized" and not href.startswith("data:") and suffix not in {".emf", ".wmf"}:
            result.errors.append(f"{label}: finalized SVG still has external image href {href!r}")
        if is_vector:
            if not (path.parent / href).resolve().exists():
                result.errors.append(f"{label}: vector image file not found: {href}")
            continue
        try:
            actual_w, actual_h = _decode_raster(href, path)
        except ImportError:
            result.warnings.append(f"{label}: Pillow unavailable; raster decode check skipped")
            continue
        except Exception as exc:
            result.errors.append(f"{label}: unreadable image ({exc})")
            continue
        density = min(actual_w / box.width, actual_h / box.height)
        if density < 1.0:
            result.errors.append(
                f"{label}: low-resolution image {actual_w}x{actual_h} for {box.width:g}x{box.height:g} box"
            )
        elif density < 1.5:
            result.warnings.append(f"{label}: image pixel density is only {density:.2f}x")
        if stage == "finalized":
            source_ratio = actual_w / actual_h
            box_ratio = box.width / box.height
            if abs(source_ratio / box_ratio - 1.0) > 0.03:
                result.errors.append(f"{label}: finalized image aspect ratio is distorted")


def _check_icons(root: ET.Element, path: Path, icons_dir: Path, canvas: Box, stage: str, result: Result) -> None:
    for index, elem in enumerate(root.iter(), start=1):
        if _local_name(elem.tag) != "use" or not elem.get("data-icon"):
            continue
        name = elem.get("data-icon", "")
        label = elem.get("id") or f"icon {name!r}"
        if stage == "finalized":
            result.errors.append(f"{label}: unresolved <use data-icon> remains after finalize")
        box = _box_from_element(elem)
        if box is None or box.width <= 0 or box.height <= 0:
            result.errors.append(f"{label}: icon needs positive x/y/width/height")
            continue
        if _outside(box, canvas):
            result.errors.append(f"{label}: icon box is outside viewBox")
        if abs(box.width / box.height - 1.0) > 0.02:
            result.errors.append(f"{label}: icon box must be square; got {box.width:g}x{box.height:g}")
        if min(box.width, box.height) < 20:
            result.warnings.append(f"{label}: icon is smaller than 20px and may not be legible")
        if max(box.width, box.height) > 128:
            result.warnings.append(f"{label}: icon exceeds 128px; prefer an illustration for hero visuals")
        if "/" not in name:
            result.errors.append(f"{label}: icon name must include a library prefix")
            continue
        library, icon_name = name.split("/", 1)
        library = {"chunk": "chunk-filled"}.get(library, library)
        icon_path = icons_dir / library / f"{icon_name}.svg"
        if not icon_path.exists():
            result.errors.append(f"{label}: icon asset not found at {icon_path}")


def _shape_box(elem: ET.Element) -> Optional[Box]:
    tag = _local_name(elem.tag)
    if tag in {"image", "use"}:
        return _box_from_element(elem)
    if tag == "rect":
        x = _number(elem.get("x"))
        y = _number(elem.get("y"))
        if (elem.get("x") is not None and x is None) or (elem.get("y") is not None and y is None):
            return None
        x = x or 0.0
        y = y or 0.0
        width = _number(elem.get("width"))
        height = _number(elem.get("height"))
        return Box(x, y, width, height) if width is not None and height is not None else None
    if tag == "circle":
        cx, cy, radius = (_number(elem.get(name)) for name in ("cx", "cy", "r"))
        return Box(cx - radius, cy - radius, radius * 2, radius * 2) if None not in (cx, cy, radius) else None
    if tag == "ellipse":
        cx, cy, rx, ry = (_number(elem.get(name)) for name in ("cx", "cy", "rx", "ry"))
        return Box(cx - rx, cy - ry, rx * 2, ry * 2) if None not in (cx, cy, rx, ry) else None
    if tag == "line":
        x1, y1, x2, y2 = (_number(elem.get(name)) for name in ("x1", "y1", "x2", "y2"))
        if None not in (x1, y1, x2, y2):
            return Box(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
    if tag in {"polygon", "polyline"}:
        values = [_number(value) for value in re.split(r"[\s,]+", elem.get("points", "").strip())]
        if any(value is None for value in values):
            return None
        if len(values) >= 4 and len(values) % 2 == 0:
            xs, ys = values[0::2], values[1::2]
            return Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    return None


def _check_shape_bounds(root: ET.Element, canvas: Box, result: Result) -> None:
    """Catch structural geometry clipped by the slide canvas.

    Elements with transforms are skipped because their local coordinates need a
    full transform matrix. Authors can opt out for deliberate bleed with
    ``data-allow-overflow=true``.
    """
    counter = 0

    def walk(elem: ET.Element, local_coordinates: bool = False) -> None:
        nonlocal counter
        counter += 1
        tag = _local_name(elem.tag)
        local_coordinates = local_coordinates or bool(elem.get("transform")) or tag in {"defs", "clipPath"}
        allow = elem.get("data-allow-overflow", "").lower() in {"1", "true", "yes"}
        if not local_coordinates and not allow:
            box = _shape_box(elem)
            if box is not None:
                if box.width < 0 or box.height < 0:
                    result.errors.append(f"{elem.get('id') or tag}#{counter}: shape has negative size")
                elif _outside(box, canvas):
                    result.errors.append(
                        f"{elem.get('id') or tag}#{counter}: visible shape is outside viewBox; "
                        "fix geometry or mark deliberate bleed with data-allow-overflow='true'"
                    )
        for child in elem:
            walk(child, local_coordinates)

    walk(root)


def _check_collisions(root: ET.Element, canvas: Box, result: Result) -> None:
    items: list[QAItem] = []
    for index, elem in enumerate(root.iter(), start=1):
        item = _qa_item(elem, index)
        if not item:
            if elem.get("data-qa-role"):
                result.errors.append(
                    f"{elem.get('id') or _local_name(elem.tag)}: data-qa-role requires data-qa-box or x/y/width/height"
                )
            continue
        if item.box.width <= 0 or item.box.height <= 0:
            result.errors.append(f"{item.label}: QA box must have positive size")
        elif _outside(item.box, canvas):
            result.errors.append(f"{item.label}: QA box is outside viewBox")
        items.append(item)
    for left_index, left in enumerate(items):
        for right in items[left_index + 1 :]:
            if left.collision_group != right.collision_group or left.allow_overlap or right.allow_overlap:
                continue
            smaller = min(left.box.area, right.box.area)
            if smaller and left.box.intersection(right.box) / smaller >= 0.12:
                result.errors.append(
                    f"collision: {left.label} ({left.role}) overlaps {right.label} ({right.role}); "
                    "move one box or mark intentional layering with data-allow-overlap='true'"
                )


def _check_text_component_overflow(root: ET.Element, result: Result) -> None:
    """Reject declared single-line text whose visible copy cannot fit its QA box."""

    for index, elem in enumerate(root.iter(), start=1):
        if _local_name(elem.tag) != "text" or not elem.get("data-qa-box"):
            continue
        text = "".join(elem.itertext()).strip()
        if not text or list(elem):
            # Multiline tspan layouts are measured by their individual boxes.
            continue
        box = _box_from_element(elem)
        font_size = _number(elem.get("font-size"))
        if box is None or font_size is None or font_size <= 0:
            continue
        units = sum(
            1.0 if "\u3400" <= char <= "\u9fff" else (0.35 if char.isspace() else 0.58)
            for char in text
        )
        estimated_width = units * font_size * 1.05
        # Font metrics differ across Source Han Sans, Microsoft YaHei, WPS and
        # PowerPoint. A 1-2% estimate excess is normal and previously caused
        # near-capacity labels (for example 252px estimated in a 248px box) to
        # fail every real project. Reserve this deterministic error for a
        # material overflow: >5% (and >4px) horizontally, or a font size that
        # itself exceeds the declared single-line height by >8%.
        width_overflow = estimated_width > max(box.width * 1.05, box.width + 4.0)
        height_overflow = font_size > max(box.height * 1.08, box.height + 2.0)
        if width_overflow or height_overflow:
            label = elem.get("id") or f"text#{index}"
            result.errors.append(
                f"text-component-overflow: {label} needs approximately "
                f"{estimated_width:.1f}x{font_size:.1f}px inside "
                f"{box.width:.1f}x{box.height:.1f}px; shorten, wrap, or enlarge the slot"
            )


def _point_inside(box: Box, point: tuple[float, float], tolerance: float = 0.5) -> bool:
    return (
        box.x - tolerance <= point[0] <= box.x + box.width + tolerance
        and box.y - tolerance <= point[1] <= box.y + box.height + tolerance
    )


def _segment_intersects_box(
    start: tuple[float, float], end: tuple[float, float], box: Box
) -> bool:
    """Return whether a finite line segment crosses an axis-aligned box."""
    if _point_inside(box, start) or _point_inside(box, end):
        return True
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    lower, upper = 0.0, 1.0
    for p, q in (
        (-dx, x1 - box.x),
        (dx, box.x + box.width - x1),
        (-dy, y1 - box.y),
        (dy, box.y + box.height - y1),
    ):
        if abs(p) < 1e-9:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return False
    return True


def _check_flow_geometry(root: ET.Element, result: Result) -> None:
    """Validate opt-in process node/edge geometry before Office conversion.

    GHB authors mark nodes with ``data-flow-node`` plus ``data-qa-box`` and
    connector lines with ``data-flow-from``/``data-flow-to``. This local
    contract avoids guessing relationships from drawing order.
    """
    nodes: dict[str, Box] = {}
    text_boxes: list[tuple[str, Box]] = []
    for index, elem in enumerate(root.iter(), start=1):
        node_id = (elem.get("data-flow-node") or "").strip()
        if node_id:
            box = _box_from_element(elem)
            if not box or box.width <= 0 or box.height <= 0:
                result.errors.append(
                    f"flow-node-contract: {node_id!r} requires a positive data-qa-box"
                )
            elif node_id in nodes:
                result.errors.append(f"flow-node-contract: duplicate node {node_id!r}")
            else:
                nodes[node_id] = box
        if elem.get("data-qa-role", "").strip().lower() in {"text", "title", "label"}:
            box = _box_from_element(elem)
            if box:
                text_boxes.append((elem.get("id") or f"text#{index}", box))

    for index, elem in enumerate(root.iter(), start=1):
        source_id = (elem.get("data-flow-from") or "").strip()
        target_id = (elem.get("data-flow-to") or "").strip()
        if not source_id and not target_id:
            continue
        label = elem.get("id") or f"connector#{index}"
        if not source_id or not target_id or source_id == target_id:
            result.errors.append(
                f"flow-connector-contract: {label} needs distinct data-flow-from/data-flow-to"
            )
            continue
        source = nodes.get(source_id)
        target = nodes.get(target_id)
        if source is None or target is None:
            result.errors.append(
                f"flow-connector-contract: {label} references missing node(s) "
                f"{source_id!r}->{target_id!r}"
            )
            continue
        if _local_name(elem.tag) != "line":
            result.errors.append(
                f"flow-connector-contract: {label} must use an Office-safe line; "
                "arrowheads may be separate polygons"
            )
            continue
        values = [_number(elem.get(name)) for name in ("x1", "y1", "x2", "y2")]
        if any(value is None for value in values):
            result.errors.append(f"flow-connector-contract: {label} has invalid endpoints")
            continue
        x1, y1, x2, y2 = (float(value) for value in values)
        start, end = (x1, y1), (x2, y2)
        intersected_nodes = [
            node_id
            for node_id, node_box in nodes.items()
            if _segment_intersects_box(start, end, node_box)
        ]
        if intersected_nodes:
            result.errors.append(
                f"connector-node-intersection: {label} crosses node bound(s) "
                f"{intersected_nodes}"
            )
        visible_length = math.dist(start, end)
        if visible_length < 24.0:
            result.errors.append(
                f"connector-visible-length-low: {label} has only {visible_length:.1f}px "
                "of visible connector; require at least 24px"
            )
        for text_label, text_box in text_boxes:
            if _segment_intersects_box(start, end, text_box):
                result.errors.append(
                    f"connector-text-intersection: {label} crosses {text_label}"
                )


def _inside_box(inner: Box, outer: Box, tolerance: float = 0.5) -> bool:
    return not _outside(inner, outer, tolerance=tolerance)


def _check_component_contracts(root: ET.Element, result: Result) -> None:
    """Validate opt-in card slots and paired comparison alignment."""
    components: dict[str, tuple[ET.Element, Box]] = {}
    pair_members: dict[tuple[str, str], list[str]] = {}
    slots: dict[str, dict[str, Box]] = {}
    balance_modes: dict[str, str] = {}
    for elem in root.iter():
        component_kind = (elem.get("data-component") or "").strip()
        component_id = (elem.get("data-component-id") or "").strip()
        if not component_kind and not component_id:
            continue
        if not component_kind or not component_id:
            result.errors.append(
                "component-contract: data-component and data-component-id must appear together"
            )
            continue
        box = _box_from_element(elem)
        if not box or box.width <= 0 or box.height <= 0:
            result.errors.append(
                f"component-contract: {component_id!r} requires a positive data-qa-box"
            )
            continue
        if component_id in components:
            result.errors.append(f"component-contract: duplicate component {component_id!r}")
            continue
        components[component_id] = (elem, box)
        slots[component_id] = {}
        balance_mode = (elem.get("data-component-balance") or "").strip().lower()
        if balance_mode and balance_mode not in {"insets", "content-insets"}:
            result.errors.append(
                f"component-contract: {component_id!r} uses unsupported "
                f"data-component-balance={balance_mode!r}"
            )
        elif balance_mode:
            balance_modes[component_id] = balance_mode
        pair = (elem.get("data-component-pair") or "").strip()
        if pair:
            pair_members.setdefault((component_kind, pair), []).append(component_id)

    for elem in root.iter():
        parent_id = (elem.get("data-component-parent") or "").strip()
        slot = (elem.get("data-component-slot") or "").strip()
        if not parent_id and not slot:
            continue
        label = elem.get("id") or slot or _local_name(elem.tag)
        if not parent_id or not slot:
            result.errors.append(
                f"component-contract: {label} needs data-component-parent and data-component-slot"
            )
            continue
        parent = components.get(parent_id)
        child_box = _box_from_element(elem)
        if parent is None or child_box is None:
            result.errors.append(
                f"component-contract: {label} references missing parent or has no data-qa-box"
            )
            continue
        if not _inside_box(child_box, parent[1]):
            result.errors.append(
                f"component-slot-overflow: {label} exceeds component {parent_id!r}"
            )
        if slot in slots[parent_id]:
            result.errors.append(
                f"component-contract: component {parent_id!r} repeats slot {slot!r}"
            )
        else:
            slots[parent_id][slot] = child_box

    for (kind, pair), members in pair_members.items():
        if len(members) != 2:
            result.errors.append(
                f"component-balance-outlier: {kind} pair {pair!r} has {len(members)} members; expected 2"
            )
            continue
        left_id, right_id = members
        all_slots = sorted(set(slots[left_id]) | set(slots[right_id]))
        for slot in all_slots:
            left = slots[left_id].get(slot)
            right = slots[right_id].get(slot)
            if left is None or right is None:
                result.errors.append(
                    f"component-balance-outlier: pair {pair!r} slot {slot!r} is missing on one side"
                )
                continue
            if abs(left.y - right.y) > 24.0 or abs(left.height - right.height) > 24.0:
                result.errors.append(
                    f"component-balance-outlier: pair {pair!r} slot {slot!r} differs by more than 24px"
                )

    # GHB-owned opt-in contract for repeated cards. The union of declared
    # internal slots must be centered inside each card. ``insets`` additionally
    # requires a shared grid across peers; ``content-insets`` intentionally
    # permits widths to follow measured copy so each icon+copy group can be
    # centered independently. Explicit slot geometry is used instead of
    # guessing glyph ink bounds, which vary across Office renderers.
    inset_tolerance = 4.0
    inset_groups: dict[str, list[tuple[str, tuple[float, float, float, float]]]] = {}
    for component_id, balance_mode in balance_modes.items():
        if balance_mode not in {"insets", "content-insets"}:
            continue
        slot_boxes = list(slots[component_id].values())
        if not slot_boxes:
            result.errors.append(
                f"component-inset-outlier: {component_id!r} declares inset balance "
                "but has no component slots"
            )
            continue
        component_elem, component_box = components[component_id]
        content_left = min(box.x for box in slot_boxes)
        content_top = min(box.y for box in slot_boxes)
        content_right = max(box.x + box.width for box in slot_boxes)
        content_bottom = max(box.y + box.height for box in slot_boxes)
        insets = (
            content_left - component_box.x,
            component_box.x + component_box.width - content_right,
            content_top - component_box.y,
            component_box.y + component_box.height - content_bottom,
        )
        left, right, top, bottom = insets
        if abs(left - right) > inset_tolerance or abs(top - bottom) > inset_tolerance:
            result.errors.append(
                f"component-inset-outlier: {component_id!r} has "
                f"left/right/top/bottom insets {left:.1f}/{right:.1f}/{top:.1f}/{bottom:.1f}px"
            )
        if balance_mode == "insets":
            component_kind = (component_elem.get("data-component") or "").strip()
            inset_groups.setdefault(component_kind, []).append((component_id, insets))

    for component_kind, records in inset_groups.items():
        reference_id, reference = records[0]
        for component_id, insets in records[1:]:
            if any(
                abs(current - expected) > inset_tolerance
                for current, expected in zip(insets, reference)
            ):
                result.errors.append(
                    f"component-inset-outlier: {component_kind} components "
                    f"{reference_id!r} and {component_id!r} use inconsistent inset grids"
                )


def check_svg(path: Path, *, stage: str, icons_dir: Path) -> Result:
    result = Result(path=path, errors=[], warnings=[])
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        result.errors.append(f"invalid SVG: {exc}")
        return result
    canvas = _viewbox(root)
    if canvas is None or canvas.width <= 0 or canvas.height <= 0:
        result.errors.append("missing or invalid viewBox")
        return result
    actual_stage = stage
    if stage == "auto":
        hrefs = [_href(elem) for elem in root.iter() if _local_name(elem.tag) == "image"]
        has_icons = any(_local_name(elem.tag) == "use" and elem.get("data-icon") for elem in root.iter())
        actual_stage = "finalized" if (hrefs and all(href.startswith("data:") for href in hrefs) and not has_icons) else "authored"
    _check_text(root, result)
    _check_images(root, path, canvas, actual_stage, result)
    _check_icons(root, path, icons_dir, canvas, actual_stage, result)
    _check_shape_bounds(root, canvas, result)
    _check_collisions(root, canvas, result)
    _check_text_component_overflow(root, result)
    _check_flow_geometry(root, result)
    _check_component_contracts(root, result)
    for elem in root.iter():
        layout = elem.get("data-layout")
        if layout:
            result.layout = layout
            break
    return result


def _discover(target: Path, stage: str) -> tuple[list[Path], Optional[Path]]:
    if target.is_file():
        return [target], None
    if stage == "finalized" and (target / "svg_final").is_dir():
        svg_dir = target / "svg_final"
    elif (target / "svg_output").is_dir():
        svg_dir = target / "svg_output"
    elif stage == "auto" and (target / "svg_final").is_dir():
        svg_dir = target / "svg_final"
    else:
        svg_dir = target
    plan = target / "layout_plan.json" if (target / "layout_plan.json").exists() else None
    return sorted(svg_dir.glob("*.svg")), plan


def _apply_content_plan(results: list[Result], plan_path: Optional[Path]) -> list[str]:
    if not plan_path:
        return []
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        entries = {int(item["slide"]): item for item in plan}
    except Exception as exc:
        return [f"layout_plan.json is invalid: {exc}"]
    project_errors: list[str] = []
    seen: set[int] = set()
    for result in results:
        match = re.match(r"(\d+)", result.path.name)
        if not match:
            result.errors.append("filename must start with the slide number")
            continue
        slide = int(match.group(1))
        seen.add(slide)
        entry = entries.get(slide)
        if not entry:
            result.errors.append(f"slide {slide} is missing from layout_plan.json")
            continue
        planned_layout = entry.get("layout_archetype")
        if result.layout != planned_layout:
            result.errors.append(f"data-layout {result.layout!r} does not match plan {planned_layout!r}")
        page_schema = entry.get("page_schema")
        density = page_schema.get("density") if isinstance(page_schema, dict) else entry.get("density")
        limits = DENSITY_LIMITS.get(density) or (
            LEGACY_DENSITY_LIMITS.get(density) if not isinstance(page_schema, dict) else None
        )
        if not limits:
            result.errors.append(f"unknown density {density!r}; use breathing/balanced/dense")
            continue
        char_limit, text_limit = limits
        if result.text_chars > char_limit:
            result.errors.append(
                f"{density} page has {result.text_chars} text chars (limit {char_limit}); split or shorten content"
            )
        if result.text_elements > text_limit:
            result.errors.append(
                f"{density} page has {result.text_elements} text elements (limit {text_limit}); consolidate or split"
            )
        if result.text_chars == 0:
            result.errors.append("planned page has no visible content")
        elif result.text_chars < 18:
            result.warnings.append("page may be too thin: fewer than 18 visible text characters")
    missing = sorted(set(entries) - seen)
    if missing:
        project_errors.append(f"layout_plan.json has no SVG for slides: {missing}")
    return project_errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="SVG file, SVG directory, or project directory")
    parser.add_argument("--stage", choices=("auto", "authored", "finalized"), default="auto")
    parser.add_argument(
        "--icons-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "templates" / "icons",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    files, plan_path = _discover(args.target, args.stage)
    if not files:
        print(f"No SVG files found under {args.target}", file=sys.stderr)
        return 2
    results = [check_svg(path, stage=args.stage, icons_dir=args.icons_dir) for path in files]
    project_errors = _apply_content_plan(results, plan_path)
    payload = {
        "passed": not project_errors and all(result.passed for result in results),
        "files": [
            {
                "file": str(result.path),
                "passed": result.passed,
                "layout": result.layout,
                "text_chars": result.text_chars,
                "text_elements": result.text_elements,
                "errors": result.errors,
                "warnings": result.warnings,
            }
            for result in results
        ],
        "project_errors": project_errors,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            print(f"[{status}] {result.path.name} — {result.text_chars} chars / {result.text_elements} text elements")
            for message in result.errors:
                print(f"  ERROR: {message}")
            for message in result.warnings:
                print(f"  WARN: {message}")
        for message in project_errors:
            print(f"PROJECT ERROR: {message}")
        print(f"Summary: {sum(result.passed for result in results)}/{len(results)} SVGs passed")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
