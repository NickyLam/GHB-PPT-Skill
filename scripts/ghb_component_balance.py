#!/usr/bin/env python3
"""Intra-component balance detection for GHB authored SVGs.

The vendored ``visual_asset_checker`` already enforces two structural component
codes: ``component-slot-overflow`` (a slot escaping its card) and
``component-balance-outlier`` (paired cards whose peer slots misalign). It does
*not* catch a card that is structurally valid but visually hollow: a large card
with sparse content that leaves a tall empty band inside it. That "card void" is
a common return source, so this GHB-side module adds the missing
``component-void`` finding. It also checks that repeated components declaring a
``data-qa-peer-group`` use the same relative slot origins; equal outer cards do
not look aligned when one card puts its title beside the icon while its peers
put the title below it.

Detection is pure geometry over declared component/slot QA boxes; it never
guesses glyph ink bounds, matching the rest of the measurable-geometry gate.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ppt_master.visual_asset_checker import Box, _box_from_element  # noqa: E402

# A card is flagged only when it is both sparsely filled AND leaves a tall
# contiguous empty band. Requiring both keeps intentionally airy anchor cards
# (uniformly padded) from tripping the gate.
DEFAULT_VOID_OCCUPANCY = 0.45
DEFAULT_VOID_BAND_PX = 200.0
DEFAULT_PEER_SLOT_TOLERANCE_PX = 8.0


def _finding(
    code: str,
    slide_id: str,
    evidence: dict[str, Any],
    expected: dict[str, Any],
    action: str,
    *,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "slide_id": slide_id,
        "evidence": evidence,
        "expected": expected,
        "suggested_action": action,
    }


def _union_area(boxes: list[Box]) -> float:
    """Exact axis-aligned rectangle union area via coordinate compression."""
    rects = [b for b in boxes if b.width > 0 and b.height > 0]
    if not rects:
        return 0.0
    xs = sorted({b.x for b in rects} | {b.x + b.width for b in rects})
    ys = sorted({b.y for b in rects} | {b.y + b.height for b in rects})
    area = 0.0
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        for j in range(len(ys) - 1):
            y0, y1 = ys[j], ys[j + 1]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if any(b.x <= cx <= b.x + b.width and b.y <= cy <= b.y + b.height for b in rects):
                area += (x1 - x0) * (y1 - y0)
    return area


def _largest_vertical_band(component: Box, slots: list[Box]) -> float:
    """Return the tallest empty horizontal band inside the card (top, gaps, bottom)."""
    if not slots:
        return component.height
    ordered = sorted(slots, key=lambda b: b.y)
    top_gap = ordered[0].y - component.y
    bottom_gap = (component.y + component.height) - (ordered[-1].y + ordered[-1].height)
    bands = [top_gap, bottom_gap]
    frontier = ordered[0].y + ordered[0].height
    for box in ordered[1:]:
        bands.append(box.y - frontier)
        frontier = max(frontier, box.y + box.height)
    return max(bands)


def _collect_components(root: ET.Element) -> tuple[dict[str, Box], dict[str, list[Box]]]:
    components: dict[str, Box] = {}
    slots: dict[str, list[Box]] = {}
    for elem in root.iter():
        component_id = (elem.get("data-component-id") or "").strip()
        if not component_id or not (elem.get("data-component") or "").strip():
            continue
        box = _box_from_element(elem)
        if box and box.width > 0 and box.height > 0 and component_id not in components:
            components[component_id] = box
            slots.setdefault(component_id, [])
    for elem in root.iter():
        parent_id = (elem.get("data-component-parent") or "").strip()
        if not parent_id or not (elem.get("data-component-slot") or "").strip():
            continue
        if parent_id not in components:
            continue
        box = _box_from_element(elem)
        if box and box.width > 0 and box.height > 0:
            slots[parent_id].append(box)
    return components, slots


def _peer_slot_findings(
    root: ET.Element,
    *,
    slide_id: str,
    tolerance_px: float,
) -> list[dict[str, Any]]:
    components: dict[str, tuple[Box, str]] = {}
    groups: dict[str, list[str]] = {}
    slots: dict[str, dict[str, Box]] = {}
    for elem in root.iter():
        component_id = (elem.get("data-component-id") or "").strip()
        peer_group = (elem.get("data-qa-peer-group") or "").strip()
        if not component_id or not peer_group or not (elem.get("data-component") or "").strip():
            continue
        box = _box_from_element(elem)
        if not box or box.width <= 0 or box.height <= 0:
            continue
        components[component_id] = (box, peer_group)
        groups.setdefault(peer_group, []).append(component_id)
        slots.setdefault(component_id, {})
    for elem in root.iter():
        parent_id = (elem.get("data-component-parent") or "").strip()
        slot_name = (elem.get("data-component-slot") or "").strip()
        if parent_id not in components or not slot_name:
            continue
        box = _box_from_element(elem)
        if box and box.width > 0 and box.height > 0:
            slots[parent_id][slot_name] = box

    findings: list[dict[str, Any]] = []
    for peer_group, member_ids in groups.items():
        if len(member_ids) < 2:
            continue
        common_slots = set.intersection(*(set(slots[member_id]) for member_id in member_ids))
        for slot_name in sorted(common_slots):
            origins = []
            for member_id in member_ids:
                component_box = components[member_id][0]
                slot_box = slots[member_id][slot_name]
                origins.append((member_id, slot_box.x - component_box.x, slot_box.y - component_box.y))
            x_values = [origin[1] for origin in origins]
            y_values = [origin[2] for origin in origins]
            x_spread = max(x_values) - min(x_values)
            y_spread = max(y_values) - min(y_values)
            if x_spread <= tolerance_px and y_spread <= tolerance_px:
                continue
            findings.append(_finding(
                "component-peer-slot-outlier",
                slide_id,
                {
                    "peer_group": peer_group,
                    "slot": slot_name,
                    "relative_origins": [
                        {"component": member_id, "x": round(x, 2), "y": round(y, 2)}
                        for member_id, x, y in origins
                    ],
                    "x_spread_px": round(x_spread, 2),
                    "y_spread_px": round(y_spread, 2),
                },
                {"max_origin_spread_px": tolerance_px},
                "Use one shared internal slot template for all components in the peer group.",
            ))
    return findings


def analyze_component_balance(
    svg: str,
    *,
    slide_id: str,
    void_occupancy_threshold: float = DEFAULT_VOID_OCCUPANCY,
    void_band_px: float = DEFAULT_VOID_BAND_PX,
    peer_slot_tolerance_px: float = DEFAULT_PEER_SLOT_TOLERANCE_PX,
) -> list[dict[str, Any]]:
    """Return ``component-void`` findings for hollow cards, or ``[]``.

    A card must declare at least one slot to be measurable; cards without slots
    are left to the upstream contract checks and produce no void finding here.
    """
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return []
    components, slots = _collect_components(root)
    findings = _peer_slot_findings(
        root,
        slide_id=slide_id,
        tolerance_px=peer_slot_tolerance_px,
    )
    for component_id, box in components.items():
        member_slots = slots.get(component_id, [])
        if not member_slots:
            continue
        occupancy = _union_area(member_slots) / box.area if box.area else 0.0
        band = _largest_vertical_band(box, member_slots)
        if occupancy < void_occupancy_threshold and band > void_band_px:
            findings.append(_finding(
                "component-void",
                slide_id,
                {
                    "component": component_id,
                    "slot_occupancy": round(occupancy, 4),
                    "largest_empty_band_px": round(band, 2),
                    "slot_count": len(member_slots),
                },
                {
                    "min_slot_occupancy": void_occupancy_threshold,
                    "max_empty_band_px": void_band_px,
                },
                "Fill the empty band inside the card (add supporting copy/media), "
                "shrink the card to its content, or merge sparse cards.",
            ))
    return findings


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("svg", type=Path, nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    all_findings: list[dict[str, Any]] = []
    for path in args.svg:
        all_findings.extend(
            analyze_component_balance(path.read_text(encoding="utf-8"), slide_id=path.stem)
        )
    if args.json:
        print(json.dumps({"passed": not all_findings, "findings": all_findings}, ensure_ascii=False, indent=2))
    else:
        print("PASS" if not all_findings else "FAIL")
        for item in all_findings:
            print(f"{item['severity'].upper()} [{item['code']}] {item['evidence']}")
    return 0 if not all_findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
