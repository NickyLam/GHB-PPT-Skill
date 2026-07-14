#!/usr/bin/env python3
"""Offline provisional SVG metrics and the auditable U11 pilot gate."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any


SUPPORTED_GEOMETRY = {"svg", "g", "rect", "line", "polygon", "text", "tspan"}
REVIEW_SCHEMA = "ghb.visual-pilot-review.v1"
DETERMINISTIC_SCHEMA = "ghb.visual-pilot-deterministic.v1"


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _number(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    cleaned = value.strip().removesuffix("px")
    try:
        result = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"invalid-svg-geometry: non-numeric coordinate {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError("invalid-svg-geometry: coordinates must be finite")
    return result


def _viewbox(root: ET.Element) -> tuple[float, float, float, float]:
    raw = root.get("viewBox")
    if raw:
        values = [_number(item) for item in raw.replace(",", " ").split()]
        if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
            raise ValueError("invalid-svg-geometry: viewBox must contain positive width and height")
        return values[0], values[1], values[2], values[3]
    width, height = _number(root.get("width")), _number(root.get("height"))
    if width <= 0 or height <= 0:
        raise ValueError("invalid-svg-geometry: SVG requires viewBox or positive width and height")
    return 0.0, 0.0, width, height


def _bbox(element: ET.Element) -> tuple[float, float, float, float] | None:
    tag = _tag(element)
    if tag == "rect":
        x, y = _number(element.get("x")), _number(element.get("y"))
        width, height = _number(element.get("width")), _number(element.get("height"))
        if width < 0 or height < 0:
            raise ValueError("invalid-svg-geometry: rectangle dimensions cannot be negative")
        return x, y, x + width, y + height
    if tag == "line":
        x1, y1 = _number(element.get("x1")), _number(element.get("y1"))
        x2, y2 = _number(element.get("x2")), _number(element.get("y2"))
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
    if tag == "polygon":
        raw = element.get("points", "").replace(",", " ").split()
        if len(raw) < 6 or len(raw) % 2:
            raise ValueError("invalid-svg-geometry: polygon requires coordinate pairs")
        values = [_number(item) for item in raw]
        xs, ys = values[::2], values[1::2]
        return min(xs), min(ys), max(xs), max(ys)
    if tag in {"text", "tspan"}:
        text = "".join(element.itertext()).strip()
        if not text:
            return None
        x, y = _number(element.get("x")), _number(element.get("y"))
        size = _number(element.get("font-size"), 16.0)
        width = max(size * 0.55 * len(text), size)
        return x - width / 2, y - size, x + width / 2, y + size * 0.25
    return None


def measure_svg(svg: str) -> dict[str, Any]:
    """Measure visible geometry; semantic markers never affect the observations."""

    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise ValueError(f"invalid-svg-geometry: malformed XML: {exc}") from exc
    if _tag(root) != "svg":
        raise ValueError("invalid-svg-geometry: root element must be svg")
    _, _, view_w, view_h = _viewbox(root)
    scope = next(
        (
            node
            for node in root.iter()
            if _tag(node) == "g" and str(node.get("id", "")).startswith("layout-")
        ),
        root,
    )
    limitations = sorted({_tag(node) for node in scope.iter() if _tag(node) not in SUPPORTED_GEOMETRY})
    boxes: list[tuple[float, float, float, float]] = []
    rects: list[tuple[ET.Element, tuple[float, float, float, float]]] = []
    for node in scope.iter():
        box = _bbox(node)
        if box is not None:
            boxes.append(box)
            if _tag(node) == "rect" and (box[2] - box[0]) > 0 and (box[3] - box[1]) > 0:
                rects.append((node, box))
    coverage = "limited" if limitations or not boxes else "supported"
    if boxes:
        left = min(box[0] for box in boxes)
        top = min(box[1] for box in boxes)
        right = max(box[2] for box in boxes)
        bottom = max(box[3] for box in boxes)
        occupancy = max(0.0, min(1.0, (right - left) * (bottom - top) / (view_w * view_h)))
    else:
        occupancy = 0.0
    areas = [(box[2] - box[0]) * (box[3] - box[1]) for _, box in rects]
    focal_areas = [area for (node, _), area in zip(rects, areas) if node.get("data-focal") == "true"]
    non_focal = [area for (node, _), area in zip(rects, areas) if node.get("data-focal") != "true"]
    if focal_areas and non_focal:
        focal_dominance = max(focal_areas) / max(statistics.median(non_focal), 1.0)
    elif len(areas) >= 2:
        focal_dominance = max(areas) / max(statistics.median(areas), 1.0)
    else:
        focal_dominance = 1.0 if areas else 0.0
    centers = sorted(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2) for _, box in rects)
    gaps = [math.dist(centers[index - 1], centers[index]) for index in range(1, len(centers))]
    spacing_deviation = statistics.pstdev(gaps) / statistics.mean(gaps) if len(gaps) >= 2 and statistics.mean(gaps) else 0.0
    return {
        "schema": "ghb.visual-provisional-metrics.v1",
        "occupancy": {"value": round(occupancy, 6), "coverage": coverage},
        "focal-dominance": {"value": round(focal_dominance, 6), "coverage": coverage},
        "spacing-consistency": {"value": round(spacing_deviation, 6), "coverage": coverage},
        "limitations": limitations,
    }


def _pending(reasons: list[str]) -> dict[str, Any]:
    return {
        "schema": "ghb.visual-pilot-gate.v1",
        "decision": "pending",
        "proceed": False,
        "preference_rate": None,
        "represented_purpose_results": {},
        "structural_veto_count": 0,
        "blocking_false_positive_count": None,
        "advisory_false_positive_rate": None,
        "reasons": reasons,
    }


def evaluate_pilot_gate(
    preferences: dict[str, Any], review: dict[str, Any], deterministic: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate frozen U11 evidence; absent human judgments can never pass."""

    if preferences.get("schema") != "ghb.visual-preferences.v1":
        raise ValueError("invalid-visual-preferences-schema")
    if review.get("schema") != REVIEW_SCHEMA:
        raise ValueError("invalid-pilot-review-schema")
    if deterministic.get("schema") != DETERMINISTIC_SCHEMA:
        raise ValueError("invalid-pilot-deterministic-schema")
    assignments = review.get("pair_assignments")
    judgments = review.get("judgments")
    eligible_case_ids = review.get("eligible_case_ids")
    if (
        not isinstance(assignments, list)
        or not isinstance(judgments, list)
        or not isinstance(eligible_case_ids, list)
    ):
        raise ValueError("invalid-pilot-review-record")
    if not assignments or not judgments:
        return _pending(["insufficient-blind-review-evidence", "deterministic-audit-not-yet-eligible"])

    protocol = preferences.get("blind_review_protocol", {})
    assignment_by_case: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        case_id = assignment.get("page_case_id")
        roles = assignment.get("roles")
        if not isinstance(case_id, str) or case_id in assignment_by_case:
            raise ValueError("invalid-or-duplicate-pair-assignment")
        if not isinstance(roles, dict) or set(roles.values()) != {"baseline", "pilot"}:
            raise ValueError("invalid-pair-role-assignment")
        masked_ids = {assignment.get("masked_left_id"), assignment.get("masked_right_id")}
        if None in masked_ids or len(masked_ids) != 2 or set(roles) != masked_ids:
            raise ValueError("pair-assignment-mask-mismatch")
        if not isinstance(assignment.get("page_purpose"), str) or not assignment["page_purpose"]:
            raise ValueError("invalid-pair-page-purpose")
        assignment_by_case[case_id] = assignment
    if (
        len(eligible_case_ids) < 3
        or len(eligible_case_ids) != len(set(eligible_case_ids))
        or set(eligible_case_ids) != set(assignment_by_case)
    ):
        raise ValueError("incomplete-pilot-case-assignments")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    veto_count = 0
    required_audit = set(protocol.get("audit_fields", []))
    for judgment in judgments:
        missing = required_audit - set(judgment)
        if missing:
            raise ValueError(f"missing-review-audit-fields: {sorted(missing)}")
        case_id = judgment.get("page_case_id")
        reviewer = judgment.get("reviewer_id_hash")
        if case_id not in assignment_by_case or not isinstance(reviewer, str) or not reviewer:
            raise ValueError("invalid-review-identity")
        key = (case_id, reviewer)
        if key in seen:
            raise ValueError("duplicate-reviewer-page-judgment")
        seen.add(key)
        assignment = assignment_by_case[case_id]
        if judgment.get("masked_left_id") != assignment["masked_left_id"] or judgment.get("masked_right_id") != assignment["masked_right_id"]:
            raise ValueError("review-mask-mismatch")
        if judgment.get("presented_order") != [assignment["masked_left_id"], assignment["masked_right_id"]]:
            raise ValueError("review-presented-order-mismatch")
        choice = judgment.get("judgment")
        if choice not in {*assignment["roles"], "tie", "abstain"}:
            raise ValueError("invalid-review-judgment")
        rubric = judgment.get("rubric")
        if not isinstance(rubric, dict) or set(rubric) != set(protocol.get("rubric_dimensions", [])):
            raise ValueError("invalid-review-rubric")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in rubric.values()
        ):
            raise ValueError("invalid-review-rubric")
        if not isinstance(judgment.get("structural_veto"), bool):
            raise ValueError("invalid-review-structural-veto")
        if not isinstance(judgment.get("recorded_at"), str) or not judgment["recorded_at"]:
            raise ValueError("invalid-review-recorded-at")
        veto_count += bool(judgment.get("structural_veto"))
        grouped[case_id].append(judgment)

    minimum_reviewers = protocol.get("minimum_independent_eligible_reviewers_per_page", 3)
    minimum_non_tie = protocol.get("minimum_eligible_non_tie_judgments_per_page", 2)
    page_results: dict[str, str] = {}
    purpose_results: dict[str, list[str]] = defaultdict(list)
    for case_id, assignment in assignment_by_case.items():
        records = grouped.get(case_id, [])
        non_tie = [record for record in records if record["judgment"] not in {"tie", "abstain"}]
        if len(records) < minimum_reviewers or len(non_tie) < minimum_non_tie:
            return _pending(["insufficient-blind-review-evidence"])
        votes = defaultdict(int)
        for record in non_tie:
            votes[assignment["roles"][record["judgment"]]] += 1
        if votes["pilot"] == votes["baseline"]:
            return _pending(["page-preference-tie"])
        winner = "pilot" if votes["pilot"] > votes["baseline"] else "baseline"
        page_results[case_id] = winner
        purpose_results[assignment["page_purpose"]].append(winner)

    gate = preferences.get("deterministic_pilot_false_positive_gate", {})
    expected_pairs = set(gate.get("advisory_rule_case_pairs", []))
    results = deterministic.get("advisory_rule_case_results")
    if not isinstance(results, list):
        raise ValueError("invalid-advisory-audit")
    actual_pairs = [result.get("rule_case_pair") for result in results]
    if set(actual_pairs) != expected_pairs or len(actual_pairs) != len(expected_pairs):
        raise ValueError("incomplete-advisory-audit")
    allowed_dispositions = {"not-triggered", "true-positive", "false-positive"}
    if any(result.get("disposition") not in allowed_dispositions for result in results):
        raise ValueError("invalid-advisory-audit-disposition")
    blocking = deterministic.get("blocking_false_positives")
    if not isinstance(blocking, list):
        raise ValueError("invalid-blocking-false-positive-audit")
    advisory_false = sum(result["disposition"] == "false-positive" for result in results)
    advisory_rate = advisory_false / max(len(expected_pairs), 1)
    preference_rate = sum(result == "pilot" for result in page_results.values()) / len(page_results)
    represented = {
        purpose: "non-regressing" if "baseline" not in results else "regressed"
        for purpose, results in purpose_results.items()
    }
    reasons: list[str] = []
    if preference_rate < 0.70:
        reasons.append("pilot-preference-below-70-percent")
    if "regressed" in represented.values():
        reasons.append("represented-purpose-regression")
    if veto_count:
        reasons.append("structural-regression-veto")
    if len(blocking) > gate.get("blocking_false_positive_maximum", 0):
        reasons.append("blocking-false-positive-ceiling-exceeded")
    if advisory_rate > gate.get("advisory_false_positive_rate_maximum", 0.10):
        reasons.append("advisory-false-positive-ceiling-exceeded")
    return {
        "schema": "ghb.visual-pilot-gate.v1",
        "decision": "failed" if reasons else "passed",
        "proceed": not reasons,
        "preference_rate": round(preference_rate, 6),
        "represented_purpose_results": represented,
        "page_results": page_results,
        "structural_veto_count": veto_count,
        "blocking_false_positive_count": len(blocking),
        "advisory_false_positive_rate": round(advisory_rate, 6),
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    measure = subparsers.add_parser("measure")
    measure.add_argument("svg", type=Path)
    gate = subparsers.add_parser("pilot-gate")
    gate.add_argument("--preferences", type=Path, required=True)
    gate.add_argument("--review", type=Path, required=True)
    gate.add_argument("--deterministic", type=Path, required=True)
    gate.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "measure":
        result = measure_svg(args.svg.read_text(encoding="utf-8"))
    else:
        result = evaluate_pilot_gate(
            json.loads(args.preferences.read_text(encoding="utf-8")),
            json.loads(args.review.read_text(encoding="utf-8")),
            json.loads(args.deterministic.read_text(encoding="utf-8")),
        )
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if getattr(args, "output", None):
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if result.get("decision") in {None, "passed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
