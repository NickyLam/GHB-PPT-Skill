#!/usr/bin/env python3
"""Run the complete authored/finalized SVG quality gate as one JSON-capable check."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "ppt_master"))
from scripts.ppt_master.check_layout_diversity import (  # noqa: E402
    analyze_layout_sequence,
    extract_layout_markers,
)
from scripts.ghb_visual_quality import analyze_deck_quality, evaluate_page_quality  # noqa: E402


_PX_TO_PT = 0.75
_TYPOGRAPHY_ROLE_FLOORS = {
    "title": "min_title_pt",
    "body": "min_body_pt",
    "text": "min_body_pt",
    "label": "min_body_pt",
    "caption": "min_caption_pt",
    "source": "min_source_pt",
    "footer": "min_footer_pt",
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _style_value(node: ET.Element, name: str) -> str | None:
    direct = node.get(name)
    if direct is not None:
        return direct
    for declaration in node.get("style", "").split(";"):
        key, separator, value = declaration.partition(":")
        if separator and key.strip().lower() == name:
            return value.strip()
    return None


def _font_size_px(node: ET.Element, inherited: float | None) -> float | None:
    raw = _style_value(node, "font-size")
    if raw is None:
        return inherited
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(px|pt)?\s*", raw, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    return value / _PX_TO_PT if match.group(2) and match.group(2).lower() == "pt" else value


def _normalized_text_role(node: ET.Element, inherited: str | None) -> str | None:
    explicit = (node.get("data-qa-role") or "").strip().lower()
    if explicit in _TYPOGRAPHY_ROLE_FLOORS:
        return explicit
    identifier = (node.get("id") or "").strip().lower().replace("_", "-")
    prefixes = {
        "main-title": "title",
        "title": "title",
        "body": "body",
        "text": "text",
        "label": "label",
        "caption": "caption",
        "source": "source",
        "footer": "footer",
    }
    for prefix, role in prefixes.items():
        if identifier == prefix or identifier.startswith(f"{prefix}-"):
            return role
    return inherited


def typography_contract_errors(svg: str, profile: dict[str, object]) -> list[str]:
    """Enforce role-specific typography floors for strict visual profiles.

    SVG user units in this pipeline are CSS pixels, so font sizes are converted
    to PowerPoint points with the standard 0.75 factor. Roles may be declared
    on a text element, inherited from a containing group, or expressed through
    the stable role-oriented id prefixes used by the DrawingML readback gate.
    """
    typography = profile.get("typography")
    if not isinstance(typography, dict) or typography.get("enforcement") != "strict":
        return []
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        return [f"typography-invalid-svg: {exc}"]

    errors: list[str] = []

    def walk(
        node: ET.Element,
        *,
        inherited_role: str | None = None,
        inherited_size: float | None = None,
        in_layout: bool = False,
        hidden: bool = False,
    ) -> None:
        style = (node.get("style") or "").replace(" ", "").lower()
        hidden = hidden or node.get("display", "").lower() == "none" or "display:none" in style
        if hidden:
            return
        in_layout = in_layout or node.get("data-layout") is not None
        role = _normalized_text_role(node, inherited_role)
        size_px = _font_size_px(node, inherited_size)
        if _local_name(node.tag) == "text" and "".join(node.itertext()).strip():
            label = node.get("id") or "text"
            if role is None and in_layout:
                errors.append(
                    f"typography-unclassified-text: {label} inside data-layout must declare a role"
                )
            elif role in _TYPOGRAPHY_ROLE_FLOORS:
                floor_name = _TYPOGRAPHY_ROLE_FLOORS[role]
                floor = typography.get(floor_name)
                if not isinstance(floor, (int, float)) or isinstance(floor, bool) or floor <= 0:
                    errors.append(f"typography-invalid-profile-floor: {floor_name}")
                elif size_px is None or size_px <= 0:
                    errors.append(f"typography-{role}-missing-size: {label}")
                else:
                    observed_pt = size_px * _PX_TO_PT
                    if observed_pt + 1e-9 < float(floor):
                        errors.append(
                            f"typography-{role}-below-min: {label} is {observed_pt:.2f}pt; "
                            f"requires {float(floor):g}pt"
                        )
        for child in node:
            walk(
                child,
                inherited_role=role,
                inherited_size=size_px,
                in_layout=in_layout,
                hidden=hidden,
            )

    walk(root)
    return errors


def semantic_contract_errors(svg: str, page_schema: dict[str, object]) -> list[str]:
    """Require visible, machine-auditable semantics for purpose-led pages."""
    purpose = page_schema.get("page_purpose")
    if not isinstance(purpose, str) or not purpose:
        return []
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        return [f"semantic-invalid-svg: {exc}"]

    layout_scope = next(
        (node for node in root.iter() if node.get("data-layout") is not None),
        root,
    )
    nodes = list(layout_scope.iter())

    def marked(attribute: str) -> list[ET.Element]:
        return [node for node in nodes if (node.get(attribute) or "").strip()]

    flow_nodes = marked("data-flow-node")
    flow_edges = [
        node
        for node in nodes
        if (node.get("data-flow-from") or "").strip()
        and (node.get("data-flow-to") or "").strip()
    ]
    steps = marked("data-step")
    lanes = marked("data-lane")
    components = [
        node
        for node in nodes
        if (node.get("data-component") or "").strip()
        and (node.get("data-component-id") or "").strip()
    ]
    evidence = marked("data-evidence")
    metrics = marked("data-metric")
    layers = marked("data-layer")
    focal = [node for node in nodes if (node.get("data-focal") or "").lower() == "true"]
    decisions = marked("data-decision") + marked("data-recommendation")
    risks = marked("data-risk")
    mitigations = marked("data-mitigation")

    errors: list[str] = []
    if purpose == "process" and not (
        (len(flow_nodes) >= 2 and flow_edges) or len(steps) >= 2 or len(lanes) >= 2
    ):
        errors.append("semantic-process-missing-flow")
    elif purpose == "instruction" and not (len(steps) >= 2 or (len(flow_nodes) >= 2 and flow_edges)):
        errors.append("semantic-instruction-missing-steps")
    elif purpose == "timeline" and len(steps) < 2:
        errors.append("semantic-timeline-missing-steps")
    elif purpose == "architecture" and len(layers) < 2:
        errors.append("semantic-architecture-missing-layers")

    if purpose == "comparison":
        component_ids = {(node.get("data-component-id") or "").strip() for node in components}
        if len(component_ids) < 2:
            errors.append("semantic-comparison-missing-components")
    if purpose in {"evidence", "case-study", "screenshot"} and not evidence:
        errors.append("semantic-evidence-missing-evidence")
    if purpose in {"metrics", "data-story"} and not metrics:
        errors.append("semantic-metrics-missing-metrics")
    if purpose in {"decision", "recommendation"} and not decisions:
        errors.append("semantic-decision-missing-decision")
    if purpose == "risk" and (not risks or not mitigations):
        errors.append("semantic-risk-missing-pairs")
    if purpose in {"hero", "section-anchor", "closing"} and not focal:
        errors.append("semantic-hero-missing-focal")
    return errors


def _ghb_chrome_errors(
    path: Path,
    *,
    stage: str,
    workflow_mode: str = "standard",
    template_profile: dict[str, object] | None = None,
) -> list[str]:
    """Verify the GHB surface contract and authored/finalized background state."""
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as exc:
        return [f"cannot parse GHB chrome: {exc}"]
    groups = {node.get("id"): node for node in root.iter() if node.get("id")}
    errors: list[str] = []
    if stage == "authored" and "bg" not in groups:
        errors.append("authored SVG must contain one preview background group id='bg'")
    if stage == "finalized" and "bg" in groups:
        errors.append("finalized SVG still contains preview background group id='bg'")
    header = groups.get("header")
    if header is not None:
        def numeric(node: ET.Element, name: str) -> float | None:
            try:
                return float(node.get(name, ""))
            except (TypeError, ValueError):
                return None

        def qa_box(node: ET.Element) -> tuple[float, float, float, float] | None:
            raw = (node.get("data-qa-box") or "").replace(",", " ").split()
            if len(raw) == 4:
                try:
                    return tuple(float(value) for value in raw)
                except ValueError:
                    return None
            if node.tag.rsplit("}", 1)[-1] != "text":
                return None
            try:
                x = float(node.get("x", "nan"))
                y = float(node.get("y", "nan"))
                size = float(node.get("font-size", "nan"))
            except ValueError:
                return None
            text = "".join(node.itertext()).strip()
            if not text or not all(value == value for value in (x, y, size)):
                return None
            units = sum(
                1.0 if "\u3400" <= char <= "\u9fff" else 0.58
                for char in text
            )
            width = units * size * 1.05
            anchor = node.get("text-anchor", "start")
            left = x - width if anchor == "end" else x - width / 2 if anchor == "middle" else x
            return left, y - size * 0.9, width, size * 1.3

        main_title = next(
            (
                node for node in header.iter()
                if node.get("data-qa-role") == "title"
                and node.get("id") != "template-section-label"
            ),
            None,
        )
        if main_title is None:
            authored_titles = [
                node for node in header.iter()
                if node.tag.rsplit("}", 1)[-1] == "text"
                and node.get("id") != "template-section-label"
                and numeric(node, "font-size") is not None
            ]
            if authored_titles:
                main_title = max(
                    authored_titles, key=lambda node: numeric(node, "font-size") or 0.0
                )
        section_label = next(
            (node for node in header.iter() if node.get("id") == "template-section-label"),
            None,
        )
        if main_title is not None and section_label is not None:
            title_box = qa_box(main_title)
            section_box = qa_box(section_label)
            if title_box is None or section_box is None:
                errors.append(
                    "header-safe-zone-contract: main title and template section label "
                    "must declare data-qa-box"
                )
            else:
                tx, ty, tw, th = title_box
                # The semantic label is replaced by the native GHB frame at
                # merge time. Reserve that full template footprint rather than
                # only the short source text's glyph box.
                zones = (
                    template_profile.get("header_safe_zones")
                    if isinstance(template_profile, dict)
                    else None
                )
                section_zone = zones.get("section") if isinstance(zones, dict) else None
                sx, sy, sw, sh = (
                    tuple(float(value) for value in section_zone)
                    if isinstance(section_zone, list) and len(section_zone) == 4
                    else (930.0, 96.0, 294.0, 80.0)
                )
                overlap_w = max(0.0, min(tx + tw, sx + sw) - max(tx, sx))
                overlap_h = max(0.0, min(ty + th, sy + sh) - max(ty, sy))
                if overlap_w > 0 and overlap_h > 0:
                    errors.append(
                        "header-safe-zone-collision: main title overlaps the native "
                        "template section-frame reservation"
                    )
        marker_candidates = [
            node
            for node in header.iter()
            if node.tag.rsplit("}", 1)[-1] == "rect"
            and numeric(node, "width") is not None
            and numeric(node, "height") is not None
            and (numeric(node, "width") or 0.0) <= 12
            and (numeric(node, "height") or 0.0) >= 20
        ]
        title_candidates = [
            node
            for node in header.iter()
            if node.tag.rsplit("}", 1)[-1] == "text"
            and node.get("id") != "template-section-label"
            and numeric(node, "font-size") is not None
            and numeric(node, "y") is not None
        ]
        if marker_candidates and title_candidates:
            marker = marker_candidates[0]
            title = max(title_candidates, key=lambda node: numeric(node, "font-size") or 0.0)
            marker_center = (numeric(marker, "y") or 0.0) + (numeric(marker, "height") or 0.0) / 2
            title_center = (numeric(title, "y") or 0.0) - (numeric(title, "font-size") or 0.0) * 0.35
            if abs(marker_center - title_center) > 4:
                errors.append(
                    "GHB title marker must be vertically centered with the main title "
                    f"(delta={abs(marker_center - title_center):.1f}px)"
                )
    surface = groups.get("bg-surface")
    if surface is None:
        if workflow_mode == "strict":
            errors.append("missing GHB content surface group id='bg-surface'")
        return errors
    if stage == "authored" and workflow_mode == "strict":
        rectangles = [node for node in surface.iter() if node.tag.rsplit("}", 1)[-1] == "rect"]
        surface_profile = (
            template_profile.get("body_surface")
            if isinstance(template_profile, dict)
            else None
        )
        surface_values = (
            [float(value) for value in surface_profile]
            if isinstance(surface_profile, list) and len(surface_profile) == 4
            else [56.0, 96.0, 1168.0, 608.0]
        )
        expected = dict(zip(("x", "y", "width", "height"), surface_values))
        if not rectangles:
            errors.append("GHB content surface must contain its profiled rectangle")
        elif any(float(rectangles[0].get(key, "nan")) != float(value) for key, value in expected.items()):
            errors.append(
                "GHB content surface must match template_profile body_surface "
                f"{surface_values}"
            )
    return errors
from scripts.ppt_master.svg_quality_checker import SVGQualityChecker  # noqa: E402
from scripts.ppt_master.visual_asset_checker import (  # noqa: E402
    _apply_content_plan,
    check_svg,
)


def check_project(
    project: Path,
    *,
    stage: str,
    workflow_mode: str = "standard",
) -> dict[str, object]:
    svg_dir = project / ("svg_final" if stage == "finalized" else "svg_output")
    files = sorted(svg_dir.glob("*.svg")) if svg_dir.is_dir() else []
    if not files:
        return {
            "passed": False,
            "stage": stage,
            "files": [],
            "layout_issues": [],
            "project_errors": [f"no SVG files found: {svg_dir}"],
            "error_count": 1,
            "warning_count": 0,
            "visual_quality": {
                "schema": "ghb.visual-quality-report.v1",
                "stage": stage,
                "page_count": 0,
                "deck_metrics": {
                    "composition_fingerprints": [],
                    "focal_zones": [],
                    "densities": [],
                    "rhythm_roles": [],
                    "layout_variants": [],
                },
                "deck_findings": [],
                "limitations": ["no-svg-files"],
            },
        }

    icons_dir = Path(__file__).resolve().parents[1] / "templates" / "icons"
    checker = SVGQualityChecker()
    plan_path = project / "layout_plan.json"
    try:
        plan_payload = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.is_file() else []
        plan_by_slide = {
            int(row["slide"]): row
            for row in plan_payload
            if isinstance(row, dict) and isinstance(row.get("slide"), int)
        } if isinstance(plan_payload, list) else {}
    except (OSError, ValueError, TypeError):
        plan_by_slide = {}
    profile_path = project / "visual_profile.json"
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}
        if not isinstance(profile, dict):
            profile = {}
    except (OSError, ValueError):
        profile = {}
    template_profile_path = project / "analysis" / "template_profile.json"
    try:
        template_profile = (
            json.loads(template_profile_path.read_text(encoding="utf-8"))
            if template_profile_path.is_file()
            else {}
        )
        if not isinstance(template_profile, dict):
            template_profile = {}
    except (OSError, ValueError):
        template_profile = {}
    visual_results = []
    page_quality_results: list[dict[str, object]] = []
    layouts: list[str] = []
    file_payloads: list[dict[str, object]] = []
    for path in files:
        svg_text = path.read_text(encoding="utf-8")
        svg_result = checker.check_file(str(path), "ppt169")
        visual_result = check_svg(path, stage=stage, icons_dir=icons_dir)
        visual_result.errors.extend(
            _ghb_chrome_errors(
                path,
                stage=stage,
                workflow_mode=workflow_mode,
                template_profile=template_profile,
            )
        )
        visual_results.append(visual_result)
        markers = extract_layout_markers(path.read_text(encoding="utf-8"))
        layouts.append(markers[0] if markers else "missing")
        match = re.match(r"(\d+)", path.name)
        slide_number = int(match.group(1)) if match else None
        row = plan_by_slide.get(slide_number, {}) if slide_number is not None else {}
        authored_schema = row.get("page_schema") if isinstance(row.get("page_schema"), dict) else None
        if authored_schema is not None:
            page_schema = dict(authored_schema)
        else:
            legacy_density = row.get("density")
            page_schema = {
                "density": "balanced" if legacy_density == "anchor" else legacy_density,
                "rhythm_role": "continuity",
                "emphasis": "distributed",
                "layout_variant": row.get("layout_archetype") or visual_result.layout,
            }
        typography_findings = typography_contract_errors(svg_text, profile)
        semantic_findings = semantic_contract_errors(svg_text, page_schema)
        if workflow_mode == "strict":
            visual_result.errors.extend(typography_findings)
            visual_result.errors.extend(semantic_findings)
        elif workflow_mode == "standard":
            # Standard keeps these findings visible for the design/QA loop but
            # does not make detailed metadata or role floors a build blocker.
            visual_result.warnings.extend(typography_findings)
            visual_result.warnings.extend(semantic_findings)
        slide_id = str(page_schema.get("slide_id") or row.get("slide_id") or f"slide-{slide_number or len(page_quality_results) + 1}")
        try:
            page_quality = evaluate_page_quality(
                svg_text,
                slide_id=slide_id,
                profile=profile,
                page_schema=page_schema,
            )
        except (OSError, ValueError) as exc:
            page_quality = {
                "slide_id": slide_id,
                "page_schema": page_schema,
                "measurements": {},
                "coverage": {
                    "status": "not-measurable",
                    "measured_elements": 0,
                    "candidate_elements": 0,
                    "ratio": 0.0,
                    "limitations": ["invalid-svg-geometry"],
                },
                "findings": [{
                    "code": "visual-invalid-geometry",
                    "severity": "error",
                    "slide_id": slide_id,
                    "evidence": {"message": str(exc)},
                    "expected": {"geometry": "valid SVG geometry"},
                    "suggested_action": "Repair malformed or non-finite SVG coordinates.",
                }],
                "suppressed_issue_codes": [],
            }
        page_quality_results.append(page_quality)
        file_payloads.append(
            {
                "file": str(path),
                "slide_id": slide_id,
                "layout": visual_result.layout,
                "text_chars": visual_result.text_chars,
                "text_elements": visual_result.text_elements,
                "svg_quality_errors": svg_result["errors"],
                "svg_quality_warnings": svg_result["warnings"],
                "visual_errors": visual_result.errors,
                "visual_warnings": visual_result.warnings,
                "visual_metrics": page_quality["measurements"],
                "visual_coverage": page_quality["coverage"],
                "visual_findings": page_quality["findings"],
            }
        )

    project_errors = _apply_content_plan(visual_results, plan_path if plan_path.is_file() else None)
    # _apply_content_plan mutates visual results; refresh those fields.
    for payload, visual_result in zip(file_payloads, visual_results):
        payload["visual_errors"] = visual_result.errors
        payload["visual_warnings"] = visual_result.warnings
    layout_issues = analyze_layout_sequence(layouts)
    measurable_pages = [page for page in page_quality_results if page.get("measurements")]
    deck_quality = analyze_deck_quality(measurable_pages, profile=profile)
    # Layout variety is design advice, not evidence that the authored deck is
    # invalid. Keep it visible without forcing content into an unsuitable
    # built-in diagram merely to satisfy an archetype quota.
    error_count = len(project_errors)
    warning_count = len(layout_issues) + len(deck_quality["findings"])
    for payload in file_payloads:
        error_count += len(payload["svg_quality_errors"]) + len(payload["visual_errors"])
        warning_count += len(payload["svg_quality_warnings"]) + len(payload["visual_warnings"])
        error_count += sum(item["severity"] == "error" for item in payload["visual_findings"])
        warning_count += sum(item["severity"] == "warning" for item in payload["visual_findings"])
    return {
        "passed": error_count == 0,
        "stage": stage,
        "svg_dir": str(svg_dir),
        "files": file_payloads,
        "layouts": layouts,
        "layout_issues": layout_issues,
        "project_errors": project_errors,
        "visual_quality": {
            "schema": "ghb.visual-quality-report.v1",
            "stage": stage,
            "page_count": len(page_quality_results),
            "deck_metrics": deck_quality["measurements"],
            "deck_findings": deck_quality["findings"],
            "limitations": sorted({
                limitation
                for page in page_quality_results
                for limitation in page["coverage"].get("limitations", [])
            }),
        },
        "error_count": error_count,
        "warning_count": warning_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--stage", choices=("authored", "finalized"), required=True)
    parser.add_argument(
        "--workflow-mode",
        choices=("quick", "standard", "strict"),
        default="standard",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = check_project(
        args.project,
        stage=args.stage,
        workflow_mode=args.workflow_mode,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"[{'PASS' if payload['passed'] else 'FAIL'}] SVG {args.stage}: "
            f"files={len(payload['files'])} errors={payload['error_count']} "
            f"warnings={payload['warning_count']}"
        )
        for item in payload["files"]:
            for message in item["svg_quality_errors"] + item["visual_errors"]:
                print(f"  ERROR {Path(item['file']).name}: {message}")
            for message in item["svg_quality_warnings"] + item["visual_warnings"]:
                print(f"  WARN {Path(item['file']).name}: {message}")
            for finding in item["visual_findings"]:
                print(f"  {finding['severity'].upper()} {Path(item['file']).name}: {finding['code']}")
        for message in payload["layout_issues"]:
            print(f"  WARN project: {message}")
        for message in payload["project_errors"]:
            print(f"  ERROR project: {message}")
        for finding in payload["visual_quality"]["deck_findings"]:
            print(f"  WARN deck: {finding['code']}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
