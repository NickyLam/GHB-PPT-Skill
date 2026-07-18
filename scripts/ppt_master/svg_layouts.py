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
FONT = "'Source Han Sans SC', 'Microsoft YaHei', Arial, sans-serif"


@dataclass(frozen=True)
class LayoutContract:
    """Supported component load for one built-in layout family."""

    min_items: int
    max_items: int
    max_chars_per_item: int
    max_text_chars: int
    variants: frozenset[str]


# GHB-owned contract kept beside the vendored SVG renderers so geometry and
# budget validation cannot drift apart during the offline packaging flow.
LAYOUT_CONTRACTS = {
    "pyramid": LayoutContract(2, 5, 64, 240, frozenset({"pyramid/default", "pyramid/foundation"})),
    "waterfall": LayoutContract(2, 6, 56, 260, frozenset({"waterfall/default", "waterfall/descending"})),
    "staircase": LayoutContract(2, 5, 56, 220, frozenset({"staircase/default", "staircase/editorial"})),
    "layered_arch": LayoutContract(2, 6, 72, 320, frozenset({"layered_arch/default", "layered_arch/platform"})),
    "matrix": LayoutContract(2, 4, 80, 240, frozenset({
        "matrix/default", "matrix/comparison", "matrix/spotlight", "matrix/metric-callout"
    })),
    "timeline": LayoutContract(2, 6, 80, 360, frozenset({
        "timeline/default", "timeline/editorial", "timeline/phased"
    })),
    "funnel": LayoutContract(2, 5, 56, 240, frozenset({"funnel/default", "funnel/qualified"})),
    "flywheel": LayoutContract(3, 6, 48, 240, frozenset({"flywheel/default", "flywheel/hub-led"})),
    "swimlane": LayoutContract(2, 4, 48, 180, frozenset({"swimlane/default", "swimlane/compact"})),
    "iceberg": LayoutContract(2, 4, 64, 220, frozenset({"iceberg/default", "iceberg/deep-dive"})),
}


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
    max_items: int | None = None
    max_text_chars: int | None = None


def render_layout(spec: LayoutSpec) -> str:
    """Render an Office-safe SVG group for a supported layout archetype."""

    normalized = _normalized(spec)
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
        renderer = renderers[normalized.archetype]
    except KeyError as exc:
        raise ValueError(f"Unsupported layout archetype: {spec.archetype}") from exc
    return renderer(normalized)


def _normalized(spec: LayoutSpec) -> LayoutSpec:
    archetype = "matrix" if spec.archetype == "comparison" else spec.archetype
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
        archetype=archetype,
        items=items,
        title=spec.title.strip(),
        x=spec.x,
        y=spec.y,
        width=spec.width,
        height=spec.height,
        density=spec.density,
        variant="matrix/comparison" if spec.archetype == "comparison" and spec.variant is None else spec.variant,
        emphasis=spec.emphasis,
        focal_index=focal_index,
        focal_target=focal_target,
        max_items=spec.max_items,
        max_text_chars=spec.max_text_chars,
    )
    _validate_visual_intent(normalized)
    return normalized


def _intent_enabled(spec: LayoutSpec) -> bool:
    return any(
        value is not None
        for value in (
            spec.density,
            spec.variant,
            spec.emphasis,
            spec.focal_index,
            spec.focal_target,
            spec.max_items,
            spec.max_text_chars,
        )
    )


