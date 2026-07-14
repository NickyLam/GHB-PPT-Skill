#!/usr/bin/env python3
"""Build non-overwriting U11 before/after SVG and blind-review templates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CASES_PATH = Path(__file__).with_name("visual_quality_cases.json")
PREFERENCES_PATH = Path(__file__).with_name("visual_preferences.json")
SCENARIOS_PATH = Path(__file__).with_name("scenarios.json")
PRECHANGE_DIR = Path(__file__).with_name("visual_prechange_svg")

from scripts.ghb_visual_quality import measure_svg  # noqa: E402
from scripts.ppt_master.svg_layouts import LayoutSpec, render_layout  # noqa: E402


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _pilot_schema(case: dict[str, Any], slide: dict[str, Any]) -> dict[str, Any]:
    family = slide["layout_type"]
    density = "balanced" if case["density"] == "anchor" else case["density"]
    emphasis = "single-focal" if case["density"] == "anchor" else "ranked"
    schema = {
        "schema_version": 1,
        "page_purpose": case["page_purpose"],
        "layout_variant": "timeline/editorial" if family == "timeline" else "matrix/comparison",
        "density": density,
        "emphasis": emphasis,
        "budgets": {"max_items": 6 if family == "timeline" else 4, "max_chars_per_item": 80},
    }
    if emphasis in {"single-focal", "ranked"}:
        schema["focal_target"] = slide["items"][1]
    return schema


def _replace_layout(source: str, family: str, fragment: str) -> str:
    pattern = re.compile(rf'<g id="layout-{re.escape(family)}".*?</g>', re.DOTALL)
    result, count = pattern.subn(fragment, source, count=1)
    if count != 1:
        raise ValueError(f"pilot-layout-source-missing: {family}")
    return result


def build(output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite pilot artifacts: {output}")
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    preferences = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    pilot_cases = [case for case in cases["cases"] if case["partition"] == "pilot-holdout"]
    output.mkdir(parents=True)
    before_dir, after_dir, blind_dir = output / "before", output / "after", output / "blind"
    before_dir.mkdir()
    after_dir.mkdir()
    blind_dir.mkdir()
    eligible: list[dict[str, Any]] = []
    for case in pilot_cases:
        case_id = case["case_id"]
        frozen = PRECHANGE_DIR / f"{case_id}.svg"
        digest = hashlib.sha256(frozen.read_bytes()).hexdigest()
        if digest != case["pre_change_evidence"]["authored_svg_sha256"]:
            raise ValueError(f"frozen-before-digest-mismatch: {case_id}")
        shutil.copy2(frozen, before_dir / frozen.name)
        source = case["source"]
        slide = scenarios[source["scenario_id"]]["slides"][source["body_slide_index"] - 1]
        if slide["layout_type"] not in {"timeline", "matrix"}:
            continue
        schema = _pilot_schema(case, slide)
        fragment = render_layout(
            LayoutSpec(
                slide["layout_type"],
                slide["items"],
                x=100,
                y=240,
                width=1080,
                height=390,
                density=schema["density"],
                variant=schema["layout_variant"],
                emphasis=schema["emphasis"],
                focal_target=schema.get("focal_target"),
            )
        )
        after = _replace_layout(frozen.read_text(encoding="utf-8"), slide["layout_type"], fragment)
        after_path = after_dir / frozen.name
        after_path.write_text(after, encoding="utf-8")
        eligible.append(
            {
                "case_id": case_id,
                "page_purpose": case["page_purpose"],
                "family": slide["layout_type"],
                "page_schema": schema,
                "before_sha256": digest,
                "after_sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(),
                "metrics": measure_svg(after),
            }
        )
    assignments = []
    public_pairs = []
    for row in eligible:
        case_id = row["case_id"]
        a, b = f"{case_id}::A", f"{case_id}::B"
        pilot_left = int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % 2 == 0
        roles = {a: "pilot" if pilot_left else "baseline", b: "baseline" if pilot_left else "pilot"}
        case_blind_dir = blind_dir / case_id
        case_blind_dir.mkdir()
        role_sources = {
            "baseline": before_dir / f"{case_id}.svg",
            "pilot": after_dir / f"{case_id}.svg",
        }
        shutil.copy2(role_sources[roles[a]], case_blind_dir / "A.svg")
        shutil.copy2(role_sources[roles[b]], case_blind_dir / "B.svg")
        assignment = {
            "page_case_id": case_id,
            "page_purpose": row["page_purpose"],
            "masked_left_id": a,
            "masked_right_id": b,
            "roles": roles,
        }
        assignments.append(assignment)
        public_pairs.append(
            {
                key: value
                for key, value in assignment.items()
                if key != "roles"
            }
            | {
                "left_artifact": f"blind/{case_id}/A.svg",
                "right_artifact": f"blind/{case_id}/B.svg",
            }
        )
    eligible_case_ids = [row["case_id"] for row in eligible]
    review = {
        "schema": "ghb.visual-pilot-review.v1",
        "eligible_case_ids": eligible_case_ids,
        "pair_assignments": assignments,
        "judgments": [],
    }
    public_review = {
        "schema": "ghb.visual-pilot-blind-template.v1",
        "protocol": preferences["blind_review_protocol"],
        "eligible_case_ids": eligible_case_ids,
        "pairs": public_pairs,
        "judgment_template": {
            "reviewer_id_hash": "<stable-opaque-reviewer-id>",
            "page_case_id": "<page-case-id>",
            "masked_left_id": "<masked-left-id>",
            "masked_right_id": "<masked-right-id>",
            "presented_order": ["<masked-left-id>", "<masked-right-id>"],
            "judgment": "<masked-left-id|masked-right-id|tie|abstain>",
            "rubric": {dimension: "<1-5>" for dimension in preferences["blind_review_protocol"]["rubric_dimensions"]},
            "structural_veto": False,
            "recorded_at": "<ISO-8601 timestamp>",
        },
        "judgments": [],
    }
    deterministic = {
        "schema": "ghb.visual-pilot-deterministic.v1",
        "blocking_false_positives": [],
        "advisory_rule_case_results": [],
        "status": "pending-human-adjudication",
    }
    (output / "pilot-gate-review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "blind-review-template.json").write_text(json.dumps(public_review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "deterministic-audit-template.json").write_text(json.dumps(deterministic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema": "ghb.visual-pilot-artifacts.v1",
        "eligible_case_count": len(eligible),
        "eligible_cases": eligible,
        "frozen_preferences_sha256": _canonical_sha256(preferences),
        "decision": "pending",
        "reason": "real blind-review judgments and deterministic false-positive adjudication are required",
        "network": "not-used",
        "model_adapter": "not-used",
    }
    (output / "pilot-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
