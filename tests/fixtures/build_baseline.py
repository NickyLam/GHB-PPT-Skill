#!/usr/bin/env python3
"""Build deterministic, offline, pre-change GHB baseline artifacts."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = Path(__file__).with_name("scenarios.json")
TEMPLATE = ROOT / "templates" / "GHB_PPT_模板.pptx"
PM = ROOT / "scripts" / "ppt_master"
BG_PATTERN = re.compile(
    r'<g id="bg">\s*<rect[^>]*/>\s*</g>\s*\n?',
    re.DOTALL,
)
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def run(command: list[str], log: list[dict[str, object]]) -> None:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    log.append(
        {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )


def xml_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_project(case_dir: Path, scenario: dict[str, object], slides: list[dict[str, object]]) -> None:
    for name in ("sources", "analysis", "svg_output", "svg_final", "notes", "exports"):
        (case_dir / name).mkdir(parents=True, exist_ok=True)

    source_lines = [f"# {scenario['title']}", "", f"> {scenario['subtitle']}", ""]
    plan: list[dict[str, object]] = []
    notes: list[str] = []
    total = len(slides)
    for index, slide in enumerate(slides, 1):
        title = str(slide["key_message"])
        items = [str(item) for item in slide["items"]]
        source_lines.extend([f"## {index}. {title}", "", *[f"- {item}" for item in items], ""])
        plan.append(
            {
                "slide": index,
                "slide_id": f"body-{index:02d}",
                "purpose": slide["purpose"],
                "key_message": title,
                "audience": scenario["audience"],
                "content_density": slide["density"],
                "density": slide["density"],
                "rhythm": slide["density"],
                "layout_type": slide["layout_type"],
                "layout_archetype": slide["layout_type"],
                "visual_encoding": slide["visual_encoding"],
                "editable_elements": ["title", "labels", "shapes"],
                "image_requirement": "none",
                "source_reference": f"source.md#{index}",
                "speaker_note": f"说明第 {index} 页的关键结论。",
                "items": items,
                "reason": f"{slide['visual_encoding']} 与本页信息关系匹配",
                "alternatives": ["timeline", "layered_arch"],
            }
        )
        notes.extend([f"# {index:02d}_{slide['layout_type']}", f"说明：{title}", "", "---", ""])
        write_svg(case_dir / "svg_output" / f"{index:02d}_{slide['layout_type']}.svg", index, total, slide)

    (case_dir / "sources" / "source.md").write_text("\n".join(source_lines), encoding="utf-8")
    (case_dir / "layout_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "design_spec.md").write_text(
        f"# Design Spec\n\nAudience: {scenario['audience']}\n\nOffline fixture: true\n",
        encoding="utf-8",
    )
    (case_dir / "notes" / "total.md").write_text("\n".join(notes), encoding="utf-8")


def write_svg(path: Path, index: int, total: int, slide: dict[str, object]) -> None:
    title = xml_text(str(slide["key_message"]))
    layout = xml_text(str(slide["layout_type"]))
    items = [str(item) for item in slide["items"]]
    box_count = max(len(items), 1)
    gap = 16
    width = (1080 - gap * (box_count - 1)) / box_count
    item_xml: list[str] = []
    for item_index, item in enumerate(items):
        x = 100 + item_index * (width + gap)
        fill = "#AB1F29" if item_index == box_count - 1 else "#F6F6F7"
        text_fill = "#FFFFFF" if item_index == box_count - 1 else "#2B2B2B"
        item_xml.append(
            f'<rect x="{x:.1f}" y="300" width="{width:.1f}" height="150" rx="10" '
            f'fill="{fill}" stroke="#E0E0E0" stroke-width="1"/>'
        )
    if slide.get("use_icon"):
        item_xml.append(
            '<use id="fixture-icon" data-icon="tabler-outline/target" '
            'x="1110" y="220" width="40" height="40" fill="#AB1F29"/>'
        )
        item_xml.append(
            f'<text x="{x + width / 2:.1f}" y="382" text-anchor="middle" font-size="18" '
            f'font-family="Microsoft YaHei, Arial, sans-serif" fill="{text_fill}">{xml_text(item)}</text>'
        )
    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <g id="bg"><rect width="1280" height="720" fill="#FFFFFF"/></g>
  <g id="bg-surface"><rect x="56" y="96" width="1168" height="608" rx="12" fill="#FFFFFF" fill-opacity="0.92" stroke="#E0E0E0"/></g>
  <g id="header"><rect x="88" y="132" width="6" height="40" fill="#AB1F29"/><text x="108" y="162" font-size="30" font-weight="bold" font-family="Arial Black, Microsoft YaHei, Arial, sans-serif" fill="#2B2B2B">{title}</text></g>
  <g id="content" data-layout="{layout}">{''.join(item_xml)}</g>
  <g id="footer"><text x="1192" y="696" text-anchor="end" font-size="13" font-family="Microsoft YaHei, Arial, sans-serif" fill="#999999">{index:02d} / {total:02d}</text></g>
</svg>\n''',
        encoding="utf-8",
    )


def make_cover(case_dir: Path, scenario: dict[str, object], log: list[dict[str, object]]) -> Path:
    library = case_dir / "analysis" / "slide_library.json"
    plan = case_dir / "analysis" / "cover_fill_plan.json"
    requested = case_dir / "exports" / "cover.pptx"
    run([sys.executable, str(PM / "template_fill_pptx.py"), "analyze", str(TEMPLATE), "-o", str(library)], log)
    plan.write_text(
        json.dumps(
            {
                "schema": "template_fill_pptx_plan.v1",
                "slides": [
                    {
                        "source_slide": 1,
                        "purpose": "封面",
                        "replacements": [
                            {"slot_id": "s01_sh8", "text": scenario["title"]},
                            {"slot_id": "s01_sh6", "text": scenario["subtitle"]},
                            {"slot_id": "s01_sh4", "text": scenario["date"]}
                        ]
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    run([sys.executable, str(PM / "template_fill_pptx.py"), "apply", str(TEMPLATE), str(plan), "-o", str(requested), "--transition", "none"], log)
    candidates = sorted(requested.parent.glob("cover_????????_??????.pptx"))
    if not candidates:
        raise RuntimeError("template-fill did not produce a timestamped cover")
    shutil.move(candidates[-1], requested)
    run([sys.executable, str(ROOT / "scripts" / "fix_cover_font.py"), str(requested)], log)
    return requested


def remove_backgrounds(case_dir: Path) -> None:
    shutil.copytree(case_dir / "svg_output", case_dir / "svg_output_original")
    for path in sorted((case_dir / "svg_output").glob("*.svg")):
        original = path.read_text(encoding="utf-8")
        updated, count = BG_PATTERN.subn("", original, count=1)
        if count != 1:
            raise RuntimeError(f"expected one removable background in {path}")
        path.write_text(updated, encoding="utf-8")


def resolve_target(source_part: str, target: str) -> str:
    source_dir = PurePosixPath(source_part).parent
    return str((source_dir / target)) if not target.startswith("/") else target.lstrip("/")


def summarize_pptx(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        name_set = set(names)
        dangling: list[str] = []
        duplicate_rids: dict[str, list[str]] = {}
        for rels_name in sorted(name for name in names if name.endswith(".rels")):
            root = ET.fromstring(archive.read(rels_name))
            ids = [rel.get("Id", "") for rel in root]
            duplicates = sorted({rid for rid in ids if ids.count(rid) > 1})
            if duplicates:
                duplicate_rids[rels_name] = duplicates
            if "/_rels/" in rels_name:
                prefix, rel_file = rels_name.split("/_rels/", 1)
                source_part = f"{prefix}/{rel_file[:-5]}"
            else:
                source_part = rel_file[:-5] if (rel_file := rels_name.split("_rels/", 1)[-1]) else ""
            for rel in root:
                if rel.get("TargetMode") == "External":
                    continue
                target = rel.get("Target", "")
                normalized = posixpath.normpath(
                    posixpath.join(posixpath.dirname(source_part), target)
                )
                if normalized not in name_set:
                    dangling.append(f"{rels_name} -> {target}")

        pres = ET.fromstring(archive.read("ppt/presentation.xml"))
        slide_ids = [node.get("id") for node in pres.findall(f".//{{{P_NS}}}sldId")]
        slide_layout_targets: dict[str, str] = {}
        for name in sorted((n for n in names if re.fullmatch(r"ppt/slides/_rels/slide\d+\.xml\.rels", n)), key=lambda n: int(re.search(r"slide(\d+)", n).group(1))):
            rels = ET.fromstring(archive.read(name))
            target = next((rel.get("Target", "") for rel in rels if rel.get("Type", "").endswith("/slideLayout")), "")
            slide_layout_targets[name] = target
        master_layout_targets: dict[str, list[str]] = {}
        for name in sorted(n for n in names if re.fullmatch(r"ppt/slideMasters/_rels/slideMaster\d+\.xml\.rels", n)):
            rels = ET.fromstring(archive.read(name))
            master_layout_targets[name] = [rel.get("Target", "") for rel in rels if rel.get("Type", "").endswith("/slideLayout")]
        return {
            "file": str(path),
            "size": path.stat().st_size,
            "part_count": len(names),
            "slide_count": len(slide_ids),
            "slide_ids": slide_ids,
            "duplicate_slide_ids": sorted({sid for sid in slide_ids if slide_ids.count(sid) > 1}),
            "duplicate_relationship_ids": duplicate_rids,
            "dangling_relationships": dangling,
            "slide_layout_targets": slide_layout_targets,
            "master_layout_targets": master_layout_targets,
            "media": sorted(name for name in names if name.startswith("ppt/media/")),
        }


def build_case(output_root: Path, name: str, scenario: dict[str, object], slides: list[dict[str, object]], merge_args: list[str]) -> None:
    case_dir = output_root / name
    if case_dir.exists():
        raise FileExistsError(f"baseline output already exists: {case_dir}")
    log: list[dict[str, object]] = []
    write_project(case_dir, scenario, slides)
    cover = make_cover(case_dir, scenario, log)
    run([sys.executable, str(PM / "svg_quality_checker.py"), str(case_dir), "--format", "ppt169"], log)
    run([sys.executable, str(PM / "visual_asset_checker.py"), str(case_dir), "--stage", "authored", "--json"], log)
    remove_backgrounds(case_dir)
    run([sys.executable, str(PM / "total_md_split.py"), str(case_dir)], log)
    run([sys.executable, str(PM / "finalize_svg.py"), str(case_dir)], log)
    run([sys.executable, str(PM / "visual_asset_checker.py"), str(case_dir), "--stage", "finalized", "--json"], log)
    content = case_dir / "exports" / "content.pptx"
    run([sys.executable, str(PM / "svg_to_pptx.py"), str(case_dir), "-o", str(content), "--animation", "none", "--transition", "none"], log)
    final = case_dir / "exports" / "final.pptx"
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "merge_template_master.py"),
            "--content", str(content),
            "--template", str(TEMPLATE),
            "--cover", str(cover),
            "--content-layout", "2",
            "--output", str(final),
            *merge_args,
        ],
        log,
    )
    summary = summarize_pptx(final)
    (case_dir / "ooxml-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "commands.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "baseline" / "before",
    )
    parser.add_argument(
        "--append-icon-case",
        action="store_true",
        help="Append only the D icon/media regression case to an existing baseline root.",
    )
    args = parser.parse_args()
    if args.append_icon_case:
        args.output.mkdir(parents=True, exist_ok=True)
        scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
        d_source = scenarios["technical_sharing"]
        icon_slides = [dict(slide) for slide in d_source["slides"][:3]]
        icon_slides[0]["use_icon"] = True
        build_case(args.output, "D_03_body_with_icon", d_source, icon_slides, [])
        print(f"Icon baseline appended to {args.output}")
        return 0
    if args.output.exists():
        print(f"Refusing to overwrite baseline directory: {args.output}", file=sys.stderr)
        return 2
    args.output.mkdir(parents=True)
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    build_case(args.output, "A_technical_sharing", scenarios["technical_sharing"], scenarios["technical_sharing"]["slides"], [])
    build_case(args.output, "B_management_plan", scenarios["management_plan"], scenarios["management_plan"]["slides"], [])
    build_case(args.output, "C_layout_stress", scenarios["layout_stress"], scenarios["layout_stress"]["slides"], [])

    d_source = scenarios["technical_sharing"]
    d_slides = d_source["slides"]
    for count in (1, 3, 10):
        expanded = [dict(d_slides[index % len(d_slides)]) for index in range(count)]
        build_case(args.output, f"D_{count:02d}_body_default_ending", d_source, expanded, [])
    build_case(args.output, "D_03_body_no_ending", d_source, d_slides[:3], ["--no-ending"])
    build_case(args.output, "D_03_body_explicit_ending", d_source, d_slides[:3], ["--ending-slide", "4"])
    icon_slides = [dict(slide) for slide in d_slides[:3]]
    icon_slides[0]["use_icon"] = True
    build_case(args.output, "D_03_body_with_icon", d_source, icon_slides, [])

    print(f"Baseline written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