def _validate_visual_intent(spec: LayoutSpec) -> None:
    if not _intent_enabled(spec):
        return
    if spec.density not in {None, "breathing", "balanced", "dense"}:
        raise ValueError("invalid-layout-density: expected breathing, balanced, or dense")
    contract = LAYOUT_CONTRACTS.get(spec.archetype)
    if contract is None:
        return
    if spec.variant is not None and spec.variant not in contract.variants:
        raise ValueError(f"invalid-layout-variant: {spec.variant!r} does not belong to {spec.archetype}")
    if spec.emphasis not in {None, "single-focal", "ranked", "distributed"}:
        raise ValueError("invalid-layout-emphasis: unsupported emphasis intent")
    if spec.max_items is not None and (not isinstance(spec.max_items, int) or spec.max_items < 1):
        raise ValueError("invalid-layout-item-budget: max_items must be a positive integer")
    if spec.max_text_chars is not None and (
        not isinstance(spec.max_text_chars, int) or spec.max_text_chars < 1
    ):
        raise ValueError("invalid-layout-text-budget: max_text_chars must be a positive integer")
    min_items = contract.min_items
    max_items = min(contract.max_items, spec.max_items or contract.max_items)
    text_total = len(spec.title) + sum(map(len, spec.items))
    text_limit = min(contract.max_text_chars, spec.max_text_chars or contract.max_text_chars)
    if any(len(item) > contract.max_chars_per_item for item in spec.items) or text_total > text_limit:
        raise ValueError(
            f"layout-budget-text-exceeded: {spec.archetype} supports at most "
            f"{contract.max_chars_per_item} characters per item and {text_limit} total characters"
        )
    if len(spec.items) < min_items:
        raise ValueError(
            f"layout-budget-items-below-minimum: {spec.archetype} requires at least {min_items} items"
        )
    if len(spec.items) > max_items:
        raise ValueError(
            f"layout-budget-items-exceeded: {spec.archetype} supports at most {max_items} items"
        )
    if spec.focal_index is not None and not 0 <= spec.focal_index < len(spec.items):
        raise ValueError("invalid-layout-focal-index: focal index must identify a visible item")
    if spec.emphasis == "single-focal" and spec.focal_index is None and not spec.focal_target:
        raise ValueError("missing-layout-focal-target: single-focal requires focal intent")


def _group(spec: LayoutSpec, body: list[str]) -> str:
    title = _title(spec)
    content = "\n  ".join([title, *body] if title else body)
    intent = ""
    if _intent_enabled(spec):
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


def _density_value(spec: LayoutSpec, breathing: float, balanced: float, dense: float) -> float:
    """Resolve a geometry token without changing legacy calls."""

    return {
        "breathing": breathing,
        "balanced": balanced,
        "dense": dense,
    }[spec.density or "balanced"]


def _highlighted(spec: LayoutSpec, item_index: int, ranked_index: int) -> bool:
    """Return whether an item owns the visible hierarchy treatment."""

    if not _intent_enabled(spec):
        return item_index == ranked_index
    emphasis = spec.emphasis or "ranked"
    if emphasis == "distributed":
        return False
    if emphasis == "single-focal":
        return item_index == spec.focal_index
    return item_index == ranked_index


def _focal_attr(spec: LayoutSpec, item_index: int) -> str:
    if _intent_enabled(spec) and spec.emphasis == "single-focal" and item_index == spec.focal_index:
        return ' data-focal="true"'
    return ""


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
    gap = _density_value(spec, 14.0, 8.0, 3.0) if _intent_enabled(spec) else 6.0
    width_scale = _density_value(spec, 0.90, 0.96, 1.0) if _intent_enabled(spec) else 1.0
    top_ratio = 0.42 if spec.variant == "pyramid/foundation" else 0.28
    body: list[str] = []
    for idx, label in enumerate(reversed(spec.items)):
        item_index = count - 1 - idx
        y1 = spec.y + idx * layer_h
        y2 = spec.y + (idx + 1) * layer_h - gap
        top_w = spec.width * width_scale * (top_ratio + (1 - top_ratio) * idx / count)
        bottom_w = spec.width * width_scale * (top_ratio + (1 - top_ratio) * (idx + 1) / count)
        highlighted = _highlighted(spec, item_index, count - 1)
        fill = PRIMARY if highlighted else SURFACE
        stroke = PRIMARY if highlighted else BORDER
        text_fill = WHITE if highlighted else TEXT
        points = [
            (cx - top_w / 2, y1),
            (cx + top_w / 2, y1),
            (cx + bottom_w / 2, y2),
            (cx - bottom_w / 2, y2),
        ]
        body.append(
            f'<polygon points="{_points(points)}"{_focal_attr(spec, item_index)} '
            f'fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{2 if highlighted and _intent_enabled(spec) else 1}"/>'
        )
        body.extend(
            _wrapped_text(
                label, cx, (y1 + y2) / 2, min(top_w, bottom_w) - 32,
                20 if highlighted and _intent_enabled(spec) else 18, text_fill,
                max_height=(y2 - y1 - 12) if _intent_enabled(spec) else None,
            )
        )
    return _group(spec, body)


