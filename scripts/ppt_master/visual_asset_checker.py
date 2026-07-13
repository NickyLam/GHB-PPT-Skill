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
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from xml.etree import ElementTree as ET


SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
VECTOR_EXTENSIONS = {".svg", ".emf", ".wmf"}
CORRUPT_TEXT_MARKERS = ("\ufffd", "Ã", "Â", "â€", "ðŸ", "ï»¿")
DENSITY_LIMITS = {
    "breathing": (160, 12),
    "anchor": (300, 18),
    "dense": (520, 28),
}


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
    return float(match.group(1)) if match else None


def _viewbox(root: ET.Element) -> Optional[Box]:
    values = re.split(r"[\s,]+", root.get("viewBox", "").strip())
    if len(values) != 4:
        return None
    try:
        return Box(*map(float, values))
    except ValueError:
        return None


def _box_from_element(elem: ET.Element) -> Optional[Box]:
    declared = elem.get("data-qa-box")
    if declared:
        values = re.split(r"[\s,]+", declared.strip())
        if len(values) != 4:
            return None
        try:
            return Box(*map(float, values))
        except ValueError:
            return None
    values = [_number(elem.get(name)) for name in ("x", "y", "width", "height")]
    return Box(*values) if all(value is not None for value in values) else None


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
    for elem in root.iter():
        if _local_name(elem.tag) != "text":
            continue
        text = "".join(elem.itertext()).strip()
        if not text:
            result.warnings.append("empty <text> element")
            continue
        markers = [marker for marker in CORRUPT_TEXT_MARKERS if marker in text]
        controls = [char for char in text if ord(char) < 32 and char not in "\t\n\r"]
        if markers or controls:
            result.errors.append(f"corrupt/mojibake text detected: {text[:48]!r}")
    for elem in content_root.iter():
        if _local_name(elem.tag) != "text":
            continue
        text = "".join(elem.itertext()).strip()
        if text:
            result.text_elements += 1
            result.text_chars += len(re.sub(r"\s+", "", text))


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
    if tag == "rect":
        x = _number(elem.get("x")) or 0.0
        y = _number(elem.get("y")) or 0.0
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
        try:
            values = [float(value) for value in re.split(r"[\s,]+", elem.get("points", "").strip())]
        except ValueError:
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
        density = entry.get("density")
        limits = DENSITY_LIMITS.get(density)
        if not limits:
            result.errors.append(f"unknown density {density!r}; use breathing/anchor/dense")
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
        if result.text_chars < 18:
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
