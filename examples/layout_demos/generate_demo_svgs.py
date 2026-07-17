#!/usr/bin/env python3
"""Generate demo SVG pages for the extended business layout archetypes."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ppt_master.svg_layouts import LayoutSpec, render_layout  # noqa: E402
from scripts.validate_project_contract import confirmation_digest, default_visual_profile  # noqa: E402


CANVAS_W = 1280
CANVAS_H = 720


def page_schema(demo: dict[str, object], slide_id: str) -> dict[str, object]:
    legacy = str(demo["density"])
    density = {"anchor": "balanced", "dense": "dense", "breathing": "breathing"}[legacy]
    rhythm_role = {"anchor": "anchor", "dense": "continuity", "breathing": "transition"}[legacy]
    archetype = str(demo["layout_archetype"])
    purpose = {
        "funnel": "process",
        "flywheel": "process",
        "swimlane": "process",
        "iceberg": "summary",
    }[archetype]
    emphasis = "single-focal" if legacy == "anchor" else "distributed" if legacy == "dense" else "ranked"
    items = [str(item) for item in demo["items"]]
    result: dict[str, object] = {
        "schema": "ghb.page-schema.v1",
        "slide_id": slide_id,
        "page_purpose": purpose,
        "layout_variant": f"{archetype}/default",
        "density": density,
        "rhythm_role": rhythm_role,
        "emphasis": emphasis,
        "budgets": {"max_text_chars": min(240, 80 + sum(map(len, items))), "max_nodes": len(items)},
    }
    if emphasis == "single-focal":
        result["focal_target"] = "primary-structure"
    return result


DEMOS = [
    {
        "file": "01_funnel.svg",
        "title": "Conversion Funnel",
        "part": "Demo 01",
        "message": "Show narrowing movement from reach to repeat purchase.",
        "layout_archetype": "funnel",
        "density": "anchor",
        "items": ["Reach", "Activate", "Convert", "Repeat"],
        "reason": "The message is about staged narrowing, so a funnel is the clearest structure.",
        "alternatives": ["waterfall", "pyramid"],
    },
    {
        "file": "02_flywheel.svg",
        "title": "Growth Flywheel",
        "part": "Demo 02",
        "message": "Show a reinforcing loop where each stage strengthens the next.",
        "layout_archetype": "flywheel",
        "density": "breathing",
        "items": ["Acquire", "Activate", "Deliver", "Refer"],
        "reason": "The page describes a loop, so the structure must read as circular instead of linear.",
        "alternatives": ["timeline", "waterfall"],
    },
    {
        "file": "03_swimlane.svg",
        "title": "Cross-Team Swimlane",
        "part": "Demo 03",
        "message": "Show business, platform, and engineering coordination across shared stages.",
        "layout_archetype": "swimlane",
        "density": "dense",
        "items": ["Business", "Platform", "Engineering"],
        "reason": "The content is role by process, so a swimlane grid is more faithful than cards.",
        "alternatives": ["matrix", "waterfall"],
    },
    {
        "file": "04_iceberg.svg",
        "title": "Issue Iceberg",
        "part": "Demo 04",
        "message": "Separate visible symptoms from deeper structural constraints.",
        "layout_archetype": "iceberg",
        "density": "anchor",
        "items": ["Visible Delay", "Missed SLA", "Manual Routing", "Legacy Rules"],
        "reason": "The slide contrasts surface issues with hidden causes, which is the core iceberg pattern.",
        "alternatives": ["layered_arch", "pyramid"],
    },
]


def build_page(index: int, demo: dict[str, object]) -> str:
    fragment = render_layout(
        LayoutSpec(
            archetype=str(demo["layout_archetype"]),
            items=[str(item) for item in demo["items"]],
            title="",
            x=140,
            y=280,
            width=1000,
            height=310,
        )
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_W}" height="{CANVAS_H}" viewBox="0 0 {CANVAS_W} {CANVAS_H}">
  <g id="bg"><rect width="{CANVAS_W}" height="{CANVAS_H}" fill="#FFFFFF"/></g>
  <g id="bg-surface">
    <rect x="56" y="96" width="1168" height="608" rx="12" fill="#FFFFFF" fill-opacity="0.92" stroke="#E0E0E0" stroke-width="1"/>
  </g>
  <g id="header">
    <rect x="88" y="132" width="6" height="40" fill="#AB1F29"/>
    <text x="108" y="162" font-size="30" font-weight="bold" fill="#2B2B2B" font-family="'Arial Black', 'Source Han Sans SC', 'Microsoft YaHei', Arial, sans-serif">Extended Layout Demo</text>
    <line x1="88" y1="190" x2="1192" y2="190" stroke="#E0E0E0" stroke-width="1"/>
    <text x="1192" y="162" text-anchor="end" font-size="14" fill="#AB1F29" font-family="'Source Han Sans SC', 'Microsoft YaHei', Arial, sans-serif">{demo["part"]}</text>
  </g>
  <g id="content-lead">
    <text x="140" y="228" font-size="24" font-weight="bold" fill="#2B2B2B" font-family="'Source Han Sans SC', 'Microsoft YaHei', Arial, sans-serif">{demo["title"]}</text>
    <text x="140" y="255" font-size="18" fill="#6E6E73" font-family="'Source Han Sans SC', 'Microsoft YaHei', Arial, sans-serif">{demo["message"]}</text>
  </g>
  {fragment}
  <g id="footer">
    <text x="1192" y="696" text-anchor="end" font-size="13" fill="#999999" font-family="'Source Han Sans SC', 'Microsoft YaHei', Arial, sans-serif">{index:02d} / 04</text>
  </g>
</svg>
"""