def _render_waterfall(spec: LayoutSpec) -> str:
    count = len(spec.items)
    # GHB intent-aware waterfalls reserve real connector space. The previous
    # dense 12 px gap was smaller than the connector's 14 px insets, which
    # reversed the horizontal vector and produced near-vertical arrow stubs.
    gap = _density_value(spec, 40.0, 36.0, 32.0) if _intent_enabled(spec) else 24
    step_w = (spec.width - gap * (count - 1)) / count
    block_h = _density_value(spec, 78.0, 84.0, 90.0) if _intent_enabled(spec) else 92
    rise = _density_value(spec, 42.0, 34.0, 26.0) if _intent_enabled(spec) else 34
    base_y = spec.y + spec.height - block_h
    body: list[str] = []
    for idx, label in enumerate(spec.items):
        x = spec.x + idx * (step_w + gap)
        offset = idx if spec.variant != "waterfall/descending" else count - 1 - idx
        y = base_y - offset * rise
        highlighted = _highlighted(spec, idx, count - 1)
        fill = PRIMARY if highlighted else SURFACE
        text_fill = WHITE if highlighted else TEXT
        height_attr = f"{block_h:.1f}" if _intent_enabled(spec) else "92"
        node_id = f"waterfall-step-{idx + 1}"
        node_contract = (
            f' id="{node_id}" data-flow-node="{node_id}" '
            f'data-qa-box="{x:.1f} {y:.1f} {step_w:.1f} {block_h:.1f}"'
            if _intent_enabled(spec)
            else ""
        )
        body.append(
            f'<rect{node_contract} x="{x:.1f}" y="{y:.1f}" width="{step_w:.1f}" height="{height_attr}" rx="10"'
            f'{_focal_attr(spec, idx)} fill="{fill}" '
            f'stroke="{PRIMARY if highlighted and _intent_enabled(spec) else BORDER}" '
            f'stroke-width="{2 if highlighted and _intent_enabled(spec) else 1}"/>'
        )
        body.extend(
            _wrapped_text(
                label, x + step_w / 2, y + block_h / 2, step_w - 24,
                19 if highlighted and _intent_enabled(spec) else 17, text_fill,
                max_height=(block_h - 20) if _intent_enabled(spec) else None,
            )
        )
        if idx < count - 1:
            if _intent_enabled(spec):
                next_x = spec.x + (idx + 1) * (step_w + gap)
                next_offset = (
                    idx + 1
                    if spec.variant != "waterfall/descending"
                    else count - 2 - idx
                )
                next_y = base_y - next_offset * rise
                current_cx, current_cy = x + step_w / 2, y + block_h / 2
                next_cx, next_cy = next_x + step_w / 2, next_y + block_h / 2
                # Four SVG units of clearance keep the line and explicit
                # arrowhead outside both rounded cards after PPT conversion.
                ax1, ay = _edge_point(
                    current_cx,
                    current_cy,
                    next_cx,
                    next_cy,
                    step_w / 2 + 4,
                    block_h / 2 + 4,
                )
                ax2, ay2 = _edge_point(
                    next_cx,
                    next_cy,
                    current_cx,
                    current_cy,
                    step_w / 2 + 4,
                    block_h / 2 + 4,
                )
            else:
                ax1 = x + step_w + 6
                ay = y + 46
                ax2 = x + step_w + gap - 8
                ay2 = ay - 20
            edge_contract = (
                f' id="waterfall-edge-{idx + 1}" data-flow-from="{node_id}" '
                f'data-flow-to="waterfall-step-{idx + 2}"'
                if _intent_enabled(spec)
                else ""
            )
            body.append(
                f'<line{edge_contract}'
                f' x1="{ax1:.1f}" y1="{ay:.1f}" x2="{ax2:.1f}" y2="{ay2:.1f}" '
                f'stroke="{SECONDARY}" stroke-width="2"/>'
            )
            # GHB keeps explicit Office-safe polygons in the vendored SVG path;
            # derive both wings from the connector vector so arrows stay balanced.
            arrow_points = (
                _arrowhead(ax2, ay2, ax1, ay, size=9)
                if _intent_enabled(spec)
                else (
                    f"{ax2:.1f},{ay - 20:.1f} {ax2 - 11:.1f},{ay - 14:.1f} "
                    f"{ax2 - 4:.1f},{ay - 4:.1f}"
                )
            )
            body.append(
                f'<polygon points="{arrow_points}" fill="{SECONDARY}"/>'
            )
    return _group(spec, body)


