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


def _ghb_chrome_errors(path: Path, *, stage: str) -> list[str]:
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
    surface = groups.get("bg-surface")
    if surface is None:
        errors.append("missing GHB content surface group id='bg-surface'")
        return errors
    if stage == "authored":
        rectangles = [node for node in surface.iter() if node.tag.rsplit("}", 1)[-1] == "rect"]
        expected = {"x": "56", "y": "96", "width": "1168", "height": "608"}
        if not rectangles:
            errors.append("GHB content surface must contain its standard rectangle")
        elif any(float(rectangles[0].get(key, "nan")) != float(value) for key, value in expected.items()):
            errors.append("GHB content surface must be x=56 y=96 width=1168 height=608")
    return errors
from scripts.ppt_master.svg_quality_checker import SVGQualityChecker  # noqa: E402
from scripts.ppt_master.visual_asset_checker import (  # noqa: E402
    _apply_content_plan,
    check_svg,
)


def check_project(project: Path, *, stage: str) -> dict[str, object]:
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
    visual_results = []
    page_quality_results: list[dict[str, object]] = []
    layouts: list[str] = []
    file_payloads: list[dict[str, object]] = []
    for path in files:
        svg_result = checker.check_file(str(path), "ppt169")
        visual_result = check_svg(path, stage=stage, icons_dir=icons_dir)
        visual_result.errors.extend(_ghb_chrome_errors(path, stage=stage))
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
        slide_id = str(page_schema.get("slide_id") or row.get("slide_id") or f"slide-{slide_number or len(page_quality_results) + 1}")
        try:
            page_quality = evaluate_page_quality(
                path.read_text(encoding="utf-8"),
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
    error_count = len(project_errors) + len(layout_issues)
    warning_count = len(deck_quality["findings"])
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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = check_project(args.project, stage=args.stage)
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
        for message in payload["layout_issues"] + payload["project_errors"]:
            print(f"  ERROR project: {message}")
        for finding in payload["visual_quality"]["deck_findings"]:
            print(f"  WARN deck: {finding['code']}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
