"""Check SVG deck layout diversity via data-layout markers."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
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
                f"({run_start + 1}-{idx}); review whether the repetition is content-appropriate."
            )
        run_layout = layout
        run_start = idx
        run_count = 1

    if run_count > max_consecutive:
        issues.append(
            f"Layout '{run_layout}' appears on more than {max_consecutive} consecutive slides "
            f"({run_start + 1}-{len(layouts)}); review whether the repetition is content-appropriate."
        )

    distinct = sorted(set(layouts))
    if len(layouts) >= long_deck_threshold and len(distinct) < min_distinct_long_deck:
        issues.append(
            f"Deck has {len(layouts)} body slides but only {len(distinct)} distinct layout archetypes; "
            f"review whether additional structures are semantically justified; do not add diagrams only to meet a quota."
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


def main(argv: Sequence[str] | None = None) -> int:
    """Report diversity advice without turning optional layouts into a build gate.

    This is a GHB-local policy layered on the vendored SVG pipeline: missing
    layout metadata remains invalid, while repetition and quota findings are
    advisory because content semantics take precedence over visual variety.
    """
    parser = argparse.ArgumentParser(description="Check SVG layout diversity for a PPT project.")
    parser.add_argument("project", type=Path, help="Project directory containing svg_output/*.svg")
    args = parser.parse_args(argv)

    layouts = collect_project_layouts(args.project)
    if not layouts:
        print("[layout-diversity] ERROR: no SVG body slides found.")
        return 1
    missing = [index for index, layout in enumerate(layouts, start=1) if layout == "missing"]
    if missing:
        slides = ", ".join(str(index) for index in missing)
        print(f"[layout-diversity] ERROR: missing data-layout metadata on slide(s): {slides}")
        return 1

    issues = analyze_layout_sequence(layouts)
    if issues:
        for issue in issues:
            print(f"[layout-diversity] WARN: {issue}")
        return 0
    print(f"[layout-diversity] OK: {len(layouts)} slides, {len(set(layouts))} layout types")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