def _render_staircase(spec: LayoutSpec) -> str:
    count = len(spec.items)
    gap = _density_value(spec, 26.0, 16.0, 8.0) if _intent_enabled(spec) else 16
    step_w = (spec.width - gap * (count - 1)) / count
    base_h = _density_value(spec, 74.0, 84.0, 94.0) if _intent_enabled(spec) else 84
    rise = _density_value(spec, 38.0, 32.0, 26.0) if _intent_enabled(spec) else 32
    body: list[str] = []
    for idx, label in enumerate(spec.items):
        height_index = idx if spec.variant != "staircase/editorial" else min(idx + 1, count - 1)
        h = base_h + height_index * rise
        x = spec.x + idx * (step_w + gap)
        y = spec.y + spec.height - h
        highlighted = _highlighted(spec, idx, count - 1)
        fill = PRIMARY if highlighted else SURFACE
        text_fill = WHITE if highlighted else TEXT
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{step_w:.1f}" height="{h:.1f}" rx="10"'
            f'{_focal_attr(spec, idx)} fill="{fill}" '
            f'stroke="{PRIMARY if highlighted and _intent_enabled(spec) else BORDER}" '
            f'stroke-width="{2 if highlighted and _intent_enabled(spec) else 1}"/>'
        )
        body.append(
            f'<text x="{x + 18:.1f}" y="{y + 32:.1f}" font-size="15" fill="{TEXT_SECONDARY}">'
            f'{idx + 1:02d}</text>'
        )
        body.extend(
            _wrapped_text(
                label, x + step_w / 2, y + h / 2 + 4, step_w - 24,
                19 if highlighted and _intent_enabled(spec) else 17, text_fill,
                max_height=(h - 48) if _intent_enabled(spec) else None,
            )
        )
    return _group(spec, body)


def _render_layered_arch(spec: LayoutSpec) -> str:
    count = len(spec.items)
    gap = _density_value(spec, 22.0, 14.0, 8.0) if _intent_enabled(spec) else 14
    layer_h = (spec.height - gap * (count - 1)) / count
    inset = _density_value(spec, 24.0, 18.0, 12.0) if _intent_enabled(spec) else 18
    body: list[str] = []
    for idx, label in enumerate(reversed(spec.items)):
        item_index = count - 1 - idx
        offset_index = idx if spec.variant != "layered_arch/platform" else count - 1 - idx
        x = spec.x + offset_index * inset
        y = spec.y + idx * (layer_h + gap)
        w = spec.width - offset_index * inset * 2
        highlighted = _highlighted(spec, item_index, 0)
        fill = PRIMARY if highlighted else SURFACE
        text_fill = WHITE if highlighted else TEXT
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{layer_h:.1f}" rx="12"'
            f'{_focal_attr(spec, item_index)} fill="{fill}" '
            f'stroke="{PRIMARY if highlighted and _intent_enabled(spec) else BORDER}" '
            f'stroke-width="{2 if highlighted and _intent_enabled(spec) else 1}"/>'
        )
        body.extend(
            _wrapped_text(
                label, x + 28, y + layer_h / 2, w - 56,
                20 if highlighted and _intent_enabled(spec) else 18, text_fill, anchor="start",
                max_height=(layer_h - 12) if _intent_enabled(spec) else None,
            )
        )
    return _group(spec, body)


