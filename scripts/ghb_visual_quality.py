#!/usr/bin/env python3
"""Offline provisional SVG metrics and the auditable U11 pilot gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.ppt_master.visual_asset_checker import Box, measure_visible_geometry  # noqa: E402


REVIEW_SCHEMA = "ghb.visual-pilot-review.v1"
DETERMINISTIC_SCHEMA = "ghb.visual-pilot-deterministic.v1"


def _union_area(boxes: list[Box]) -> float:
    xs = sorted({value for box in boxes for value in (box.x, box.x + box.width)})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted(
            (box.y, box.y + box.height)
            for box in boxes
            if box.x < right and box.x + box.width > left and box.height > 0
        )
        if not intervals:
            continue
        start, end = intervals[0]
        height = 0.0
        for next_start, next_end in intervals[1:]:
            if next_start > end:
                height += end - start
                start, end = next_start, next_end
            else:
                end = max(end, next_end)
        total += (right - left) * (height + end - start)
    return total


def _metric(value: float | str | None, coverage: str) -> dict[str, Any]:
    return {
        "value": round(value, 6) if isinstance(value, float) else value,
        "coverage": coverage,
    }


def _geometry_fingerprint(observations: list[dict[str, Any]], body: list[float]) -> str:
    bx, by, width, height = body
    normalized = []
    for item in observations:
        x, y, box_w, box_h = item["box"]
        normalized.append(
            (
                item["role"],
                round((x - bx) / width, 2),
                round((y - by) / height, 2),
                round(box_w / width, 2),
                round(box_h / height, 2),
                bool(item["focal"]),
            )
        )
    normalized.sort()
    canonical = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _focal_zone(observations: list[dict[str, Any]], body: list[float]) -> str | None:
    candidates = [item for item in observations if item["focal"]]
    candidates = [item for item in candidates if item["box"][2] * item["box"][3] > 0]
    if not candidates:
        return None
    focal = max(candidates, key=lambda item: item["box"][2] * item["box"][3])
    center = focal["box"][0] + focal["box"][2] / 2
    relative = (center - body[0]) / body[2]
    return "left" if relative < 1 / 3 else "right" if relative > 2 / 3 else "center"


def measure_svg(
    svg: str,
    *,
    primary_color: str = "#AB1F29",
    base_unit: float = 8.0,
) -> dict[str, Any]:
    """Return explainable metrics derived from visible geometry, never markers."""
    raw = measure_visible_geometry(svg)
    body = raw["body_canvas"]
    body_area = body[2] * body[3]
    observations = raw["observations"]
    boxes = [Box(*item["box"]) for item in observations]
    areas = [box.area for box in boxes if box.area > 0]
    focal_areas = [Box(*item["box"]).area for item in observations if item["focal"] and Box(*item["box"]).area > 0]
    non_focal = [Box(*item["box"]).area for item in observations if not item["focal"] and Box(*item["box"]).area > 0]
    if focal_areas and non_focal:
        focal_ratio = max(focal_areas) / max(statistics.median(non_focal), 1.0)
    elif len(areas) >= 2:
        focal_ratio = max(areas) / max(statistics.median(areas), 1.0)
    else:
        focal_ratio = 1.0 if areas else 0.0

    gaps = raw["gaps"]
    spacing_deviation = (
        statistics.pstdev(gaps) / statistics.mean(gaps)
        if len(gaps) >= 2 and statistics.mean(gaps)
        else 0.0
    )
    edges = [coordinate for box in boxes for coordinate in (box.x, box.y, box.x + box.width, box.y + box.height)]
    alignment_deviation = (
        statistics.mean(min(value % base_unit, base_unit - value % base_unit) for value in edges) / base_unit
        if edges and base_unit > 0
        else 0.0
    )
    primary = primary_color.strip().upper()
    primary_boxes = [
        Box(*item["box"])
        for item in observations
        if item["fill"] == primary and Box(*item["box"]).area > 0
    ]
    focal_primary_fill = any(item["focal"] and item["fill"] == primary for item in observations)
    title_sizes = [item["font_size"] for item in raw["text_sizes"] if item["role"] == "title"]
    body_sizes = [item["font_size"] for item in raw["text_sizes"] if item["role"] != "title"]
    if not title_sizes and len(raw["text_sizes"]) >= 2:
        largest = max(item["font_size"] for item in raw["text_sizes"])
        smaller = [item["font_size"] for item in raw["text_sizes"] if item["font_size"] < largest]
        if smaller:
            title_sizes = [largest]
            body_sizes = smaller
    title_body_ratio = (
        max(title_sizes) / statistics.median(body_sizes) if title_sizes and body_sizes else None
    )
    raw_boxes = [Box(*item["box"]) for item in raw["raw_observations"]]
    if raw_boxes:
        left = min(box.x for box in raw_boxes)
        top = min(box.y for box in raw_boxes)
        right = max(box.x + box.width for box in raw_boxes)
        bottom = max(box.y + box.height for box in raw_boxes)
        content_bounds: dict[str, float] | None = {
            "x": round(left, 6),
            "y": round(top, 6),
            "width": round(right - left, 6),
            "height": round(bottom - top, 6),
        }
    else:
        content_bounds = None
    coverage = raw["coverage"]
    status = coverage["status"]
    return {
        "schema": "ghb.visual-metrics.v1",
        "occupancy": _metric(raw["occupied_area"] / body_area if body_area else 0.0, status),
        "focal-dominance": _metric(focal_ratio, status),
        "focal-emphasis": {
            "area_ratio": round(focal_ratio, 6),
            "primary_fill": focal_primary_fill,
            "coverage": status,
        },
        "title-body-scale": _metric(title_body_ratio, "supported" if title_body_ratio is not None else "not-measurable"),
        "alignment-deviation": _metric(alignment_deviation, status),
        "spacing-consistency": _metric(spacing_deviation, status),
        "minimum-component-gap": _metric(min(gaps) if gaps else None, status if gaps else "not-measurable"),
        "emphasis-color-area": _metric(_union_area(primary_boxes) / body_area if body_area else 0.0, status),
        "composition-fingerprint": {
            "value": _geometry_fingerprint(observations, body),
            "coverage": status,
            "source": "geometry",
        },
        "focal-zone": _metric(_focal_zone(observations, body), status if observations else "not-measurable"),
        "content-bounds": {"value": content_bounds, "coverage": status if content_bounds else "not-measurable"},
        "coverage": coverage,
        "limitations": coverage["limitations"],
    }


def _finding(
    code: str,
    slide_id: str,
    evidence: dict[str, Any],
    expected: dict[str, Any],
    action: str,
    *,
    severity: str = "warning",
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "slide_id": slide_id,
        "evidence": evidence,
        "expected": expected,
        "suggested_action": action,
    }


def _exceptions(page_schema: dict[str, Any]) -> set[str]:
    values = page_schema.get("policy_exceptions", [])
    return {item for item in values if isinstance(item, str)} if isinstance(values, list) else set()


def evaluate_page_quality(
    svg: str,
    *,
    slide_id: str,
    profile: dict[str, Any],
    page_schema: dict[str, Any],
) -> dict[str, Any]:
    """Apply advisory GHB policy without mutating the raw measurements."""
    brand = profile.get("brand") if isinstance(profile.get("brand"), dict) else {}
    spacing = profile.get("spacing") if isinstance(profile.get("spacing"), dict) else {}
    metrics = measure_svg(
        svg,
        primary_color=str(brand.get("primary", "#AB1F29")),
        base_unit=float(spacing.get("base_unit", 8)),
    )
    findings: list[dict[str, Any]] = []
    requested_exceptions = _exceptions(page_schema)
    occupancy_policy = profile.get("occupancy", {}).get("body", {}) if isinstance(profile.get("occupancy"), dict) else {}
    minimum = float(occupancy_policy.get("min", 0.42))
    maximum = float(occupancy_policy.get("max", 0.78))
    occupancy = metrics["occupancy"]
    if occupancy["coverage"] != "not-measurable" and occupancy["value"] < minimum:
        findings.append(_finding(
            "visual-occupancy-below-min", slide_id,
            {"occupancy": occupancy["value"], "coverage": occupancy["coverage"]},
            {"min": minimum, "max": maximum},
            "Increase the scale or spread of meaningful body components.",
        ))
    if occupancy["coverage"] != "not-measurable" and occupancy["value"] > maximum:
        findings.append(_finding(
            "visual-occupancy-above-max", slide_id,
            {"occupancy": occupancy["value"], "coverage": occupancy["coverage"]},
            {"min": minimum, "max": maximum},
            "Reduce or split body components to restore whitespace.",
        ))
    typography = profile.get("typography") if isinstance(profile.get("typography"), dict) else {}
    ratio = metrics["title-body-scale"]
    ratio_min = float(typography.get("min_title_body_ratio", 1.5))
    if ratio["value"] is not None and ratio["value"] < ratio_min:
        findings.append(_finding(
            "visual-title-body-scale-low", slide_id,
            {"title_body_ratio": ratio["value"]}, {"min": ratio_min},
            "Increase title scale relative to body text.",
        ))
    min_gap = float(spacing.get("min_component_gap", 16))
    gap_metric = metrics["minimum-component-gap"]
    if gap_metric["value"] is not None and gap_metric["value"] < min_gap:
        findings.append(_finding(
            "visual-component-gap-small", slide_id,
            {"minimum_gap": gap_metric["value"]}, {"min": min_gap},
            "Separate neighboring components while preserving equal sizing.",
        ))
    if metrics["spacing-consistency"]["value"] > 0.45:
        findings.append(_finding(
            "visual-spacing-inconsistent", slide_id,
            {"coefficient_of_variation": metrics["spacing-consistency"]["value"]},
            {"advisory_max": 0.45},
            "Use a consistent spacing scale between peer components.",
        ))
    if metrics["alignment-deviation"]["value"] > 0.35:
        findings.append(_finding(
            "visual-alignment-deviation", slide_id,
            {"grid_deviation": metrics["alignment-deviation"]["value"]},
            {"advisory_max": 0.35, "base_unit": spacing.get("base_unit", 8)},
            "Align component edges to the profile spacing grid.",
        ))
    if metrics["emphasis-color-area"]["value"] > 0.35:
        findings.append(_finding(
            "visual-primary-color-overuse", slide_id,
            {"primary_color_area": metrics["emphasis-color-area"]["value"]},
            {"advisory_max": 0.35},
            "Reserve the primary brand color for focal emphasis.",
        ))
    if (
        page_schema.get("emphasis") == "single-focal"
        and metrics["focal-dominance"]["value"] <= 1.1
        and not metrics["focal-emphasis"]["primary_fill"]
    ):
        findings.append(_finding(
            "visual-focal-dominance-low", slide_id,
            {"focal_ratio": metrics["focal-dominance"]["value"]},
            {"advisory_min": 1.1},
            "Increase focal contrast through scale, weight, or color without changing peer card sizes.",
        ))
    override = page_schema.get("bounds_override")
    observed_bounds = metrics["content-bounds"]
    if isinstance(override, dict) and observed_bounds["coverage"] == "supported" and isinstance(observed_bounds["value"], dict):
        expected_box = Box(*(float(override[key]) for key in ("x", "y", "width", "height")))
        value = observed_bounds["value"]
        observed_box = Box(*(float(value[key]) for key in ("x", "y", "width", "height")))
        tolerance = 0.5
        outside = (
            observed_box.x < expected_box.x - tolerance
            or observed_box.y < expected_box.y - tolerance
            or observed_box.x + observed_box.width > expected_box.x + expected_box.width + tolerance
            or observed_box.y + observed_box.height > expected_box.y + expected_box.height + tolerance
        )
        if outside:
            findings.append(_finding(
                "visual-explicit-bounds-violation", slide_id,
                {"observed": value, "coverage": "supported"},
                {"bounds_override": override, "tolerance": tolerance},
                "Move or resize content to satisfy the explicitly declared measurable bounds.",
                severity="error",
            ))
    if metrics["coverage"]["status"] == "partial":
        findings.append(_finding(
            "visual-coverage-partial", slide_id,
            metrics["coverage"], {"status": "supported"},
            "Add QA boxes or flatten supported geometry before relying on balance findings.",
        ))
    elif metrics["coverage"]["status"] == "not-measurable":
        findings.append(_finding(
            "visual-not-measurable", slide_id,
            metrics["coverage"], {"measured_elements": ">=1"},
            "Provide visible supported geometry or declared QA boxes.",
        ))
    suppressed = {
        item["code"]
        for item in findings
        if item["severity"] == "warning" and item["code"] in requested_exceptions
    }
    findings = [
        item
        for item in findings
        if not (item["severity"] == "warning" and item["code"] in requested_exceptions)
    ]
    return {
        "slide_id": slide_id,
        "page_schema": page_schema,
        "measurements": metrics,
        "coverage": metrics["coverage"],
        "findings": findings,
        "suppressed_issue_codes": sorted(suppressed),
    }


def analyze_deck_quality(pages: list[dict[str, Any]], *, profile: dict[str, Any]) -> dict[str, Any]:
    """Evaluate geometry/rhythm streaks; all results remain advisory."""
    fingerprints = [
        page["measurements"]["composition-fingerprint"]["value"]
        if page["coverage"]["status"] != "not-measurable" else None
        for page in pages
    ]
    focal_zones = [
        page["measurements"]["focal-zone"]["value"]
        if page["coverage"]["status"] != "not-measurable" else None
        for page in pages
    ]
    densities = [page.get("page_schema", {}).get("density") for page in pages]
    roles = [page.get("page_schema", {}).get("rhythm_role") for page in pages]
    variants = [page.get("page_schema", {}).get("layout_variant") for page in pages]
    findings: list[dict[str, Any]] = []

    def repeated_runs(values: list[Any], minimum: int) -> list[tuple[int, int, Any]]:
        runs: list[tuple[int, int, Any]] = []
        start = 0
        for index in range(1, len(values) + 1):
            if index < len(values) and values[index] == values[start] and values[start] is not None:
                continue
            if values[start] is not None and index - start >= minimum:
                runs.append((start, index - 1, values[start]))
            start = index
        return runs

    def add_run(code: str, run: tuple[int, int, Any], action: str) -> None:
        start, end, value = run
        affected = pages[start : end + 1]
        if any(code in _exceptions(page.get("page_schema", {})) for page in affected):
            return
        findings.append({
            "code": code,
            "severity": "warning",
            "slide_ids": [page["slide_id"] for page in affected],
            "evidence": {"value": value, "streak": end - start + 1},
            "expected": {"max_streak": end - start},
            "suggested_action": action,
        })

    for run in repeated_runs(fingerprints, 2):
        add_run("visual-composition-repeated", run, "Vary actual component geometry, not only data-layout markers.")
    for run in repeated_runs(focal_zones, 3):
        add_run("visual-focal-zone-streak", run, "Move the focal component to vary deck rhythm.")
    max_role = int(profile.get("deck_rhythm", {}).get("max_same_role_streak", 3)) if isinstance(profile.get("deck_rhythm"), dict) else 3
    for run in repeated_runs(roles, max_role + 1):
        add_run("visual-rhythm-role-streak", run, "Insert an anchor or transition page.")
    for run in repeated_runs(densities, 4):
        add_run("visual-density-rhythm-drift", run, "Alternate density where the narrative permits.")
    for run in repeated_runs(variants, 3):
        add_run("visual-variant-repetition", run, "Use a different semantic variant or component arrangement.")
    return {
        "schema": "ghb.visual-deck-metrics.v1",
        "measurements": {
            "composition_fingerprints": fingerprints,
            "focal_zones": focal_zones,
            "densities": densities,
            "rhythm_roles": roles,
            "layout_variants": variants,
        },
        "findings": findings,
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
            value != "not-scored"
            and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 1 <= value <= 5
            )
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
