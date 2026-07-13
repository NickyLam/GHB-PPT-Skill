"""Check SVG deck layout diversity via data-layout markers."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


LAYOUT_RE = re.compile(r'data-layout="([^"]+)"')


def extract_layout_markers(svg_text: str) -> list[str]:
    """Return data-layout markers in the order they appear in one SVG file."""

    return LAYOUT_RE.findall(svg_text)


def analyze_layout_sequence(
    layouts: list[str],
    *,
    max_consecutive: int = 2,
    long_deck_threshold: int = 8,
    min_distinct_long_deck: int = 4,
) -> list[str]:
    """Return reader-facing layout-diversity issues for a deck sequence."""

    issues: list[str] = []
    if not layouts:
        return ["No data-layout markers found in SVG body slides."]

    run_layout = layouts[0]
    run_start = 0
    run_count = 1
    for idx, layout in enumerate(layouts[1:], start=1):
        if layout == run_layout:
            run_count += 1
            continue
        if run_count > max_consecutive:
            issues.append(
                f"Layout '{run_layout}' appears on more than {max_consecutive} consecutive slides "
                f"({run_start + 1}-{idx}); avoid three consecutive slides with the same layout."
            )
        run_layout = layout
        run_start = idx
        run_count = 1

    if run_count > max_consecutive:
        issues.append(
            f"Layout '{run_layout}' appears on more than {max_consecutive} consecutive slides "
            f"({run_start + 1}-{len(layouts)}); avoid three consecutive slides with the same layout."
        )

    distinct = sorted(set(layouts))
    if len(layouts) >= long_deck_threshold and len(distinct) < min_distinct_long_deck:
        issues.append(
            f"Deck has {len(layouts)} body slides but only {len(distinct)} distinct layout archetypes; "
            f"use at least {min_distinct_long_deck} distinct structure archetypes when content supports it."
        )

    return issues


def collect_project_layouts(project_dir: Path) -> list[str]:
    """Collect the primary layout marker from each SVG in project/svg_output."""

    svg_dir = project_dir / "svg_output"
    layouts: list[str] = []
    for path in sorted(svg_dir.glob("*.svg")):
        markers = extract_layout_markers(path.read_text(encoding="utf-8"))
        layouts.append(markers[0] if markers else "missing")
    return layouts


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SVG layout diversity for a PPT project.")
    parser.add_argument("project", type=Path, help="Project directory containing svg_output/*.svg")
    args = parser.parse_args()

    layouts = collect_project_layouts(args.project)
    issues = analyze_layout_sequence(layouts)
    if issues:
        for issue in issues:
            print(f"[layout-diversity] {issue}")
        return 1
    print(f"[layout-diversity] OK: {len(layouts)} slides, {len(set(layouts))} layout types")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