def _render_matrix(spec: LayoutSpec) -> str:
    if _intent_enabled(spec):
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
    focal = spec.focal_index if spec.focal_index is not None else 1
    density = spec.density or "balanced"
    gap = {"breathing": 22.0, "balanced": 14.0, "dense": 8.0}[density]
    columns = len(labels) if len(labels) < 4 else 2
    rows = 1 if len(labels) < 4 else 2
    cell_w = (spec.width - gap * (columns - 1)) / columns
    cell_h = (spec.height - gap * (rows - 1)) / rows
    body: list[str] = []
    for idx, label in enumerate(labels):
        col, row = idx % columns, idx // columns
        x = spec.x + col * (cell_w + gap)
        y = spec.y + row * (cell_h + gap)
        w, h = cell_w, cell_h
        highlighted = _highlighted(spec, idx, focal)
        fill = PRIMARY if highlighted else SURFACE
        text_fill = WHITE if highlighted and _intent_enabled(spec) else TEXT
        focal_attr = _focal_attr(spec, idx)
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12"'
            f'{focal_attr} fill="{fill}" stroke="{PRIMARY if highlighted else BORDER}" stroke-width="{2 if highlighted else 1}"/>'
        )
        if label:
            comparison_parts: list[str] = []
            if spec.variant == "matrix/comparison":
                separator = "：" if "：" in label else ":"
                if separator in label:
                    comparison_parts = label.split(separator, 1)
            if len(comparison_parts) == 2:
                heading, explanation = (part.strip() for part in comparison_parts)
                # GHB comparison cards keep equal geometry while making the
                # semantic option label independently scannable and editable.
                body.extend(
                    _wrapped_text(
                        heading,
                        x + w / 2,
                        y + h * 0.36,
                        w - 40,
                        22 if highlighted else 20,
                        text_fill,
                        max_lines=1,
                        max_height=h * 0.24,
                    )
                )
                body.extend(
                    _wrapped_text(
                        explanation,
                        x + w / 2,
                        y + h * 0.64,
                        w - 40,
                        16 if highlighted else 15,
                        text_fill,
                        max_lines=2,
                        max_height=h * 0.34,
                    )
                )
                continue
            if spec.variant == "matrix/metric-callout":
                size = 26 if highlighted else 22
            elif spec.variant == "matrix/spotlight":
                size = 24 if highlighted else 17
            else:
                size = 21 if highlighted else 17
            body.extend(
                _wrapped_text(
                    label, x + w / 2, y + h / 2, w - 40, size, text_fill,
                    max_height=h - 24,
                )
            )
    return _group(spec, body)


def _render_timeline(spec: LayoutSpec) -> str:
    if _intent_enabled(spec):
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
        highlighted = _highlighted(spec, idx, focal)
        single_focal = spec.emphasis == "single-focal" and idx == spec.focal_index
        size = base_size * (1.36 if single_focal else 1.0)
        fill = PRIMARY if highlighted else WHITE
        text_fill = WHITE if highlighted else PRIMARY
        focal_attr = _focal_attr(spec, idx)
        body.append(
            f'<rect x="{x - size / 2:.1f}" y="{y_line - size / 2:.1f}" '
            f'width="{size:.1f}" height="{size:.1f}" rx="{size / 2:.1f}"{focal_attr} '
            f'fill="{fill}" stroke="{PRIMARY}" stroke-width="{3 if highlighted else 2}"/>'
        )
        body.append(
            f'<text x="{x:.1f}" y="{y_line + 6:.1f}" text-anchor="middle" font-size="16" '
            f'font-weight="bold" fill="{text_fill}">{idx + 1}</text>'
        )
        alternating = spec.variant != "timeline/phased"
        label_y = y_line + size / 2 + 42 if not alternating or idx % 2 == 0 else y_line - size / 2 - 26
        body.extend(
            _wrapped_text(
                label, x, label_y, min(210, max(120, step * 0.82)),
                17 if highlighted else 16, TEXT, max_height=88,
            )
        )
    return _group(spec, body)


