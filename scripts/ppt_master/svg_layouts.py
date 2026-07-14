"""Office-safe SVG business layout fragments for PPT body slides.

The functions in this module intentionally emit a conservative SVG subset:
groups, rectangles, polygons, lines, text, and tspans.  The output is meant to
be pasted under the standard GHB page chrome and then passed through the
existing SVG-to-PPT pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import math
from typing import Callable


PRIMARY = "#AB1F29"
SECONDARY = "#44546A"
TEXT = "#2B2B2B"
TEXT_SECONDARY = "#6E6E73"
BORDER = "#E0E0E0"
SURFACE = "#F6F6F7"
WHITE = "#FFFFFF"
FONT = "'Microsoft YaHei', Arial, sans-serif"


@dataclass(frozen=True)
class LayoutSpec:
    """Parameters for one reusable SVG business-layout fragment."""

    archetype: str
    items: list[str]
    title: str = ""
    x: int = 120
    y: int = 220
    width: int = 1040
    height: int = 400
    density: str | None = None
    variant: str | None = None
    emphasis: str | None = None
    focal_index: int | None = None
    focal_target: str | None = None


def render_layout(spec: LayoutSpec) -> str:
    """Render an Office-safe SVG group for a supported layout archetype."""

    renderers: dict[str, Callable[[LayoutSpec], str]] = {
        "pyramid": _render_pyramid,
        "waterfall": _render_waterfall,
        "staircase": _render_staircase,
        "layered_arch": _render_layered_arch,
        "matrix": _render_matrix,
        "timeline": _render_timeline,
        "funnel": _render_funnel,
        "flywheel": _render_flywheel,
        "swimlane": _render_swimlane,
        "iceberg": _render_iceberg,
    }
    try:
        renderer = renderers[spec.archetype]
    except KeyError as exc:
        raise ValueError(f"Unsupported layout archetype: {spec.archetype}") from exc
    return renderer(_normalized(spec))


def _normalized(spec: LayoutSpec) -> LayoutSpec:
    items = [str(item).strip() for item in spec.items if str(item).strip()]
    if not items:
        items = ["核心要点"]
    focal_target = spec.focal_target.strip() if spec.focal_target else None
    focal_index = spec.focal_index
    if focal_index is None and focal_target is not None:
        try:
            focal_index = items.index(focal_target)
        except ValueError as exc:
            raise ValueError("invalid-layout-focal-target: focal target must match a visible item") from exc
    normalized = LayoutSpec(
        archetype=spec.archetype,
        items=items,
        title=spec.title.strip(),
        x=spec.x,
        y=spec.y,
        width=spec.width,
        height=spec.height,
        density=spec.density,
        variant=spec.variant,
        emphasis=spec.emphasis,
        focal_index=focal_index,
        focal_target=focal_target,
    )
    _validate_pilot_intent(normalized)
    return normalized


def _pilot_enabled(spec: LayoutSpec) -> bool:
    return any(
        value is not None
        for value in (spec.density, spec.variant, spec.emphasis, spec.focal_index, spec.focal_target)
    )


def _validate_pilot_intent(spec: LayoutSpec) -> None:
    if not _pilot_enabled(spec):
        return
    if spec.archetype not in {"timeline", "matrix"}:
        raise ValueError("pilot-layout-family-unsupported: only timeline and matrix accept visual intent")
    if spec.density not in {None, "breathing", "balanced", "dense"}:
        raise ValueError("invalid-layout-density: expected breathing, balanced, or dense")
    variants = {
        "timeline": {None, "timeline/default", "timeline/editorial", "timeline/phased"},
        "matrix": {None, "matrix/default", "matrix/comparison", "matrix/spotlight"},
    }
    if spec.variant not in variants[spec.archetype]:
        raise ValueError(f"invalid-layout-variant: {spec.variant!r} does not belong to {spec.archetype}")
    if spec.emphasis not in {None, "single-focal", "ranked", "distributed"}:
        raise ValueError("invalid-layout-emphasis: unsupported emphasis intent")
    max_items = 6 if spec.archetype == "timeline" else 4
    if len(spec.items) > max_items:
        raise ValueError(
            f"layout-budget-items-exceeded: {spec.archetype} supports at most {max_items} pilot items"
        )
    if any(len(item) > 80 for item in spec.items):
        raise ValueError("layout-budget-text-exceeded: a pilot item exceeds 80 characters")
    if spec.focal_index is not None and not 0 <= spec.focal_index < len(spec.items):
        raise ValueError("invalid-layout-focal-index: focal index must identify a visible item")
    if spec.emphasis == "single-focal" and spec.focal_index is None and not spec.focal_target:
        raise ValueError("missing-layout-focal-target: single-focal requires focal intent")


def _group(spec: LayoutSpec, body: list[str]) -> str:
    title = _title(spec)
    content = "\n  ".join([title, *body] if title else body)
    intent = ""
    if _pilot_enabled(spec):
        density = spec.density or "balanced"
        variant = spec.variant or f"{spec.archetype}/default"
        emphasis = spec.emphasis or "ranked"
        intent = (
            f' data-density="{density}" data-variant="{variant}" '
            f'data-emphasis="{emphasis}"'
        )
    return (
        f'<g id="layout-{spec.archetype}" data-layout="{spec.archetype}"{intent} '
        f'font-family="{FONT}">\n  {content}\n</g>'
    )


def _title(spec: LayoutSpec) -> str:
    if not spec.title:
        return ""
    return (
        f'<text x="{spec.x}" y="{spec.y - 28}" font-size="20" font-weight="bold" '
        f'fill="{TEXT}">{_xml(spec.title)}</text>'
    )


def _render_pyramid(spec: LayoutSpec) -> str:
    count = len(spec.items)
    layer_h = spec.height / count
    cx = spec.x + spec.width / 2
    body: list[str] = []
    for idx, label in enumerate(reversed(spec.items)):
        y1 = spec.y + idx * layer_h
        y2 = spec.y + (idx + 1) * layer_h - 6
        top_w = spec.width * (0.28 + 0.72 * idx / count)
        bottom_w = spec.width * (0.28 + 0.72 * (idx + 1) / count)
        fill = PRIMARY if idx == 0 else SURFACE
        stroke = PRIMARY if idx == 0 else BORDER
        text_fill = WHITE if idx == 0 else TEXT
        points = [
            (cx - top_w / 2, y1),
            (cx + top_w / 2, y1),
            (cx + bottom_w / 2, y2),
            (cx - bottom_w / 2, y2),
        ]
        body.append(
            f'<polygon points="{_points(points)}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
        )
        body.extend(
            _wrapped_text(label, cx, (y1 + y2) / 2, min(top_w, bottom_w) - 32, 18, text_fill)
        )
    return _group(spec, body)


def _render_waterfall(spec: LayoutSpec) -> str:
    count = len(spec.items)
    gap = 24
    step_w = (spec.width - gap * (count - 1)) / count
    base_y = spec.y + spec.height - 92
    body: list[str] = []
    for idx, label in enumerate(spec.items):
        x = spec.x + idx * (step_w + gap)
        y = base_y - idx * 34
        fill = PRIMARY if idx == count - 1 else SURFACE
        text_fill = WHITE if idx == count - 1 else TEXT
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{step_w:.1f}" height="92" rx="10" '
            f'fill="{fill}" stroke="{BORDER}" stroke-width="1"/>'
        )
        body.extend(
            _wrapped_text(label, x + step_w / 2, y + 46, step_w - 24, 17, text_fill)
        )
        if idx < count - 1:
            ax1 = x + step_w + 6
            ay = y + 46
            ax2 = x + step_w + gap - 8
            body.append(
                f'<line x1="{ax1:.1f}" y1="{ay:.1f}" x2="{ax2:.1f}" y2="{ay - 20:.1f}" '
                f'stroke="{SECONDARY}" stroke-width="2"/>'
            )
            body.append(
                f'<polygon points="{ax2:.1f},{ay - 20:.1f} {ax2 - 11:.1f},{ay - 14:.1f} '
                f'{ax2 - 4:.1f},{ay - 4:.1f}" fill="{SECONDARY}"/>'
            )
    return _group(spec, body)


def _render_staircase(spec: LayoutSpec) -> str:
    count = len(spec.items)
    gap = 16
    step_w = (spec.width - gap * (count - 1)) / count
    body: list[str] = []
    for idx, label in enumerate(spec.items):
        h = 84 + idx * 32
        x = spec.x + idx * (step_w + gap)
        y = spec.y + spec.height - h
        fill = PRIMARY if idx == count - 1 else SURFACE
        text_fill = WHITE if idx == count - 1 else TEXT
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{step_w:.1f}" height="{h:.1f}" rx="10" '
            f'fill="{fill}" stroke="{BORDER}" stroke-width="1"/>'
        )
        body.append(
            f'<text x="{x + 18:.1f}" y="{y + 32:.1f}" font-size="15" fill="{TEXT_SECONDARY}">'
            f'{idx + 1:02d}</text>'
        )
        body.extend(
            _wrapped_text(label, x + step_w / 2, y + h / 2 + 4, step_w - 24, 17, text_fill)
        )
    return _group(spec, body)


def _render_layered_arch(spec: LayoutSpec) -> str:
    count = len(spec.items)
    gap = 14
    layer_h = (spec.height - gap * (count - 1)) / count
    body: list[str] = []
    for idx, label in enumerate(reversed(spec.items)):
        x = spec.x + idx * 18
        y = spec.y + idx * (layer_h + gap)
        w = spec.width - idx * 36
        fill = PRIMARY if idx == count - 1 else SURFACE
        text_fill = WHITE if idx == count - 1 else TEXT
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{layer_h:.1f}" rx="12" '
            f'fill="{fill}" stroke="{BORDER}" stroke-width="1"/>'
        )
        body.extend(
            _wrapped_text(
                label, x + 28, y + layer_h / 2, w - 56, 18, text_fill, anchor="start"
            )
        )
    return _group(spec, body)


def _render_matrix(spec: LayoutSpec) -> str:
    if _pilot_enabled(spec):
        return _render_matrix_pilot(spec)
    labels = spec.items[:4]
    while len(labels) < 4:
        labels.append("")
    cell_w = spec.width / 2
    cell_h = spec.height / 2
    body = [
        f'<line x1="{spec.x + cell_w:.1f}" y1="{spec.y}" x2="{spec.x + cell_w:.1f}" '
        f'y2="{spec.y + spec.height}" stroke="{BORDER}" stroke-width="2"/>',
        f'<line x1="{spec.x}" y1="{spec.y + cell_h:.1f}" x2="{spec.x + spec.width}" '
        f'y2="{spec.y + cell_h:.1f}" stroke="{BORDER}" stroke-width="2"/>',
    ]
    for idx, label in enumerate(labels):
        col = idx % 2
        row = idx // 2
        x = spec.x + col * cell_w
        y = spec.y + row * cell_h
        fill = PRIMARY if idx == 1 else SURFACE
        text_fill = WHITE if idx == 1 else TEXT
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w:.1f}" height="{cell_h:.1f}" rx="10" '
            f'fill="{fill}" fill-opacity="0.92" stroke="{BORDER}" stroke-width="1"/>'
        )
        if label:
            body.extend(
                _wrapped_text(label, x + cell_w / 2, y + cell_h / 2, cell_w - 40, 18, text_fill)
            )
    return _group(spec, body)


def _render_matrix_pilot(spec: LayoutSpec) -> str:
    labels = list(spec.items)
    while len(labels) < 4:
        labels.append("")
    focal = spec.focal_index if spec.focal_index is not None else 1
    focal_col = focal % 2
    focal_row = focal // 2
    density = spec.density or "balanced"
    gap = {"breathing": 22.0, "balanced": 14.0, "dense": 8.0}[density]
    if spec.variant in {"matrix/comparison", "matrix/spotlight"} or spec.emphasis == "single-focal":
        focal_share = 0.60
    else:
        focal_share = 0.52
    usable_w = spec.width - gap
    focal_w = usable_w * focal_share
    other_w = usable_w - focal_w
    col_widths = [other_w, focal_w] if focal_col == 1 else [focal_w, other_w]
    usable_h = spec.height - gap
    focal_h = usable_h * (0.56 if spec.emphasis == "single-focal" else 0.50)
    other_h = usable_h - focal_h
    row_heights = [other_h, focal_h] if focal_row == 1 else [focal_h, other_h]
    xs = [spec.x, spec.x + col_widths[0] + gap]
    ys = [spec.y, spec.y + row_heights[0] + gap]
    body: list[str] = []
    for idx, label in enumerate(labels):
        col, row = idx % 2, idx // 2
        x, y = xs[col], ys[row]
        w, h = col_widths[col], row_heights[row]
        is_focal = idx == focal
        fill = PRIMARY if is_focal else SURFACE
        text_fill = WHITE if is_focal else TEXT
        focal_attr = ' data-focal="true"' if is_focal else ""
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12"'
            f'{focal_attr} fill="{fill}" stroke="{PRIMARY if is_focal else BORDER}" stroke-width="{2 if is_focal else 1}"/>'
        )
        if label:
            size = 21 if is_focal else 17
            body.extend(_wrapped_text(label, x + w / 2, y + h / 2, w - 40, size, text_fill))
    return _group(spec, body)


def _render_timeline(spec: LayoutSpec) -> str:
    if _pilot_enabled(spec):
        return _render_timeline_pilot(spec)
    count = len(spec.items)
    step = spec.width / max(count - 1, 1)
    y_line = spec.y + spec.height / 2
    body = [
        f'<line x1="{spec.x}" y1="{y_line:.1f}" x2="{spec.x + spec.width}" y2="{y_line:.1f}" '
        f'stroke="{SECONDARY}" stroke-width="3"/>'
    ]
    for idx, label in enumerate(spec.items):
        x = spec.x + idx * step if count > 1 else spec.x + spec.width / 2
        fill = PRIMARY if idx == count - 1 else WHITE
        text_fill = WHITE if idx == count - 1 else PRIMARY
        body.append(
            f'<rect x="{x - 22:.1f}" y="{y_line - 22:.1f}" width="44" height="44" rx="22" '
            f'fill="{fill}" stroke="{PRIMARY}" stroke-width="2"/>'
        )
        body.append(
            f'<text x="{x:.1f}" y="{y_line + 7:.1f}" text-anchor="middle" font-size="16" '
            f'font-weight="bold" fill="{text_fill}">{idx + 1}</text>'
        )
        label_y = y_line + 72 if idx % 2 == 0 else y_line - 56
        body.extend(
            _wrapped_text(label, x, label_y, min(190, step * 0.86), 16, TEXT)
        )
    return _group(spec, body)


def _render_timeline_pilot(spec: LayoutSpec) -> str:
    count = len(spec.items)
    density = spec.density or "balanced"
    side_pad = {"breathing": 70.0, "balanced": 42.0, "dense": 20.0}[density]
    usable_w = spec.width - 2 * side_pad
    step = usable_w / max(count - 1, 1)
    y_line = spec.y + spec.height * ({"breathing": 0.46, "balanced": 0.50, "dense": 0.56}[density])
    focal = spec.focal_index if spec.focal_index is not None else count - 1
    body = [
        f'<line x1="{spec.x + side_pad:.1f}" y1="{y_line:.1f}" '
        f'x2="{spec.x + spec.width - side_pad:.1f}" y2="{y_line:.1f}" '
        f'stroke="{SECONDARY}" stroke-width="3"/>'
    ]
    base_size = {"breathing": 56.0, "balanced": 48.0, "dense": 40.0}[density]
    for idx, label in enumerate(spec.items):
        x = spec.x + side_pad + (idx * step if count > 1 else usable_w / 2)
        is_focal = idx == focal and spec.emphasis == "single-focal"
        size = base_size * (1.36 if is_focal else 1.0)
        fill = PRIMARY if is_focal else WHITE
        text_fill = WHITE if is_focal else PRIMARY
        focal_attr = ' data-focal="true"' if is_focal else ""
        body.append(
            f'<rect x="{x - size / 2:.1f}" y="{y_line - size / 2:.1f}" '
            f'width="{size:.1f}" height="{size:.1f}" rx="{size / 2:.1f}"{focal_attr} '
            f'fill="{fill}" stroke="{PRIMARY}" stroke-width="{3 if is_focal else 2}"/>'
        )
        body.append(
            f'<text x="{x:.1f}" y="{y_line + 6:.1f}" text-anchor="middle" font-size="16" '
            f'font-weight="bold" fill="{text_fill}">{idx + 1}</text>'
        )
        alternating = spec.variant != "timeline/phased"
        label_y = y_line + size / 2 + 42 if not alternating or idx % 2 == 0 else y_line - size / 2 - 26
        body.extend(_wrapped_text(label, x, label_y, min(210, max(120, step * 0.82)), 17 if is_focal else 16, TEXT))
    return _group(spec, body)


def _render_funnel(spec: LayoutSpec) -> str:
    count = len(spec.items)
    cx = spec.x + spec.width / 2
    top_width = spec.width
    min_width = spec.width * 0.34
    segment_h = (spec.height - 10 * (count - 1)) / count
    body: list[str] = []
    for idx, label in enumerate(spec.items):
        y1 = spec.y + idx * (segment_h + 10)
        y2 = y1 + segment_h
        top_w = top_width - (top_width - min_width) * idx / count
        bottom_w = top_width - (top_width - min_width) * (idx + 1) / count
        fill = PRIMARY if idx == count - 1 else SURFACE
        text_fill = WHITE if idx == count - 1 else TEXT
        points = [
            (cx - top_w / 2, y1),
            (cx + top_w / 2, y1),
            (cx + bottom_w / 2, y2),
            (cx - bottom_w / 2, y2),
        ]
        body.append(
            f'<polygon points="{_points(points)}" fill="{fill}" stroke="{BORDER}" stroke-width="1"/>'
        )
        body.extend(
            _wrapped_text(label, cx, (y1 + y2) / 2, min(top_w, bottom_w) - 36, 18, text_fill)
        )
    return _group(spec, body)


def _render_flywheel(spec: LayoutSpec) -> str:
    count = len(spec.items)
    cx = spec.x + spec.width / 2
    cy = spec.y + spec.height / 2
    radius_x = spec.width * 0.34
    radius_y = spec.height * 0.32
    box_w = min(170, spec.width * 0.24)
    box_h = 58
    nodes: list[tuple[float, float, str]] = []
    for idx, label in enumerate(spec.items):
        angle = -math.pi / 2 + idx * (2 * math.pi / count)
        nodes.append((cx + math.cos(angle) * radius_x, cy + math.sin(angle) * radius_y, label))

    body = [
        f'<rect x="{cx - 82:.1f}" y="{cy - 34:.1f}" width="164" height="68" rx="34" '
        f'fill="{PRIMARY}" stroke="{PRIMARY}" stroke-width="1"/>',
        f'<text x="{cx:.1f}" y="{cy + 7:.1f}" text-anchor="middle" font-size="18" '
        f'font-weight="bold" fill="{WHITE}">正向循环</text>',
    ]
    for idx, (nx, ny, label) in enumerate(nodes):
        fill = SURFACE if idx < count - 1 else WHITE
        body.append(
            f'<rect x="{nx - box_w / 2:.1f}" y="{ny - box_h / 2:.1f}" width="{box_w:.1f}" '
            f'height="{box_h}" rx="18" fill="{fill}" stroke="{PRIMARY}" stroke-width="2"/>'
        )
        body.extend(
            _wrapped_text(label, nx, ny, box_w - 20, 17, TEXT, max_lines=2)
        )
        next_x, next_y, _ = nodes[(idx + 1) % count]
        sx, sy = _edge_point(nx, ny, next_x, next_y, box_w / 2 - 6, box_h / 2 - 6)
        ex, ey = _edge_point(next_x, next_y, nx, ny, box_w / 2 - 6, box_h / 2 - 6)
        body.append(
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="{SECONDARY}" stroke-width="2"/>'
        )
        body.append(
            f'<polygon points="{_arrowhead(ex, ey, sx, sy)}" fill="{SECONDARY}"/>'
        )
    return _group(spec, body)


def _render_swimlane(spec: LayoutSpec) -> str:
    lanes = spec.items[:4]
    stage_labels = ["阶段1", "阶段2", "阶段3"]
    header_w = 172
    gap = 12
    lane_gap = 10
    cell_w = (spec.width - header_w - gap - gap * (len(stage_labels) - 1)) / len(stage_labels)
    lane_h = (spec.height - lane_gap * (len(lanes) - 1)) / max(len(lanes), 1)
    body: list[str] = []
    for row, lane in enumerate(lanes):
        y = spec.y + row * (lane_h + lane_gap)
        body.append(
            f'<rect x="{spec.x:.1f}" y="{y:.1f}" width="{header_w}" height="{lane_h:.1f}" rx="12" '
            f'fill="{SECONDARY if row == 0 else SURFACE}" stroke="{BORDER}" stroke-width="1"/>'
        )
        body.extend(
            _wrapped_text(
                lane,
                spec.x + header_w / 2,
                y + lane_h / 2,
                header_w - 20,
                17,
                WHITE if row == 0 else TEXT,
                max_lines=2,
            )
        )
        for col, stage in enumerate(stage_labels):
            x = spec.x + header_w + gap + col * (cell_w + gap)
            fill = PRIMARY if col == len(stage_labels) - 1 and row == 0 else WHITE
            text_fill = WHITE if fill == PRIMARY else TEXT
            body.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w:.1f}" height="{lane_h:.1f}" rx="12" '
                f'fill="{fill}" stroke="{BORDER}" stroke-width="1"/>'
            )
            body.append(
                f'<text x="{x + 18:.1f}" y="{y + 28:.1f}" font-size="13" fill="{TEXT_SECONDARY if fill == WHITE else WHITE}">'
                f'{stage}</text>'
            )
            body.append(
                f'<line x1="{x + 16:.1f}" y1="{y + 38:.1f}" x2="{x + cell_w - 16:.1f}" y2="{y + 38:.1f}" '
                f'stroke="{BORDER if fill == WHITE else WHITE}" stroke-width="1"/>'
            )
    return _group(spec, body)


def _render_iceberg(spec: LayoutSpec) -> str:
    surface_label = spec.items[0]
    hidden_labels = spec.items[1:] or [spec.items[0]]
    water_y = spec.y + spec.height * 0.32
    cx = spec.x + spec.width / 2
    top_peak_y = water_y - 92
    pill_w = min(spec.width * 0.34, 340)
    pill_h = 54
    outline = [
        (spec.x + spec.width * 0.30, water_y + 4),
        (spec.x + spec.width * 0.43, water_y - 40),
        (cx - 26, top_peak_y + 22),
        (cx, top_peak_y),
        (cx + 36, top_peak_y + 32),
        (spec.x + spec.width * 0.68, water_y + 4),
        (spec.x + spec.width * 0.72, spec.y + spec.height * 0.56),
        (spec.x + spec.width * 0.64, spec.y + spec.height * 0.86),
        (cx, spec.y + spec.height),
        (spec.x + spec.width * 0.36, spec.y + spec.height * 0.85),
        (spec.x + spec.width * 0.27, spec.y + spec.height * 0.57),
    ]
    body = [
        f'<line x1="{spec.x:.1f}" y1="{water_y:.1f}" x2="{spec.x + spec.width:.1f}" y2="{water_y:.1f}" '
        f'stroke="{SECONDARY}" stroke-width="2"/>',
        f'<text x="{spec.x + 6:.1f}" y="{water_y - 12:.1f}" font-size="15" fill="{TEXT_SECONDARY}">水面以上</text>',
        f'<text x="{spec.x + 6:.1f}" y="{water_y + 28:.1f}" font-size="15" fill="{TEXT_SECONDARY}">水面以下</text>',
        f'<polygon points="{_points(outline)}" fill="{SURFACE}" stroke="{BORDER}" stroke-width="1.5"/>',
        f'<line x1="{cx:.1f}" y1="{top_peak_y + 6:.1f}" x2="{spec.x + spec.width * 0.44:.1f}" y2="{water_y - 20:.1f}" '
        f'stroke="{BORDER}" stroke-width="1"/>',
        f'<line x1="{cx:.1f}" y1="{top_peak_y + 6:.1f}" x2="{spec.x + spec.width * 0.58:.1f}" y2="{water_y - 14:.1f}" '
        f'stroke="{BORDER}" stroke-width="1"/>',
    ]
    pill_x = cx - pill_w / 2
    pill_y = spec.y + 8
    body.append(
        f'<rect x="{pill_x:.1f}" y="{pill_y:.1f}" width="{pill_w:.1f}" height="{pill_h}" rx="18" '
        f'fill="{PRIMARY}" stroke="{PRIMARY}" stroke-width="1"/>'
    )
    body.extend(
        _wrapped_text(surface_label, cx, pill_y + pill_h / 2, pill_w - 28, 18, WHITE, max_lines=2)
    )
    layer_top = water_y + 34
    layer_gap = 14
    layer_h = min(56, (spec.y + spec.height - 26 - layer_top - layer_gap * (len(hidden_labels) - 1)) / len(hidden_labels))
    layer_widths = [spec.width * 0.46, spec.width * 0.38, spec.width * 0.30]
    layer_fills = [WHITE, SURFACE, PRIMARY]
    for idx, label in enumerate(hidden_labels[:3]):
        width = layer_widths[min(idx, len(layer_widths) - 1)]
        x = cx - width / 2
        y = layer_top + idx * (layer_h + layer_gap)
        fill = layer_fills[min(idx, len(layer_fills) - 1)]
        stroke = PRIMARY if idx == 0 else BORDER
        text_fill = WHITE if fill == PRIMARY else TEXT
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{layer_h:.1f}" rx="16" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        )
        body.extend(
            _wrapped_text(label, cx, y + layer_h / 2, width - 24, 17, text_fill, max_lines=2)
        )
    return _group(spec, body)


def _xml(value: str) -> str:
    return escape(value, quote=False)


def _wrap_label(value: str, max_units: float) -> list[str]:
    """Wrap CJK/Latin labels at deterministic visual-width boundaries."""
    value = " ".join(value.split())
    if not value:
        return []

    def units(character: str) -> float:
        if "\u3400" <= character <= "\u9fff":
            return 1.0
        if character.isspace():
            return 0.35
        return 0.58

    lines: list[str] = []
    start = 0
    while start < len(value):
        used = 0.0
        end = start
        last_break = -1
        while end < len(value):
            candidate = used + units(value[end])
            if candidate > max_units and end > start:
                break
            used = candidate
            if value[end].isspace() or value[end] in "/|·：:-，、；":
                last_break = end + 1
            end += 1
        if end < len(value) and last_break > start:
            end = last_break
        line = value[start:end].strip()
        if line:
            lines.append(line)
        start = end
        while start < len(value) and value[start].isspace():
            start += 1
    return lines


def _wrapped_text(
    label: str,
    x: float,
    center_y: float,
    max_width: float,
    font_size: int,
    fill: str,
    *,
    anchor: str = "middle",
    max_lines: int = 3,
) -> list[str]:
    """Return separate editable SVG text nodes for a centered multiline label."""
    size = font_size
    while True:
        lines = _wrap_label(label, max(4.0, max_width / (size * 0.95)))
        if len(lines) <= max_lines or size <= 13:
            break
        size -= 1
    line_height = size + 6
    first_baseline = center_y - (len(lines) - 1) * line_height / 2 + size * 0.34
    return [
        f'<text x="{x:.1f}" y="{first_baseline + index * line_height:.1f}" '
        f'text-anchor="{anchor}" font-size="{size}" font-weight="bold" fill="{fill}">'
        f'{_xml(line)}</text>'
        for index, line in enumerate(lines)
    ]


def _points(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def _arrowhead(x: float, y: float, from_x: float, from_y: float, size: float = 11) -> str:
    angle = math.atan2(y - from_y, x - from_x)
    left = (x - size * math.cos(angle - math.pi / 6), y - size * math.sin(angle - math.pi / 6))
    right = (x - size * math.cos(angle + math.pi / 6), y - size * math.sin(angle + math.pi / 6))
    return _points([(x, y), left, right])


def _edge_point(
    x: float,
    y: float,
    toward_x: float,
    toward_y: float,
    half_w: float,
    half_h: float,
) -> tuple[float, float]:
    dx = toward_x - x
    dy = toward_y - y
    if dx == 0 and dy == 0:
        return x, y
    scale = 1 / max(abs(dx) / max(half_w, 1), abs(dy) / max(half_h, 1))
    return x + dx * scale, y + dy * scale