def main() -> int:
    output_dir = Path(__file__).resolve().parent
    svg_dir = output_dir / "svg_output"
    svg_dir.mkdir(parents=True, exist_ok=True)

    layout_plan = []
    claims = []
    for index, demo in enumerate(DEMOS, start=1):
        svg_path = svg_dir / str(demo["file"])
        svg_path.write_text(build_page(index, demo), encoding="utf-8")
        claim_id = f"claim-{index:02d}"
        claims.append(
            {
                "id": claim_id,
                "statement": demo["message"],
                "must_include": True,
                "source_reference": f"sources/source.md#{index}",
            }
        )
        row = {
                "slide": index,
                "slide_id": f"body-{index:02d}",
                "purpose": demo["title"],
                "key_message": demo["message"],
                "message": demo["message"],
                "audience": "layout-component maintainers",
                "content_density": demo["density"],
                "rhythm": demo["density"],
                "layout_type": demo["layout_archetype"],
                "layout_archetype": demo["layout_archetype"],
                "density": demo["density"],
                "visual_encoding": demo["reason"],
                "editable_elements": ["title", "labels", "shapes"],
                "image_requirement": "none",
                "source_reference": f"sources/source.md#{index}",
                "speaker_note": demo["message"],
                "items": demo["items"],
                "reason": demo["reason"],
                "alternatives": demo["alternatives"],
                "claim_ids": [claim_id],
                "page_schema": page_schema(demo, f"body-{index:02d}"),
            }
        if demo["layout_archetype"] == "flywheel":
            row["loop_closure"] = "Refer strengthens Acquire"
        elif demo["layout_archetype"] == "swimlane":
            row["owners"] = demo["items"]
        layout_plan.append(row)

    (output_dir / "layout_plan.json").write_text(
        json.dumps(layout_plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "visual_profile.json").write_text(
        json.dumps(default_visual_profile(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    sources_dir = output_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "source.md").write_text(
        "# Extended Layout Demo\n\n" + "\n".join(
            f"## {index}. {demo['message']}" for index, demo in enumerate(DEMOS, start=1)
        ) + "\n",
        encoding="utf-8",
    )
    (output_dir / "design_spec.md").write_text(
        "# Design Spec\n\nAudience: layout-component maintainers\nMode: instructional\nAssets: none\n",
        encoding="utf-8",
    )
    (output_dir / "spec_lock.md").write_text(
        "canvas: 1280x720\nmode: instructional\ncolors: GHB\ntypography: Office-safe\n",
        encoding="utf-8",
    )
    (output_dir / "content_model.json").write_text(
        json.dumps({"schema": "ghb.content-model.v1", "claims": claims}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    confirmation = {
                "schema": "ghb.confirmation.v1",
                "status": "confirmed",
                "confirmation_source": "fixture",
                "confirmed_at": "2026-07-13T00:00:00Z",
                "decisions": {
                    "audience": "layout-component maintainers",
                    "page_range": "4 body slides",
                    "mode": "instructional",
                    "outline": [
                        {"title": demo["message"], "rhythm": demo["density"]}
                        for demo in DEMOS
                    ],
                    "content_tradeoffs": {"expand": [], "omit": [], "combine": []},
                    "visual_assets": {"image_source": "none", "icon_set": "none"},
                },
            }
    confirmation["decision_digest"] = confirmation_digest(confirmation["decisions"])
    (output_dir / "confirmation.json").write_text(
        json.dumps(
            confirmation,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