def _render_funnel(spec: LayoutSpec) -> str:
    count = len(spec.items)
    cx = spec.x + spec.width / 2
    width_scale = _density_value(spec, 0.90, 0.96, 1.0) if _intent_enabled(spec) else 1.0
    top_width = spec.width * width_scale
    min_ratio = 0.26 if spec.variant == "funnel/qualified" else 0.34
    min_width = spec.width * min_ratio
    gap = _density_value(spec, 16.0, 10.0, 5.0) if _intent_enabled(spec) else 10
    segment_h = (spec.height - gap * (count - 1)) / count
    body: list[str] = []
    for idx, label in enumerate(spec.items):
        y1 = spec.y + idx * (segment_h + gap)
        y2 = y1 + segment_h
        top_w = top_width - (top_width - min_width) * idx / count
        bottom_w = top_width - (top_width - min_width) * (idx + 1) / count
        highlighted = _highlighted(spec, idx, count - 1)
        fill = PRIMARY if highlighted else SURFACE
        text_fill = WHITE if highlighted else TEXT
        points = [
            (cx - top_w / 2, y1),
            (cx + top_w / 2, y1),
            (cx + bottom_w / 2, y2),
            (cx - bottom_w / 2, y2),
        ]
        body.append(
            f'<polygon points="{_points(points)}"{_focal_attr(spec, idx)} fill="{fill}" '
            f'stroke="{PRIMARY if highlighted and _intent_enabled(spec) else BORDER}" '
            f'stroke-width="{2 if highlighted and _intent_enabled(spec) else 1}"/>'
        )
        body.extend(
            _wrapped_text(
                label, cx, (y1 + y2) / 2, min(top_w, bottom_w) - 36,
                20 if highlighted and _intent_enabled(spec) else 18, text_fill,
                max_height=(segment_h - 12) if _intent_enabled(spec) else None,
            )
        )
    return _group(spec, body)


