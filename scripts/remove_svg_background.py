#!/usr/bin/env python3
"""Remove the explicit full-canvas ``<g id="bg">`` preview background.

The native SVG-to-PPTX converter reads ``svg_output/``.  Removing this preview
background makes body slides transparent so the injected GHB master can show
through.  The operation is deterministic and idempotent; unrelated groups and
non-white/non-full-canvas backgrounds are rejected rather than guessed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


WHITE_VALUES = {"#fff", "#ffffff", "white", "rgb(255,255,255)"}
GROUP_RE = re.compile(
    r"<g\b(?P<attrs>[^>]*)\bid\s*=\s*(?P<quote>['\"])bg(?P=quote)[^>]*>"
    r"(?P<body>.*?)</g>\s*",
    re.IGNORECASE | re.DOTALL,
)


class BackgroundRemovalError(ValueError):
    """Raised when a declared ``bg`` group is unsafe or ambiguous to remove."""


@dataclass(frozen=True)
class RemovalResult:
    path: str
    status: str
    backup: str | None = None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:px)?\s*", value)
    return float(match.group(1)) if match else None


def _validate_background_group(text: str, path: Path) -> str:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise BackgroundRemovalError(f"{path}: invalid SVG XML: {exc}") from exc

    viewbox = [_number(part) for part in re.split(r"[\s,]+", root.get("viewBox", "").strip())]
    if len(viewbox) != 4 or any(value is None for value in viewbox):
        raise BackgroundRemovalError(f"{path}: missing or invalid viewBox")
    vb_x, vb_y, vb_w, vb_h = (float(value) for value in viewbox)

    groups = [element for element in root if _local_name(element.tag) == "g" and element.get("id") == "bg"]
    if not groups:
        return "absent"
    if len(groups) != 1:
        raise BackgroundRemovalError(f"{path}: expected one top-level <g id='bg'>, found {len(groups)}")

    group = groups[0]
    children = list(group)
    if len(children) != 1 or _local_name(children[0].tag) != "rect":
        raise BackgroundRemovalError(f"{path}: bg group must contain exactly one rect")
    rect = children[0]
    x = _number(rect.get("x")) or 0.0
    y = _number(rect.get("y")) or 0.0
    width = _number(rect.get("width"))
    height = _number(rect.get("height"))
    fill = (rect.get("fill") or "").replace(" ", "").lower()
    if width is None or height is None:
        raise BackgroundRemovalError(f"{path}: bg rect needs numeric width and height")
    if any(abs(left - right) > 0.5 for left, right in ((x, vb_x), (y, vb_y), (width, vb_w), (height, vb_h))):
        raise BackgroundRemovalError(f"{path}: bg rect does not cover the full viewBox")
    if fill not in WHITE_VALUES:
        raise BackgroundRemovalError(f"{path}: bg rect is not white (fill={fill!r})")
    return "removable"


def remove_background(path: Path, *, backup_dir: Path | None = None, dry_run: bool = False) -> RemovalResult:
    text = path.read_text(encoding="utf-8")
    state = _validate_background_group(text, path)
    if state == "absent":
        return RemovalResult(str(path), "already-absent")

    matches = list(GROUP_RE.finditer(text))
    if len(matches) != 1:
        raise BackgroundRemovalError(
            f"{path}: XML contains a removable bg group but source matching found {len(matches)} candidates"
        )
    if dry_run:
        return RemovalResult(str(path), "would-remove")

    backup: Path | None = None
    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / path.name
        if not backup.exists():
            shutil.copy2(path, backup)
    match = matches[0]
    path.write_text(text[: match.start()] + text[match.end() :], encoding="utf-8")
    return RemovalResult(str(path), "removed", str(backup) if backup else None)


def remove_project_backgrounds(
    project: Path,
    *,
    svg_dir_name: str = "svg_output",
    backup_dir: Path | None = None,
    dry_run: bool = False,
) -> list[RemovalResult]:
    if not svg_dir_name or Path(svg_dir_name).name != svg_dir_name:
        raise BackgroundRemovalError("svg_dir_name must be one project-local directory name")
    svg_dir = project / svg_dir_name
    if not svg_dir.is_dir():
        raise BackgroundRemovalError(f"{svg_dir_name} directory not found: {svg_dir}")
    files = sorted(svg_dir.glob("*.svg"))
    if not files:
        raise BackgroundRemovalError(f"no SVG files found: {svg_dir}")
    return [remove_background(path, backup_dir=backup_dir, dry_run=dry_run) for path in files]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="SVG file or project directory")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument(
        "--svg-dir-name",
        default="svg_output",
        help="Project-local SVG directory to modify (default: svg_output)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.target.is_file():
            results = [remove_background(args.target, backup_dir=args.backup_dir, dry_run=args.dry_run)]
        else:
            results = remove_project_backgrounds(
                args.target,
                svg_dir_name=args.svg_dir_name,
                backup_dir=args.backup_dir,
                dry_run=args.dry_run,
            )
    except (OSError, BackgroundRemovalError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f"[{result.status}] {result.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
