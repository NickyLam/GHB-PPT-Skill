#!/usr/bin/env python3
"""Run the complete authored/finalized SVG quality gate as one JSON-capable check."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "ppt_master"))
from scripts.ppt_master.check_layout_diversity import (  # noqa: E402
    analyze_layout_sequence,
    extract_layout_markers,
)


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
        }

    icons_dir = Path(__file__).resolve().parents[1] / "templates" / "icons"
    checker = SVGQualityChecker()
    visual_results = []
    layouts: list[str] = []
    file_payloads: list[dict[str, object]] = []
    for path in files:
        svg_result = checker.check_file(str(path), "ppt169")
        visual_result = check_svg(path, stage=stage, icons_dir=icons_dir)
        visual_result.errors.extend(_ghb_chrome_errors(path, stage=stage))
        visual_results.append(visual_result)
        markers = extract_layout_markers(path.read_text(encoding="utf-8"))
        layouts.append(markers[0] if markers else "missing")
        file_payloads.append(
            {
                "file": str(path),
                "layout": visual_result.layout,
                "text_chars": visual_result.text_chars,
                "text_elements": visual_result.text_elements,
                "svg_quality_errors": svg_result["errors"],
                "svg_quality_warnings": svg_result["warnings"],
                "visual_errors": visual_result.errors,
                "visual_warnings": visual_result.warnings,
            }
        )

    plan_path = project / "layout_plan.json"
    project_errors = _apply_content_plan(visual_results, plan_path if plan_path.is_file() else None)
    # _apply_content_plan mutates visual results; refresh those fields.
    for payload, visual_result in zip(file_payloads, visual_results):
        payload["visual_errors"] = visual_result.errors
        payload["visual_warnings"] = visual_result.warnings
    layout_issues = analyze_layout_sequence(layouts)
    error_count = len(project_errors) + len(layout_issues)
    warning_count = 0
    for payload in file_payloads:
        error_count += len(payload["svg_quality_errors"]) + len(payload["visual_errors"])
        warning_count += len(payload["svg_quality_warnings"]) + len(payload["visual_warnings"])
    return {
        "passed": error_count == 0,
        "stage": stage,
        "svg_dir": str(svg_dir),
        "files": file_payloads,
        "layouts": layouts,
        "layout_issues": layout_issues,
        "project_errors": project_errors,
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
        for message in payload["layout_issues"] + payload["project_errors"]:
            print(f"  ERROR project: {message}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