def _render_flywheel(spec: LayoutSpec) -> str:
    count = len(spec.items)
    cx = spec.x + spec.width / 2
    cy = spec.y + spec.height / 2
    radius_scale = _density_value(spec, 0.38, 0.34, 0.30) if _intent_enabled(spec) else 0.34
    radius_x = spec.width * radius_scale
    radius_y = spec.height * (radius_scale - 0.02)
    box_w = min(_density_value(spec, 154.0, 170.0, 184.0), spec.width * 0.24) if _intent_enabled(spec) else min(170, spec.width * 0.24)
    box_h = _density_value(spec, 52.0, 58.0, 64.0) if _intent_enabled(spec) else 58
    nodes: list[tuple[float, float, str]] = []
    for idx, label in enumerate(spec.items):
        angle = -math.pi / 2 + idx * (2 * math.pi / count)
        nodes.append((cx + math.cos(angle) * radius_x, cy + math.sin(angle) * radius_y, label))

    hub_w = 190.0 if spec.variant == "flywheel/hub-led" else 164.0
    hub_h = 82.0 if spec.variant == "flywheel/hub-led" else 68.0
    body = [
        f'<rect x="{cx - hub_w / 2:.1f}" y="{cy - hub_h / 2:.1f}" width="{hub_w:g}" height="{hub_h:g}" rx="{hub_h / 2:g}" '
        f'fill="{PRIMARY}" stroke="{PRIMARY}" stroke-width="1"/>',
        f'<text x="{cx:.1f}" y="{cy + 7:.1f}" text-anchor="middle" font-size="18" '
        f'font-weight="bold" fill="{WHITE}">正向循环</text>',
    ]
    for idx, (nx, ny, label) in enumerate(nodes):
        highlighted = _highlighted(spec, idx, count - 1)
        fill = PRIMARY if highlighted and _intent_enabled(spec) else (SURFACE if idx < count - 1 else WHITE)
        text_fill = WHITE if highlighted and _intent_enabled(spec) else TEXT
        node_id = f"flywheel-step-{idx + 1}"
        node_contract = (
            f' id="{node_id}" data-flow-node="{node_id}" '
            f'data-qa-box="{nx - box_w / 2:.1f} {ny - box_h / 2:.1f} {box_w:.1f} {box_h:.1f}"'
            if _intent_enabled(spec)
            else ""
        )
        body.append(
            f'<rect{node_contract} x="{nx - box_w / 2:.1f}" y="{ny - box_h / 2:.1f}" width="{box_w:.1f}" '
            f'height="{box_h:g}" rx="18"{_focal_attr(spec, idx)} fill="{fill}" stroke="{PRIMARY}" '
            f'stroke-width="{3 if highlighted and _intent_enabled(spec) else 2}"/>'
        )
        body.extend(
            _wrapped_text(
                label, nx, ny, box_w - 20,
                19 if highlighted and _intent_enabled(spec) else 17, text_fill, max_lines=2,
                max_height=(box_h - 14) if _intent_enabled(spec) else None,
            )
        )
        next_x, next_y, _ = nodes[(idx + 1) % count]
        if _intent_enabled(spec):
            # The old half-size-minus-six calculation placed both endpoints
            # inside the node. Keep a visible clearance outside the bounding
            # box so diagonal arrows cannot pierce rounded corners.
            sx, sy = _edge_point(
                nx, ny, next_x, next_y, box_w / 2 + 4, box_h / 2 + 4
            )
            ex, ey = _edge_point(
                next_x, next_y, nx, ny, box_w / 2 + 4, box_h / 2 + 4
            )
        else:
            sx, sy = _edge_point(nx, ny, next_x, next_y, box_w / 2 - 6, box_h / 2 - 6)
            ex, ey = _edge_point(next_x, next_y, nx, ny, box_w / 2 - 6, box_h / 2 - 6)
        edge_contract = (
            f' id="flywheel-edge-{idx + 1}" data-flow-from="{node_id}" '
            f'data-flow-to="flywheel-step-{(idx + 1) % count + 1}"'
            if _intent_enabled(spec)
            else ""
        )
        body.append(
            f'<line{edge_contract}'
            f' x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="{SECONDARY}" stroke-width="2"/>'
        )
        body.append(
            f'<polygon points="{_arrowhead(ex, ey, sx, sy)}" fill="{SECONDARY}"/>'
        )
    return _group(spec, body)


def _render_swimlane(spec: LayoutSpec) -> str:
    lanes = spec.items[:4]
    stage_labels = ["阶段1", "阶段2", "阶段3"]
    header_w = _density_value(spec, 190.0, 172.0, 154.0) if _intent_enabled(spec) else 172
    gap = _density_value(spec, 18.0, 12.0, 6.0) if _intent_enabled(spec) else 12
    lane_gap = _density_value(spec, 16.0, 10.0, 6.0) if _intent_enabled(spec) else 10
    if spec.variant == "swimlane/compact":
        header_w -= 18
    cell_w = (spec.width - header_w - gap - gap * (len(stage_labels) - 1)) / len(stage_labels)
    lane_h = (spec.height - lane_gap * (len(lanes) - 1)) / max(len(lanes), 1)
    body: list[str] = []
    for row, lane in enumerate(lanes):
        y = spec.y + row * (lane_h + lane_gap)
        highlighted = _highlighted(spec, row, 0)
        header_fill = SECONDARY if highlighted else SURFACE
        body.append(
            f'<rect x="{spec.x:.1f}" y="{y:.1f}" width="{header_w:g}" height="{lane_h:.1f}" rx="12"'
            f'{_focal_attr(spec, row)} fill="{header_fill}" '
            f'stroke="{PRIMARY if highlighted and _intent_enabled(spec) else BORDER}" '
            f'stroke-width="{2 if highlighted and _intent_enabled(spec) else 1}"/>'
        )
        body.extend(
            _wrapped_text(
                lane,
                spec.x + header_w / 2,
                y + lane_h / 2,
                header_w - 20,
                19 if highlighted and _intent_enabled(spec) else 17,
                WHITE if highlighted else TEXT,
                max_lines=2,
                max_height=(lane_h - 16) if _intent_enabled(spec) else None,
            )
        )
        for col, stage in enumerate(stage_labels):
            x = spec.x + header_w + gap + col * (cell_w + gap)
            fill = PRIMARY if col == len(stage_labels) - 1 and highlighted else WHITE
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
    water_ratio = _density_value(spec, 0.28, 0.32, 0.36) if _intent_enabled(spec) else 0.32
    if spec.variant == "iceberg/deep-dive":
        water_ratio -= 0.04
    water_y = spec.y + spec.height * water_ratio
    cx = spec.x + spec.width / 2
    top_peak_y = water_y - 92
    pill_w = min(spec.width * _density_value(spec, 0.30, 0.34, 0.38), 380) if _intent_enabled(spec) else min(spec.width * 0.34, 340)
    pill_h = _density_value(spec, 50.0, 54.0, 60.0) if _intent_enabled(spec) else 54
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
    surface_highlighted = _highlighted(spec, 0, 0)
    body.append(
        f'<rect x="{pill_x:.1f}" y="{pill_y:.1f}" width="{pill_w:.1f}" height="{pill_h:g}" rx="18"'
        f'{_focal_attr(spec, 0)} fill="{PRIMARY if surface_highlighted else WHITE}" '
        f'stroke="{PRIMARY}" stroke-width="{2 if surface_highlighted and _intent_enabled(spec) else 1}"/>'
    )
    body.extend(
        _wrapped_text(
            surface_label, cx, pill_y + pill_h / 2, pill_w - 28,
            20 if surface_highlighted and _intent_enabled(spec) else 18,
            WHITE if surface_highlighted else TEXT, max_lines=2,
            max_height=(pill_h - 12) if _intent_enabled(spec) else None,
        )
    )
    layer_top = water_y + 34
    layer_gap = _density_value(spec, 20.0, 14.0, 8.0) if _intent_enabled(spec) else 14
    layer_h = min(56, (spec.y + spec.height - 26 - layer_top - layer_gap * (len(hidden_labels) - 1)) / len(hidden_labels))
    layer_widths = [spec.width * 0.46, spec.width * 0.38, spec.width * 0.30]
    layer_fills = [WHITE, SURFACE, PRIMARY]
    for idx, label in enumerate(hidden_labels[:3]):
        item_index = idx + 1
        width = layer_widths[min(idx, len(layer_widths) - 1)]
        x = cx - width / 2
        y = layer_top + idx * (layer_h + layer_gap)
        highlighted = _highlighted(spec, item_index, 0)
        fill = PRIMARY if highlighted else layer_fills[min(idx, len(layer_fills) - 1)]
        stroke = PRIMARY if highlighted or idx == 0 else BORDER
        text_fill = WHITE if fill == PRIMARY else TEXT
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{layer_h:.1f}" rx="16"'
            f'{_focal_attr(spec, item_index)} fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{2.5 if highlighted and _intent_enabled(spec) else 1.5}"/>'
        )
        body.extend(
            _wrapped_text(
                label, cx, y + layer_h / 2, width - 24,
                19 if highlighted and _intent_enabled(spec) else 17, text_fill, max_lines=2,
                max_height=(layer_h - 12) if _intent_enabled(spec) else None,
            )
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
    max_height: float | None = None,
) -> list[str]:
    """Return separate editable SVG text nodes for a centered multiline label."""
    size = font_size
    while True:
        lines = _wrap_label(label, max(4.0, max_width / (size * 0.95)))
        line_height = size + 6
        occupied_height = size + max(0, len(lines) - 1) * line_height
        fits_height = max_height is None or occupied_height <= max_height
        if (len(lines) <= max_lines and fits_height) or size <= 13:
            break
        size -= 1
    line_height = size + 6
    occupied_height = size + max(0, len(lines) - 1) * line_height
    if max_height is not None and occupied_height > max_height:
        raise ValueError(
            "layout-budget-text-exceeded: wrapped text does not fit the available component height"
        )
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
